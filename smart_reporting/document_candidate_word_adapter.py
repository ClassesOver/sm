"""DOCX adapter bridge for the existing channel Word candidate service.

The host must supply a scope resolver bound to the authenticated identity.
This adapter delegates to the existing Word service; it does not accept/save.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .document_candidate_contract import (
    DocumentCandidateRequest,
    DocumentFormat,
    DocumentScope,
)
from .report_channel_api import ConnectorIdentity, DelegateRequest
from .report_channel_word import ReportChannelWordAssistant


class ChannelWordCandidateAdapter:
    format = DocumentFormat.DOCX

    def __init__(
        self,
        word: ReportChannelWordAssistant,
        identity_for_scope: Callable[[DocumentScope], Awaitable[ConnectorIdentity | None]],
    ) -> None:
        self._word = word
        self._identity_for_scope = identity_for_scope

    async def _identity(self, scope: DocumentScope) -> ConnectorIdentity:
        identity = await self._identity_for_scope(scope)
        if identity is None:
            raise PermissionError("document_channel_authorization_required")
        grant = await self._word.repository.member_grant(scope.channel, identity)
        if grant != scope.grant or not await self._word.repository.grant_active(grant):
            raise PermissionError("document_channel_authorization_required")
        return identity

    async def prepare(self, request: DocumentCandidateRequest) -> str:
        if request.scope.format != self.format:
            raise ValueError("document_adapter_format_mismatch")
        identity = await self._identity(request.scope)
        # The existing Word service resolves the authoritative source and
        # selection. Never substitute caller-supplied operations or selection.
        draft = await self._word._draft(request.scope.channel)
        if draft.source_sha256 != request.scope.source_sha256:
            raise PermissionError("document_source_changed")
        # The unified request must not silently discard the requested selection.
        # Word currently edits only the host-authorized draft selection.
        if list(request.selection) != draft.selection:
            raise ValueError("document_selection_mismatch")
        result = await self._word.start(
            request.scope.channel,
            identity,
            DelegateRequest(request_id=request.request_id, instruction=request.instruction),
            validated_draft=draft,
            expected_grant=request.scope.grant,
        )
        return result["taskId"]

    async def status(self, scope: DocumentScope, task_id: str) -> dict[str, Any]:
        if scope.format != self.format:
            raise ValueError("document_adapter_format_mismatch")
        identity = await self._identity(scope)
        draft = await self._word._draft(scope.channel)
        if draft.source_sha256 != scope.source_sha256:
            raise PermissionError("document_source_changed")
        return await self._word.status(scope.channel, identity, task_id)
