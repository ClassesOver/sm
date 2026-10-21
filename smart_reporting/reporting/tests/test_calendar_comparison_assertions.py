"""Calendar-period comparisons require real complete input buckets and exact roles."""

import hashlib
import json

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.assertions import AssertionCompiler, AssertionRequest
from smart_reporting.reporting.trace.comparison_proofs import _comparable_periods
from smart_reporting.reporting.trace.reference_semantics import number_reference_warnings
from smart_reporting.reporting.trace.semantic_bindings import (
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.workflow.runtime.sections import _controlled_assertions

from .test_deterministic_analysis import analysis, context, semantic


def calendar_document(grain="day", kind="yoy", current=None, baseline=None):
    if current is None:
        current = (
            (("2025-01-01", 120), ("2025-01-02", 180))
            if grain == "day"
            else (("2024", 120), ("2025", 180))
        )
    if baseline is None:
        baseline = (
            (("2024-01-01", 100), ("2024-01-02", 100))
            if grain == "day"
            else (("2023", 100), ("2024", 100))
        )
    datasets = []
    for name, role, values in (("current", "current", current), ("baseline", kind, baseline)):
        raw = (
            f"{grain},department,amount\n"
            + "".join(f"{label},A,{amount}\n" for label, amount in values)
        ).encode()
        declaration = {
            **semantic("amount", scope={"department": "A"}, unit="元"),
            "additiveAcross": [grain, "department"],
        }
        ctx = context(
            name,
            fields=(grain, "department", "amount"),
            semantics=(declaration,),
            sha256=hashlib.sha256(raw).hexdigest(),
        ).model_copy(
            update={
                "time_series_sort_field": grain,
                "period_granularities": {grain: "date" if grain == "day" else grain},
            }
        )
        datasets.append((name, raw, ctx, (role,)))
    bundle = build_deterministic_analysis_bundle(
        analysis().model_copy(update={"series_granularity": grain}),
        tuple(datasets),
        profile_hash="a" * 64,
    )
    assert len(bundle.comparisons) == 1, bundle.warnings
    return json.loads(bundle.model_dump_json(by_alias=True))


def compile_calendar(doc, selector="changeRate"):
    entry = doc["comparisons"][0]
    source = json.dumps(doc, ensure_ascii=False)
    token = (
        f"{{{{value:{entry['factId']}:{selector}:{'%' if selector == 'changeRate' else '元'}}}}}"
    )
    result = AssertionCompiler(
        [source], profile_hash="a" * 64, authorization_scope_hash="b" * 64
    ).compile(
        AssertionRequest(
            operation="relative_change" if selector == "changeRate" else "difference",
            operands=(token,),
            comparison=entry["comparisonType"],
        )
    )
    return result, source, token


@pytest.mark.parametrize("grain", ["day", "year"])
@pytest.mark.parametrize("selector", ["change", "changeRate"])
def test_frozen_daily_and_yearly_flow_comparisons_render_and_recheck(grain, selector):
    result, source, token = compile_calendar(calendar_document(grain), selector)
    assert result.status == "supported", result.reasons
    assert result.value == ("100.0" if selector == "change" else "50.0")
    text, refs, notices = render_bound_numbers(
        "{{assert:" + result.assertion_id + "}}",
        [source],
        key="calendar",
        assertions={result.assertion_id: result},
    )
    assert len(refs) == 1 and not notices, text
    assert "2024年" in text if grain == "year" else "2025-01-01" in text
    assert not number_reference_warnings(
        text.split(refs[0].display_text, 1)[0], resolve_number_reference(token, [source])
    )


@pytest.mark.parametrize(
    "grain,current,baseline,word",
    [
        ("day", (("2025-01-01", 120),), (("2024-12-31", 100),), "较前一日"),
        ("day", (("2024-03-01", 120),), (("2024-02-29", 100),), "较前一日"),
        ("year", (("2025", 120),), (("2024", 100),), "较上一年"),
    ],
)
def test_prior_period_uses_declared_calendar_grain_and_clear_wording(
    grain, current, baseline, word
):
    result, source, token = compile_calendar(calendar_document(grain, "mom", current, baseline))
    assert result.status == "supported", result.reasons
    assert result.value == "20.0" and word in result.factual_fragment()
    text, refs, notices = render_bound_numbers(
        "{{assert:" + result.assertion_id + "}}",
        [source],
        key="prior",
        assertions={result.assertion_id: result},
    )
    assert len(refs) == 1 and not notices, text
    assert not number_reference_warnings(
        text.split(refs[0].display_text, 1)[0], resolve_number_reference(token, [source])
    )


@pytest.mark.parametrize("leap_side", ["current", "baseline"])
def test_whole_calendar_yoy_preserves_the_actual_leap_day_in_its_own_total(leap_side):
    current_year, baseline_year = (2024, 2023) if leap_side == "current" else (2025, 2024)

    def values(year, leap):
        return tuple(
            (f"{year}-{day}", 10)
            for day in (("02-28", "02-29", "03-01") if leap else ("02-28", "03-01"))
        )

    doc = calendar_document(
        current=values(current_year, leap_side == "current"),
        baseline=values(baseline_year, leap_side == "baseline"),
    )
    result, _, _ = compile_calendar(doc, "change")
    assert result.status == "supported", result.reasons
    assert float(result.value) == (10 if leap_side == "current" else -10)
    assert len(result.periods) == (3 if leap_side == "current" else 2)
    assert len(result.baseline_periods) == (3 if leap_side == "baseline" else 2)


@pytest.mark.parametrize(
    "fault",
    [
        "missing_grain",
        "grain_mismatch",
        "missing_series",
        "unparseable_numeric",
        "missing_period",
        "gap_without_warning",
        "wrong_value",
        "wrong_profile",
        "wrong_role",
        "partial_window",
        "unit",
        "nonadditive",
    ],
)
@pytest.mark.parametrize("grain", ["day", "year"])
def test_calendar_comparison_does_not_upgrade_incomplete_or_incomparable_sources(grain, fault):
    doc = calendar_document(grain)
    metric = doc["metrics"][0]
    if fault == "missing_grain":
        metric["periodGranularity"] = None
    elif fault == "grain_mismatch":
        doc["comparisons"][0]["periodGranularity"] = "month"
    elif fault == "missing_series":
        metric.pop("seriesMissingCount")
    elif fault == "unparseable_numeric":
        metric["seriesMissingCount"] = 1
    elif fault == "missing_period":
        metric["periodMissingCount"] = 1
    elif fault == "gap_without_warning":
        metric["periodValues"].pop(0)
    elif fault == "wrong_value":
        doc["comparisons"][0]["changeRate"] += 1
    elif fault == "wrong_profile":
        metric["profileHash"] = "c" * 64
    elif fault == "wrong_role":
        doc["metrics"][1]["periodRoles"] = ["mom"]
    elif fault == "partial_window":
        doc["comparisons"][0]["periodStart"] = doc["comparisons"][0]["periodEnd"]
    elif fault == "unit":
        doc["metrics"][1]["unit"] = "人次"
    elif fault == "nonadditive":
        for metric in doc["metrics"]:
            metric["periodAggregation"] = None
    result, _, _ = compile_calendar(doc)
    assert result.status == "unknown" and result.value is None


def test_a_missing_inner_leap_day_cannot_be_filled_from_metadata_endpoints():
    doc = calendar_document(
        current=(("2024-02-28", 10), ("2024-02-29", 10), ("2024-03-01", 10)),
        baseline=(("2023-02-28", 10), ("2023-03-01", 10)),
    )
    doc["metrics"][0]["periodValues"].pop(1)
    doc["metrics"][0]["total"] = 20
    doc["comparisons"][0].update(currentTotal=20, baselineTotal=20, change=0, changeRate=0)
    result, _, _ = compile_calendar(doc)
    assert (
        result.status == "unknown" and "comparison_calendar_completeness_unproven" in result.reasons
    )


@pytest.mark.parametrize(
    "grain,wrong",
    [("day", "月度同比"), ("day", "环比"), ("year", "月度同比"), ("year", "日度同比")],
)
def test_unchanged_amount_cannot_lend_a_proof_to_another_calendar_relation(grain, wrong):
    result, source, token = compile_calendar(calendar_document(grain))
    prefix = result.factual_fragment().split(result.value + "%", 1)[0]
    assert not number_reference_warnings(prefix, resolve_number_reference(token, [source]))
    assert number_reference_warnings(
        prefix.replace("同比", wrong), resolve_number_reference(token, [source])
    )


def test_enabled_generation_can_select_registered_calendar_comparisons_without_a_model_declaring_proof():
    doc = calendar_document("year")
    result, source, token = compile_calendar(doc)
    payload = {"frozenNumbers": {token: "50%"}}
    policy = dict(
        mode="enabled",
        profileHash="a" * 64,
        authorizationScopeHash="b" * 64,
        trustedFactSha256=[hashlib.sha256(source.encode()).hexdigest()],
    )
    assert result.assertion_id in _controlled_assertions([source], payload, policy)
    assert not _controlled_assertions([source], payload, {**policy, "mode": "shadow"})


@pytest.mark.parametrize(
    "current,baseline,kind,grain,expected",
    [
        (
            ("2024-02-28", "2024-02-29", "2024-03-01"),
            ("2023-02-28", "2023-03-01"),
            "yoy",
            "day",
            True,
        ),
        (("2024-02-28", "2024-03-01"), ("2023-02-28", "2023-03-01"), "yoy", "day", False),
        (("2024-02-29",), ("2023-02-28",), "yoy", "day", False),
        (("2025-01-01",), ("2024-12-31",), "mom", "day", True),
        (("2025",), ("2024",), "mom", "year", True),
        (("2024", "2025"), ("2023", "2024"), "mom", "year", False),
        (("2025-01",), ("2024-12",), "mom", "month", True),
        (("2025-01-01",), ("2024-01-01",), "yoy", "month", False),
        (("2025-01-01",), ("2024-01-01",), "unexpected", "day", False),
    ],
)
def test_calendar_policy_has_explicit_boundaries(current, baseline, kind, grain, expected):
    assert _comparable_periods(current, baseline, kind, grain=grain) is expected


@pytest.mark.parametrize(
    "grain,current,baseline",
    [
        ("day", (("2025/01/01", 120),), (("2024/01/01", 100),)),
        ("year", (("2025-01-01", 120),), (("2024-01-01", 100),)),
    ],
)
def test_declared_grain_normalizes_valid_date_aliases_without_changing_the_window(
    grain, current, baseline
):
    result, _, _ = compile_calendar(calendar_document(grain, current=current, baseline=baseline))
    assert result.status == "supported", result.reasons
    assert result.value == "20.0"


@pytest.mark.parametrize(
    "grain,current,baseline",
    [
        (
            "day",
            (("2025-01-01", "bad"), ("2025-01-02", 180)),
            (("2024-01-01", 100), ("2024-01-02", 100)),
        ),
        ("month", (("2025-01", "bad"), ("2025-02", 180)), (("2024-01", 100), ("2024-02", 100))),
        ("year", (("2024", "bad"), ("2025", 180)), (("2023", 100), ("2024", 100))),
    ],
)
def test_real_unparseable_input_cannot_pass_using_only_the_raw_null_count(grain, current, baseline):
    doc = calendar_document(grain, current=current, baseline=baseline)
    assert doc["metrics"][0]["missingCount"] == 0
    assert doc["metrics"][0]["seriesMissingCount"] == 1
    result, _, _ = compile_calendar(doc)
    assert result.status == "unknown" and result.value is None


@pytest.mark.parametrize("grain", ["day", "month", "year"])
def test_endpoint_expansion_never_returns_a_truncated_over_budget_window(grain):
    from smart_reporting.reporting.trace.subject_builder import fact_periods

    assert (
        fact_periods(
            {"periodStart": "0001-01-01", "periodEnd": "9999-12-31", "periodGranularity": grain}
        )
        == ()
    )


def test_explicit_year_role_labels_do_not_turn_a_four_digit_currency_amount_into_a_date():
    from smart_reporting.reporting.trace.subject_builder import unit_period_warnings

    assert not unit_period_warnings(
        "本期2025年、基期2024年，同比差额为2025元",
        expected_unit="元",
        expected_periods=("2025", "2024"),
        expected_period_roles={"current": ("2025",), "baseline": ("2024",)},
        fact_value=2025,
    )


def test_source_display_name_is_not_an_authored_comparison_predicate():
    doc = calendar_document("day", "mom", (("2025-01-01", 120),), (("2024-12-31", 100),))
    doc["metrics"][0]["displayName"] = "同比业务收入"
    result, source, token = compile_calendar(doc)
    assert result.status == "supported"
    assert not number_reference_warnings(
        result.factual_fragment().split(result.value + "%", 1)[0],
        resolve_number_reference(token, [source]),
    )


def test_explicit_complete_month_window_cannot_be_narrowed_while_leaving_its_total_unchanged():
    from .test_frozen_time_aggregation import frozen_bundle

    doc = json.loads(frozen_bundle().model_dump_json(by_alias=True))
    result, source, token = compile_calendar(doc)
    from smart_reporting.reporting.trace.subject_builder import unit_period_warnings

    text = result.factual_fragment().replace("本期2025-01至2025-02", "本期2025-02至2025-02")
    selected = resolve_number_reference(token, [source])
    assert unit_period_warnings(
        text, expected_periods=selected["periods"], expected_period_roles=selected["period_roles"]
    )
