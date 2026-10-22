"""Complete populations and exact tie policy determine Top-N membership."""

import json

import pytest

from smart_reporting.reporting.trace.assertions import (
    AssertionCompiler,
    AssertionRequest,
    assertion_catalog,
)
from smart_reporting.reporting.trace.fact_index import metric_fact_identity
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
from smart_reporting.reporting.trace.top_sets import registered_top_sets, top_set_wording_warnings

from .test_group_share_assertions import group_bundle


def document(weights=(100, 90, 90, 80), **kwargs):
    return json.loads(group_bundle(weights=weights, **kwargs).model_dump_json(by_alias=True))


def compile_set(doc, mode="rank", limit=3):
    source = json.dumps(doc, ensure_ascii=False)
    token = f"{{{{value:{doc['metrics'][0]['factId']}:topSet.{mode}.{limit}:元}}}}"
    result = AssertionCompiler(
        [source], profile_hash="a" * 64, authorization_scope_hash="b" * 64
    ).compile(AssertionRequest(operation="top_n_set", operands=(token,)))
    return result, source, token


@pytest.mark.parametrize(
    "mode,limit,count",
    [
        ("rank", 1, 1),
        ("rank", 2, 3),
        ("rank", 3, 3),
        ("rank", 4, 4),
        ("items", 2, 2),
        ("items", 3, 3),
    ],
)
@pytest.mark.parametrize("stock", [False, True])
def test_complete_membership_and_count_survive_generation_and_statement_validation(
    mode, limit, count, stock
):
    doc = document(stock=stock)
    result, source, token = compile_set(doc, mode, limit)
    assert result.status == "supported", result.reasons
    assert len(result.top_set_members) == count
    assert result.top_set_mode == mode and result.top_set_limit == limit
    text, refs, notices = render_bound_numbers(
        "{{assert:" + result.assertion_id + "}}",
        [source],
        key="set",
        assertions={result.assertion_id: result},
    )
    assert len(refs) == 1 and not notices
    selected = resolve_number_reference(token, [source])
    assert not top_set_wording_warnings(text, selected)
    actual = claim_status(
        anchor_bound_numbers(text, refs),
        refs[0].claim_id,
        selected["value"],
        expected_unit=selected["unit"],
        expected_periods=selected["periods"],
        expected_scope=selected["scope"],
        expected_reference=selected,
    )
    assert actual["status"] == "valid" and not actual["warnings"], actual


def test_boundary_tie_beyond_old_top_ten_is_not_dropped():
    doc = document(weights=(100, *([90] * 14), 80))
    assert len(doc["metrics"][0]["topGroups"]) == 10
    result, source, token = compile_set(doc, "rank", 2)
    assert result.status == "supported" and len(result.top_set_members) == 15
    first_n, _, _ = compile_set(doc, "items", 2)
    assert first_n.status == "supported" and len(first_n.top_set_members) == 2
    assert first_n.assertion_id != result.assertion_id
    assert len(resolve_number_reference(token, [source])["entry"]["groupPopulation"]) == 16


@pytest.mark.parametrize(
    "fault",
    [
        "legacy",
        "empty",
        "removed",
        "duplicate",
        "identity",
        "unit",
        "prefix",
        "missing",
        "numeric_missing",
        "numeric_unknown",
        "scope",
        "profile",
        "time",
    ],
)
def test_incomplete_or_conflicting_population_never_mints_a_complete_set(fault):
    doc = document()
    fact = doc["metrics"][0]
    if fault == "legacy":
        fact.pop("groupPopulation")
    elif fault == "empty":
        fact["groupPopulation"] = []
    elif fault == "removed":
        fact["groupPopulation"].pop()
    elif fault == "duplicate":
        fact["groupPopulation"][-1] = dict(fact["groupPopulation"][0])
    elif fault == "identity":
        fact["groupPopulation"][0]["groupValues"] = {}
    elif fault == "unit":
        fact["unit"] = "%"
    elif fault == "prefix":
        fact["topGroups"][0]["value"] += 1
    elif fault == "missing":
        fact["missingCount"] = 1
    elif fault == "numeric_missing":
        fact["seriesMissingCount"] = 1
    elif fault == "numeric_unknown":
        fact["seriesMissingCount"] = None
    elif fault == "scope":
        fact["scope"] = {}
    elif fault == "profile":
        fact["profileHash"] = "c" * 64
    elif fault == "time":
        fact["periodAggregation"] = None
    result, _, _ = compile_set(doc)
    assert result.status != "supported"


def test_negative_values_are_ranked_but_too_few_items_cannot_claim_exact_n():
    doc = document(weights=(-10, -10, -20))
    result, _, _ = compile_set(doc, "rank", 1)
    assert result.status == "supported" and len(result.top_set_members) == 2
    result, _, _ = compile_set(doc, "items", 4)
    assert result.status == "unknown"


