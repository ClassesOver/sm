"""Read-only XLSX candidate preview using openpyxl; never persists edits.

The host supplies source bytes and a proposed operation list. This engine
only supports literal writes to individual, non-formula cells. Preview data is
ephemeral and process-local; no acceptance or saving API is provided.
"""
from __future__ import annotations

import hashlib
import io
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
        self._tasks: dict[str, tuple[DocumentScope, dict[str, Any]]] = {}

    async def prepare(self, request: DocumentCandidateRequest) -> str:
        source = await self._load_source(request.scope)
        if hashlib.sha256(source).hexdigest() != request.scope.source_sha256:
            raise PermissionError("document_source_changed")
        operations = await self._propose(request)
        validate_xlsx_operations(request.selection, operations)
        workbook = load_workbook(io.BytesIO(source), read_only=False, data_only=False)
        try:
            changes = []
            for operation in operations:
                sheet_name, address = operation["sheet"], operation["range"]
                if sheet_name not in workbook.sheetnames or ":" in address:
                    raise ValueError("xlsx_preview_target_invalid")
                sheet = workbook[sheet_name]
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
            # Never mutate or save the workbook: a diff is the only output.
            task_id = hashlib.sha256(
                (request.scope.grant + ":" + request.scope.source_sha256 + ":" + request.request_id).encode()
            ).hexdigest()
            if task_id in self._tasks:
                previous_scope, previous = self._tasks[task_id]
                if previous_scope != request.scope or previous["changes"] != changes:
                    raise ValueError("document_request_id_conflict")
            else:
                self._tasks[task_id] = (request.scope, {
                    "taskId": task_id, "status": "preview_ready",
                    "accepted": False, "changes": changes,
                })
            return task_id
        finally:
            workbook.close()

    async def status(self, scope: DocumentScope, task_id: str) -> dict[str, Any]:
        entry = self._tasks.get(task_id)
        if entry is None or entry[0] != scope:
            raise PermissionError("document_task_not_accessible")
        return dict(entry[1], changes=[dict(item) for item in entry[1]["changes"]])
