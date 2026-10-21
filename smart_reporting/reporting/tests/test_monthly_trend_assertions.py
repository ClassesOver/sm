"""A monthly trend needs every adjacent level, never just two endpoints."""

import hashlib
import json

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.tests.test_deterministic_analysis import analysis, context, semantic
from smart_reporting.reporting.trace.assertions import (
    AssertionCompiler,
    AssertionRequest,
    assertion_catalog,
)
from smart_reporting.reporting.trace.monthly_trends import monthly_trend_wording_warnings
from smart_reporting.reporting.trace.numeric_text import (
    frozen_number_catalog,
    prompt_number_catalog,
)
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.subject_builder import claim_status


def trend_bundle(values=(10, 20, 30), *, months=None, stock=False, extra_rows=()):
    months = months or tuple(f"2025-{index:02d}" for index in range(1, len(values) + 1))
    raw = (
        "month,department,amount\n"
        + "".join(f"{month},A,{value}\n" for month, value in zip(months, values, strict=True))
        + "".join(row + "\n" for row in extra_rows)
    ).encode()
    declaration = {
        **semantic("amount", scope={"department": "A"}, unit="元"),
        "additiveAcross": ["department"] if stock else ["month", "department"],
    }
    ctx = context(
        "current", semantics=(declaration,), sha256=hashlib.sha256(raw).hexdigest()
    ).model_copy(
        update={"period_granularities": {"month": "month"}},
    )
    return build_deterministic_analysis_bundle(
        analysis(), (("current", raw, ctx, ("current",)),), profile_hash="a" * 64
    )


def compile_trend(document, *, selector="monthlyTrend"):
    source = json.dumps(document, ensure_ascii=False)
    token = f"{{{{value:{document['metrics'][0]['factId']}:{selector}:元}}}}"
    compiler = AssertionCompiler([source], profile_hash="a" * 64, authorization_scope_hash="b" * 64)
    return (
        compiler.compile(AssertionRequest(operation="monthly_trend", operands=(token,))),
        source,
        token,
    )


@pytest.mark.parametrize(
    "values,direction",
    [
        ((10, 20, 30), "increasing"),
        ((30, 20, 10), "decreasing"),
        ((5, 5, 5), "constant"),
        ((10, 40, 30), "mixed"),
        ((10, 10, 30), "mixed"),
        ((-30, -20, -10), "increasing"),
        ((1.001, 1.002, 1.003), "increasing"),
    ],
)
@pytest.mark.parametrize("stock", [False, True])
def test_all_registered_adjacent_levels_determine_trend(values, direction, stock):
    document = json.loads(trend_bundle(values, stock=stock).model_dump_json(by_alias=True))
    result, source, token = compile_trend(document)
    assert result.status == "supported", result.reasons
    assert result.trend_direction == direction and result.trend_comparisons == 2
    assert result.periods == ("2025-01", "2025-02", "2025-03")
    assert result.value == str(float(values[-1])) and result.scope == {"department": "A"}
    text, refs, notices = render_bound_numbers(
        "{{assert:" + result.assertion_id + "}}",
        [source],
        key="trend",
        assertions={result.assertion_id: result},
    )
    assert "未舍入" in text and "全部相邻月份" in text and len(refs) == 1 and not notices
    selected = resolve_number_reference(token, [source])
    assert selected["periods"] == result.periods and selected["value"] == values[-1]
    assert claim_status(
        anchor_bound_numbers(text, refs),
        refs[0].claim_id,
        selected["value"],
        expected_unit=selected["unit"],
        expected_periods=selected["periods"],
        expected_scope=selected["scope"],
        expected_reference=selected,
    ) == {"status": "valid", "warnings": []}


@pytest.mark.parametrize(
    "months", [("2024-12", "2025-01", "2025-02"), ("2024-11", "2024-12", "2025-01")]
)
def test_cross_year_months_are_compared_without_month_number_collision(months):
    result, _, _ = compile_trend(
        json.loads(trend_bundle(months=months).model_dump_json(by_alias=True))
    )
    assert result.status == "supported" and result.periods == months


