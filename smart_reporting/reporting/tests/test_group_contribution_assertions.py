"""Complete additive group changes prove signed arithmetic, never causal claims."""

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
from smart_reporting.reporting.trace.reference_semantics import number_reference_warnings
from smart_reporting.reporting.trace.semantic_bindings import (
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.workflow.runtime.sections import _controlled_assertions

from .test_deterministic_analysis import analysis, context, semantic


def contribution_document(*, current=(150, 50), baseline=(100, 80), stock=False, scale=False):
    datasets = []
    for dataset_id, role, year, amounts in (
        ("current", "current", 2025, current),
        ("baseline", "yoy", 2024, baseline),
    ):
        raw = (
            "month,campus,department,amount\n"
            + "".join(
                f"{year}-{month:02d},北院,科室{index:02d},{value}\n"
                for month in (1, 2)
                for index, value in enumerate(amounts)
            )
        ).encode()
        declaration = {
            **semantic(
                "amount", scope={"campus": "北院"}, unit="万元" if scale and role == "yoy" else "元"
            ),
            "additiveAcross": ["department"] if stock else ["month", "department"],
        }
        ctx = context(
            dataset_id,
            fields=("month", "campus", "department", "amount"),
            semantics=(declaration,),
            sha256=hashlib.sha256(raw).hexdigest(),
        ).model_copy(update={"period_granularities": {"month": "month"}})
        datasets.append((dataset_id, raw, ctx, (role,)))
    bundle = build_deterministic_analysis_bundle(analysis(), tuple(datasets), profile_hash="a" * 64)
    assert len(bundle.comparisons) == 1, bundle.warnings
    return json.loads(bundle.model_dump_json(by_alias=True))


def compile_contribution(doc, index=0):
    source = json.dumps(doc, ensure_ascii=False)
    token = f"{{{{value:{doc['comparisons'][0]['factId']}:groupContributions.{index}:%}}}}"
    result = AssertionCompiler(
        [source], profile_hash="a" * 64, authorization_scope_hash="b" * 64
    ).compile(AssertionRequest(operation="group_contribution", operands=(token,), comparison="yoy"))
    return result, source, token


@pytest.mark.parametrize(
    "current,baseline,expected",
    [
        ((150, 50), (100, 80), (250, -150)),
        (
            (50, 100),
            (100, 80),
            (
                Decimal("166.6666666666666666666666666666666666666666666666666666666666667"),
                Decimal("-66.66666666666666666666666666666666666666666666666666666666666667"),
            ),
        ),
        ((120, 100), (100, 80), (50, 50)),
    ],
)
def test_full_partition_supports_signed_contributions_including_offsetting_groups(
    current, baseline, expected
):
    doc = contribution_document(current=current, baseline=baseline)
    for index, value in enumerate(expected):
        result, source, token = compile_contribution(doc, index)
        assert result.status == "supported", result.reasons
        assert Decimal(result.value) == value
        assert len(result.contribution_members) == 2
        assert (
            "有符号净差额" in result.factual_fragment()
            and "不代表因果" in result.factual_fragment()
        )
        selected = resolve_number_reference(token, [source])
        prefix = result.factual_fragment().rsplit(result.value + "%", 1)[0]
        assert not number_reference_warnings(prefix, selected), number_reference_warnings(
            prefix, selected
        )


def test_contribution_catalog_render_and_recheck_use_complete_server_fragment():
    result, source, token = compile_contribution(contribution_document())
    records = {result.assertion_id: result}
    rendered, references, notices = render_bound_numbers(
        "{{assert:" + result.assertion_id + "}}", [source], key="contribution", assertions=records
    )
    assert not notices, rendered
    assert len(references) == 1 and references[0].token == token
    assert "完整分组对照清单" in rendered and "250.00%" in rendered and "待核实" not in rendered
    selected = resolve_number_reference(token, [source])
    assert "(100.0) / (40.0)" in selected["formula"]
    assert not number_reference_warnings(rendered.split("250.00%", 1)[0], selected)
    catalog = frozen_number_catalog([source])
    assert token in catalog and token not in prompt_number_catalog(catalog)
    allowed = f"{{{{value:{json.loads(source)['comparisons'][0]['factId']}:change:元}}}}"
    compiled = assertion_catalog(
        [source],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
        allowed_tokens=[allowed],
        include_group_contributions=True,
    )
    assert (
        sum(record.request.operation == "group_contribution" for record in compiled.values()) == 2
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing_population",
        "missing_member",
        "scope",
        "profile",
        "missing_numeric",
        "duplicate",
        "wrong_total",
        "wrong_change",
        "source",
        "warning",
        "grain",
        "rate",
        "null_group",
        "zero_net",
        "partial_overlap",
        "comparison_warning",
    ],
)
def test_unproven_partition_does_not_mint_a_contribution(fault):
    doc = contribution_document()
    current, baseline = doc["metrics"]
    if fault == "comparison_warning":
        doc["comparisons"][0]["warnings"] = ["共同窗口待复核"]
    elif fault == "missing_population":
        baseline["groupPopulation"] = None
    elif fault == "missing_member":
        baseline["groupPopulation"].pop()
    elif fault == "scope":
        baseline["scope"] = {"campus": "南院"}
    elif fault == "profile":
        baseline["profileHash"] = "c" * 64
    elif fault == "missing_numeric":
        baseline["seriesMissingCount"] = 1
    elif fault == "duplicate":
        baseline["groupPopulation"].append(baseline["groupPopulation"][0])
    elif fault == "wrong_total":
        doc["comparisons"][0]["baselineTotal"] += 1
    elif fault == "wrong_change":
        doc["comparisons"][0]["change"] += 1
    elif fault == "source":
        doc["comparisons"][0]["baselineDatasetSha256"] = "e" * 64
    elif fault == "warning":
        baseline["warnings"] = ["分组总体待确认"]
    elif fault == "grain":
        for array in ("groupPopulation", "topGroups", "bottomGroups"):
            for group in baseline[array]:
                group["groupValues"] = {"ward": group["groupValues"]["department"]}
    elif fault == "rate":
        baseline["unit"] = "%"
    elif fault == "null_group":
        baseline["groupPopulation"][0]["groupValues"]["department"] = None
    elif fault == "zero_net":
        doc = contribution_document(current=(120, 60), baseline=(100, 80))
    elif fault == "partial_overlap":
        # A valid comparison may trim an extra current month, but its full group
        # population belongs to the original three-month frame, not that window.
        current["periodValues"].append({"period": "2025-03", "value": 200})
        current["periodEnd"] = "2025-03"
        current["total"] += 200
    result, source, token = compile_contribution(doc)
    assert result.status == "unknown" and result.value is None
    assert token not in frozen_number_catalog([source])


