"""独立原生 XLSX/PPTX 的引擎适配，不参与报告发布或 AI 候选登记。"""
from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Set
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from PIL import Image

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

_ALLOWED_KEYS = {'notesEdits', 'linkEdits', 'clipboardPastes', 'groupEdits', 'elementOrders', 'images', 'pictureReplacements', 'pictureCrops', 'pictureOpacities', 'chartEdits', 'kind', 'edits', 'order', 'newSlides', 'deletedSlides', 'resetLayouts', 'shapes', 'tables', 'shapeStyles', 'shapeKinds', 'sections', 'headerFooter', 'tableCells', 'tableStyles', 'tableStructures', 'charts', 'smartArts', 'theme', 'slideSize', 'hiddenSlides', 'commentEdits', 'transitions', 'animations', 'animationSequences', 'slideLayouts', 'backgrounds', 'textBoxes', 'deletions', 'textFormatting', 'paragraphFormatting'}
# 对齐既有 workbook bridge/operations.ts 顶层协议；内部参数仍交共享引擎验证。
_XLSX_FIELDS = {
    'applyCellEdits': {'edits'}, 'applySheetMerges': {'sheetName', 'ranges'},
    'applyChartAdditions': {'additions'}, 'applyChartDeletions': {'deletions'}, 'applyChartEdits': {'edits'},
    'applySheetEdits': {'plan'}, 'applyRowColumnOps': {'sheetName', 'ops'},
    'applyCellShift': {'sheetName', 'range', 'shift'},
    'applyDvRules': {'rules'}, 'applyCfRules': {'rules'}, 'applySheetNotes': {'sheetName', 'notes'},
    'patchSheetNotes': {'sheetName', 'sourceIdentity', 'changes'},
    'applySheetFilter': {'sheetName', 'filter', 'hiddenRows', 'visibilityRange'},
    'appendSheetSparklines': {'sheetName', 'groups'},
    'replaceSheetDataValidations': {'sheetName', 'rules'},
    'replaceSheetConditionalFormats': {'sheetName', 'rules'},
    'addPivot': {'addition'}, 'applyColumnWidths': {'sheetName', 'entries'},
    'applySheetOutline': {'sheetName', 'rows', 'columns', 'summaryBelow', 'summaryRight'},
    'applyRowHeights': {'sheetName', 'entries'}, 'applyPageSetups': {'setups'},
    'applyTableAdditions': {'additions'}, 'applyTableEdits': {'edits'}, 'refreshPivotCaches': set(),
    'applyPivotLayoutExpansions': {'updates', 'controlRequest'}, 'expandPivotOutputs': {'expansions'},
    'upsertPivotControl': {'request'}, 'removePivotControl': {'request'},
    'applyDefinedNames': {'plan'}, 'protectSheet': {'sheetName', 'protect'},
    'setSheetEditableRanges': {'sheetName', 'ranges'},
    'protectWorkbookStructure': {'lockStructure'}, 'setThemePart': {'themePath', 'state'},
    'sortRange': {'sheetName', 'spec'},
}
_TRANSITIONS = {'none', 'morph', 'fade', 'push', 'wipe', 'split', 'circle', 'cover', 'pull', 'dissolve', 'zoom', 'random'}
# ECMA-376 ST_SlideSizeCoordinate: 1 to 56 inches in EMU.
_MIN_SLIDE_EMU, _MAX_SLIDE_EMU = 914400, 51206400
# 与桥和前端的 ECMAScript trim 保持一致。
_COMMENT_WHITESPACE = '\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'
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



