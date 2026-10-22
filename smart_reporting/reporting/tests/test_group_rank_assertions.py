"""Ranks follow frozen values, tie rules and scope, including editor changes."""

import json

import pytest

from smart_reporting.reporting.tests.test_group_share_assertions import group_bundle
from smart_reporting.reporting.trace.assertions import (
    AssertionCompiler,
    AssertionRequest,
    assertion_catalog,
)
from smart_reporting.reporting.trace.group_ranking import group_rank_wording_warnings
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.subject_builder import claim_status


def rank_document(**kwargs):
    return json.loads(group_bundle(**kwargs).model_dump_json(by_alias=True))


def compile_rank(document, *, array="topGroups", index=0, comparison="same_period"):
    source = json.dumps(document, ensure_ascii=False)
    token = f"{{{{value:{document['metrics'][0]['factId']}:{array}.{index}:元}}}}"
    compiler = AssertionCompiler([source], profile_hash="a" * 64, authorization_scope_hash="b" * 64)
    return (
        compiler.compile(
            AssertionRequest(operation="group_rank", operands=(token,), comparison=comparison)
        ),
        source,
        token,
    )


@pytest.mark.parametrize(
    "array,index,rank",
    [
        ("topGroups", 0, 1),
        ("topGroups", 1, 2),
        ("topGroups", 2, 2),
        ("topGroups", 3, 4),
        ("bottomGroups", 0, 1),
        ("bottomGroups", 1, 2),
        ("bottomGroups", 2, 2),
        ("bottomGroups", 3, 4),
    ],
)
def test_rank_uses_strictly_better_values_instead_of_position(array, index, rank):
    document = rank_document(weights=(100, 90, 90, 80))
    result, source, token = compile_rank(document, array=array, index=index)
    assert result.status == "supported", result.reasons
    assert result.rank == rank
    assert result.ranking_order == ("descending" if array == "topGroups" else "ascending")
    assert result.population_scope == {"campus": "北院"}
    assert result.numerator_scope == document["metrics"][0][array][index]["groupValues"]
    assert result.value == str(float(document["metrics"][0][array][index]["value"]))
    text, refs, notices = render_bound_numbers(
        "{{assert:" + result.assertion_id + "}}",
        [source],
        key="rank",
        assertions={result.assertion_id: result},
    )
    assert f"第{rank}名" in text and "同值同名次" in text
    assert "总体范围（campus=北院）" in text and len(refs) == 1 and not notices
    selected = resolve_number_reference(token, [source])
    assert selected["scope"] == result.scope
    markdown = anchor_bound_numbers(text, refs)
    assert claim_status(
        markdown,
        refs[0].claim_id,
        selected["value"],
        expected_unit=selected["unit"],
        expected_periods=selected["periods"],
        expected_scope=selected["scope"],
        expected_reference=selected,
    ) == {"status": "valid", "warnings": []}


def test_truncated_tie_does_not_turn_lexical_order_into_a_unique_rank():
    document = rank_document(weights=(100,) * 30)
    assert len(document["metrics"][0]["topGroups"]) == 10
    result, source, token = compile_rank(document, index=9)
    assert result.status == "supported" and result.rank == 1
    selected = resolve_number_reference(token, [source])
    assert not group_rank_wording_warnings("同值同名次，列第1名", selected)
    assert group_rank_wording_warnings("唯一第一名", selected)
    assert group_rank_wording_warnings("列第10名", selected)


def test_tie_at_the_last_retained_position_has_the_population_competition_rank():
    weights = (*range(200, 191, -1), *((100,) * 21))
    result, _, _ = compile_rank(rank_document(weights=weights), index=9)
    assert result.status == "supported"
    assert result.rank == 1 + sum(value > 100 for value in weights) == 10


def test_rank_retains_warnings_from_another_analysis_of_the_same_fact():
    document = rank_document()
    other = json.loads(json.dumps(document))
    other["analysisId"] = "analysis_002"
    other["metrics"][0]["warnings"] = ["上游来源完整性未确认"]
    source = json.dumps(document)
    token = f"{{{{value:{document['metrics'][0]['factId']}:topGroups.0:元}}}}"
    compiler = AssertionCompiler(
        [source, json.dumps(other)],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
    )
    result = compiler.compile(AssertionRequest(operation="group_rank", operands=(token,)))
    assert result.status == "unknown" and result.rank is None


