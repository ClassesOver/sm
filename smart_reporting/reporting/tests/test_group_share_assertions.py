"""Composition proofs use frozen row partitions and an explicit population scope."""

import hashlib
import json
from decimal import Decimal

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
from smart_reporting.reporting.trace.semantic_bindings import (
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.workflow.runtime.sections import _controlled_assertions


def group_bundle(*, stock=False, groups=2, collision=False, weights=None):
    if weights is not None:
        values = tuple((f"科室{index:02d}", value) for index, value in enumerate(weights))
    elif groups == 2:
        values = (("内科", 60), ("外科", 40))
    else:
        values = tuple((f"科室{index:02d}", index + 1) for index in range(groups))
    rows = [
        f"2025-{month:02d},北院,{department},{value}"
        for month in (1, 2)
        for department, value in values
    ]
    # The denominator is the filtered north-campus population, never the entire CSV.
    rows.append("2025-01,南院,内科,9000")
    fields = ("month", "campus", "department", "amount")
    plan = analysis()
    if collision:
        fields = ("month", "campus", "department", "ward", "amount")
        raw = (
            "month,campus,department,ward,amount\n"
            + "".join(
                f"2025-{month:02d},北院,{department},{ward},{value}\n"
                for month in (1, 2)
                for department, ward, value in (("内 / 科", "病区", 60), ("内", "科 / 病区", 40))
            )
        ).encode()
        plan = plan.model_copy(update={"organization_grain": ("department", "ward")})
    else:
        raw = ("month,campus,department,amount\n" + "\n".join(rows) + "\n").encode()
    declaration = {
        **semantic("amount", scope={"campus": "北院"}, unit="元"),
        "additiveAcross": ["department"] if stock else ["month", "department"],
    }
    ctx = context(
        "current",
        fields=fields,
        semantics=(declaration,),
        sha256=hashlib.sha256(raw).hexdigest(),
    ).model_copy(update={"period_granularities": {"month": "month"}})
    return build_deterministic_analysis_bundle(
        plan,
        (("current", raw, ctx, ("current",)),),
        profile_hash="a" * 64,
        profile_metrics=(
            {
                "code": "income",
                "description": "收入",
                "kind": "amount",
                "fieldRef": declaration["fieldRef"],
                "aggregation": "sum",
            },
        ),
    )


def share_token(fact_id, *, array="topGroups", index=0):
    return f"{{{{value:{fact_id}:groupShares.{array}.{index}:%}}}}"


def compile_share(document):
    source = json.dumps(document, ensure_ascii=False)
    token = share_token(document["metrics"][0]["factId"])
    compiler = AssertionCompiler([source], profile_hash="a" * 64, authorization_scope_hash="b" * 64)
    return compiler.compile(AssertionRequest(operation="share", operands=(token,))), source, token


@pytest.mark.parametrize("stock,periods", [(False, ("2025-01", "2025-02")), (True, ("2025-02",))])
def test_group_share_has_same_fact_denominator_and_explicit_population_scope(stock, periods):
    bundle = group_bundle(stock=stock)
    result, source, token = compile_share(json.loads(bundle.model_dump_json(by_alias=True)))
    assert result.status == "supported", result.reasons
    assert result.value == "60.0" and result.unit == "%"
    assert result.population_fact_id == bundle.metrics[0].fact_id
    assert result.population_scope == {"campus": "北院"}
    assert result.scope["department"] == "内科" and result.periods == periods
    assert result.subject == "收入"
    text, references, notices = render_bound_numbers(
        "{{assert:" + result.assertion_id + "}}",
        [source],
        key="share",
        assertions={result.assertion_id: result},
    )
    assert all(word in text for word in ("分组范围", "内科", "总体范围", "北院", "收入登记合计"))
    assert "全院" not in text and "南院" not in text
    assert len(references) == 1 and not notices and references[0].token == token
    assert resolve_number_reference(token, [source])["value"] == 60


@pytest.mark.parametrize(
    "fault",
    [
        "no_population",
        "legacy_label",
        "null_group",
        "scope_conflict",
        "profile",
        "warning",
        "missing_values",
        "missing_period",
        "unknown_time",
        "period_gap",
        "negative",
        "zero_total",
        "too_large",
        "rate_unit",
        "compound_unit",
        "average",
        "duplicate",
        "conflicting_overlap",
        "mixed_grain",
    ],
)
def test_invalid_membership_or_population_is_unknown_without_factual_value(fault):
    document = json.loads(group_bundle().model_dump_json(by_alias=True))
    metric = document["metrics"][0]
    selected = metric["topGroups"][0]
    if fault == "no_population":
        metric["scope"] = {}
    elif fault == "legacy_label":
        selected.pop("groupValues")
    elif fault == "null_group":
        selected["groupValues"]["department"] = None
    elif fault == "scope_conflict":
        selected["groupValues"]["campus"] = "南院"
    elif fault == "profile":
        metric["profileHash"] = "c" * 64
    elif fault == "warning":
        metric["warnings"] = ["总体完整性待确认"]
    elif fault == "missing_values":
        metric["missingCount"] = 1
    elif fault == "missing_period":
        metric.pop("periodMissingCount")
    elif fault == "unknown_time":
        metric.pop("periodAggregation")
    elif fault == "period_gap":
        metric["periodValues"][1]["period"] = "2025-03-01"
    elif fault == "negative":
        metric["negativeCount"] = 1
    elif fault == "zero_total":
        metric["total"] = 0
    elif fault == "too_large":
        selected["value"] = metric["total"] + 1
    elif fault == "rate_unit":
        metric["unit"] = "%"
    elif fault == "compound_unit":
        metric["unit"] = "元/人次"
    elif fault == "average":
        metric["aggregation"] = "average"
    elif fault == "duplicate":
        metric["topGroups"].append(dict(selected))
    elif fault == "conflicting_overlap":
        other = next(
            item
            for item in metric["bottomGroups"]
            if item["groupValues"] == selected["groupValues"]
        )
        other["value"] += 1
    elif fault == "mixed_grain":
        metric["bottomGroups"][0]["groupValues"]["ward"] = "一病区"
    result, _, _ = compile_share(document)
    assert result.status == "unknown", result
    assert result.value is None and result.reference_token is None
    assert result.population_scope is None and result.population_fact_id is None


@pytest.mark.parametrize("groups,expected", [(2, 2), (30, 20)])
def test_catalog_deduplicates_top_bottom_overlap_without_renormalizing_top_k(groups, expected):
    bundle = group_bundle(groups=groups)
    source = bundle.model_dump_json(by_alias=True)
    parent = f"{{{{value:{bundle.metrics[0].fact_id}:total:元}}}}"
    records = assertion_catalog(
        [source],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
        allowed_tokens=[parent],
        include_group_shares=True,
    )
    shares = [result for result in records.values() if result.request.operation == "share"]
    assert len(shares) == expected and all(result.status == "supported" for result in shares)
    if groups == 30:
        top = max(Decimal(result.value) for result in shares)
        assert float(top) == pytest.approx(30 / sum(range(1, 31)) * 100)
        assert sum(Decimal(result.value) for result in shares) < 100


def test_display_name_total_does_not_supply_cross_metric_population_membership():
    from smart_reporting.reporting.tests.test_numeric_text import _share_document

    # The old numerical catalog may offer a ratio, but no group partition or
    # trusted population relation follows from its denominator display name.
    document = _share_document()
    source = json.dumps(document)
    token = "{{value:fact-aaaaaaaaaaaaaaaa:metricShare.fact-bbbbbbbbbbbbbbbb:%}}"
    result = AssertionCompiler(
        [source], profile_hash="a" * 64, authorization_scope_hash="b" * 64
    ).compile(AssertionRequest(operation="share", operands=(token,)))
    assert result.status == "unknown" and result.value is None


def test_generation_refuses_missing_or_unregistered_fact_provenance():
    bundle = group_bundle()
    source = bundle.model_dump_json(by_alias=True)
    policy = {"mode": "enabled", "profileHash": "a" * 64, "authorizationScopeHash": "b" * 64}
    token = f"{{{{value:{bundle.metrics[0].fact_id}:total:元}}}}"
    payload = {"frozenNumbers": {token: "200元"}}
    assert _controlled_assertions([source], payload, policy) == {}
    assert payload["assertionUnavailable"] == "trusted_facts_unavailable"
    payload = {"frozenNumbers": {token: "200元"}}
    assert (
        _controlled_assertions([source], payload, {**policy, "trustedFactSha256": ["0" * 64]}) == {}
    )
    payload = {"frozenNumbers": {token: "200元"}}
    records = _controlled_assertions(
        [source],
        payload,
        {**policy, "trustedFactSha256": [hashlib.sha256(source.encode()).hexdigest()]},
    )
    assert any(
        result.request.operation == "share" and result.status == "supported"
        for result in records.values()
    )


@pytest.mark.parametrize("part", ["total", "other_group"])
def test_nonfinite_population_is_never_a_zero_percent_proof(part):
    document = json.loads(group_bundle().model_dump_json(by_alias=True))
    if part == "total":
        document["metrics"][0]["total"] = float("inf")
    else:
        document["metrics"][0]["bottomGroups"][0]["value"] = float("nan")
    result, _, _ = compile_share(document)
    assert result.status == "unknown" and result.value is None


def test_only_server_registered_bytes_can_supply_a_new_group_identity():
    bundle = group_bundle()
    source = bundle.model_dump_json(by_alias=True)
    forged = json.loads(source)
    forged["metrics"][0]["factId"] = "fact-" + "f" * 16
    forged["metrics"][0]["topGroups"][0]["groupValues"]["department"] = "伪造组"
    forged_source = json.dumps(forged, ensure_ascii=False)
    payload = {
        "frozenNumbers": {
            f"{{{{value:{bundle.metrics[0].fact_id}:total:元}}}}": "200元",
            "{{value:fact-ffffffffffffffff:total:元}}": "200元",
        }
    }
    policy = {
        "mode": "enabled",
        "profileHash": "a" * 64,
        "authorizationScopeHash": "b" * 64,
        "trustedFactSha256": [hashlib.sha256(source.encode()).hexdigest()],
    }
    records = _controlled_assertions([source, forged_source], payload, policy)
    assert records
    assert all(
        "fact-ffffffffffffffff" not in result.request.operands[0] for result in records.values()
    )
    assert "伪造组" not in json.dumps(payload["assertionCatalog"], ensure_ascii=False)


def test_composition_share_cannot_use_a_different_period_population():
    from smart_reporting.reporting.tests.test_assertion_compiler import comparison_document
    from smart_reporting.reporting.trace.assertions import MetricCapability

    document = comparison_document()
    # Even trusted population IDs do not make a previous-year total the
    # population of a current-year constituent.
    ids = [metric["factId"] for metric in document["metrics"]]
    compiler = AssertionCompiler(
        [json.dumps(document)],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
        capabilities={
            key: MetricCapability(
                comparisonKey="definition", populationId="population", denominatorFactId=ids[1]
            )
            for key in ids
        },
    )
    result = compiler.compile(
        AssertionRequest(
            operation="share",
            comparison="yoy",
            operands=tuple(f"{{{{value:{key}:total:万元}}}}" for key in ids),
        )
    )
    assert result.status == "unknown" and "population_period_mismatch" in result.reasons


def test_colliding_display_labels_keep_structured_group_identity_in_the_proof():
    from smart_reporting.reporting.trace.semantic_bindings import anchor_bound_numbers
    from smart_reporting.reporting.trace.subject_builder import claim_status

    bundle = group_bundle(collision=True)
    result, source, token = compile_share(json.loads(bundle.model_dump_json(by_alias=True)))
    assert result.status == "supported" and result.numerator_scope == {
        "department": "内 / 科",
        "ward": "病区",
    }
    text, refs, notices = render_bound_numbers(
        "{{assert:" + result.assertion_id + "}}",
        [source],
        key="collision",
        assertions={result.assertion_id: result},
    )
    selected = resolve_number_reference(token, [source])
    assert selected["scope"] == {"campus": "北院", "department": "内 / 科", "ward": "病区"}
    assert "group=" not in text and "department=内 / 科" in text and "ward=病区" in text
    markdown = anchor_bound_numbers(text, refs, notices)
    detail = claim_status(
        markdown,
        refs[0].claim_id,
        selected["value"],
        expected_unit=selected["unit"],
        expected_scope=selected["scope"],
        expected_periods=selected["periods"],
    )
    assert detail["status"] == "valid" and not detail["warnings"]
