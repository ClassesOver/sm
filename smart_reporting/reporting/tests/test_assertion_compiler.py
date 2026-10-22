import json

import pytest

from smart_reporting.reporting.tests.test_content_review import _metric
from smart_reporting.reporting.trace.assertions import (
    AssertionCompiler,
    AssertionRequest,
    MetricCapability,
)
from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers


def facts(*, scope=None, values=(100, 40), unit="万元", second=False):
    first = {
        **_metric(values=values),
        "scope": scope or {},
        "unit": unit,
        "displayName": "实际支出",
        "periodAggregation": "sum",
    }
    metrics = [first]
    if second:
        metrics.append(
            {
                **first,
                "factId": "fact-" + "b" * 16,
                "field": "budget",
                "displayName": "预算支出",
                "total": 200,
                "periodValues": [
                    {"period": "2025-01-01", "value": 120},
                    {"period": "2025-02-01", "value": 80},
                ],
            }
        )
    return json.dumps({"analysisId": "analysis_001", "metrics": metrics}, ensure_ascii=False)


def compiler(contents, capabilities=None):
    return AssertionCompiler(
        contents,
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
        capabilities=capabilities,
    )


def token(letter="a", selector="total", unit="万元"):
    return "{{value:fact-" + letter * 16 + ":" + selector + ":" + unit + "}}"


def test_server_value_is_self_contained_and_reference_remains_recomputable():
    content = facts(scope={"院区": "北院"})
    assertion = compiler([content]).compile(
        AssertionRequest(operation="value", operands=(token(),))
    )
    assert assertion.status == "supported"
    assert assertion.value == "140.0"
    assert (
        "北院" in assertion.factual_fragment()
        and "2025-01至2025-02" in assertion.factual_fragment()
    )
    text, refs, notices = render_bound_numbers(
        "{{assert:" + assertion.assertion_id + "}}",
        [content],
        key="test",
        assertions={assertion.assertion_id: assertion},
    )
    assert "北院" in text and "140" in text and "assert-" not in text
    assert len(refs) == 1 and refs[0].token == token()
    assert not notices


def test_unknown_scope_and_forged_assertion_do_not_generate_factual_value():
    content = facts()
    result = compiler([content]).compile(AssertionRequest(operation="value", operands=(token(),)))
    assert result.status == "unknown" and "scope_unknown" in result.reasons
    assert result.value is None
    text, refs, _ = render_bound_numbers(
        "{{assert:assert-" + "f" * 64 + "}}", [content], key="test"
    )
    assert "证据不足" in text and not refs and "140" not in text


@pytest.mark.parametrize("scope", [{"院区": " "}, {"": "北院"}, {"院区": "北院", "科室": ""}])
def test_blank_scope_identity_is_not_accepted_as_a_verified_subject(scope):
    result = compiler([facts(scope=scope)]).compile(AssertionRequest(operation="value", operands=(token(),)))
    assert result.status == "unknown" and "scope_value_unknown" in result.reasons
    assert result.value is None
    assert "140" not in result.factual_fragment()


@pytest.mark.parametrize(
    "kind,complete,expected",
    [
        ("flow", True, "supported"),
        ("flow", False, "unknown"),
        ("stock", True, "unknown"),
        ("cumulative", True, "unknown"),
        ("unknown", True, "unknown"),
    ],
)
def test_monthly_average_requires_explicit_flow_and_completeness(kind, complete, expected):
    content = facts(scope={"院区": "北院"})
    capabilities = {
        "fact-" + "a" * 16: MetricCapability(metricKind=kind, monthlyFlowComplete=complete)
    }
    result = compiler([content], capabilities).compile(
        AssertionRequest(
            operation="monthly_average",
            operands=(token(selector="monthlyAverage"),),
        )
    )
    assert result.status == expected


