"""独立原生 XLSX/PPTX 的引擎适配，不参与报告发布或 AI 候选登记。"""
from __future__ import annotations

import json
import re
from collections.abc import Set
from pathlib import Path, PurePosixPath
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

_ALLOWED_KEYS = {'kind', 'edits', 'order', 'newSlides', 'deletedSlides', 'resetLayouts', 'shapes', 'tables', 'shapeStyles', 'shapeKinds', 'sections', 'headerFooter', 'tableCells', 'charts', 'smartArts', 'theme', 'slideSize', 'transitions', 'animations', 'animationSequences', 'slideLayouts', 'backgrounds', 'textBoxes', 'deletions', 'textFormatting', 'paragraphFormatting'}
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
# 固定源形状库（与前端 shape-gallery-data.ts 同源），只允许这些 prstGeom。
_SHAPE_DATA = json.loads((Path(__file__).parents[1] / 'reporting' / 'slides_engine' / 'bridge' / 'shape-presets.json').read_text(encoding='utf-8'))
_SHAPE_PRESETS = frozenset(_SHAPE_DATA['presets'])
_LINE_PRESETS = frozenset(_SHAPE_DATA['lines'])
# 固定源 CHART_GALLERY 的 13 种图表
_CHART_KINDS = frozenset({'bar', 'bar3D', 'barStacked', 'barPercentStacked', 'barH', 'line', 'area', 'pie', 'pie3D', 'doughnut', 'scatter', 'radar', 'comboBarLine'})


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