def test_actual_member_list_and_rule_cannot_be_edited_while_sum_stays_equal():
    doc = document()
    result, source, token = compile_set(doc, "rank", 2)
    text = result.factual_fragment()
    reference = resolve_number_reference(token, [source])
    assert not top_set_wording_warnings(text, reference)
    assert top_set_wording_warnings(text.replace("科室00", "伪造科室"), reference)
    assert top_set_wording_warnings(text.replace("前2名", "前3名"), reference)
    assert top_set_wording_warnings(text.replace("含边界全部并列", "不含并列"), reference)
    assert top_set_wording_warnings(text.replace("降序", "升序"), reference)
    ordinary = resolve_number_reference(
        f"{{{{value:{doc['metrics'][0]['factId']}:total:元}}}}", [source]
    )
    assert top_set_wording_warnings(text, ordinary)


def test_population_participates_in_identity_but_historical_none_does_not_upgrade():
    bundle = group_bundle(weights=(100, 90, 80))
    fact = bundle.metrics[0]
    old = fact.model_copy(update={"group_population": None})
    changed = fact.model_copy(update={"group_population": fact.group_population[:-1]})
    assert (
        len({metric_fact_identity(fact), metric_fact_identity(old), metric_fact_identity(changed)})
        == 3
    )


def test_server_only_catalog_is_bounded_and_keeps_complete_lists():
    doc = document(weights=tuple(range(20)))
    source = json.dumps(doc, ensure_ascii=False)
    catalog = frozen_number_catalog([source])
    assert any(":topSet." in token for token in catalog)
    assert not any(":topSet." in token for token in prompt_number_catalog(catalog))
    allowed = [token for token in catalog if ":total:" in token]
    records = assertion_catalog(
        [source],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
        allowed_tokens=allowed,
        include_top_sets=True,
    )
    selected = [result for result in records.values() if result.request.operation == "top_n_set"]
    assert len(selected) == 6 and all(result.status == "supported" for result in selected)
    assert {result.top_set_limit for result in selected} == {3, 5, 10}


def test_population_over_producer_row_budget_is_unavailable_not_a_partial_partition():
    doc = document(weights=tuple(range(2001)))
    assert doc["metrics"][0]["groupPopulation"] is None
    assert len(doc["metrics"][0]["topGroups"]) == 10
    sets, reasons = registered_top_sets(doc["metrics"][0])
    assert not sets and reasons == ("complete_group_population_unavailable",)


def test_quoted_member_labels_cannot_be_interpreted_as_rank_or_business_predicates():
    from smart_reporting.reporting.trace.reference_semantics import number_reference_warnings

    doc = document(weights=(100, 90))
    fact = doc["metrics"][0]
    for group in (*fact["groupPopulation"], *fact["topGroups"], *fact["bottomGroups"]):
        group["groupValues"]["department"] = "唯一未来驱动科室" + group["groupValues"]["department"]
    result, source, token = compile_set(doc, "rank", 1)
    assert result.status == "supported"
    text = result.factual_fragment()
    selected = resolve_number_reference(token, [source])
    assert not top_set_wording_warnings(text, selected)
    assert not number_reference_warnings(text.rsplit(result.value, 1)[0], selected)


@pytest.mark.parametrize(
    "goal,expected",
    [
        ("Top7科室", (7,)),
        ("前七名和前十二个", (7, 12)),
        ("前100名", (100,)),
        ("前一百名", (100,)),
        ("Top101不支持", ()),
        ("前零名", ()),
        ("收入分析", (3, 5, 10)),
    ],
)
def test_requested_cutoff_only_selects_registered_finite_rules(goal, expected):
    from smart_reporting.reporting.trace.top_sets import requested_top_set_limits

    assert requested_top_set_limits(goal) == expected


def test_enabled_generation_can_select_a_requested_nondefault_top_n():
    import hashlib

    from smart_reporting.reporting.workflow.runtime.sections import _controlled_assertions

    source = json.dumps(document(weights=tuple(range(20))), ensure_ascii=False)
    numbers = prompt_number_catalog(frozen_number_catalog([source]))
    payload = {"reportGoal": "报告按收入列出前七名，包含边界并列", "frozenNumbers": numbers}
    records = _controlled_assertions(
        [source],
        payload,
        {
            "mode": "enabled",
            "profileHash": "a" * 64,
            "authorizationScopeHash": "b" * 64,
            "trustedFactSha256": [hashlib.sha256(source.encode()).hexdigest()],
        },
    )
    sets = [value for value in records.values() if value.request.operation == "top_n_set"]
    assert len(sets) == 2 and {value.top_set_limit for value in sets} == {7}
    assert all(len(value.top_set_members) == 7 for value in sets)


def test_global_population_budget_does_not_discard_independent_metric_facts(monkeypatch):
    from smart_reporting.reporting.hospital_operation import deterministic_analysis

    monkeypatch.setattr(deterministic_analysis, "COMPLETE_GROUP_POPULATION_BUDGET_BYTES", 1)
    doc = document()
    assert doc["metrics"][0]["groupPopulation"] is None
    assert doc["metrics"][0]["total"] > 0
    assert doc["metrics"][0]["topGroups"]


