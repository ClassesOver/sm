"""Bind a private ACP conversation to an authenticated report-channel grant."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from typing import TYPE_CHECKING

from .report_acp_client import ReportAcpClient
from .report_channel_repository import ReportChannelRepository

if TYPE_CHECKING:
    from .report_channel_api import ConnectorIdentity


class ReportChannelAcpDenied(PermissionError):
    pass


class ReportChannelAcpConflict(ValueError):
    pass


class ReportChannelAcpCapacity(RuntimeError):
    pass


class ReportChannelAcp:
    """Accept identities resolved by the host's existing channel authenticator."""

    def __init__(
        self, repository: ReportChannelRepository, client_factory: Callable[[], ReportAcpClient],
        *, durable: bool = False,
    ):
        self._repository = repository
        self._client_factory = client_factory
        self._durable = durable

    async def bind(self, channel: str, identity: ConnectorIdentity) -> "ReportAcpConversation":
        grant = await self._repository.member_grant(channel, identity)
        if grant is None:
            raise ReportChannelAcpDenied("Report channel membership required")
        if self._durable and not await self._repository.enable_acp_binding(grant):
            raise ReportChannelAcpDenied("Report channel membership required")
        return ReportAcpConversation(self, channel, identity, grant)

    async def restore(self, channel: str, identity: ConnectorIdentity) -> ReportAcpConversation | None:
        if not self._durable:
            return None
        grant = await self._repository.member_grant(channel, identity)
        if grant is None or await self._repository.acp_binding(grant) is None:
            return None
        return ReportAcpConversation(self, channel, identity, grant)


class ReportAcpConversation:
    def __init__(
        self, bridge: ReportChannelAcp, channel: str, identity: ConnectorIdentity, grant: str,
    ):
        self._bridge = bridge
        self._channel = channel
        self._identity = identity
        self._grant = grant
        self._session_id: str | None = None
        self._lock = asyncio.Lock()
        self._receipts: dict[str, tuple[bytes, str | None]] = {}

    def matches_binding(self, other: ReportAcpConversation) -> bool:
        return (
            self._bridge is other._bridge
            and self._channel == other._channel
            and self._identity == other._identity
            and self._grant == other._grant
        )

    async def _authorize(self, identity: ConnectorIdentity):
        if identity != self._identity:
            raise ReportChannelAcpDenied("Report channel membership required")
        grant = await self._bridge._repository.member_grant(self._channel, identity)
        if grant != self._grant:
            raise ReportChannelAcpDenied("Report channel membership required")

    async def _prompt_while_authorized(self, client, identity, text: str) -> str:
        # A revoked grant must stop an in-flight local ACP subprocess, not just
        # suppress its eventual reply. The final authorization check remains.
        turn = asyncio.create_task(client.prompt(text))
        try:
            while True:
                done, _ = await asyncio.wait({turn}, timeout=0.5)
                await self._authorize(identity)
                if done:
                    return await turn
        finally:
            if not turn.done():
                turn.cancel()
                try:
                    await turn
                except asyncio.CancelledError:
                    pass

    async def prompt(self, identity: ConnectorIdentity, text: str, *, message_id: str) -> str:
        if not text.strip() or len(text) > 8000:
            raise ValueError("Report message must contain between 1 and 8000 characters")
        digest = hashlib.sha256(text.encode()).digest()
        if self._bridge._durable:
            return await self._persistent_prompt(identity, text, message_id, digest.hex())
        async with self._lock:
            await self._authorize(identity)
            if receipt := self._receipts.get(message_id):
                previous_digest, reply = receipt
                if previous_digest != digest:
                    raise ReportChannelAcpConflict("report_channel_acp_message_conflict")
                if reply is None:
                    raise ReportChannelAcpConflict("report_channel_acp_outcome_unknown")
                return reply
            if len(self._receipts) >= 128:
                raise ReportChannelAcpCapacity("report_channel_acp_conversation_full")
            async with self._bridge._client_factory() as client:
                self._session_id = await client.open_session(resume=self._session_id)
                await self._authorize(identity)
                # If delivery fails after submission, do not run the same turn again.
                self._receipts[message_id] = (digest, None)
                reply = await self._prompt_while_authorized(client, identity, text)
            # Do not disclose a reply after revocation, including during process shutdown.
            await self._authorize(identity)
            self._receipts[message_id] = (digest, reply)
            return reply

    async def _persistent_prompt(
        self, identity: ConnectorIdentity, text: str, message_id: str, request_digest: str,
    ) -> str:
        repository = self._bridge._repository
        await self._authorize(identity)
        async with repository.acp_turn_lock(self._grant) as locked:
            if not locked:
                raise ReportChannelAcpConflict("report_channel_acp_turn_in_progress")
            await self._authorize(identity)
            receipt = await repository.acp_receipt(self._grant, message_id)
            if receipt is not None:
                if receipt.request_digest != request_digest:
                    raise ReportChannelAcpConflict("report_channel_acp_message_conflict")
                if receipt.reply is None:
                    raise ReportChannelAcpConflict("report_channel_acp_outcome_unknown")
                await self._authorize(identity)
                return receipt.reply
            binding = await repository.acp_binding(self._grant)
            if binding is None:
                raise ReportChannelAcpDenied("Report channel membership required")
            async with self._bridge._client_factory() as client:
                session_id = await client.open_session(resume=binding.session_id)
                if not await repository.set_acp_session(self._grant, session_id):
                    raise ReportChannelAcpDenied("Report channel membership required")
                reserved = await repository.reserve_acp_turn(
                    self._grant, message_id, request_digest, limit=128,
                )
                if reserved == "full":
                    raise ReportChannelAcpCapacity("report_channel_acp_conversation_full")
                if reserved != "created":
                    raise ReportChannelAcpConflict("report_channel_acp_outcome_unknown")
                await self._authorize(identity)
                reply = await client.prompt(text)
            await self._authorize(identity)
            if not await repository.complete_acp_turn(self._grant, message_id, request_digest, reply):
                raise ReportChannelAcpDenied("Report channel membership required")
            return reply
