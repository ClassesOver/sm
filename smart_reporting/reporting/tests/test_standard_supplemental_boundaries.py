"""标准补证执行边界与旧追溯布局回归。"""

from types import SimpleNamespace

import pytest

from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _standard_analysis_state,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import AnalysisItemWorkflow
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    standard_computation_candidates,
)


def cross_state():
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    parent.period_roles = ("current",)
    parent.period_granularity = "month"
    parent.field_ref = "source.db.income.income"
    parent.unit = "元"
    parent.dataset_sha256 = "a" * 64
    prior = SimpleNamespace(**vars(parent))
    prior.fact_id = "fact-bbbbbbbbbbbbbbbb"
    prior.dataset_id = "dataset_prior"
    prior.period_roles = ("yoy",)
    prior.period_values = (SimpleNamespace(period="2025-01", value=1),)
    state.facts.metrics.append(prior)
    state.instruction["datasets"].append(
        {
            "datasetId": prior.dataset_id,
            "columns": ["period", "department", "income"],
            "path": "datasets/prior.csv",
            "size": 10,
            "sha256": "a" * 64,
        }
    )
    state.instruction["currentAnalysis"]["datasetIds"].append(prior.dataset_id)
    req = state.decision.coding_requirements[0]
    spec = req.standard_computation.model_copy(
        update={
            "operation": "period_comparison",
            "baseline_dataset_id": prior.dataset_id,
            "baseline_parent_fact_id": prior.fact_id,
            "baseline_periods": ("2025-01",),
        }
    )
    req = req.model_copy(update={"standard_computation": spec})
    state.decision = state.decision.model_copy(update={"coding_requirements": (req,)})
    return state, prior


@pytest.mark.parametrize("fault", ["role", "parent_role", "calendar"])
def test_explicit_spec_must_obey_same_calendar_and_role_as_catalog(fault):
    state, prior = cross_state()
    if fault == "role":
        prior.period_roles = ("current",)
    elif fault == "parent_role":
        state.facts.metrics[0].period_roles = ("yoy",)
    else:
        prior.period_values = (SimpleNamespace(period="2024-07", value=1),)
        req = state.decision.coding_requirements[0]
        spec = req.standard_computation.model_copy(update={"baseline_periods": ("2024-07",)})
        state.decision = state.decision.model_copy(
            update={
                "coding_requirements": (req.model_copy(update={"standard_computation": spec}),),
            }
        )
    catalog = standard_computation_candidates(state.facts, state.instruction["datasets"])
    assert not [c for c in catalog if c["standardComputation"]["operation"] == "period_comparison"]
    assert AnalysisItemWorkflow._standard_plan(state) == ()


@pytest.mark.parametrize("side", ["current", "baseline"])
@pytest.mark.parametrize("fault", ["mismatch", "missing"])
def test_frozen_hash_must_match_registered_dataset(side, fault):
    state, prior = cross_state()
    fact = prior if side == "baseline" else state.facts.metrics[0]
    if fault == "missing":
        del fact.dataset_sha256
    else:
        fact.dataset_sha256 = "b" * 64
    assert AnalysisItemWorkflow._standard_plan(state) == ()


def test_requested_missing_month_must_not_fall_back_to_other_window():
    state, prior = cross_state()
    state.instruction["currentAnalysis"]["periods"] = ["2026-01", "2026-02"]
    catalog = standard_computation_candidates(
        state.facts, state.instruction["datasets"], state.instruction["currentAnalysis"]["periods"]
    )
    assert not [c for c in catalog if c["standardComputation"]["operation"] == "period_comparison"]
    assert AnalysisItemWorkflow._standard_plan(state) == ()


@pytest.mark.parametrize(
    "grain, current, prior_periods, role, expected",
    [
        ("month", ("2026-02", "2026-01"), ("2025-01", "2025-02"), "yoy", True),
        ("month", ("2026-01",), ("2025-12",), "mom", True),
        ("day", ("2024-02-29",), ("2023-02-28",), "yoy", False),
    ],
)
def test_explicit_calendar_uses_sets_and_does_not_borrow_leap_day(
    grain, current, prior_periods, role, expected
):
    state, prior = cross_state()
    parent = state.facts.metrics[0]
    parent.period_granularity = prior.period_granularity = grain
    parent.period_values = tuple(SimpleNamespace(period=p, value=1) for p in current)
    prior.period_values = tuple(SimpleNamespace(period=p, value=1) for p in prior_periods)
    prior.period_roles = (role,)
    req = state.decision.coding_requirements[0]
    spec = req.standard_computation.model_copy(
        update={
            "current_periods": current,
            "baseline_periods": prior_periods,
        }
    )
    state.decision = state.decision.model_copy(
        update={
            "coding_requirements": (req.model_copy(update={"standard_computation": spec}),),
        }
    )
    assert bool(AnalysisItemWorkflow._standard_plan(state)) is expected


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_old_report_without_layout_flag_or_origin_keeps_label_offset():
    import json
    import re

    from smart_reporting.report_editor.trace_sources import ReportEditorTraceService
    from smart_reporting.reporting.tests.test_supplemental_published_tables import built_source
    from smart_reporting.reporting.tests.test_trace_index_builder import _build_table
    from smart_reporting.reporting.trace.contracts_v1 import TableTraceV1
    from smart_reporting.reporting.trace.table_builder import render_table_markdown
    from smart_reporting.reporting.trace.table_quality import evaluate_table_quality
    from smart_reporting.reporting.trace.table_sources import resolve_source_cell

    raw, source, resource, trace, _ = built_source()
    document = json.loads(raw)
    rows = document["findings"][0]["rows"]
    markdown = render_table_markdown(
        trace.table_id,
        trace.column_keys,
        [[f"第{i + 1}行", *[str(value) for value in row]] for i, row in enumerate(rows)],
    )
    payload = trace.model_dump(mode="json", by_alias=True)
    payload.pop("rowLabelColumn")
    payload.pop("originMarkdown")
    # 旧报告早于单元格单位格式化，同样没有sourceCellDisplay，按原始值核验。
    payload.pop("sourceCellDisplay")
    legacy = TableTraceV1.model_validate(payload)
    assert legacy.row_label_column is True
    index = _build_table(server_table_traces=(legacy,), table_source_files=(source,))
    quality = evaluate_table_quality(
        index, markdown, {resource: document}, original_markdown=markdown
    )
    assert quality[trace.table_id].status == "verified"

    async def read(*args, **kwargs):
        return markdown.encode()

    async def unused(*args):
        return None

    async def selected(operand):
        return resolve_source_cell(operand, {resource: raw})

    tables, summary = await ReportEditorTraceService._evaluate_tables(
        SimpleNamespace(_workspace=SimpleNamespace(read_limited_regular_file=read)),
        index,
        SimpleNamespace(scope={"threadId": "thread-1"}, markdown_path="report.md"),
        markdown,
        unused,
        re.compile(r"\[\[table:([^\]]+)\]\]\n(.*?)\n\[\[/table:\1\]\]", re.S),
        lambda *args: False,
        source_cell_of=selected,
    )
    assert summary["valid"] == len(trace.cells)
    assert summary["stale"] == summary["unbound"] == 0
    assert min(item["columnIndex"] for item in tables[0]["locations"]) == 1
