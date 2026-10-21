"""Only the dedicated snapshot rule can prove annual-reset differences."""

import copy
import hashlib
import json

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.assertions import (
    AssertionCompiler,
    AssertionRequest,
    MetricCapability,
    assertion_catalog,
    assertion_request_for_token,
)
from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers

from .test_deterministic_analysis import analysis, context, semantic


def cumulative_document(*, months=("2024-12", "2025-01", "2025-02"), values=(1000, 10, 25)):
    raw = ("month,department,amount\n" + "".join(
        f"{month},A,{value}\n" for month, value in zip(months, values, strict=True)
    )).encode()
    declaration = {
        **semantic("amount", scope={"department": "A"}, unit="元"),
        "additiveAcross": ["department"],
    }
    ctx = context("current", semantics=(declaration,), sha256=hashlib.sha256(raw).hexdigest())
    ctx = ctx.model_copy(update={"period_granularities": {"month": "month"}})
    bundle = build_deterministic_analysis_bundle(
        analysis(), (("current", raw, ctx, ("current",)),), profile_hash="a" * 64,
        profile_metrics=({
            "code": "annual_cumulative_amount", "kind": "amount", "aggregation": "sum",
            "fieldRef": declaration["fieldRef"], "description": "累计收入",
            "cumulativePolicy": {
                "reset": "calendar_year_zero", "observation": "closed_month_end",
                "changes": "signed_snapshot_delta",
            },
        },),
    )
    assert len(bundle.metrics) == 1, bundle.warnings
    return json.loads(bundle.model_dump_json(by_alias=True))


def compile_change(document, index=1, *, comparison="same_period", profile_hash="a" * 64):
    source = json.dumps(document, ensure_ascii=False)
    token = f"{{{{value:{document['metrics'][0]['factId']}:cumulativeChanges.{index}:元}}}}"
    compiler = AssertionCompiler([source], profile_hash=profile_hash, authorization_scope_hash="b" * 64)
    result = compiler.compile(AssertionRequest(
        operation="cumulative_change", operands=(token,), comparison=comparison,
    ))
    return result, compiler, token, source


@pytest.mark.parametrize("index,amount,baseline,phrase", [
    (1, "10.0", (), "按自然年重置零基线"),
    (2, "15.0", ("2025-01",), "以2025-01月末累计快照为基线"),
])
def test_dedicated_rule_proves_snapshot_differences_with_reset(index, amount, baseline, phrase):
    result, compiler, token, source = compile_change(cumulative_document(), index)
    assert result.status == "supported", result.reasons
    assert result.value == amount
    assert result.baseline_periods == baseline
    assert result.periods == (f"2025-0{index}",)
    assert result.source_hashes == (hashlib.sha256(source.encode()).hexdigest(),)
    assert compiler._metric_capability(token).metric_kind == "cumulative"
    assert assertion_request_for_token(token, compiler.resolver).operation == "cumulative_change"
    phrase_text = result.factual_fragment()
    assert phrase in phrase_text
    assert "可能包含追溯调整，不等同当期业务流量" in phrase_text
    assert "department=A" in phrase_text and "累计收入" in phrase_text
    assert result.model_validate_json(result.model_dump_json()).factual_fragment() == phrase_text
    text, refs, notices = render_bound_numbers(
        "{{assert:" + result.assertion_id + "}}", [source], key="cumulative",
        assertions={result.assertion_id: result},
    )
    assert phrase in text and len(refs) == 1 and not notices


def test_signed_snapshot_correction_does_not_acquire_a_flow_claim():
    doc = cumulative_document(values=(1000, 10, 3))
    result, _, _, _ = compile_change(doc, 2)
    assert result.status == "supported" and result.value == "-7.0"
    assert "不等同当期业务流量" in result.factual_fragment()


