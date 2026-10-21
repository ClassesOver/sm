"""Generated counterexamples for arithmetic, identity and calendar contracts.

The decimal oracle and competition-rank oracle do not call production arithmetic.
Examples use real CSV producers where source aggregation matters; calendar tests
exercise the frozen reader over explicitly declared, complete monthly snapshots.
"""

import copy
import json
import math
from decimal import Decimal, localcontext
from functools import lru_cache

from hypothesis import example, given, settings
from hypothesis import strategies as st

from smart_reporting.reporting.trace.cumulative_changes import registered_cumulative_changes
from smart_reporting.reporting.trace.numeric_text import format_fact_value
from smart_reporting.reporting.trace.ratio_proofs import registered_ratio
from smart_reporting.reporting.trace.top_sets import registered_top_sets
from smart_reporting.reporting.units import unit_conversion_scale

from .test_cumulative_changes import cumulative_entry
from .test_group_share_assertions import group_bundle
from .test_registered_ratio_assertions import ratio_document

# Bounded per-test budgets; retain Hypothesis's example database and shrinking.
property_settings = settings(max_examples=60, deadline=None)
_MONEY = {"元": 1, "万元": 10_000, "亿元": 100_000_000}


@property_settings
@given(value=st.floats(allow_nan=False, allow_infinity=False),
       source=st.sampled_from(tuple(_MONEY)), target=st.sampled_from(tuple(_MONEY)))
@example(value=1e200, source="元", target="万元")
def test_money_display_is_within_half_cent_of_independent_decimal_conversion(value, source, target):
    text = format_fact_value(value, source, target)
    assert text.endswith(target)
    shown = Decimal(text[:-len(target)].replace(",", ""))
    with localcontext() as context:
        context.prec = 700
        expected = Decimal(str(value)) * _MONEY[source] / _MONEY[target]
        assert abs(shown - expected) <= Decimal("0.005")


@property_settings
@given(source=st.sampled_from(tuple(_MONEY)), middle=st.sampled_from(tuple(_MONEY)),
       target=st.sampled_from(tuple(_MONEY)))
def test_unit_conversion_composition_and_inverse_preserve_value(source, middle, target):
    direct = unit_conversion_scale(source, target)
    assert direct == unit_conversion_scale(source, middle) * unit_conversion_scale(middle, target)
    assert direct * unit_conversion_scale(target, source) == 1
    assert unit_conversion_scale(source, "人次") is None


def _ratio_proof(document):
    entries = {metric["factId"]: metric for metric in document["metrics"]}
    return registered_ratio(document["derivedMetrics"][0], entries,
                            profile_hash="a" * 64, fact_warnings={})


@property_settings
@given(numerator=st.integers(0, 1_000_000), denominator=st.integers(1, 1_000_000),
       numerator_unit=st.sampled_from(tuple(_MONEY)), denominator_unit=st.sampled_from(("人次", "万人次")))
def test_compound_ratio_matches_independent_decimal_oracle(
    numerator, denominator, numerator_unit, denominator_unit,
):
    document = ratio_document(numerator=(numerator, numerator), denominator=(denominator, denominator),
                              num_unit=numerator_unit, den_unit=denominator_unit)
    proof, reasons = _ratio_proof(document)
    assert proof is not None, reasons
    with localcontext() as context:
        context.prec = 64
        expected = (Decimal(numerator) * _MONEY[numerator_unit]
                    / (Decimal(denominator) * (10_000 if denominator_unit == "万人次" else 1)))
    assert proof["value"] == expected and proof["unit"] == "元/人次"


@property_settings
@given(numerator=st.integers(1, 9), denominator=st.integers(1, 9),
       numerator_exponent=st.integers(-300, 300), denominator_exponent=st.integers(-300, 300))
@example(numerator=1, denominator=1, numerator_exponent=200, denominator_exponent=-200)
@example(numerator=1, denominator=1, numerator_exponent=-200, denominator_exponent=200)
def test_ratio_extremes_cannot_destroy_primitives_or_prove_nonzero_as_zero(
    numerator, denominator, numerator_exponent, denominator_exponent,
):
    left = float(f"{numerator}e{numerator_exponent}")
    right = float(f"{denominator}e{denominator_exponent}")
    with localcontext() as context:
        context.prec = 700
        quotient = Decimal(str(left)) / Decimal(str(right))
        representable = (math.isfinite(float(quotient)) and float(quotient) != 0
                         and math.isfinite(float(quotient * 100)))
    document = ratio_document(numerator=(left, left), denominator=(right, right),
                              den_unit="元", expected_derived_count=1 if representable else 0)
    assert len(document["metrics"]) == 2
    if not representable:
        assert any("溢出或下溢" in warning for warning in document["warnings"])
    else:
        proof, reasons = _ratio_proof(document)
        assert proof is not None, reasons
        assert proof["value"] > 0