def _native_media_edits(operation: dict[str, Any]) -> tuple[list, list, list]:
    """上传图片与原生图表沿用同一修订，不接收本机文件路径或 AI 候选身份。"""
    images = _records(operation, 'images', {'slideIndex', 'bytesBase64', 'extension', 'geometry'}, {'descr'})
    replacements = _records(operation, 'pictureReplacements',
        {'slideIndex', 'elementId', 'expectedSha256', 'expectedSize', 'bytesBase64', 'extension'})
    total = 0
    for records in (images, replacements):
        if len(records) > 50:
            raise ValueError('native_office_operations_invalid')
        for item in records:
            value = item['bytesBase64']
            if (not isinstance(value, str) or len(value) > 8 * 1024 * 1024
                or not isinstance(item['extension'], str) or item['extension'] not in {'png', 'jpg'}):
                raise ValueError('native_office_operations_invalid')
            try:
                data = base64.b64decode(value, validate=True)
                if base64.b64encode(data).decode() != value or len(data) > 6 * 1024 * 1024:
                    raise ValueError('native_office_operations_invalid')
                with Image.open(BytesIO(data)) as image:
                    if image.format != {'png': 'PNG', 'jpg': 'JPEG'}[item['extension']] or image.width * image.height > 100_000_000:
                        raise ValueError('native_office_operations_invalid')
                    image.verify()
            except (ValueError, binascii.Error, OSError, Image.DecompressionBombError) as exc:
                raise ValueError('native_office_operations_invalid') from exc
            total += len(data)
            if total > 8 * 1024 * 1024:
                raise ValueError('native_office_operations_invalid')
    for item in images:
        geometry = item['geometry']
        if (not isinstance(geometry, dict) or set(geometry) != {'x', 'y', 'width', 'height'}
            or any(not _number(geometry[key], 0, 100_000) for key in ('x', 'y'))
            or any(not _number(geometry[key], 0, 100_000) or geometry[key] <= 0 for key in ('width', 'height'))
            or ('descr' in item and (not isinstance(item['descr'], str) or len(item['descr']) > 10000))):
            raise ValueError('native_office_operations_invalid')
    for item in replacements:
        if (not isinstance(item['elementId'], str) or not item['elementId']
            or not isinstance(item['expectedSha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', item['expectedSha256'])
            or not isinstance(item['expectedSize'], int) or isinstance(item['expectedSize'], bool) or item['expectedSize'] < 1):
            raise ValueError('native_office_operations_invalid')
    chart_style_fields = {'title', 'catAxisTitle', 'valAxisTitle', 'legendPos', 'dataLabels', 'gridlines', 'colorScheme', 'gapWidthPct', 'pointColors'}
    charts = _records(operation, 'chartEdits', {'slideIndex', 'elementId'}, {'kind', 'categories', 'series', 'switchRowCol'} | chart_style_fields)
    if len(charts) > 50:
        raise ValueError('native_office_operations_invalid')
    for item in charts:
        if (not isinstance(item['elementId'], str) or not item['elementId']
            or not set(item) & ({'kind', 'categories', 'series', 'switchRowCol'} | chart_style_fields)
            or ('switchRowCol' in item and type(item['switchRowCol']) is not bool)
            or ('kind' in item and (not isinstance(item['kind'], str) or item['kind'] not in _CHART_KINDS))
            or ('categories' in item) != ('series' in item)):
            raise ValueError('native_office_operations_invalid')
        if (('colorScheme' in item and (not isinstance(item['colorScheme'], str) or item['colorScheme'] not in {
                'default', 'colorful', 'colorful2', 'mono-accent1', 'mono-accent2', 'mono-accent3',
                'mono-accent4', 'mono-accent5', 'mono-accent6', 'blue', 'warm', 'cool', 'mono'}))
            or ('gapWidthPct' in item and (type(item['gapWidthPct']) is not int or not 0 <= item['gapWidthPct'] <= 500))):
            raise ValueError('native_office_operations_invalid')
        if 'pointColors' in item:
            points = item['pointColors']
            if (not isinstance(points, dict) or not points
                or any(not isinstance(si, str) or not re.fullmatch(r'0|[1-9][0-9]*', si) or len(si) > 2 or int(si) >= 20
                    or not isinstance(row, dict) or not row
                    or any(not isinstance(pi, str) or not re.fullmatch(r'0|[1-9][0-9]*', pi) or len(pi) > 2 or int(pi) >= 100
                        or (color is not None and (not isinstance(color, str) or not re.fullmatch(r'#[a-fA-F0-9]{6}', color)))
                        for pi, color in row.items()) for si, row in points.items())):
                raise ValueError('native_office_operations_invalid')
        if (any(key in item and (not isinstance(item[key], str) or len(item[key]) > 1000
                or any(ord(c) < 32 or ord(c) == 127 or 0xd800 <= ord(c) <= 0xdfff or ord(c) in {0xfffe, 0xffff} for c in item[key]))
                for key in ('title', 'catAxisTitle', 'valAxisTitle'))
            or ('legendPos' in item and (not isinstance(item['legendPos'], str) or item['legendPos'] not in {'b', 't', 'r', 'l', 'none'}))
            or any(key in item and type(item[key]) is not bool for key in ('dataLabels', 'gridlines'))):
            raise ValueError('native_office_operations_invalid')
        if 'categories' in item:
            categories, series = item['categories'], item['series']
            def label(value):
                return isinstance(value, str) and len(value) <= 100 and not any(ord(c) < 32 or ord(c) == 127 for c in value)
            if (not isinstance(categories, list) or not 1 <= len(categories) <= 100 or not all(label(value) for value in categories)
                or not isinstance(series, list) or not 1 <= len(series) <= 20
                or any(not isinstance(entry, dict) or set(entry) != {'name', 'values'} or not label(entry['name'])
                    or not isinstance(entry['values'], list) or len(entry['values']) != len(categories)
                    or any(not _number(value, -1e100, 1e100) for value in entry['values']) for entry in series)):
                raise ValueError('native_office_operations_invalid')
    for records in (replacements, charts):
        keys = [(item['slideIndex'], item['elementId']) for item in records]
        if len(set(keys)) != len(keys):
            raise ValueError('native_office_operations_invalid')
    return images, replacements, charts


def _native_picture_opacities(operation: dict[str, Any]) -> list[dict[str, Any]]:
    """固定源 Picture Format ▸ Transparency：按媒体身份绑定的整图不透明度（0–1，整数百分比）。"""
    items = _records(operation, 'pictureOpacities', {'slideIndex', 'elementId', 'expectedSha256', 'expectedSize', 'opacity'})
    if len(items) > 50:
        raise ValueError('native_office_operations_invalid')
    seen = set()
    for item in items:
        key = (item['slideIndex'], item['elementId'])
        if (not isinstance(item['elementId'], str) or not item['elementId']
            or not isinstance(item['expectedSha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', item['expectedSha256'])
            or not isinstance(item['expectedSize'], int) or isinstance(item['expectedSize'], bool) or item['expectedSize'] < 1
            or not _number(item['opacity'], 0, 1) or abs(round(item['opacity'] * 100) - item['opacity'] * 100) > 1e-9
            or key in seen):
            raise ValueError('native_office_operations_invalid')
        seen.add(key)
    return items


def _native_picture_crops(operation: dict[str, Any]) -> list[dict[str, Any]]:
    crops = _records(operation, 'pictureCrops',
        {'slideIndex', 'elementId', 'expectedSha256', 'expectedSize', 'srcRect', 'geometry'})
    if len(crops) > 50:
        raise ValueError('native_office_operations_invalid')
    seen = set()
    for item in crops:
        key = (item['slideIndex'], item['elementId'])
        rect, geometry = item['srcRect'], item['geometry']
        if (not isinstance(item['elementId'], str) or not item['elementId']
            or not isinstance(item['expectedSha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', item['expectedSha256'])
            or not isinstance(item['expectedSize'], int) or isinstance(item['expectedSize'], bool) or item['expectedSize'] < 1
            or key in seen
            or (rect is not None and (not isinstance(rect, dict) or set(rect) != {'l', 't', 'r', 'b'}
                or any(not _number(rect[side], 0, 1) or rect[side] >= 1 for side in ('l', 't', 'r', 'b'))
                or rect['l'] + rect['r'] >= 1 or rect['t'] + rect['b'] >= 1))
            or not isinstance(geometry, dict) or set(geometry) != {'x', 'y', 'width', 'height'}
            or any(not _number(geometry[axis], -100_000, 100_000) for axis in ('x', 'y'))
            or any(not _number(geometry[axis], 0, 100_000) or geometry[axis] <= 0 for axis in ('width', 'height'))):
            raise ValueError('native_office_operations_invalid')
        seen.add(key)
    return crops


def _native_element_orders(operation: dict[str, Any]) -> list[dict[str, Any]]:
    orders = _records(operation, 'elementOrders', {'slideIndex', 'elementIds'})
    seen = set()
    if len(orders) > 500:
        raise ValueError('native_office_operations_invalid')
    for item in orders:
        ids = item['elementIds']
        if (item['slideIndex'] in seen or not isinstance(ids, list) or len(ids) > 500
            or any(not isinstance(value, str) or not value or len(value) > 200 for value in ids)
            or len(set(ids)) != len(ids)):
            raise ValueError('native_office_operations_invalid')
        seen.add(item['slideIndex'])
    return orders


def _native_group_edits(operation: dict[str, Any]) -> list[dict[str, Any]]:
    groups = _records(operation, 'groupEdits', {'slideIndex', 'kind'}, {'elementIds', 'elementId'})
    seen = set()
    if len(groups) > 50:
        raise ValueError('native_office_operations_invalid')
    for item in groups:
        if item['slideIndex'] in seen:
            raise ValueError('native_office_operations_invalid')
        seen.add(item['slideIndex'])
        if item['kind'] == 'group':
            ids = item.get('elementIds')
            if (set(item) != {'slideIndex', 'kind', 'elementIds'} or not isinstance(ids, list)
                or not 2 <= len(ids) <= 500
                or any(not isinstance(value, str) or not value or len(value) > 200 for value in ids)
                or len(set(ids)) != len(ids)):
                raise ValueError('native_office_operations_invalid')
        elif item['kind'] == 'ungroup':
            if (set(item) != {'slideIndex', 'kind', 'elementId'} or not isinstance(item.get('elementId'), str)
                or not item['elementId'] or len(item['elementId']) > 200):
                raise ValueError('native_office_operations_invalid')
        else:
            raise ValueError('native_office_operations_invalid')
    if not groups:
        return groups
    if any(key in operation for key in ('theme', 'slideSize', 'headerFooter')):
        raise ValueError('native_group_conflict')
    for key, values in operation.items():
        if key in {'groupEdits', 'order'} or not isinstance(values, list):
            continue
        if key in {'deletedSlides', 'resetLayouts'} and any(index in seen for index in values):
            raise ValueError('native_group_conflict')
        if key == 'newSlides' and any(isinstance(item, dict) and
            (item.get('duplicateOf') in seen or item.get('layoutFrom') in seen) for item in values):
            raise ValueError('native_group_conflict')
        if any(isinstance(item, dict) and item.get('slideIndex') in seen for item in values):
            raise ValueError('native_group_conflict')
    return groups


def _native_link_edits(operation: dict[str, Any]) -> list[dict[str, Any]]:
    records = _records(operation, 'linkEdits', {'slideIndex', 'elementId', 'target'})
    seen = set()
    if len(records) > 50:
        raise ValueError('native_office_operations_invalid')
    for item in records:
        element_id, target = item['elementId'], item['target']
        if not isinstance(element_id, str) or not 1 <= len(element_id) <= 200:
            raise ValueError('native_office_operations_invalid')
        identity = (item['slideIndex'], element_id)
        if identity in seen:
            raise ValueError('native_office_operations_invalid')
        seen.add(identity)
        if target is None:
            continue
        if not isinstance(target, dict):
            raise ValueError('native_office_operations_invalid')
        if target.get('kind') == 'url' and set(target) == {'kind', 'url'}:
            url = target['url']
            if not isinstance(url, str) or not 1 <= len(url) <= 2048 or any(ord(c) <= 32 or 127 <= ord(c) <= 159 for c in url):
                raise ValueError('native_office_operations_invalid')
            try:
                parsed = urlsplit(url)
                if parsed.scheme.lower() not in {'http', 'https', 'mailto'} or (parsed.scheme.lower() == 'mailto' and not parsed.path) or (parsed.scheme.lower() != 'mailto' and not parsed.hostname):
                    raise ValueError('native_office_operations_invalid')
            except ValueError as error:
                raise ValueError('native_office_operations_invalid') from error
        elif target.get('kind') == 'slide' and set(target) == {'kind', 'slideIndex'}:
            if not _slide_index(target['slideIndex']):
                raise ValueError('native_office_operations_invalid')
        else:
            raise ValueError('native_office_operations_invalid')
    return records


def _native_clipboard_pastes(operation: dict[str, Any]) -> list[dict[str, Any]]:
    records = _records(operation, 'clipboardPastes', {'sourceSlideIndex', 'elementIds', 'slideIndex', 'dx', 'dy'})
    total = 0
    if len(records) > 50:
        raise ValueError('native_office_operations_invalid')
    for item in records:
        if not _slide_index(item['sourceSlideIndex']):
            raise ValueError('native_office_operations_invalid')
        ids = item['elementIds']
        if not isinstance(ids, list) or not 1 <= len(ids) <= 500 or any(not isinstance(value, str) or not 1 <= len(value) <= 200 for value in ids) or len(set(ids)) != len(ids):
            raise ValueError('native_office_operations_invalid')
        total += len(ids)
        if total > 500 or not all(_number(item[key], -100000, 100000) for key in ('dx', 'dy')):
            raise ValueError('native_office_operations_invalid')
    return records


def _native_notes_edits(operation: dict[str, Any]) -> list[dict[str, Any]]:
    records = _records(operation, 'notesEdits', {'slideIndex', 'text'})
    if len(records) > 200:
        raise ValueError('native_office_operations_invalid')
    seen, total, result = set(), 0, []
    for item in records:
        value, index = item['text'], item['slideIndex']
        if not isinstance(value, str) or index in seen:
            raise ValueError('native_office_operations_invalid')
        size = sum(2 if ord(char) > 0xffff else 1 for char in value)
        total += size
        if (size > 20000 or total > 200000
            or any(not (ord(char) in {9, 10, 13} or 0x20 <= ord(char) <= 0xd7ff
                        or 0xe000 <= ord(char) <= 0xfffd or 0x10000 <= ord(char) <= 0x10ffff) for char in value)
            or index in operation.get('deletedSlides', [])
            or any(isinstance(slide, dict) and slide.get('duplicateOf') == index for slide in operation.get('newSlides', []))):
            raise ValueError('native_office_operations_invalid')
        seen.add(index)
        result.append({'slideIndex': index, 'text': value.replace('\r\n', '\n').replace('\r', '\n').rstrip('\n')})
    return result


def _pptx_arguments(operation: dict[str, Any]) -> dict[str, Any]:
    if operation.get('kind') != 'editSlides' or not set(operation).issubset(_ALLOWED_KEYS):
        raise ValueError('native_office_operations_invalid')
    native_images, picture_replacements, chart_edits = _native_media_edits(operation)
    picture_crops = _native_picture_crops(operation)
    picture_opacities = _native_picture_opacities(operation)
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
    table_structures = _records(operation, 'tableStructures', {'slideIndex', 'elementId', 'kind', 'index'}, {'before'})
    if len(table_structures) > 100:
        raise ValueError('native_office_operations_invalid')
    structure_slides = set()
    for item in table_structures:
        if (not isinstance(item['elementId'], str) or not item['elementId'] or not isinstance(item['kind'], str)
            or item['kind'] not in {'insert-row', 'delete-row', 'insert-col', 'delete-col'} or not isinstance(item['index'], int) or isinstance(item['index'], bool) or not 0 <= item['index'] < 75
            or (not isinstance(item.get('before'), bool) if item['kind'].startswith('insert-') else 'before' in item)
            or item['slideIndex'] in structure_slides):
            raise ValueError('native_office_operations_invalid')
        structure_slides.add(item['slideIndex'])
    table_flags = {'firstRow', 'lastRow', 'firstCol', 'lastCol', 'bandRow', 'bandCol', 'rtl'}
    table_presets = {'none', 'lightGrid', 'zebraBlue', 'zebraGray', 'headerDarkBlue', 'headerOrange', 'noBorder', 'fullBorder'}
    table_styles = _records(operation, 'tableStyles', {'slideIndex', 'elementId'}, {'styleName', 'shadingColor', 'borderPreset', 'cellShadings'} | table_flags)
    if len(table_styles) > 500:
        raise ValueError('native_office_operations_invalid')
    style_keys = set()
    cell_shading_count = 0
    table_colors = {'none', '#FFFFFF', '#F2F2F2', '#DAEEF3', '#EBF3FB', '#D6E4F0', '#FFF2CC', '#FFE6CC', '#FCE4D6', '#E2EFDA', '#E6E6FF'}
    for item in table_styles:
        key = (item['slideIndex'], item['elementId']) if isinstance(item['elementId'], str) else None
        if (key is None or not item['elementId'] or key in style_keys or not ({'styleName', 'shadingColor', 'borderPreset', 'cellShadings'} | table_flags) & item.keys()
            or ('styleName' in item and (not isinstance(item['styleName'], str) or item['styleName'] not in table_presets))
            or any(key in item and not isinstance(item[key], bool) for key in table_flags)
            or ('shadingColor' in item and (not isinstance(item['shadingColor'], str) or item['shadingColor'] not in {'none', '#FFFFFF', '#F2F2F2', '#DAEEF3', '#EBF3FB', '#D6E4F0', '#FFF2CC', '#FFE6CC', '#FCE4D6', '#E2EFDA', '#E6E6FF'}))
            or ('borderPreset' in item and (not isinstance(item['borderPreset'], str) or item['borderPreset'] not in {'all', 'none'}))):
            raise ValueError('native_office_operations_invalid')
        if 'cellShadings' in item:
            cells = item['cellShadings']
            if not isinstance(cells, list) or not cells:
                raise ValueError('native_office_operations_invalid')
            cell_shading_count += len(cells)
            if cell_shading_count > 500:
                raise ValueError('native_office_operations_invalid')
            cell_keys = set()
            for cell in cells:
                if (not isinstance(cell, dict) or set(cell) != {'row', 'col', 'shadingColor'}
                    or any(not isinstance(cell[axis], int) or isinstance(cell[axis], bool) or not 0 <= cell[axis] < 75 for axis in ('row', 'col'))
                    or not isinstance(cell['shadingColor'], str) or cell['shadingColor'] not in table_colors
                    or (cell['row'], cell['col']) in cell_keys):
                    raise ValueError('native_office_operations_invalid')
                cell_keys.add((cell['row'], cell['col']))
        style_keys.add(key)
    table_cells = _records(operation, 'tableCells', {'slideIndex', 'elementId', 'row', 'col', 'text'})
    if len(table_cells) > 500 or any(not isinstance(item['elementId'], str) or not item['elementId'] or not isinstance(item['text'], str) or len(item['text']) > 10000 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', item['text'])
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
    hidden_slides = _records(operation, 'hiddenSlides', {'slideIndex', 'hidden'})
    if (any(not isinstance(item['hidden'], bool) or item['slideIndex'] in deleted_slides for item in hidden_slides)
        or len({item['slideIndex'] for item in hidden_slides}) != len(hidden_slides)):
        raise ValueError('native_office_operations_invalid')
    comment_edits = _records(operation, 'commentEdits', {'slideIndex', 'kind'}, {'clientId', 'text', 'authorId', 'idx'})
    comment_ids, comment_deletes = set(), set()
    for item in comment_edits:
        if item['slideIndex'] in deleted_slides:
            raise ValueError('native_office_operations_invalid')
        if item['kind'] == 'add':
            value, client_id = item.get('text'), item.get('clientId')
            if (set(item) != {'slideIndex', 'kind', 'clientId', 'text'}
                or not isinstance(value, str) or not value.strip(_COMMENT_WHITESPACE)
                or sum(2 if ord(char) > 0xffff else 1 for char in value) > 10000
                or any(not (ord(char) in {9, 10, 13} or 0x20 <= ord(char) <= 0xd7ff
                            or 0xe000 <= ord(char) <= 0xfffd or 0x10000 <= ord(char) <= 0x10ffff) for char in value)
                or not isinstance(client_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', client_id)
                or client_id in comment_ids):
                raise ValueError('native_office_operations_invalid')
            comment_ids.add(client_id)
        elif item['kind'] == 'delete':
            if (set(item) != {'slideIndex', 'kind', 'authorId', 'idx'}
                or any(type(item.get(key)) is not int or not 0 <= item[key] <= 9007199254740991 for key in ('authorId', 'idx'))):
                raise ValueError('native_office_operations_invalid')
            identity = (item['slideIndex'], item['authorId'], item['idx'])
            if identity in comment_deletes:
                raise ValueError('native_office_operations_invalid')
            comment_deletes.add(identity)
        else:
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
    return {'edits': bridge_edits, 'order': order, 'new_slides': new_slides, 'deleted_slides': deleted_slides, 'reset_layouts': reset_layouts, 'shapes': shapes, 'tables': tables, 'shape_styles': shape_styles, 'shape_kinds': shape_kinds, 'sections': sections, 'header_footer': header_footer, 'table_cells': table_cells, 'table_styles': table_styles, 'table_structures': table_structures, 'charts': charts, 'smart_arts': smart_arts, 'animation_sequences': animation_sequences, 'theme': theme, 'slide_size': slide_size, 'hidden_slides': hidden_slides, 'comment_edits': comment_edits, 'transitions': transitions, 'animations': animations,
        'slide_layouts': layouts, 'backgrounds': backgrounds, 'text_boxes': text_boxes, 'deletions': deletions,
        'paragraph_formatting': paragraph_formatting, 'native_images': native_images,
        'picture_replacements': picture_replacements, 'picture_crops': picture_crops, 'picture_opacities': picture_opacities, 'chart_edits': chart_edits,
        'element_orders': _native_element_orders(operation), 'group_edits': _native_group_edits(operation), 'notes_edits': _native_notes_edits(operation), 'link_edits': _native_link_edits(operation), 'clipboard_pastes': _native_clipboard_pastes(operation)}


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
                if not isinstance(kind, str) or kind not in _XLSX_FIELDS:
                    raise ValueError('native_office_operations_invalid')
                allowed = {'kind', *_XLSX_FIELDS[kind]}
                if kind == 'applySheetOutline':
                    if not {'kind', 'sheetName'} <= set(operation) <= allowed:
                        raise ValueError('native_office_operations_invalid')
                elif kind == 'applyPivotLayoutExpansions':
                    if not {'kind', 'updates'} <= set(operation) <= allowed:
                        raise ValueError('native_office_operations_invalid')
                elif kind == 'applySheetFilter':
                    if not {'kind', 'sheetName', 'filter'} <= set(operation) <= allowed:
                        raise ValueError('native_office_operations_invalid')
                elif set(operation) != allowed:
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
