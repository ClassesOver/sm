"""Time additivity is confirmed before freezing; readers never infer it from an old sum."""

import hashlib
import json

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.tests.test_deterministic_analysis import analysis, context, semantic
from smart_reporting.reporting.trace.assertions import AssertionCompiler, assertion_catalog
from smart_reporting.reporting.trace.fact_index import assign_fact_ids, metric_fact_identity
from smart_reporting.reporting.trace.fact_service import read_fact_document
from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers


def frozen_bundle(*, additive=("month", "department"), months=(1, 2), comparison=True):
    datasets = []
    for name, year, role, scale in (("current", 2025, "current", 100), ("yoy", 2024, "yoy", 50)):
        if name == "yoy" and not comparison:
            continue
        raw = (
            "month,department,amount\n"
            + "".join(f"{year}-{month:02d},A,{month * scale}\n" for month in months)
        ).encode()
        declaration = {
            **semantic("amount", scope={"department": "A"}, unit="元"),
            "additiveAcross": list(additive),
        }
        ctx = context(
            name, semantics=(declaration,), sha256=hashlib.sha256(raw).hexdigest()
        ).model_copy(update={"period_granularities": {"month": "month"}})
        datasets.append((name, raw, ctx, (role,)))
    return build_deterministic_analysis_bundle(analysis(), tuple(datasets), profile_hash="a" * 64)


def catalog(bundle, *tokens):
    source = bundle.model_dump_json(by_alias=True)
    return assertion_catalog(
        [source], profile_hash="a" * 64, authorization_scope_hash="b" * 64, allowed_tokens=tokens
    ), source


@pytest.mark.parametrize(
    "additive,expected", [(("month", "department"), "sum"), (("department",), "last"), ((), None)]
)
def test_time_aggregation_is_frozen_from_confirmed_reporting_axis(additive, expected):
    bundle = frozen_bundle(additive=additive, comparison=False)
    fact = bundle.metrics[0]
    assert fact.period_aggregation == expected
    loaded = read_fact_document(bundle.model_dump_json(by_alias=True).encode())
    assert loaded["metrics"][0]["periodAggregation"] == expected
    assert ("最新登记期间" in fact.formula) == (expected == "last")
    assert fact.total == (200 if expected == "last" else 300)


def test_explicit_flow_identity_does_not_rewrite_legacy_unknown_metadata():
    bundle = frozen_bundle(comparison=False)
    payload = json.loads(bundle.model_dump_json(by_alias=True))
    payload["metrics"][0].pop("periodAggregation")
    legacy = DeterministicAnalysisBundle.model_validate(payload)
    assert legacy.metrics[0].period_aggregation is None
    assert "periodAggregation" not in metric_fact_identity(legacy.metrics[0])
    assert metric_fact_identity(legacy.metrics[0]) != metric_fact_identity(bundle.metrics[0])
    legacy = assign_fact_ids(legacy)
    assert legacy.metrics[0].fact_id != bundle.metrics[0].fact_id
    tokens = f"{{{{value:{legacy.metrics[0].fact_id}:monthlyAverage:元}}}}"
    records, _ = catalog(legacy, tokens)
    assert next(iter(records.values())).status == "unknown"


def test_frozen_flow_monthly_average_needs_no_model_capability_declaration():
    bundle = frozen_bundle(comparison=False)
    token = f"{{{{value:{bundle.metrics[0].fact_id}:monthlyAverage:元}}}}"
    records, source = catalog(bundle, token)
    (result,) = records.values()
    assert result.status == "supported" and result.value == "150.0"
    assert result.periods == ("2025-01", "2025-02")
    text, references, notices = render_bound_numbers(
        "{{assert:" + result.assertion_id + "}}", [source], key="monthly", assertions=records
    )
    assert "2025-01至2025-02" in text and "月均值" in text
    assert len(references) == 1 and references[0].token == token and not notices


@pytest.mark.parametrize(
    "selector,unit,value", [("change", "元", "150.0"), ("changeRate", "%", "100.0")]
)
def test_multi_month_comparison_uses_explicit_frozen_flow_contract(selector, unit, value):
    bundle = frozen_bundle()
    comparison = bundle.comparisons[0]
    token = f"{{{{value:{comparison.fact_id}:{selector}:{unit}}}}}"
    records, source = catalog(bundle, token)
    (result,) = records.values()
    assert result.status == "supported", result.reasons
    assert result.value == value
    assert result.periods == ("2025-01", "2025-02") and result.baseline_periods == (
        "2024-01",
        "2024-02",
    )
    _, refs, notices = render_bound_numbers(
        "{{assert:" + result.assertion_id + "}}", [source], key="comparison", assertions=records
    )
    assert len(refs) == 1 and not notices