@pytest.mark.parametrize("stock,periods", [(False, ("2025-01", "2025-02")), (True, ("2025-02",))])
def test_rank_retains_temporal_scope_and_structured_collision_identity(stock, periods):
    result, source, token = compile_rank(rank_document(stock=stock, collision=True))
    assert result.status == "supported" and result.periods == periods
    assert result.numerator_scope == {"department": "内 / 科", "ward": "病区"}
    assert resolve_number_reference(token, [source])["scope"] == {
        "campus": "北院",
        "department": "内 / 科",
        "ward": "病区",
    }
    assert "group=" not in result.factual_fragment()


def test_negative_group_values_still_have_a_well_defined_rank():
    result, _, _ = compile_rank(rank_document(weights=(-10, -20, -30)), index=2)
    assert result.status == "supported" and result.rank == 3 and result.value == "-60.0"


def test_equal_rounded_displays_do_not_create_a_false_tie():
    document = rank_document(weights=(100.001, 100.002))
    outputs = []
    for index in (0, 1):
        result, source, _ = compile_rank(document, index=index)
        assert result.status == "supported" and result.rank == index + 1
        text, references, notices = render_bound_numbers(
            "{{assert:" + result.assertion_id + "}}",
            [source],
            key="precision",
            assertions={result.assertion_id: result},
        )
        assert "未舍入" in text and not notices
        outputs.append(references[0].display_text)
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("unit", ["%", "个百分点", "元/人次", "元／床日"])
def test_summed_rates_or_compound_units_do_not_acquire_rank_proofs(unit):
    document = rank_document()
    document["metrics"][0]["unit"] = unit
    source = json.dumps(document)
    compiler = AssertionCompiler([source], profile_hash="a" * 64, authorization_scope_hash="b" * 64)
    token = f"{{{{value:{document['metrics'][0]['factId']}:topGroups.0:{unit}}}}}"
    result = compiler.compile(AssertionRequest(operation="group_rank", operands=(token,)))
    assert result.status == "unknown" and result.rank is None


@pytest.mark.parametrize(
    "fault",
    [
        "scope",
        "profile",
        "value_missing",
        "period_missing",
        "warning",
        "time_unknown",
        "time_gap",
        "legacy_group",
        "null_group",
        "grain",
        "duplicate",
        "order",
        "conflict",
        "prefix",
        "scope_conflict",
        "nonfinite",
    ],
)
def test_unproven_or_inconsistent_ranking_is_unknown(fault):
    document = rank_document(weights=(100, 90, 90, 80))
    metric = document["metrics"][0]
    if fault == "scope":
        metric["scope"] = {}
    elif fault == "profile":
        metric["profileHash"] = "c" * 64
    elif fault == "value_missing":
        metric["missingCount"] = 1
    elif fault == "period_missing":
        metric["periodMissingCount"] = None
    elif fault == "warning":
        metric["warnings"] = ["来源不完整"]
    elif fault == "time_unknown":
        metric["periodAggregation"] = None
    elif fault == "time_gap":
        metric["periodValues"][1]["period"] = "2025-03"
        metric["periodEnd"] = "2025-03"
    elif fault == "legacy_group":
        metric["topGroups"][0]["groupValues"] = {}
    elif fault == "null_group":
        metric["bottomGroups"][0]["groupValues"]["department"] = None
    elif fault == "grain":
        metric["bottomGroups"][0]["groupValues"]["ward"] = "A"
    elif fault == "duplicate":
        metric["topGroups"][1] = metric["topGroups"][0]
    elif fault == "order":
        metric["topGroups"].reverse()
    elif fault == "conflict":
        metric["bottomGroups"][-1]["value"] += 1
    elif fault == "prefix":
        metric["topGroups"] = metric["topGroups"][1:]
    elif fault == "scope_conflict":
        for group in metric["topGroups"] + metric["bottomGroups"]:
            group["groupValues"]["campus"] = "南院"
    elif fault == "nonfinite":
        metric["topGroups"][0]["value"] = float("inf")
    result, _, _ = compile_rank(document)
    assert result.status == "unknown" and result.value is None and result.rank is None