def test_difference_requires_business_comparability_and_share_requires_membership():
    content = facts(scope={"院区": "北院"}, second=True)
    request = AssertionRequest(operation="difference", operands=(token(), token("b")))
    assert compiler([content]).compile(request).status == "unknown"
    caps = {
        "fact-" + letter * 16: MetricCapability(comparisonKey="budget-realized") for letter in "ab"
    }
    result = compiler([content], caps).compile(request)
    assert result.status == "supported" and result.value == "-60.0"
    share = request.model_copy(update={"operation": "share"})
    assert "population_membership_required" in compiler([content], caps).compile(share).reasons
    caps = {
        key: value.model_copy(
            update={"population_id": "hospital", "denominator_fact_id": "fact-" + "b" * 16}
        )
        for key, value in caps.items()
    }
    assert compiler([content], caps).compile(share).value == "70.0"


def test_irrelevant_evidence_does_not_change_proof_identity():
    content = facts(scope={"院区": "北院"})
    unrelated = facts(scope={"院区": "南院"}).replace("fact-" + "a" * 16, "fact-" + "c" * 16)
    request = AssertionRequest(operation="value", operands=(token(),))
    before = compiler([content]).compile(request)
    assert compiler([content, unrelated]).compile(request) == before
    changed = compiler([content.replace('"value": 100', '"value": 101')]).compile(request)
    assert changed.assertion_id != before.assertion_id
    assert compiler([]).compile(request).status == "unknown"


def test_same_identity_conflicting_sources_never_get_a_proof():
    content = facts(scope={"院区": "北院"})
    changed = content.replace('"total": 140', '"total": 141')
    result = compiler([content, changed]).compile(
        AssertionRequest(operation="value", operands=(token(),))
    )
    assert result.status == "conflicting" and result.value is None


@pytest.mark.parametrize(
    "baseline,comparison,status",
    [
        (200, "yoy", "supported"),
        (0, "yoy", "unknown"),
        (-200, "yoy", "unknown"),
        (200, "mom", "unknown"),
    ],
)
def test_relative_change_requires_correct_windows_and_positive_baseline(
    baseline, comparison, status
):
    document = json.loads(facts(scope={"院区": "北院"}, second=True))
    right = document["metrics"][1]
    right["total"] = baseline
    right["periodValues"] = [
        {"period": f"2024-{month:02d}-01", "value": baseline / 2} for month in (1, 2)
    ]
    caps = {
        "fact-" + letter * 16: MetricCapability(comparisonKey="same-definition") for letter in "ab"
    }
    result = compiler([json.dumps(document)], caps).compile(
        AssertionRequest(
            operation="relative_change",
            operands=(token(), token("b")),
            comparison=comparison,
        )
    )
    assert result.status == status
    if status == "supported":
        assert result.value == "-30.0"
    else:
        assert result.value is None


def comparison_document(*, kind="yoy", baseline=200, current=140):
    current_metric = {
        **_metric(values=(current,)),
        "scope": {"院区": "北院"},
        "unit": "万元",
        "displayName": "实际支出",
        "profileHash": "a" * 64,
        "periodMissingCount": 0,
    }
    baseline_month = "2024-01-01" if kind == "yoy" else "2024-12-01"
    baseline_metric = {
        **current_metric,
        "factId": "fact-" + "b" * 16,
        "datasetId": "baseline",
        "datasetSha256": "d" * 64,
        "periodRoles": [kind],
        "total": baseline,
        "periodValues": [{"period": baseline_month, "value": baseline}],
    }
    comparison = {
        "factId": "fact-" + "c" * 16,
        "inputFactIds": [current_metric["factId"], baseline_metric["factId"]],
        "scope": current_metric["scope"],
        "comparisonType": kind,
        "field": current_metric["field"],
        "fieldRef": current_metric["fieldRef"],
        "currentDatasetId": "current",
        "baselineDatasetId": "baseline",
        "currentDatasetSha256": "b" * 64,
        "baselineDatasetSha256": "d" * 64,
        "currentTotal": current,
        "baselineTotal": baseline,
        "change": current - baseline,
        "changeRate": (current - baseline) / abs(baseline) * 100 if baseline else None,
        "formula": "(currentTotal-baselineTotal)/abs(baselineTotal)*100%",
        "unit": "万元",
        "periodGranularity": "month",
        "periodStart": "2025-01-01",
        "periodEnd": "2025-01-01",
        "baselinePeriodStart": baseline_month,
        "baselinePeriodEnd": baseline_month,
    }
    return {
        "analysisId": "analysis_001",
        "metrics": [current_metric, baseline_metric],
        "comparisons": [comparison],
    }