@property_settings
@given(value=st.integers(1, 1_000_000), foreign_scope=st.sampled_from(("B", "C", "D")))
def test_equal_numbers_do_not_allow_a_foreign_ratio_scope(value, foreign_scope):
    document = ratio_document(numerator=(value, value), denominator=(value, value))
    # Source identity/amount equality cannot establish the same population.
    document["metrics"][1]["scope"] = {"department": foreign_scope}
    proof, reasons = _ratio_proof(document)
    assert proof is None and "ratio_scope_unproven" in reasons


@property_settings
@given(weights=st.lists(st.integers(1, 100), min_size=2, max_size=16),
       cutoff=st.integers(1, 18), data=st.data())
def test_top_sets_match_competition_rank_oracle_and_ignore_population_order(weights, cutoff, data):
    document = json.loads(group_bundle(weights=weights).model_dump_json(by_alias=True))
    metric = document["metrics"][0]
    proofs, reasons = registered_top_sets(metric, profile_hash="a" * 64)
    assert not reasons
    expected = {f"科室{index:02d}": weight * 2 for index, weight in enumerate(weights)}
    members = {name for name, value in expected.items()
               if 1 + sum(other > value for other in expected.values()) <= cutoff}
    proof = proofs[f"topSet.rank.{cutoff}"]
    assert {member["department"] for member in proof["members"]} == members
    assert proof["value"] == sum(expected[name] for name in members)
    if cutoff <= len(weights):
        exact = proofs[f"topSet.items.{cutoff}"]
        ordered = sorted(expected, key=lambda name: (-expected[name], name))[:cutoff]
        assert [member["department"] for member in exact["members"]] == ordered
    else:
        assert f"topSet.items.{cutoff}" not in proofs
    permutation = data.draw(st.permutations(tuple(range(len(weights)))))
    shuffled = copy.deepcopy(metric)
    shuffled["groupPopulation"] = [metric["groupPopulation"][index] for index in permutation]
    replay, reasons = registered_top_sets(shuffled, profile_hash="a" * 64)
    assert not reasons and replay == proofs


@lru_cache(maxsize=1)
def _calendar_template():
    return cumulative_entry()


def _calendar_entry(start, values):
    metric = copy.deepcopy(_calendar_template())
    months = [f"{(start + index) // 12:04d}-{(start + index) % 12 + 1:02d}"
              for index in range(len(values))]
    metric.update(periodValues=[{"period": month, "value": value}
                                for month, value in zip(months, values, strict=True)],
                  periodStart=months[0], periodEnd=months[-1], total=values[-1])
    return metric, months


@property_settings
@given(start=st.integers(2023 * 12, 2025 * 12 + 11),
       values=st.lists(st.integers(-1_000_000, 1_000_000), min_size=1, max_size=26))
def test_cumulative_calendar_never_fills_missing_baseline_or_subtracts_prior_year(start, values):
    metric, months = _calendar_entry(start, values)
    proofs, reasons = registered_cumulative_changes(metric, profile_hash="a" * 64)
    assert not reasons
    for index, month in enumerate(months):
        selector = f"cumulativeChanges.{index}"
        january = month.endswith("-01")
        if index == 0 and not january:
            assert selector not in proofs
            continue
        baseline = 0 if january else values[index - 1]
        assert proofs[selector]["value"] == Decimal(values[index]) - Decimal(baseline)
        assert proofs[selector]["reset"] is january
        assert proofs[selector]["baseline_period"] == (None if january else months[index - 1])


@property_settings
@given(start=st.integers(2023 * 12, 2025 * 12),
       values=st.lists(st.integers(-1_000_000, 1_000_000), min_size=3, max_size=16), data=st.data())
def test_cumulative_missing_month_is_unknown_without_zero_filling(start, values, data):
    metric, _ = _calendar_entry(start, values)
    missing = data.draw(st.integers(1, len(values) - 2))
    del metric["periodValues"][missing]
    proofs, reasons = registered_cumulative_changes(metric, profile_hash="a" * 64)
    assert proofs == {} and "cumulative_window_incomplete" in reasons