@pytest.mark.parametrize(
    "old,new",
    [
        ("科室00", "伪造分组"),
        ("有符号净差额", "净差额绝对值"),
        ("允许负贡献", "禁止负贡献"),
        ("2024-01", "2023-01"),
    ],
)
def test_current_body_must_preserve_registered_members_and_denominator(old, new):
    result, source, token = compile_contribution(contribution_document())
    text = result.factual_fragment().split(result.value + "%", 1)[0]
    changed = text.replace(old, new)
    assert changed != text
    assert number_reference_warnings(changed, resolve_number_reference(token, [source]))


def test_extra_causal_or_contribution_claim_cannot_borrow_registered_proof():
    result, source, token = compile_contribution(contribution_document())
    prefix = result.factual_fragment().split(result.value + "%", 1)[0]
    selected = resolve_number_reference(token, [source])
    assert number_reference_warnings("政策驱动增长，" + prefix, selected)
    assert number_reference_warnings("另一分组贡献率也是相同的，" + prefix, selected)


def test_group_change_generation_requires_trusted_source_and_respects_mode():
    result, source, _ = compile_contribution(contribution_document())
    allowed = f"{{{{value:{json.loads(source)['comparisons'][0]['factId']}:change:元}}}}"
    policy = dict(
        mode="enabled",
        profileHash="a" * 64,
        authorizationScopeHash="b" * 64,
        trustedFactSha256=[hashlib.sha256(source.encode()).hexdigest()],
    )
    payload = {"frozenNumbers": {allowed: "40元"}}
    records = _controlled_assertions([source], payload, policy)
    assert result.assertion_id in records
    assert not _controlled_assertions([source], payload, {**policy, "mode": "shadow"})
    assert not _controlled_assertions(
        [source], payload, {**policy, "trustedFactSha256": ["c" * 64]}
    )


