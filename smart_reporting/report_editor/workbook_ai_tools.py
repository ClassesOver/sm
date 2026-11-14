"""源 sheets/ai/tools.ts 的服务端适配：只读冻结草稿，提案只进入预览。

固定源 f8c17004fb730df11f0f743164ffd8b4281bb38c；沿用源工具名与 DSL 字段，
实际修改复用既有 workbook engine。导航、新文件签发不属于此候选权限。
"""
from __future__ import annotations

import re
from builtins import range as iter_range
from collections import Counter
from copy import deepcopy
from typing import Any

from agno.tools import Toolkit
from openpyxl.formula import Tokenizer
from openpyxl.utils.cell import get_column_letter, range_boundaries

from .workbook_ai import WorkbookAIProposal
from .workbook_ai_charts import validate_chart_candidates


def _bounds(address: str) -> tuple[int, int, int, int]:
    if not isinstance(address, str) or re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]{0,6}(?::[A-Z]{1,3}[1-9][0-9]{0,6})?', address) is None:
        raise ValueError('workbook_ai_range_invalid')
    c0, r0, c1, r1 = range_boundaries(address)
    if not (1 <= r0 <= r1 <= 1048576 and 1 <= c0 <= c1 <= 16384):
        raise ValueError('workbook_ai_range_invalid')
    return r0 - 1, r1 - 1, c0 - 1, c1 - 1


