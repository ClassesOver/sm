"""可视化编码任务按计划实际使用的 standard* 字段附带实现规则。

这些规则只约束带对应字段的图；固定写进 Agent 指令会让每次编码调用都发送全部字段说明，
回退到自由绘图的图大多不带这些字段。按计划字段选取后随 facts 下发，规则原文不变。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

StandardFieldPredicate = Callable[[Mapping[str, Any]], bool]


def _present(*keys: str) -> StandardFieldPredicate:
    return lambda chart: any(chart.get(key) for key in keys)


def _right_axis(chart: Mapping[str, Any]) -> bool:
    axes = chart.get("standardAxes")
    return isinstance(axes, Mapping) and bool(axes.get("rightFields"))


STANDARD_FIELD_RULES: tuple[tuple[StandardFieldPredicate, str], ...] = (
    (
        _right_axis,
        "stacked-bar/stacked-total配合dual/rightFields时，左侧分项正负分离堆叠、右侧字段仅画折线，按各轴登记单位换算。"
        "总额只对左侧分项求净和或读取已对账冻结总额，右侧指标和总额不能重复堆叠；缺失右轴值保留断点。",
    ),
    (
        _present("standardPagination"),
        "standardPagination由宿主原子展开为预算内的全部独立图页，每页保留完整原绑定、统一全表范围与系列颜色并标注页号。"
        "未展开的分页计划不能被忽略或只交付前几页；不得用TopN冒充分页，不支持的形状明确回退。",
    ),
    (
        _present("standardSteps", "standardView", "standardDerivations"),
        "计划中的standardSteps或standardView/standardDerivations须从冻结输入按声明顺序执行分组、透视或计算，"
        "不得把预先算好的数值写死在脚本中；保留声明的范围、缺失值、显示单位和系列geometry。",
    ),
    (
        _present("standardEncoding", "standardBands"),
        "standardEncoding须按冻结列绘制真实数值X/Y、比例气泡面积或分类热力矩阵；颜色/面积不可被主题或高亮重写。"
        "缺失观测和单元保留掩码，不能补零；热力矩阵不能转置或暗中聚合重复单元。"
        "standardBands上下界逐行读取已绑定列，按登记单位换算并保持缺失断带，不能估算区间或越过原范围。",
    ),
    (
        _present("standardWaterfall", "standardDistribution"),
        "standardWaterfall必须区分冻结绝对值与有符号增减，不排序截取贡献链，小计/终点与累计对账且不得隐式重置。"
        "standardDistribution仅用绑定的原始组内样本，由Matplotlib绘线性四分位/IQR箱线；缺失不补零，注明有效n，隐藏异常点须说明。",
    ),
    (
        _present("standardDomains"),
        "standardDomains以显示单位控制指定数值轴的范围、刻度和格式；保留原始坐标、范围带和堆叠总高，不按范围裁掉输入行或将超界值压成边界值。"
        "仅outOfRange=annotate允许裁切显示，必须注明超界数量，隐藏图外数值标注；左右轴、各分面和局部轴保持独立，不截取类别轴。",
    ),
    (
        _present("standardBreak"),
        "standardBreak用显示单位声明两个严格分离的线性值轴区间，画清晰断轴标记并注明省略开区间；两段读取相同完整数据，不能修改数值或删除省略行。"
        "barh支持横向分组断轴，lower在左、upper在右，lowerFraction为左段宽度份额；保持同一类别顺序、颜色和有符号柱长，不在两段独立排序。"
        "omittedValues/outOfRange仅显式annotate才允许省略/裁切，并说明数据或边界值数量；缺失空位单独说明，值标注只能落在真实所属区间。",
    ),
    (
        _present("standardBoxSummary"),
        "standardBoxSummary直接读取冻结分位数/中位数/须，不从汇总行重算分布、IQR或原始样本量；未知n和未绑定异常点必须明确说明。"
        "可选异常点使用第二个绑定长表，保留重复观测，并在预检和执行时核验其SHA，隐藏异常点也不能跳过；范围检查涵盖所有统计量和异常点。",
    ),
)

STANDARD_PREFLIGHT_RULE = (
    "standardChartPreflight是标准模板预检诊断；脚本尚不存在时这是首次生成任务，"
    "应结合完整计划和授权数据生成源码，不要假定已有脚本可读。"
)

STANDARD_FIELD_RULES_INSTRUCTION = "图的standard*字段与标准预检按facts.standardFieldRules逐条实现。"


def standard_field_rules(task_facts: Mapping[str, Any]) -> list[str]:
    """按 facts 中的标准预检与计划实际有值的 standard* 字段选取规则，保持规则表顺序。"""
    rules = [STANDARD_PREFLIGHT_RULE] if "standardChartPreflight" in task_facts else []
    plan = task_facts.get("visualizationPlan")
    charts = plan.get("charts") if isinstance(plan, Mapping) else None
    if not isinstance(charts, Sequence) or isinstance(charts, str | bytes):
        return rules
    chart_maps = [chart for chart in charts if isinstance(chart, Mapping)]
    rules.extend(rule for predicate, rule in STANDARD_FIELD_RULES if any(predicate(chart) for chart in chart_maps))
    return rules


__all__ = [
    "STANDARD_FIELD_RULES",
    "STANDARD_FIELD_RULES_INSTRUCTION",
    "STANDARD_PREFLIGHT_RULE",
    "standard_field_rules",
]
