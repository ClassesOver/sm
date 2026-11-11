"""XLSX AI 真工具：冻结授权、引擎预览、显式采纳；不访问真实 provider。"""
from __future__ import annotations

import asyncio
import hashlib
import json
from io import BytesIO

import pytest
from agno.agent import Agent
from agno.models.response import ModelResponse
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.table import Table

from smart_reporting.report_editor.native_models import NativeEditorContext
from smart_reporting.report_editor.native_office import inspect_office, patch_office
from smart_reporting.report_editor.workbook_ai import AgnoWorkbookProposalPlanner
from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel
from smart_reporting.reporting.tests.test_workbook_native_ai import Editor


def test_workbook_formula_trace_reports_precedents_and_rejects_unsupported_syntax():
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit

    tools = WorkbookAIToolkit(model={"sheets": [
        {"name": "Sheet", "cells": {
            "A1": {"value": 2}, "B1": {"value": 3},
            "C1": {"value": 5, "formula": "SUM(A1:B1)"},
        }},
    ]}, scope="workbook", selection={}, preview=None)
    result = tools.trace_precedents("C1", "Sheet")
    assert result["formula"] == "SUM(A1:B1)"
    assert {(item["sheetName"], item["address"], item["value"]) for item in result["precedents"]} == {
        ("Sheet", "A1", 2), ("Sheet", "B1", 3)
    }
    tools._sheets["Sheet"]["cells"]["C1"]["formula"] = "Other!A1+NamedTotal"
    with pytest.raises(ValueError, match="unsupported"):
        tools.trace_precedents("C1", "Sheet")


def test_workbook_formula_trace_dependents_is_bounded_and_cross_sheet():
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit

    tools = WorkbookAIToolkit(model={"sheets": [
        {"name": "Sheet", "cells": {"A1": {"value": 2}}},
        {"name": "Other", "cells": {
            "A1": {"value": 4, "formula": "Sheet!A1*2"},
            "B1": {"value": 6, "formula": "SUM(Sheet!A1,Other!A1)"},
        }},
    ]}, scope="workbook", selection={}, preview=None)
    result = tools.trace_dependents("A1", "Sheet")
    assert {(item["sheetName"], item["address"]) for item in result["dependents"]} == {
        ("Other", "A1"), ("Other", "B1")
    }


def test_formula_trace_tokenizes_strings_absolute_refs_and_escaped_sheet_names():
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit

    tools = WorkbookAIToolkit(model={"sheets": [
        {"name": "Sheet", "cells": {"A1": {"value": 2}, "C1": {
            "formula": 'IF($A$1="B2",LOG10(\'O\'\'Brien\'!$B$2),1)', "value": 3,
        }}},
        {"name": "O'Brien", "cells": {"B2": {"value": 1000}}},
    ]}, scope="workbook", selection={}, preview=None)
    refs = tools.trace_precedents("C1", "Sheet")["precedents"]
    assert [(item["sheetName"], item["address"]) for item in refs] == [("Sheet", "A1"), ("O'Brien", "B2")]


def test_formula_dependents_reports_unsupported_formulas_and_limited_scope():
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit

    model = {"sheets": [{"name": "Sheet", "cells": {
        "A1": {"value": 2}, "B1": {"formula": 'INDIRECT("A1")'},
        "C1": {"formula": "NamedTotal+A1"}, "D1": {"formula": 'IF(A1="B2",1,2)'},
    }}]}
    tools = WorkbookAIToolkit(model=model, scope="workbook", selection={}, preview=None)
    result = tools.trace_dependents("A1", "Sheet")
    assert result["complete"] is False
    assert result["unsupportedFormulaCount"] == 2
    assert [item["address"] for item in result["dependents"]] == ["D1"]
    with pytest.raises(ValueError, match="unsupported"):
        tools.trace_precedents("B1", "Sheet")
    scoped = WorkbookAIToolkit(model=model, scope="range", selection={
        "sheetName": "Sheet", "startRow": 0, "endRow": 0, "startColumn": 0, "endColumn": 0,
    }, preview=None)
    result = scoped.trace_dependents("A1", "Sheet")
    assert result["scope"] == "range" and result["complete"] is False
    assert result["dependents"] == []


@pytest.mark.parametrize("formula", [
    "NamedTotal+A1", "Table1[Amount]+A1", "'[book.xlsx]Sheet'!A1",
    "SUM(A1:A201)", 'OFFSET(A1,0,1)', "Sheet:Other!A1", "SUM(A1",
])
def test_formula_trace_rejects_unresolved_or_unbounded_references(formula):
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit

    tools = WorkbookAIToolkit(model={"sheets": [{"name": "Sheet", "cells": {
        "C1": {"formula": formula},
    }}]}, scope="workbook", selection={}, preview=None)
    with pytest.raises(ValueError, match="unsupported"):
        tools.trace_precedents("C1", "Sheet")


