"""Fail-closed XLSX candidate adapter.

An injected engine may prepare an immutable preview, never accept or save it.
The host owns the document source, authorization and workbook metadata.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from .document_candidate_contract import (
    DocumentCandidateRequest,
    DocumentFormat,
    DocumentScope,
)
from .document_candidate_xlsx_targets import validate_xlsx_selection


class XlsxCandidateEngine(Protocol):
    async def prepare(self, request: DocumentCandidateRequest) -> str: ...
    async def status(self, scope: DocumentScope, task_id: str) -> dict[str, Any]: ...


class XlsxCandidateAdapter:
    format = DocumentFormat.XLSX

    def __init__(
        self,
        engine: XlsxCandidateEngine,
        authorize: Callable[[DocumentScope], Awaitable[bool]],
        validate_source: Callable[[DocumentScope], Awaitable[bool]],
    ) -> None:
        self._engine = engine
        self._authorize = authorize
        self._validate_source = validate_source

    async def _check(self, scope: DocumentScope) -> None:
        if scope.format != self.format:
            raise ValueError("document_adapter_format_mismatch")
        if not await self._authorize(scope):
            raise PermissionError("document_channel_authorization_required")
        if not await self._validate_source(scope):
            raise PermissionError("document_source_changed")

    async def prepare(self, request: DocumentCandidateRequest) -> str:
        validate_xlsx_selection(request.selection)
        await self._check(request.scope)
        task_id = await self._engine.prepare(request)
        await self._check(request.scope)
        return task_id

    async def status(self, scope: DocumentScope, task_id: str) -> dict[str, Any]:
        await self._check(scope)
        result = await self._engine.status(scope, task_id)
        await self._check(scope)
        return result
