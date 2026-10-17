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


def make_bundle(grain, labels):
    raw = (
        "month,department,amount\n"
        + "".join(
            f"{label},A,{value}\n" for label, value in zip(labels, (100, 200, 300), strict=True)
        )
    ).encode()
    ctx = context("current", semantics=(semantic("amount", unit="元"),)).model_copy(
        update={"period_granularities": {"month": "month" if grain == "month" else "date"}}
    )
    return build_deterministic_analysis_bundle(
        analysis().model_copy(update={"series_granularity": grain}), (dataset("current", raw, ctx),)
    )


@pytest.mark.parametrize(
    "grain,labels,first,last",
    [
        ("month", ("2025-01", "2025-12", "2026-01"), "2025年12月", "次年1月"),
        ("day", ("2025-01-02", "2025-01-31", "2025-02-02"), "2025年1月31日", "次月2日"),
    ],
)
def test_relative_calendar_qualifier_does_not_get_ignored(grain, labels, first, last):
    b = make_bundle(grain, labels)
    fact = b.metrics[0]
    tokens = ["{{value:" + fact.fact_id + ":periodValues." + str(i) + ":元}}" for i in (1, 2)]
    text, refs, notices = render_bound_numbers(
        first + "收入为" + tokens[0] + "，" + last + "收入为" + tokens[1],
        [b.model_dump_json(by_alias=True)],
        key="relative",
        field_definitions={"amount": "收入"},
    )
    assert len(refs) == 2 and not notices
    values = [
        resolve_number_reference(ref.token, [b.model_dump_json(by_alias=True)])["value"]
        for ref in refs
    ]
    assert values == [200, 300], (text, values)


@pytest.mark.parametrize(
    "grain,labels,first,last",
    [
        ("month", ("2025-01", "2025-12", "2026-01"), "2025年12月", "2026年1月"),
        ("day", ("2025-01-02", "2025-01-31", "2025-02-02"), "2025年1月31日", "2025年2月2日"),
    ],
)
def test_fully_written_calendar_control(grain, labels, first, last):
    b = make_bundle(grain, labels)
    tokens = [
        "{{value:" + b.metrics[0].fact_id + ":periodValues." + str(i) + ":元}}" for i in (1, 2)
    ]
    text, refs, notices = render_bound_numbers(
        first + "收入为" + tokens[0] + "，" + last + "收入为" + tokens[1],
        [b.model_dump_json(by_alias=True)],
        key="full",
        field_definitions={"amount": "收入"},
    )
    assert len(refs) == 2 and not notices
    assert [
        resolve_number_reference(ref.token, [b.model_dump_json(by_alias=True)])["value"]
        for ref in refs
    ] == [200, 300]


@pytest.mark.parametrize("modifier", ["次年", "翌年", "来年", "上年", "去年", "同年", "当年"])
def test_relative_year_modifier_selects_the_correct_calendar_year(modifier):
    past = modifier in {"上年", "去年"}
    labels = ("2024-01", "2025-12", "2026-01") if past else ("2025-01", "2025-12", "2026-01")
    expected_index = 2 if modifier in {"次年", "翌年", "来年"} else 0
    b = make_bundle("month", labels)
    token = "{{value:" + b.metrics[0].fact_id + ":periodValues.1:元}}"
    text, refs, notices = render_bound_numbers(
        "2025年12月数据已核对，" + modifier + "1月收入为" + token,
        [b.model_dump_json(by_alias=True)],
        key="year-shift",
        field_definitions={"amount": "收入"},
    )
    assert len(refs) == 1 and not notices, text
    selected = resolve_number_reference(refs[0].token, [b.model_dump_json(by_alias=True)])
    assert selected["periods"] == (labels[expected_index],)


@pytest.mark.parametrize("modifier", ["次月", "翌月", "下月", "上月", "当月", "本月"])
def test_relative_month_modifier_selects_the_correct_calendar_month(modifier):
    labels = (
        ("2024-12-02", "2025-01-31", "2025-02-02")
        if modifier == "上月"
        else ("2025-01-02", "2025-01-31", "2025-02-02")
    )
    expected_index = 2 if modifier in {"次月", "翌月", "下月"} else 0
    b = make_bundle("day", labels)
    token = "{{value:" + b.metrics[0].fact_id + ":periodValues.1:元}}"
    text, refs, notices = render_bound_numbers(
        "2025年1月31日数据已核对，" + modifier + "2日收入为" + token,
        [b.model_dump_json(by_alias=True)],
        key="month-shift",
        field_definitions={"amount": "收入"},
    )
    assert len(refs) == 1 and not notices, text
    selected = resolve_number_reference(refs[0].token, [b.model_dump_json(by_alias=True)])
    assert selected["periods"] == (labels[expected_index],)


@pytest.mark.parametrize(
    "labels,anchor,target",
    [
        (("2025-12-02", "2025-12-31", "2026-01-02"), "2025年12月31日", "次月2日"),
        (("2024-01-29", "2024-01-31", "2024-02-29"), "2024年1月31日", "次月29日"),
        (("2025-01-02", "2025-01-31", "2025-02-02"), "2025年1月31日", "次月2月2日"),
    ],
)
def test_relative_month_rollover_and_leap_day(labels, anchor, target):
    b = make_bundle("day", labels)
    token = "{{value:" + b.metrics[0].fact_id + ":periodValues.2:元}}"
    text, refs, notices = render_bound_numbers(
        anchor + "数据已核对，" + target + "收入为" + token,
        [b.model_dump_json(by_alias=True)],
        key="rollover",
        field_definitions={"amount": "收入"},
    )
    assert text.endswith("收入为300元") and len(refs) == 1 and not notices


@pytest.mark.parametrize(
    "grain,labels,anchor,target",
    [
        ("month", ("2025-01", "2025-02", "2025-03"), "", "次年1月"),
        ("day", ("2025-01-01", "2025-01-02", "2025-01-03"), "", "次月2日"),
        ("day", ("2025-01-01", "2025-01-02", "2025-01-03"), "2025年", "次月2日"),
        ("day", ("2025-01-01", "2025-01-02", "2025-01-03"), "2025年13月", "次月2日"),
        ("day", ("2025-01-29", "2025-01-31", "2025-03-01"), "2025年1月31日", "次月29日"),
        ("day", ("2025-01-01", "2025-01-31", "2025-02-01"), "2025年1月31日", "次月3月1日"),
        ("month", ("2025-01", "2025-12", "2026-01"), "2025年12月", "次年2月"),
    ],
)
def test_unavailable_or_ambiguous_relative_calendar_never_borrows_a_value(
    grain, labels, anchor, target
):
    b = make_bundle(grain, labels)
    token = "{{value:" + b.metrics[0].fact_id + ":periodValues.0:元}}"
    prefix = anchor + "数据已核对，" if anchor else ""
    text, refs, notices = render_bound_numbers(
        prefix + target + "收入为" + token,
        [b.model_dump_json(by_alias=True)],
        key="unknown-relative",
        field_definitions={"amount": "收入"},
    )
    assert "待核实" in text and not refs and notices