@pytest.mark.parametrize("kind", ["yoy", "mom"])
@pytest.mark.parametrize(
    "selector,operation,unit",
    [("change", "difference", "万元"), ("changeRate", "relative_change", "%")],
)
def test_registered_comparison_catalog_expands_complete_recomputable_fragment(
    kind, selector, operation, unit
):
    from smart_reporting.reporting.trace.assertions import assertion_catalog
    from smart_reporting.reporting.trace.semantic_bindings import resolve_number_reference

    source = json.dumps(comparison_document(kind=kind), ensure_ascii=False)
    selected_token = token("c", selector=selector, unit=unit)
    records = assertion_catalog(
        [source],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
        allowed_tokens=[selected_token],
    )
    (result,) = records.values()
    assert result.status == "supported", result.reasons
    assert result.request.operation == operation
    assert result.periods == ("2025-01",)
    assert result.baseline_periods == (("2024-01",) if kind == "yoy" else ("2024-12",))
    assert result.value == ("-60.0" if selector == "change" else "-30.0")
    fragment = result.factual_fragment()
    assert all(
        label in fragment for label in ("本期", "基期", "2025-01", "2024-", "北院", "实际支出")
    )
    text, references, notices = render_bound_numbers(
        "{{assert:" + result.assertion_id + "}}", [source], key="comparison", assertions=records
    )
    assert len(references) == 1 and not notices
    assert references[0].token == selected_token
    assert resolve_number_reference(references[0].token, [source])["value"] == float(result.value)
    assert "assert-" not in text


@pytest.mark.parametrize(
    "fault",
    [
        "missing_inputs",
        "wrong_source",
        "wrong_scope",
        "wrong_profile",
        "wrong_amount",
        "wrong_window",
        "wrong_role",
        "warning",
    ],
)
def test_registered_comparison_never_self_signs_a_declared_relationship(fault):
    document = comparison_document()
    comparison = document["comparisons"][0]
    if fault == "missing_inputs":
        document["metrics"].pop()
    elif fault == "wrong_source":
        comparison["baselineDatasetSha256"] = "e" * 64
    elif fault == "wrong_scope":
        document["metrics"][1]["scope"] = {"院区": "南院"}
    elif fault == "wrong_profile":
        document["metrics"][1]["profileHash"] = "f" * 64
    elif fault == "wrong_amount":
        comparison["changeRate"] = 20
    elif fault == "wrong_window":
        comparison["baselinePeriodStart"] = comparison["baselinePeriodEnd"] = "2023-01-01"
    elif fault == "wrong_role":
        document["metrics"][1]["periodRoles"] = ["current"]
    else:
        document["metrics"][1]["warnings"] = ["尚未消除的质量缺口"]
    result = compiler([json.dumps(document)]).compile(
        AssertionRequest(
            operation="relative_change",
            operands=(token("c", selector="changeRate", unit="%"),),
            comparison="yoy",
        )
    )
    assert result.status == "unknown", result
    assert result.value is None and result.reference_token is None


@pytest.mark.parametrize("baseline", [0, -200])
def test_registered_relative_change_keeps_nonpositive_baseline_unknown(baseline):
    source = json.dumps(comparison_document(baseline=baseline))
    result = compiler([source]).compile(
        AssertionRequest(
            operation="relative_change",
            operands=(token("c", selector="changeRate", unit="%"),),
            comparison="yoy",
        )
    )
    assert result.status == "unknown" and result.value is None


