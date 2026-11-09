"""独立原生 XLSX/PPTX 的引擎适配，不参与报告发布或 AI 候选登记。"""
from __future__ import annotations

import json
import re
from collections.abc import Set
from pathlib import PurePosixPath
from typing import Any

from ..reporting.delivery.xlsx import inspect_workbook, patch_workbook
from .slides import (
    _SLIDE_ANIMATION_EFFECTS,
    _SLIDE_ANIMATION_TRIGGERS,
    ReportSlidesEditorService,
    _number,
    _slide_index,
    _validate_structure_edits,
)
from .slides_render import validate_slide_edits

_ALLOWED_KEYS = {'kind', 'edits', 'order', 'theme', 'slideSize', 'transitions', 'animations', 'slideLayouts', 'backgrounds', 'textBoxes', 'deletions', 'textFormatting', 'paragraphFormatting'}
# 对齐既有 workbook bridge/operations.ts 顶层协议；内部参数仍交共享引擎验证。
_XLSX_FIELDS = {
    'applyCellEdits': {'edits'}, 'applySheetMerges': {'sheetName', 'ranges'},
    'applySheetEdits': {'plan'}, 'applyRowColumnOps': {'sheetName', 'ops'},
    'applyCellShift': {'sheetName', 'range', 'shift'},
    'applyDvRules': {'rules'}, 'applyCfRules': {'rules'}, 'applySheetNotes': {'sheetName', 'notes'},
    'patchSheetNotes': {'sheetName', 'sourceIdentity', 'changes'},
    'applySheetFilter': {'sheetName', 'filter'},
    'addPivot': {'addition'}, 'applyColumnWidths': {'sheetName', 'entries'},
    'applyRowHeights': {'sheetName', 'entries'}, 'applyPageSetups': {'setups'},
    'applyTableAdditions': {'additions'}, 'refreshPivotCaches': set(),
    'applyPivotLayoutExpansions': {'updates'}, 'expandPivotOutputs': {'expansions'},
    'applyDefinedNames': {'plan'}, 'protectSheet': {'sheetName', 'protect'},
    'protectWorkbookStructure': {'lockStructure'}, 'setThemePart': {'themePath', 'state'},
    'sortRange': {'sheetName', 'spec'},
}
_TRANSITIONS = {'none', 'morph', 'fade', 'push', 'wipe', 'split', 'circle', 'cover', 'pull', 'dissolve', 'zoom', 'random'}
# ECMA-376 ST_SlideSizeCoordinate: 1 to 56 inches in EMU.
_MIN_SLIDE_EMU, _MAX_SLIDE_EMU = 914400, 51206400
_ANIMATION_DIRECTIONS = {'top', 'bottom', 'left', 'right'}
_DIRECTIONAL_ANIMATIONS = {'flyIn', 'flyOut', 'wipe', 'wipeOut'}
_NUMBERING_TYPES = {'arabicPeriod', 'arabicParenR', 'romanUcPeriod', 'alphaUcPeriod', 'alphaLcParenR', 'alphaLcPeriod', 'romanLcPeriod', 'circleNumDbPlain', 'ea1ChsPeriod'}
# ECMA-376 ST_TextMargin/ST_TextIndent use an absolute limit of 56 inches.
_MAX_PARAGRAPH_EMU = 51206400
_HEX_COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')


def _content(format: str, content: bytes) -> None:
    if format not in {'xlsx', 'pptx'} or not isinstance(content, bytes) or not content or len(content) > 24 * 1024 * 1024:
        raise ValueError('native_office_content_invalid')


def inspect_office(format: str, content: bytes) -> dict[str, Any]:
    _content(format, content)
    try:
        return inspect_workbook(content) if format == 'xlsx' else ReportSlidesEditorService._run_engine(content, 'inspect')
    except Exception:
        raise ValueError('native_office_inspect_failed') from None


def _records(payload: dict[str, Any], key: str, required: set[str], optional: Set[str] = frozenset()) -> list[dict[str, Any]]:
    values = payload.get(key, [])
    if not isinstance(values, list) or len(values) > 500:
        raise ValueError('native_office_operations_invalid')
    for value in values:
        if (not isinstance(value, dict) or not required.issubset(value) or not set(value).issubset(required | optional)
            or not _slide_index(value.get('slideIndex'))):
            raise ValueError('native_office_operations_invalid')
    return values


