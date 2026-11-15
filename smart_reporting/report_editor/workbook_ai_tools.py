"""源 sheets/ai/tools.ts 的服务端适配：只读冻结草稿，提案只进入预览。

固定源 f8c17004fb730df11f0f743164ffd8b4281bb38c；沿用源工具名与 DSL 字段，
实际修改复用既有 workbook engine。导航、新文件签发不属于此候选权限。
"""
from __future__ import annotations

import math
import re
from builtins import range as iter_range
from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from agno.tools import Toolkit
from openpyxl.formula import Tokenizer
from openpyxl.utils.cell import get_column_letter, quote_sheetname, range_boundaries

from ..office.ai_skills import WORKBOOK_GUIDES, source_workbook_guide
from .workbook_ai import WorkbookAIProposal
from .workbook_ai_charts import translate_chart_deletion, validate_chart_candidates
from .workbook_ai_page_setup import page_setup_patch
from .workbook_ai_structure import (
    AXIS_SIZE_SOURCE_OPS,
    AXIS_VISIBILITY_SOURCE_OPS,
    ROW_COLUMN_SOURCE_OPS,
    SHEET_LIFECYCLE_OPS,
    SHEET_SOURCE_OPS,
    translate_axis_size,
    translate_axis_visibility,
    translate_row_column_operation,
    translate_sheet_operation,
)
from .workbook_search import find_cell_indexes

_CELL_SOURCE_OPS = {'set_cell', 'set_formula', 'clear_cell', 'set_range', 'clear_range'}
_RANGE_VALUE_KINDS = {'clearCellRange', 'replaceRangeText'}
_MAX_EXPANDED_CELL_EDITS = 2000
_MAX_CLEAR_RANGE_CELLS = 200000


def _bounds(address: str) -> tuple[int, int, int, int]:
    if not isinstance(address, str):
        raise ValueError('workbook_ai_range_invalid')
    parts = [part.strip().upper() for part in address.strip().split(':')]
    if not 1 <= len(parts) <= 2 or any(
        re.fullmatch(r'\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}', part) is None for part in parts
    ):
        raise ValueError('workbook_ai_range_invalid')
    c0, r0, _, _ = range_boundaries(parts[0])
    c1, r1, _, _ = range_boundaries(parts[-1])
    r0, r1 = min(r0, r1), max(r0, r1)
    c0, c1 = min(c0, c1), max(c0, c1)
    if not (1 <= r0 <= r1 <= 1048576 and 1 <= c0 <= c1 <= 16384):
        raise ValueError('workbook_ai_range_invalid')
    return r0 - 1, r1 - 1, c0 - 1, c1 - 1


def _cell_address(address: str) -> str:
    if not isinstance(address, str) or ':' in address:
        raise ValueError('workbook_ai_range_invalid')
    row, _, column, _ = _bounds(address)
    return f'{get_column_letter(column + 1)}{row + 1}'


def _source_range_values(operation: dict[str, Any]) -> tuple[tuple[int, int, int, int], list[list[Any]]]:
    shape = {'op', 'sheetId'}
    if not isinstance(operation.get('sheetId'), str) or not operation['sheetId']:
        raise ValueError('workbook_ai_range_invalid')
    if operation['op'] == 'clear_range':
        if set(operation) != shape | {'range'}:
            raise ValueError('workbook_ai_range_invalid')
        bounds = _bounds(operation['range'])
        r0, r1, c0, c1 = bounds
        height, width = r1 - r0 + 1, c1 - c0 + 1
        if height * width > _MAX_EXPANDED_CELL_EDITS:
            raise ValueError('workbook_ai_range_too_large')
        return bounds, [[None] * width for _ in range(height)]
    values = operation.get('values')
    if (set(operation) - (shape | {'values', 'start', 'range'})
            or not isinstance(values, list) or not 1 <= len(values) <= 500
            or not isinstance(values[0], list) or not 1 <= len(values[0]) <= 100):
        raise ValueError('workbook_ai_range_invalid')
    height, width = len(values), len(values[0])
    if any(not isinstance(row, list) or len(row) != width for row in values):
        raise ValueError('workbook_ai_range_invalid')
    if height * width > _MAX_EXPANDED_CELL_EDITS:
        raise ValueError('workbook_ai_range_too_large')
    if 'range' in operation:
        r0, r1, c0, c1 = _bounds(operation['range'])
        if (r1 - r0 + 1, c1 - c0 + 1) != (height, width):
            raise ValueError('workbook_ai_range_invalid')
        if 'start' in operation:
            start_row, _, start_col, _ = _bounds(_cell_address(operation['start']))
            if (start_row, start_col) != (r0, c0):
                raise ValueError('workbook_ai_range_invalid')
    else:
        r0, _, c0, _ = _bounds(_cell_address(operation.get('start')))
        r1, c1 = r0 + height - 1, c0 + width - 1
        if r1 >= 1048576 or c1 >= 16384:
            raise ValueError('workbook_ai_range_invalid')
    return (r0, r1, c0, c1), values


def clear_range_bounds(address: str) -> tuple[int, int, int, int]:
    r0, r1, c0, c1 = _bounds(address)
    if (r1 - r0 + 1) * (c1 - c0 + 1) > _MAX_CLEAR_RANGE_CELLS:
        raise ValueError('workbook_ai_range_too_large')
    return r0, r1, c0, c1

def _range_address(address: str) -> str:
    r0, r1, c0, c1 = _bounds(address)
    first = f'{get_column_letter(c0 + 1)}{r0 + 1}'
    last = f'{get_column_letter(c1 + 1)}{r1 + 1}'
    return first if first == last else f'{first}:{last}'


def _matches_expected_value(actual: Any, expected: Any) -> bool:
    # Source uses JS strict scalar equality: numbers may compare across Python
    # int/float, but True must never satisfy expectedValue=1 (or vice versa).
    if type(expected) not in (str, int, float, bool, type(None)) or (
        type(expected) is float and not math.isfinite(expected)
    ):
        raise ValueError('workbook_ai_precondition_invalid')
    if type(actual) is bool or type(expected) is bool:
        return type(actual) is type(expected) and actual == expected
    return actual == expected


