"""生成表格与正文来源必须与冻结事实保持一致。"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from markdown_it import MarkdownIt

from smart_reporting.report_editor.trace_sources import ReportEditorTraceService
from smart_reporting.reporting.delivery.artifacts_v1 import _TABLE_BLOCK
from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id
from smart_reporting.reporting.trace.semantic_bindings import (
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.subject_builder import (
    build_claim_subject_bindings,
    value_matches,
)
from smart_reporting.reporting.trace.table_builder import build_analysis_table, build_table_trace
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime.sections import RuntimeSectionsMixin

from .test_deterministic_analysis import analysis, context, semantic
from .test_trace_server_tables import _Harness


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(("value", "label", "shown"), [
    ("1.005", "收入", "1.01"),
    ("-1.005", "收入", "-1.01"),
    ("-0.004", "收入", "0.00"),
    ("3600", "收入|净额", "3,600"),
    ("3600", "收入 **合计**", "3,600"),
    ("3600", r"收入\|净额", "3,600"),
    ("3600", "收入 &amp; `净额`", "3,600"),
])
async def test_generated_table_retains_literal_header_and_valid_value(value, label, shown):
    content = f"month,department,amount\n2025-09,A,{value}\n".encode()
    bundle = build_deterministic_analysis_bundle(
        analysis(),
        (("current", content, context("current"), ("current",)),),
        profile_metrics=({
            "code": "income", "fieldRef": "dynamic_source.dynamic_db.dynamic_table.amount",
            "description": label,
        },),
    )
    trace, markdown = build_analysis_table(
        bundle, fact_file_resource_id="trf-" + "0" * 20,
    )
    parser = MarkdownIt().enable("table")
    tokens = parser.parse(markdown)
    assert sum(token.type == "th_open" for token in tokens) == 2
    assert f"| {shown} |" in markdown

    results, summary = await _evaluate_table(bundle, trace, markdown)
    assert summary["valid"] == 1
    assert summary["stale"] == summary["unbound"] == 0
    assert results[0]["locations"][0]["columnKey"] == trace.column_keys[0]
    assert results[0]["locations"][0]["text"] == shown

    changed = markdown.replace(f"| {shown} |", "| 9,999 |")
    _, summary = await _evaluate_table(bundle, trace, changed, committed=markdown)
    assert summary["valid"] == 0
    assert summary["stale"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_escaped_row_label_keeps_its_fact_location():
    bundle = build_deterministic_analysis_bundle(
        analysis(),
        (("current", b"month,department,amount\n2025-09,A,3600\n",
          context("current"), ("current",)),),
        profile_metrics=({
            "code": "income", "fieldRef": "dynamic_source.dynamic_db.dynamic_table.amount",
        },),
    )
    trace, markdown = build_table_trace(bundle, {
        "tableId": "table-income", "metricCodes": ["income"],
        "rows": [{"key": "period:2025-09", "label": r"本期\|合计 *原值*", "period": "2025-09"}],
    }, fact_file_resource_id="trf-" + "0" * 20)
    results, summary = await _evaluate_table(bundle, trace, markdown)
    assert summary["valid"] == 1
    assert results[0]["locations"][0]["rowLabel"] == r"本期\|合计 *原值*"


async def _evaluate_table(bundle, trace, markdown, *, committed=None):
    class Workspace:
        async def read_limited_regular_file(self, *_args, **_kwargs):
            return (committed or markdown).encode()

    async def fact_value(_ref, _row):
        return bundle.metrics[0].period_values[0].value

    async def fact_unit(_ref, _row):
        return bundle.metrics[0].unit

    return await ReportEditorTraceService._evaluate_tables(
        SimpleNamespace(_workspace=Workspace()), SimpleNamespace(tables=(trace,)),
        SimpleNamespace(scope={"threadId": "thread"}, markdown_path="report.md"),
        markdown, fact_value, _TABLE_BLOCK, value_matches, fact_unit_of=fact_unit,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("legacy_ids", [False, True])
async def test_grouped_claims_never_bind_to_another_analyses_values(reverse, legacy_ids):
    content = (
        b"month,department,campus,amount\n"
        b"2025-09,A,X,10\n2025-09,A,Y,20\n2025-09,B,X,30\n"
    )
    dataset = context(
        "current", fields=("month", "department", "campus", "amount"),
        semantics=(semantic("amount", unit="元"),), sha256=hashlib.sha256(content).hexdigest(),
    )
    bundles = []
    for analysis_id, grain in (("analysis_001", "department"), ("analysis_002", "campus")):
        item = analysis().model_copy(update={"analysis_id": analysis_id, "organization_grain": (grain,)})
        bundle = build_deterministic_analysis_bundle(
            item, (("current", content, dataset, ("current",)),),
            profile_metrics=({
                "code": "income", "fieldRef": "dynamic_source.dynamic_db.dynamic_table.amount",
            },),
        )
        if legacy_ids:
            bundle = bundle.model_copy(update={"metrics": (
                bundle.metrics[0].model_copy(update={"fact_id": "fact-" + "a" * 16}),
            )})
        bundles.append(bundle)

    artifacts, resources, files, identities = [], {}, {}, {}
    for index, bundle in enumerate(bundles, 1):
        token = "{{value:" + bundle.metrics[0].fact_id + ":topGroups.0:元}}"
        _, refs, notices = render_bound_numbers(
            "分组贡献为" + token + "。", [bundle.model_dump_json(by_alias=True)], key=f"section_{index:03}:b1",
        )
        assert len(refs) == 1 and not notices
        artifacts.append(SimpleNamespace(
            section_code=f"section_{index:03}", claims=(),
            blocks=(SimpleNamespace(number_references=refs, review_notices=(), claim_ids=()),),
        ))
    ordered = list(reversed(bundles)) if reverse else bundles
    if legacy_ids:
        # 冲突后再遇到首份内容也不能恢复有歧义的 ID。
        ordered = [*ordered, ordered[0].model_copy(update={"analysis_id": "analysis_003"})]
    for bundle in ordered:
        path = f"facts/{bundle.analysis_id}.json"
        raw = bundle.model_dump_json(by_alias=True).encode()
        files[path] = raw
        identities[bundle.analysis_id] = FileIdentity(path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        resources[bundle.analysis_id] = derive_resource_id(path)
    tables, traces, directory, values = await RuntimeSectionsMixin._build_server_tables(
        _Harness(files), SimpleNamespace(),
        checkpoint=SimpleNamespace(deterministic_fact_files=identities),
        outline=SimpleNamespace(sections=tuple(
            SimpleNamespace(code=f"section_{index:03}", analysis_ids=(bundle.analysis_id,))
            for index, bundle in enumerate(bundles, 1)
        )),
    )
    assert len(tables) == len(traces) == 2
    subjects = build_claim_subject_bindings(artifacts, directory, resources)
    if legacy_ids:
        assert subjects == ()
        assert "fact-" + "a" * 16 not in directory
        assert "fact-" + "a" * 16 not in values
    else:
        assert len(subjects) == 2
        for subject, bundle in zip(subjects, bundles):
            ref = subject.fact_refs[0]
            assert ref.analysis_id == bundle.analysis_id
            assert ref.file_resource_id == resources[bundle.analysis_id]
            resolved = resolve_number_reference(
                subject.number_reference.token, [files[f"facts/{ref.analysis_id}.json"].decode()],
            )
            assert resolved["value"] == bundle.metrics[0].top_groups[0].value
            assert resolved["scope"]["group"] == bundle.metrics[0].top_groups[0].group