def test_known_unit_conversion_precedes_group_subtraction():
    doc = contribution_document(current=(1500000, 500000), baseline=(100, 80), scale=True)
    result, _, _ = compile_contribution(doc)
    assert result.status == "supported", result.reasons
    assert Decimal(result.value) == 250


def test_changed_members_are_not_zero_filled_even_with_valid_totals_and_prefixes():
    doc = contribution_document()
    baseline = doc["metrics"][1]
    for array in ("groupPopulation", "topGroups", "bottomGroups"):
        for group in baseline[array]:
            group["groupValues"]["department"] += "旧名称"
            group["group"] += "旧名称"
    result, _, _ = compile_contribution(doc)
    assert result.status == "unknown"


def test_stock_trimmed_comparison_is_not_upgraded_to_a_partition_proof():
    result, _, _ = compile_contribution(contribution_document(stock=True))
    assert result.status == "unknown"


def test_allocation_and_expansion_budget_do_not_expose_unrequested_comparison_facts():
    doc = contribution_document(current=tuple(range(100, 120)), baseline=tuple(range(20)))
    result, source, _ = compile_contribution(doc)
    assert result.status == "supported"
    token = f"{{{{value:{doc['comparisons'][0]['factId']}:change:元}}}}"
    common = dict(
        profile_hash="a" * 64, authorization_scope_hash="b" * 64, include_group_contributions=True
    )
    records = assertion_catalog([source], allowed_tokens=[token], **common)
    contributions = [
        value for value in records.values() if value.request.operation == "group_contribution"
    ]
    assert len(contributions) == 5 and all(
        len(value.contribution_members) == 20 for value in contributions
    )
    other = f"{{{{value:{doc['metrics'][0]['factId']}:total:元}}}}"
    records = assertion_catalog([source], allowed_tokens=[other], **common)
    assert not any(value.request.operation == "group_contribution" for value in records.values())


def test_unknown_contribution_does_not_remove_independent_total_change():
    doc = contribution_document(current=(120, 60), baseline=(100, 80))
    source = json.dumps(doc)
    token = f"{{{{value:{doc['comparisons'][0]['factId']}:change:元}}}}"
    records = assertion_catalog(
        [source],
        profile_hash="a" * 64,
        authorization_scope_hash="b" * 64,
        allowed_tokens=[token],
        include_group_contributions=True,
    )
    assert len(records) == 1 and next(iter(records.values())).status == "supported"


def test_independent_warning_variant_cannot_reuse_clean_partition_proof():
    doc = contribution_document()
    result, clean, token = compile_contribution(doc)
    assert result.status == "supported"
    doc["metrics"][1]["warnings"] = ["待复核"]
    result = AssertionCompiler(
        [clean, json.dumps(doc)], profile_hash="a" * 64, authorization_scope_hash="b" * 64
    ).compile(AssertionRequest(operation="group_contribution", operands=(token,), comparison="yoy"))
    assert result.status == "unknown"


@pytest.mark.parametrize(
    "current,baseline,index", [((150, 50), (100, 80), 1), ((50, 100), (100, 80), 0)]
)
def test_signed_and_repeating_contribution_survives_real_numeric_rendering(
    current, baseline, index
):
    result, source, token = compile_contribution(
        contribution_document(current=current, baseline=baseline), index
    )
    assert result.status == "supported"
    rendered, references, notices = render_bound_numbers(
        "{{assert:" + result.assertion_id + "}}",
        [source],
        key="signed-contribution",
        assertions={result.assertion_id: result},
    )
    assert len(references) == 1 and not notices, rendered
    shown = references[0].display_text
    assert shown in rendered
    assert not number_reference_warnings(
        rendered.split(shown, 1)[0], resolve_number_reference(token, [source])
    )
