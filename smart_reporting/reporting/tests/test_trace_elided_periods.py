import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.tests.test_deterministic_analysis import analysis, context, semantic
from smart_reporting.reporting.tests.test_deterministic_reconciliation_edges import dataset
from smart_reporting.reporting.trace.semantic_bindings import (
    render_bound_numbers,
    resolve_number_reference,
)


def bundle(grain, labels=None):
    labels = labels or (
        ("2025-01", "2025-02") if grain == "month" else ("2025-01-01", "2025-01-02")
    )
    raw = f"month,department,amount\n{labels[0]},A,100\n{labels[1]},A,200\n".encode()
    ctx = context("current", semantics=(semantic("amount", unit="元"),)).model_copy(
        update={"period_granularities": {"month": "month" if grain == "month" else "date"}}
    )
    return build_deterministic_analysis_bundle(
        analysis().model_copy(update={"series_granularity": grain}), (dataset("current", raw, ctx),)
    )


@pytest.mark.parametrize(
    "grain,first,second",
    [
        ("month", "2025年1月", "2月"),
        ("day", "2025年1月1日", "2日"),
    ],
)
def test_correct_reference_is_not_changed_to_previous_clause_period(grain, first, second):
    b = bundle(grain)
    tokens = [
        "{{value:" + b.metrics[0].fact_id + ":periodValues." + str(i) + ":元}}" for i in (0, 1)
    ]
    text, refs, notices = render_bound_numbers(
        first + "收入为" + tokens[0] + "，" + second + "收入为" + tokens[1] + "。",
        [b.model_dump_json(by_alias=True)],
        key="elided",
        field_definitions={"amount": "收入"},
    )
    assert len(refs) == 2 and not notices
    values = [
        resolve_number_reference(ref.token, [b.model_dump_json(by_alias=True)])["value"]
        for ref in refs
    ]
    assert values == [100, 200], (text, values)


@pytest.mark.parametrize(
    "grain,first,second",
    [
        ("month", "2025年1月", "2025年2月"),
        ("day", "2025年1月1日", "2025年1月2日"),
    ],
)
def test_explicit_period_control(grain, first, second):
    b = bundle(grain)
    tokens = [
        "{{value:" + b.metrics[0].fact_id + ":periodValues." + str(i) + ":元}}" for i in (0, 1)
    ]
    text, refs, notices = render_bound_numbers(
        first + "收入为" + tokens[0] + "，" + second + "收入为" + tokens[1] + "。",
        [b.model_dump_json(by_alias=True)],
        key="explicit",
        field_definitions={"amount": "收入"},
    )
    assert len(refs) == 2 and not notices
    assert [
        resolve_number_reference(ref.token, [b.model_dump_json(by_alias=True)])["value"]
        for ref in refs
    ] == [100, 200]


@pytest.mark.parametrize(
    "grain,first,second",
    [
        ("month", "2025年1月", "2月"),
        ("day", "2025年1月1日", "2日"),
        ("day", "2025年1月1号", "2号"),
    ],
)
def test_wrong_second_reference_is_corrected_using_elided_date(grain, first, second):
    b = bundle(grain)
    token = "{{value:" + b.metrics[0].fact_id + ":periodValues.0:元}}"
    text, refs, notices = render_bound_numbers(
        first + "收入为" + token + "，" + second + "收入为" + token,
        [b.model_dump_json(by_alias=True)],
        key="correct-elided",
        field_definitions={"amount": "收入"},
    )
    assert len(refs) == 2 and not notices
    assert text.endswith(second + "收入为200元")
    assert refs[1].token.endswith(":periodValues.1:元}}")


@pytest.mark.parametrize(
    "grain,first,invalid",
    [
        ("month", "2025年1月", "13月"),
        ("month", "2025年1月", "0月"),
        ("month", "2025年1月", "3月"),
        ("day", "2025年1月1日", "32日"),
        ("day", "2025年1月1日", "0日"),
        ("day", "2025年1月1日", "3日"),
        ("day", "2025年1月1日", "2月30日"),
    ],
)
def test_invalid_or_missing_elided_date_is_unverified(grain, first, invalid):
    b = bundle(grain)
    token = "{{value:" + b.metrics[0].fact_id + ":periodValues.0:元}}"
    text, refs, notices = render_bound_numbers(
        first + "收入为" + token + "，" + invalid + "收入为" + token,
        [b.model_dump_json(by_alias=True)],
        key="invalid-elided",
        field_definitions={"amount": "收入"},
    )
    assert len(refs) == 1 and len(notices) == 1
    assert text.endswith("数值待核实")


@pytest.mark.parametrize(
    "first,second,labels",
    [
        ("2025年1月1日", "2月2日", ("2025-01-01", "2025-02-02")),
        ("2025年1月1日", "2月2号", ("2025-01-01", "2025-02-02")),
    ],
)
def test_elided_daily_year_can_change_month(first, second, labels):
    b = bundle("day", labels)
    token = "{{value:" + b.metrics[0].fact_id + ":periodValues.1:元}}"
    text, refs, notices = render_bound_numbers(
        first + "数据已核对，" + second + "收入为" + token,
        [b.model_dump_json(by_alias=True)],
        key="month-switch",
        field_definitions={"amount": "收入"},
    )
    assert text.endswith("收入为200元") and len(refs) == 1 and not notices


def test_elided_month_uses_end_year_of_preceding_cross_year_range():
    raw = b"month,department,amount\n2024-12,A,100\n2025-01,A,200\n2025-02,A,400\n"
    ctx = context("current", semantics=(semantic("amount", unit="元"),)).model_copy(
        update={"period_granularities": {"month": "month"}}
    )
    b = build_deterministic_analysis_bundle(
        analysis().model_copy(update={"series_granularity": "month"}),
        (dataset("current", raw, ctx),),
    )
    token = "{{value:" + b.metrics[0].fact_id + ":periodValues.2:元}}"
    text, refs, notices = render_bound_numbers(
        "2024年12月至2025年1月数据已核对，2月收入为" + token,
        [b.model_dump_json(by_alias=True)],
        key="cross-year-elided",
        field_definitions={"amount": "收入"},
    )
    assert text.endswith("2月收入为400元") and len(refs) == 1 and not notices
    selected = resolve_number_reference(refs[0].token, [b.model_dump_json(by_alias=True)])
    assert selected["periods"] == ("2025-02",)


@pytest.mark.parametrize("grain,period", [("month", "2月"), ("day", "2日")])
def test_bare_date_with_unique_frozen_calendar_context(grain, period):
    b = bundle(grain)
    token = "{{value:" + b.metrics[0].fact_id + ":periodValues.1:元}}"
    text, refs, notices = render_bound_numbers(
        period + "收入为" + token,
        [b.model_dump_json(by_alias=True)],
        key="bare-date",
        field_definitions={"amount": "收入"},
    )
    assert text.endswith("收入为200元") and len(refs) == 1 and not notices


@pytest.mark.parametrize(
    "grain,period,labels",
    [
        ("month", "1月", ("2024-01", "2025-01")),
        ("day", "2日", ("2025-01-02", "2025-02-02")),
    ],
)
def test_bare_date_with_ambiguous_calendar_context_is_unverified(grain, period, labels):
    b = bundle(grain, labels)
    token = "{{value:" + b.metrics[0].fact_id + ":periodValues.1:元}}"
    text, refs, notices = render_bound_numbers(
        period + "收入为" + token,
        [b.model_dump_json(by_alias=True)],
        key="ambiguous-date",
        field_definitions={"amount": "收入"},
    )
    assert "待核实" in text and not refs and notices
