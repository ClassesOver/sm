"""从冻结事实生成正文数值；模型只选择数值引用，不负责换算或千分位。"""

from __future__ import annotations

import bisect
import json
import math
import os
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any

from loguru import logger

from ..hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
    PeriodValue,
    _parse_period,
)
from ..units import MONEY_UNITS as _MONEY_UNITS
from ..units import unit_scales as _unit_scales
from .fact_index import fact_binding_records, merge_binding_records

# 增减方向词对照：自动纠正、正文复核与 claim 绑定共用同一份，避免各处漏掉不同写法
# （“跌幅-5%”“上涨-654万元”曾因词表不全原样发布）。
RISING_TO_FALLING = {
    "增长": "下降", "上升": "下降", "增加": "减少", "提高": "降低", "增幅": "降幅",
    "涨幅": "跌幅", "上涨": "下跌", "回升": "回落",
}
FALLING_TO_RISING = {
    "下降": "增长", "减少": "增加", "降低": "提高", "回落": "回升", "下滑": "上升",
    "降幅": "增幅", "减幅": "增幅", "跌幅": "涨幅", "下跌": "上涨", "缩减": "增加",
}
RISING_WORDS = tuple(RISING_TO_FALLING)
FALLING_WORDS = tuple(FALLING_TO_RISING)
DIRECTION_WORD_PATTERN = "|".join((*RISING_WORDS, *FALLING_WORDS))
# 方向词紧跟在比率名词之后（“增速下降为5.03%”“增幅回落为…”）时，描述的是比率本身
# 升降到多少，不是数量的增减方向：不能按冻结符号改写动作词或去掉负号。
_RATE_SUBJECT = re.compile(
    r"(?:增速|增幅|增长率|增长速度|降幅|跌幅|涨幅|减幅|变化率|比重|占比|完成率|执行率)(?:\*\*)?\s*$"
)


def describes_rate_level(prefix: str) -> bool:
    """方向词之前紧邻比率名词时返回 True。"""
    return _RATE_SUBJECT.search(prefix) is not None
_NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_MONEY_PAIR = re.compile(
    rf"(?<![\d.,])(?P<large>{_NUMBER})\s*(?P<unit>亿元|万元)"
    rf"\s*[（(]\s*(?P<base>{_NUMBER})\s*元\s*[）)]"
)


# 百分数指标的变化额/差额是两项百分数之差：85.30%→83.20% 是下降 2.10 个百分点，
# 写成“下降2.10%”会被读成相对降幅。数值引用仍沿用 % 单位名，显示改为百分点。
PERCENT_POINT = "个百分点"


def percent_point_field(field: str, unit: str | None) -> bool:
    """百分数指标的变化额、差额（含预算差额）按百分点显示。"""
    return unit == "%" and (field in {"change", "difference"} or field.endswith(".difference"))


def format_fact_value(value: Any, unit: str | None, display_unit: str | None = None) -> str:
    number = Decimal(str(value))
    target = display_unit or unit
    if target != unit and not (unit == "%" and target == PERCENT_POINT):
        scales = _unit_scales(unit)
        number = number * scales[unit] / scales[target]
    if target in {"万元", "亿元", "万人次", "%", "‰", PERCENT_POINT} or number != number.to_integral_value():
        rounded = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        # 舍入为零的负数不能显示为“-0.00”。
        text = f"{abs(rounded) if rounded == 0 else rounded:,f}"
    else:
        text = f"{number:,.0f}"
    return text + (target or "")


def _hidden_by_rounding(value: Any, unit: str | None, target: str | None) -> bool:
    """非零值换算到更大单位后舍入为 0.00（如 10万元 → 0.00亿元）时不提供该显示。"""
    if not target or target == unit or value is None:
        return False
    number = Decimal(str(value))
    if number == 0:
        return False
    scales = _unit_scales(unit)
    if scales is None or target not in scales:
        return False
    converted = number * scales[unit] / scales[target]
    return converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == 0


def _canonical_month_label(label: str) -> str | None:
    """统一有效年月和月初标签，保留数值选择器对应的原始桶索引。"""
    parsed = _parse_period(label)
    if parsed is None or parsed.granularity == "year" or parsed.value.day != 1:
        return None
    return f"{parsed.value.year:04d}-{parsed.value.month:02d}"


def _valid_month_labels(periods: Iterable[str]) -> bool:
    return all(_canonical_month_label(label) is not None for label in periods)


def budget_comparison_values(bundle: DeterministicAnalysisBundle) -> list[dict[str, Any]]:
    """仅对唯一、同快照、同范围的 budget_/actual_ 月度事实提供数学比较。"""
    comparisons = []
    for actual in bundle.metrics:
        if not actual.fact_id or not actual.field.startswith("actual_"):
            continue
        budgets = [fact for fact in bundle.metrics if fact.field == "budget_" + actual.field.removeprefix("actual_")
                   and fact.dataset_id == actual.dataset_id and fact.dataset_sha256 == actual.dataset_sha256
                   and fact.scope == actual.scope and fact.unit == actual.unit
                   and fact.field_ref.rsplit(".", 1)[0] == actual.field_ref.rsplit(".", 1)[0]
                   and fact.period_roles == actual.period_roles]
        if len(budgets) != 1 or not budgets[0].fact_id:
            continue
        budget = budgets[0]
        if actual.period_aggregation != budget.period_aggregation:
            continue
        monthly = []
        for fact in (actual, budget):
            if fact.aggregation != "sum" or fact.period_granularity != "month" or not 0 < len(fact.period_values) <= 12:
                break
            if not _valid_month_labels(value.period for value in fact.period_values):
                break
            values = {_canonical_month_label(value.period): Decimal(str(value.value)) for value in fact.period_values}
            if len(values) != len(fact.period_values) or len({period[:4] for period in values}) != 1:
                break
            monthly.append(values)
        if len(monthly) != 2 or monthly[0].keys() != monthly[1].keys():
            continue
        periods = sorted(monthly[0])
        if any(int(right[5:7]) - int(left[5:7]) != 1 for left, right in zip(periods, periods[1:])):
            continue
        actual_running = budget_running = Decimal(0)
        for period in periods:
            numerator, denominator = monthly[0][period], monthly[1][period]
            actual_running += numerator
            budget_running += denominator
            windows = [(period, numerator, denominator)]
            if actual.period_aggregation != "last":
                windows.append((f"{periods[0]}..{period}", actual_running, budget_running))
            for window, current, planned in windows:
                comparisons.append({
                    "actualFactId": actual.fact_id, "budgetFactId": budget.fact_id,
                    "numeratorMetric": actual.field, "denominatorMetric": budget.field,
                    "period": window, "unit": actual.unit,
                    "difference": current - planned,
                    "percentage": current / planned * 100 if planned != 0 else None,
                })
    return comparisons


def project_ratio_values(bundle: DeterministicAnalysisBundle) -> list[dict[str, Any]]:
    """由同快照项目预算与合同/付款总额计算无量纲比例。"""
    ratios = []
    for numerator in bundle.metrics:
        if numerator.field not in {"contract_amount", "payment_amount"} or not numerator.fact_id:
            continue
        budgets = [budget for budget in bundle.metrics
                   if budget.field == "budget_project_amount" and budget.fact_id
                   and budget.aggregation == numerator.aggregation == "sum"
                   and budget.dataset_id == numerator.dataset_id
                   and budget.dataset_sha256 == numerator.dataset_sha256
                   and budget.scope == numerator.scope and budget.unit == numerator.unit
                   and budget.period_roles == numerator.period_roles
                   and budget.period_start == numerator.period_start
                   and budget.period_end == numerator.period_end
                   and budget.field_ref.rsplit(".", 1)[0] == numerator.field_ref.rsplit(".", 1)[0]]
        if len(budgets) != 1 or not budgets[0].total:
            continue
        ratios.append({
            "numeratorFactId": numerator.fact_id, "budgetFactId": budgets[0].fact_id,
            "numeratorMetric": numerator.field, "percentage":
                Decimal(str(numerator.total)) / Decimal(str(budgets[0].total)) * 100,
        })
    return ratios


def frozen_fact_bundles(contents: Iterable[str]) -> Iterator[DeterministicAnalysisBundle]:
    """目录与引用解析共用模型校验和字段规范化，忽略非事实文档。"""
    for content in contents:
        try:
            bundle = DeterministicAnalysisBundle.model_validate_json(content)
        except ValueError:
            continue
        yield bundle


def _registered_groups(entry: Mapping[str, Any], key: str):
    groups = entry.get(key, ())
    counts = Counter(item['group'] for item in groups)
    return [(index, item) for index, item in enumerate(groups)
            if item.get('groupValues') or counts[item['group']] == 1]