@pytest.mark.parametrize(
    "fault", ["stock", "unknown", "gap", "missing_values", "missing_period", "profile", "warning"]
)
def test_monthly_average_never_upgrades_incomplete_or_nonflow_history(fault):
    bundle = frozen_bundle(months=(1, 3) if fault == "gap" else (1, 2), comparison=False)
    payload = json.loads(bundle.model_dump_json(by_alias=True))
    metric = payload["metrics"][0]
    if fault == "stock":
        metric["periodAggregation"] = "last"
    elif fault == "unknown":
        metric.pop("periodAggregation")
    elif fault == "missing_values":
        metric["missingCount"] = 1
    elif fault == "missing_period":
        metric.pop("periodMissingCount")
    elif fault == "profile":
        metric["profileHash"] = "c" * 64
    elif fault == "warning":
        metric["warnings"] = ["数据完整性尚未确认"]
    modified = DeterministicAnalysisBundle.model_validate(payload)
    token = f"{{{{value:{modified.metrics[0].fact_id}:monthlyAverage:元}}}}"
    records, _ = catalog(modified, token)
    (result,) = records.values()
    assert result.status == "unknown" and result.value is None
    assert result.reference_token is None


def test_comparison_with_one_legacy_operand_cannot_borrow_other_operands_flow_contract():
    bundle = frozen_bundle()
    payload = json.loads(bundle.model_dump_json(by_alias=True))
    payload["metrics"][1].pop("periodAggregation")
    modified = DeterministicAnalysisBundle.model_validate(payload)
    token = f"{{{{value:{modified.comparisons[0].fact_id}:changeRate:%}}}}"
    records, _ = catalog(modified, token)
    (result,) = records.values()
    assert result.status == "unknown" and result.value is None


def test_an_explicit_stock_contract_cannot_be_overridden_by_flow_capability():
    from smart_reporting.reporting.trace.assertions import AssertionRequest, MetricCapability

    bundle = frozen_bundle(additive=("department",), comparison=False)
    fact = bundle.metrics[0]
    compiler = AssertionCompiler(
        [bundle.model_dump_json(by_alias=True)],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
        capabilities={fact.fact_id: MetricCapability(metricKind="flow", monthlyFlowComplete=True)},
    )
    result = compiler.compile(
        AssertionRequest(
            operation="monthly_average",
            operands=(f"{{{{value:{fact.fact_id}:monthlyAverage:元}}}}",),
        )
    )
    assert result.status == "unknown"


@pytest.mark.parametrize("operation", ["monthly_average", "comparison"])
def test_merging_same_fact_from_other_analysis_never_erases_quality_warning(operation):
    bundle = frozen_bundle(comparison=operation == "comparison")
    original = bundle.model_dump_json(by_alias=True)
    payload = json.loads(original)
    payload["analysisId"] = "analysis_002"
    payload["metrics"][0]["warnings"] = ["该指标存在尚未解决的数据质量缺口"]
    if operation == "monthly_average":
        token = f"{{{{value:{bundle.metrics[0].fact_id}:monthlyAverage:元}}}}"
    else:
        token = f"{{{{value:{bundle.comparisons[0].fact_id}:changeRate:%}}}}"
    for contents in ([original, json.dumps(payload)], [json.dumps(payload), original]):
        records = assertion_catalog(
            contents,
            profile_hash="a" * 64,
            authorization_scope_hash="b" * 64,
            allowed_tokens=[token],
        )
        (result,) = records.values()
        assert result.status == "unknown" and result.value is None


def test_comparison_key_alone_does_not_establish_legacy_time_additivity():
    from smart_reporting.reporting.trace.assertions import AssertionRequest, MetricCapability

    bundle = frozen_bundle()
    payload = json.loads(bundle.model_dump_json(by_alias=True))
    for metric in payload["metrics"]:
        metric.pop("periodAggregation")
    compiler = AssertionCompiler(
        [json.dumps(payload)],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
        capabilities={
            metric["factId"]: MetricCapability(comparisonKey="same-definition")
            for metric in payload["metrics"]
        },
    )
    result = compiler.compile(
        AssertionRequest(
            operation="relative_change",
            comparison="yoy",
            operands=tuple(
                f"{{{{value:{metric['factId']}:total:元}}}}" for metric in payload["metrics"]
            ),
        )
    )
    assert result.status == "unknown" and "time_additivity_unproven" in result.reasons


def test_time_contract_is_evaluated_once_per_fact_for_many_value_references(monkeypatch):
    from smart_reporting.reporting.trace import assertions

    bundle = frozen_bundle(comparison=False)
    fact = bundle.metrics[0]
    calls = 0
    consecutive = assertions._consecutive_months

    def count(periods):
        nonlocal calls
        calls += 1
        return consecutive(periods)

    monkeypatch.setattr(assertions, "_consecutive_months", count)
    compiler = AssertionCompiler(
        [bundle.model_dump_json(by_alias=True)],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
    )
    for selector in ("total", "periodValues.0", "periodValues.1"):
        result = compiler.compile(
            assertions.AssertionRequest(
                operation="value", operands=(f"{{{{value:{fact.fact_id}:{selector}:元}}}}",)
            )
        )
        assert result.status == "supported"
    assert calls == 1