def test_cross_period_request_cannot_become_a_group_rank():
    result, _, _ = compile_rank(rank_document(), comparison="yoy")
    assert result.status == "unknown" and "ranking_period_mismatch" in result.reasons


@pytest.mark.parametrize(
    "text,invalid",
    [
        ("降序竞赛排名为第2名", False),
        ("排名第二名", False),
        ("并列第2位", False),
        ("第3名", True),
        ("密集排名第2名", True),
        ("升序第2名", True),
        ("最高", True),
        ("登记分组收入为180元", False),
    ],
)
def test_rank_wording_is_checked_against_the_exact_reference(text, invalid):
    result, source, token = compile_rank(rank_document(weights=(100, 90, 90, 80)), index=2)
    assert result.rank == 2
    assert (
        bool(group_rank_wording_warnings(text, resolve_number_reference(token, [source])))
        == invalid
    )


def test_rank_assertion_catalog_stays_inside_allocated_facts():
    document = rank_document()
    _, source, token = compile_rank(document)
    records = assertion_catalog(
        [source], profile_hash="a" * 64, authorization_scope_hash="b" * 64, allowed_tokens=[token]
    )
    assert len(records) == 1 and next(iter(records.values())).request.operation == "group_rank"
    assert not assertion_catalog(
        [source], profile_hash="a" * 64, authorization_scope_hash="b" * 64, allowed_tokens=[]
    )


@pytest.mark.parametrize(
    "wording", ["位居第一", "排名为第一名", "唯一第一", "位列第三", "排名第3位"]
)
def test_rank_variants_cannot_bypass_rechecking_by_dropping_the_unit(wording):
    _, source, token = compile_rank(rank_document(weights=(100, 90, 90, 80)), index=2)
    assert group_rank_wording_warnings(wording, resolve_number_reference(token, [source]))


def test_rank_qualifier_does_not_borrow_a_previous_reference_or_lose_current_clauses():
    from smart_reporting.reporting.trace.reference_semantics import number_reference_warnings

    _, source, token = compile_rank(rank_document(weights=(100, 90, 90, 80)), index=2)
    reference = resolve_number_reference(token, [source])
    assert not number_reference_warnings(
        "前项第3名，200元[[claim:previous]]及科室02收入为", reference
    )
    warnings = number_reference_warnings(
        "前项200元[[claim:previous]]及科室02排名第3名，对应登记值为", reference
    )
    assert any("竞赛排名" in warning for warning in warnings)
    warnings = number_reference_warnings("科室02收入为", reference, suffix="（排名第三名）")
    assert any("竞赛排名" in warning for warning in warnings)


def test_dimension_labels_are_not_interpreted_as_author_supplied_rank_claims():
    _, source, token = compile_rank(rank_document(), index=1)
    reference = resolve_number_reference(token, [source])
    reference["scope"]["ward"] = "最高第1名病区"
    assert not group_rank_wording_warnings("分组（ward=最高第1名病区）登记值为80元", reference)


def test_concentration_restricts_ranking_without_invalidating_totals():
    document = rank_document(weights=(10000, 1))
    metric = document['metrics'][0]
    assert metric['warnings'] == []
    assert metric['total'] > 0
    assert metric['groupWarnings']['department']
    result, _, token = compile_rank(document)
    assert result.status != 'supported'
    assert 'ranking_dimension_review_required' in result.reasons
    selected = resolve_number_reference(token, [json.dumps(document, ensure_ascii=False)])
    assert group_rank_wording_warnings('该科室排名第1名', selected)


def test_dimension_warning_does_not_restrict_a_different_grain():
    document = rank_document(weights=(100, 90))
    document['metrics'][0]['groupWarnings'] = {'unrelated_dimension': ['待确认']}
    result, _, _ = compile_rank(document)
    assert result.status == 'supported', result.reasons