def _frozen_number_entries(contents: Iterable[str]) -> Iterator[tuple[str, Any, str | None, str | None]]:
    """逐项给出 (数值引用, 未舍入原值, 原单位, 显示单位)；目录与复核共用同一来源。"""
    for bundle in frozen_fact_bundles(contents):
        document = bundle.model_dump(mode="json", by_alias=True)
        for array, fields in (
            ("metrics", ("total", "average", "minimum", "maximum")),
            ("comparisons", ("currentTotal", "baselineTotal", "change", "changeRate")),
            ("derivedMetrics", ("value", "percentage", "numerator", "denominator", "difference")),
            ("reconciliations", ("difference",)),
            ("correlationDetails", ("value",)),
        ):
            for entry in document[array]:
                fact_id = entry.get("factId")
                if not fact_id:
                    continue
                values = [(field, entry.get(field)) for field in fields]
                values.extend((f"periodValues.{index}", item["value"]) for index, item in enumerate(entry.get("periodValues", ())))
                for groups_key in ("topGroups", "bottomGroups"):
                    values.extend((f"{groups_key}.{index}", item["value"])
                                  for index, item in _registered_groups(entry, groups_key))
                # 分组占比（“心内科占全院门诊收入的23.85%”）由服务端按登记分组值与合计计算：
                # 仅限求和指标、合计为正且无负值，百分数指标的占比无意义，不在此登记。
                total = entry.get("total")
                if (array == "metrics" and entry.get("aggregation") == "sum" and entry.get("unit") != "%"
                        and isinstance(total, (int, float)) and total > 0 and not entry.get("negativeCount")):
                    for groups_key in ("topGroups", "bottomGroups"):
                        values.extend(
                            (f"groupShares.{groups_key}.{index}", Decimal(str(item["value"])) / Decimal(str(total)) * 100)
                            for index, item in _registered_groups(entry, groups_key)
                            if isinstance(item.get("value"), (int, float)) and item["value"] >= 0)
                # 分组之间的差额（“心内科较骨科多140.00万元”）：按登记的前列分组两两相减，只登记非负差额。
                top = [(index, item) for index, item in _registered_groups(entry, "topGroups")
                       if isinstance(item.get("value"), (int, float))]
                if array == "metrics" and entry.get("unit") != "%" and len(top) <= 12:
                    values.extend(
                        (f"groupGaps.{left[0]}-{right[0]}", abs(Decimal(str(left[1]["value"])) - Decimal(str(right[1]["value"]))))
                        for left_position, left in enumerate(top) for right in top[left_position + 1:])
                periods = [{**item, "period": _canonical_month_label(item["period"]) or item["period"]}
                           for item in entry.get("periodValues", ())]
                if (array == "metrics" and entry.get("aggregation") == "sum"
                        and entry.get("periodGranularity") == "month" and periods
                        and len(periods) <= 12
                        and _valid_month_labels(item["period"] for item in periods)
                        and len({item["period"][:7] for item in periods}) == len(periods)):
                    # 均值分母使用实际月桶数，前缀累计从原值相加，禁止先舍入再累加。
                    amounts = [Decimal(str(item["value"])) for item in periods]
                    values.extend((("monthlyAverage", sum(amounts) / len(amounts)),
                                   ("monthlyMinimum", min(amounts)), ("monthlyMaximum", max(amounts))))
                    running = Decimal(0)
                    months = [int(item["period"][:4]) * 12 + int(item["period"][5:7]) for item in periods]
                    chronological = True
                    for index, amount in enumerate(amounts):
                        running += amount
                        chronological = chronological and (index == 0 or months[index] > months[index - 1])
                        if not chronological:
                            continue
                        if entry.get("periodAggregation") != "last":
                            values.append((f"periodTotals.0-{index}", running))
                        if months[:index + 1] == list(range(months[0], months[0] + index + 1)):
                            values.append((f"periodAverages.0-{index}", running / (index + 1)))
                    # 相邻两月的变化额与变化率（“3月环比增长…”）由服务端按登记月度值计算：只在月份
                    # 连续时登记，基期为零时不给变化率；百分数指标的差值口径不同，不在此登记。
                    for index in range(1, len(amounts)) if entry.get("unit") != "%" else ():
                        if months[index] != months[index - 1] + 1:
                            continue
                        change = amounts[index] - amounts[index - 1]
                        values.append((f"periodChanges.{index}", change))
                        if amounts[index - 1]:
                            values.append((f"periodChangeRates.{index}", change / amounts[index - 1] * 100))

                for field, value in values:
                    if value is None:
                        continue
                    # 派生事实的 unit 是分子/差额单位，比值本身无量纲。
                    unit = ("%" if field in {"changeRate", "percentage"}
                            or field.startswith(("periodChangeRates.", "groupShares."))
                            else None if array == "derivedMetrics" and field == "value"
                            else entry.get("unit"))
                    if percent_point_field(field, unit):
                        yield f"{{{{value:{fact_id}:{field}:%}}}}", value, unit, PERCENT_POINT
                        continue
                    units = _unit_scales(unit) or (unit or "",)
                    for target in units:
                        yield f"{{{{value:{fact_id}:{field}:{target}}}}}", value, unit, target or None
        for comparison in budget_comparison_values(bundle):
            for field, unit in (("difference", comparison["unit"]), ("percentage", "%")):
                # 单位未知时不登记绝对差额；无量纲的预算完成率仍可引用。
                if field == "difference" and not unit:
                    continue
                if comparison[field] is None:
                    continue
                if percent_point_field(field, unit):
                    token = f"{{{{value:{comparison['actualFactId']}:budgetComparison.{comparison['budgetFactId']}.{comparison['period']}.{field}:%}}}}"
                    yield token, comparison[field], unit, PERCENT_POINT
                    continue
                for target in (_unit_scales(unit) or (unit or "",)):
                    token = f"{{{{value:{comparison['actualFactId']}:budgetComparison.{comparison['budgetFactId']}.{comparison['period']}.{field}:{target}}}}}"
                    yield token, comparison[field], unit, target or None
        for ratio in project_ratio_values(bundle):
            yield (f"{{{{value:{ratio['numeratorFactId']}:projectRatio.{ratio['budgetFactId']}.percentage:%}}}}",
                   ratio["percentage"], "%", "%")


def _readable_display_unit(value: Any, unit: str | None, target: str | None) -> str | None:
    """换算后绝对值不足 1 的非零值改用同量纲中能写成不小于 1 的最大单位。

    654.32万元的变化额写成“0.07亿元”既难读又丢精度（误差约 7%）；数值引用名不变，
    只换显示单位，模型选了亿元引用也会显示为“654.32万元”。
    """
    if not target or target == unit or value is None:
        return target
    scales = _unit_scales(unit)
    if scales is None or target not in scales:
        return target
    amount = abs(Decimal(str(value)) * scales[unit])
    if amount == 0 or amount / scales[target] >= 1:
        return target
    for candidate, scale in sorted(scales.items(), key=lambda item: item[1], reverse=True):
        if amount / scale >= 1:
            return candidate
    return min(scales, key=lambda candidate: scales[candidate])


# 只供服务端核对与渲染的派生数值引用（相邻月变化、分组占比与分组差额）：不放进模型可见的数值目录。
_SERVER_ONLY_FIELDS = ("periodChanges.", "periodChangeRates.", "groupShares.", "groupGaps.")


def prompt_number_catalog(catalog: Mapping[str, str]) -> dict[str, str]:
    """模型可见的数值目录：去掉只供服务端核对的相邻月变化、分组占比与分组差额引用。"""
    return {token: text for token, text in catalog.items()
            if not token[2:-2].split(":")[2].startswith(_SERVER_ONLY_FIELDS)}


def frozen_number_catalog(contents: Iterable[str]) -> dict[str, str]:
    contents = tuple(contents)
    records = {}
    conflicts = set()
    for bundle in frozen_fact_bundles(contents):
        for fact_id, record in fact_binding_records(bundle).items():
            if fact_id in records:
                merged = merge_binding_records(records[fact_id], record)
                if merged is None:
                    conflicts.add(fact_id)
                record = merged or record
            records[fact_id] = record
    catalog: dict[str, str] = {}
    originals: dict[str, tuple[Decimal, str | None, str | None]] = {}
    for token, value, unit, target in _frozen_number_entries(contents):
        if any(fact_id in conflicts for fact_id in re.findall(r"fact-[0-9a-f]{16}", token)):
            catalog[token] = "数值待核实"
            continue
        original = (Decimal(str(value)), unit, target)
        if token in originals:
            # 必须比较未舍入原值；显示均为 30.00 不能证明 30.001 与 30.002 一致。
            # 一旦冲突就保留待核实，后续重复证据不能将其恢复为可信数值。
            if originals[token] != original:
                catalog[token] = "数值待核实"
            continue
        originals[token] = original
        catalog[token] = format_fact_value(value, unit, _readable_display_unit(value, unit, target))
    return catalog


def frozen_number_values(contents: Iterable[str], catalog: dict[str, str]) -> dict[str, set[Decimal]]:
    """按显示单位给出未舍入的冻结原值。

    正文数字应由原值按其书写精度舍入后比较；若用两位小数的显示文本再舍入，
    1.245万元会先变成1.25再变成1.3，正确的1.2反被判为无依据。
    """
    values: dict[str, set[Decimal]] = {}
    for token, value, unit, target in _frozen_number_entries(contents):
        display_unit = target or unit
        # 非零值换算后舍入为 0.00（-10万元 → 0.00亿元）不能作为依据，手写“0.00亿元”仍替换。
        if (not display_unit or catalog.get(token) == "数值待核实"
                or _hidden_by_rounding(value, unit, target)):
            continue
        number = Decimal(str(value))
        if display_unit != unit and (scales := _unit_scales(unit)) is not None:
            number = number * scales[unit] / scales[display_unit]
        values.setdefault(display_unit, set()).add(number)
    return values


