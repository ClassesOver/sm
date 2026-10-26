"""补证决策的确定性前置：固定事实明确覆盖分析问题时不再请求模型判断。

只认标准统计意图（规模、趋势、同比、构成、预算执行），且每个意图都有对应的冻结事实；
问题里出现固定事实不提供的意图（贡献、异常、排名、相关、人均等）、点名了未拆分的维度、
或处于返工/修订/重试中时一律返回 None，交由模型决策。宁可多问一次，不能漏掉必要补证。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ...hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
from ...trace.fact_index import breakdown_partitions, shareable_partition
from ...trace.numeric_text import budget_comparison_values, project_ratio_values

_BEYOND_FACTS = re.compile(
    r"相关|回归|预测|归因|原因|驱动|贡献|异常|离群|明细|下钻|排名|排序|前\s*\d|top\s*\d|"
    r"人均|单产|次均|均次|每(?:人|床|门诊|出院|人次|万元)|弹性|敏感|模拟|假设|同步|联动|"
    r"效率|周转|测算|推算|口径|可比",
    re.IGNORECASE,
)
_INTENTS = {
    "scale": re.compile(r"规模|合计|总额|总量|汇总|总体|全年|累计|sum|total|summar", re.IGNORECASE),
    "trend": re.compile(r"趋势|走势|月度|逐月|各月|每月|变化|波动|环比|拐点|trend|month", re.IGNORECASE),
    "yoy": re.compile(r"同比|上年|去年|yoy", re.IGNORECASE),
    "structure": re.compile(r"构成|结构|占比|分布|比重|composition|share", re.IGNORECASE),
    "budget": re.compile(r"预算|执行|完成率|达成|budget", re.IGNORECASE),
}
# “按 X 划分”“各 X”的 X；X 与已拆分维度的名称或组值有共同词时才算已覆盖。
_DIMENSION_MENTION = re.compile(
    r"(?:按|各)([一-鿿A-Za-z]{1,10}?)"
    r"(?=划分|分组|统计|比较|对比|构成|结构|占比|分布|汇总|的|和|与|及|、|，|,|。|？|\?|$)"
)
_TIME_WORDS = re.compile(r"月|年|季|期|日")
# 指标名中的通用词不能证明维度相同（“收入科室”与“收入业务类型”只共享“收入”）。
_GENERIC_WORDS = re.compile(r"收入|支出|成本|预算|金额|医疗|业务|指标|构成|数量|情况")
_FACT_GAP_WARNING = re.compile(r"未生成|未对数值字段猜测|没有已确认指标语义|无法解析为 CSV")


def facts_cover_analysis(
    facts: DeterministicAnalysisBundle,
    analysis: Mapping[str, Any] | None,
    instruction: Mapping[str, Any],
) -> str | None:
    """固定事实覆盖当前分析问题时返回可审计的原因；不确定时返回 None。"""

    if (not isinstance(analysis, Mapping) or not facts.metrics
            or instruction.get("analysisReworkRequest") or instruction.get("reviewFeedback")
            or instruction.get("thinkingFailureKind")):
        return None
    if any(_FACT_GAP_WARNING.search(warning) for warning in facts.warnings):
        return None
    text = "；".join(str(item) for item in (analysis.get("step"), *(analysis.get("actions") or ())) if item)
    if not text or _BEYOND_FACTS.search(text):
        return None
    mentions = _dimension_mentions(text)
    intents = [name for name, pattern in _INTENTS.items()
               if pattern.search(text) or (name == "structure" and mentions)]
    if not intents:
        return None
    # 无法判断问题针对哪项指标，趋势与构成须对每项当期指标都成立。
    current = [fact for fact in facts.metrics if "current" in fact.period_roles]
    partitions = _shareable_partitions(facts)
    available = {
        "scale": True,
        "trend": bool(current) and all(len(fact.period_values) >= 3 for fact in current),
        "yoy": any(item.comparison_type == "yoy" for item in facts.comparisons),
        "structure": bool(current) and all(fact.fact_id in partitions for fact in current),
        "budget": bool(budget_comparison_values(facts) or project_ratio_values(facts)),
    }
    if not all(available[name] for name in intents):
        return None
    if mentions and not all(_dimensions_covered(mentions, partitions[fact.fact_id]) for fact in current):
        return None
    # 只说“占比/结构”而未点名维度或已登记分组（“药品收入占医疗收入的比重”）时，
    # 存在任意分组不能证明问到的那一项已登记，交给模型判断。
    if "structure" in intents and not mentions and not _names_registered_group(text, partitions):
        return None
    return "固定事实已覆盖" + "、".join(
        {"scale": "规模", "trend": "趋势", "yoy": "同比", "structure": "维度构成", "budget": "预算执行"}[name]
        for name in intents
    )


def _dimension_mentions(text: str) -> list[str]:
    """“按/各 X”中的非期间 X；“各月医疗收入”只是期间，不是维度。"""
    mentions = []
    for match in _DIMENSION_MENTION.finditer(text):
        mention = match.group(1)
        if _TIME_WORDS.search(mention) and not _GENERIC_WORDS.sub("", mention).strip("月年季期日的"):
            continue
        mentions.append(mention)
    return mentions


def _shareable_partitions(facts: DeterministicAnalysisBundle) -> dict[str | None, list[list[Any]]]:
    """父指标 → 能登记占比的完整维度（父合计为正、各组非负）；其余维度没有占比可引用。"""
    parents = {fact.fact_id: fact for fact in facts.metrics}
    partitions: dict[str | None, list[list[Any]]] = {}
    for (parent, _), groups in breakdown_partitions(facts).items():
        if shareable_partition(parents[parent], groups):
            partitions.setdefault(parent, []).append(groups)
    return partitions


def _dimensions_covered(mentions: list[str], partitions: list[list[Any]]) -> bool:
    vocabulary = {
        word
        for groups in partitions
        for fact in groups
        for word in (fact.breakdown_label, fact.breakdown_field, *(fact.scope.values()))
        if word
    }
    return all(any(_shares_word(mention, word) for word in vocabulary) for mention in mentions)


def _shares_word(mention: str, word: str) -> bool:
    """点名的维度与登记维度/组值是同一个词，或是登记名称的一部分；多出限定词（“开单科室”）不算。"""
    left, right = _GENERIC_WORDS.sub("", mention), _GENERIC_WORDS.sub("", word)
    return len(left) >= 2 and (left == right or left in right)


def _names_registered_group(text: str, partitions: dict[str | None, list[list[Any]]]) -> bool:
    return any(
        len(value) >= 2 and value in text
        for parent in partitions.values()
        for groups in parent
        for fact in groups
        for value in (fact.breakdown_value or "",)
    )


__all__ = ["facts_cover_analysis"]
