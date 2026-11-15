"""Opt-in PPTX candidate adapter wrapping read-only text previews.

The adapter never accepts or saves a presentation. In-memory task receipts
are only suitable for single-worker prototypes, not production persistence.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from .document_candidate_contract import DocumentCandidateRequest, DocumentFormat, DocumentScope
from .document_candidate_pptx_preview import PptxTextPreviewEngine
from .document_candidate_pptx_targets import validate_pptx_selection


class PptxCandidateAdapter:
    format = DocumentFormat.PPTX

    def __init__(
        self,
        engine: PptxTextPreviewEngine,
        authorize: Callable[[DocumentScope], Awaitable[bool]],
        validate_source: Callable[[DocumentScope], Awaitable[bool]],
    ) -> None:
        self._engine = engine
        self._authorize = authorize
        self._validate_source = validate_source
        self._lock = asyncio.Lock()
        self._tasks: dict[str, tuple[DocumentScope, str, dict[str, Any]]] = {}

    async def _check(self, scope: DocumentScope) -> None:
        if scope.format != self.format:
            raise ValueError("document_adapter_format_mismatch")
        if not await self._authorize(scope):
            raise PermissionError("document_channel_authorization_required")
        if not await self._validate_source(scope):
            raise PermissionError("document_source_changed")

    async def prepare(self, request: DocumentCandidateRequest) -> str:
        validate_pptx_selection(request.selection)
        async with self._lock:
            await self._check(request.scope)
            task_id = hashlib.sha256(json.dumps([
                request.scope.channel, request.scope.grant, request.scope.document_id,
                request.scope.revision, request.scope.source_sha256, request.request_id,
            ]).encode()).hexdigest()
            fingerprint = hashlib.sha256(json.dumps([
                request.instruction, request.selection,
            ], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            existing = self._tasks.get(task_id)
            if existing is not None:
                if existing[0] != request.scope or existing[1] != fingerprint:
                    raise ValueError("document_request_id_conflict")
                await self._check(request.scope)
                return task_id
            preview = await self._engine.prepare(request)
            await self._check(request.scope)
            if preview.get("status") != "preview_ready" or preview.get("accepted") is not False:
                raise ValueError("pptx_preview_invalid")
            self._tasks[task_id] = (request.scope, fingerprint, deepcopy({
                **preview, "taskId": task_id,
            }))
            return task_id

    async def status(self, scope: DocumentScope, task_id: str) -> dict[str, Any]:
        await self._check(scope)
        entry = self._tasks.get(task_id)
        if entry is None or entry[0] != scope:
            raise PermissionError("document_task_not_accessible")
        await self._check(scope)
        return deepcopy(entry[2])
