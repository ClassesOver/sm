"""Read-only XLSX candidate preview using openpyxl; never persists edits.

The host supplies source bytes and a proposed operation list. This engine
only supports literal writes to individual, non-formula cells. Preview data is
ephemeral and process-local; no acceptance or saving API is provided.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import io
import json
from collections.abc import Awaitable, Callable
from typing import Any

from openpyxl import load_workbook

from .document_candidate_contract import DocumentCandidateRequest, DocumentScope
from .document_candidate_xlsx_operations import validate_xlsx_operations


class XlsxLiteralPreviewEngine:
    def __init__(
        self,
        load_source: Callable[[DocumentScope], Awaitable[bytes]],
        propose: Callable[[DocumentCandidateRequest], Awaitable[tuple[dict[str, Any], ...]]],
    ) -> None:
        self._load_source = load_source
        self._propose = propose
        self._tasks: dict[str, tuple[DocumentScope, str, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def _verified_source(self, scope: DocumentScope) -> bytes:
        source = await self._load_source(scope)
        if hashlib.sha256(source).hexdigest() != scope.source_sha256:
            raise PermissionError("document_source_changed")
        return source

    async def prepare(self, request: DocumentCandidateRequest) -> str:
        async with self._lock:
            return await self._prepare_locked(request)

    async def _prepare_locked(self, request: DocumentCandidateRequest) -> str:
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
            await self._verified_source(request.scope)
            return task_id
        source = await self._verified_source(request.scope)
        operations = await self._propose(request)
        validate_xlsx_operations(request.selection, operations)
        # A proposal may take seconds; reject a stale snapshot before publishing.
        await self._verified_source(request.scope)
        workbook = load_workbook(io.BytesIO(source), read_only=False, data_only=False)
        try:
            changes = []
            for operation in operations:
                sheet_name, address = operation["sheet"], operation["range"]
                if sheet_name not in workbook.sheetnames or ":" in address:
                    raise ValueError("xlsx_preview_target_invalid")
                sheet = workbook[sheet_name]
                if sheet.protection.sheet:
                    raise ValueError("xlsx_preview_protected_sheet")
                cell = sheet[address]
                if cell.__class__.__name__ == "MergedCell" or cell.data_type == "f":
                    raise ValueError("xlsx_preview_formula_or_merged_cell")
                old = cell.value
                if isinstance(old, str) and old.startswith("="):
                    raise ValueError("xlsx_preview_formula_or_merged_cell")
                changes.append({
                    "sheet": sheet_name, "cell": address,
                    "before": old, "after": operation["value"],
                })
            # A literal edit can change formula results even without editing a
            # formula cell. Do not imply that this read-only preview recalculated
            # workbook formulas or verified their dependencies.
            formula_count = sum(
                1 for sheet in workbook.worksheets
                for cell in sheet._cells.values() if cell.data_type == "f"
            )
            # Parsing and formula inspection can be expensive. Do not publish
            # a preview if the source changed after the previous digest check.
            await self._verified_source(request.scope)
            # Never mutate or save the workbook: a diff is the only output.
            if task_id in self._tasks:
                previous_scope, previous_fingerprint, previous = self._tasks[task_id]
                if previous_scope != request.scope or previous_fingerprint != fingerprint or previous["changes"] != changes:
                    raise ValueError("document_request_id_conflict")
            else:
                self._tasks[task_id] = (request.scope, fingerprint, {
                    "taskId": task_id, "status": "preview_ready",
                    "accepted": False, "changes": changes,
                    "formulaCount": formula_count,
                    "requiresFormulaRecalculation": formula_count > 0,
                })
            return task_id
        finally:
            workbook.close()

    async def status(self, scope: DocumentScope, task_id: str) -> dict[str, Any]:
        entry = self._tasks.get(task_id)
        if entry is None or entry[0] != scope:
            raise PermissionError("document_task_not_accessible")
        await self._verified_source(scope)
        return deepcopy(entry[2])
