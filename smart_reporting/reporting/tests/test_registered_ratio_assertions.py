"""Frozen ratio dependencies prove a ratio of totals, not an average or subset."""

import hashlib
import json
from decimal import Decimal

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.assertions import (
    AssertionCompiler,
    AssertionRequest,
    assertion_catalog,
)
from smart_reporting.reporting.trace.numeric_text import (
    frozen_number_catalog,
    prompt_number_catalog,
)
from smart_reporting.reporting.trace.ratio_proofs import registered_ratio
from smart_reporting.reporting.trace.reference_semantics import number_reference_warnings
from smart_reporting.reporting.trace.semantic_bindings import (
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.workflow.runtime.sections import _controlled_assertions

from .test_deterministic_analysis import analysis, context, semantic


def ratio_document(
    *,
    grain="month",
    numerator=(100, 900),
    denominator=(10, 30),
    num_unit="元",
    den_unit="人次",
    stock=False,
    expected_derived_count=1,
):
    periods = (
        ("2025-01", "2025-02")
        if grain == "month"
        else ("2025-01-01", "2025-01-02")
        if grain == "day"
        else ("2024", "2025")
    )
    raw = (
        f"{grain},department,amount,visits\n"
        + "".join(
            f"{period},A,{num},{den}\n"
            for period, num, den in zip(periods, numerator, denominator, strict=True)
        )
    ).encode()
    declarations = tuple(
        {
            **semantic(field, scope={"department": "A"}, unit=unit),
            "additiveAcross": ["department"] if stock else [grain, "department"],
        }
        for field, unit in (("amount", num_unit), ("visits", den_unit))
    )
    ctx = context(
        "current",
        fields=(grain, "department", "amount", "visits"),
        semantics=declarations,
        sha256=hashlib.sha256(raw).hexdigest(),
    ).model_copy(
        update={
            "time_series_sort_field": grain,
            "period_granularities": {grain: "date" if grain == "day" else grain},
        }
    )
    definitions = tuple(
        {
            "code": code,
            "kind": "amount" if unit in {"元", "万元", "亿元"} else "count",
            "aggregation": "sum",
            "fieldRef": declaration["fieldRef"],
        }
        for code, unit, declaration in zip(
            ("num", "den"), (num_unit, den_unit), declarations, strict=True
        )
    ) + (
        {
            "code": "registered_ratio",
            "kind": "ratio",
            "aggregation": "ratio",
            "numeratorMetric": "num",
            "denominatorMetric": "den",
        },
    )
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("amount", "visits")).model_copy(update={"series_granularity": grain}),
        (("current", raw, ctx, ("current",)),),
        profile_metrics=definitions,
        profile_hash="a" * 64,
    )
    assert len(bundle.derived_metrics) == expected_derived_count, bundle.warnings
    return json.loads(bundle.model_dump_json(by_alias=True))


def compile_ratio(doc, unit="元/人次"):
    source = json.dumps(doc, ensure_ascii=False)
    token = f"{{{{value:{doc['derivedMetrics'][0]['factId']}:registeredRatio:{unit}}}}}"
    result = AssertionCompiler(
        [source], profile_hash="a" * 64, authorization_scope_hash="b" * 64
    ).compile(AssertionRequest(operation="registered_ratio", operands=(token,)))
    return result, source, token


@pytest.mark.parametrize("grain", ["day", "month", "year"])
@pytest.mark.parametrize("stock", [False, True])
def test_registered_ratio_uses_joint_window_and_explicit_time_aggregation(grain, stock):
    result, source, token = compile_ratio(ratio_document(grain=grain, stock=stock))
    assert result.status == "supported", result.reasons
    assert Decimal(result.value) == (30 if stock else 25)
    assert result.unit == "元/人次"
    assert (
        "共同期末" in result.factual_fragment()
        if stock
        else "同期分子总量" in result.factual_fragment()
    )
    assert "不是各期比率的平均" in result.factual_fragment()
    selected = resolve_number_reference(token, [source])
    assert not number_reference_warnings(
        result.factual_fragment().split(result.value + result.unit, 1)[0], selected
    )
    assert "/" in selected["formula"] and result.unit in selected["formula"]


def test_sum_ratio_is_not_the_unweighted_average_of_period_ratios():
    result, _, _ = compile_ratio(ratio_document())
    assert result.status == "supported"
    assert Decimal(result.value) == 25
    assert Decimal(result.value) != (Decimal(100) / 10 + Decimal(900) / 30) / 2