def test_formula_trace_enforces_range_authorization_and_ignores_literal_addresses():
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit

    tools = WorkbookAIToolkit(model={"sheets": [{"name": "Sheet", "cells": {
        "A1": {"formula": 'IF(TRUE,"B2","C3")'}, "B1": {"value": "private"},
    }}]}, scope="range", selection={
        "sheetName": "Sheet", "startRow": 0, "endRow": 0, "startColumn": 0, "endColumn": 0,
    }, preview=None)
    assert tools.trace_precedents("A1", "Sheet")["precedents"] == []
    tools._sheets["Sheet"]["cells"]["A1"]["formula"] = "B1+1"
    with pytest.raises(ValueError, match="selection"):
        tools.trace_precedents("A1", "Sheet")


@pytest.mark.anyio
async def test_agno_tool_loop_reads_formula_dependencies_before_submitting_proposal():
    from ast import literal_eval
    from unittest.mock import AsyncMock

    model = ScriptedModel(id='scripted-trace', responses=[
        call('trace_precedents', {'address': 'C1', 'sheetId': 'Sheet'}, 'precedents'),
        call('trace_dependents', {'address': 'A1', 'sheetId': 'Sheet'}, 'dependents'),
        call('propose_operations', {'operations': [{'op': 'set_cell', 'sheetId': 'Sheet', 'address': 'D1', 'value': 5}], 'summary': '保留公式并登记合计'}, 'propose'),
        ModelResponse(content='候选待采纳'),
    ])
    preview = AsyncMock(return_value={'draftSha256': 'a' * 64})
    proposal = await AgnoWorkbookProposalPlanner(Agent(model=model)).plan_workbook(
        '核对C1依赖并将合计写入D1', model={'sheets': [{'name': 'Sheet', 'cells': {
            'A1': {'value': 2}, 'B1': {'value': 3}, 'C1': {'value': 5, 'formula': 'SUM($A$1:B1)'},
        }}]}, scope='workbook', selection={}, preview=preview, session_id='trace', user_id='u',
    )
    replies = [literal_eval(message.content) for turn in model.seen for message in turn
               if message.role == 'tool' and isinstance(message.content, str) and message.content.startswith('{')]
    assert any([item['address'] for item in reply.get('precedents', [])] == ['A1', 'B1'] for reply in replies)
    assert any(reply.get('complete') is True and [item['address'] for item in reply.get('dependents', [])] == ['C1'] for reply in replies)
    assert proposal.summary == '保留公式并登记合计'
    preview.assert_awaited_once()


def call(name, arguments, identity):
    return ModelResponse(tool_calls=[{
        'id': identity, 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)},
    }])


@pytest.mark.anyio
async def test_workbook_tools_do_not_read_or_propose_outside_frozen_range():
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit
    selection = {'sheetName': 'Sheet', 'startRow': 0, 'endRow': 0, 'startColumn': 0, 'endColumn': 0}
    async def preview(_operations):
        raise AssertionError('越权候选不得进入预览')
    tools = WorkbookAIToolkit(model={'sheets': [
        {'name': 'Sheet', 'cells': {'A1': {'value': 42}, 'B1': {'value': '秘密'}}, 'merges': ['B1:C1']},
        {'name': 'Private', 'cells': {'A1': {'value': '另一秘密'}}},
    ]}, scope='range', selection=selection, preview=preview)
    assert tools.read_range('A1')['cells']['A1']['value'] == 42
    with pytest.raises(ValueError, match='selection'):
        tools.read_range('A1:B1')
    with pytest.raises(ValueError, match='selection'):
        tools.read_cells(['A1'], sheetId='Private')
    assert '秘密' not in json.dumps(tools.find_cells('秘密'), ensure_ascii=False)
    assert 'B1:C1' not in json.dumps(tools.read_sheet_features(), ensure_ascii=False)
    assert 'Private' not in json.dumps(tools.get_workbook_context(), ensure_ascii=False)
    with pytest.raises(ValueError, match='selection'):
        await tools.propose_operations([{'op': 'sort_range', 'sheetId': 'Sheet', 'range': 'A1:A3', 'byColumn': 'A', 'order': 'asc'}], '排序')
    assert tools.proposal is None


