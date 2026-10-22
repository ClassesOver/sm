"""Business qualifiers require their actual sequence, definition and study evidence."""

import json

import pytest

from smart_reporting.reporting.trace.business_semantics import (
    complex_monthly_semantics,
    unsupported_business_warnings,
)
from smart_reporting.reporting.trace.monthly_trends import monthly_trend_wording_warnings
from smart_reporting.reporting.trace.reference_semantics import number_reference_warnings
from smart_reporting.reporting.trace.semantic_bindings import resolve_number_reference

from .test_monthly_trend_assertions import compile_trend, trend_bundle


@pytest.mark.parametrize("department", [None, "普通外科"])
def test_null_hierarchy_scope_does_not_crash_review(department):
    selected, _ = reference((10, 20, 30), "total")
    selected["scope"] = {"department": department, "parent_department": None}
    selected["entry"]["aliases"] = ["医疗收入"]
    warnings = number_reference_warnings("普通外科收入为", selected)
    assert any("业务范围" in warning for warning in warnings) is (department is None)


def reference(values, selector="monthlyTrend"):
    doc = json.loads(trend_bundle(values).model_dump_json(by_alias=True))
    result, source, token = compile_trend(doc, selector=selector)
    return resolve_number_reference(token, [source]), result


@pytest.mark.parametrize(
    "values,text,valid",
    [
        ((10, 30, 20), "先严格上升后严格下降（唯一峰值月份=2025-02）", True),
        ((30, 10, 20), "先严格下降后严格上升（唯一谷值月份=2025-02）", True),
        ((10, 30, 20, 40), "先升后降", False),
        ((10, 30, 30, 20), "单峰", False),
        ((10, 20, 30), "先升后降", False),
        ((10, 30, 20), "先升后降（唯一峰值月份=2025-01）", False),
        ((10, 30, 30), "唯一峰值月份=2025-02", False),
        ((10, 30, 20), "唯一谷值月份=2025-01", True),
        ((10, 30, 20), "单谷", False),
        ((10, 30, 20), "预计先升后降", False),
        ((10, 30, 20), "累计先升后降", False),
        ((10, 30, 20), "不是单峰", False),
    ],
)
def test_single_turn_and_unique_extreme_use_every_registered_month(values, text, valid):
    selected, _ = reference(values)
    assert bool(monthly_trend_wording_warnings(text, selected)) is not valid


@pytest.mark.parametrize(
    "values,text,valid",
    [
        ((100, 200, 310), "相邻月绝对增量严格扩大", True),
        ((100, 200, 310), "相邻月环比增长率严格下降", True),
        ((100, 200, 310), "相邻月环比增长率严格上升", False),
        ((100, 200, 310), "相邻月绝对增量严格缩小", False),
        ((100, 130, 150), "相邻月绝对增量严格缩小", True),
        ((100, 80, 50), "相邻月绝对减量严格扩大", True),
        ((100, 80, 70), "相邻月绝对减量严格缩小", True),
        ((100, 80, 70), "相邻月绝对增量严格扩大", False),
        ((100, 80, 70), "相邻月环比增长率严格上升", False),
        ((100, 80, 70), "相邻月环比相对变化率严格上升", True),
        ((0, 10, 30), "相邻月环比增长率严格上升", False),
        ((-10, -5, -1), "相邻月环比相对变化率严格上升", False),
        ((10, 20, 30), "相邻月绝对增量严格持平", True),
        ((10, 20, 40), "相邻月环比增长率严格持平", True),
    ],
)
def test_absolute_changes_and_relative_growth_are_separate_predicates(values, text, valid):
    selected, _ = reference(values)
    assert bool(monthly_trend_wording_warnings(text, selected)) is not valid


def test_complex_shape_cannot_borrow_a_total_or_an_endpoint():
    selected, _ = reference((10, 30, 20), "total")
    assert monthly_trend_wording_warnings("先升后降", selected)
    selected, _ = reference((10, 30, 20), "periodValues.2")
    assert monthly_trend_wording_warnings("单峰", selected)