def _month_coverage(periods: list[str]) -> str | None:
    """单一年度月度期间的覆盖说明（“2025年1—10月（10个月），不是全年”），供模型直接引用。"""
    if not periods or not _valid_month_labels(periods):
        return None
    periods = [_canonical_month_label(period) for period in periods]
    years = {period[:4] for period in periods}
    months = sorted({int(period[5:7]) for period in periods})
    if len(years) != 1 or len(months) != len(periods):
        return None
    span = (f"{months[0]}—{months[-1]}月" if months == list(range(months[0], months[-1] + 1))
            else "、".join(f"{month}月" for month in months))
    note = "" if len(months) == 12 else "，不是全年"
    return f"{years.pop()}年{span}（{len(months)}个月）{note}"


# numberGuide 中 total 的读法：只有 sum/count 是加总，平均与极值口径不能写成合计或累计。
_TOTAL_MEANINGS = {
    "sum": "完整期间合计",
    "count": "完整期间计数",
    "count_distinct": "完整期间去重计数，不能按月相加",
    "average": "完整期间平均值，不能称为合计、累计或总额",
    "min": "完整期间最小值，不能称为合计、累计或总额",
    "max": "完整期间最大值，不能称为合计、累计或总额",
}


def frozen_number_guide(
    contents: Iterable[str], catalog: dict[str, str], *, field_definitions: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """将数值引用与期间、粒度及分组绑定，避免模型只看数值猜用途。"""
    guide: list[dict[str, Any]] = []
    seen: set[str] = set()
    for content in contents:
        try:
            bundle = DeterministicAnalysisBundle.model_validate_json(content)
        except ValueError:
            continue
        comparisons = budget_comparison_values(bundle)
        project_ratios = project_ratio_values(bundle)
        for fact in bundle.metrics:
            if not fact.fact_id or fact.fact_id in seen:
                continue
            seen.add(fact.fact_id)

            def reference(field: str) -> str | None:
                token = f"{{{{value:{fact.fact_id}:{field}:{fact.unit or ''}}}}}"
                return token if token in catalog and catalog[token] != "数值待核实" else None

            def shown(field: str, unit: str | None = None) -> str | None:
                # 相邻月变化不进模型数值目录（避免目录膨胀），这里直接给显示值；金额按万元显示。
                target = unit or ("万元" if fact.unit in _MONEY_UNITS else fact.unit or "")
                text = catalog.get(f"{{{{value:{fact.fact_id}:{field}:{target}}}}}")
                return text if text and text != "数值待核实" else None

            periods = [item.period for item in fact.period_values]
            stock = fact.period_aggregation == "last"
            total_periods = periods[-1:] if stock else periods
            item: dict[str, Any] = {
                "factId": fact.fact_id, "analysisId": bundle.analysis_id,
                "datasetId": fact.dataset_id,
                "metric": getattr(fact, "display_name", None) or (field_definitions or {}).get(fact.field, fact.field),
                "metricCodes": list(fact.metric_codes), "scope": fact.scope,
                "unit": fact.unit, "periodRoles": list(fact.period_roles),
                "periodGranularity": fact.period_granularity,
                "periodAggregation": fact.period_aggregation,
                "total": {"reference": reference("total"), "periods": total_periods,
                          "periodStart": fact.period_end if stock else fact.period_start, "periodEnd": fact.period_end,
                          "aggregation": fact.aggregation,
                          "meaning": "最新登记期间的期末余额，不能跨期相加" if stock else
                                     _TOTAL_MEANINGS.get(fact.aggregation, "完整期间的统计值"),
                          **({"coverage": coverage} if (coverage := _month_coverage(total_periods)) else {})},
                "rowStatistics": {"average": reference("average"), "minimum": reference("minimum"),
                                  "maximum": reference("maximum"),
                                  "meaning": ("最新登记期间的原始行统计" if stock else "原始行统计")
                                             + "，不能称为月均值或月度极值"},
            }
            if reference("monthlyAverage"):
                low = min(value.value for value in fact.period_values)
                high = max(value.value for value in fact.period_values)
                item["monthlyStatistics"] = {
                    "monthCount": len(periods), "average": reference("monthlyAverage"),
                    "minimum": reference("monthlyMinimum"), "maximum": reference("monthlyMaximum"),
                    "minimumPeriods": [value.period for value in fact.period_values if value.value == low],
                    "maximumPeriods": [value.period for value in fact.period_values if value.value == high],
                    "zeroPeriods": [value.period for value in fact.period_values if value.value == 0],
                    "prefixTotals": [{"start": periods[0], "end": period,
                                      "reference": reference(f"periodTotals.0-{index}")}
                                     for index, period in enumerate(periods) if reference(f"periodTotals.0-{index}")],
                    "prefixAverages": [{"start": periods[0], "end": period, "monthCount": index + 1,
                                        "reference": reference(f"periodAverages.0-{index}")}
                                       for index, period in enumerate(periods) if reference(f"periodAverages.0-{index}")],
                    "monthOverMonth": [
                        {"period": period, "change": shown(f"periodChanges.{index}"),
                         "changeRate": shown(f"periodChangeRates.{index}", "%")}
                        for index, period in enumerate(periods) if shown(f"periodChanges.{index}")
                    ],
                    "meaning": "包含已登记的零值月份；零值本身不证明未入账或缺失。局部极值必须明确子期间。"
                               "monthOverMonth 是服务端按登记月度值计算的相邻两月变化额与变化率（某月较上月），"
                               "可按显示值直接书写，不是环比比较事实的窗口变化",
                }
            item["groups"] = [{"group": group.group, "reference": reference(f"{key}.{index}"),
                               "meaning": ("最新登记期间的完整分组组合期末余额" if stock else "完整分组组合的数值")
                                          + "，不能称为单一科室或院区累计"}
                              for key, groups in (("topGroups", fact.top_groups), ("bottomGroups", fact.bottom_groups))
                              for index, group in enumerate(groups)]
            item["budgetComparisons"] = []
            for comparison in comparisons:
                if comparison["actualFactId"] != fact.fact_id:
                    continue
                references = {}
                for field, unit in (("difference", comparison["unit"]), ("percentage", "%")):
                    token = f"{{{{value:{fact.fact_id}:budgetComparison.{comparison['budgetFactId']}.{comparison['period']}.{field}:{unit or ''}}}}}"
                    references[field] = token if token in catalog and catalog[token] != "数值待核实" else None
                item["budgetComparisons"].append({
                    "budgetFactId": comparison["budgetFactId"], "period": comparison["period"],
                    "numeratorMetric": comparison["numeratorMetric"], "denominatorMetric": comparison["denominatorMetric"],
                    "references": references, "meaning": "同范围实际减预算、实际除预算×100%；百分数引用为空表示分母为零",
                })
            item["projectRatios"] = [{
                "budgetFactId": ratio["budgetFactId"],
                "numeratorMetric": ratio["numeratorMetric"],
                "reference": token,
                "meaning": "同快照合同或付款总额除以项目预算总额×100%；金额单位未知不影响比率。",
            } for ratio in project_ratios if ratio["numeratorFactId"] == fact.fact_id
            if (token := f"{{{{value:{fact.fact_id}:projectRatio.{ratio['budgetFactId']}.percentage:%}}}}") in catalog]
            guide.append(item)
        for fact in bundle.derived_metrics:
            if not fact.fact_id or fact.fact_id in seen:
                continue
            seen.add(fact.fact_id)
            references = {}
            for field, unit in (("numerator", fact.unit), ("denominator", fact.unit), ("difference", fact.unit), ("percentage", "%")):
                token = f"{{{{value:{fact.fact_id}:{field}:{unit or ''}}}}}"
                references[field] = token if token in catalog and catalog[token] != "数值待核实" else None
            guide.append({
                "factId": fact.fact_id, "analysisId": bundle.analysis_id, "metric": fact.code,
                "kind": fact.kind, "periodRole": fact.period_role,
                "periodGranularity": fact.period_granularity,
                "periodStart": fact.period_start, "periodEnd": fact.period_end,
                "numeratorMetric": fact.numerator_metric, "denominatorMetric": fact.denominator_metric,
                "references": references,
                "meaning": "分母为零时不可计算；分子为零且分母非零时为0%。仅使用已登记的比率期间，不扩展为月度比率",
            })
        for fact in bundle.comparisons:
            if not fact.fact_id or fact.fact_id in seen:
                continue
            seen.add(fact.fact_id)
            references = {}
            for field in ("currentTotal", "baselineTotal", "change", "changeRate"):
                unit = "%" if field == "changeRate" else (fact.unit or "")
                token = f"{{{{value:{fact.fact_id}:{field}:{unit}}}}}"
                references[field] = token if token in catalog and catalog[token] != "数值待核实" else None
            guide.append({
                "factId": fact.fact_id, "analysisId": bundle.analysis_id, "kind": "comparison",
                "comparisonType": {"yoy": "同比", "mom": "环比"}[fact.comparison_type],
                "periodGranularity": fact.period_granularity,
                "metric": getattr(fact, "display_name", None) or (field_definitions or {}).get(fact.field, fact.field), "unit": fact.unit,
                "periodStart": fact.period_start, "periodEnd": fact.period_end,
                "baselinePeriodStart": fact.baseline_period_start, "baselinePeriodEnd": fact.baseline_period_end,
                "baselineScale": fact.baseline_scale,
                "references": references,
                "meaning": "本期与基期取同一连续窗口的合计后比较；periodStart 与 periodEnd 跨多个月时是累计窗口，"
                           "正文须写明该窗口，不能写成单月变化；同比与环比不可混用",
            })
    return guide


# 占位渲染为带单位的显示值；模型常在占位后再写一遍单位（“{{…:亿元}}亿元”“{{…:%}}%”），
# 渲染后成为“1.37亿元亿元”“654.32万元亿元”“5.03%%”。显示值已带单位时，紧随其后的
# 同一量纲单位去掉；显示值不带单位（单位待核实）或量纲不同的不动。
_UNIT_FAMILIES = (("亿元", "万元", "元"), ("万人次", "人次"), (PERCENT_POINT, "百分点", "%"), ("‰",), ("床日",))
_TRAILING_UNIT = "|".join(sorted({unit for family in _UNIT_FAMILIES for unit in family}, key=len, reverse=True))
_VALUE_TOKEN_WITH_UNIT = re.compile(
    rf"(?P<token>\{{\{{value:[^{{}}\r\n]+\}}\}})(?P<unit>[ \t]*(?:{_TRAILING_UNIT}))?"
)


def _unit_family(unit: str) -> tuple[str, ...] | None:
    return next((family for family in _UNIT_FAMILIES if unit in family), None)


def render_frozen_numbers(markdown: str, catalog: dict[str, str], *, annotate=None) -> str:
    def replace(match: re.Match[str]) -> str:
        text = catalog.get(match["token"])
        written = match["unit"] or ""
        if text is None:
            logger.warning("report_number_reference_unavailable token={}", match["token"])
            return (annotate(match["token"], "数值待核实") if annotate else "数值待核实") + written
        shown = re.search(rf"(?:{_TRAILING_UNIT})$", text)
        if annotate:
            text = annotate(match["token"], text)
        if written and shown and _unit_family(shown[0]) == _unit_family(written.strip()):
            logger.warning("report_duplicate_unit_removed token={} unit={}", match["token"], written.strip())
            return text
        return text + written

    rendered = _VALUE_TOKEN_WITH_UNIT.sub(replace, markdown)
    for warning in money_text_warnings(rendered):
        logger.warning("report_number_conversion_warning message={}", warning)
    return rendered


def supplemental_number_values(contents: Iterable[str]) -> dict[str, set[Decimal]]:
    """只登记补证列元数据声明的数值及单位，不从数字大小猜测用途。"""
    known: dict[str, set[Decimal]] = {}
    for content in contents:
        try:
            document = json.loads(content)
        except (TypeError, ValueError):
            continue
        if not isinstance(document, dict):
            continue
        if document.get("schema") == "chart-input/v1":
            pending = [document]
        elif isinstance(document.get("findings"), list):
            pending = list(document["findings"])
        else:
            continue
        while pending:
            finding = pending.pop()
            if isinstance(finding, list):
                pending.extend(finding)
                continue
            if not isinstance(finding, dict):
                continue
            columns, rows, metadata = (finding.get(key) for key in ("columns", "rows", "columnMeta"))
            if not isinstance(columns, list) or not isinstance(rows, list) or not isinstance(metadata, dict):
                pending.extend(value for key, value in finding.items()
                               if key not in {"columns", "rows", "columnMeta"}
                               and isinstance(value, (dict, list)))
                continue
            for index, column in enumerate(columns):
                meta = metadata.get(column) if isinstance(column, str) else None
                if not isinstance(meta, dict):
                    continue
                unit = meta.get("unit")
                if not isinstance(unit, str) or unit not in {*_MONEY_UNITS, "人次", "万人次", "床日", "%", "‰"}:
                    continue
                if unit == "%" and meta.get("isPercent") is not True:
                    continue
                for row in rows:
                    if not isinstance(row, list) or len(row) != len(columns):
                        continue
                    value = row[index]
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        continue
                    number = Decimal(str(value))
                    if not number.is_finite():
                        continue
                    known.setdefault(unit, set()).add(number)
                    if (scales := _unit_scales(unit)) is not None:
                        for target, scale in scales.items():
                            known.setdefault(target, set()).add(number * scales[unit] / scale)
    return known


_DERIVED_ROW_LIMIT = 30
_CHINESE_COUNTS = "一两二三四五六七八九十"


def _operand_names(left: str, right: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """两个操作数在正文中的可接受写法：全称，或去掉二者共同前后缀后的区分部分
    （“门诊人次”与“不含体检&急诊门诊人次”写作“含与不含体检&急诊”）。"""
    prefix = len(os.path.commonprefix((left, right)))
    suffix = len(os.path.commonprefix((left[::-1], right[::-1])))

    def names(label: str) -> tuple[str, ...]:
        core = label[prefix:len(label) - suffix] if prefix + suffix < len(label) else ""
        return (label, core) if len(core) >= 2 else (label,)

    return names(left), names(right)


class DerivedNumbers:
    """服务端补算的派生数值及其操作数名称：正文须在同一段写出参与计算的对象才认可。

    只登记数值会让“A比B多60元”因 60 恰好等于 A−C 而通过；因此每个差额、合计都带上
    操作数的行名、列名或指标名，核对时要求这些名称出现在数字所在段落。
    """

    def __init__(self) -> None:
        self._values: dict[str, list[tuple[Decimal, tuple[tuple[str, ...], ...], int | None]]] = {}
        self._sorted: dict[str, list[Decimal]] = {}

    def add(self, unit: str, number: Decimal, operands: tuple[tuple[str, ...], ...], top: int | None = None) -> None:
        if not operands or any(not names for names in operands):
            return
        targets = [(unit, Decimal(1))]
        if (scales := _unit_scales(unit)) is not None:
            targets = [(target, scales[unit] / scale) for target, scale in scales.items()]
        elif unit == "人次":
            targets.append(("万人次", Decimal("0.0001")))
        for target, factor in targets:
            for value in {number, -number}:
                self._values.setdefault(target, []).append((value * factor, operands, top))
        self._sorted.clear()

    def supports(self, number: Decimal, unit: str, quantum: Decimal, context: str) -> bool:
        entries = self._values.get(unit)
        if not entries:
            return False
        if unit not in self._sorted:
            entries.sort(key=lambda entry: entry[0])
            self._sorted[unit] = [entry[0] for entry in entries]
        keys = self._sorted[unit]
        index = bisect.bisect_left(keys, number - quantum)
        while index < len(keys) and keys[index] <= number + quantum:
            value, operands, top = entries[index]
            index += 1
            if value.quantize(quantum, rounding=ROUND_HALF_UP) != number:
                continue
            if all(any(name in context for name in names) for names in operands):
                return True
            if top is not None and re.search(rf"前(?:{top}|{_CHINESE_COUNTS[top - 1] if top <= 10 else '_'})", context):
                return True
        return False


def _derive_from_table(derived: DerivedNumbers, labels: list[str | None],
                       columns: Mapping[str, tuple[str, list[Decimal]]]) -> None:
    """同一张表内补算：列内两行差额与降序前 N 项合计，同单位两列的逐行差额与合计差额。"""
    for unit, numbers in columns.values():
        if not 1 < len(numbers) <= _DERIVED_ROW_LIMIT:
            continue
        # 两个百分数之差是百分点，不是百分数；占比列只补算降序前 N 项合计。
        if unit != "%":
            for position, (left_label, left) in enumerate(zip(labels, numbers, strict=True)):
                for right_label, right in zip(labels[position + 1:], numbers[position + 1:], strict=True):
                    if left_label and right_label:
                        derived.add(unit, left - right, _operand_names(left_label, right_label))
        ranked = sorted(zip(numbers, labels, strict=True), key=lambda item: item[0], reverse=True)
        running = Decimal(0)
        for count, (number, label) in enumerate(ranked[:-1], start=1):
            running += number
            members = tuple((item[1],) for item in ranked[:count] if item[1])
            if count > 1 and len(members) == count:
                derived.add(unit, running, members, top=count)
    items = list(columns.items())
    for position, (left_name, (unit, left)) in enumerate(items):
        for right_name, (right_unit, right) in items[position + 1:]:
            if unit == "%" or right_unit != unit or len(left) > _DERIVED_ROW_LIMIT:
                continue
            operands = _operand_names(left_name, right_name)
            for label, a, b in zip(labels, left, right, strict=True):
                if label:
                    derived.add(unit, a - b, ((label,), *operands))
            derived.add(unit, sum(left) - sum(right), operands)


def _short_name(fact: Any) -> str | None:
    name = fact.display_name or ""
    return re.split(r"[，,；;]", name, maxsplit=1)[0].strip() or None


def derived_number_values(contents: Iterable[str]) -> DerivedNumbers:
    """服务端补算模型常写的两数之差与前 N 项合计，供正文核对使用，不进入模型可见目录。

    只在同一张补证表、同一分析的同口径事实内组合（同单位、同期间），不跨表或跨分析凑数：
    “门诊人次相差424,831人次”“总部与北部院区合计占比93.05%”“1月成本高于收入3.02亿元”。
    """
    contents = tuple(contents)
    derived = DerivedNumbers()
    for content in contents:
        try:
            document = json.loads(content)
        except (TypeError, ValueError):
            continue
        pending = [document] if isinstance(document, (dict, list)) else []
        while pending:
            finding = pending.pop()
            if isinstance(finding, list):
                pending.extend(finding)
                continue
            if not isinstance(finding, dict):
                continue
            columns, rows, metadata = (finding.get(key) for key in ("columns", "rows", "columnMeta"))
            if not isinstance(columns, list) or not isinstance(rows, list) or not isinstance(metadata, dict):
                pending.extend(value for value in finding.values() if isinstance(value, (dict, list)))
                continue
            rows = [row for row in rows if isinstance(row, list) and len(row) == len(columns)]
            labels = [next((cell.strip() for cell in row if isinstance(cell, str) and cell.strip()), None)
                      for row in rows]
            table: dict[str, tuple[str, list[Decimal]]] = {}
            for index, column in enumerate(columns):
                meta = metadata.get(column) if isinstance(column, str) else None
                unit = meta.get("unit") if isinstance(meta, dict) else None
                if (not isinstance(unit, str) or unit not in {*_MONEY_UNITS, "人次", "床日", "%"}
                        or unit == "%" and meta.get("isPercent") is not True):
                    continue
                numbers = [Decimal(str(row[index])) for row in rows
                           if isinstance(row[index], (int, float)) and not isinstance(row[index], bool)
                           and math.isfinite(row[index])]
                if rows and len(numbers) == len(rows):
                    table[column] = (unit, numbers)
            _derive_from_table(derived, labels, table)
    for bundle in frozen_fact_bundles(contents):
        metrics = [fact for fact in bundle.metrics if fact.unit in {*_MONEY_UNITS, "人次", "床日"} and _short_name(fact)]
        for position, left in enumerate(metrics):
            for right in metrics[position + 1:]:
                if (left.unit, left.period_start, left.period_end) != (right.unit, right.period_start, right.period_end):
                    continue
                operands = _operand_names(_short_name(left), _short_name(right))
                derived.add(left.unit, Decimal(str(left.total)) - Decimal(str(right.total)), operands)
                if [item.period for item in left.period_values] != [item.period for item in right.period_values]:
                    continue
                for a, b in zip(left.period_values, right.period_values, strict=True):
                    month = _canonical_month_label(a.period)
                    if month:
                        derived.add(left.unit, Decimal(str(a.value)) - Decimal(str(b.value)),
                                    (*operands, (f"{int(month[5:7])}月",)))
    return derived


def _paragraph_at(markdown: str, index: int) -> str:
    start = markdown.rfind("\n\n", 0, index)
    end = markdown.find("\n\n", index)
    return markdown[start + 2 if start >= 0 else 0:end if end >= 0 else len(markdown)]


def registered_decline_magnitude(
    number: Decimal, unit: str, candidates: Iterable[Decimal], *, prefix: str, quantum: Decimal,
) -> bool:
    """负的冻结值（变化率、变化额）可表述为“下降/减少”后接正幅度；不能据此豁免增长或占比。

    符号规范化会把“减少-654.32万元”改写为“减少654.32万元”，金额、人次与百分数一样
    必须按此认定为已登记数值，否则正确正文会被替换为待核实。
    """
    if number <= 0 or not re.search(
        rf"(?:{'|'.join(FALLING_WORDS)})(?:了|约|为|达)?\s*$", prefix,
    ):
        return False
    return any(value < 0 and (-value).quantize(quantum, rounding=ROUND_HALF_UP) == number
               for value in candidates)




def normalize_signed_wording(markdown: str) -> str:
    """按冻结值的符号改写方向词：负值不能跟“增长”，也不能与“下降”构成双重否定。

    冻结值决定方向，改写只调整措辞与负号，不改动数值本身。
    """

    def replace(match: re.Match[str]) -> str:
        if describes_rate_level(match.string[:match.start()]):
            return match[0]
        verb = match["verb"]
        falling = RISING_TO_FALLING.get(verb, verb)
        logger.warning("report_signed_wording_normalized verb={} value={}", verb, match["value"])
        return f"{falling}{match['filler'] or ''}{match['space']}{match['value']}"

    markdown = re.sub(
        rf"(?P<verb>{DIRECTION_WORD_PATTERN})"
        r"(?P<filler>了|约|为|达|幅度为)?(?P<space>\s*)-\s*(?P<value>\d[\d,]*(?:\.\d+)?)",
        replace,
        markdown,
    )

    # “实际较预算少-4.34万人次；2月少-6.37万人次”：比较句里的“多/少”同样不能再带负号。
    # 单字不进方向词表，以免“至少”“最多”等被改写。
    def replace_comparative(match: re.Match[str]) -> str:
        logger.warning("report_signed_wording_normalized verb={} value={}", match["verb"], match["value"])
        return f"少{match['space']}{match['value']}"

    return re.sub(
        r"(?<![至最不多少])(?P<verb>多|少)(?P<space>\s*)-\s*(?P<value>\d[\d,]*(?:\.\d+)?)",
        replace_comparative,
        markdown,
    )


# 只有比较事实的变化额/变化率带方向语义；合计、均值等前面的“下降至”不属于此类。
_DIRECTED_FIELDS = frozenset({"change", "changeRate"})
DIRECTED_PLACEHOLDER = re.compile(
    "(?P<verb>" + "|".join(FALLING_WORDS) + ")"
    r"(?P<filler>了|约|为|达|幅度为)?(?P<space>\s*)(?P<token>\{\{value:[^{}\r\n]+\}\})"
)


def positive_directed_placeholders(contents: Iterable[str]) -> dict[str, Decimal]:
    """变化额/变化率占位中登记值确定为正的引用（同一引用出现正负冲突时不计）。"""
    signs: dict[str, set[bool]] = {}
    values: dict[str, Decimal] = {}
    for token, value, _unit, _target in _frozen_number_entries(contents):
        parts = token.removeprefix("{{value:").removesuffix("}}").split(":")
        directed = parts[1] in _DIRECTED_FIELDS if len(parts) == 3 else False
        # 预算比较的差额是“实际减预算”，与变化额同样带增减方向。
        directed = directed or (
            len(parts) == 3 and parts[1].startswith("budgetComparison.") and parts[1].endswith(".difference")
        )
        if not directed or value is None:
            continue
        number = Decimal(str(value))
        if number == 0:
            continue
        signs.setdefault(token, set()).add(number > 0)
        values[token] = number
    return {token: values[token] for token, kinds in signs.items() if kinds == {True}}


def align_placeholder_direction(markdown: str, contents: Iterable[str]) -> str:
    """“下降/减少”后接登记为正的变化额/变化率时改为“增长/增加”。

    冻结值决定方向；负值配“增长”由 normalize_signed_wording 在渲染后处理，这里补齐
    正值配下降词的一侧。只改动作词，不改数值引用。
    """
    positive = positive_directed_placeholders(contents)
    if not positive:
        return markdown

    def replace(match: re.Match[str]) -> str:
        if match["token"] not in positive or describes_rate_level(match.string[:match.start()]):
            return match[0]
        rising = FALLING_TO_RISING[match["verb"]]
        logger.warning("report_direction_wording_aligned verb={} token={}", match["verb"], match["token"])
        return f"{rising}{match['filler'] or ''}{match['space']}{match['token']}"

    return DIRECTED_PLACEHOLDER.sub(replace, markdown)


def _display_precision(number_text: str) -> str:
    """超过两位小数的带单位数值按数值目录的显示精度（两位小数）舍入。

    “5.0332%”“1.2345678亿元”按书写精度核对可通过，但原样发布难以阅读；非零值舍入为
    零时保留原文，避免把很小的数写成 0.00。
    """
    if "." not in number_text or len(number_text.split(".", 1)[1]) <= 2:
        return number_text
    number = Decimal(number_text.replace(",", ""))
    rounded = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded == 0:
        return number_text
    logger.warning("report_number_precision_rounded value={}", number_text)
    return f"{rounded:,f}" if "," in number_text else f"{rounded:f}"


# “35.3万人”“353,000人”：人数写法；“人次”“人均”“人员”“人口”不在此列。
PERSON_COUNT = re.compile(
    r"(?<![\d.,])(?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?P<scale>万)?人(?!次|均|员|口|民)"
)
# “是上年同期的1.05倍”“增长2倍”：倍数只能由已登记的比较或比率得出。
# “3倍标准差”“1.5倍四分位距”是统计阈值，不是事实之间的倍数。
MULTIPLE_NUMBER = re.compile(r"(?<![\d.,+-])(?P<number>[+-]?\d+(?:\.\d+)?)\s*倍(?!数|标准差|四分位|方差|IQR)")


# “同比增长11.00个百分点”：变化率写成了百分点。占比、比重、比例或“率”的变化本来就以百分点计，
# 这类分句不改写。
RATE_AS_PERCENT_POINT = re.compile(r"(?<![\d.,])(?P<number>\d+(?:\.\d+)?)\s*个?百分点")
_PERCENT_POINT_SUBJECT = re.compile(r"占比|比重|比例|构成|率|增速|增幅|降幅|涨幅|跌幅")


def registered_change_rates(contents: Iterable[str]) -> set[Decimal]:
    """已登记的变化率幅度：比较事实的同比/环比变化率与相邻两月的变化率。"""
    return {abs(Decimal(str(value))) for token, value, _unit, _target in _frozen_number_entries(contents)
            if value is not None and token[2:-2].split(":")[2] == "changeRate"
            or value is not None and token[2:-2].split(":")[2].startswith("periodChangeRates.")}


def registered_group_shares(contents: Iterable[str]) -> set[Decimal]:
    """服务端按分组值与合计登记的分组占比（只供核对）。"""
    return {Decimal(str(value)) for token, value, _unit, _target in _frozen_number_entries(contents)
            if value is not None and token[2:-2].split(":")[2].startswith("groupShares.")}


def percent_point_written_for_rate(
    match: re.Match[str], text: str, rates: set[Decimal], points: Iterable[Decimal], percents: Sequence[Decimal],
) -> bool:
    """“个百分点”的数值只对得上登记变化率、对不上百分点差值且分句不是占比/比率类时返回 True。"""
    clause = re.split(r"[。；，\n]", text[:match.start()])[-1]
    if _PERCENT_POINT_SUBJECT.search(clause):
        return False
    number = Decimal(match["number"])
    quantum = Decimal(1).scaleb(-(len(match["number"].split(".")[1]) if "." in match["number"] else 0))

    def shown(values: Iterable[Decimal]) -> bool:
        return any(abs(value).quantize(quantum, rounding=ROUND_HALF_UP) == number for value in values)

    if not shown(rates) or shown(points):
        return False
    # 两项登记百分数（占比、完成率等水平值）之差同样是有依据的百分点；变化率之间的差只在
    # “增速/增幅”语境下才是百分点，已在上方跳过。候选过多时不比较，按变化率处理。
    ordered = sorted(value for value in percents if abs(value) not in rates)
    return not (len(ordered) <= 400 and shown(
        right - left for index, left in enumerate(ordered) for right in ordered[index + 1:]
    ))


def registered_multiples(
    contents: Iterable[str], catalog: dict[str, str],
) -> dict[str, set[Decimal]]:
    """分开登记水平倍数与增减幅度，保留符号并排除有冲突的操作数。"""
    totals: dict[tuple[str, str | None], dict[str, Decimal]] = {}
    multiples: dict[str, set[Decimal]] = {"ratio": set(), "increase": set(), "decrease": set()}
    for token, value, unit, target in _frozen_number_entries(contents):
        if value is None or (target or unit) != unit or catalog.get(token) == "数值待核实":
            continue
        fact_id, field = token[2:-2].split(":")[1:3]
        number = Decimal(str(value))
        if field in {"currentTotal", "baselineTotal"}:
            totals.setdefault((fact_id, unit), {})[field] = number
        elif field == "changeRate":
            if number >= 0:
                multiples["increase"].add(number / 100)
            if number <= 0:
                multiples["decrease"].add(-number / 100)
        elif field == "percentage" or field.endswith(".percentage"):
            multiples["ratio"].add(number / 100)
    for pair in totals.values():
        if pair.get("baselineTotal") and "currentTotal" in pair:
            multiples["ratio"].add(pair["currentTotal"] / pair["baselineTotal"])
    return multiples


_MULTIPLE_DIRECTION = re.compile(rf"(?P<verb>{DIRECTION_WORD_PATTERN})(?:了)?\s*(?:约|为|达)?\s*$")


def registered_multiple_matches(match: re.Match[str], multiples: dict[str, set[Decimal]]) -> bool:
    """“增长 X 倍”核对变化率；“增长至/是同期的 X 倍”核对水平比值。"""
    direction = _MULTIPLE_DIRECTION.search(match.string[max(0, match.start() - 40):match.start()])
    kind = "ratio"
    if direction:
        kind = "increase" if direction["verb"] in RISING_WORDS else "decrease"
    number = Decimal(match["number"])
    digits = len(match["number"].split(".", 1)[1]) if "." in match["number"] else 0
    quantum = Decimal(1).scaleb(-digits)
    return any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in multiples[kind])


_TABLE_SEPARATOR_ROW = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
_TABLE_HEADER_UNIT = re.compile(
    r"[（(]\s*(?:单位\s*[:：]\s*)?(亿元|万元|元|万人次|人次|床日|%|个百分点)\s*[）)]\s*$"
)
_BARE_CELL_NUMBER = re.compile(
    r"^\s*(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*$"
)


def _table_cells(line: str) -> list[tuple[int, int]]:
    """管道表一行的单元格区间（不含分隔竖线），忽略转义的“\\|”。"""
    pipes = [index for index, character in enumerate(line)
             if character == "|" and (index == 0 or line[index - 1] != "\\")]
    if not pipes:
        return []
    cells = [(pipes[index] + 1, pipes[index + 1]) for index in range(len(pipes) - 1)]
    if line[:pipes[0]].strip():
        cells.insert(0, (0, pipes[0]))
    if line[pipes[-1] + 1:].strip():
        cells.append((pipes[-1] + 1, len(line)))
    return cells


def table_unit_cells(markdown: str) -> list[tuple[int, int, str, str]]:
    """管道表中表头带单位列（“金额（万元）”“同比（%）”）的裸数字单元格。

    返回 (起点, 终点, 数字, 单位)，位置是数字在 markdown 中的区间；无单位列与已带单位的
    单元格不在此列，后者由正文数值核对处理。
    """
    lines = markdown.split("\n")
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)
    found: list[tuple[int, int, str, str]] = []
    index = 0
    while index < len(lines) - 1:
        # GFM 表格可以省略首尾竖线；分隔行也须含竖线，避免把“---”分隔线或 setext 标题当表格。
        if not ("|" in lines[index] and "|" in lines[index + 1]
                and _TABLE_SEPARATOR_ROW.match(lines[index + 1])):
            index += 1
            continue
        header = lines[index]
        units = []
        for start, end in _table_cells(header):
            match = _TABLE_HEADER_UNIT.search(header[start:end].replace("**", "").strip())
            units.append(match[1] if match else None)
        row = index + 2
        while row < len(lines) and "|" in lines[row] and lines[row].strip():
            for column, (start, end) in enumerate(_table_cells(lines[row])):
                if column >= len(units) or units[column] is None:
                    continue
                match = _BARE_CELL_NUMBER.match(lines[row][start:end])
                if match is not None:
                    found.append((offsets[row] + start + match.start("number"),
                                  offsets[row] + start + match.end("number"), match["number"], units[column]))
            row += 1
        index = row
    return found