@pytest.mark.parametrize('numerator,denominator,num_unit,den_unit', [
    (1e200, 1e-200, '元', '元'),
    (1e200, 1e-200, '元', '人次'),
    (1e307, 1, '元', '元'),
    (1, 1e307, '元', '万元'),
    (-8e307, 8e307, '元', '元'),
    (1e-200, 1e200, '元', '元'),
    (1e-200, 1e200, '元', '人次'),
    (1, 5e-324, '亿元', '元'),
])
def test_unrepresentable_ratio_preserves_its_finite_primitive_facts(
    numerator, denominator, num_unit, den_unit,
):
    document = ratio_document(numerator=(numerator, numerator), denominator=(denominator, denominator),
                              num_unit=num_unit, den_unit=den_unit, expected_derived_count=0)
    assert len(document['metrics']) == 2
    assert {fact['field'] for fact in document['metrics']} == {'amount', 'visits'}
    assert all(not fact['warnings'] for fact in document['metrics'])
    assert any('溢出或下溢' in warning for warning in document['warnings'])


def test_legacy_nonzero_percent_underflow_cannot_acquire_a_zero_proof():
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicAnalysisBundle,
    )
    from smart_reporting.reporting.trace.fact_index import assign_fact_ids

    document = ratio_document(numerator=(1e-200, 1e-200), denominator=(1e200, 1e200),
                              den_unit='元', expected_derived_count=0)
    legacy = ratio_document(den_unit='元')['derivedMetrics'][0]
    legacy.update(numerator=2e-200, denominator=2e200, value=0.0, percentage=0.0, difference=-2e200,
                  datasetSha256s=[document['metrics'][0]['datasetSha256']], inputFactIds=[])
    document['derivedMetrics'] = [legacy]
    document['warnings'] = []
    document = json.loads(assign_fact_ids(DeterministicAnalysisBundle.model_validate(document)).model_dump_json(by_alias=True))
    entry = document['derivedMetrics'][0]
    entries = {fact['factId']: fact for fact in document['metrics']}
    proof, reasons = registered_ratio(entry, entries, profile_hash='a' * 64, fact_warnings={})
    assert proof is None and 'ratio_quotient_out_of_range' in reasons
    result, source, token = compile_ratio(document, '%')
    assert result.status == 'unknown' and result.value is None
    assert token not in frozen_number_catalog([source])


@pytest.mark.parametrize(
    "num_unit,den_unit,expected",
    [("万元", "人次", 250000), ("元", "万人次", Decimal("0.0025")), ("万元", "万人次", 25)],
)
def test_compound_quotient_applies_both_confirmed_unit_scales(num_unit, den_unit, expected):
    result, _, _ = compile_ratio(ratio_document(num_unit=num_unit, den_unit=den_unit))
    assert result.status == "supported", result.reasons
    assert Decimal(result.value) == expected and result.unit == "元/人次"


@pytest.mark.parametrize(
    "numerator,denominator,expected", [((10, 90), (10, 30), 250), ((0, 0), (10, 30), 0)]
)
def test_same_dimension_percent_is_arithmetic_even_when_above_one_hundred(
    numerator, denominator, expected
):
    doc = ratio_document(numerator=numerator, denominator=denominator, den_unit="元")
    result, source, token = compile_ratio(doc, "%")
    assert result.status == "supported", result.reasons
    assert Decimal(result.value) == expected
    assert "不表示总体隶属关系" in result.factual_fragment()
    assert not number_reference_warnings(
        result.factual_fragment().split(result.value + "%", 1)[0],
        resolve_number_reference(token, [source]),
    )


def test_actual_numeric_render_and_catalog_are_bounded_to_registered_source_units():
    result, source, token = compile_ratio(ratio_document(num_unit="万元"))
    text, refs, notices = render_bound_numbers(
        "{{assert:" + result.assertion_id + "}}",
        [source],
        key="ratio",
        assertions={result.assertion_id: result},
    )
    assert not notices and len(refs) == 1, text
    assert "250,000元/人次" in text
    assert refs[0].token == token
    assert not number_reference_warnings(
        text.split(refs[0].display_text, 1)[0], resolve_number_reference(token, [source])
    )
    catalog = frozen_number_catalog([source])
    assert token in catalog and token not in prompt_number_catalog(catalog)
    assert token.replace("元/人次", "%") not in catalog