@pytest.mark.parametrize(
    "fault",
    [
        "two_points",
        "gap",
        "duplicate",
        "reordered",
        "profile",
        "scope",
        "missing",
        "period_missing",
        "warning",
        "unknown_semantics",
        "rate_unit",
        "compound_unit",
        "average",
        "year_grain",
        "wrong_endpoint",
        "nonfinite",
    ],
)
def test_incomplete_or_unknown_trend_stays_unknown(fault):
    document = json.loads(trend_bundle().model_dump_json(by_alias=True))
    metric = document["metrics"][0]
    if fault == "two_points":
        metric["periodValues"].pop()
        metric["periodEnd"] = "2025-02"
    elif fault == "gap":
        metric["periodValues"][1]["period"] = "2025-04"
    elif fault == "duplicate":
        metric["periodValues"][1]["period"] = "2025-01"
    elif fault == "reordered":
        metric["periodValues"].reverse()
    elif fault == "profile":
        metric["profileHash"] = "c" * 64
    elif fault == "scope":
        metric["scope"] = {}
    elif fault == "missing":
        metric["missingCount"] = 1
    elif fault == "period_missing":
        metric["periodMissingCount"] = None
    elif fault == "warning":
        metric["warnings"] = ["来源完整性未确认"]
    elif fault == "unknown_semantics":
        metric["periodAggregation"] = None
    elif fault == "rate_unit":
        metric["unit"] = "%"
    elif fault == "compound_unit":
        metric["unit"] = "元/人次"
    elif fault == "average":
        metric["aggregation"] = "average"
    elif fault == "year_grain":
        metric["periodGranularity"] = "year"
    elif fault == "wrong_endpoint":
        metric["periodStart"] = "2024-12"
    elif fault == "nonfinite":
        metric["periodValues"][1]["value"] = float("inf")
    result, _, _ = compile_trend(document)
    assert result.status == "unknown" and result.trend_direction is None and result.value is None


def test_two_endpoints_cannot_substitute_for_the_trend_selector():
    document = json.loads(trend_bundle((10, 40, 30)).model_dump_json(by_alias=True))
    result, source, token = compile_trend(document, selector="periodValues.2")
    assert result.status == "unknown" and "trend_selector_invalid" in result.reasons
    reference = resolve_number_reference(token, [source])
    assert monthly_trend_wording_warnings("1至3月持续上升", reference)


@pytest.mark.parametrize(
    "text,invalid",
    [
        ("逐月严格上升", False),
        ("连续三个月回升", False),
        ("持续下降", True),
        ("逐月持平", True),
        ("属于混合变化", True),
        ("同比持续增长", True),
        ("累计逐月增加", True),
        ("稳步增长", True),
        ("预计持续增长", True),
        ("并非持续上升", True),
        ("期末登记值为30元", False),
    ],
)
def test_actual_wording_rechecks_the_whole_series(text, invalid):
    _, source, token = compile_trend(json.loads(trend_bundle().model_dump_json(by_alias=True)))
    assert (
        bool(monthly_trend_wording_warnings(text, resolve_number_reference(token, [source])))
        == invalid
    )


def test_catalog_exposes_one_trend_for_allocated_facts_only():
    document = json.loads(trend_bundle().model_dump_json(by_alias=True))
    _, source, token = compile_trend(document)
    ordinary = token.replace("monthlyTrend", "total")
    catalog = frozen_number_catalog([source])
    assert token in catalog and token not in prompt_number_catalog(catalog)
    arguments = {
        "profile_hash": "a" * 64,
        "authorization_scope_hash": "b" * 64,
        "include_month_trends": True,
    }
    assert not assertion_catalog([source], allowed_tokens=[], **arguments)
    records = assertion_catalog([source], allowed_tokens=[ordinary], **arguments)
    trends = [result for result in records.values() if result.request.operation == "monthly_trend"]
    assert len(trends) == 1 and trends[0].reference_token == token