# “超过3,700万元”“近4,000万元”：以整数界限描述登记值。界限必须是某个登记值按 1～2 位有效数字
# 向下取整（超过/逾/突破…）或向上取整（不足/近/接近…）的结果，避免任意登记值碰巧落在宽松区间内。
_LOWER_BOUND = re.compile(r"(?:超过|逾|突破|高于|多于|大于)\s*$")
_UPPER_BOUND = re.compile(r"(?:不足|低于|少于|小于|近|接近|将近|不到)\s*$")


def bounded_by_registered(number: Decimal, number_text: str, values: Iterable[Decimal], *, prefix: str) -> bool:
    """整数界限是否为某个登记值按 1～2 位有效数字朝界限方向取整的结果。"""
    if "." in number_text or number <= 0:
        return False
    above = _LOWER_BOUND.search(prefix) is not None
    if not above and _UPPER_BOUND.search(prefix) is None:
        return False
    for value in values:
        if value <= 0 or (value <= number if above else value >= number):
            continue
        for significant in (1, 2):
            step = Decimal(1).scaleb(value.adjusted() - significant + 1)
            bound = (value / step).to_integral_value(rounding=ROUND_FLOOR if above else ROUND_CEILING) * step
            if bound == number:
                return True
    return False


def replace_unregistered_numbers(markdown: str, contents: Iterable[str], *, missing=None) -> str:
    """把没有冻结依据的带单位数字替换为待核实，避免手算结果落盘。"""

    contents = tuple(contents)
    catalog = frozen_number_catalog(contents)
    known = supplemental_number_values(contents)
    derived = derived_number_values(contents)
    # 没有可解析的冻结事实时，服务端无法判断正文数字是否为派生值；
    # 保留原文，避免把仅含原始证据的旧格式内容全部改成“待核实”。
    if not catalog and not known:
        return markdown
    for unit, values in frozen_number_values(contents, catalog).items():
        known.setdefault(unit, set()).update(values)

    def verify(number_text: str, unit: str, prefix: str, context: str) -> tuple[str, str]:
        """返回 (结论, 数字)：registered 按显示精度保留，percent_point 改写为百分点，missing 替换。"""
        number = Decimal(number_text.replace(",", ""))
        digits = len(number_text.split(".", 1)[1]) if "." in number_text else 0
        quantum = Decimal(1).scaleb(-digits)
        candidates = known.get(unit, ())
        if (any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in candidates)
                or registered_decline_magnitude(number, unit, candidates, prefix=prefix, quantum=quantum)
                or bounded_by_registered(number, number_text, candidates, prefix=prefix)
                or derived.supports(number, unit, quantum, context)):
            return "registered", _display_precision(number_text)
        # 百分数指标的变化写成“提高2.10%”：数值只对得上登记的百分点差值时改写单位，
        # 避免把两项百分数之差读成相对变化率。
        points = known.get(PERCENT_POINT, ()) if unit == "%" else ()
        if points and (any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in points)
                       or registered_decline_magnitude(number, PERCENT_POINT, points,
                                                       prefix=prefix, quantum=quantum)):
            logger.warning("report_percent_point_unit_corrected value={}{}", number_text, unit)
            return "percent_point", _display_precision(number_text)
        logger.warning("report_unregistered_number_replaced value={}{}", number_text, unit)
        return "missing", number_text

    missing = missing or (lambda: "待核实")

    # 模型自写表格把单位写在表头（“金额（万元）”），单元格只有数字：按表头单位同样核对。
    for start, end, number_text, unit in reversed(table_unit_cells(markdown)):
        verdict, written = verify(number_text, unit, "", _paragraph_at(markdown, start))
        cell = (written if verdict == "registered" else f"{written}{PERCENT_POINT}"
                if verdict == "percent_point" else missing())
        markdown = markdown[:start] + cell + markdown[end:]

    def replace(match: re.Match[str]) -> str:
        verdict, written = verify(match["number"], match["unit"],
                                  markdown[max(0, match.start() - 12):match.start()],
                                  _paragraph_at(markdown, match.start()))
        if verdict == "registered":
            return written + match[0][len(match["number"]):]
        return f"{written}{PERCENT_POINT}" if verdict == "percent_point" else missing()

    replaced = re.sub(
        r"(?<![\d.,])(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?P<unit>亿元|万元|元|万人次|人次|床日|%)",
        replace,
        markdown,
    )

    def replace_bare(match: re.Match[str]) -> str:
        # “收入1.23亿”“门诊量35.3万”省略了单位：按亿元/万元/万人次的登记值核对；
        # 只对上一种单位时补全单位，对不上的手写数值同样替换为待核实。
        number = Decimal(match["number"].replace(",", ""))
        digits = len(match["number"].split(".", 1)[1]) if "." in match["number"] else 0
        quantum = Decimal(1).scaleb(-digits)
        targets = ("亿元",) if match["scale"] == "亿" else ("万元", "万人次")
        matched = [
            target for target in targets
            if any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in known.get(target, ()))
        ]
        if not matched:
            logger.warning("report_unregistered_number_replaced value={}", match[0])
            return missing()
        written = _display_precision(match["number"]) + match["scale"]
        return written + matched[0][1:] if len(matched) == 1 else written

    def replace_persons(match: re.Match[str]) -> str:
        # “门诊量35.3万人”：人次（就诊次数）写成了人数。数值只对得上登记的人次时改回人次；
        # 对不上的“人”可能是职工、床位等其他人数，不在此替换。
        number = Decimal(match["number"].replace(",", ""))
        digits = len(match["number"].split(".", 1)[1]) if "." in match["number"] else 0
        quantum = Decimal(1).scaleb(-digits)
        visit_unit = "万人次" if match["scale"] else "人次"
        if (not any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in known.get(visit_unit, ()))
                or any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in known.get("人", ()))):
            return match[0]
        logger.warning("report_visit_unit_corrected value={}", match[0])
        return f"{_display_precision(match['number'])}{match['scale'] or ''}人次"

    replaced = PERSON_COUNT.sub(replace_persons, replaced)
    rates = registered_change_rates(contents)
    # 分组占比两两相减的组合很多，取整后容易凑上变化率；判断“变化率误写为百分点”时不用它们作依据。
    shares = registered_group_shares(contents)
    rate_level_percents = tuple(value for value in known.get("%", ()) if value not in shares)

    def replace_rate_points(match: re.Match[str]) -> str:
        if not percent_point_written_for_rate(match, replaced, rates, known.get(PERCENT_POINT, ()), rate_level_percents):
            return match[0]
        logger.warning("report_change_rate_unit_corrected value={}", match[0])
        return f"{_display_precision(match['number'])}%"

    replaced = RATE_AS_PERCENT_POINT.sub(replace_rate_points, replaced) if rates else replaced
    multiples = registered_multiples(contents, catalog)

    def replace_multiple(match: re.Match[str]) -> str:
        if registered_multiple_matches(match, multiples):
            return _display_precision(match["number"]) + match[0][len(match["number"]):]
        logger.warning("report_unregistered_multiple_replaced value={}", match[0])
        return missing()

    return MULTIPLE_NUMBER.sub(replace_multiple, BARE_SCALED_NUMBER.sub(replace_bare, replaced))


