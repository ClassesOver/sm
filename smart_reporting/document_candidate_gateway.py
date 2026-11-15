"""Host-authorized dispatch for document candidate adapters.

The caller's document scope is never accepted from a client request. The host
must resolve it from the authenticated channel membership on every operation.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .document_candidate_contract import (
    DocumentAdapterRegistry,
    DocumentCandidateRequest,
    DocumentScope,
)


class DocumentCandidateDenied(PermissionError):
    pass


class DocumentCandidateGateway:
    def __init__(
        self,
        registry: DocumentAdapterRegistry,
        resolve_scope: Callable[[str, Any], Awaitable[DocumentScope | None]],
    ) -> None:
        self._registry = registry
        self._resolve_scope = resolve_scope

    async def _scope(self, channel: str, identity: Any) -> DocumentScope:
        scope = await self._resolve_scope(channel, identity)
        if scope is None or scope.channel != channel:
            raise DocumentCandidateDenied("document_channel_authorization_required")
        return scope

    async def prepare(
        self,
        channel: str,
        identity: Any,
        *,
        request_id: str,
        instruction: str,
        selection: tuple[dict[str, Any], ...],
    ) -> str:
        scope = await self._scope(channel, identity)
        adapter = self._registry.require(scope.format)
        request = DocumentCandidateRequest(scope, request_id, instruction, selection)
        task_id = await adapter.prepare(request)
        # The authorization may have been revoked while the adapter awaited.
        if await self._scope(channel, identity) != scope:
            raise DocumentCandidateDenied("document_scope_changed")
        return task_id

    async def status(self, channel: str, identity: Any, task_id: str) -> dict[str, Any]:
        scope = await self._scope(channel, identity)
        if not task_id or len(task_id) > 256:
            raise ValueError("document_task_id_invalid")
        adapter = self._registry.require(scope.format)
        result = await adapter.status(scope, task_id)
        if await self._scope(channel, identity) != scope:
            raise DocumentCandidateDenied("document_scope_changed")
        return result