@pytest.mark.parametrize(
    "text", ["连续四个月上升", "持续上升四个月", "三连增", "先升后降", "显著持续上升"]
)
def test_additional_count_or_shape_claims_cannot_borrow_a_level_trend_proof(text):
    _, source, token = compile_trend(json.loads(trend_bundle().model_dump_json(by_alias=True)))
    assert monthly_trend_wording_warnings(text, resolve_number_reference(token, [source]))


def test_nonfinite_series_does_not_break_an_independent_frozen_fact():
    damaged = json.loads(trend_bundle().model_dump_json(by_alias=True))
    damaged["metrics"][0]["periodValues"][1]["value"] = float("inf")
    good = trend_bundle((40, 50, 60))
    token = f"{{{{value:{good.metrics[0].fact_id}:monthlyTrend:元}}}}"
    compiler = AssertionCompiler(
        [json.dumps(damaged), good.model_dump_json(by_alias=True)],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
    )
    result = compiler.compile(AssertionRequest(operation="monthly_trend", operands=(token,)))
    assert result.status == "supported" and result.trend_direction == "increasing"


@pytest.mark.parametrize("stock", [False, True])
@pytest.mark.parametrize("bad_value", ["", "not-a-number"])
def test_entire_series_completeness_cannot_be_inferred_from_the_latest_snapshot(stock, bad_value):
    bundle = trend_bundle(stock=stock, extra_rows=(f"2025-02,A,{bad_value}",))
    metric = bundle.metrics[0]
    assert len(metric.period_values) == 3  # A partial bucket is still present.
    assert metric.series_missing_count == 1
    if stock:
        assert metric.missing_count == 0  # Latest snapshot alone looks complete.
    result, _, _ = compile_trend(json.loads(bundle.model_dump_json(by_alias=True)))
    assert result.status == "unknown" and "trend_completeness_unproven" in result.reasons


def test_legacy_series_completeness_is_unknown_and_participates_in_new_fact_identity():
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicAnalysisBundle,
    )
    from smart_reporting.reporting.trace.fact_index import assign_fact_ids

    bundle = trend_bundle(stock=True)
    document = json.loads(bundle.model_dump_json(by_alias=True))
    document["metrics"][0].pop("seriesMissingCount")
    legacy = assign_fact_ids(DeterministicAnalysisBundle.model_validate(document))
    assert legacy.metrics[0].series_missing_count is None
    assert legacy.metrics[0].fact_id != bundle.metrics[0].fact_id
    result, _, _ = compile_trend(json.loads(legacy.model_dump_json(by_alias=True)))
    assert result.status == "unknown" and result.trend_direction is None


def test_trend_window_cannot_be_expanded_and_previous_reference_is_not_borrowed():
    from smart_reporting.reporting.trace.reference_semantics import number_reference_warnings

    _, source, token = compile_trend(json.loads(trend_bundle().model_dump_json(by_alias=True)))
    reference = resolve_number_reference(token, [source])
    assert any(
        "统计窗口" in warning
        for warning in number_reference_warnings(
            "2025年1—4月，department=A，逐月严格上升，期末登记值为",
            reference,
        )
    )
    assert not number_reference_warnings(
        "前项持续下降20元[[claim:previous]]及department=A，期末登记值为",
        reference,
    )
    assert any(
        "趋势" in warning
        for warning in number_reference_warnings(
            "前项20元[[claim:previous]]及department=A，逐月严格下降，期末登记值为",
            reference,
        )
    )


def test_trend_keeps_warnings_from_all_analysis_dependencies():
    document = json.loads(trend_bundle().model_dump_json(by_alias=True))
    other = json.loads(json.dumps(document))
    other["analysisId"] = "analysis_002"
    other["metrics"][0]["warnings"] = ["另一个分析发现数据完整性风险"]
    token = f"{{{{value:{document['metrics'][0]['factId']}:monthlyTrend:元}}}}"
    compiler = AssertionCompiler(
        [json.dumps(document), json.dumps(other)],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
    )
    result = compiler.compile(AssertionRequest(operation="monthly_trend", operands=(token,)))
    assert result.status == "unknown" and result.trend_direction is None
