"""Delegate channel tasks to the editor's existing Word candidate service."""

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi import HTTPException

from .report_channel_api import ConnectorIdentity, DelegateRequest
from .report_channel_repository import ReportChannelRepository
from .report_editor.native_ai import NativeAIService
from .office.editor_grants import ReportEditorSession
from .reporting.models import ReportingError


@dataclass(frozen=True)
class ChannelWordDraft:
    session: ReportEditorSession
    source_sha256: str
    operations: list[dict]
    selection: list[dict[str, str]]
    session_reference: str | None = field(default=None, repr=False)


class ReportChannelWordAssistant:
    def __init__(
        self,
        ai: NativeAIService,
        resolve_draft: Callable[[str], Awaitable[ChannelWordDraft | None]],
        repository: ReportChannelRepository,
    ):
        self.ai = ai
        self.resolve_draft = resolve_draft
        self.repository = repository

    async def _draft(self, channel: str) -> ChannelWordDraft:
        draft = await self.resolve_draft(channel)
        if draft is None:
            raise HTTPException(409, "report_channel_word_draft_unavailable")
        context = await self.ai.editor.context_for_session(draft.session)
        if context.format != "docx":
            raise HTTPException(409, "report_channel_word_draft_unavailable")
        return draft

    @staticmethod
    def _prefix(channel: str, identity: ConnectorIdentity) -> str:
        scope = json.dumps([channel, identity.connector, identity.subject, identity.session])
        return hashlib.sha256(scope.encode()).hexdigest() + "_"

    @staticmethod
    def _status(job: dict) -> dict:
        return {"taskId": job["editId"], "status": job["status"], "accepted": job["accepted"]}

    async def start(self, channel: str, identity: ConnectorIdentity, payload: DelegateRequest) -> dict:
        grant = await self.repository.member_grant(channel, identity)
        if grant is None:
            raise HTTPException(403, "report_channel_membership_required")

        async def authorized() -> bool:
            return await self.repository.grant_active(grant)

        request_hash = hashlib.sha256(f"{grant}:{payload.request_id}".encode()).hexdigest()[:63]
        try:
            draft = await self._draft(channel)
            job = await self.ai.start_edit(
                draft.session,
                instruction=payload.instruction,
                expected_sha256=draft.source_sha256,
                operations=draft.operations,
                selection=draft.selection,
                client_request_id=self._prefix(channel, identity) + request_hash,
                server_session_reference=draft.session_reference,
                authorization_check=authorized,
            )
        except ReportingError as error:
            raise HTTPException(409, error.code) from None
        return self._status(job)

    async def status(self, channel: str, identity: ConnectorIdentity, task_id: str) -> dict:
        try:
            draft = await self._draft(channel)
            job = await self.ai.wait_edit_status(draft.session, task_id, wait_ms=0)
        except ReportingError:
            raise HTTPException(404, "report_channel_word_task_missing") from None
        if not job.get("clientRequestId", "").startswith(self._prefix(channel, identity)):
            raise HTTPException(404, "report_channel_word_task_missing")
        return self._status(job)