@pytest.mark.parametrize("fault", ["profile", "warning", "missing", "reset", "gap", "total"])
def test_invalid_premise_keeps_snapshot_change_unknown(fault):
    doc = cumulative_document()
    metric = doc["metrics"][0]
    profile = "a" * 64
    if fault == "profile":
        profile = "c" * 64
    elif fault == "warning":
        metric["warnings"] = ["上游完整性未确认"]
    elif fault == "missing":
        metric["seriesMissingCount"] = 1
    elif fault == "reset":
        metric["cumulativePolicy"]["reset"] = "fiscal_year"
    elif fault == "gap":
        metric["periodValues"][1]["period"] = "2025-03"
    elif fault == "total":
        metric["total"] += 1
    result, _, _, _ = compile_change(doc, profile_hash=profile)
    assert result.status == "unknown" and result.value is None and result.reasons


def test_warning_union_cannot_be_bypassed_with_another_clean_source():
    doc = cumulative_document()
    dirty = copy.deepcopy(doc)
    dirty["metrics"][0]["warnings"] = ["历史源未核验"]
    result, _, token, source = compile_change(doc)
    compiler = AssertionCompiler(
        [source, json.dumps(dirty, ensure_ascii=False)],
        profile_hash="a" * 64, authorization_scope_hash="b" * 64,
    )
    result = compiler.compile(AssertionRequest(operation="cumulative_change", operands=(token,)))
    assert result.status != "supported" and result.value is None


def test_non_january_first_snapshot_has_no_zero_baseline():
    doc = cumulative_document(months=("2025-02", "2025-03"), values=(25, 30))
    result, _, _, _ = compile_change(doc, 0)
    assert result.status == "unknown" and result.value is None
    result, _, _, _ = compile_change(doc, 1)
    assert result.status == "supported" and result.value == "5.0"


def test_cumulative_rule_cannot_be_selected_as_yoy_or_value():
    doc = cumulative_document()
    result, compiler, token, _ = compile_change(doc, comparison="yoy")
    assert result.status == "unknown"
    assert compiler.compile(AssertionRequest(operation="value", operands=(token,))).status == "unknown"


def test_ordinary_recorded_point_remains_valid_but_generic_change_cannot_bypass_policy():
    doc = cumulative_document()
    source = json.dumps(doc, ensure_ascii=False)
    fact_id = doc["metrics"][0]["factId"]
    compiler = AssertionCompiler(
        [source], profile_hash="a" * 64, authorization_scope_hash="b" * 64,
        capabilities={fact_id: MetricCapability(metricKind="flow", comparisonKey="same", monthlyFlowComplete=True)},
    )
    current = f"{{{{value:{fact_id}:periodValues.1:元}}}}"
    previous = f"{{{{value:{fact_id}:periodValues.0:元}}}}"
    assert compiler.compile(AssertionRequest(operation="value", operands=(current,))).status == "supported"
    result = compiler.compile(AssertionRequest(operation="difference", operands=(current, previous), comparison="mom"))
    assert result.status == "unknown" and "cumulative_snapshot_policy_required" in result.reasons


def test_automatic_catalog_is_opt_in_scoped_and_bounded_to_latest_twelve():
    months = tuple(f"{2023 + index // 12}-{index % 12 + 1:02d}" for index in range(36))
    doc = cumulative_document(months=months, values=tuple(range(1, 37)))
    source = json.dumps(doc, ensure_ascii=False)
    token = f"{{{{value:{doc['metrics'][0]['factId']}:total:元}}}}"
    kwargs = dict(profile_hash="a" * 64, authorization_scope_hash="b" * 64)
    ordinary = assertion_catalog([source], allowed_tokens=[token], **kwargs)
    assert all(result.request.operation != "cumulative_change" for result in ordinary.values())
    chosen = assertion_catalog([source], allowed_tokens=[token], include_cumulative_changes=True, **kwargs)
    changes = [result for result in chosen.values() if result.request.operation == "cumulative_change"]
    assert len(changes) == 12 and all(result.status == "supported" for result in changes)
    assert {result.periods[0] for result in changes} == set(months[-12:])
    assert assertion_catalog([source], allowed_tokens=[], include_cumulative_changes=True, **kwargs) == {}
