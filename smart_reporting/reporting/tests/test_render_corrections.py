"""最终渲染的语义改写：写作关口试渲染时记录并交回模型，正式渲染不记录、行为不变。"""

import json
from pathlib import Path

import pytest
from agno.agent import Agent
from pydantic import ValidationError

from smart_reporting.reporting.agent import ReportingPhaseOpenAIChat
from smart_reporting.reporting.structured_output.execution import _validation_issues
from smart_reporting.reporting.tests.test_derived_claim_context import money_table, share_table
from smart_reporting.reporting.tests.test_number_selection import source
from smart_reporting.reporting.tests.test_numeric_text import (
    _FLAT_BUDGET,
    _comparison_document,
    _monthly_document,
    _rate_comparison_document,
)
from smart_reporting.reporting.trace.numeric_text import (
    align_placeholder_direction,
    correct_constant_monthly_totals,
    correct_period_extrema,
    replace_unregistered_numbers,
)
from smart_reporting.reporting.trace.render_corrections import (
    correction_message,
    record_render_correction,
    recording_render_corrections,
)
from smart_reporting.reporting.workflow.runtime import sections
from smart_reporting.reporting.workflow.runtime.phase_models import SectionBlockContent

_FACTS = (Path(__file__).parent / "fixtures" / "report_quality" / "facts.json").read_text(encoding="utf-8")


def _metric(**overrides):
    return {"factId": "fact-" + "a" * 16, "datasetId": "current", "datasetSha256": "b" * 64,
            "periodRoles": ["current"], "aggregation": "sum", "missingCount": 0, "zeroCount": 0,
            "negativeCount": 0, **overrides}


_VISITS = json.dumps({"analysisId": "analysis_001", "metrics": [_metric(
    field="visits", fieldRef="hospital.visits", unit="人次", formula="sum", total=353000)]})
_MONTHS = json.dumps({"analysisId": "analysis_001", "metrics": [_metric(
    field="amount", fieldRef="hospital.amount", unit="元", formula="sum(amount)", total=150,
    periodGranularity="month",
    periodValues=[{"period": "2025-01", "value": 100}, {"period": "2025-02", "value": 50}])]})
_RATE = "{{value:fact-cccccccccccccccc:changeRate:%}}"

CASES = [
    ("direction", lambda: align_placeholder_direction(f"收入同比下降{_RATE}。", [_comparison_document(6543211, 5.0332)]),
     f"下降{_RATE}", f"增长{_RATE}"),
    ("monthly_total", lambda: correct_constant_monthly_totals(
        "预算总医疗收入各月均为常量131.73亿元（13,172,622,072元）。", [_monthly_document(values=_FLAT_BUDGET)]),
     "各月均为常量131.73亿元（13,172,622,072元）", "各月均为常量10.98亿元（1097718506元）"),
    ("extrema", lambda: correct_period_extrema("[[analysis:analysis_001]]2月金额为最高值50元。", [_MONTHS]),
     "2月金额为最高值50元", "金额最高月份为1月"),
    ("percent_point", lambda: replace_unregistered_numbers("床位使用率同比提高2.10%。", [_rate_comparison_document(2.1)]),
     "2.10%", "2.10个百分点"),
    ("last_digit", lambda: replace_unregistered_numbers("总部、北部合计占69.9%。", [money_table(), share_table()]),
     "69.9%", "70.0%"),
    ("rate_unit", lambda: replace_unregistered_numbers("2月门诊收入环比增长10.00个百分点。", [_FACTS]),
     "10.00个百分点", "10.00%"),
    ("visit_unit", lambda: replace_unregistered_numbers("门诊量35.30万人。", [_VISITS]), "35.30万人", "35.30万人次"),
]


@pytest.mark.parametrize(("kind", "render", "original", "corrected"), CASES, ids=[case[0] for case in CASES])
def test_each_semantic_rewrite_is_recorded_with_what_it_becomes(kind, render, original, corrected):
    with recording_render_corrections() as corrections:
        render()
    [correction] = corrections
    assert (correction.kind, correction.original, correction.corrected) == (kind, original, corrected)
    message = correction_message(correction)
    assert f"“{corrected}”" in message and "所在语句：" in message and "[[" not in message


def test_final_rendering_records_nothing_and_behaves_as_before():
    record_render_correction("direction", "下降", "增长", "下降", 0)
    assert replace_unregistered_numbers("门诊量35.30万人。", [_VISITS]) == "门诊量35.30万人次。"
    with recording_render_corrections() as corrections:
        pass
    assert corrections == []


def _validate(markdown, contents):
    stage = sections._section_stage_agent(
        Agent(model=ReportingPhaseOpenAIChat(id="test", api_key="test")), SectionBlockContent, "block-1",
        response_validator=sections._number_reference_validator(
            SectionBlockContent, number_contents=contents, field_definitions={}, assertions=None,
        ),
    )
    return getattr(stage.model, "_report_response_validator")({"markdown": markdown})


TOTAL = "{{value:fact-dddddddddddddddd:total:元}}"


def test_meaning_changing_rewrites_go_back_to_the_model():
    with pytest.raises(ValidationError) as caught:
        _validate(f"2025年1—2月预算总医疗收入合计{TOTAL}，各月均为140元。", source())
    [issue] = _validation_issues(caught.value)
    assert "把期间合计写成了每月数值" in issue["message"] and "“各月均为70元”" in issue["message"]


def test_deterministic_unit_fixes_alone_do_not_cost_a_model_round():
    # 单位换写由最终渲染确定完成；只有这类修正时不退回，避免为同一结果多开一轮模型调用。
    assert _validate("门诊量35.30万人。", [_VISITS]).markdown == "门诊量35.30万人。"


def test_deterministic_fixes_ride_along_when_the_response_is_returned_anyway():
    with pytest.raises(ValidationError) as caught:
        _validate("门诊量35.30万人，另有999人次。", [_VISITS])
    messages = [issue["message"] for issue in _validation_issues(caught.value)]
    assert any("“999人次”没有对应的登记值" in message for message in messages)
    assert any("应写作“35.30万人次”" in message for message in messages)


def test_value_preserving_retargets_do_not_bother_the_model():
    # “1—2月合计”引用 total 与 periodTotals 显示值相同，只是同一窗口的不同写法。
    assert _validate(f"2025年1—2月预算总医疗收入合计{TOTAL}。", source()).markdown.endswith(f"{TOTAL}。")