# 省略单位的“X亿”“X万”：只在其后是标点、空白或段尾时认定为完整数量，
# “2万多名”“上万”等后接汉字的写法不处理。
BARE_SCALED_NUMBER = re.compile(
    r"(?<![\d.,])(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?P<scale>亿|万)"
    r"(?=[，。；、,.;:：）)\]\s*]|$)"
)


def correct_period_extrema(markdown: str, bundles: Iterable[dict[str, Any] | str]) -> str:
    """对明确与冻结序列冲突的极值句做确定性改写，保留其余正文。"""

    normalized: list[dict[str, Any]] = []
    for bundle in bundles:
        if isinstance(bundle, dict):
            normalized.append(bundle)
            continue
        try:
            parsed = json.loads(bundle)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            normalized.append(parsed)
    # 章节 block 由模型撰写，不含 [[analysis:…]] 协议标记；与 review_content 一致，
    # 只有一个分析事实包时整段即其作用域，否则无标记正文无法归属，不做改写。
    analysis_bundles = [item for item in normalized
                        if item.get("metrics") and isinstance(item.get("analysisId"), str)]
    scope = ""
    if "[[analysis:" not in markdown and len(analysis_bundles) == 1:
        scope = f"[[analysis:{analysis_bundles[0]['analysisId']}]]"
    corrected = scope + markdown
    for bundle in normalized:
        # 告警按分析标记分段产生；改写也只能落在该分析的段落内，
        # 否则会改掉其他分析中同月份的正确陈述。
        for warning in period_extrema_warnings(corrected, [bundle]):
            match = re.search(r"(\d+)月被写为(最高|最低)，冻结月序列的\2月份为([^。]+)", warning)
            if match is None:
                continue
            wrong_month, kind, expected = match.groups()
            markers = list(re.finditer(r"\[\[analysis:([^\]]+)\]\]", corrected))
            for index, marker in enumerate(markers):
                if marker[1] != bundle.get("analysisId"):
                    continue
                end = markers[index + 1].start() if index + 1 < len(markers) else len(corrected)
                segment = _rewrite_extrema_sentence(
                    corrected[marker.end():end], int(wrong_month), kind, expected,
                    _series_year(bundle),
                )
                if segment is not None:
                    corrected = corrected[:marker.end()] + segment + corrected[end:]
                    logger.warning("report_period_extrema_corrected wrong_month={} expected_months={}",
                                   wrong_month, expected)
                    break
    return corrected[len(scope):]


