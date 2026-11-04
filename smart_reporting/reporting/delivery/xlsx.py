"""共享工作簿引擎的薄 Python / Node 桥接。"""
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .office_engine import last_json_line, run_bridge


@dataclass(frozen=True)
class WorkbookBuildResult:
    path: str
    size: int
    sha256: str
    sheet_count: int
    issues: tuple[dict[str, Any], ...] = ()


_OPERATION_KINDS = frozenset({
    'applyCellEdits', 'applySheetMerges', 'applySheetEdits', 'applyRowColumnOps', 'applyDvRules',
    'applyCfRules', 'applySheetNotes', 'addPivot', 'applyColumnWidths',
    'applyRowHeights', 'applyPageSetups', 'applyTableAdditions', 'sortRange',
    'refreshPivotCaches', 'applyPivotLayoutExpansions', 'expandPivotOutputs',
    'applyDefinedNames', 'protectSheet', 'protectWorkbookStructure', 'setThemePart',
})


def _invoke(payload: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix='report-workbook-') as temporary:
        request = Path(temporary) / 'request.json'
        request.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        completed = run_bridge('workbook', 'cli', request)
    if completed.returncode:
        raise ValueError(f'workbook_engine_failed: {completed.stderr[-2000:]}')
    try:
        receipt = last_json_line(completed.stdout)
    except ValueError as error:
        raise ValueError('workbook_engine_receipt_invalid') from error
    if not isinstance(receipt, dict):
        raise ValueError('workbook_engine_receipt_invalid')
    return receipt


def build_workbook(
    *, output_path: Path, title: str, period: str,
    sheets: tuple[dict[str, Any], ...], source_mapping: dict[str, Any] | None = None,
) -> WorkbookBuildResult:
    """按冻结的结构化数值成稿；不解析 Markdown 中的显示文本。"""
    if not sheets or not title.strip():
        raise ValueError('workbook_content_invalid')
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    receipt = _invoke({
        'kind': 'create', 'output': str(output_path), 'title': title, 'period': period,
        'sheets': sheets, 'sourceMapping': source_mapping or {},
    })
    content = output_path.read_bytes()
    if not content:
        raise ValueError('workbook_identity_unavailable')
    return WorkbookBuildResult(
        path=output_path.as_posix(), size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        sheet_count=int(receipt['sheetCount']), issues=tuple(receipt.get('issues', ())),
    )


def inspect_workbook(content: bytes) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix='inspect-workbook-') as temporary:
        source = Path(temporary) / 'input.xlsx'
        source.write_bytes(content)
        return _invoke({'kind': 'inspect', 'input': str(source)})


def patch_workbook(content: bytes, operations: list[dict[str, Any]]) -> bytes:
    if not isinstance(operations, list) or any(
        not isinstance(operation, dict) or operation.get('kind') not in _OPERATION_KINDS
        for operation in operations
    ):
        raise ValueError('workbook_operation_invalid')
    with tempfile.TemporaryDirectory(prefix='patch-workbook-') as temporary:
        source, output = Path(temporary) / 'input.xlsx', Path(temporary) / 'output.xlsx'
        source.write_bytes(content)
        _invoke({'kind': 'patch', 'input': str(source), 'output': str(output), 'operations': operations})
        return output.read_bytes()