@pytest.mark.parametrize(
    "fault",
    [
        "missing_input",
        "swap_inputs",
        "codes",
        "profile",
        "source",
        "scope",
        "empty_scope",
        "period_role",
        "missing_series",
        "parse_error",
        "missing_period",
        "warning",
        "stored_value",
        "stored_numerator",
        "stored_denominator",
        "scale",
        "period",
        "grain",
        "time_policy",
        "weighted_average",
        "compound_input",
        "unknown_unit",
        "rate_input",
        "nonfinite",
        "count_distinct",
    ],
)
def test_unproven_ratio_keeps_ordinary_facts_but_never_mints_a_ratio_assertion(fault):
    doc = ratio_document()
    ratio = doc["derivedMetrics"][0]
    first, second = doc["metrics"]
    if fault == "missing_input":
        ratio["inputFactIds"].pop()
    elif fault == "swap_inputs":
        ratio["inputFactIds"].reverse()
    elif fault == "codes":
        first["metricCodes"] = ["other"]
    elif fault == "profile":
        first["profileHash"] = "c" * 64
    elif fault == "source":
        ratio["datasetSha256s"] = ["c" * 64]
    elif fault == "scope":
        second["scope"] = {"department": "B"}
    elif fault == "empty_scope":
        for item in (ratio, first, second):
            item["scope"] = {}
    elif fault == "period_role":
        second["periodRoles"] = ["yoy"]
    elif fault == "missing_series":
        first.pop("seriesMissingCount")
    elif fault == "parse_error":
        first["seriesMissingCount"] = 1
    elif fault == "missing_period":
        first["periodMissingCount"] = 1
    elif fault == "warning":
        second["warnings"] = ["口径待核实"]
    elif fault == "stored_value":
        ratio["value"] += 1
    elif fault == "stored_numerator":
        ratio["numerator"] += 1
    elif fault == "stored_denominator":
        ratio["denominator"] += 1
    elif fault == "scale":
        ratio["denominatorScale"] = 10000
    elif fault == "period":
        ratio["periodStart"] = ratio["periodEnd"]
    elif fault == "grain":
        second["periodGranularity"] = "day"
    elif fault == "time_policy":
        first["periodAggregation"] = "last"
    elif fault == "weighted_average":
        first["aggregation"] = "average"
    elif fault == "compound_input":
        second["unit"] = "人次/床"
    elif fault == "unknown_unit":
        first["unit"] = "评分"
    elif fault == "rate_input":
        second["unit"] = "%"
    elif fault == "nonfinite":
        first["periodValues"][0]["value"] = float("inf")
    elif fault == "count_distinct":
        second["aggregation"] = "count_distinct"
    result, source, token = compile_ratio(doc)
    assert result.status == "unknown" and result.value is None
    catalog = frozen_number_catalog([source])
    assert token not in catalog
    ordinary = f"{{{{value:{first['factId']}:total:{first['unit']}}}}}"
    assert ordinary in catalog


@pytest.mark.parametrize(
    "numerator,denominator",
    [((100, 900), (0, 0)), ((100, 900), (-10, -30)), ((-100, -900), (10, 30))],
)
def test_zero_or_unsupported_sign_policy_does_not_claim_a_usable_ratio(numerator, denominator):
    result, _, _ = compile_ratio(ratio_document(numerator=numerator, denominator=denominator))
    assert result.status == "unknown" and result.value is None


@pytest.mark.parametrize(
    "old,new",
    [
        ("分子（amount）", "分子（visits）"),
        ("分母（visits）", "分母（amount）"),
        ("同期分子总量除以同期分母总量", "各期比率求平均"),
        ("2025-01至2025-02", "2025-02至2025-02"),
    ],
)
def test_unchanged_result_cannot_hide_changed_operands_or_aggregation_wording(old, new):
    result, source, token = compile_ratio(ratio_document())
    prefix = result.factual_fragment().split(result.value + result.unit, 1)[0]
    changed = prefix.replace(old, new)
    assert changed != prefix
    assert number_reference_warnings(changed, resolve_number_reference(token, [source]))