def test_overflowing_forged_partition_degrades_without_breaking_numeric_catalog():
    doc = document(weights=(100, 90, 80, 70))
    for group in doc["metrics"][0]["groupPopulation"]:
        group["value"] = 1e308
    sets, reasons = registered_top_sets(doc["metrics"][0])
    assert not sets and reasons == ("top_set_partition_total_mismatch",)
    catalog = frozen_number_catalog([json.dumps(doc, ensure_ascii=False)])
    assert any(":total:" in token for token in catalog)
    assert not any(":topSet." in token for token in catalog)


@pytest.mark.parametrize("aggregation,supported", [("count", True), ("count_distinct", False)])
def test_row_counts_are_additive_but_distinct_entities_cannot_be_summed_across_groups(
    aggregation, supported
):
    import hashlib

    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        build_deterministic_analysis_bundle,
    )

    from .test_deterministic_analysis import analysis, context, semantic

    raw = b"month,campus,department,amount\n2025-01,north,A,1\n2025-01,north,A,1\n2025-01,north,A,1\n2025-01,north,B,1\n2025-01,north,B,1\n2025-01,north,C,1\n"
    declaration = {
        **semantic("amount", scope={"campus": "north"}, unit="人次"),
        "aggregation": aggregation,
        "additiveAcross": ["month", "department"],
    }
    ctx = context(
        "current",
        fields=("month", "campus", "department", "amount"),
        semantics=(declaration,),
        sha256=hashlib.sha256(raw).hexdigest(),
    ).model_copy(update={"period_granularities": {"month": "month"}})
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("amount",)),
        (("current", raw, ctx, ("current",)),),
        profile_hash="a" * 64,
    )
    source = bundle.model_dump_json(by_alias=True)
    token = f"{{{{value:{bundle.metrics[0].fact_id}:topSet.rank.2:人次}}}}"
    result = AssertionCompiler(
        [source], profile_hash="a" * 64, authorization_scope_hash="b" * 64
    ).compile(AssertionRequest(operation="top_n_set", operands=(token,)))
    assert (result.status == "supported") is supported
    if supported:
        assert result.value == "5.0" and len(result.top_set_members) == 2


def test_complete_partition_validation_is_reused_only_inside_one_compiler_request(monkeypatch):
    from smart_reporting.reporting.trace import top_sets

    doc = document(weights=tuple(range(200)))
    source = json.dumps(doc, ensure_ascii=False)
    compiler = AssertionCompiler([source], profile_hash="a" * 64, authorization_scope_hash="b" * 64)
    original = top_sets.registered_top_sets
    calls = []

    def observed(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(top_sets, "registered_top_sets", observed)
    for limit in range(1, 21):
        token = f"{{{{value:{doc['metrics'][0]['factId']}:topSet.rank.{limit}:元}}}}"
        result = compiler.compile(AssertionRequest(operation="top_n_set", operands=(token,)))
        assert result.status == "supported"
    assert len(calls) == 2  # Numeric resolver + semantic compiler; independent of citation count.
    doc["metrics"][0]["groupPopulation"][0]["value"] += 1
    fresh = AssertionCompiler(
        [json.dumps(doc, ensure_ascii=False)],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
    )
    token = f"{{{{value:{doc['metrics'][0]['factId']}:topSet.rank.3:元}}}}"
    assert (
        fresh.compile(AssertionRequest(operation="top_n_set", operands=(token,))).status
        == "unknown"
    )


def test_equivalent_chinese_cutoff_does_not_hide_a_second_conflicting_cutoff():
    result, source, token = compile_set(document(), "rank", 2)
    selected = resolve_number_reference(token, [source])
    text = result.factual_fragment().replace("前2名", "前二名")
    assert not top_set_wording_warnings(text, selected)
    assert top_set_wording_warnings(
        text.replace("完整成员清单：", "也就是前3名，完整成员清单："), selected
    )


def test_rank_cutoff_larger_than_population_does_not_claim_that_many_members_exist():
    result, source, token = compile_set(document(weights=(100, 90)), "rank", 10)
    assert result.status == "supported" and len(result.top_set_members) == 2
    assert "当前登记总体成员少于所请求名次上限" in result.factual_fragment()
    assert not top_set_wording_warnings(
        result.factual_fragment(), resolve_number_reference(token, [source])
    )


@pytest.mark.parametrize(
    "extra,valid",
    [
        ("成员共3个，", True),
        ("成员共2个，", False),
        ("总体有4个分组，", True),
        ("总体共4个分组，", True),
        ("总体共9个分组，", False),
    ],
)
def test_member_and_population_cardinality_cannot_contradict_complete_list(extra, valid):
    result, source, token = compile_set(document(), "rank", 2)
    text = result.factual_fragment().replace("完整成员清单：", extra + "完整成员清单：")
    assert (
        bool(top_set_wording_warnings(text, resolve_number_reference(token, [source]))) is not valid
    )


def test_concentration_is_retained_by_top_set_validation():
    doc = document(weights=(10000, 1))
    result, _, _ = compile_set(doc, limit=1)
    assert result.status != 'supported'
    _, reasons = registered_top_sets(doc['metrics'][0], profile_hash='a' * 64)
    assert reasons == ('ranking_dimension_review_required',)