def _layout_path(path: Any) -> bool:
    return (isinstance(path, str) and path.startswith('ppt/slideLayouts/') and path.endswith('.xml')
            and '\\' not in path and '..' not in PurePosixPath(path).parts and ':' not in path)


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
    # 新建空白页（固定源 onAddSlide，layoutFrom）或复制页（duplicateSlide，duplicateOf）；位置由 order 决定，引擎再按来源页数校验。
    new_slides = operation.get('newSlides', [])
    if (not isinstance(new_slides, list) or len(new_slides) > 50
        or any(not isinstance(item, dict) or len(item) != 1 or set(item) - {'layoutFrom', 'duplicateOf', 'withLayout'}
               or (not _slide_index(next(iter(item.values()))) if 'withLayout' not in item else not _layout_path(item['withLayout'])) for item in new_slides)
        or (new_slides and order is None)):
        raise ValueError('native_office_operations_invalid')
    shapes = _records(operation, 'shapes', {'slideIndex', 'kind', 'geometry'})
    for item in shapes:
        geometry = item['geometry']
        if (not isinstance(item['kind'], str) or item['kind'] not in _SHAPE_PRESETS or not isinstance(geometry, dict)
            or set(geometry) != {'x', 'y', 'width', 'height'} or any(not _number(geometry[key], -100_000, 100_000) for key in ('x', 'y'))
            or any(not _number(geometry[key], 1, 100_000) for key in ('width', 'height'))):
            raise ValueError('native_office_operations_invalid')
    tables = _records(operation, 'tables', {'slideIndex', 'rows', 'cols'})
    if len(tables) > 100 or any(not isinstance(item[key], int) or isinstance(item[key], bool) or not 1 <= item[key] <= 75 for item in tables for key in ('rows', 'cols')):
        raise ValueError('native_office_operations_invalid')
    shape_styles = _records(operation, 'shapeStyles', {'slideIndex', 'elementId'}, {'fill', 'stroke'})
    for item in shape_styles:
        fill, stroke = item.get('fill'), item.get('stroke', ...)
        if (not isinstance(item['elementId'], str) or not item['elementId'] or ('fill' not in item and 'stroke' not in item)
            or ('fill' in item and fill != 'none' and (not isinstance(fill, str) or not _HEX_COLOR.fullmatch(fill)))
            or (stroke is not ... and stroke is not None and (not isinstance(stroke, dict) or set(stroke) != {'color', 'widthPt'}
                or not isinstance(stroke['color'], str) or not _HEX_COLOR.fullmatch(stroke['color']) or not _number(stroke['widthPt'], 0.01, 100)))):
            raise ValueError('native_office_operations_invalid')
    shape_kinds = _records(operation, 'shapeKinds', {'slideIndex', 'elementId', 'kind'})
    if any(not isinstance(item['elementId'], str) or not item['elementId'] or not isinstance(item['kind'], str)
           or item['kind'] not in _SHAPE_PRESETS or item['kind'] in _LINE_PRESETS for item in shape_kinds):
        raise ValueError('native_office_operations_invalid')
    sections = operation.get('sections', [])
    if (not isinstance(sections, list) or len(sections) > 100
        or any(not isinstance(item, dict) or set(item) != {'slideIndex', 'name'} or not _slide_index(item['slideIndex'])
               or not isinstance(item['name'], str) or not item['name'].strip() or len(item['name']) > 100
               or any(ord(char) < 32 or ord(char) == 127 for char in item['name']) for item in sections)):
        raise ValueError('native_office_operations_invalid')
    header_footer = operation.get('headerFooter')
    if header_footer is not None and (
        not isinstance(header_footer, dict) or set(header_footer) != {'footer', 'slideNum', 'date', 'dateAuto'}
        or any(header_footer[key] is not None and (not isinstance(header_footer[key], str) or len(header_footer[key]) > 500
               or any(ord(char) < 32 and char not in '\t\n' or ord(char) == 127 for char in header_footer[key])) for key in ('footer', 'date'))
        or any(not isinstance(header_footer[key], bool) for key in ('slideNum', 'dateAuto'))):
        raise ValueError('native_office_operations_invalid')
    table_cells = _records(operation, 'tableCells', {'slideIndex', 'elementId', 'row', 'col', 'text'})
    if len(table_cells) > 2000 or any(not isinstance(item['elementId'], str) or not item['elementId'] or not isinstance(item['text'], str) or len(item['text']) > 10000
           or any(not isinstance(item[key], int) or isinstance(item[key], bool) or item[key] < 0 for key in ('row', 'col')) for item in table_cells):
        raise ValueError('native_office_operations_invalid')
    charts = _records(operation, 'charts', {'slideIndex', 'kind', 'categories', 'series'})
    def _label(value: Any) -> bool:
        return isinstance(value, str) and len(value) <= 100 and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    if len(charts) > 50 or any(
        item['kind'] not in _CHART_KINDS or not isinstance(item['categories'], list) or not 1 <= len(item['categories']) <= 100
        or not all(_label(value) for value in item['categories']) or not isinstance(item['series'], list) or not 1 <= len(item['series']) <= 20
        or any(not isinstance(series, dict) or set(series) != {'name', 'values'} or not _label(series['name']) or not isinstance(series['values'], list)
               or len(series['values']) != len(item['categories']) or not all(_number(value, -1e15, 1e15) for value in series['values']) for series in item['series'])
        for item in charts):
        raise ValueError('native_office_operations_invalid')
    # 整页动画列表覆盖写（动画窗格/无/动作路径/按段）：结构在此粗校验，条目语义与来源身份由桥接按真实动画表校验。
    animation_sequences = _records(operation, 'animationSequences', {'slideIndex', 'items'})
    if any(not isinstance(item['items'], list) or len(item['items']) > 500 or any(not isinstance(entry, dict) for entry in item['items'])
           for item in animation_sequences) or len({item['slideIndex'] for item in animation_sequences}) != len(animation_sequences):
        raise ValueError('native_office_operations_invalid')
    smart_arts = _records(operation, 'smartArts', {'slideIndex', 'layout', 'items'})
    if len(smart_arts) > 50 or any(
        item['layout'] not in {'list', 'process', 'cycle', 'hierarchy', 'pyramid', 'matrix', 'venn'} or not isinstance(item['items'], list)
        or not 1 <= len(item['items']) <= 8 or not all(isinstance(text, str) and len(text) <= 200 and not any(ord(char) < 32 or ord(char) == 127 for char in text) for text in item['items'])
        for item in smart_arts):
        raise ValueError('native_office_operations_invalid')
    reset_layouts = operation.get('resetLayouts', [])
    if (not isinstance(reset_layouts, list) or len(reset_layouts) > 500 or any(not _slide_index(index) for index in reset_layouts)
        or len(set(reset_layouts)) != len(reset_layouts)):
        raise ValueError('native_office_operations_invalid')
    # 删除来源页（固定源 deleteSlide）：只列来源索引；order 必须给出保留页，引擎再核对引用与页数。
    deleted_slides = operation.get('deletedSlides', [])
    if (not isinstance(deleted_slides, list) or len(deleted_slides) > 500 or any(not _slide_index(index) for index in deleted_slides)
        or len(set(deleted_slides)) != len(deleted_slides) or (deleted_slides and order is None)):
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
    return {'edits': bridge_edits, 'order': order, 'new_slides': new_slides, 'deleted_slides': deleted_slides, 'reset_layouts': reset_layouts, 'shapes': shapes, 'tables': tables, 'shape_styles': shape_styles, 'shape_kinds': shape_kinds, 'sections': sections, 'header_footer': header_footer, 'table_cells': table_cells, 'charts': charts, 'smart_arts': smart_arts, 'animation_sequences': animation_sequences, 'theme': theme, 'slide_size': slide_size, 'transitions': transitions, 'animations': animations,
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