def test_known_complex_qualifiers_do_not_disable_other_unsupported_claim_checks():
    selected, _ = reference((10, 30, 20))
    assert monthly_trend_wording_warnings("先升后降且显著改善", selected)
    assert monthly_trend_wording_warnings("先升后降且震荡", selected)
    assert monthly_trend_wording_warnings("先升后降但持续上升", selected)


@pytest.mark.parametrize(
    "text",
    [
        "政策导致收入增长",
        "增长归因于人力扩张",
        "投入是增长主因",
        "存在因果关系",
        "收入统计显著上升",
        "收入显著增长",
        "预测未来继续上升",
        "明年将达到新高",
        "占比说明贡献率增加",
        "算术贡献为全部增长",
    ],
)
def test_arithmetic_is_not_causal_statistical_or_forecasting_evidence(text):
    assert unsupported_business_warnings(text)
    selected, _ = reference((10, 20, 30))
    assert number_reference_warnings("department=A，" + text + "，期末登记值为", selected)


@pytest.mark.parametrize(
    "text",
    [
        "不能证明因果关系",
        "不代表因果关系",
        "不能据此认定为增长主因",
        "没有证据证明因果关系",
        "不作为预测",
        "不代表显著增长",
        "不代表贡献率",
        "登记值按全部相邻月核对",
    ],
)
def test_explicit_limits_do_not_become_positive_business_claims(text):
    assert not unsupported_business_warnings(text)


def test_direction_shape_and_relative_qualifiers_remain_independently_checked():
    selected, result = reference((100, 200, 310))
    fragment = result.factual_fragment()
    assert "相邻月绝对增量严格扩大" in fragment
    assert "相邻月环比相对变化率严格下降" in fragment
    assert not monthly_trend_wording_warnings(fragment, selected)
    assert monthly_trend_wording_warnings(
        fragment.replace("变化率严格下降", "变化率严格上升"), selected
    )
    selected, result = reference((10, 30, 20))
    assert "唯一峰值月份=2025-02" in result.factual_fragment()
    assert not complex_monthly_semantics(result.factual_fragment(), selected)[0]


@pytest.mark.parametrize(
    "text", ["总体增长所以所有科室都增长", "全部分组均下降", "并非所有科室都增长"]
)
def test_aggregate_or_subset_cannot_prove_a_universal_subgroup_change(text):
    assert unsupported_business_warnings(text)


def test_explicit_limit_does_not_claim_a_universal_subgroup_change():
    assert not unsupported_business_warnings("不能据此证明所有科室都增长")


@pytest.mark.parametrize(
    "date,valid",
    [
        ("2025/2", True),
        ("2025年2月", True),
        ("2025/1", False),
        ("2025-02-01", False),
        ("今年2月", False),
        ("2025-99", False),
    ],
)
def test_peak_period_alias_or_unknown_format_does_not_skip_validation(date, valid):
    selected, _ = reference((10, 30, 20))
    assert bool(monthly_trend_wording_warnings("单峰，唯一峰值月份=" + date, selected)) is not valid


def test_known_source_name_is_data_not_a_future_or_causal_predicate():
    selected, _ = reference((10, 20, 30))
    selected["entry"]["displayName"] = "未来收益驱动额"
    text = "未来收益驱动额按未舍入登记月值逐月严格上升，期末登记值为"
    assert not number_reference_warnings("department=A，" + text, selected)


@pytest.mark.parametrize(
    "values,text,valid",
    [
        ((10, 30, 20), "先升后降", True),
        ((30, 10, 20), "先降后升", True),
        ((10, 30, 20), "先升后降随后上升", False),
        ((10, 30, 20), "先升后持平再降", False),
        ((10, 30, 20), "先升后降且整体上升", True),
        ((30, 10, 20), "先降后升且整体上升", False),
        ((30, 10, 20), "先降后升且期末较期初下降", True),
    ],
)
def test_path_connectors_and_net_direction_are_not_inferred_from_one_true_subclause(
    values, text, valid
):
    selected, _ = reference(values)
    assert bool(monthly_trend_wording_warnings(text, selected)) is not valid
