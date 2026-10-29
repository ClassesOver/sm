"""补证展示使用显式列语义，中文表头与缩放数值仍逐格绑定冻结来源。"""

import hashlib
import json

import pytest

from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id
from smart_reporting.reporting.trace.table_builder import build_supplemental_tables
from smart_reporting.reporting.trace.table_quality import evaluate_table_quality

from .test_trace_index_builder import _build_table


@pytest.mark.anyio
@pytest.mark.parametrize('edited', [False, True])
async def test_legacy_raw_amount_header_preserves_quality_and_editor_checks(tmp_path, edited):
    import re
    from types import SimpleNamespace

    from smart_reporting.report_editor.trace_sources import ReportEditorTraceService
    from smart_reporting.reporting.trace.contracts_v1 import TableTraceV1
    from smart_reporting.reporting.trace.table_sources import resolve_source_cell

    document = {'findings': [{'columns': ['项目', '收入（元）'],
                              'columnMeta': {'收入（元）': {'unit': '元'}},
                              'rows': [['A', 1234.5]]}]}
    raw = json.dumps(document, ensure_ascii=False).encode()
    resource = derive_resource_id('evidence/legacy-amount.json')
    current, _ = build_supplemental_tables(document, file_resource_id=resource)[0]
    # 历史快照没有展示格式字段，金额格原样输出，不能按括号表头猜成新格式。
    markdown = (f'[[table:{current.table_id}]]\n| 项目 | 收入（元） |\n'
                f'| --- | --- |\n| A | 1234.5 |\n[[/table:{current.table_id}]]')
    payload = current.model_dump(by_alias=True)
    payload.pop('sourceCellDisplay', None)
    payload['originMarkdown'] = markdown
    trace = TableTraceV1.model_validate(payload)
    source = {'path': 'evidence/legacy-amount.json', 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    index = _build_table(server_table_traces=(trace,), table_source_files=(source,))
    draft = markdown.replace('1234.5', '1234.6') if edited else markdown
    check = evaluate_table_quality(index, draft, {resource: document})[trace.table_id]
    assert check.status == ('unknown' if edited else 'verified')

    async def read(*_args, **_kwargs):
        return markdown.encode()

    async def unused(*_args):
        return None

    async def selected(operand):
        return resolve_source_cell(operand, {resource: raw})

    _, summary = await ReportEditorTraceService._evaluate_tables(
        SimpleNamespace(_workspace=SimpleNamespace(read_limited_regular_file=read)), index,
        SimpleNamespace(scope={'threadId': 'test'}, markdown_path='report.md'),
        draft, unused, re.compile(r'\[\[table:([^\]]+)\]\]\n(.*?)\n\[\[/table:\1\]\]', re.S),
        lambda *_args: False, source_cell_of=selected,
    )
    assert summary['valid'] == (1 if edited else 2)
    assert summary['stale'] == int(edited)
    assert summary['unbound'] == 0


@pytest.mark.parametrize("edited", [False, True])
def test_standard_amount_and_ratio_presentation_preserves_source_verification(edited):
    document = {"findings": [{
        "name": "院区收入同比", "columns": ["area", "current", "baseline", "changeRate", "rank"],
        "columnMeta": {
            "area": {"label": "院区"}, "current": {"unit": "元"},
            "baseline": {"unit": "元"}, "changeRate": {"unit": "%", "isPercent": False},
            "rank": {"unit": "名"},
        },
        "rows": [["总部", 13146853903, 11582097047, 0.135101338, 1]],
    }]}
    raw = json.dumps(document, ensure_ascii=False).encode()
    resource = derive_resource_id("evidence/income.json")
    trace, markdown = build_supplemental_tables(document, file_resource_id=resource)[0]
    assert trace.column_keys == ("院区", "本期值（亿元）", "对照期值（亿元）", "变动幅度（%）", "排名（名）")
    assert "| 总部 | 131.47 | 115.82 | 13.51 | 1 |" in markdown
    assert trace.cells[1].source_cell.column_index == 1
    assert trace.cells[1].column_key == "本期值（亿元）"
    source = {"path": "evidence/income.json", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    index = _build_table(server_table_traces=(trace,), table_source_files=(source,))
    if edited:
        markdown = markdown.replace("131.47", "131.48")
        trace = trace.model_copy(update={"origin_markdown": markdown})
        index = index.model_copy(update={"tables": (trace,)})
    check = evaluate_table_quality(index, markdown, {resource: document})[trace.table_id]
    assert check.status == ("unknown" if edited else "verified")
    assert check.checked_cells == (4 if edited else 5)


def test_unknown_units_and_percentage_conventions_are_not_invented():
    document = {"findings": [{
        "columns": ["类别", "current", "share", "rank"],
        "columnMeta": {"share": {"unit": "%", "isPercent": True}, "rank": {"unit": "名"}},
        "rows": [["A", 1250.5, -12.345, 1], ["B", None, 0, 2]],
    }]}
    trace, markdown = build_supplemental_tables(document, file_resource_id="trf-" + "1" * 20)[0]
    assert "本期值（单位未提供）" in trace.column_keys
    assert "| A | 1,250.50 | -12.35 | 1 |" in markdown
    assert "| B | — | 0.00 | 2 |" in markdown


def test_dimension_headers_use_only_registered_dataset_schema():
    document = {"findings": [{"columns": ["area", "value"],
                               "columnMeta": {"value": {"unit": "元"}},
                               "rows": [["总部", 1000]]}]}
    contexts = [{"datasetId": "income", "schema": {"tables": [{"columns": [
        {"name": "area", "description": "院区，包括总部和北部"},
    ]}]}}, {"datasetId": "foreign", "schema": {"tables": [{"columns": [
        {"name": "area", "description": "无关字段"},
    ]}]}}]
    trace, markdown = build_supplemental_tables(
        document, file_resource_id="trf-" + "1" * 20,
        dataset_ids=("income",), dataset_contexts=contexts,
    )[0]
    assert trace.column_keys == ("院区", "指标值（元）")
    assert "| 总部 | 1,000 |" in markdown


@pytest.mark.anyio
async def test_formatted_source_cells_validate_in_editor(tmp_path):
    import re
    from types import SimpleNamespace

    from smart_reporting.report_editor.trace_sources import ReportEditorTraceService
    from smart_reporting.reporting.trace.table_sources import resolve_source_cell

    document = {"findings": [{"columns": ["科室", "share"],
                               "columnMeta": {"share": {"unit": "%", "isPercent": False}},
                               "rows": [["A", 0.125]]}]}
    raw = json.dumps(document).encode()
    resource = derive_resource_id("evidence/ratios.json")
    trace, markdown = build_supplemental_tables(document, file_resource_id=resource)[0]
    source = {"path": "evidence/ratios.json", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    index = _build_table(server_table_traces=(trace,), table_source_files=(source,))

    async def read(*_args, **_kwargs):
        return markdown.encode()

    async def unused(*_args):
        return None

    async def selected(operand):
        return resolve_source_cell(operand, {resource: raw})

    _tables, summary = await ReportEditorTraceService._evaluate_tables(
        SimpleNamespace(_workspace=SimpleNamespace(read_limited_regular_file=read)), index,
        SimpleNamespace(scope={"threadId": "test"}, markdown_path="report.md"),
        markdown, unused, re.compile(r'\[\[table:([^\]]+)\]\]\n(.*?)\n\[\[/table:\1\]\]', re.S),
        lambda *_args: False, source_cell_of=selected,
    )
    assert summary["valid"] == 2
    assert summary["stale"] == summary["unbound"] == 0