_EXTREMA_WORDS = {"最高": "最高|峰值", "最低": "最低|低点"}
# 与 period_extrema_warnings 的豁免一致：分项比例、变化率和组织明细的极值不按全院月序列改写。
_EXTREMA_EXEMPT = re.compile(r"占比|比重|比例|环比|同比|增长率|降幅|增幅|组织明细|明细分组|分组组合")
_MONTH_RANGE = re.compile(r"(?<!\d)\d{1,2}月?\s*[–—~～至到-]\s*\d{1,2}月")
_EXTREMA_SUBJECT_SUFFIX = re.compile(
    r"(?:为|是|达到|达|处于|出现|创下|创|录得|位居|居|全年|年内|期内|期间|当期|单月|各月|月度|的|中|内)$"
)
_DISPLAYED_VALUE = (
    r"(?:\{\{value:[^{}\r\n]+\}\}"
    r"|[+-]?\d[\d,]*(?:\.\d+)?\s*(?:亿元|万元|元|万人次|人次|床日|%)?)"
)


def _validated_monthly_periods(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """极值复核与改写共用相同的月度事实校验，忽略异常补充记录。"""
    raw_metrics = bundle.get("metrics")
    if not isinstance(raw_metrics, (list, tuple)):
        return []
    metrics = [entry for entry in raw_metrics if isinstance(entry, Mapping)
               and isinstance(entry.get("periodRoles"), (list, tuple))
               and "current" in entry["periodRoles"]]
    if len(metrics) != 1 or metrics[0].get("periodGranularity") != "month":
        return []
    raw_periods = metrics[0].get("periodValues")
    if not isinstance(raw_periods, (list, tuple)) or not raw_periods:
        return []
    try:
        periods = [PeriodValue.model_validate(item).model_dump(mode="json") for item in raw_periods]
    except ValueError:
        return []
    if any(not Decimal(str(item["value"])).is_finite() for item in periods):
        return []
    labels = [str(item["period"]) for item in periods]
    if not _valid_month_labels(labels):
        return []
    periods = [{**item, "period": _canonical_month_label(item["period"])} for item in periods]
    labels = [item["period"] for item in periods]
    if len({label[:4] for label in labels}) != 1:
        return []
    if len({label[:7] for label in labels}) != len(periods):
        return []
    return periods


def _series_year(bundle: dict[str, Any]) -> str | None:
    periods = _validated_monthly_periods(bundle)
    return periods[0]["period"][:4] if periods else None


def _rewrite_extrema_sentence(
    segment: str, wrong_month: int, kind: str, expected: str, year: str | None,
) -> str | None:
    """只改写唯一一句与告警对应的极值陈述；无法唯一定位时保留原文，交由软告警复核。"""

    claim = re.compile(
        rf"(?<![\d–—~～至到-]){wrong_month}月(?P<between>(?:(?!\d{{1,2}}月)[^。；\n]){{0,60}}?)"
        rf"(?:{_EXTREMA_WORDS[kind]})(?:值|月份|水平|点)?"
    )
    candidates = []
    for sentence in re.finditer(r"[^。；\n]+", segment):
        years = set(re.findall(r"(?<!\d)(\d{4})年", sentence[0]))
        # 子期间范围的极值以范围内月份为准，改写会丢失范围语义；其他年份不属于该序列。
        if _MONTH_RANGE.search(sentence[0]) or (years and years != {year}):
            continue
        candidates.extend((sentence, found) for found in claim.finditer(sentence[0])
                          if not _EXTREMA_EXEMPT.search(found[0]))
    if len(candidates) != 1:
        return None
    sentence, found = candidates[0]
    before = sentence[0][:found.start()]
    if before.endswith(("在", "于")):
        before = before[:-1]
    # 保留月份与极值词之间的指标名（“2月金额为最高值”→“金额最高月份为…”）；
    # 夹带数值或分句时那是错误月份的数值，一并去掉。
    subject = found["between"].replace("**", "")
    while (stripped := _EXTREMA_SUBJECT_SUFFIX.sub("", subject)) != subject:
        subject = stripped
    if re.search(r"[\d，,、]|\{\{", subject):
        subject = ""
    after = sentence[0][found.end():]
    after = re.sub(rf"^\s*(?:（[^）]*）)?\s*(?:为|达|约|计|是)?\s*{_DISPLAYED_VALUE}", "", after)
    after = re.sub(rf"^[，,]\s*(?:为|达|约|计|金额为|数值为)\s*{_DISPLAYED_VALUE}", "", after)
    rewritten = f"{before}{subject}{kind}月份为{expected}{after}"
    if rewritten.count("**") % 2:
        rewritten = rewritten.replace("**", "")
    return segment[:sentence.start()] + rewritten + segment[sentence.end():]


def money_text_warnings(markdown: str) -> list[str]:
    """仅核对紧邻括号中的同一金额，不把正文中的不同指标强行比较。"""
    warnings: list[str] = []
    for match in _MONEY_PAIR.finditer(markdown.replace("**", "")):
        number = Decimal(match["large"].replace(",", ""))
        base = Decimal(match["base"].replace(",", ""))
        digits = len(match["large"].split(".", 1)[1]) if "." in match["large"] else 0
        rounded = (base / _MONEY_UNITS[match["unit"]]).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
        if rounded != number:
            warnings.append(f"金额单位换算不一致：{match[0]}，请核对原始元值。")
    return list(dict.fromkeys(warnings))


def period_extrema_warnings(markdown: str, bundles: Iterable[dict[str, Any]]) -> list[str]:
    """单一月度指标的明确极值、连续趋势与冻结月序列不符时，仅提示复核。"""
    warnings: list[str] = []
    markers = list(re.finditer(r"\[\[analysis:([^\]]+)\]\]", markdown))
    for bundle in bundles:
        periods = _validated_monthly_periods(bundle)
        if not periods:
            continue
        labels = [item["period"] for item in periods]
        monthly = {int(item["period"][5:7]): Decimal(str(item["value"])) for item in periods}
        for index, marker in enumerate(markers):
            if marker[1] != bundle.get("analysisId"):
                continue
            end = markers[index + 1].start() if index + 1 < len(markers) else len(markdown)
            text = markdown[marker.end():end].replace("**", "")
            pattern = r"(?<![\d–—~-])(?P<month>\d{1,2})月(?:(?!\d{1,2}月)[^。；\n]){0,60}?(?P<kind>最高|最低|峰值|低点)"
            # “低点：2月”与“2月为最低”使用相同的冻结极值判定。
            text = re.sub(r"(低点|峰值)[：:]\s*(\d{1,2})月", r"\2月为\1", text)
            # 后置月份只属于括号前的极值，不能被下一分句的极值词接走。
            text = re.sub(
                rf"(?P<kind>最高|最低|峰值|低点)(?:值)?\s*(?:为|是|[：:])?\s*"
                rf"{_DISPLAYED_VALUE}\s*[（(](?:出现在|出现于|在|于)(?P<month>\d{{1,2}})月[）)]",
                lambda m: f"{m['month']}月为{m['kind']}", text,
            )
            # 范围端点不是另一项月份断言；掩去“月”但保持字符位置，
            # 使“2月为1—10月最低”仍可匹配2月，范围则从原文取回。
            masked = re.sub(r"(?<!\d)\d{1,2}月?\s*[–—~～至到-]\s*\d{1,2}月",
                            lambda m: m[0].replace("月", "期"), text)
            # “11月较10月减少，为最低值”中的10月是比较基期，不是极值主语。
            masked = re.sub(r"(?:较|相比于?|相较于?|比)\s*\d{1,2}月",
                            lambda m: m[0].replace("月", "期"), masked)
            for match in re.finditer(pattern, masked):
                if (re.search(r"占比|比重|比例|环比|同比|增长率|降幅|增幅|组织明细|明细分组|分组组合", match[0])
                        or re.match(r"单项|单条", text[match.end():])):
                    # 分项比例、变化率或组织明细极值不能用全院原始月序列复核。
                    continue
                high = match["kind"] in {"最高", "峰值"}
                clause_start = max(text.rfind(separator, 0, match.start())
                                   for separator in ("。", "；", "\n")) + 1
                local = text[clause_start:match.end()]
                named_years = set(re.findall(r"(?<!\d)(\d{4})年", local))
                if named_years and named_years != {labels[0][:4]}:
                    continue
                ranges = list(re.finditer(r"(?<!\d)(\d{1,2})月?\s*[–—~～至到-]\s*(\d{1,2})月", local))
                selected = monthly
                if ranges:
                    start, stop = int(ranges[-1][1]), int(ranges[-1][2])
                    if start > stop or not all(month in monthly for month in range(start, stop + 1)):
                        continue
                    selected = {month: monthly[month] for month in range(start, stop + 1)}
                elif re.search(r"有数据(?:的)?月份", local):
                    # 未给明确范围时，零值不能据此判为无数据并排除。
                    continue
                extreme = (max if high else min)(selected.values())
                months = {month for month, value in selected.items() if value == extreme}
                if int(match["month"]) not in months:
                    label = "最高" if high else "最低"
                    expected = "、".join(f"{month}月" for month in sorted(months))
                    warnings.append(f"月度极值陈述需复核：{match['month']}月被写为{label}，冻结月序列的{label}月份为{expected}。")
            trend_pattern = r"(?<!\d)(\d{1,2})月?\s*[–—~～至到-]\s*(\d{1,2})月[^。；\n]{0,20}?连续(?:[一二三四五六七八九十\d]+个月)?(?:上升|增长|增加|回升|下降|减少|回落)"
            for match in re.finditer(trend_pattern, text):
                clause_start = max(text.rfind(separator, 0, match.start())
                                   for separator in ("。", "；", "\n")) + 1
                named_years = set(re.findall(r"(?<!\d)(\d{4})年", text[clause_start:match.end()]))
                if named_years and named_years != {labels[0][:4]}:
                    continue
                start, stop = int(match[1]), int(match[2])
                if start >= stop or not all(month in monthly for month in range(start, stop + 1)):
                    continue
                rising = not re.search(r"下降|减少|回落", match[0])
                inconsistent = [f"{month}月→{month + 1}月" for month in range(start, stop)
                                if (monthly[month + 1] <= monthly[month] if rising else monthly[month + 1] >= monthly[month])]
                if inconsistent:
                    warnings.append(f"连续趋势陈述需复核：{match[0]}，冻结月序列在{'、'.join(inconsistent)}不满足该趋势。")
    return list(dict.fromkeys(warnings))