@pytest.mark.anyio
async def test_workbook_tools_real_agno_loop_previews_complex_engine_ops_and_accepts_complete_draft():
    workbook = Workbook()
    sheet = workbook.active
    for row in [['项目', '金额'], ['乙', 9], ['甲', 2]]:
        sheet.append(row)
    sheet['D1'] = '既有合并'
    sheet.merge_cells('D1:E1')
    sheet.add_table(Table(displayName='Items', ref='A1:B3'))
    stream = BytesIO()
    workbook.save(stream)
    content = stream.getvalue()
    class RealEditor(Editor):
        def __init__(self):
            super().__init__()
            raw = self.context.model_dump(by_alias=True)
            raw['sourceFile'].update(sha256=hashlib.sha256(content).hexdigest(), size=len(content))
            self.context = NativeEditorContext.model_validate(raw)
        async def preview(self, _context, *, expected_sha256, operations):
            assert expected_sha256 == self.context.source_file.sha256
            self.previews.append(operations)
            edited = await asyncio.to_thread(patch_office, 'xlsx', content, operations)
            return {'draftSha256': hashlib.sha256(edited).hexdigest(), 'model': await asyncio.to_thread(inspect_office, 'xlsx', edited)}
    operations = [
        {'op': 'sort_range', 'sheetId': 'Sheet', 'range': 'A1:B3', 'byColumn': 'B', 'order': 'asc', 'hasHeader': True},
        {'op': 'merge_cells', 'sheetId': 'Sheet', 'range': 'D2:E2'},
        {'op': 'set_filter', 'sheetId': 'Sheet', 'range': 'G1:H3'},
        {'op': 'add_defined_name', 'name': 'SalesAmounts', 'ref': 'Sheet!$B$2:$B$3'},
        {'kind': 'applyTableEdits', 'arguments': {'edits': [{'worksheetSheetName': 'Sheet', 'tableName': 'Items', 'style': 'TableStyleMedium2', 'totalsRow': True}]}},
    ]
    model = ScriptedModel(id='scripted', responses=[
        call('get_workbook_context', {}, 'ctx'),
        call('read_range', {'range': 'A1:B3', 'sheetId': 'Sheet'}, 'read'),
        call('read_sheet_features', {'sheetId': 'Sheet'}, 'features'),
        call('propose_operations', {'operations': operations, 'summary': '排序并调整表格结构'}, 'propose'),
        ModelResponse(content='候选已完成；这段正文不是可执行代码。'),
    ])
    editor = RealEditor()
    ai = NativeWorkbookAIService(editor, planner=AgnoWorkbookProposalPlanner(Agent(model=model)), enabled=True)
    base = [{'kind': 'applyCellEdits', 'edits': [{'sheetName': 'Sheet', 'row': 4, 'column': 0, 'writeValue': True, 'cell': {'value': '人工未保存'}}]}]
    job = await ai.start_edit(None, client_request_id='tools-real-engine', instruction='金额升序、保留既有合并并新增D2:E2合并，设置筛选和名称，把Items表改为中蓝色并开启汇总行', expected_sha256=editor.context.source_file.sha256, operations=base, selection={}, scope='workbook')
    result = await ai.wait_edit_status(None, job['editId'])
    assert result['status'] == 'succeeded', result
    assert result['accepted'] is False
    assert any('人工未保存' in str(m.content) for turn in model.seen for m in turn)
    accepted = await ai.accept_edit(None, job['editId'], expected_sha256=editor.context.source_file.sha256, operations=base, snapshot_sha256=result['snapshotSha256'])
    assert accepted['operations'][0] == base[0]
    edited = await asyncio.to_thread(patch_office, 'xlsx', content, accepted['operations'])
    reopened = load_workbook(BytesIO(edited))
    target = reopened.active
    assert [target['B2'].value, target['B3'].value] == [2, 9]
    assert [target['A2'].value, target['A3'].value] == ['甲', '乙']
    assert {str(area) for area in target.merged_cells.ranges} == {'D1:E1', 'D2:E2'}
    assert target.auto_filter.ref == 'G1:H3'
    assert reopened.defined_names['SalesAmounts'].attr_text == 'Sheet!$B$2:$B$3'
    assert target.tables['Items'].tableStyleInfo.name == 'TableStyleMedium2'
    assert target.tables['Items'].totalsRowShown is True
    assert target['A5'].value == '人工未保存'
    assert load_workbook(BytesIO(content)).active['B2'].value == 9
    with pytest.raises(Exception):
        await ai.accept_edit(None, job['editId'], expected_sha256=editor.context.source_file.sha256, operations=[], snapshot_sha256=result['snapshotSha256'])
    await ai.aclose()


@pytest.mark.anyio
async def test_workbook_tool_planner_never_executes_a_model_prose_proposal():
    model = ScriptedModel(id='scripted', responses=[ModelResponse(content=json.dumps({
        'summary': '不得执行正文', 'operations': [{'kind': 'applyCellEdits', 'arguments': {
            'edits': [{'sheetName': 'Sheet', 'row': 0, 'column': 0, 'writeValue': True, 'cell': {'value': '非法候选'}}],
        }}],
    }))])
    ai = NativeWorkbookAIService(Editor(), planner=AgnoWorkbookProposalPlanner(Agent(model=model)), enabled=True)
    job = await ai.start_edit(None, client_request_id='prose', instruction='修改A1', expected_sha256='a'*64, operations=[], selection={}, scope='workbook')
    result = await ai.wait_edit_status(None, job['editId'])
    assert result['status'] == 'failed' and 'proposal' not in result
    await ai.aclose()
