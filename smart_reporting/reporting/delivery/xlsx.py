"""共享工作簿引擎的薄 Python / Node 桥接。"""
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from io import BytesIO
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
    'applyStaticImages', 'applyCellEdits', 'applySheetMerges', 'applySheetEdits', 'applyRowColumnOps', 'applyDvRules',
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
    images: tuple[dict[str, Any], ...] = (),
) -> WorkbookBuildResult:
    """按冻结数值成稿，可选嵌入已核验 PNG/JPEG；坏图作为 issues 拒用。

    images 项包括 imageId/path/size/sha256、sheetName/range、chartId、
    snapshotId/chartRevision（均为字符串）、sourceRanges，以及可选 sourceFiles。
    宿主绝对读取路径可另配 identityPath，工作簿只保存该相对身份；未配时保存文件名。
    range 是包含末端单元格的 A1 范围；替换沿用 imageId 及原有位置。
    source_mapping.snapshotId/chartRevisions 如存在，必须与图片身份一致。
    """
    if not sheets or not title.strip():
        raise ValueError('workbook_content_invalid')
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    verified_images, image_issues = _verified_images(images)
    receipt = _invoke({
        'kind': 'create', 'output': str(output_path), 'title': title, 'period': period,
        'sheets': sheets, 'sourceMapping': source_mapping or {}, 'images': verified_images,
    })
    content = output_path.read_bytes()
    if not content:
        raise ValueError('workbook_identity_unavailable')
    return WorkbookBuildResult(
        path=output_path.as_posix(), size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        sheet_count=int(receipt['sheetCount']), issues=tuple(image_issues) + tuple(receipt.get('issues', ())),
    )


def _verified_images(images: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """边界解码并验证当前图片；Node 嵌入前再次核对文件身份。"""
    from PIL import Image

    accepted, issues = [], []
    for image in images:
        try:
            content = Path(image['path']).read_bytes()
            if len(content) != image['size'] or hashlib.sha256(content).hexdigest() != image['sha256']:
                raise ValueError('workbook_image_identity_changed')
            with Image.open(BytesIO(content)) as bitmap:
                if bitmap.format not in {'PNG', 'JPEG'}:
                    raise ValueError('workbook_image_format_invalid')
                pixel_width, pixel_height = bitmap.size
                bitmap.verify()
            for source in image.get('sourceFiles', ()):
                source_bytes = Path(source['path']).read_bytes()
                if len(source_bytes) != source['size'] or hashlib.sha256(source_bytes).hexdigest() != source['sha256']:
                    raise ValueError('workbook_image_source_identity_changed')
            accepted.append({**image, 'pixelWidth': pixel_width, 'pixelHeight': pixel_height})
        except (OSError, ValueError, KeyError, TypeError) as error:
            issues.append({'code': 'workbook_image_rejected', 'imageId': image.get('imageId', ''), 'message': str(error)})
    return accepted, issues


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
    prepared = []
    for operation in operations:
        if operation['kind'] == 'applyStaticImages':
            images, issues = _verified_images(operation.get('images', []))
            operation = {**operation, 'images': images, 'imageIssues': issues}
        prepared.append(operation)
    with tempfile.TemporaryDirectory(prefix='patch-workbook-') as temporary:
        source, output = Path(temporary) / 'input.xlsx', Path(temporary) / 'output.xlsx'
        source.write_bytes(content)
        _invoke({'kind': 'patch', 'input': str(source), 'output': str(output), 'operations': prepared})
        return output.read_bytes()