class WorkbookAIToolkit(Toolkit):
    def __init__(self, *, model: dict[str, Any], scope: str, selection: dict[str, Any], preview: Any):
        self._model, self._scope = deepcopy(model), scope
        self._selection, self._preview = deepcopy(selection), preview
        self.proposal: WorkbookAIProposal | None = None
        self._sheets = {sheet['name']: sheet for sheet in self._model['sheets']
                        if scope == 'workbook' or sheet['name'] == selection['sheetName']}
        super().__init__(name='workbook_candidate', tools=[
            self.get_workbook_context, self.read_range, self.read_cells, self.read_formats,
            self.read_sheet_features, self.find_cells, self.aggregate_range,
            self.trace_precedents, self.trace_dependents, self.load_guide,
            self.propose_operations,
        ])

    def _sheet(self, sheetId: str | None) -> dict[str, Any]:
        identity = sheetId or next(iter(self._sheets))
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
        return {'scope': self._scope, 'selection': deepcopy(self._selection), 'sheets': sheets}

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
        if not 1 <= len(addresses) <= 100 or any(':' in address for address in addresses):
            raise ValueError('workbook_ai_read_limit')
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

    def find_cells(self, query: str = '', sheetId: str | None = None, look_in: str = 'both', errors_only: bool = False, max_results: int = 50) -> dict[str, Any]:
        """在授权内容内查找值、公式或错误；不执行正则表达式，最多200条。"""
        if look_in not in {'values', 'formulas', 'both'} or not 1 <= max_results <= 200 or not query and not errors_only:
            raise ValueError('workbook_ai_search_invalid')
        matches = []
        errors = {'#REF!', '#DIV/0!', '#VALUE!', '#NAME?', '#N/A', '#NUM!', '#NULL!'}
        sheets = [self._sheet(sheetId)] if sheetId else self._sheets.values()
        for sheet in sheets:
            for address, cell in self._visible_cells(sheet):
                fields = [str(cell.get(key, '')) for key in ('value', 'formula') if look_in == 'both' or key == ('value' if look_in == 'values' else 'formula')]
                if errors_only and str(cell.get('value')) not in errors:
                    continue
                if query.casefold() not in ' '.join(fields).casefold():
                    continue
                if len(matches) == max_results:
                    return {'matches': matches, 'truncated': True}
                matches.append({'sheetName': sheet['name'], 'address': address, **deepcopy(cell)})
        return {'matches': matches, 'truncated': False}

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
        if not isinstance(address, str) or ':' in address or not re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]{0,6}', address):
            raise ValueError('workbook_ai_trace_invalid')
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
        if not isinstance(address, str) or ':' in address or not re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]{0,6}', address):
            raise ValueError('workbook_ai_trace_invalid')
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
        """加载适配器实际支持的操作协议；结构操作仅用于明确授权整簿模式。"""
        catalog = {
            'writing': 'set_cell(sheetId,address,value)、set_formula(sheetId,address,formula以=开头)、clear_cell(sheetId,address)。原生操作使用{kind,arguments}，applyCellEdits.edits每项sheetName,row,column,writeValue布尔,cell:{value,formula?},style?；行列从0开始。',
            'layout': 'sort_range(sheetId,range,byColumn,order=asc|desc,hasHeader布尔)复用真实引擎排序；有公式或批注时引擎拒绝。merge_cells/unmerge_cells(sheetId,range)保留范围外既有合并。',
            'data': 'set_filter(sheetId,range)、clear_filter(sheetId)、add_defined_name(name,ref)、delete_defined_name(name)。需要复杂筛选可使用原生applySheetFilter。',
            'table': '原生applyTableAdditions/additions；applyTableEdits/edits每项worksheetSheetName,tableName，可含name,area,columnNames,style,totalsRow,bandedRows,headerRow,remove等；先read_sheet_features核对既有表格。',
            'structure': '原生applySheetEdits/plan、applyRowColumnOps/sheetName/ops、applyCellShift/sheetName/range/shift，仅整簿授权。',
            'pivot': '原生addPivot/addition、refreshPivotCaches/空arguments、applyPivotLayoutExpansions/updates、expandPivotOutputs/expansions；复用引擎验证来源和输出。',
            'charts': '仅整簿授权；先read_sheet_features读取冻结草稿中charts的chartPath/title/kind/anchor/series引用。多图须按用户明确目标匹配，不能按数组顺序猜测，不明确时请求澄清而不提交。applyChartEdits.arguments.edits每项含真实唯一chartPath，可改title、chartType(column/bar/line/area/pie/doughnut)、legend、seriesColors、pointColors、dataLabels、dataLabelPosition、dataLabelFormat、axisTitles、grouping、gridlines、valueAxis、gapWidthPct、holeSizePct、explosionPct、pointExplosions；具体值由引擎预览核验。新增使用源DSL {op:add_chart,sheetId,chartType:column|bar|line|area|pie|doughnut|scatter|radar|combo,dataRange,title?,anchorCell?}，先read_range核对最多2000格真实数据。换绑使用{op:edit_chart,chartPath,seriesData:[{index,name?,valuesRange?,categoriesRange?,sheetId?}]}，范围须为单行或单列；支持已有格式字段。引擎从当前草稿生成引用与缓存，禁止传series/seriesSet/values/categories缓存；不与行列或工作表结构操作混批。applyChartDeletions.arguments.deletions每项含所属sheetName和chartPath。只生成候选，显式采纳后仍需保存。',
        }
        if any(guide not in catalog for guide in guides):
            raise ValueError('workbook_ai_guide_invalid')
        return {guide: catalog[guide] for guide in guides}

    def _translate(self, operation: dict[str, Any], merges: dict[str, list[str]]) -> dict[str, Any]:
        if 'kind' in operation:
            arguments = operation.get('arguments', {})
            if not isinstance(arguments, dict) or 'kind' in arguments:
                raise ValueError('workbook_ai_operation_invalid')
            return {'kind': operation['kind'], **arguments}
        op = operation.get('op')
        if op in {'add_chart', 'edit_chart'}:
            return {'kind': 'applyChartSource', 'operation': deepcopy(operation)}
        if op in {'add_defined_name', 'delete_defined_name'}:
            plan = {'sets': [{'name': operation['name'], 'refersTo': operation['ref']}]} if op == 'add_defined_name' else {'removes': [operation['name']]}
            return {'kind': 'applyDefinedNames', 'plan': plan}
        sheet = self._sheet(operation.get('sheetId'))
        name = sheet['name']
        if op in {'set_cell', 'set_formula', 'clear_cell'}:
            row, _, column, _ = _bounds(operation['address'])
            if ':' in operation['address']:
                raise ValueError('workbook_ai_range_invalid')
            cell = {'value': operation.get('value') if op == 'set_cell' else None}
            if op == 'set_formula':
                formula = operation['formula']
                if not isinstance(formula, str) or not formula.startswith('='):
                    raise ValueError('workbook_ai_formula_invalid')
                cell['formula'] = formula[1:]
            return {'kind': 'applyCellEdits', 'edits': [{'sheetName': name, 'row': row, 'column': column, 'writeValue': True, 'cell': cell}]}
        if op == 'sort_range':
            if operation.get('order') not in {'asc', 'desc'} or type(operation.get('hasHeader', False)) is not bool:
                raise ValueError('workbook_ai_sort_invalid')
            _bounds(operation['range'])
            return {'kind': 'sortRange', 'sheetName': name, 'spec': {'range': operation['range'], 'byColumn': operation['byColumn'], 'ascending': operation['order'] == 'asc', 'hasHeader': operation.get('hasHeader', False)}}
        if op in {'merge_cells', 'unmerge_cells'}:
            area = _bounds(operation['range'])
            current = merges.setdefault(name, list(sheet.get('merges', [])))
            if op == 'merge_cells':
                current.append(operation['range'])
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
        if self.proposal is not None:
            raise ValueError('workbook_ai_proposal_already_submitted')
        if not 1 <= len(operations) <= 100:
            raise ValueError('workbook_ai_operations_invalid')
        if self._scope == 'range' and any(operation.get('op') not in {'set_cell', 'set_formula', 'clear_cell', None} or operation.get('kind') not in {'applyCellEdits', None} for operation in operations):
            raise ValueError('workbook_ai_selection_mismatch')
        merges: dict[str, list[str]] = {}
        proposal = WorkbookAIProposal.model_validate({'summary': summary, 'operations': [
            {'kind': translated['kind'], 'arguments': {key: value for key, value in translated.items() if key != 'kind'}}
            for operation in operations
            for translated in [self._translate(operation, merges)]
        ]})
        candidate = proposal.engine_operations()
        validate_chart_candidates(self._model, candidate)
        if self._scope == 'range':
            for operation in candidate:
                if operation['kind'] != 'applyCellEdits' or not operation.get('edits'):
                    raise ValueError('workbook_ai_selection_mismatch')
                for edit in operation['edits']:
                    if type(edit.get('row')) is not int or type(edit.get('column')) is not int:
                        raise ValueError('workbook_ai_selection_mismatch')
                    self._authorized(self._sheet(edit.get('sheetName')), (edit['row'], edit['row'], edit['column'], edit['column']))
        preview = await self._preview(candidate)
        self.proposal = proposal
        return {'status': 'previewed', 'summary': proposal.summary, 'operationCount': len(candidate), 'previewSha256': preview['draftSha256'], 'requiresAcceptance': True}


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] <= b[1] and a[1] >= b[0] and a[2] <= b[3] and a[3] >= b[2]


# 工具参数沿用源协议 range 名称；仅循环需要 Python 内置 range。
