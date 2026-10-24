"""写作时计算引用：服务端按冻结原值求值、渲染、放行与溯源。"""

import pytest
from loguru import logger

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.calc_references import CalcEvaluator
from smart_reporting.reporting.trace.content_review import review_content
from smart_reporting.reporting.trace.semantic_bindings import (
    NumberReferenceResolver,
    anchor_bound_numbers,
    render_bound_numbers,
)
from smart_reporting.reporting.trace.subject_builder import claim_status

from .test_deterministic_analysis import analysis, context, semantic

_FIELDS = ("budget_drug", "actual_drug", "budget_material", "actual_material", "visits")


def _bundle_content() -> str:
    ctx = context("current", fields=("month", "department", *_FIELDS), semantics=tuple(
        semantic(field, unit="人次" if field == "visits" else "元") for field in _FIELDS
    )).model_copy(update={"period_granularities": {"month": "month"}})
    rows = (
        "2025-01,A,1500000000,1450000000,1000000000,990000000,300\n"
        "2025-02,A,1213908213,1168227308,1063197728,1059614372,200\n"
    )
    raw = ("month,department," + ",".join(_FIELDS) + "\n" + rows).encode()
    bundle = build_deterministic_analysis_bundle(analysis(fields=_FIELDS), (("current", raw, ctx, ("current",)),))
    return bundle.model_dump_json(by_alias=True)


@pytest.fixture(scope="module")
def facts():
    content = _bundle_content()
    resolver = NumberReferenceResolver([content])
    ids = {entry["field"]: entry["factId"] for entry in resolver.entries.values() if entry.get("field") in _FIELDS}
    return content, {field: f"{fact_id}:total" for field, fact_id in ids.items()}


def _calc(expr: str, unit: str) -> str:
    return "{{calc:" + expr + ":" + unit + "}}"


def test_evaluator_computes_from_unrounded_frozen_values(facts):
    content, ref = facts
    evaluator = CalcEvaluator([content])
    actual = f"sum({ref['actual_drug']},{ref['actual_material']})"
    budget = f"sum({ref['budget_drug']},{ref['budget_material']})"
    cases = {
        _calc(f"ratio({ref['actual_drug']},{ref['budget_drug']})", "%"): "96.47%",
        _calc(budget, "亿元"): "47.77亿元",
        _calc(f"ratio({actual},{budget})", "%"): "97.71%",
        _calc(f"diff({actual},{budget})", "亿元"): "-1.09亿元",
        _calc(f"growth({ref['actual_drug']},{ref['budget_drug']})", "%"): "-3.53%",
        _calc(f"avg({ref['actual_drug']},{ref['budget_drug']})", "亿元"): "26.66亿元",
        _calc(
            f"diff(ratio({ref['actual_drug']},{ref['budget_drug']}),"
            f"ratio({ref['actual_material']},{ref['budget_material']}))",
            "个百分点",
        ): "-2.87个百分点",
    }
    for token, expected in cases.items():
        result = evaluator.evaluate(token)
        assert result is not None and result.text == expected, token


@pytest.mark.parametrize("expr,unit", [
    ("ratio({actual_drug},{visits})", "%"),            # 金额与人次不同单位族
    ("ratio({actual_drug},{budget_drug})", "亿元"),     # 显示单位与结果不符
    ("sum({actual_drug},fact-ffffffffffffffff:total)", "亿元"),  # 未登记操作数
    ("ratio({actual_drug},diff({budget_drug},{budget_drug}))", "%"),  # 除数为零
    ("sum({actual_drug},100)", "亿元"),                 # 不接受字面数字
    ("pow({actual_drug},{budget_drug})", "亿元"),       # 未知运算
    ("sum(sum(sum(sum({actual_drug},{budget_drug}),{budget_drug}),{budget_drug}),{budget_drug})", "亿元"),
])
def test_evaluator_refuses_invalid_expressions(facts, expr, unit):
    content, ref = facts
    assert CalcEvaluator([content]).evaluate(_calc(expr.format(**ref), unit)) is None


def test_render_signs_calc_references_and_flags_invalid_ones(facts):
    content, ref = facts
    markdown = (
        "## 预算执行\n\n"
        f"药品完成率{_calc(f'ratio({ref['actual_drug']},{ref['budget_drug']})', '%')}，"
        f"实际较预算短少{_calc(f'diff({ref['budget_drug']},{ref['actual_drug']})', '亿元')}，"
        f"两项预算合计{_calc(f'sum({ref['budget_drug']},{ref['budget_material']})', '亿元')}；"
        f"错误示例{_calc(f'ratio({ref['actual_drug']},{ref['visits']})', '%')}。\n"
    )
    text, references, notices = render_bound_numbers(markdown, [content], key="calc")[:3]
    assert "药品完成率96.47%，实际较预算短少0.96亿元，两项预算合计47.77亿元；错误示例数值待核实。" in text
    assert [notice.kind for notice in notices] == ["numeric_unverified"]
    anchored = anchor_bound_numbers(text, references, notices)
    resolver = NumberReferenceResolver([content])
    calc_references = [item for item in references if item.token.startswith("{{calc:")]
    assert len(calc_references) == 3
    for item in calc_references:
        selected = resolver.resolve(item.token)
        assert selected["selector"] == "calc" and " = " in selected["formula"]
        status = claim_status(anchored, item.claim_id, selected["value"], expected_unit=selected["unit"],
                              expected_periods=selected["periods"], expected_reference=selected)
        assert status == {"status": "valid", "warnings": []}


def test_content_review_explains_invalid_calc_reference(facts):
    content, ref = facts
    valid = f"完成率{_calc(f'ratio({ref['actual_drug']},{ref['budget_drug']})', '%')}。"
    invalid = f"完成率{_calc(f'ratio({ref['actual_drug']},{ref['visits']})', '%')}。"
    assert not any("计算引用" in warning for warning in review_content(valid, [content]))
    assert any("计算引用无法求值" in warning for warning in review_content(invalid, [content]))


def test_content_review_does_not_report_valid_calc_references_as_unavailable(facts):
    content, ref = facts
    markdown = (f"药品完成率{_calc(f'ratio({ref['actual_drug']},{ref['budget_drug']})', '%')}，"
                f"较预算短少{_calc(f'diff({ref['budget_drug']},{ref['actual_drug']})', '亿元')}。")
    messages = []
    sink = logger.add(lambda message: messages.append(message.record["message"]), level="WARNING")
    try:
        warnings = review_content(markdown, [content])
    finally:
        logger.remove(sink)
    # 能重算的计算引用不再按未登记引用记日志，服务端结果也不参与按登记值比对的数字核对。
    assert not any("report_number_reference_unavailable" in message for message in messages)
    assert warnings == []


def test_content_review_returns_falling_wording_on_positive_calc_growth(facts):
    content, ref = facts
    growth = _calc(f"growth({ref['actual_drug']},{ref['actual_material']})", "%")
    decline = _calc(f"growth({ref['actual_material']},{ref['actual_drug']})", "%")
    [warning] = review_content(f"药品较材料下降{growth}。", [content])
    assert warning.startswith("方向与计算结果相反：下降") and "growth(本期, 基期)" in warning
    # 负增速的负号由最终渲染改写；“增速下降为”描述的是比率水平；差额的方向取决于操作数先后。
    assert review_content(f"材料较药品下降{decline}。", [content]) == []
    assert review_content(f"药品增速下降为{growth}。", [content]) == []
    gap = _calc(f"diff({ref['budget_drug']},{ref['actual_drug']})", "亿元")
    assert review_content(f"药品实际较预算减少{gap}。", [content]) == []