@pytest.mark.parametrize("period", ["not-a-date", "20xx-01", "2025-01-15"])
def test_bad_month_labels_never_crash_monthly_average_evaluation(period):
    document = json.loads(facts(scope={"院区": "北院"}))
    document["metrics"][0]["periodValues"][0]["period"] = period
    caps = {"fact-" + "a" * 16: MetricCapability(metricKind="flow", monthlyFlowComplete=True)}
    result = compiler([json.dumps(document)], caps).compile(
        AssertionRequest(operation="monthly_average", operands=(token(selector="monthlyAverage"),))
    )
    assert result.status == "unknown"


def test_registered_multi_month_comparison_does_not_infer_time_additivity():
    document = comparison_document()
    for year, metric in zip((2025, 2024), document["metrics"], strict=True):
        metric["periodValues"] = [
            {"period": f"{year}-01-01", "value": metric["total"] / 2},
            {"period": f"{year}-02-01", "value": metric["total"] / 2},
        ]
    document["comparisons"][0].update(periodEnd="2025-02-01", baselinePeriodEnd="2024-02-01")
    result = compiler([json.dumps(document)]).compile(
        AssertionRequest(
            operation="relative_change",
            operands=(token("c", selector="changeRate", unit="%"),),
            comparison="yoy",
        )
    )
    assert result.status == "unknown" and "time_additivity_unproven" in result.reasons


@pytest.mark.parametrize("missing", [None, 1])
def test_registered_comparison_requires_observed_period_completeness(missing):
    document = comparison_document()
    document["metrics"][1]["periodMissingCount"] = missing
    result = compiler([json.dumps(document)]).compile(
        AssertionRequest(
            operation="relative_change",
            operands=(token("c", selector="changeRate", unit="%"),),
            comparison="yoy",
        )
    )
    assert result.status == "unknown" and "comparison_completeness_unproven" in result.reasons


def test_registered_proof_hash_includes_separately_stored_input_sources():
    document = comparison_document()
    contents = [
        json.dumps(
            {"analysisId": "analysis_001", "metrics": [], "comparisons": document["comparisons"]}
        )
    ]
    contents.extend(
        json.dumps({"analysisId": "analysis_001", "metrics": [metric]})
        for metric in document["metrics"]
    )
    request = AssertionRequest(
        operation="difference", operands=(token("c", selector="change"),), comparison="yoy"
    )
    before = compiler(contents).compile(request)
    assert before.status == "supported" and len(before.source_hashes) == 3
    changed = [
        *contents[:2],
        contents[2].replace(
            '"displayName": "\\u5b9e\\u9645\\u652f\\u51fa"', '"displayName": "base"'
        ),
    ]
    # A harmless byte change in the dependent file still changes the proof identity.
    changed[2] += " "
    after = compiler(changed).compile(request)
    assert after.status == "supported" and after.assertion_id != before.assertion_id


def test_neutral_difference_cannot_borrow_an_unrelated_value_reference():
    source = json.dumps(comparison_document(current=60, baseline=120))
    text, refs, notices = render_bound_numbers("差额为" + token() + "。", [source], key="unrelated")
    assert not refs and notices and "待核实" in text
    _, refs, _ = render_bound_numbers(
        "差额为" + token("c", selector="change") + "。", [source], key="exact"
    )
    assert len(refs) == 1


@pytest.mark.parametrize(
    "selector,unit,value",
    [("periodChanges.1", "万元", "-60.0"), ("periodChangeRates.1", "%", "-30.0")],
)
def test_registered_adjacent_month_change_uses_exact_same_fact(selector, unit, value):
    from smart_reporting.reporting.trace.assertions import assertion_catalog

    metric = comparison_document(current=200)["metrics"][0]
    metric["periodValues"].append({"period": "2025-02-01", "value": 140})
    metric["total"] = 340
    source = json.dumps({"analysisId": "analysis_001", "metrics": [metric]})
    records = assertion_catalog(
        [source],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
        allowed_tokens=[token(selector=selector, unit=unit)],
    )
    (result,) = records.values()
    assert result.status == "supported", result.reasons
    assert (
        result.value == value
        and result.periods == ("2025-02",)
        and result.baseline_periods == ("2025-01",)
    )
    _, refs, notices = render_bound_numbers(
        "{{assert:" + result.assertion_id + "}}", [source], key="monthly", assertions=records
    )
    assert len(refs) == 1 and not notices