def _pptx_arguments(operation: dict[str, Any]) -> dict[str, Any]:
    if operation.get('kind') != 'editSlides' or not set(operation).issubset(_ALLOWED_KEYS):
        raise ValueError('native_office_operations_invalid')
    edits = validate_slide_edits(operation.get('edits', []))
    order, theme = operation.get('order'), operation.get('theme')
    if order is not None and (not isinstance(order, list) or len(order) > 500 or any(not _slide_index(index) for index in order)
                              or len(set(order)) != len(order)):
        raise ValueError('native_office_operations_invalid')
    if theme is not None and (not isinstance(theme, str) or theme not in {'executive', 'clinical', 'modern'}):
        raise ValueError('native_office_operations_invalid')
    slide_size = operation.get('slideSize')
    if slide_size is not None and (
        not isinstance(slide_size, dict) or set(slide_size) != {'cx', 'cy'}
        or any(not isinstance(slide_size[key], int) or isinstance(slide_size[key], bool) for key in ('cx', 'cy'))
        or any(not _MIN_SLIDE_EMU <= slide_size[key] <= _MAX_SLIDE_EMU for key in ('cx', 'cy'))
    ):
        raise ValueError('native_office_operations_invalid')
    transitions = _records(operation, 'transitions', {'slideIndex', 'kind'})
    if any(not isinstance(item['kind'], str) or item['kind'] not in _TRANSITIONS for item in transitions):
        raise ValueError('native_office_operations_invalid')
    animations = _records(operation, 'animations', {'slideIndex', 'elementId', 'effect', 'trigger'}, {'durationMs', 'delayMs', 'direction', 'append'})
    for item in animations:
        if (not isinstance(item['elementId'], str) or not item['elementId']
            or not isinstance(item['effect'], str) or item['effect'] not in _SLIDE_ANIMATION_EFFECTS
            or not isinstance(item['trigger'], str) or item['trigger'] not in _SLIDE_ANIMATION_TRIGGERS
            or ('append' in item and not isinstance(item['append'], bool))
            or any(key in item and not _number(item[key], 0, 3_600_000) for key in ('durationMs', 'delayMs'))):
            raise ValueError('native_office_operations_invalid')
        if 'direction' in item and (item['direction'] not in _ANIMATION_DIRECTIONS or item['effect'] not in _DIRECTIONAL_ANIMATIONS):
            raise ValueError('native_office_operations_invalid')
    text_formatting = _records(operation, 'textFormatting', {'slideIndex', 'elementId'}, {
        'fontSizePt', 'fontFamily', 'color', 'bold', 'italic', 'underline', 'strike',
    })
    for item in text_formatting:
        fields = set(item) - {'slideIndex', 'elementId'}
        if (not isinstance(item['elementId'], str) or not item['elementId'] or not fields
            or ('fontSizePt' in item and not _number(item['fontSizePt'], 1, 400))
            or ('fontFamily' in item and (not isinstance(item['fontFamily'], str) or not item['fontFamily'].strip() or len(item['fontFamily']) > 200 or any(ord(char) < 32 for char in item['fontFamily'])))
            or ('color' in item and (not isinstance(item['color'], str) or not _HEX_COLOR.fullmatch(item['color'])))
            or any(key in item and not isinstance(item[key], bool) for key in ('bold', 'italic', 'underline', 'strike'))):
            raise ValueError('native_office_operations_invalid')
    paragraph_formatting = _records(operation, 'paragraphFormatting', {'slideIndex', 'elementId'}, {
        'align', 'lineSpacingPct', 'spaceBeforePt', 'spaceAfterPt',
        'bullet', 'bulletChar', 'bulletFont', 'numType', 'startAt', 'bulletHangEmu',
        'bulletSizePct', 'bulletColor', 'rtl', 'indentDelta',
    })
    for item in paragraph_formatting:
        if (not isinstance(item['elementId'], str) or not item['elementId']
            or not set(item) - {'slideIndex', 'elementId'}
            or ('align' in item and (not isinstance(item['align'], str) or item['align'] not in {'left', 'center', 'right', 'justify'}))
            or ('lineSpacingPct' in item and (not _number(item['lineSpacingPct'], 100, 300) or item['lineSpacingPct'] not in {100, 115, 150, 200, 250, 300}))
            or any(key in item and not _number(item[key], 0, 500) for key in ('spaceBeforePt', 'spaceAfterPt'))
            or ('bullet' in item and (not isinstance(item['bullet'], str) or item['bullet'] not in {'char', 'number', 'none'}))
            or ('bulletChar' in item and (not isinstance(item['bulletChar'], str) or len(item['bulletChar']) != 1 or ord(item['bulletChar']) < 32 or 0x7f <= ord(item['bulletChar']) <= 0x9f or 0xd800 <= ord(item['bulletChar']) <= 0xdfff or ord(item['bulletChar']) in {0xfffe, 0xffff}))
            or ('bulletFont' in item and (not isinstance(item['bulletFont'], str) or not item['bulletFont'].strip() or len(item['bulletFont']) > 200 or any(ord(char) < 32 or 0x7f <= ord(char) <= 0x9f or 0xd800 <= ord(char) <= 0xdfff or ord(char) in {0xfffe, 0xffff} for char in item['bulletFont'])))
            or ('numType' in item and (not isinstance(item['numType'], str) or item['numType'] not in _NUMBERING_TYPES))
            or any(key in item and (not isinstance(item[key], int) or isinstance(item[key], bool) or not low <= item[key] <= high) for key, low, high in [('startAt', 1, 32767), ('bulletHangEmu', 0, _MAX_PARAGRAPH_EMU)])
            or ('bulletSizePct' in item and (not _number(item['bulletSizePct'], 75, 150) or item['bulletSizePct'] not in {75, 90, 100, 125, 150}))
            or ('bulletColor' in item and (not isinstance(item['bulletColor'], str) or not _HEX_COLOR.fullmatch(item['bulletColor'])))
            or ('rtl' in item and not isinstance(item['rtl'], bool))
            or ('indentDelta' in item and (not isinstance(item['indentDelta'], int) or isinstance(item['indentDelta'], bool) or item['indentDelta'] not in {-1, 1}))
            or (item.get('bullet') == 'none' and bool(set(item) & {'bulletChar', 'bulletFont', 'numType', 'startAt', 'bulletHangEmu', 'bulletSizePct', 'bulletColor'}))
            or (item.get('bullet') == 'char' and bool(set(item) & {'numType', 'startAt'}))
            or (bool(set(item) & {'bulletChar', 'bulletFont'}) and item.get('bullet') != 'char')):
            raise ValueError('native_office_operations_invalid')
    bridge_edits = [
        *edits,
        *[
            {key: value for key, value in item.items() if key != 'elementId'}
            | {'elementId': item['elementId']}
            for item in text_formatting
        ],
    ]
    layouts = _records(operation, 'slideLayouts', {'slideIndex', 'layoutPath'})
    for item in layouts:
        path = item['layoutPath']
        if (not isinstance(path, str) or not path.startswith('ppt/slideLayouts/') or not path.endswith('.xml')
            or '\\' in path or '..' in PurePosixPath(path).parts or ':' in path):
            raise ValueError('native_office_operations_invalid')
    backgrounds, text_boxes, deletions = _validate_structure_edits(operation)
    return {'edits': bridge_edits, 'order': order, 'theme': theme, 'slide_size': slide_size, 'transitions': transitions, 'animations': animations,
        'slide_layouts': layouts, 'backgrounds': backgrounds, 'text_boxes': text_boxes, 'deletions': deletions,
        'paragraph_formatting': paragraph_formatting}


def patch_office(format: str, content: bytes, operations: list[dict[str, Any]]) -> bytes:
    _content(format, content)
    try:
        if (not isinstance(operations, list) or len(operations) > 500
            or any(not isinstance(operation, dict) for operation in operations)
            or len(json.dumps(operations, ensure_ascii=False, allow_nan=False).encode()) > 12 * 1024 * 1024):
            raise ValueError('native_office_operations_invalid')
        if not operations:
            return content
        if format == 'xlsx':
            for operation in operations:
                kind = operation.get('kind')
                if not isinstance(kind, str) or kind not in _XLSX_FIELDS or set(operation) != {'kind', *_XLSX_FIELDS[kind]}:
                    raise ValueError('native_office_operations_invalid')
            result = patch_workbook(content, operations)
        else:
            if len(operations) != 1:
                raise ValueError('native_office_operations_invalid')
            arguments = _pptx_arguments(operations[0])
            result = ReportSlidesEditorService._run_engine(content, 'edit', **arguments)['bytes']
        return result
    except Exception:
        raise ValueError('native_office_operations_invalid') from None
