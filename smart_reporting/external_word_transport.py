"""Single-process Word Harness adapter for explicitly configured private tests.

The host supplies authenticated subjects and serves the per-task ASGI app.
Invitation references are secrets and must be delivered out of band.
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


def _denied() -> ValueError:
    return ValueError("external_word_access_unavailable")


@dataclass(frozen=True)
class WordAccess:
    task_id: str
    ticket: str = field(repr=False)
    instruction: str = field(repr=False)


@dataclass
class _Invitation:
    subject: str
    digest: bytes
    expires_at: float
    result: asyncio.Event = field(default_factory=asyncio.Event)
    access: WordAccess | None = None
    app: Any = None
    proposal: Callable[[], dict | None] | None = None
    redeemed: bool = False
    completed: bool = False


class ExternalWordTransport:
    """Run on the same event loop as the dispatcher and the private ASGI host."""

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._pending: dict[str, _Invitation] = {}
        self._references: dict[bytes, str] = {}

    def invite(self, *, task_id: str, subject: str) -> str:
        for expired_task, invitation in list(self._pending.items()):
            if self._clock() >= invitation.expires_at:
                self.revoke(expired_task)
        if not task_id or not subject or task_id in self._pending:
            raise _denied()
        reference = secrets.token_urlsafe(32)
        digest = hashlib.sha256(reference.encode()).digest()
        self._pending[task_id] = _Invitation(subject, digest, self._clock() + 60)
        self._references[digest] = task_id
        return reference

    def _live(self, task_id: str) -> _Invitation:
        invitation = self._pending.get(task_id)
        if invitation is None:
            raise _denied()
        if self._clock() >= invitation.expires_at:
            self.revoke(task_id)
            raise _denied()
        return invitation

    def redeem(self, reference: str, *, subject: str) -> WordAccess:
        task_id = self._references.get(hashlib.sha256(reference.encode()).digest())
        if task_id is None:
            raise _denied()
        invitation = self._live(task_id)
        if invitation.subject != subject or invitation.access is None:
            raise _denied()
        invitation.redeemed = True
        self._references.pop(invitation.digest)
        return invitation.access

    def app_for_task(self, task_id: str, *, subject: str):
        invitation = self._live(task_id)
        if not invitation.redeemed or invitation.subject != subject or invitation.completed:
            raise _denied()
        return invitation.app

    def assert_authorized(self, task_id: str, *, ticket: str) -> None:
        invitation = self._live(task_id)
        if not invitation.redeemed or invitation.access is None or invitation.access.ticket != ticket:
            raise _denied()

    def complete(self, task_id: str, *, subject: str) -> None:
        self.app_for_task(task_id, subject=subject)
        invitation = self._live(task_id)
        if invitation.proposal is None or invitation.proposal() is None:
            raise _denied()
        invitation.completed = True
        invitation.result.set()

    def is_pending_candidate(self, task_id: str, *, ticket: str) -> bool:
        self.assert_authorized(task_id, ticket=ticket)
        proposal = self._live(task_id).proposal
        return proposal is None or proposal() is None

    def revoke(self, task_id: str, *, ticket: str | None = None) -> None:
        current = self._pending.get(task_id)
        if ticket is not None and (current is None or current.access is None or current.access.ticket != ticket):
            return
        invitation = self._pending.pop(task_id, None)
        if invitation is not None:
            self._references.pop(invitation.digest, None)
            invitation.result.set()

    async def run(self, *, server, ticket, task_id, instruction, registered_proposal):
        invitation = self._live(task_id)
        if invitation.access is not None:
            raise _denied()
        try:
            invitation.app = server.http_app(transport="streamable-http", stateless_http=True)
            invitation.access = WordAccess(task_id, ticket, instruction)
            invitation.proposal = registered_proposal
            try:
                await asyncio.wait_for(invitation.result.wait(), invitation.expires_at - self._clock())
            except TimeoutError:
                raise _denied() from None
            self.assert_authorized(task_id, ticket=ticket)
            if not invitation.completed:
                raise _denied()
            return registered_proposal()
        finally:
            # Keep the successfully exchanged authorization live for reconciliation.
            if not invitation.completed:
                self.revoke(task_id, ticket=ticket)