def test_catalog_collapses_unit_variants_without_exposing_unrequested_facts():
    from smart_reporting.reporting.trace.assertions import assertion_catalog

    source = json.dumps(comparison_document())
    records = assertion_catalog(
        [source],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
        allowed_tokens=[
            token("c", selector="change", unit=unit) for unit in ("元", "万元", "亿元")
        ],
    )
    (result,) = records.values()
    assert result.reference_token == token("c", selector="change")
    assert result.request.operation == "difference"


def test_large_registered_totals_cannot_hide_a_changed_amount_with_relative_tolerance():
    document = comparison_document(current=1e12, baseline=2e12)
    document["comparisons"][0]["currentTotal"] += 0.5
    result = compiler([json.dumps(document)]).compile(
        AssertionRequest(
            operation="difference", operands=(token("c", selector="change"),), comparison="yoy"
        )
    )
    assert result.status == "unknown" and "comparison_value_mismatch" in result.reasons


def test_monthly_change_catalog_stays_inside_selected_block_facts():
    from smart_reporting.reporting.trace.assertions import assertion_catalog

    first = comparison_document(current=200)["metrics"][0]
    first["periodValues"].append({"period": "2025-02-01", "value": 140})
    first["total"] = 340
    second = {**first, "factId": "fact-" + "b" * 16, "field": "other", "scope": {"院区": "南院"}}
    source = json.dumps({"analysisId": "analysis_001", "metrics": [first, second]})
    records = assertion_catalog(
        [source],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
        allowed_tokens=[token()],
        include_month_changes=True,
    )
    assert any(
        result.request.operation == "difference" and result.status == "supported"
        for result in records.values()
    )
    assert all("fact-" + "b" * 16 not in result.request.operands[0] for result in records.values())


def test_registered_percentage_difference_keeps_percentage_point_unit():
    document = comparison_document(current=60, baseline=80)
    document["comparisons"][0]["unit"] = "%"
    for metric in document["metrics"]:
        metric.update(unit="%", aggregation="average")
    source = json.dumps(document)
    selected = token("c", selector="change", unit="%")
    result = compiler([source]).compile(
        AssertionRequest(operation="difference", operands=(selected,), comparison="yoy")
    )
    assert result.status == "supported" and result.unit == "个百分点"
    text, refs, notices = render_bound_numbers(
        "{{assert:" + result.assertion_id + "}}",
        [source],
        key="points",
        assertions={result.assertion_id: result},
    )
    assert "个百分点" in text and len(refs) == 1 and not notices


@pytest.mark.parametrize(
    ("selector", "value", "periods"),
    [("currentTotal", "70.0", ("2025-01",)), ("baselineTotal", "100.0", ("2024-01",))],
)
def test_registered_comparison_side_totals_are_value_proofs(selector, value, periods):
    from smart_reporting.reporting.trace.assertions import assertion_request_for_token

    source = json.dumps(comparison_document(current=70, baseline=100), ensure_ascii=False)
    selected = token("c", selector=selector)
    built = compiler([source])
    request = assertion_request_for_token(selected, built.resolver)
    assert request is not None and request.operation == "value"
    result = built.compile(request)
    assert result.status == "supported", result.reasons
    assert result.value == value and result.periods == periods


def test_comparison_side_total_keeps_input_identity_check():
    from smart_reporting.reporting.trace.assertions import assertion_request_for_token

    document = comparison_document(current=70, baseline=100)
    document["comparisons"][0]["baselineDatasetSha256"] = "e" * 64
    built = compiler([json.dumps(document, ensure_ascii=False)])
    selected = token("c", selector="currentTotal")
    result = built.compile(assertion_request_for_token(selected, built.resolver))
    assert result.status != "supported" and result.value is None