def _sparkline_addition(operation: dict[str, Any], sheet_name: str) -> dict[str, Any]:
    allowed = {'op', 'sheetId', 'type', 'dataRange', 'targetCell', 'color'}
    kind, color = operation.get('type'), operation.get('color')
    if (set(operation) - allowed or kind not in ('line', 'column', 'stacked')
            or ('color' in operation and (not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color)))):
        raise ValueError('workbook_ai_sparkline_invalid')
    first_row, last_row, first_col, last_col = _bounds(operation.get('dataRange'))
    row_count = min(200, last_row - first_row + 1)
    dest_row, dest_col = first_row, last_col + 1
    if 'targetCell' in operation:
        dest_row, end_row, dest_col, end_col = _bounds(operation['targetCell'])
        if dest_row != end_row or dest_col != end_col:
            raise ValueError('workbook_ai_sparkline_invalid')
    if first_col == last_col or dest_col >= 16384 or dest_row + row_count > 1048576:
        raise ValueError('workbook_ai_sparkline_invalid')
    first_label = get_column_letter(first_col + 1)
    last_label = get_column_letter(last_col + 1)
    dest_label = get_column_letter(dest_col + 1)
    sheet_ref = quote_sheetname(sheet_name)
    cells = []
    for offset in range(row_count):
        row = first_row + offset + 1
        cells.append({
            'cell': f'{dest_label}{dest_row + offset + 1}',
            'sourceRef': f'{sheet_ref}!${first_label}${row}:${last_label}${row}',
        })
    group = {'type': kind, 'cells': cells}
    if color is not None:
        group['color'] = color
    return {'kind': 'appendSheetSparklines', 'sheetName': sheet_name, 'groups': [group]}