@pytest.mark.parametrize(
    "extra",
    [
        "占比为",
        "平均比率为",
        "同比增长率为",
        "政策驱动提升，",
        "预计未来增加，",
        "全年累计比率为",
        "月均比率为",
        "完成率为",
    ],
)
def test_extra_business_claim_cannot_borrow_a_ratio_of_totals_proof(extra):
    result, source, token = compile_ratio(ratio_document())
    prefix = result.factual_fragment().split(result.value + result.unit, 1)[0]
    assert number_reference_warnings(extra + prefix, resolve_number_reference(token, [source]))


def test_generation_requires_trusted_and_allocated_ratio_fact_not_just_its_inputs():
    result, source, _ = compile_ratio(ratio_document())
    doc = json.loads(source)
    allocated = f"{{{{value:{doc['derivedMetrics'][0]['factId']}:value:}}}}"
    policy = dict(
        mode="enabled",
        profileHash="a" * 64,
        authorizationScopeHash="b" * 64,
        trustedFactSha256=[hashlib.sha256(source.encode()).hexdigest()],
    )
    payload = {"frozenNumbers": {allocated: "25"}}
    assert result.assertion_id in _controlled_assertions([source], payload, policy)
    assert not _controlled_assertions([source], payload, {**policy, "mode": "shadow"})
    records = assertion_catalog(
        [source],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
        allowed_tokens=[f"{{{{value:{doc['metrics'][0]['factId']}:total:元}}}}"],
        include_registered_ratios=True,
    )
    assert not any(item.request.operation == "registered_ratio" for item in records.values())


def test_warning_variant_from_another_analysis_cannot_reuse_clean_ratio_proof():
    doc = ratio_document()
    result, source, token = compile_ratio(doc)
    assert result.status == "supported"
    doc["metrics"][1]["warnings"] = ["口径待核实"]
    compiler = AssertionCompiler(
        [source, json.dumps(doc)], profile_hash="a" * 64, authorization_scope_hash="b" * 64
    )
    assert (
        compiler.compile(AssertionRequest(operation="registered_ratio", operands=(token,))).status
        == "unknown"
    )


def test_proof_uses_frozen_primitive_inputs_not_a_kind_or_formula_hint():
    doc = ratio_document()
    doc["derivedMetrics"][0]["inputFactIds"] = []
    doc["derivedMetrics"][0]["formula"] = "已验证：amount/visits"
    proof, reasons = registered_ratio(
        doc["derivedMetrics"][0],
        {m["factId"]: m for m in doc["metrics"]},
        profile_hash="a" * 64,
        fact_warnings={},
    )
    assert proof is None and reasons


@pytest.mark.parametrize(
    "num_unit,den_unit,numerator,denominator",
    [
        ("万元", "元", (1, 9), (10000, 30000)),
        ("元", "万元", (10000, 90000), (1, 3)),
    ],
)
def test_same_dimension_percentage_applies_registered_denominator_conversion(
    num_unit, den_unit, numerator, denominator
):
    result, source, token = compile_ratio(
        ratio_document(
            num_unit=num_unit, den_unit=den_unit, numerator=numerator, denominator=denominator
        ),
        "%",
    )
    assert result.status == "supported", result.reasons
    assert Decimal(result.value) == 250
    assert not number_reference_warnings(
        result.factual_fragment().split(result.value + "%", 1)[0],
        resolve_number_reference(token, [source]),
    )


@pytest.mark.parametrize(
    "qualifier", ["不是平均比率", "不是各期比率的平均", "不代表占比", "不能证明同比增长率"]
)
def test_explicit_limitations_do_not_masquerade_as_positive_ratio_claims(qualifier):
    result, source, token = compile_ratio(ratio_document())
    prefix = result.factual_fragment().split(result.value + result.unit, 1)[0]
    assert not number_reference_warnings(
        prefix, resolve_number_reference(token, [source]), f"（{qualifier}）"
    )


def test_unsupported_compound_unit_cannot_use_a_recognized_numerator_prefix():
    doc = ratio_document(num_unit="床", den_unit="人")
    result, source, token = compile_ratio(doc, "床/人")
    assert result.status == "unknown" and token not in frozen_number_catalog([source])


def test_extra_postfix_average_qualifier_is_rechecked_despite_an_unchanged_result():
    result, source, token = compile_ratio(ratio_document())
    prefix = result.factual_fragment().split(result.value + result.unit, 1)[0]
    assert number_reference_warnings(
        prefix, resolve_number_reference(token, [source]), "（平均比率）"
    )
