"""无倍率单位的计算引用须保留原单位，不能把床日混作床或人次。"""

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.calc_references import CalcEvaluator
from smart_reporting.reporting.trace.number_handles import NumberHandles
from smart_reporting.reporting.trace.numeric_text import frozen_number_catalog
from smart_reporting.reporting.trace.semantic_bindings import (
    NumberReferenceResolver,
    render_bound_numbers,
)
from smart_reporting.reporting.trace.value_references import number_reference_failures

from .test_deterministic_analysis import analysis, context, semantic
from .test_number_selection import source


def _scalar_comparison(unit="床日"):
    # 真实运行中出院者占用床日数：2025-01 为 110625，2024-01 为 117305。
    datasets = tuple(
        (name, f"month,department,discharges_bed\n{year}-01,A,{value}\n".encode(),
         context(name, fields=("month", "department", "discharges_bed"),
                 semantics=(semantic("discharges_bed", unit=unit),)), (role,))
        for name, year, value, role in (
            ("current", 2025, 110625, "current"),
            ("baseline", 2024, 117305, "yoy"),
        )
    )
    bundle = build_deterministic_analysis_bundle(analysis(fields=("discharges_bed",)), datasets)
    return [bundle.model_dump_json(by_alias=True)], bundle.comparisons[0].fact_id


@pytest.mark.parametrize("unit", ["床日", "床", "人", "元/人次"])
@pytest.mark.parametrize("operation,expected", [
    ("diff", "6,680"), ("sum", "227,930"), ("avg", "113,965"),
])
def test_calc_preserves_identical_units_without_a_conversion_family(unit, operation, expected):
    contents, fact_id = _scalar_comparison(unit)
    token = "{{calc:" + f"{operation}({fact_id}:baselineTotal,{fact_id}:currentTotal):{unit}" + "}}"
    evaluator = CalcEvaluator(contents)

    result = evaluator.evaluate(token)

    assert result is not None, evaluator.failure(token)
    assert result.text == expected + unit
    assert evaluator.failure(token) is None


def test_bed_day_difference_survives_handles_validation_rendering_and_trace():
    contents, fact_id = _scalar_comparison()
    token = "{{calc:" + f"diff({fact_id}:baselineTotal,{fact_id}:currentTotal):床日" + "}}"
    handles = NumberHandles(frozen_number_catalog(contents))
    encoded = handles.encode(token)
    assert encoded == "{{calc:diff(N1,N2):床日}}"
    markdown = "出院者占用床日数同比减少" + handles.decode(encoded) + "。"

    assert number_reference_failures(markdown, contents) == []
    text, references, notices = render_bound_numbers(markdown, contents, key="bed-day")[:3]

    assert text == "出院者占用床日数同比减少6,680床日。"
    assert not notices
    assert len(references) == 1 and references[0].token == token
    resolved = NumberReferenceResolver(contents).resolve(references[0].token)
    assert resolved["value"] == 6680 and resolved["unit"] == "床日"
    assert "117,305床日" in resolved["formula"]
    assert "110,625床日" in resolved["formula"]
    assert resolved["formula"].endswith(" = 6,680床日")


@pytest.mark.parametrize("unit", ["床", "人次", "元", "%"])
def test_bed_day_difference_rejects_incompatible_display_units(unit):
    contents, fact_id = _scalar_comparison()
    token = "{{calc:" + f"diff({fact_id}:baselineTotal,{fact_id}:currentTotal):{unit}" + "}}"
    evaluator = CalcEvaluator(contents)

    assert evaluator.evaluate(token) is None
    assert evaluator.failure(token) is not None
    assert number_reference_failures(token, contents)


def test_calc_rejects_incompatible_operands_even_when_display_matches_first_unit():
    contents, fact_id = _scalar_comparison()
    token = "{{calc:" + f"sum({fact_id}:currentTotal,fact-bbbbbbbbbbbbbbbb:total):床日" + "}}"
    evaluator = CalcEvaluator(contents + source())

    assert evaluator.evaluate(token) is None
    assert evaluator.failure(token) == "单位不一致"