class WorkbookAIToolkit(Toolkit):
    def __init__(self, *, model: dict[str, Any], scope: str, selection: dict[str, Any], preview: Any,
                 navigation_enabled: bool = False):
        self._model, self._scope = deepcopy(model), scope
        self._selection, self._preview = deepcopy(selection), preview
        self.proposal: WorkbookAIProposal | None = None
        self._submitting = False
        self.navigation_enabled = navigation_enabled
        self._navigation: dict[str, Any] | None = None
        self._active_sheet = None
        self._sheets = {sheet['name']: sheet for sheet in self._model['sheets']
                        if scope == 'workbook' or sheet['name'] == selection['sheetName']}
        super().__init__(name='workbook_candidate', tools=[
            self.get_workbook_context, self.read_range, self.read_cells, self.read_formats,
            self.read_sheet_features, self.find_cells, self.aggregate_range,
            self.trace_precedents, self.trace_dependents, self.load_guide,
            self.propose_operations,
        ] + ([self.select_range] if navigation_enabled else []))

    @property
    def navigation(self):
        return deepcopy(self._navigation)

    def select_range(self, range: str, sheetId: str | None = None) -> dict[str, Any]:
        """仅当用户要求移动视图时请求定位；navigation_requested尚未由浏览器确认，不修改数据。"""
        if not self.navigation_enabled:
            raise ValueError("workbook_ai_navigation_unavailable")
        if self.proposal is not None or self._submitting:
            raise ValueError("workbook_ai_proposal_already_submitted")
        sheet = self._sheet(sheetId)
        bounds = _bounds(range)
        self._authorized(sheet, bounds)
        r0, r1, c0, c1 = bounds
        self._navigation = {"sheetName": sheet["name"], "range": _range_address(range),
            "startRow": r0, "endRow": r1, "startColumn": c0, "endColumn": c1}
        self._active_sheet = sheet["name"]
        return {**self.navigation, "status": "navigation_requested", "mutated": False}

    def _sheet(self, sheetId: str | None) -> dict[str, Any]:
        identity = sheetId if sheetId is not None else (
            self._active_sheet or self._selection.get('sheetName') or next(iter(self._sheets))
        )
        if identity not in self._sheets:
            raise ValueError('workbook_ai_selection_mismatch')
        return self._sheets[identity]

    def _authorized(self, sheet: dict[str, Any], bounds: tuple[int, int, int, int]) -> None:
        if self._scope == 'workbook':
            return
        r0, r1, c0, c1 = bounds
        selected = self._selection
        if not (sheet['name'] == selected['sheetName'] and selected['startRow'] <= r0 <= r1 <= selected['endRow']
                and selected['startColumn'] <= c0 <= c1 <= selected['endColumn']):
            raise ValueError('workbook_ai_selection_mismatch')

    def _visible_cells(self, sheet: dict[str, Any]):
        for address, cell in sheet.get('cells', {}).items():
            try:
                self._authorized(sheet, _bounds(address))
            except ValueError:
                continue
            yield address, cell

    def get_workbook_context(self) -> dict[str, Any]:
        """读取授权草稿的工作表名称、数据范围和已知地址；sheetId 使用工作表名称。"""
        sheets = []
        for sheet in self._sheets.values():
            addresses = [address for address, _ in self._visible_cells(sheet)]
            bounds = [_bounds(address) for address in addresses]
            sheets.append({'id': sheet['name'], 'name': sheet['name'],
                           'rows': max((area[1] + 1 for area in bounds), default=0),
                           'columns': max((area[3] + 1 for area in bounds), default=0),
                           'knownAddresses': addresses[:200]})
        return {'scope': self._scope, 'selection': deepcopy(self._selection), 'sheets': sheets,
                'activeSheetId': self._sheet(None)['name'],
                'viewState': 'navigation_requested' if self._navigation else 'captured' if self.navigation_enabled else 'unavailable'}

    def read_range(self, range: str, sheetId: str | None = None) -> dict[str, Any]:
        """读取矩形范围的真实值、公式；最多2000格，越过冻结选区会被拒绝。"""
        sheet = self._sheet(sheetId)
        bounds = _bounds(range)
        self._authorized(sheet, bounds)
        r0, r1, c0, c1 = bounds
        if (r1 - r0 + 1) * (c1 - c0 + 1) > 2000:
            raise ValueError('workbook_ai_read_limit')
        return {'sheetId': sheet['name'], 'range': range, 'cells': {
            f'{get_column_letter(column + 1)}{row + 1}': deepcopy(sheet.get('cells', {}).get(
                f'{get_column_letter(column + 1)}{row + 1}', {'value': None}))
            for row in iter_range(r0, r1 + 1) for column in iter_range(c0, c1 + 1)}}

    def read_cells(self, addresses: list[str], sheetId: str | None = None) -> dict[str, Any]:
        """读取最多100个离散单元格，包含真实值、公式和现有格式。"""
        if not isinstance(addresses, list) or not 1 <= len(addresses) <= 100:
            raise ValueError('workbook_ai_read_limit')
        addresses = [_cell_address(address) for address in addresses]
        sheet = self._sheet(sheetId)
        for address in addresses:
            self._authorized(sheet, _bounds(address))
        return {'sheetId': sheet['name'], 'cells': {address: deepcopy(sheet.get('cells', {}).get(address, {'value': None})) for address in addresses}}

    def read_formats(self, range: str, sheetId: str | None = None) -> dict[str, Any]:
        """读取范围内已有单元格格式；最多200格。"""
        r0, r1, c0, c1 = _bounds(range)
        if (r1 - r0 + 1) * (c1 - c0 + 1) > 200:
            raise ValueError('workbook_ai_read_limit')
        data = self.read_range(range, sheetId)
        return {'sheetId': data['sheetId'], 'formats': {address: {key: value for key, value in cell.items() if key not in {'value', 'formula'}} for address, cell in data['cells'].items() if set(cell) - {'value', 'formula'}}}

    def read_sheet_features(self, sheetId: str | None = None) -> dict[str, Any]:
        """修改合并、筛选、表格、名称和规则前，读取既有状态；选区模式不泄露表外特性。"""
        sheet = self._sheet(sheetId)
        if self._scope == 'range':
            return {'sheetId': sheet['name'], 'scope': 'range', 'features': {}}
        return {'sheetId': sheet['name'], 'features': deepcopy({key: value for key, value in sheet.items() if key not in {'cells', 'path', 'name'}}),
                'definedNames': deepcopy(self._model.get('definedNames', []))}

    def find_cells(self, query: str = '', sheetId: str | None = None, look_in: str = 'both', errors_only: bool = False, max_results: int = 50, regex: bool = False) -> dict[str, Any]:
        """在冻结授权内容中搜索；regex 使用大小写不敏感的 JavaScript 正则，最多200条。"""
        if (not isinstance(query, str) or look_in not in {'values', 'formulas', 'both'}
                or type(max_results) is not int
                or type(regex) is not bool or type(errors_only) is not bool):
            raise ValueError('workbook_ai_search_invalid')
        if not query and not errors_only:
            raise ValueError('workbook_ai_search_invalid')
        max_results = min(max_results, 200) if max_results >= 1 else 50
        entries = []
        sheets = [self._sheet(sheetId)] if sheetId is not None else self._sheets.values()
        for sheet in sheets:
            for address, cell in self._visible_cells(sheet):
                entries.append({'sheetName': sheet['name'], 'address': address, **deepcopy(cell)})
        result = find_cell_indexes(
            [{key: cell[key] for key in ('value', 'formula') if key in cell} for cell in entries],
            query=query, regex=regex, look_in=look_in, errors_only=errors_only, max_results=max_results,
        )
        return {'matches': [entries[index] for index in result['indexes']], 'truncated': result['truncated']}

    def aggregate_range(self, range: str, sheetId: str | None = None, topValues: int = 10) -> dict[str, Any]:
        """统计授权范围内非空数、不同值数、数值合计/均值/极值；最多100万格。"""
        sheet = self._sheet(sheetId)
        bounds = _bounds(range)
        self._authorized(sheet, bounds)
        r0, r1, c0, c1 = bounds
        if (r1-r0+1)*(c1-c0+1) > 1000000 or not 0 <= topValues <= 50:
            raise ValueError('workbook_ai_read_limit')
        values = [cell.get('value') for address, cell in self._visible_cells(sheet)
                  if r0 <= _bounds(address)[0] <= r1 and c0 <= _bounds(address)[2] <= c1 and cell.get('value') is not None]
        counts = Counter((type(value).__name__, value) for value in values)
        numbers = [value for value in values if type(value) in (int, float)]
        return {'nonEmptyCount': len(values), 'distinctCount': len(counts), 'numericCount': len(numbers),
                'sum': sum(numbers), 'average': sum(numbers)/len(numbers) if numbers else None,
                'min': min(numbers) if numbers else None, 'max': max(numbers) if numbers else None,
                'topValues': [{'value': key[1], 'count': count} for key, count in counts.most_common(topValues)]}

    def _trace_refs(self, formula: str, default_sheet: str) -> list[tuple[str, str]]:
        if not isinstance(formula, str) or not formula:
            raise ValueError('workbook_ai_trace_unsupported')
        try:
            tokens = Tokenizer(formula if formula.startswith('=') else '=' + formula).items
        except Exception as error:
            raise ValueError('workbook_ai_trace_unsupported') from error
        refs = []
        pattern = re.compile(r"(?:(?:'((?:[^']|'')+)'|([^'!:\[\]]+))!)?(\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6})(?::(\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6}))?")
        depth = 0
        for token in tokens:
            if token.type in {'FUNC', 'PAREN'}:
                depth += 1 if token.subtype == 'OPEN' else -1
                if depth < 0:
                    raise ValueError('workbook_ai_trace_unsupported')
            if token.type == 'FUNC' and token.subtype == 'OPEN' and token.value[:-1].upper().split('.')[-1] in {'INDIRECT', 'OFFSET'}:
                raise ValueError('workbook_ai_trace_unsupported')
            if token.type != 'OPERAND' or token.subtype != 'RANGE':
                continue
            match = pattern.fullmatch(token.value)
            if match is None:
                raise ValueError('workbook_ai_trace_unsupported')
            sheet_name = (match.group(1).replace("''", "'") if match.group(1) else match.group(2)) or default_sheet
            if sheet_name not in self._sheets:
                raise ValueError('workbook_ai_trace_unsupported')
            start = match.group(3).replace('$', '').upper()
            end = (match.group(4) or match.group(3)).replace('$', '').upper()
            try:
                r0, r1, c0, c1 = _bounds(f'{start}:{end}')
            except ValueError as error:
                raise ValueError('workbook_ai_trace_unsupported') from error
            if (r1 - r0 + 1) * (c1 - c0 + 1) + len(refs) > 200:
                raise ValueError('workbook_ai_trace_unsupported')
            for row in iter_range(r0, r1 + 1):
                for column in iter_range(c0, c1 + 1):
                    refs.append((sheet_name, f'{get_column_letter(column + 1)}{row + 1}'))
        if depth != 0:
            raise ValueError('workbook_ai_trace_unsupported')
        return list(dict.fromkeys(refs))

    def _trace_cell(self, sheet_name: str, address: str) -> dict[str, Any]:
        sheet = self._sheets.get(sheet_name)
        if sheet is None:
            raise ValueError('workbook_ai_trace_unsupported')
        try:
            self._authorized(sheet, _bounds(address))
        except ValueError as error:
            raise ValueError('workbook_ai_selection_mismatch') from error
        cell = deepcopy(sheet.get('cells', {}).get(address, {'value': None}))
        return {'sheetName': sheet_name, 'address': address, **cell,
                'error': str(cell.get('value', '')).startswith('#')}

    def trace_precedents(self, address: str, sheetId: str | None = None) -> dict[str, Any]:
        """追踪冻结工作簿中一个公式的直接依赖；不展开命名范围或外部引用。"""
        sheet = self._sheet(sheetId)
        try:
            address = _cell_address(address)
        except ValueError as error:
            raise ValueError('workbook_ai_trace_invalid') from error
        target = self._trace_cell(sheet['name'], address)
        formula = target.get('formula')
        if not isinstance(formula, str) or not formula:
            raise ValueError('workbook_ai_trace_not_formula')
        refs = self._trace_refs(formula, sheet['name'])
        return {'sheetName': sheet['name'], 'address': address, 'formula': formula,
                'value': target.get('value'), 'error': target['error'],
                'precedents': [self._trace_cell(name, ref) for name, ref in refs],
                'truncated': False}

    def trace_dependents(self, address: str, sheetId: str | None = None) -> dict[str, Any]:
        """查找冻结工作簿中直接引用目标单元格的公式单元格。"""
        sheet = self._sheet(sheetId)
        try:
            address = _cell_address(address)
        except ValueError as error:
            raise ValueError('workbook_ai_trace_invalid') from error
        self._trace_cell(sheet['name'], address)
        dependents = []
        unsupported = 0
        for candidate_sheet in self._sheets.values():
            for candidate_address, cell in self._visible_cells(candidate_sheet):
                formula = cell.get('formula')
                if not isinstance(formula, str) or not formula:
                    continue
                try:
                    refs = self._trace_refs(formula, candidate_sheet['name'])
                except ValueError:
                    unsupported += 1
                    continue
                if (sheet['name'], address) in refs:
                    dependents.append(self._trace_cell(candidate_sheet['name'], candidate_address))
                    if len(dependents) >= 200:
                        return {'sheetName': sheet['name'], 'address': address, 'dependents': dependents, 'truncated': True, 'complete': False, 'scope': self._scope, 'unsupportedFormulaCount': unsupported}
        return {'sheetName': sheet['name'], 'address': address, 'dependents': dependents, 'truncated': False, 'complete': unsupported == 0 and self._scope == 'workbook', 'scope': self._scope, 'unsupportedFormulaCount': unsupported}

    def load_guide(self, guides: list[str]) -> dict[str, Any]:
        """加载源指南与原生适配说明：writing/formatting/layout/structure/charts/data/financial-formatting/data-attribution/table/pivot/shape-image。"""
        catalog = {
            'writing': 'set_cell(sheetId,address,value,expectedValue可选)、set_formula(sheetId,address,formula以=开头,expectedFormula可选)、clear_cell(sheetId,address)。前置条件精确核对冻结值/公式，纯单元格DSL批次按顺序核对前序写入；混合原生或结构操作之后的条件写入须另起候选，不能按旧快照猜测。原生操作使用{kind,arguments}，applyCellEdits.edits每项sheetName,row,column,writeValue布尔,cell:{value,formula?},style?；行列从0开始。',
            'layout': 'sort_range(sheetId,range,byColumn,order=asc|desc,hasHeader布尔)复用真实引擎排序；有公式或批注时引擎拒绝。merge_cells/unmerge_cells(sheetId,range)保留范围外既有合并。',
            'data': 'set_filter(sheetId,range)、clear_filter(sheetId)、add_defined_name(name,ref)、delete_defined_name(name)。需要复杂筛选可使用原生applySheetFilter。',
            'table': '整簿授权下用 {op:add_table,sheetId,range,name?,style?,bandedRows?} 创建 Excel 表格。'
            '范围首行是表头，至少再有一行数据；实际草稿生成表头与默认表名，不提供模型自填列名。'
            '原生applyTableEdits/edits每项worksheetSheetName,tableName，可含name,area,columnNames,style,totalsRow,bandedRows,headerRow,remove等；先read_sheet_features核对既有表格。',
            'structure': '仅整簿授权。源DSL insert_rows/delete_rows(sheetId,row,count)：row从1开始，count必填1–500；insert_cols/delete_cols(sheetId,column,count)：column为A到XFD大写列名，count必填1–100。结构DSL必须单独成批，不能与单元格、布局或原生操作混合；先预览、显式采纳并保存，再以新修订继续内容修改。原生applySheetEdits/plan、applyRowColumnOps/sheetName/ops、applyCellShift/sheetName/range/shift继续兼容。',
            'pivot': '整簿授权下用 {op:refresh_pivot,sheetId} 刷新指定表上的透视表。'
            '原生addPivot/addition、applyPivotLayoutExpansions/updates、expandPivotOutputs/expansions；复用引擎验证来源和输出。',
            'charts': '仅整簿授权；先read_sheet_features读取冻结草稿中charts的chartPath/title/kind/anchor/series引用。多图须按用户明确目标匹配，不能按数组顺序猜测，不明确时请求澄清而不提交。applyChartEdits.arguments.edits每项含真实唯一chartPath，可改title、chartType(column/bar/line/area/pie/doughnut)、legend、seriesColors、pointColors、dataLabels、dataLabelPosition、dataLabelFormat、axisTitles、grouping、gridlines、valueAxis、gapWidthPct、holeSizePct、explosionPct、pointExplosions；具体值由引擎预览核验。新增使用源DSL {op:add_chart,sheetId,chartType:column|bar|line|area|pie|doughnut|scatter|radar|combo,dataRange,title?,anchorCell?}，先read_range核对最多2000格真实数据。换绑使用{op:edit_chart,chartPath,seriesData:[{index,name?,valuesRange?,categoriesRange?,sheetId?}]}，范围须为单行或单列；支持已有格式字段。引擎从当前草稿生成引用与缓存，禁止传series/seriesSet/values/categories缓存；不与行列或工作表结构操作混批。applyChartDeletions.arguments.deletions每项含所属sheetName和chartPath。只生成候选，显式采纳后仍需保存。',
        }
        if (not isinstance(guides, list) or not guides
                or any(not isinstance(guide, str) or guide not in WORKBOOK_GUIDES for guide in guides)):
            raise ValueError('workbook_ai_guide_invalid')
        if 'writing' in guides:
            catalog['writing'] += (
                '批量写入用 {op:set_range,sheetId,start?,range?,values}，提供左上起点或与矩阵等大的范围。'
                'values 必须是矩形，等号开头为公式，null 清空内容。'
                '用 {op:clear_range,sheetId,range} 清空值和公式，保留格式。'
                '用 {op:find_replace,sheetId,range,find,replace,matchCase?,wholeCell?} 在范围内替换文字，跳过公式和非文本单元格。'
                '大范围清空每项最多 200000 格；其余单元格操作每批最多展开 2000 格。'
            )
        if 'layout' in guides:
            catalog['layout'] += (
                '整簿授权下用 {op:set_hyperlink,sheetId,address,target} 设置链接。'
                'target 是网址或同工作簿工作表引用；传 null 移除。'
                '用 {op:set_note,sheetId,address,text} 设置单元格旧式备注，传 null 删除。'
                '用 {op:set_row_height,sheetId,row,count,heightPoints} 调整行高（磅），'
                '用 {op:set_col_width,sheetId,column,count,widthPx} 调整列宽（像素，上限 1790）。'
                '起始行号从 1 开始，列使用字母，count 缺省为 1，需要工作簿权限。'
                '整簿授权可用 set_rows_hidden(sheetId,row,count?,hidden) 和 set_cols_hidden(sheetId,column,count?,hidden) 隐藏或显示连续行列。'
                '用 {op:set_freeze,sheetId,rows,columns} 从工作表左上角冻结行列，'
                '行数和列数均为 0–100 的整数；同时传 0 取消冻结。'
                '用 set_page_setup(sheetId,orientation?,paperSize?,scale?,fitToWidth?,fitToHeight?,margins?,'
                'printGridlines?,printHeadings?,printArea?,printTitles?,header?,footer?,rowBreaks?,colBreaks?)。'
                '缩放百分比与按页适配互斥，printTitles 可写 "1:2,A:B"，null 清除打印范围、标题或页眉页脚。'
            )
        if 'data' in guides:
            catalog['data'] += (
                '用 set_data_validation(sheetId,range,validation) 增设或替换范围内验证，null 清除。'
                'validation 支持 list(values)、listRef(range)、numberBetween(min,max)、'
                'dateBetween(start,end)，日期为 YYYY-MM-DD，以及 checkbox 和 formula(formula，以等号开头)。'
                '列表过长或包含逗号时请引用同表单元格区域。仅整簿授权可修改数据验证。'
            )
        if 'structure' in guides:
            catalog['structure'] += (
                '整簿授权下用 {op:move_sheet,sheetId,position} 移动工作表标签。'
                'position 从 1 开始；同批多个移动按提交顺序执行。'
                '支持 add_sheet(name)、rename_sheet(sheetId,name) 和 delete_sheet(sheetId)。'
                '用 set_sheet_hidden(sheetId,hidden) 隐藏或显示工作表；始终保留至少一个可见工作表。'
                '在工作表结构批次内按当前表名寻址；Excel 新建空白表无需指定 rows 或 columns。'
                '仍被其他工作表引用的表由写入器拒绝删除。'
            )
        if 'charts' in guides:
            catalog['charts'] += (
                '源DSL add_chart/edit_chart会映射至原生applyChartSource。'
                '迷你图新增使用源 DSL {op:add_sparkline,sheetId,type:line|column|stacked,dataRange,targetCell?,color?}。'
                '每行至少两列，每行一个迷你图，最多取前200行。默认放在来源右侧，也可从同表的单格 targetCell 向下排列。'
                'color 使用 #RRGGBB；stacked 表示盈亏图。'
                '删除工作簿图表使用源 DSL {op:delete_visual,visualId}，visualId 填 read_sheet_features 返回的唯一 chartPath。'
                '新增图表可传 columns，例如 ["C","E","B"]。按顺序指定分类列和各系列列，'
                '列必须互不重复且位于 dataRange 内，第一行用作表头。'
            )
        boundary = (
            '这是固定源指南，不表示源端全部操作已在此宿主开放。'
            '仅使用当前注册工具和已支持的源DSL/原生参数；未支持的操作应明确说明。'
            '保持冻结授权、来源身份和真实引擎验证；所有写入先生成预览候选，等待用户显式采纳后另行保存。'
            '指南中的自动应用或直接写文件不改变此流程。'
        )
        return {guide: source_workbook_guide(guide) + '\n## Native Agno adapter\n' + boundary +
                '\n' + catalog.get(guide, '本主题尚未逐操作完成原生适配，请按已注册工具及实际引擎能力执行。')
                for guide in guides}

    def _translate(
        self, operation: dict[str, Any], merges: dict[str, list[str]],
        cell_state: dict[tuple[str, str], dict[str, Any]] | None,
        sheet_order: list[str],
        page_setups: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        op = operation.get('op')
        if ('expectedValue' in operation and op != 'set_cell') or (
            'expectedFormula' in operation and op != 'set_formula'
        ):
            raise ValueError('workbook_ai_precondition_invalid')
        if 'kind' in operation:
            if 'op' in operation:
                raise ValueError('workbook_ai_operation_invalid')
            arguments = operation.get('arguments', {})
            if not isinstance(arguments, dict) or 'kind' in arguments:
                raise ValueError('workbook_ai_operation_invalid')
            return {'kind': operation['kind'], **arguments}
        if op in {'add_chart', 'edit_chart'}:
            return {'kind': 'applyChartSource', 'operation': deepcopy(operation)}
        if op == 'delete_visual':
            return translate_chart_deletion(self._model, operation)
        if op == 'add_sparkline':
            sheet_id = operation.get('sheetId')
            if not isinstance(sheet_id, str) or not sheet_id:
                raise ValueError('workbook_ai_sparkline_invalid')
            return _sparkline_addition(operation, self._sheet(sheet_id)['name'])
        if op == 'add_table':
            sheet_id = operation.get('sheetId')
            if (set(operation) - {'op', 'sheetId', 'range', 'name', 'style', 'bandedRows'}
                    or not isinstance(sheet_id, str) or not sheet_id):
                raise ValueError('workbook_ai_table_source_invalid')
            sheet = self._sheet(sheet_id)
            r0, r1, c0, c1 = _bounds(operation.get('range'))
            if r0 == r1 or c1 - c0 + 1 > 1000:
                raise ValueError('workbook_ai_table_range_invalid')
            start = f'{get_column_letter(c0 + 1)}{r0 + 1}'
            end = f'{get_column_letter(c1 + 1)}{r1 + 1}'
            return {'kind': 'applyTableSource', 'sheetName': sheet['name'], 'range': f'{start}:{end}',
                    **{key: operation[key] for key in ('name', 'style', 'bandedRows') if key in operation}}
        if op == 'set_hyperlink':
            if set(operation) != {'op', 'sheetId', 'address', 'target'}:
                raise ValueError('workbook_ai_hyperlink_invalid')
            sheet_id, target = operation['sheetId'], operation['target']
            if (not isinstance(sheet_id, str) or not sheet_id
                    or (target is not None and (not isinstance(target, str) or not 1 <= len(target) <= 2048))):
                raise ValueError('workbook_ai_hyperlink_invalid')
            return {'kind': 'applyHyperlinkSource', 'sheetName': self._sheet(sheet_id)['name'],
                    'ref': _cell_address(operation['address']), 'target': target}
        if op == 'set_note':
            if set(operation) != {'op', 'sheetId', 'address', 'text'}:
                raise ValueError('workbook_ai_note_invalid')
            sheet_id, text = operation['sheetId'], operation['text']
            if (not isinstance(sheet_id, str) or not sheet_id
                    or (text is not None and (not isinstance(text, str) or not 1 <= len(text) <= 32000))):
                raise ValueError('workbook_ai_note_invalid')
            row, _, column, _ = _bounds(_cell_address(operation['address']))
            return {'kind': 'applyNoteSource', 'sheetName': self._sheet(sheet_id)['name'],
                    'row': row, 'column': column, 'text': text}
        if op in AXIS_SIZE_SOURCE_OPS:
            sheet_id = operation.get('sheetId')
            if not isinstance(sheet_id, str) or not sheet_id:
                raise ValueError('workbook_ai_axis_size_invalid')
            return translate_axis_size(operation, self._sheet(sheet_id)['name'])
        if op in AXIS_VISIBILITY_SOURCE_OPS:
            sheet_id = operation.get('sheetId')
            if not isinstance(sheet_id, str) or not sheet_id:
                raise ValueError('workbook_ai_axis_visibility_invalid')
            return translate_axis_visibility(operation, self._sheet(sheet_id)['name'])
        if op == 'refresh_pivot':
            sheet_id = operation.get('sheetId')
            if set(operation) != {'op', 'sheetId'} or not isinstance(sheet_id, str) or not sheet_id:
                raise ValueError('workbook_ai_pivot_refresh_invalid')
            return {'kind': 'refreshPivotCaches', 'sheetName': self._sheet(sheet_id)['name']}
        if op == 'set_freeze':
            if set(operation) != {'op', 'sheetId', 'rows', 'columns'}:
                raise ValueError('workbook_ai_freeze_invalid')
            sheet_id, rows, columns = operation['sheetId'], operation['rows'], operation['columns']
            if (not isinstance(sheet_id, str) or not sheet_id
                    or any(type(count) is not int or not 0 <= count <= 100 for count in (rows, columns))):
                raise ValueError('workbook_ai_freeze_invalid')
            return {'kind': 'applyPageSetups', 'setups': [{
                'sheetName': self._sheet(sheet_id)['name'], 'frozenRows': rows, 'frozenColumns': columns,
            }]}
        if op == 'set_page_setup':
            sheet_id = operation.get('sheetId')
            if not isinstance(sheet_id, str) or not sheet_id:
                raise ValueError('workbook_ai_page_setup_invalid')
            sheet = self._sheet(sheet_id)
            prior = page_setups.get(sheet['name'], sheet.get('pageSetup') or {})
            patch = page_setup_patch(operation, prior)
            if patch.get('printArea') is not None:
                r0, r1, c0, c1 = _bounds(patch['printArea'])
                start = f'{get_column_letter(c0 + 1)}{r0 + 1}'
                end = f'{get_column_letter(c1 + 1)}{r1 + 1}'
                patch['printArea'] = start if start == end else f'{start}:{end}'
            return {'kind': 'applyPageSetups', 'setups': [{'sheetName': sheet['name'], **patch}]}
        if op in SHEET_SOURCE_OPS:
            return translate_sheet_operation(operation, sheet_order)
        if op in {'add_defined_name', 'delete_defined_name'}:
            plan = {'sets': [{'name': operation['name'], 'refersTo': operation['ref']}]} if op == 'add_defined_name' else {'removes': [operation['name']]}
            return {'kind': 'applyDefinedNames', 'plan': plan}
        if op == 'set_data_validation':
            if (set(operation) != {'op', 'sheetId', 'range', 'validation'}
                    or not isinstance(operation['sheetId'], str) or not operation['sheetId']
                    or (operation['validation'] is not None and not isinstance(operation['validation'], dict))):
                raise ValueError('workbook_ai_data_validation_invalid')
            return {'kind': 'applyDataValidationSource', 'sheetName': self._sheet(operation['sheetId'])['name'],
                    'range': _range_address(operation['range']), 'validation': operation['validation']}
        if op == 'find_replace':
            required = {'op', 'sheetId', 'range', 'find', 'replace'}
            if (set(operation) - {'matchCase', 'wholeCell'} != required
                    or not isinstance(operation['sheetId'], str) or not operation['sheetId']
                    or not isinstance(operation['find'], str) or not 1 <= len(operation['find']) <= 32767
                    or not isinstance(operation['replace'], str) or len(operation['replace']) > 255
                    or any(type(operation.get(key, False)) is not bool for key in ('matchCase', 'wholeCell'))):
                raise ValueError('workbook_ai_find_replace_invalid')
            sheet = self._sheet(operation['sheetId'])
            self._authorized(sheet, clear_range_bounds(operation['range']))
            return {'kind': 'replaceRangeText', 'sheetName': sheet['name'],
                    'range': _range_address(operation['range']), 'find': operation['find'],
                    'replace': operation['replace'], 'matchCase': operation.get('matchCase', False),
                    'wholeCell': operation.get('wholeCell', False)}
        if op == 'clear_range':
            r0, r1, c0, c1 = clear_range_bounds(operation.get('range'))
            if (r1 - r0 + 1) * (c1 - c0 + 1) > _MAX_EXPANDED_CELL_EDITS:
                sheet_id = operation.get('sheetId')
                if set(operation) != {'op', 'sheetId', 'range'} or not isinstance(sheet_id, str) or not sheet_id:
                    raise ValueError('workbook_ai_range_invalid')
                sheet = self._sheet(sheet_id)
                self._authorized(sheet, (r0, r1, c0, c1))
                if cell_state is not None:
                    # Clear only cells known to the frozen or staged model.
                    # Absent cells already match a null value precondition.
                    addresses = set(sheet.get('cells', {}))
                    addresses.update(address for name, address in cell_state if name == sheet_id)
                    for address in addresses:
                        if _overlaps(_bounds(address), (r0, r1, c0, c1)):
                            cell_state[(sheet_id, address)] = {'value': None}
                start = f'{get_column_letter(c0 + 1)}{r0 + 1}'
                end = f'{get_column_letter(c1 + 1)}{r1 + 1}'
                return {'kind': 'clearCellRange', 'sheetName': sheet['name'], 'range': f'{start}:{end}'}
        if op in {'set_range', 'clear_range'}:
            bounds, values = _source_range_values(operation)
            sheet = self._sheet(operation['sheetId'])
            self._authorized(sheet, bounds)
            r0, _, c0, _ = bounds
            edits = []
            for row, row_values in enumerate(values, r0):
                for column, value in enumerate(row_values, c0):
                    if type(value) not in (str, int, float, bool, type(None)) or (
                        type(value) is float and not math.isfinite(value)
                    ):
                        raise ValueError('workbook_ai_range_invalid')
                    formula = value if isinstance(value, str) and value.startswith('=') else None
                    cell = {'value': value} if formula is None else {'value': None, 'formula': formula[1:]}
                    edits.append({'sheetName': sheet['name'], 'row': row, 'column': column,
                                  'writeValue': True, 'cell': cell})
                    if cell_state is not None:
                        address = f'{get_column_letter(column + 1)}{row + 1}'
                        cell_state[(sheet['name'], address)] = {'value': cell['value'], 'formula': formula}
            return {'kind': 'applyCellEdits', 'edits': edits}

        if op in ROW_COLUMN_SOURCE_OPS:
            sheet_id = operation.get('sheetId')
            if not isinstance(sheet_id, str) or not sheet_id:
                raise ValueError('workbook_ai_structure_invalid')
            return translate_row_column_operation(operation, self._sheet(sheet_id)['name'])
        sheet = self._sheet(operation.get('sheetId'))
        name = sheet['name']
        if op in {'set_cell', 'set_formula', 'clear_cell'}:
            address = _cell_address(operation['address'])
            bounds = _bounds(address)
            row, _, column, _ = bounds
            if ':' in operation['address']:
                raise ValueError('workbook_ai_range_invalid')
            self._authorized(sheet, bounds)
            key = (name, address)
            expected_key = 'expectedValue' if op == 'set_cell' else 'expectedFormula' if op == 'set_formula' else None
            if expected_key is not None and expected_key in operation:
                if cell_state is None:
                    raise ValueError('workbook_ai_precondition_requires_cell_batch')
                before = cell_state.get(key, sheet.get('cells', {}).get(address, {'value': None}))
                if expected_key == 'expectedValue':
                    matches = _matches_expected_value(before.get('value'), operation[expected_key])
                else:
                    expected = operation[expected_key]
                    if not isinstance(expected, str):
                        raise ValueError('workbook_ai_precondition_invalid')
                    matches = before.get('formula') == expected
                if not matches:
                    raise ValueError('workbook_ai_precondition_mismatch')
            cell = {'value': operation.get('value') if op == 'set_cell' else None}
            if op == 'set_formula':
                formula = operation['formula']
                if not isinstance(formula, str) or not formula.startswith('='):
                    raise ValueError('workbook_ai_formula_invalid')
                cell['formula'] = formula[1:]
            if cell_state is not None:
                cell_state[key] = {**cell, **({'formula': operation['formula']} if op == 'set_formula' else {})}
            return {'kind': 'applyCellEdits', 'edits': [{'sheetName': name, 'row': row, 'column': column, 'writeValue': True, 'cell': cell}]}
        if op == 'sort_range':
            if operation.get('order') not in {'asc', 'desc'} or type(operation.get('hasHeader', False)) is not bool:
                raise ValueError('workbook_ai_sort_invalid')
            return {'kind': 'sortRange', 'sheetName': name, 'spec': {'range': _range_address(operation['range']), 'byColumn': operation['byColumn'], 'ascending': operation['order'] == 'asc', 'hasHeader': operation.get('hasHeader', False)}}
        if op in {'merge_cells', 'unmerge_cells'}:
            area = _bounds(operation['range'])
            current = merges.setdefault(name, list(sheet.get('merges', [])))
            if op == 'merge_cells':
                current.append(_range_address(operation['range']))
            else:
                current[:] = [ref for ref in current if not _overlaps(_bounds(ref), area)]
            return {'kind': 'applySheetMerges', 'sheetName': name, 'ranges': list(current)}
        if op in {'set_filter', 'clear_filter'}:
            filter_state = None
            if op == 'set_filter':
                r0, r1, c0, c1 = _bounds(operation['range'])
                filter_state = {'range': {'startRow': r0, 'endRow': r1, 'startColumn': c0, 'endColumn': c1}, 'columns': []}
            return {'kind': 'applySheetFilter', 'sheetName': name, 'filter': filter_state}
        raise ValueError('workbook_ai_operation_unsupported')

    async def propose_operations(self, operations: list[dict[str, Any]], summary: str) -> dict[str, Any]:
        """提交结构化候选，经范围校验和真实引擎预览；不保存文件，等待用户显式采纳。"""
        if self.proposal is not None or self._submitting:
            raise ValueError('workbook_ai_proposal_already_submitted')
        if not 1 <= len(operations) <= 100:
            raise ValueError('workbook_ai_operations_invalid')
        if self._scope == 'range' and any(operation.get('op') not in (_CELL_SOURCE_OPS | {'find_replace', None}) or operation.get('kind') not in (_RANGE_VALUE_KINDS | {'applyCellEdits', None}) for operation in operations):
            raise ValueError('workbook_ai_selection_mismatch')
        if any(operation.get('op') in ROW_COLUMN_SOURCE_OPS for operation in operations) and any(
            operation.get('op') not in ROW_COLUMN_SOURCE_OPS or 'kind' in operation for operation in operations
        ):
            raise ValueError('workbook_ai_structure_batch_invalid')
        if any(operation.get('op') in SHEET_LIFECYCLE_OPS for operation in operations) and any(
            operation.get('op') not in SHEET_SOURCE_OPS or 'kind' in operation for operation in operations
        ):
            raise ValueError('workbook_ai_structure_batch_invalid')
        if any(operation.get('op') in {'move_sheet', 'set_sheet_hidden'} for operation in operations) and any(
            operation.get('kind') == 'applySheetEdits' for operation in operations
        ):
            raise ValueError('workbook_ai_structure_batch_invalid')
        merges: dict[str, list[str]] = {}
        cell_state: dict[tuple[str, str], dict[str, Any]] | None = {}
        sheet_order = list(self._sheets)
        page_setups: dict[str, dict[str, Any]] = {}
        translated_operations = []
        expanded_cell_edits = 0
        for operation in operations:
            translated = self._translate(operation, merges, cell_state, sheet_order, page_setups)
            if translated['kind'] == 'applyPageSetups' and isinstance(translated.get('setups'), list):
                for setup in translated['setups']:
                    if isinstance(setup, dict) and isinstance(name := setup.get('sheetName'), str) and name in self._sheets:
                        page_setups.setdefault(name, dict(self._sheets[name].get('pageSetup') or {})).update(setup)
            if operation.get('op') in _CELL_SOURCE_OPS and translated['kind'] == 'applyCellEdits':
                expanded_cell_edits += len(translated['edits'])
                if expanded_cell_edits > _MAX_EXPANDED_CELL_EDITS:
                    raise ValueError('workbook_ai_range_too_large')
            translated_operations.append({'kind': translated['kind'], 'arguments': {
                key: value for key, value in translated.items() if key != 'kind'
            }})
            if 'kind' in operation or operation.get('op') not in _CELL_SOURCE_OPS:
                # Native and structural operations can move/replace cells. Never
                # validate a later condition against an unchanged base model.
                cell_state = None
        proposal = WorkbookAIProposal.model_validate({'summary': summary, 'operations': translated_operations})
        candidate = proposal.engine_operations()
        validate_chart_candidates(self._model, candidate)
        if self._scope == 'range':
            for operation in candidate:
                if operation['kind'] in _RANGE_VALUE_KINDS:
                    self._authorized(self._sheet(operation.get('sheetName')), clear_range_bounds(operation.get('range')))
                    continue
                if operation['kind'] != 'applyCellEdits' or not operation.get('edits'):
                    raise ValueError('workbook_ai_selection_mismatch')
                for edit in operation['edits']:
                    if type(edit.get('row')) is not int or type(edit.get('column')) is not int:
                        raise ValueError('workbook_ai_selection_mismatch')
                    self._authorized(self._sheet(edit.get('sheetName')), (edit['row'], edit['row'], edit['column'], edit['column']))
        self._submitting = True
        try:
            preview = await self._preview(candidate)
            digest = preview.get('draftSha256') if isinstance(preview, Mapping) else None
            if not isinstance(digest, str) or re.fullmatch(r'[0-9a-fA-F]{64}', digest) is None:
                raise ValueError('workbook_ai_preview_invalid')
            self.proposal = proposal
        finally:
            self._submitting = False
        return {'status': 'previewed', 'summary': proposal.summary, 'operationCount': len(candidate), 'previewSha256': digest, 'requiresAcceptance': True}


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] <= b[1] and a[1] >= b[0] and a[2] <= b[3] and a[3] >= b[2]


# 工具参数沿用源协议 range 名称；仅循环需要 Python 内置 range。
