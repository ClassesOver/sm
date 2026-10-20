"""从冻结事实生成正文数值；模型只选择数值引用，不负责换算或千分位。"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
import os
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any

from loguru import logger

from ..hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
    PeriodValue,
    _parse_fact_period,
    _parse_period,
)
from ..units import MONEY_UNITS as _MONEY_UNITS
from ..units import REPORT_VALUE_UNIT_PATTERN, unit_conversion_scale
from ..units import unit_scales as _unit_scales
from .contracts_v1 import TableDerivationV1, TableOperandV1
from .fact_index import fact_binding_records, merge_binding_records
from .table_sources import table_semantics

# 增减方向词对照：自动纠正、正文复核与 claim 绑定共用同一份，避免各处漏掉不同写法
# （“跌幅-5%”“上涨-654万元”曾因词表不全原样发布）。
RISING_TO_FALLING = {
    "增长": "下降",
    "上升": "下降",
    "增加": "减少",
    "提高": "降低",
    "增幅": "降幅",
    "涨幅": "跌幅",
    "上涨": "下跌",
    "回升": "回落",
}
FALLING_TO_RISING = {
    "下降": "增长",
    "减少": "增加",
    "降低": "提高",
    "回落": "回升",
    "下滑": "上升",
    "降幅": "增幅",
    "减幅": "增幅",
    "跌幅": "涨幅",
    "下跌": "上涨",
    "缩减": "增加",
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


_SCALED_DISPLAY_UNITS = frozenset({"万元", "亿元", "万人次", "%", "‰", PERCENT_POINT})


def format_fact_value(value: Any, unit: str | None, display_unit: str | None = None) -> str:
    number = Decimal(str(value))
    target = display_unit or unit
    if target != unit and not (unit == "%" and target == PERCENT_POINT):
        scales = _unit_scales(unit)
        number = number * scales[unit] / scales[target]
    # 零值在万元、亿元、万人次下写成“0.00万人次”既别扭又像有零头，直接写 0。
    if number == 0 and target in {"万元", "亿元", "万人次"}:
        return "0" + target
    if target in _SCALED_DISPLAY_UNITS or number != number.to_integral_value():
        rounded = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        # 舍入为零的负数不能显示为“-0.00”。
        text = f"{abs(rounded) if rounded == 0 else rounded:,f}"
        # 百万以上元、人次合计的浮点尾差（20921671264.99973）舍入后是整数，不写“265.00元”；
        # 小额值保留“30.00元”，以区分与整数登记值冲突的未舍入值。
        if (
            target not in _SCALED_DISPLAY_UNITS
            and abs(rounded) >= 1_000_000
            and rounded == rounded.to_integral_value()
        ):
            text = f"{rounded:,.0f}"
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
        budgets = [
            fact
            for fact in bundle.metrics
            if fact.field == "budget_" + actual.field.removeprefix("actual_")
            and fact.dataset_id == actual.dataset_id
            and fact.dataset_sha256 == actual.dataset_sha256
            and fact.scope == actual.scope
            and fact.unit == actual.unit
            and fact.field_ref.rsplit(".", 1)[0] == actual.field_ref.rsplit(".", 1)[0]
            and fact.period_roles == actual.period_roles
        ]
        if len(budgets) != 1 or not budgets[0].fact_id:
            continue
        budget = budgets[0]
        if actual.period_aggregation != budget.period_aggregation:
            continue
        monthly = []
        for fact in (actual, budget):
            if (
                fact.aggregation != "sum"
                or fact.period_granularity != "month"
                or not 0 < len(fact.period_values) <= 12
            ):
                break
            if not _valid_month_labels(value.period for value in fact.period_values):
                break
            values = {
                _canonical_month_label(value.period): Decimal(str(value.value))
                for value in fact.period_values
            }
            if (
                len(values) != len(fact.period_values)
                or len({period[:4] for period in values}) != 1
            ):
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
                comparisons.append(
                    {
                        "actualFactId": actual.fact_id,
                        "budgetFactId": budget.fact_id,
                        "numeratorMetric": actual.field,
                        "denominatorMetric": budget.field,
                        "period": window,
                        "unit": actual.unit,
                        "difference": current - planned,
                        "percentage": current / planned * 100 if planned != 0 else None,
                    }
                )
    return comparisons


def project_ratio_values(bundle: DeterministicAnalysisBundle) -> list[dict[str, Any]]:
    """由同快照项目预算与合同/付款总额计算无量纲比例。"""
    ratios = []
    for numerator in bundle.metrics:
        if numerator.field not in {"contract_amount", "payment_amount"} or not numerator.fact_id:
            continue
        budgets = [
            budget
            for budget in bundle.metrics
            if budget.field == "budget_project_amount"
            and budget.fact_id
            and budget.aggregation == numerator.aggregation == "sum"
            and budget.dataset_id == numerator.dataset_id
            and budget.dataset_sha256 == numerator.dataset_sha256
            and budget.scope == numerator.scope
            and budget.unit == numerator.unit
            and budget.period_roles == numerator.period_roles
            and budget.period_start == numerator.period_start
            and budget.period_end == numerator.period_end
            and budget.field_ref.rsplit(".", 1)[0] == numerator.field_ref.rsplit(".", 1)[0]
        ]
        if len(budgets) != 1 or not budgets[0].total:
            continue
        ratios.append(
            {
                "numeratorFactId": numerator.fact_id,
                "budgetFactId": budgets[0].fact_id,
                "numeratorMetric": numerator.field,
                "percentage": Decimal(str(numerator.total)) / Decimal(str(budgets[0].total)) * 100,
            }
        )
    return ratios


_TOTAL_METRIC_MARKERS = ("合计", "总额", "总量")


def _is_total_metric(fact: Any) -> bool:
    return any(marker in (fact.display_name or fact.field) for marker in _TOTAL_METRIC_MARKERS)


def metric_share_values(bundle: DeterministicAnalysisBundle) -> list[dict[str, Any]]:
    """同快照、同范围、同期间的“部分占合计”构成占比：正文引用与核对共用同一来源。

    合计指标按显示名中的 合计/总额/总量 识别；仅当分母唯一、口径完全一致且
    部分值不超过合计时登记，避免把不同命名空间或不同口径的金额凑成占比。
    双方均为对齐的月度求和事实时，与 budgetComparisons 一致地逐月与累计窗口登记。
    """
    shares = []
    for part in bundle.metrics:
        if not part.fact_id or _is_total_metric(part) or part.negative_count:
            continue
        totals = [
            total
            for total in bundle.metrics
            if total.fact_id
            and total.fact_id != part.fact_id
            and _is_total_metric(total)
            and total.aggregation == part.aggregation == "sum"
            and total.dataset_id == part.dataset_id
            and total.dataset_sha256 == part.dataset_sha256
            and total.scope == part.scope
            and total.unit == part.unit
            and total.period_roles == part.period_roles
            and total.period_start == part.period_start
            and total.period_end == part.period_end
            and total.period_aggregation == part.period_aggregation
            and total.field_ref.rsplit(".", 1)[0] == part.field_ref.rsplit(".", 1)[0]
            and total.total > 0
            and not total.negative_count
            and 0 <= part.total <= total.total
        ]
        if len(totals) != 1:
            continue
        total = totals[0]

        def entry(period: str | None, numerator: Decimal, denominator: Decimal) -> dict[str, Any]:
            return {
                "partFactId": part.fact_id,
                "totalFactId": total.fact_id,
                "partMetric": part.display_name or part.field,
                "totalMetric": total.display_name or total.field,
                "period": period,
                "percentage": numerator / denominator * 100,
            }

        shares.append(entry(None, Decimal(str(part.total)), Decimal(str(total.total))))
        monthly = []
        for fact in (part, total):
            if (
                fact.period_aggregation == "last"
                or fact.period_granularity != "month"
                or not 0 < len(fact.period_values) <= 12
                or not _valid_month_labels(value.period for value in fact.period_values)
            ):
                monthly = []
                break
            values = {
                _canonical_month_label(value.period): Decimal(str(value.value))
                for value in fact.period_values
            }
            if len(values) != len(fact.period_values):
                monthly = []
                break
            monthly.append(values)
        if not monthly or monthly[0].keys() != monthly[1].keys():
            continue
        periods = sorted(monthly[0])

        def month_index(period: str) -> int:
            return int(period[:4]) * 12 + int(period[5:7])

        if any(
            month_index(right) - month_index(left) != 1 for left, right in zip(periods, periods[1:])
        ):
            continue
        part_running = total_running = Decimal(0)
        for index, period in enumerate(periods):
            part_running += monthly[0][period]
            total_running += monthly[1][period]
            windows = [(period, monthly[0][period], monthly[1][period])]
            if index:
                windows.append((f"{periods[0]}..{period}", part_running, total_running))
            for window, numerator, denominator in windows:
                if denominator > 0 and 0 <= numerator <= denominator:
                    shares.append(entry(window, numerator, denominator))
    return shares


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
    counts = Counter(item["group"] for item in groups)
    return [
        (index, item)
        for index, item in enumerate(groups)
        if item.get("groupValues") or counts[item["group"]] == 1
    ]


def _derived_units_comparable(
    entry: Mapping[str, Any], metrics: Sequence[Mapping[str, Any]]
) -> bool:
    """旧快照可能已登记异量纲差额；有完整输入依据时不能重新认可。"""
    inputs = entry.get("inputFactIds", ())
    operands = []
    for index, code in enumerate((entry["numeratorMetric"], entry["denominatorMetric"])):
        candidates = [
            metric
            for metric in metrics
            if (
                metric.get("factId") == inputs[index]
                if len(inputs) == 2
                else code in metric.get("metricCodes", ())
                and metric.get("datasetId") in entry.get("datasetIds", ())
                and entry.get("periodRole") in metric.get("periodRoles", ())
            )
        ]
        if len(candidates) != 1:
            return True  # 保留尚未登记完整输入身份的旧文件读取行为。
        operands.append(candidates[0])
    return unit_conversion_scale(operands[1].get("unit"), operands[0].get("unit")) is not None


def _frozen_number_entries(
    contents: Iterable[str],
) -> Iterator[tuple[str, Any, str | None, str | None]]:
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
                if array == "derivedMetrics" and not _derived_units_comparable(
                    entry, document["metrics"]
                ):
                    values = [(field, value) for field, value in values if field != "difference"]
                values.extend(
                    (f"periodValues.{index}", item["value"])
                    for index, item in enumerate(entry.get("periodValues", ()))
                )
                for groups_key in ("topGroups", "bottomGroups"):
                    values.extend(
                        (f"{groups_key}.{index}", item["value"])
                        for index, item in _registered_groups(entry, groups_key)
                    )
                # 分组占比（“心内科占全院门诊收入的23.85%”）由服务端按登记分组值与合计计算：
                # 仅限求和指标、合计为正且无负值，百分数指标的占比无意义，不在此登记。
                total = entry.get("total")
                if (
                    array == "metrics"
                    and entry.get("aggregation") == "sum"
                    and entry.get("unit") != "%"
                    and isinstance(total, (int, float))
                    and total > 0
                    and not entry.get("negativeCount")
                ):
                    for groups_key in ("topGroups", "bottomGroups"):
                        values.extend(
                            (
                                f"groupShares.{groups_key}.{index}",
                                Decimal(str(item["value"])) / Decimal(str(total)) * 100,
                            )
                            for index, item in _registered_groups(entry, groups_key)
                            if isinstance(item.get("value"), (int, float)) and item["value"] >= 0
                        )
                # 分组之间的差额（“心内科较骨科多140.00万元”）：按登记的前列分组两两相减，只登记非负差额。
                top = [
                    (index, item)
                    for index, item in _registered_groups(entry, "topGroups")
                    if isinstance(item.get("value"), (int, float))
                ]
                if array == "metrics" and entry.get("unit") != "%" and len(top) <= 12:
                    values.extend(
                        (
                            f"groupGaps.{left[0]}-{right[0]}",
                            abs(Decimal(str(left[1]["value"])) - Decimal(str(right[1]["value"]))),
                        )
                        for left_position, left in enumerate(top)
                        for right in top[left_position + 1 :]
                    )
                periods = [
                    {**item, "period": _canonical_month_label(item["period"]) or item["period"]}
                    for item in entry.get("periodValues", ())
                ]
                if (
                    array == "metrics"
                    and entry.get("aggregation") == "sum"
                    and entry.get("periodGranularity") == "month"
                    and periods
                    and len(periods) <= 12
                    and _valid_month_labels(item["period"] for item in periods)
                    and len({item["period"][:7] for item in periods}) == len(periods)
                ):
                    # 均值分母使用实际月桶数，前缀累计从原值相加，禁止先舍入再累加。
                    amounts = [Decimal(str(item["value"])) for item in periods]
                    values.extend(
                        (
                            ("monthlyAverage", sum(amounts) / len(amounts)),
                            ("monthlyMinimum", min(amounts)),
                            ("monthlyMaximum", max(amounts)),
                        )
                    )
                    running = Decimal(0)
                    months = [
                        int(item["period"][:4]) * 12 + int(item["period"][5:7]) for item in periods
                    ]
                    chronological = True
                    for index, amount in enumerate(amounts):
                        running += amount
                        chronological = chronological and (
                            index == 0 or months[index] > months[index - 1]
                        )
                        if not chronological:
                            continue
                        if entry.get("periodAggregation") != "last":
                            values.append((f"periodTotals.0-{index}", running))
                        if months[: index + 1] == list(range(months[0], months[0] + index + 1)):
                            values.append((f"periodAverages.0-{index}", running / (index + 1)))
                    # 相邻两月的变化额与变化率（“3月环比增长…”）由服务端按登记月度值计算：只在月份
                    # 连续时登记，基期为零时不给变化率；百分数指标的差值口径不同，不在此登记。
                    for index in range(1, len(amounts)) if entry.get("unit") != "%" else ():
                        if months[index] != months[index - 1] + 1:
                            continue
                        change = amounts[index] - amounts[index - 1]
                        values.append((f"periodChanges.{index}", change))
                        if amounts[index - 1]:
                            values.append(
                                (
                                    f"periodChangeRates.{index}",
                                    change / abs(amounts[index - 1]) * 100,
                                )
                            )

                for field, value in values:
                    if value is None:
                        continue
                    # 派生事实的 unit 是分子/差额单位，比值本身无量纲。
                    unit = (
                        "%"
                        if field in {"changeRate", "percentage"}
                        or field.startswith(("periodChangeRates.", "groupShares."))
                        else None
                        if array == "derivedMetrics" and field == "value"
                        else entry.get("unit")
                    )
                    if percent_point_field(field, unit):
                        yield f"{{{{value:{fact_id}:{field}:%}}}}", value, unit, PERCENT_POINT
                        continue
                    units = _unit_scales(unit) or (unit or "",)
                    for target in units:
                        yield (
                            f"{{{{value:{fact_id}:{field}:{target}}}}}",
                            value,
                            unit,
                            target or None,
                        )
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
                for target in _unit_scales(unit) or (unit or "",):
                    token = f"{{{{value:{comparison['actualFactId']}:budgetComparison.{comparison['budgetFactId']}.{comparison['period']}.{field}:{target}}}}}"
                    yield token, comparison[field], unit, target or None
        for ratio in project_ratio_values(bundle):
            yield (
                f"{{{{value:{ratio['numeratorFactId']}:projectRatio.{ratio['budgetFactId']}.percentage:%}}}}",
                ratio["percentage"],
                "%",
                "%",
            )
        for share in metric_share_values(bundle):
            window = f".{share['period']}" if share["period"] else ""
            yield (
                f"{{{{value:{share['partFactId']}:metricShare.{share['totalFactId']}{window}:%}}}}",
                share["percentage"],
                "%",
                "%",
            )


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
    return {
        token: text
        for token, text in catalog.items()
        if not token[2:-2].split(":")[2].startswith(_SERVER_ONLY_FIELDS)
    }


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


def frozen_number_values(
    contents: Iterable[str], catalog: dict[str, str]
) -> dict[str, set[Decimal]]:
    """按显示单位给出未舍入的冻结原值。

    正文数字应由原值按其书写精度舍入后比较；若用两位小数的显示文本再舍入，
    1.245万元会先变成1.25再变成1.3，正确的1.2反被判为无依据。
    """
    values: dict[str, set[Decimal]] = {}
    for token, value, unit, target in _frozen_number_entries(contents):
        display_unit = target or unit
        # 非零值换算后舍入为 0.00（-10万元 → 0.00亿元）不能作为依据，手写“0.00亿元”仍替换。
        if (
            not display_unit
            or catalog.get(token) == "数值待核实"
            or _hidden_by_rounding(value, unit, target)
        ):
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
    span = (
        f"{months[0]}—{months[-1]}月"
        if months == list(range(months[0], months[-1] + 1))
        else "、".join(f"{month}月" for month in months)
    )
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
    contents: Iterable[str],
    catalog: dict[str, str],
    *,
    field_definitions: dict[str, str] | None = None,
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
        metric_shares = metric_share_values(bundle)
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

            def shown_reference(field: str, unit: str | None = None) -> str | None:
                # 模型常照着 monthOverMonth 键名自造 “monthOverMonth.N” 引用；直接给出可用的服务端引用。
                target = unit or ("万元" if fact.unit in _MONEY_UNITS else fact.unit or "")
                token = f"{{{{value:{fact.fact_id}:{field}:{target}}}}}"
                return token if shown(field, unit) else None

            periods = [item.period for item in fact.period_values]
            stock = fact.period_aggregation == "last"
            total_periods = periods[-1:] if stock else periods
            item: dict[str, Any] = {
                "factId": fact.fact_id,
                "analysisId": bundle.analysis_id,
                "datasetId": fact.dataset_id,
                "metric": getattr(fact, "display_name", None)
                or (field_definitions or {}).get(fact.field, fact.field),
                "metricCodes": list(fact.metric_codes),
                "scope": fact.scope,
                "unit": fact.unit,
                "periodRoles": list(fact.period_roles),
                "periodGranularity": fact.period_granularity,
                "periodAggregation": fact.period_aggregation,
                "total": {
                    "reference": reference("total"),
                    "periods": total_periods,
                    "periodStart": fact.period_end if stock else fact.period_start,
                    "periodEnd": fact.period_end,
                    "aggregation": fact.aggregation,
                    "meaning": "最新登记期间的期末余额，不能跨期相加"
                    if stock
                    else _TOTAL_MEANINGS.get(fact.aggregation, "完整期间的统计值"),
                    **(
                        {"coverage": coverage}
                        if (coverage := _month_coverage(total_periods))
                        else {}
                    ),
                },
                "rowStatistics": {
                    "average": reference("average"),
                    "minimum": reference("minimum"),
                    "maximum": reference("maximum"),
                    "meaning": ("最新登记期间的原始行统计" if stock else "原始行统计")
                    + "，不能称为月均值或月度极值",
                },
            }
            if reference("monthlyAverage"):
                low = min(value.value for value in fact.period_values)
                high = max(value.value for value in fact.period_values)
                item["monthlyStatistics"] = {
                    "monthCount": len(periods),
                    "average": reference("monthlyAverage"),
                    "minimum": reference("monthlyMinimum"),
                    "maximum": reference("monthlyMaximum"),
                    "minimumPeriods": [
                        value.period for value in fact.period_values if value.value == low
                    ],
                    "maximumPeriods": [
                        value.period for value in fact.period_values if value.value == high
                    ],
                    "zeroPeriods": [
                        value.period for value in fact.period_values if value.value == 0
                    ],
                    "prefixTotals": [
                        {
                            "start": periods[0],
                            "end": period,
                            "reference": reference(f"periodTotals.0-{index}"),
                        }
                        for index, period in enumerate(periods)
                        if reference(f"periodTotals.0-{index}")
                    ],
                    "prefixAverages": [
                        {
                            "start": periods[0],
                            "end": period,
                            "monthCount": index + 1,
                            "reference": reference(f"periodAverages.0-{index}"),
                        }
                        for index, period in enumerate(periods)
                        if reference(f"periodAverages.0-{index}")
                    ],
                    # 期末连续零值月份（回放：11、12月工作量为0）会拉低全期月均，正文只好解释分母；
                    # 另给零值月份之前的月均引用。
                    **(
                        {
                            "averageBeforeTrailingZeros": {
                                "end": periods[len(periods) - trailing - 1],
                                "monthCount": len(periods) - trailing,
                                "reference": reference(
                                    f"periodAverages.0-{len(periods) - trailing - 1}"
                                ),
                            }
                        }
                        if 0
                        < (
                            trailing := next(
                                (
                                    count
                                    for count, value in enumerate(reversed(fact.period_values))
                                    if value.value != 0
                                ),
                                0,
                            )
                        )
                        < len(periods)
                        and reference(f"periodAverages.0-{len(periods) - trailing - 1}")
                        else {}
                    ),
                    "monthOverMonth": [
                        {
                            "period": period,
                            "change": shown(f"periodChanges.{index}"),
                            "changeRate": shown(f"periodChangeRates.{index}", "%"),
                            "reference": shown_reference(f"periodChanges.{index}"),
                            "rateReference": shown_reference(f"periodChangeRates.{index}", "%"),
                        }
                        for index, period in enumerate(periods)
                        if shown(f"periodChanges.{index}")
                    ],
                    "meaning": "包含已登记的零值月份；零值本身不证明未入账或缺失。局部极值必须明确子期间。"
                    "monthOverMonth 是服务端按登记月度值计算的相邻两月变化额与变化率（某月较上月），"
                    "可按显示值直接书写或使用 reference/rateReference 引用，不得自造 monthOverMonth.N 引用；"
                    "不是环比比较事实的窗口变化",
                }
            item["groups"] = [
                {
                    "group": group.group,
                    "reference": reference(f"{key}.{index}"),
                    "meaning": (
                        "最新登记期间的完整分组组合期末余额" if stock else "完整分组组合的数值"
                    )
                    + "，不能称为单一科室或院区累计",
                }
                for key, groups in (
                    ("topGroups", fact.top_groups),
                    ("bottomGroups", fact.bottom_groups),
                )
                for index, group in enumerate(groups)
            ]
            item["budgetComparisons"] = []
            for comparison in comparisons:
                if comparison["actualFactId"] != fact.fact_id:
                    continue
                references = {}
                for field, unit in (("difference", comparison["unit"]), ("percentage", "%")):
                    token = f"{{{{value:{fact.fact_id}:budgetComparison.{comparison['budgetFactId']}.{comparison['period']}.{field}:{unit or ''}}}}}"
                    references[field] = (
                        token if token in catalog and catalog[token] != "数值待核实" else None
                    )
                item["budgetComparisons"].append(
                    {
                        "budgetFactId": comparison["budgetFactId"],
                        "period": comparison["period"],
                        "numeratorMetric": comparison["numeratorMetric"],
                        "denominatorMetric": comparison["denominatorMetric"],
                        "references": references,
                        "meaning": "同范围实际减预算、实际除预算×100%；百分数引用为空表示分母为零",
                    }
                )
            item["projectRatios"] = [
                {
                    "budgetFactId": ratio["budgetFactId"],
                    "numeratorMetric": ratio["numeratorMetric"],
                    "reference": token,
                    "meaning": "同快照合同或付款总额除以项目预算总额×100%；金额单位未知不影响比率。",
                }
                for ratio in project_ratios
                if ratio["numeratorFactId"] == fact.fact_id
                if (
                    token
                    := f"{{{{value:{fact.fact_id}:projectRatio.{ratio['budgetFactId']}.percentage:%}}}}"
                )
                in catalog
            ]
            item["metricShares"] = [
                {
                    "totalFactId": share["totalFactId"],
                    "totalMetric": share["totalMetric"],
                    "period": share["period"],
                    "reference": token,
                    "meaning": "该指标占同口径合计指标的百分比，分子分母均为冻结值；写占比必须使用此引用，不得自行相除",
                }
                for share in metric_shares
                if share["partFactId"] == fact.fact_id
                if (
                    token := f"{{{{value:{fact.fact_id}:metricShare.{share['totalFactId']}"
                    + (f".{share['period']}" if share["period"] else "")
                    + ":%}}"
                )
                in catalog
                and catalog[token] != "数值待核实"
            ]
            guide.append(item)
        for fact in bundle.derived_metrics:
            if not fact.fact_id or fact.fact_id in seen:
                continue
            seen.add(fact.fact_id)
            references = {}
            for field, unit in (
                ("numerator", fact.unit),
                ("denominator", fact.unit),
                ("difference", fact.unit),
                ("percentage", "%"),
            ):
                token = f"{{{{value:{fact.fact_id}:{field}:{unit or ''}}}}}"
                references[field] = (
                    token if token in catalog and catalog[token] != "数值待核实" else None
                )
            guide.append(
                {
                    "factId": fact.fact_id,
                    "analysisId": bundle.analysis_id,
                    "metric": fact.code,
                    "kind": fact.kind,
                    "periodRole": fact.period_role,
                    "periodGranularity": fact.period_granularity,
                    "periodStart": fact.period_start,
                    "periodEnd": fact.period_end,
                    "numeratorMetric": fact.numerator_metric,
                    "denominatorMetric": fact.denominator_metric,
                    "references": references,
                    "meaning": "分母为零时不可计算；分子为零且分母非零时为0%。仅使用已登记的比率期间，不扩展为月度比率",
                }
            )
        for fact in bundle.comparisons:
            if not fact.fact_id or fact.fact_id in seen:
                continue
            seen.add(fact.fact_id)
            references = {}
            for field in ("currentTotal", "baselineTotal", "change", "changeRate"):
                unit = "%" if field == "changeRate" else (fact.unit or "")
                token = f"{{{{value:{fact.fact_id}:{field}:{unit}}}}}"
                references[field] = (
                    token if token in catalog and catalog[token] != "数值待核实" else None
                )
            guide.append(
                {
                    "factId": fact.fact_id,
                    "analysisId": bundle.analysis_id,
                    "kind": "comparison",
                    "comparisonType": {"yoy": "同比", "mom": "环比"}[fact.comparison_type],
                    "periodGranularity": fact.period_granularity,
                    "metric": getattr(fact, "display_name", None)
                    or (field_definitions or {}).get(fact.field, fact.field),
                    "unit": fact.unit,
                    "periodStart": fact.period_start,
                    "periodEnd": fact.period_end,
                    "baselinePeriodStart": fact.baseline_period_start,
                    "baselinePeriodEnd": fact.baseline_period_end,
                    "baselineScale": fact.baseline_scale,
                    "references": references,
                    "meaning": "本期与基期取同一连续窗口的合计后比较；periodStart 与 periodEnd 跨多个月时是累计窗口，"
                    "正文须写明该窗口，不能写成单月变化；同比与环比不可混用",
                }
            )
    return guide


# 占位渲染为带单位的显示值；模型常在占位后再写一遍单位（“{{…:亿元}}亿元”“{{…:%}}%”），
# 渲染后成为“1.37亿元亿元”“654.32万元亿元”“5.03%%”。显示值已带单位时，紧随其后的
# 同一量纲单位去掉；显示值不带单位（单位待核实）或量纲不同的不动。
_UNIT_FAMILIES = (
    ("亿元", "万元", "元"),
    ("万人次", "人次"),
    (PERCENT_POINT, "百分点", "%"),
    ("‰",),
    ("床日",),
)
_TRAILING_UNIT = "|".join(
    sorted({unit for family in _UNIT_FAMILIES for unit in family}, key=len, reverse=True)
)
_VALUE_TOKEN_WITH_UNIT = re.compile(
    rf"(?P<token>\{{\{{value:[^{{}}\r\n]+\}}\}})(?P<unit>[ \t]*(?:{_TRAILING_UNIT}))?"
)


def _unit_family(unit: str) -> tuple[str, ...] | None:
    return next((family for family in _UNIT_FAMILIES if unit in family), None)


# 模型从补证表抄写的原始元值、人次（“1097718506元”“差额-66724688元”）没有千分位，领导读不出量级。
# 只处理五位及以上整数、紧跟元/人次/床日的写法；万元、亿元、编号与年份不动。
_UNGROUPED_AMOUNT = re.compile(r"(?<![A-Za-z0-9_.,])(\d{5,})(?=(?:\.\d+)?(?:元|人次|床日))")


def group_large_amounts(markdown: str) -> str:
    return _UNGROUPED_AMOUNT.sub(lambda match: f"{int(match[1]):,}", markdown)


# 读者是医院领导与财务人员，“月度桶”“登记值”是数据处理用语，按日常说法改写。
_NULL_WORDING = re.compile(r"(为|是|记为)\s*(?:null|None|NaN|nan)(?![A-Za-z0-9_])")
_MONTH_BUCKET_COUNT = re.compile(r"(\d+|[一两二三四五六七八九十]+)个月度桶")


def plain_period_wording(markdown: str) -> str:
    markdown = _MONTH_BUCKET_COUNT.sub(r"\1个月", markdown)
    # “登记值”是数据处理用语，财务与业务人员习惯说“记录值”；模型照抄的空值写法（“为null”）改为“为空”。
    markdown = _NULL_WORDING.sub(r"\1空", markdown)
    return (
        markdown.replace("月度桶标签", "月份").replace("月度桶", "月度").replace("登记值", "记录值")
    )


def render_frozen_numbers(markdown: str, catalog: dict[str, str], *, annotate=None) -> str:
    def replace(match: re.Match[str]) -> str:
        text = catalog.get(match["token"])
        written = match["unit"] or ""
        if text is None:
            logger.warning("report_number_reference_unavailable token={}", match["token"])
            return (annotate(match["token"], "数值待核实") if annotate else "数值待核实") + written
        shown = re.search(rf"(?:{_TRAILING_UNIT})$", text)
        parts = match["token"][2:-2].split(":")
        field, target = (parts[2] if len(parts) > 2 else ""), (parts[3] if len(parts) > 3 else "")
        # 相关系数、比值等无量纲引用（“…:value:”）后写了金额或人次单位，或显示单位与所写单位
        # 不同类（“5.03%万元”）：模型拿错了引用，回放中相关系数0.0048被写成“最小约0.00万元”。
        if written.strip() and (
            (not shown and field == "value" and not target)
            or (shown and _unit_family(shown[0]) != _unit_family(written.strip()))
        ):
            logger.warning(
                "report_number_reference_unit_mismatch token={} unit={}",
                match["token"],
                written.strip(),
            )
            return annotate(match["token"], "数值待核实") if annotate else "数值待核实"
        if annotate:
            text = annotate(match["token"], text)
        if written and shown and _unit_family(shown[0]) == _unit_family(written.strip()):
            logger.warning(
                "report_duplicate_unit_removed token={} unit={}", match["token"], written.strip()
            )
            return text
        return text + written

    rendered = _VALUE_TOKEN_WITH_UNIT.sub(replace, markdown)
    for warning in money_text_warnings(rendered):
        logger.warning("report_number_conversion_warning message={}", warning)
    return rendered


def supplemental_number_values(contents: Iterable[str]) -> dict[str, set[Decimal]]:
    """按补证列元数据或列名中的可信单位登记数值，不从数字大小猜测用途。"""
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
            columns, rows, metadata = (
                finding.get(key) for key in ("columns", "rows", "columnMeta")
            )
            # 明细表下可再挂汇总子表（finding.tables：按月合计、按科室合计），同样要登记。
            pending.extend(
                value
                for key, value in finding.items()
                if key not in {"columns", "rows", "columnMeta"} and isinstance(value, (dict, list))
            )
            if not isinstance(columns, list) or not isinstance(rows, list):
                continue
            if not isinstance(metadata, dict):
                metadata = {}
            for index, column in enumerate(columns):
                meta = metadata.get(column) if isinstance(column, str) else None
                unit = meta.get("unit") if isinstance(meta, dict) else None
                if not isinstance(unit, str):
                    # 补证表常缺 columnMeta；金额/人次/占比的列名自带单位词（“收入金额（元）”
                    # “门诊人次”“药耗占比”），按列名登记，不从数字大小猜用途。
                    unit = _unit_from_column_name(column if isinstance(column, str) else "")
                    meta = {**(meta if isinstance(meta, dict) else {}), "unit": unit}
                    if unit == "%":
                        meta.setdefault("isPercent", True)
                if unit not in {*_MONEY_UNITS, "人次", "万人次", "床日", "%", "‰"}:
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


_COLUMN_UNIT_WORDS = (
    # 仅供没有显式单位的列名回退；占比差额不能当成百分数水平。
    (("%",), ("占比", "比重", "比例", "贡献率", "完成率", "百分比")),
    # 金额列：单位词最具体者优先；无括号单位时金额类列名仍能识别。
    (("亿元",), ("亿元",)),
    (("万元",), ("万元",)),
    (("元",), ("金额", "收入", "支出", "成本", "费用", "差额", "缺口", "余额", "（元）", "(元)")),
    # 人次列：人次单位不可按金额列名误配。
    (("人次",), ("人次", "门诊量", "出院量")),
)
_COLUMN_UNIT_ANNOTATION = re.compile(r"[（(]\s*(?:单位\s*[:：]\s*)?([^（）()]+?)\s*[）)]\s*$")
_COLUMN_UNIT_SUFFIX = re.compile(r"(亿元|万元|万人次|人次|床日|%|‰)\s*$")
_COLUMN_SUPPORTED_UNITS = frozenset({*_MONEY_UNITS, "人次", "万人次", "床日", "%", "‰"})


def _unit_from_column_name(column: str) -> str | None:
    """补证表列名推断显示单位；无法确定时返回 None，不登记。"""
    # 完整单位优先于业务词；未知或复合单位也不能退回到“收入→元”等推断。
    if match := _COLUMN_UNIT_ANNOTATION.search(column):
        unit = match[1].strip()
        return unit if unit in _COLUMN_SUPPORTED_UNITS else None
    if re.search(r"[/／]|百分点|人数|人均|次均|床均|均次|单价|平均|每", column):
        return None
    if match := _COLUMN_UNIT_SUFFIX.search(column):
        return match[1]
    if any(word in column for word in _COLUMN_UNIT_WORDS[0][1]):
        return None if re.search(r"差额|差值|变化|变动|增减|缺口", column) else "%"
    if "率" in column:
        return None
    for (unit,), words in _COLUMN_UNIT_WORDS[1:]:
        if any(word in column for word in words):
            return unit
    return None


_DERIVED_ROW_LIMIT = 30
_CHINESE_COUNTS = "一二三四五六七八九十"


def _derived_period_matches(periods: tuple[str, ...], statement: str) -> bool:
    """派生差额必须覆盖正文写出的完整期间，不能只因某月落在总窗口中就认可总差额。"""
    from .number_selection import _DAY_PERIOD, _PERIOD

    parsed = [_parse_period(period) for period in periods]
    grains = {period.granularity for period in parsed if period is not None}
    expected = {period.value for period in parsed if period is not None}
    requests = []
    occupied = []

    def matches_span(match):
        return any(start <= match.start() < end for start, end in occupied)

    def day_window(match):
        try:
            start = date(int(match["year"]), int(match["month"]), int(match["day"]))
            end = date(
                int(match["end_year"] or match["year"]),
                int(match["end_month"] or match["month"]),
                int(match["end_day"] or match["day"]),
            )
        except ValueError:
            return None
        length = (end - start).days + 1
        if not 0 < length <= 1200:
            return None
        return ("day", {start + timedelta(days=i) for i in range(length)})

    for match in _DAY_PERIOD.finditer(statement):
        occupied.append(match.span())
        request = day_window(match)
        if request is None:
            return False
        requests.append(request)
    bare_day = re.compile(
        r"(?<![\d年])\d{1,2}月\d{1,2}(?:[日号]?[—–至到~～-]"
        r"(?:\d{4}年)?(?:\d{1,2}月)?\d{1,2})?[日号]"
    )
    for match in bare_day.finditer(statement):
        if matches_span(match):
            continue
        years = {period.year for period in expected}
        if len(years) != 1:
            return False
        labelled = _DAY_PERIOD.fullmatch(f"{next(iter(years))}年{match[0]}")
        request = day_window(labelled) if labelled else None
        if request is None:
            return False
        occupied.append(match.span())
        requests.append(request)
    for match in _PERIOD.finditer(statement):
        if matches_span(match):
            continue
        occupied.append(match.span())
        year = int(match["year"])
        if match["start"] is None:
            requests.append(("year", {year}))
            continue
        else:
            start, end = int(match["start"]), int(match["end"] or match["start"])
            if not 1 <= start <= 12 or not 1 <= end <= 12:
                return False
            first, last = year * 12 + start - 1, int(match["end_year"] or year) * 12 + end - 1
            if not match["end"] and expected and re.search("截至|累计", statement):
                first = min(period.year * 12 + period.month - 1 for period in expected)
        if not 0 <= last - first < 1200:
            return False
        requests.append(("month", set(range(first, last + 1))))
    for match in re.finditer(r"\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?", statement):
        if matches_span(match):
            continue
        occupied.append(match.span())
        period = _parse_period(match[0])
        if period is None:
            return False
        key = (
            period.value
            if period.granularity == "day"
            else period.value.year * 12 + period.value.month - 1
        )
        requests.append((period.granularity, {key}))
    for match in re.finditer(
        r"(?<![\d年])(?P<start>\d{1,2})月?(?:[—–至到~～-](?P<end>\d{1,2}))?月", statement
    ):
        if matches_span(match):
            continue
        years = {period.year for period in expected}
        if len(years) != 1:
            return False
        year = next(iter(years))
        start, end = int(match["start"]), int(match["end"] or match["start"])
        if not 1 <= start <= end <= 12:
            return False
        first, last = year * 12 + start - 1, year * 12 + end - 1
        if not match["end"] and expected and re.search("截至|累计", statement):
            first = min(period.year * 12 + period.month - 1 for period in expected)
        requests.append(("month", set(range(first, last + 1))))
    if not requests:
        return not (len(periods) > 1 and re.search("本月|当月|当日|本日", statement))
    keys = (
        expected
        if grains == {"day"}
        else {period.year for period in expected}
        if grains == {"year"}
        else {period.year * 12 + period.month - 1 for period in expected}
    )
    return all(
        (
            {period.year for period in expected} == requested
            if grain == "year"
            else grains == {grain} and keys == requested
        )
        for grain, requested in requests
    )


def _operand_names(left: str, right: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """两个操作数在正文中的可接受写法：全称，或去掉二者共同前后缀后的区分部分
    （“门诊人次”与“不含体检&急诊门诊人次”写作“含与不含体检&急诊”）。"""
    prefix = len(os.path.commonprefix((left, right)))
    suffix = len(os.path.commonprefix((left[::-1], right[::-1])))

    def names(label: str) -> tuple[str, ...]:
        core = label[prefix : len(label) - suffix] if prefix + suffix < len(label) else ""
        return (label, core) if len(core) >= 2 else (label,)

    return names(left), names(right)


@dataclass(frozen=True)
class _DerivedValue:
    value: Decimal
    operands: tuple[tuple[str, ...], ...]
    top: int | None
    periods: tuple[str, ...] | None
    difference: Decimal | None
    comparison: tuple[tuple[str, ...], ...]
    column: str | None
    peer_columns: tuple[str, ...]
    named_only: bool = False
    window_required: bool = False
    ratio: bool = False
    members: tuple[Decimal, ...] = ()
    fact_ids: tuple[str, ...] = ()
    operand_values: tuple[Decimal, ...] = ()
    table_derivation: TableDerivationV1 | None = None
    table_token: str | None = None


_RATIO_VERB = r"(?:相当于|为|占|是|达到?)"
_PERCENT_NUMBER = re.compile(r"(?<![\d.,])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?=\s*%)")


def _ratio_matches(entry: _DerivedValue, claim: str) -> bool:
    """“实际支出相当于预算支出的122.55%”：分子写在比较词前、分母写在其后且紧邻数值，方向不能互换。"""
    numerator, denominator = (
        "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
        for names in entry.comparison
    )
    tail = re.sub(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*%$", "", claim.rstrip())
    return (
        re.search(
            rf"(?:{numerator})[^，,。；]*?{_RATIO_VERB}[^，,。；\d]{{0,6}}?(?:{denominator})"
            rf"[^，,。；\d]{{0,4}}$",
            tail,
        )
        is not None
    )


def _members_written(members: tuple[Decimal, ...], claim: str) -> bool:
    """“人员支出35.32%、卫生材料27.28%、药品26.40%为主，三类合计约89.00%”：各分项数值已在本段写出时，
    合计就是这几项之和，分项名称可简写；写明的项数须与分项数一致。"""
    counts = re.findall(
        r"(\d+|[一二两三四五六七八九十])(?:项|类|个|家)(?:合计|共计|之和|总计|累计|共占)", claim
    )
    if counts:
        count = counts[-1]
        expected = {str(len(members))}
        if len(members) <= 10:
            expected.add(_CHINESE_COUNTS[len(members) - 1])
        if len(members) == 2:
            expected.add("两")
        if count not in expected:
            return False
    written = []
    for match in _PERCENT_NUMBER.finditer(claim):
        text = match[0].replace(",", "")
        digits = len(text.split(".", 1)[1]) if "." in text else 0
        written.append((Decimal(text), Decimal(1).scaleb(-digits)))
    remaining = list(written)
    for member in members:
        hit = next(
            (
                item
                for item in remaining
                if member.quantize(item[1], rounding=ROUND_HALF_UP) == item[0]
            ),
            None,
        )
        if hit is None:
            return False
        remaining.remove(hit)
    return True


def _derived_difference_matches(
    entry: _DerivedValue, number: Decimal, quantum: Decimal, claim: str
) -> bool:
    """保留减法的左右顺序；方向词后的正数是幅度，不能把多与少或正负互换。"""
    if entry.difference is None or len(entry.comparison) != 2:
        return False

    def spans(names):
        found = {match.span() for name in names for match in re.finditer(re.escape(name), claim)}
        return [
            span
            for span in found
            if not any(
                other != span and other[0] <= span[0] and span[1] <= other[1] for other in found
            )
        ]

    left, right = (spans(names) for names in entry.comparison)
    pairs = [(a, b) for a in left for b in right if a[1] <= b[0] or b[1] <= a[0]]
    if not pairs:
        return False
    relations = [
        match
        for match in re.finditer(r"(?<!相)(?:比|较)|高于|低于|多于|少于|超过|不足", claim)
        if not any(start <= match.start() < end for start, end in (*left, *right))
    ]
    if relations:
        relation = relations[-1]
        pairs = [
            (a, b)
            for a, b in pairs
            if (
                a[1] <= relation.start()
                and b[0] >= relation.end()
                or b[1] <= relation.start()
                and a[0] >= relation.end()
            )
        ]
        if not pairs:
            return False
        # 明确比较词两侧选最近的操作数，不借用同句中更早的另一组对象。
        a, b = min(
            pairs,
            key=lambda pair: (
                abs(pair[0][1] - relation.start()) + abs(pair[1][0] - relation.end())
                if pair[0][0] < pair[1][0]
                else abs(pair[1][1] - relation.start()) + abs(pair[0][0] - relation.end())
            ),
        )
    else:
        a, b = min(pairs, key=lambda pair: abs(pair[0][0] - pair[1][0]))
    difference = entry.difference if a[0] < b[0] else -entry.difference
    directions = list(
        re.finditer(
            r"高于|低于|多于|少于|超过|不足|(?<![至最不多少])(?:多|少|高|低)",
            claim[max(a[1], b[1]) :],
        )
    )
    if directions and not relations:
        # “1月收入…、成本…，成本高3.02亿元”：没有比较词时，方向词的主语是紧邻其前的操作数，
        # 不是先写出的一方。
        position = max(a[1], b[1]) + directions[-1].start()
        subjects = [
            (span[1], side)
            for side, found in ((1, left), (-1, right))
            for span in found
            if span[1] <= position
        ]
        if subjects:
            difference = entry.difference * max(subjects)[1]
    directed = (
        directions[-1][0]
        if directions
        else relations[-1][0]
        if relations and relations[-1][0] in {"高于", "低于", "多于", "少于", "超过", "不足"}
        else None
    )
    if directed:
        direction = 1 if directed in {"高于", "多于", "超过", "多", "高"} else -1
        return (
            number >= 0
            and difference * direction >= 0
            and abs(difference).quantize(quantum, rounding=ROUND_HALF_UP) == number
        )
    if re.search("相差|差额|差距|差异", claim):
        return number >= 0 and abs(difference).quantize(quantum, rounding=ROUND_HALF_UP) == number
    return difference.quantize(quantum, rounding=ROUND_HALF_UP) == number


def _column_stems(columns: tuple[str, ...]) -> dict[str, str]:
    """同单位多列去掉共同后缀后的区分词（“预算占比/实际占比”→“预算/实际”）；不唯一时不给。"""
    suffix = os.path.commonprefix([name[::-1] for name in columns])[::-1]
    stems = {name: name[: len(name) - len(suffix)] for name in columns} if suffix else {}
    if any(len(stem) < 2 for stem in stems.values()) or len(set(stems.values())) != len(stems):
        return {}
    return stems


class DerivedNumbers:
    """服务端补算的派生数值及其操作数名称：正文须在当前比较句写出参与计算的对象才认可。

    只登记数值会让“A比B多60元”因 60 恰好等于 A−C 而通过；因此每个差额、合计都带上
    操作数的行名、列名或指标名，并保留运算方向与期间，核对时只使用数字所在句。
    """

    def __init__(self, table_sources: Mapping[str, bytes] | None = None) -> None:
        self._values: dict[str, list[_DerivedValue]] = {}
        self._sorted: dict[str, list[Decimal]] = {}
        self._table_sources = table_sources or {}

    def add(
        self,
        unit: str,
        number: Decimal,
        operands: tuple[tuple[str, ...], ...],
        top: int | None = None,
        *,
        periods: tuple[str, ...] | None = None,
        comparison: tuple[tuple[str, ...], ...] | None = None,
        column: str | None = None,
        peer_columns: tuple[str, ...] = (),
        named_only: bool = False,
        window_required: bool = False,
        members: tuple[Decimal, ...] = (),
        fact_ids: tuple[str, ...] = (),
        operand_values: tuple[Decimal, ...] = (),
        table_operands: tuple[TableOperandV1, ...] = (),
    ) -> None:
        if not operands or any(not names for names in operands):
            return
        targets = [(unit, Decimal(1))]
        if (scales := _unit_scales(unit)) is not None:
            targets = [(target, scales[unit] / scale) for target, scale in scales.items()]
        elif unit == "人次":
            targets.append(("万人次", Decimal("0.0001")))
        for target, factor in targets:
            # 前 N 项合计只登记真实符号；差额的两个显示符号仍须按左右操作数和方向复核。
            for value in {number} if top is not None else {number, -number}:
                direction = Decimal(-1) if value != number else Decimal(1)
                table_derivation = (
                    TableDerivationV1(
                        operands=tuple(
                            operand.model_copy(update={
                                "coefficient": format(Decimal(operand.coefficient) * factor * direction, "f")
                            })
                            for operand in table_operands
                        ),
                        unit=target,
                    )
                    if table_operands and len(table_operands) <= 100 else None
                )
                self._values.setdefault(target, []).append(
                    _DerivedValue(
                        value * factor,
                        operands,
                        top,
                        periods,
                        number * factor if top is None else None,
                        comparison or operands[-2:],
                        column,
                        peer_columns,
                        named_only,
                        window_required,
                        members=tuple(member * factor for member in members),
                        fact_ids=fact_ids,
                        operand_values=tuple(operand * factor for operand in operand_values),
                        table_derivation=table_derivation,
                    )
                )
        self._sorted.clear()

    def add_ratio(
        self,
        numerator: Decimal,
        denominator: Decimal,
        names: tuple[tuple[str, ...], tuple[str, ...]],
        *,
        extra: tuple[tuple[str, ...], ...] = (),
        periods: tuple[str, ...] | None = None,
        fact_ids: tuple[str, ...] = (),
        operand_values: tuple[Decimal, ...] = (),
    ) -> None:
        """登记两个同口径值之比（百分数）；只在正文按“分子相当于分母的”写法时认可。"""
        if denominator == 0 or not all(names):
            return
        self._values.setdefault("%", []).append(
            _DerivedValue(
                numerator / denominator * 100,
                (*names, *extra),
                None,
                periods,
                None,
                names,
                None,
                (),
                ratio=True,
                fact_ids=fact_ids,
                operand_values=operand_values,
            )
        )
        self._sorted.pop("%", None)

    def supports(
        self,
        number: Decimal,
        unit: str,
        quantum: Decimal,
        context: str,
        *,
        statement: str | None = None,
        claim: str | None = None,
    ) -> bool:
        return next(
            self._matches(number, unit, quantum, context, statement=statement, claim=claim), None
        ) is not None

    def match(
        self,
        number: Decimal,
        unit: str,
        quantum: Decimal,
        context: str,
        *,
        statement: str | None = None,
        claim: str | None = None,
    ) -> _DerivedValue | None:
        """只有全部候选具有同一派生身份时才能签发引用。"""
        matches = list(self._matches(number, unit, quantum, context, statement=statement, claim=claim))
        if self._table_sources:
            from .table_sources import table_derivation_token

            matches = [
                replace(entry, table_token=table_derivation_token(entry.table_derivation, self._table_sources))
                if entry.table_derivation is not None else entry
                for entry in matches
            ]
        tokens = {derived_reference_token(entry, unit) for entry in matches}
        return matches[0] if matches and None not in tokens and len(tokens) == 1 else None

    def _matches(
        self,
        number: Decimal,
        unit: str,
        quantum: Decimal,
        context: str,
        *,
        statement: str | None = None,
        claim: str | None = None,
    ) -> Iterator[_DerivedValue]:
        entries = self._values.get(unit)
        if not entries:
            return
        if unit not in self._sorted:
            entries.sort(key=lambda entry: entry.value)
            self._sorted[unit] = [entry.value for entry in entries]
        keys = self._sorted[unit]
        index = bisect.bisect_left(keys, number - quantum)
        while index < len(keys) and keys[index] <= number + quantum:
            entry = entries[index]
            index += 1
            if entry.value.quantize(quantum, rounding=ROUND_HALF_UP) != number:
                continue
            local_claim = claim or statement or context
            if entry.column and len(entry.peer_columns) > 1:
                clauses = re.split(r"，|(?<!\d),|,(?!\d)", local_claim)
                measure_claim = next(
                    (
                        clause
                        for clause in reversed(clauses)
                        if any(name in clause for name in entry.peer_columns)
                    ),
                    local_claim,
                )
                mentions = [
                    (match.start(), match.end(), name)
                    for name in entry.peer_columns
                    for match in re.finditer(re.escape(name), measure_claim)
                ]
                if not mentions:
                    # “预算端……合计93.86%”只写出列名去掉共同后缀（“占比”）后的部分；以最先出现者为
                    # 主语，分项名中的“支出预算-全院性”不能再把实际端改判为预算端。
                    stems = sorted(
                        (match.start(), match.end(), name)
                        for name, stem in _column_stems(entry.peer_columns).items()
                        for match in re.finditer(re.escape(stem), measure_claim)
                    )
                    mentions = stems[:1]
                # 嵌套列名按最长匹配解释，“医疗收入”不能同时冒充“收入”列。
                columns = {
                    name
                    for start, end, name in mentions
                    if not any(
                        (a, b) != (start, end) and a <= start and end <= b
                        for a, b, _name in mentions
                    )
                }
                if columns != {entry.column}:
                    continue
            if entry.periods is not None and not _derived_period_matches(
                entry.periods, statement or local_claim
            ):
                continue
            # 只在共同期间成立的累计差额，正文不写期间会被读成全年口径。
            if entry.window_required and not re.search(r"\d{1,2}月", statement or local_claim):
                continue
            named = all(any(name in local_claim for name in names) for names in entry.operands)
            if entry.ratio:
                if named and _ratio_matches(entry, local_claim):
                    yield entry
                continue
            if entry.difference is not None:
                if named and _derived_difference_matches(entry, number, quantum, local_claim):
                    yield entry
                continue
            if entry.top is not None:
                names = [str(entry.top)]
                if entry.top <= 10:
                    names.append(_CHINESE_COUNTS[entry.top - 1])
                if entry.top == 2:
                    names.append("两")
                rankings = list(re.finditer(r"前(?:\d+|[一二两三四五六七八九十]+)", local_claim))
                ranked = rankings and rankings[-1][0][1:] in names
                if rankings and not ranked:
                    continue
                listed = re.search(
                    "合计|共计|累计|总计|之和|共占", local_claim
                ) and _members_written(entry.members, context)
                if (named or ranked and not entry.named_only or listed) and not re.search(
                    "相差|差额|差值|高于|低于", local_claim
                ):
                    yield entry

    def registered_values(self, unit: str) -> tuple[Decimal, ...]:
        """已登记的派生值（诊断用）：不做语句匹配，仅供质量扫描寻找最近候选。"""
        return tuple(entry.value for entry in self._values.get(unit, ()))

    def derived_entries(self) -> Iterator[tuple[str, _DerivedValue]]:
        """全部 (登记单位, 派生条目)；编辑器按 token 重建派生引用时使用。"""
        for unit, entries in self._values.items():
            yield from ((unit, entry) for entry in entries)


def _derived_number_text(value: Decimal) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def derived_reference_token(
    entry: _DerivedValue, unit: str, *, legacy: bool = False
) -> str | None:
    """事实对派生（同口径两事实之差/之比）铸成可解析引用 token；无事实身份不铸。

    token 内嵌两个操作数 factId（供绑定构建提取来源），并以内容寻址摘要保证唯一；
    解析端用同一 contents 重建派生登记后按 token 相等匹配，不做文法反解。
    ``legacy=True`` 按 PR #80 首版格式（操作数 ID 排序）重铸，用于继续解析已签发旧 token。
    """
    if entry.table_derivation is not None:
        return entry.table_token if not legacy and entry.table_derivation.unit == unit else None
    if len(entry.fact_ids) != 2 or len(set(entry.fact_ids)) != 2 or len(entry.operand_values) != 2:
        return None
    fact_ids = tuple(sorted(entry.fact_ids)) if legacy else tuple(entry.fact_ids)
    kind = "ratio" if entry.ratio else "difference" if entry.difference is not None else None
    if kind is None:
        return None
    digest = hashlib.sha256(
        "|".join(
            (
                kind,
                unit,
                *fact_ids,
                _derived_number_text(entry.value),
                *(entry.periods or ()),
                *(_derived_number_text(value) for value in entry.operand_values),
            )
        ).encode()
    ).hexdigest()[:16]
    return "{{derived:" + ":".join((*fact_ids, kind, digest, unit)) + "}}"


def derived_reference_resolution(
    entry: _DerivedValue, unit: str, fact_entries: Mapping[str, Any] | None = None
) -> dict[str, Any] | None:
    """派生引用的核对视图：与普通 token 解析结果同构，编辑器按相同口径消费。"""
    if derived_reference_token(entry, unit) is None:
        return None
    left, right = entry.operand_values[:2]
    fact_ids = entry.fact_ids[:2]
    fact_entries = fact_entries or {}
    if any(fact_id not in fact_entries for fact_id in fact_ids):
        return None
    if entry.difference is not None and entry.value != left - right:
        left, right = right, left
    if entry.ratio:
        formula = f"({_derived_number_text(left)}) / ({_derived_number_text(right)}) * 100"
        selector = "derivedRatio"
    else:
        formula = f"({_derived_number_text(left)}) - ({_derived_number_text(right)})"
        selector = "derivedDifference"
    names = [str(fact_entries[fact_id].get("displayName") or "") for fact_id in fact_ids]
    common_scope = fact_entries[fact_ids[0]].get("scope") or {}
    if common_scope != (fact_entries[fact_ids[1]].get("scope") or {}):
        return None
    roles = {
        role: tuple(entry.periods or ())
        for fact_id in fact_ids
        for role in fact_entries[fact_id].get("periodRoles") or ()
    }
    return {
        "value": float(entry.value),
        "unit": unit,
        "periods": tuple(entry.periods or ()),
        "period_roles": roles,
        "scope": common_scope,
        "formula": formula,
        "entry": {
            "displayName": "与".join(name for name in names if name) or None,
            "aliases": (),
            "scope": common_scope,
        },
        "selector": selector,
    }


_TOTAL_ROW = re.compile(r"(?:全院|全部|总)?(?:合计|总计|小计|汇总|总额|总量)")


def _derive_from_table(
    derived: DerivedNumbers,
    labels: list[str | None],
    columns: Mapping[str, tuple[str, list[Decimal]]],
    aliases: list[tuple[str, ...]] | None = None,
    *,
    resource_id: str | None = None,
    table_pointer: str = "",
    row_indices: Sequence[int] = (),
    column_indices: Mapping[str, int] | None = None,
    periods: tuple[str, ...] | None = None,
) -> None:
    """同一张表内补算，并在来源唯一时保留原始 JSON 单元格坐标。"""
    def cells(items: Iterable[tuple[int, str, int]]) -> tuple[TableOperandV1, ...]:
        if resource_id is None or column_indices is None:
            return ()
        return tuple(
            TableOperandV1(
                fileResourceId=resource_id, tablePointer=table_pointer,
                rowIndex=row_indices[row], columnIndex=column_indices[column],
                coefficient=str(coefficient),
            )
            for row, column, coefficient in items
        )

    for column, (unit, numbers) in columns.items():
        peers = tuple(
            name
            for name, (other_unit, _values) in columns.items()
            if other_unit == unit or other_unit in (_unit_scales(unit) or {})
        )
        if len(numbers) < 2:
            continue
        # 两个百分数之差以百分点补算，仍绑定行名和列名；占比合计保留百分数单位。
        # 两两差额随行数平方增长，只在小表补算；前 N 项合计只需一次排序，长表（科室、预算单元明细）
        # 也补算前 10 项，“预算端前五个单元合计94.08%”不再因表长被判为无依据。
        if len(numbers) <= _DERIVED_ROW_LIMIT:
            for position, (left_label, left) in enumerate(zip(labels, numbers, strict=True)):
                for right_position, (right_label, right) in enumerate(zip(
                    labels[position + 1 :], numbers[position + 1 :], strict=True
                ), start=position + 1):
                    if left_label and right_label:
                        derived.add(
                            PERCENT_POINT if unit == "%" else unit,
                            left - right,
                            _operand_names(left_label, right_label),
                            column=column,
                            peer_columns=peers,
                            periods=periods,
                            table_operands=cells(((position, column, 1), (right_position, column, -1))),
                        )
        # 补证表常带“合计”行：它不是分项，参与排序会让“前两项合计”变成合计行加首项。
        # 行名取该行全部文本单元格（编码与名称），正文写“财务处”也能对上“RJ008.01 / 财务处”。
        names = aliases or [(label,) if label else () for label in labels]
        ranked = sorted(
            (
                (number, row_names, row_position)
                for row_position, (number, label, row_names) in enumerate(zip(numbers, labels, names, strict=True))
                if not (label and _TOTAL_ROW.fullmatch(label.strip()))
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        running = Decimal(0)
        long_table = len(numbers) > _DERIVED_ROW_LIMIT
        prefixes = ranked[:10] if long_table else ranked[:-1]
        for count, (number, row_names, _row_position) in enumerate(prefixes, start=1):
            running += number
            top_rows = ranked[:count]
            members = tuple(item[1] for item in top_rows if item[1])
            if count > 1 and len(members) == count:
                derived.add(
                    unit,
                    running,
                    members,
                    top=count,
                    column=column,
                    peer_columns=peers,
                    named_only=long_table,
                    members=tuple(item[0] for item in top_rows),
                    periods=periods,
                    table_operands=cells(tuple((item[2], column, 1) for item in top_rows)),
                )
    items = list(columns.items())
    for position, (left_name, (unit, left)) in enumerate(items):
        for right_name, (right_unit, right) in items[position + 1 :]:
            if right_unit != unit or len(left) > _DERIVED_ROW_LIMIT:
                continue
            operands = _operand_names(left_name, right_name)
            for row_position, (label, a, b) in enumerate(zip(labels, left, right, strict=True)):
                if label:
                    derived.add(
                        PERCENT_POINT if unit == "%" else unit, a - b, ((label,), *operands),
                        periods=periods,
                        table_operands=cells(((row_position, left_name, 1), (row_position, right_name, -1))),
                    )
            if unit != "%":  # 百分数水平不能跨行求和后再比较。
                derived.add(
                    unit, sum(left) - sum(right), operands, periods=periods,
                    table_operands=cells(tuple(
                        (row, column, coefficient)
                        for column, coefficient in ((left_name, 1), (right_name, -1))
                        for row in range(len(left))
                    )),
                )


def _short_name(fact: Any) -> str | None:
    name = fact.display_name or ""
    return re.split(r"[，,；;]", name, maxsplit=1)[0].strip() or None


def derived_number_values(
    contents: Iterable[str], *, table_sources: Mapping[str, bytes] | None = None,
) -> DerivedNumbers:
    """服务端补算模型常写的两数之差与前 N 项合计，供正文核对使用，不进入模型可见目录。

    只在同一张补证表、同一分析的兼容事实内组合（同单位、同期间），不跨表或跨分析凑数：
    “门诊人次相差424,831人次”“总部与北部院区合计占比93.05%”“1月成本高于收入3.02亿元”。
    """
    contents = tuple(contents)
    sources = table_sources or {}
    derived = DerivedNumbers(sources)
    sources_by_digest: dict[bytes, list[str]] = {}
    for resource_id, raw in sources.items():
        if isinstance(raw, bytes):
            sources_by_digest.setdefault(hashlib.sha256(raw).digest(), []).append(resource_id)
    source_matches = {
        content: sources_by_digest.get(hashlib.sha256(content.encode("utf-8")).digest(), [])
        for content in contents if isinstance(content, str)
    }
    # 补证表列名常是字段编码（budget_project_amount），正文写“预算”“合同”：
    # 按同批事实的字段显示名改写列名，差额与列归属才能对上正文的比较对象。
    display: dict[str, str] = {}
    for bundle in frozen_fact_bundles(contents):
        for fact in bundle.metrics:
            if fact.field and (name := _short_name(fact)):
                display.setdefault(fact.field, name)
    for content in contents:
        try:
            document = json.loads(content)
        except (TypeError, ValueError):
            continue
        matches = set(source_matches.get(content, ()))
        resource_id = next(iter(matches)) if len(matches) == 1 else None
        pending = [(document, "")] if isinstance(document, (dict, list)) else []
        while pending:
            finding, pointer = pending.pop()
            if isinstance(finding, list):
                pending.extend((value, f"{pointer}/{index}") for index, value in enumerate(finding))
                continue
            if not isinstance(finding, dict):
                continue
            columns, rows, metadata = (
                finding.get(key) for key in ("columns", "rows", "columnMeta")
            )
            pending.extend(
                (value, pointer + "/" + key.replace("~", "~0").replace("/", "~1"))
                for key, value in finding.items()
                if key not in {"columns", "rows", "columnMeta"} and isinstance(value, (dict, list))
            )
            if not isinstance(columns, list) or not isinstance(rows, list):
                continue
            if not isinstance(metadata, dict):
                metadata = {}
            row_indices = [
                index for index, row in enumerate(rows)
                if isinstance(row, list) and len(row) == len(columns)
            ]
            rows = [rows[index] for index in row_indices]
            labels = [
                next((cell.strip() for cell in row if isinstance(cell, str) and cell.strip()), None)
                for row in rows
            ]
            aliases = [
                tuple(cell.strip() for cell in row if isinstance(cell, str) and cell.strip())
                for row in rows
            ]
            table: dict[str, tuple[str, list[Decimal]]] = {}
            column_indices: dict[str, int] = {}
            source_columns_valid = (
                all(isinstance(column, str) and column for column in columns)
                and len(set(columns)) == len(columns)
            )
            for index, column in enumerate(columns):
                if not isinstance(column, str):
                    continue
                meta = metadata.get(column)
                unit = meta.get("unit") if isinstance(meta, dict) else None
                if not isinstance(unit, str):
                    # 与 supplemental_number_values 同一列名推断；补证表缺 columnMeta 时
                    # 行差额/前 N 合计仍可按列单位补算。
                    unit = _unit_from_column_name(column if isinstance(column, str) else "")
                    meta = {**(meta if isinstance(meta, dict) else {}), "unit": unit}
                    if unit == "%":
                        meta.setdefault("isPercent", True)
                if (
                    unit not in {*_MONEY_UNITS, "人次", "万人次", "床日", "%"}
                    or unit == "%"
                    and meta.get("isPercent") is not True
                ):
                    continue
                numbers = [
                    Decimal(str(row[index]))
                    for row in rows
                    if isinstance(row[index], (int, float))
                    and not isinstance(row[index], bool)
                    and math.isfinite(row[index])
                ]
                if rows and len(numbers) == len(rows):
                    name = display.get(column, column)
                    key = column if name in table or name in columns else name
                    table[key] = (unit, numbers)
                    column_indices[key] = index
            semantics = table_semantics(document, finding)
            _derive_from_table(
                derived, labels, table, aliases,
                resource_id=resource_id if source_columns_valid else None,
                table_pointer=pointer,
                row_indices=row_indices,
                column_indices=column_indices,
                periods=semantics["periods"],
            )
    for bundle in frozen_fact_bundles(contents):
        from .subject_builder import fact_periods

        metrics = [
            fact
            for fact in bundle.metrics
            if fact.unit in {*_MONEY_UNITS, "人次", "床日"} and _short_name(fact)
        ]
        for position, left in enumerate(metrics):
            for right in metrics[position + 1 :]:
                if (
                    left.unit,
                    left.scope,
                    left.aggregation,
                    left.period_aggregation,
                    left.period_granularity,
                ) != (
                    right.unit,
                    right.scope,
                    right.aggregation,
                    right.period_aggregation,
                    right.period_granularity,
                ):
                    continue
                operands = _operand_names(_short_name(left), _short_name(right))
                periods = fact_periods(left.model_dump(mode="json", by_alias=True))
                # 事实对派生携带操作数身份：正文核对通过时可铸成派生引用（差/比），
                # 编辑器按与普通 {{value:}} 引用相同口径展示公式与来源。
                pair_ids = (
                    (left.fact_id, right.fact_id)
                    if isinstance(left.fact_id, str) and isinstance(right.fact_id, str)
                    else ()
                )
                left_total, right_total = Decimal(str(left.total)), Decimal(str(right.total))
                # 合计差额要求统计窗口完全相同；逐期差额只按两边都有的同一期间配对
                # （收入到11月、成本到9月时，1月仍可比）。
                if (left.period_start, left.period_end) == (
                    right.period_start,
                    right.period_end,
                ) and periods == fact_periods(right.model_dump(mode="json", by_alias=True)):
                    derived.add(
                        left.unit,
                        left_total - right_total,
                        operands,
                        periods=periods,
                        fact_ids=pair_ids,
                        operand_values=(left_total, right_total),
                    )
                    # “实际支出相当于预算支出的122.55%”：两个方向都登记，核对时按分子分母的写法定方向。
                    derived.add_ratio(
                        left_total,
                        right_total,
                        operands,
                        periods=periods,
                        fact_ids=pair_ids,
                        operand_values=(left_total, right_total),
                    )
                    derived.add_ratio(
                        right_total,
                        left_total,
                        operands[::-1],
                        periods=periods,
                        fact_ids=tuple(reversed(pair_ids)),
                        operand_values=(right_total, left_total),
                    )
                right_values = {item.period: item.value for item in right.period_values}
                shared: list[tuple[str, Decimal]] = []
                shared_operands = [Decimal(0), Decimal(0)]
                running: list[tuple[str, Decimal, Decimal]] = []
                for a in left.period_values:
                    if a.period not in right_values:
                        continue
                    period = _parse_fact_period(a.period, left.period_granularity)
                    if period:
                        year, month, day = period.value.year, period.value.month, period.value.day
                        if period.granularity == "day":
                            key = period.value.isoformat()
                            aliases = (
                                f"{year}年{month}月{day}日",
                                f"{month}月{day}日",
                                key,
                                key.replace("-", "/"),
                            )
                        elif period.granularity == "month":
                            key = f"{year:04d}-{month:02d}"
                            aliases = (f"{month}月", f"{month:02d}月", key, key.replace("-", "/"))
                        else:
                            key = f"{year:04d}"
                            aliases = (f"{year}年", key)
                        value, other = Decimal(str(a.value)), Decimal(str(right_values[a.period]))
                        gap = value - other
                        shared.append((key, gap))
                        shared_operands[0] += value
                        shared_operands[1] += other
                        derived.add(
                            left.unit,
                            gap,
                            (*operands, aliases),
                            periods=(key,),
                            comparison=operands,
                            fact_ids=pair_ids,
                            operand_values=(value, other),
                        )
                        derived.add_ratio(
                            value,
                            other,
                            operands,
                            extra=(aliases,),
                            periods=(key,),
                            fact_ids=pair_ids,
                            operand_values=(value, other),
                        )
                        derived.add_ratio(
                            other,
                            value,
                            operands[::-1],
                            extra=(aliases,),
                            periods=(key,),
                            fact_ids=tuple(reversed(pair_ids)),
                            operand_values=(other, value),
                        )
                        if period.granularity == "month":
                            running.append((key, value, other))
                # “1—11月累计实际支出相当于累计预算支出的…”：按共同月份从首月起逐月累计后求比。
                if running == sorted(running) and len(running) > 1:
                    total_left = total_right = Decimal(0)
                    for count, (_key, value, other) in enumerate(running, start=1):
                        total_left += value
                        total_right += other
                        if count > 1:
                            window = tuple(key for key, _a, _b in running[:count])
                            derived.add_ratio(
                                total_left,
                                total_right,
                                operands,
                                periods=window,
                                fact_ids=pair_ids,
                                operand_values=(total_left, total_right),
                            )
                            derived.add_ratio(
                                total_right,
                                total_left,
                                operands[::-1],
                                periods=window,
                                fact_ids=tuple(reversed(pair_ids)),
                                operand_values=(total_right, total_left),
                            )
                # 统计窗口不同（收入到11月、成本到9月）时，“1—9月成本比收入多3.98亿元”按两边都有的
                # 期间累计差额核对；正文须写出完整的共同窗口。
                if len(shared) > 1 and (left.period_start, left.period_end) != (
                    right.period_start,
                    right.period_end,
                ):
                    derived.add(
                        left.unit,
                        sum(gap for _key, gap in shared),
                        operands,
                        periods=tuple(key for key, _gap in shared),
                        window_required=True,
                        fact_ids=pair_ids,
                        operand_values=(shared_operands[0], shared_operands[1]),
                    )
    return derived


# Profile 告警登记的比例及正文须写明的含义词：缺失比例（“23646 (78.7%) missing values”）、
# 零值比例（“9673 (68.7%) zeros”）。
_PROFILE_RATES = (
    (
        re.compile(
            r"\((\d+(?:\.\d+)?)%\)\s*missing values|缺失(?:率|比例)?\s*(?:为|约)?\s*(\d+(?:\.\d+)?)%"
        ),
        ("缺失",),
    ),
    (re.compile(r"\((\d+(?:\.\d+)?)%\)\s*zeros"), ("零", "为0")),
)


def profile_rate_values(contents: Iterable[str]) -> list[tuple[tuple[str, ...], set[Decimal]]]:
    """事实告警中 Profile 登记的缺失、零值比例。

    正文说明数据质量时会引用这些比例；只在写明对应含义（“缺失”“零值”）的段落中认可，
    不作为一般百分数依据。
    """
    rates = [(words, set()) for _pattern, words in _PROFILE_RATES]
    for bundle in frozen_fact_bundles(contents):
        document = bundle.model_dump(mode="json", by_alias=True)
        warnings = list(document.get("warnings") or ())
        for array in ("metrics", "comparisons", "derivedMetrics"):
            for entry in document.get(array) or ():
                warnings.extend(entry.get("warnings") or ())
        for warning in warnings:
            for (pattern, _words), (_same, values) in zip(_PROFILE_RATES, rates, strict=True):
                values.update(
                    Decimal(next(group for group in match.groups() if group))
                    for match in pattern.finditer(str(warning))
                )
    return rates


def profile_rate_supported(rates, number: Decimal, quantum: Decimal, context: str) -> bool:
    return any(
        any(word in context for word in words)
        and any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in values)
        for words, values in rates
    )


def _paragraph_at(markdown: str, index: int) -> str:
    start = markdown.rfind("\n\n", 0, index)
    end = markdown.find("\n\n", index)
    return markdown[start + 2 if start >= 0 else 0 : end if end >= 0 else len(markdown)]


def _statement_at(markdown: str, index: int) -> str:
    return (
        re.split(r"[。！？；;\n]", markdown[:index])[-1]
        + re.split(r"[。！？；;\n]", markdown[index:])[0]
    )


NEUTRAL_DIFFERENCE_PREFIX = re.compile(r"(?:相差|差额|差距)(?:了|约|为|达)?\s*$")


def referenced_difference_matches(
    token: str | None,
    catalog: Mapping[str, str],
    number: Decimal,
    unit: str,
) -> bool:
    """只认可当前数值的差额引用；其他同值事实或同句引用不能提供豁免。"""
    parts = (token or "").removeprefix("{{value:").removesuffix("}}").split(":")
    if len(parts) != 3 or not (
        parts[1] == "difference"
        or (parts[1].startswith("budgetComparison.") and parts[1].endswith(".difference"))
    ):
        return False
    shown = re.fullmatch(rf"({_NUMBER})\s*{re.escape(unit)}", catalog.get(token or "", ""))
    return shown is not None and Decimal(shown[1].replace(",", "")) == number


def registered_decline_magnitude(
    number: Decimal,
    unit: str,
    candidates: Iterable[Decimal],
    *,
    prefix: str,
    quantum: Decimal,
) -> bool:
    """负的冻结值（变化率、变化额）可表述为“下降/减少”后接正幅度；不能据此豁免增长或占比。

    符号规范化会把“减少-654.32万元”改写为“减少654.32万元”，金额、人次与百分数一样
    必须按此认定为已登记数值，否则正确正文会被替换为待核实。
    """
    # 简写“实际降9.83%”“较预算少4.34万人次”同样是下降幅度；“至少”“最少”“减少”等不按单字处理。
    # 中性差额（相差/差额/差距）必须由操作数验证，不能借用全局负值的幅度。
    if number <= 0 or not re.search(
        rf"(?:{'|'.join(FALLING_WORDS)}|(?<![至最不多])[降减少]|超支|超出|缺口)"
        r"(?:了|约|为|达)?\s*$",
        prefix,
    ):
        return False
    return any(
        value < 0 and (-value).quantize(quantum, rounding=ROUND_HALF_UP) == number
        for value in candidates
    )


def normalize_signed_wording(markdown: str) -> str:
    """按冻结值的符号改写方向词：负值不能跟“增长”，也不能与“下降”构成双重否定。

    冻结值决定方向，改写只调整措辞与负号，不改动数值本身。
    """

    def replace(match: re.Match[str]) -> str:
        if describes_rate_level(match.string[: match.start()]) and not re.match(
            r"\s*个百分点", match.string[match.end() :]
        ):
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

    # “实际较预算少-4.34万人次”“较预算支出低-13.47亿元”：比较句里的“多/少”“高/低”同样不能再带负号。
    # 单字不进方向词表，以免“至少”“最多”“最低-5.2%”“提高”“降低”等被改写。
    def replace_comparative(match: re.Match[str]) -> str:
        logger.warning(
            "report_signed_wording_normalized verb={} value={}", match["verb"], match["value"]
        )
        word = "少" if match["verb"] in "多少" else "低"
        return f"{word}{match['space']}{match['value']}"

    return re.sub(
        r"(?<![至最不多少偏提降升抬拉])(?P<verb>多|少|高|低)(?P<space>\s*)-\s*(?P<value>\d[\d,]*(?:\.\d+)?)",
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
            len(parts) == 3
            and parts[1].startswith("budgetComparison.")
            and parts[1].endswith(".difference")
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
        if match["token"] not in positive or describes_rate_level(match.string[: match.start()]):
            return match[0]
        rising = FALLING_TO_RISING[match["verb"]]
        logger.warning(
            "report_direction_wording_aligned verb={} token={}", match["verb"], match["token"]
        )
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
MULTIPLE_NUMBER = re.compile(
    r"(?<![\d.,+-])(?P<number>[+-]?\d+(?:\.\d+)?)\s*倍(?!数|标准差|四分位|方差|IQR)"
)


# “同比增长11.00个百分点”：变化率写成了百分点。占比、比重、比例或“率”的变化本来就以百分点计，
# 这类分句不改写。
RATE_AS_PERCENT_POINT = re.compile(rf"(?<![\d.,])(?P<number>{_NUMBER})\s*个?百分点")
_PERCENT_POINT_SUBJECT = re.compile(r"占比|比重|比例|构成|率|增速|增幅|降幅|涨幅|跌幅")


def registered_change_rates(contents: Iterable[str]) -> set[Decimal]:
    """已登记的变化率幅度：比较事实的同比/环比变化率与相邻两月的变化率。"""
    return {
        abs(Decimal(str(value)))
        for token, value, _unit, _target in _frozen_number_entries(contents)
        if value is not None
        and token[2:-2].split(":")[2] == "changeRate"
        or value is not None
        and token[2:-2].split(":")[2].startswith("periodChangeRates.")
    }


def registered_group_shares(contents: Iterable[str]) -> set[Decimal]:
    """服务端按分组值与合计登记的分组占比（只供核对）。"""
    return {
        Decimal(str(value))
        for token, value, _unit, _target in _frozen_number_entries(contents)
        if value is not None and token[2:-2].split(":")[2].startswith("groupShares.")
    }


def percent_point_written_for_rate(
    match: re.Match[str],
    text: str,
    rates: set[Decimal],
    points: Iterable[Decimal],
    percents: Sequence[Decimal],
) -> bool:
    """“个百分点”的数值只对得上登记变化率、对不上百分点差值且分句不是占比/比率类时返回 True。"""
    clause = re.split(r"[。；，\n]", text[: match.start()])[-1]
    if _PERCENT_POINT_SUBJECT.search(clause):
        return False
    number = abs(Decimal(match["number"].replace(",", "")))
    quantum = Decimal(1).scaleb(
        -(len(match["number"].split(".")[1]) if "." in match["number"] else 0)
    )

    def shown(values: Iterable[Decimal]) -> bool:
        return any(
            abs(value).quantize(quantum, rounding=ROUND_HALF_UP) == number for value in values
        )

    if not shown(rates) or shown(points):
        return False
    # 两项登记百分数（占比、完成率等水平值）之差同样是有依据的百分点；变化率之间的差只在
    # “增速/增幅”语境下才是百分点，已在上方跳过。候选过多时不比较，按变化率处理。
    ordered = sorted(value for value in percents if abs(value) not in rates)
    return not (
        len(ordered) <= 400
        and shown(
            right - left for index, left in enumerate(ordered) for right in ordered[index + 1 :]
        )
    )


def registered_multiples(
    contents: Iterable[str],
    catalog: dict[str, str],
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
    direction = _MULTIPLE_DIRECTION.search(match.string[max(0, match.start() - 40) : match.start()])
    kind = "ratio"
    if direction:
        kind = "increase" if direction["verb"] in RISING_WORDS else "decrease"
    number = Decimal(match["number"])
    digits = len(match["number"].split(".", 1)[1]) if "." in match["number"] else 0
    quantum = Decimal(1).scaleb(-digits)
    return any(
        value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in multiples[kind]
    )


_TABLE_SEPARATOR_ROW = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
_TABLE_HEADER_UNIT = re.compile(
    rf"[（(]\s*(?:单位\s*[:：]\s*)?({REPORT_VALUE_UNIT_PATTERN}|个百分点)\s*[）)]\s*$"
)
_BARE_CELL_NUMBER = re.compile(r"^\s*(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*$")


def _table_cells(line: str) -> list[tuple[int, int]]:
    """管道表一行的单元格区间（不含分隔竖线），忽略转义的“\\|”。"""
    pipes = [
        index
        for index, character in enumerate(line)
        if character == "|" and (index == 0 or line[index - 1] != "\\")
    ]
    if not pipes:
        return []
    cells = [(pipes[index] + 1, pipes[index + 1]) for index in range(len(pipes) - 1)]
    if line[: pipes[0]].strip():
        cells.insert(0, (0, pipes[0]))
    if line[pipes[-1] + 1 :].strip():
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
        if not (
            "|" in lines[index]
            and "|" in lines[index + 1]
            and _TABLE_SEPARATOR_ROW.match(lines[index + 1])
        ):
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
                    found.append(
                        (
                            offsets[row] + start + match.start("number"),
                            offsets[row] + start + match.end("number"),
                            match["number"],
                            units[column],
                        )
                    )
            row += 1
        index = row
    return found


# “超过3,700万元”“近4,000万元”：以整数界限描述登记值。界限必须是某个登记值按 1～2 位有效数字
# 向下取整（超过/逾/突破…）或向上取整（不足/近/接近…）的结果，避免任意登记值碰巧落在宽松区间内。
_LOWER_BOUND = re.compile(r"(?:超过|逾|突破|高于|多于|大于)\s*$")
_UPPER_BOUND = re.compile(r"(?:不足|低于|少于|小于|近|接近|将近|不到)\s*$")


def bounded_by_registered(
    number: Decimal, number_text: str, values: Iterable[Decimal], *, prefix: str
) -> bool:
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
            bound = (value / step).to_integral_value(
                rounding=ROUND_FLOOR if above else ROUND_CEILING
            ) * step
            if bound == number:
                return True
    return False


def replace_unregistered_numbers(
    markdown: str,
    contents: Iterable[str],
    *,
    missing=None,
    on_unverified=None,
    references: Mapping[str, str] | None = None,
    on_verdict: Callable[[str, Decimal, str, str], None] | None = None,
    on_derived_anchor: Callable[[Any, str], str] | None = None,
    table_sources: Mapping[str, bytes] | None = None,
) -> str:
    """把没有冻结依据的带单位数字替换为待核实，避免手算结果落盘。

    references 仅接受本次服务端渲染生成的 claim→token 映射，不信任正文自带的标记。
    on_verdict 观测每个核对数字的 (结论, 数值, 单位, 依据原因)，只用于质量扫描统计，
    不改变替换行为；结论取 registered/percent_point/corrected/missing。
    on_derived_anchor 在唯一来源的派生核对通过时收到 (派生条目, 单位)，返回值作为锚点
    追加在该数字之后（服务端签发派生引用用）；不提供则维持只放行不锚定。
    """

    contents = tuple(contents)
    catalog = frozen_number_catalog(contents)
    known = supplemental_number_values(contents)
    derived = derived_number_values(contents, table_sources=table_sources)
    profile_rates = profile_rate_values(contents)
    # 没有可解析的冻结事实时，服务端无法判断正文数字是否为派生值；
    # 保留原文，避免把仅含原始证据的旧格式内容全部改成“待核实”。
    if not catalog and not known:
        return markdown
    for unit, values in frozen_number_values(contents, catalog).items():
        known.setdefault(unit, set()).update(values)

    def reference_at(tail: str) -> str | None:
        anchor = re.match(r"\[\[claim:([^\]\n]+)\]\]", tail)
        return (references or {}).get(anchor[1]) if anchor else None

    def verify(
        number_text: str,
        unit: str,
        prefix: str,
        context: str,
        statement: str,
        claim: str,
        reference: str | None = None,
    ) -> tuple[str, str, str]:
        """返回 (结论, 数字, 锚点)：registered 按显示精度保留，corrected 改写为服务端补算值，
        percent_point 改写为百分点，missing 替换；锚点仅在唯一来源派生通过时非空。"""
        number = Decimal(number_text.replace(",", ""))
        digits = len(number_text.split(".", 1)[1]) if "." in number_text else 0
        quantum = Decimal(1).scaleb(-digits)
        candidates = known.get(unit, ())
        neutral = NEUTRAL_DIFFERENCE_PREFIX.search(prefix) is not None

        def derived_check() -> bool:
            return derived.supports(number, unit, quantum, context, statement=statement, claim=claim)

        def anchor_for(value: Decimal) -> str:
            if on_derived_anchor is None or reference is not None:
                return ""
            entry = derived.match(value, unit, quantum, context, statement=statement, claim=claim)
            return on_derived_anchor(entry, unit) if entry is not None else ""

        if neutral:
            # 中性差额只认当前句操作数的补算差额，或当前数字由服务端渲染的差额引用。
            checks = (
                ("derived", derived_check),
                (
                    "referenced_difference",
                    lambda: referenced_difference_matches(reference, catalog, number, unit),
                ),
            )
        else:
            checks = (
                (
                    "direct",
                    lambda: any(
                        value.quantize(quantum, rounding=ROUND_HALF_UP) == number
                        for value in candidates
                    ),
                ),
                (
                    "decline",
                    lambda: registered_decline_magnitude(
                        number, unit, candidates, prefix=prefix, quantum=quantum
                    ),
                ),
                (
                    "bounded",
                    lambda: bounded_by_registered(number, number_text, candidates, prefix=prefix),
                ),
                ("derived", derived_check),
                # “预算支出有65.9%的行为零”：含义词写在比例之后，按整句判断。
                (
                    "profile_rate",
                    lambda: (
                        unit == "%"
                        and profile_rate_supported(
                            profile_rates, number, quantum, statement or claim or context
                        )
                    ),
                ),
            )
        reason = next((name for name, check in checks if check()), None)
        if reason is not None:
            anchor = anchor_for(number)
            report("registered", number, unit, reason)
            return "registered", _display_precision(number_text), anchor
        # 百分数指标的变化写成“提高2.10%”：数值只对得上登记的百分点差值时改写单位，
        # 避免把两项百分数之差读成相对变化率。
        points = known.get(PERCENT_POINT, ()) if unit == "%" and not neutral else ()
        if points and (
            any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in points)
            or registered_decline_magnitude(
                number, PERCENT_POINT, points, prefix=prefix, quantum=quantum
            )
        ):
            logger.warning("report_percent_point_unit_corrected value={}{}", number_text, unit)
            report("percent_point", number, unit, "percent_point")
            return "percent_point", _display_precision(number_text), ""
        # 回放：“三项合计占88.99%”（实为88.9987%，应写89.00%）、“相差约6.51亿元”（实为6.5164亿元）：
        # 模型拿已舍入的显示值手算，末位差一个单位。正文已写明参与计算的对象、服务端补算值唯一
        # 对得上相邻末位时改写为补算值，不替换为待核实；整数与直接登记值不做此修正。
        if digits:
            nearby = [
                candidate
                for candidate in (number - quantum, number + quantum)
                if derived.supports(
                    candidate, unit, quantum, context, statement=statement, claim=claim
                )
            ]
            if len(nearby) == 1:
                corrected = (
                    f"{nearby[0]:,.{digits}f}" if "," in number_text else f"{nearby[0]:.{digits}f}"
                )
                logger.warning(
                    "report_derived_number_corrected value={}{} corrected={}{}",
                    number_text,
                    unit,
                    corrected,
                    unit,
                )
                report("corrected", number, unit, "last_digit")
                return "corrected", _display_precision(corrected), anchor_for(nearby[0])
        logger.warning("report_unregistered_number_replaced value={}{}", number_text, unit)
        report("missing", number, unit, "unmatched")
        return "missing", number_text, ""

    missing = missing or (lambda: "待核实")

    def unverified(original: str) -> str:
        # 原始写法仅供编辑器核对，不能重新登记成可信数值或写回正文。
        return on_unverified(original) if on_unverified is not None else missing()

    def report(verdict: str, number: Decimal, unit: str, reason: str) -> None:
        if on_verdict is not None:
            on_verdict(verdict, number, unit, reason)

    # 模型自写表格把单位写在表头（“金额（万元）”），单元格只有数字：按表头单位同样核对。
    for start, end, number_text, unit in reversed(table_unit_cells(markdown)):
        verdict, written, anchor = verify(
            number_text,
            unit,
            "",
            _paragraph_at(markdown, start),
            _statement_at(markdown, start),
            re.split(r"[。！？；;\n]", markdown[:end])[-1],
            reference_at(markdown[end:]),
        )
        if verdict in {"registered", "corrected"}:
            cell = written + anchor
        elif verdict == "percent_point":
            cell = f"{written}{PERCENT_POINT}"
        else:
            cell = unverified(number_text + unit)
        markdown = markdown[:start] + cell + markdown[end:]

    def replace(match: re.Match[str]) -> str:
        unit = match["unit"]
        prefix = markdown[max(0, match.start() - 12) : match.start()]
        if unit in {PERCENT_POINT, "百分点"}:
            # 非中性百分点仍交给后续变化率单位纠正；中性差额与金额共用当前引用/操作数校验。
            if not NEUTRAL_DIFFERENCE_PREFIX.search(prefix):
                return match[0]
            unit = PERCENT_POINT
        # 只使用调用方提供的服务端锚点映射；正文自行书写的 claim 标记不能建立数值身份。
        reference = reference_at(markdown[match.end() :])
        verdict, written, anchor = verify(
            match["number"],
            unit,
            prefix,
            _paragraph_at(markdown, match.start()),
            _statement_at(markdown, match.start()),
            re.split(r"[。！？；;\n]", markdown[: match.end()])[-1],
            reference,
        )
        if verdict in {"registered", "corrected"}:
            return written + match[0][len(match["number"]) :] + anchor
        return f"{written}{PERCENT_POINT}" if verdict == "percent_point" else unverified(match[0])

    replaced = re.sub(
        r"(?<![\d.,])(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*"
        rf"(?P<unit>个?百分点|{REPORT_VALUE_UNIT_PATTERN})",
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
            target
            for target in targets
            if any(
                value.quantize(quantum, rounding=ROUND_HALF_UP) == number
                for value in known.get(target, ())
            )
        ]
        if not matched:
            logger.warning("report_unregistered_number_replaced value={}", match[0])
            report("missing", number, match["scale"], "bare_scaled")
            return unverified(match[0])
        if len(matched) == 1:
            report("registered", number, matched[0], "bare_scaled")
        written = _display_precision(match["number"]) + match["scale"]
        return written + matched[0][1:] if len(matched) == 1 else written

    def replace_persons(match: re.Match[str]) -> str:
        # “门诊量35.3万人”：人次（就诊次数）写成了人数。数值只对得上登记的人次时改回人次；
        # 对不上的“人”可能是职工、床位等其他人数，不在此替换。
        number = Decimal(match["number"].replace(",", ""))
        digits = len(match["number"].split(".", 1)[1]) if "." in match["number"] else 0
        quantum = Decimal(1).scaleb(-digits)
        visit_unit = "万人次" if match["scale"] else "人次"
        if not any(
            value.quantize(quantum, rounding=ROUND_HALF_UP) == number
            for value in known.get(visit_unit, ())
        ) or any(
            value.quantize(quantum, rounding=ROUND_HALF_UP) == number
            for value in known.get("人", ())
        ):
            return match[0]
        logger.warning("report_visit_unit_corrected value={}", match[0])
        return f"{_display_precision(match['number'])}{match['scale'] or ''}人次"

    replaced = PERSON_COUNT.sub(replace_persons, replaced)
    rates = registered_change_rates(contents)
    # 分组占比两两相减的组合很多，取整后容易凑上变化率；判断“变化率误写为百分点”时不用它们作依据。
    shares = registered_group_shares(contents)
    rate_level_percents = tuple(value for value in known.get("%", ()) if value not in shares)

    def replace_rate_points(match: re.Match[str]) -> str:
        if not percent_point_written_for_rate(
            match, replaced, rates, known.get(PERCENT_POINT, ()), rate_level_percents
        ):
            return match[0]
        logger.warning("report_change_rate_unit_corrected value={}", match[0])
        return f"{_display_precision(match['number'])}%"

    replaced = RATE_AS_PERCENT_POINT.sub(replace_rate_points, replaced) if rates else replaced
    multiples = registered_multiples(contents, catalog)

    def replace_multiple(match: re.Match[str]) -> str:
        number = Decimal(match["number"])
        if registered_multiple_matches(match, multiples):
            report("registered", number, "倍", "multiple")
            return _display_precision(match["number"]) + match[0][len(match["number"]) :]
        logger.warning("report_unregistered_multiple_replaced value={}", match[0])
        report("missing", number, "倍", "multiple")
        return unverified(match[0])

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
    analysis_bundles = [
        item
        for item in normalized
        if item.get("metrics") and isinstance(item.get("analysisId"), str)
    ]
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
                    corrected[marker.end() : end],
                    int(wrong_month),
                    kind,
                    expected,
                    _series_year(bundle),
                )
                if segment is not None:
                    corrected = corrected[: marker.end()] + segment + corrected[end:]
                    logger.warning(
                        "report_period_extrema_corrected wrong_month={} expected_months={}",
                        wrong_month,
                        expected,
                    )
                    break
    return corrected[len(scope) :]


# “预算各月均为131.73亿元（13,172,622,072元）”把全年合计写成了单月值，领导会读成每月 131 亿。
# 只在事实为逐月相加且各月取值相同、正文数值恰为其合计时改写为单月值；其余情形不猜。
_EACH_MONTH_AMOUNT = re.compile(
    rf"(?P<lead>(?:各月|每月|逐月|按月)[^。；;\n\d{{}}（(]{{0,12}}?)"
    rf"(?P<number>{_NUMBER})\s*(?P<unit>亿元|万元|元|万人次|人次)"
    rf"(?P<base>\s*[（(]\s*(?P<base_number>{_NUMBER})\s*(?P<base_unit>元|人次)\s*[）)])?"
)


def _scaled_value(value: Decimal, fact_unit: str, unit: str, number_text: str) -> Decimal | None:
    scales = _unit_scales(fact_unit)
    if scales is None or unit not in scales:
        return None
    digits = len(number_text.split(".", 1)[1]) if "." in number_text else 0
    return (value * scales[fact_unit] / scales[unit]).quantize(
        Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP
    )


def correct_constant_monthly_totals(markdown: str, contents: Iterable[str]) -> str:
    constants: list[tuple[str, Decimal, Decimal]] = []
    for bundle in frozen_fact_bundles(contents):
        for fact in bundle.metrics:
            values = {Decimal(str(item.value)) for item in fact.period_values}
            if (
                fact.period_granularity != "month"
                or len(fact.period_values) < 2
                or len(values) != 1
                or fact.aggregation not in {"sum", "count"}
                or fact.period_aggregation == "last"
                or not fact.unit
                or _unit_scales(fact.unit) is None
            ):
                continue
            month, total = next(iter(values)), Decimal(str(fact.total))
            if month and total == month * len(fact.period_values):
                constants.append((fact.unit, total, month))
    if not constants:
        return markdown

    def replace(match: re.Match[str]) -> str:
        if re.search(r"合计|累计|全年|总计|总额|年度", match["lead"]):
            return match[0]
        number = Decimal(match["number"].replace(",", ""))
        months = {
            month
            for fact_unit, total, month in constants
            if _scaled_value(total, fact_unit, match["unit"], match["number"]) == number
        }
        if len(months) != 1:
            return match[0]
        month = months.pop()
        fact_unit = next(unit for unit, _, value in constants if value == month)
        written = (
            f"{_scaled_value(month, fact_unit, match['unit'], match['number'])}{match['unit']}"
        )
        base = match["base"] or ""
        if base:
            base_number = Decimal(match["base_number"].replace(",", ""))
            total = next(total for _, total, value in constants if value == month)
            if (
                _scaled_value(total, fact_unit, match["base_unit"], match["base_number"])
                == base_number
            ):
                monthly = _scaled_value(month, fact_unit, match["base_unit"], match["base_number"])
                base = base.replace(match["base_number"], str(monthly), 1)
        logger.warning(
            "report_constant_monthly_total_corrected value={}{}", match["number"], match["unit"]
        )
        return match["lead"] + written + base

    return _EACH_MONTH_AMOUNT.sub(replace, markdown)


_EXTREMA_WORDS = {"最高": "最高|峰值", "最低": "最低|低点"}
# 与 period_extrema_warnings 的豁免一致：分项比例、变化率和组织明细的极值不按全院月序列改写。
_EXTREMA_EXEMPT = re.compile(
    r"占比|比重|比例|环比|同比|增长率|降幅|增幅|组织明细|明细分组|分组组合"
)
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
    metrics = [
        entry
        for entry in raw_metrics
        if isinstance(entry, Mapping)
        and isinstance(entry.get("periodRoles"), (list, tuple))
        and "current" in entry["periodRoles"]
    ]
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
    segment: str,
    wrong_month: int,
    kind: str,
    expected: str,
    year: str | None,
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
        candidates.extend(
            (sentence, found)
            for found in claim.finditer(sentence[0])
            if not _EXTREMA_EXEMPT.search(found[0])
        )
    if len(candidates) != 1:
        return None
    sentence, found = candidates[0]
    before = sentence[0][: found.start()]
    if before.endswith(("在", "于")):
        before = before[:-1]
    # 保留月份与极值词之间的指标名（“2月金额为最高值”→“金额最高月份为…”）；
    # 夹带数值或分句时那是错误月份的数值，一并去掉。
    subject = found["between"].replace("**", "")
    while (stripped := _EXTREMA_SUBJECT_SUFFIX.sub("", subject)) != subject:
        subject = stripped
    if re.search(r"[\d，,、]|\{\{", subject):
        subject = ""
    after = sentence[0][found.end() :]
    after = re.sub(rf"^\s*(?:（[^）]*）)?\s*(?:为|达|约|计|是)?\s*{_DISPLAYED_VALUE}", "", after)
    after = re.sub(rf"^[，,]\s*(?:为|达|约|计|金额为|数值为)\s*{_DISPLAYED_VALUE}", "", after)
    rewritten = f"{before}{subject}{kind}月份为{expected}{after}"
    if rewritten.count("**") % 2:
        rewritten = rewritten.replace("**", "")
    return segment[: sentence.start()] + rewritten + segment[sentence.end() :]


def money_text_warnings(markdown: str) -> list[str]:
    """仅核对紧邻括号中的同一金额，不把正文中的不同指标强行比较。"""
    warnings: list[str] = []
    for match in _MONEY_PAIR.finditer(markdown.replace("**", "")):
        number = Decimal(match["large"].replace(",", ""))
        base = Decimal(match["base"].replace(",", ""))
        digits = len(match["large"].split(".", 1)[1]) if "." in match["large"] else 0
        rounded = (base / _MONEY_UNITS[match["unit"]]).quantize(
            Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP
        )
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
            text = markdown[marker.end() : end].replace("**", "")
            pattern = r"(?<![\d–—~-])(?P<month>\d{1,2})月(?:(?!\d{1,2}月)[^。；\n]){0,60}?(?P<kind>最高|最低|峰值|低点)"
            # “低点：2月”与“2月为最低”使用相同的冻结极值判定。
            text = re.sub(r"(低点|峰值)[：:]\s*(\d{1,2})月", r"\2月为\1", text)
            # 后置月份只属于括号前的极值，不能被下一分句的极值词接走。
            text = re.sub(
                rf"(?P<kind>最高|最低|峰值|低点)(?:值)?\s*(?:为|是|[：:])?\s*"
                rf"{_DISPLAYED_VALUE}\s*[（(](?:出现在|出现于|在|于)(?P<month>\d{{1,2}})月[）)]",
                lambda m: f"{m['month']}月为{m['kind']}",
                text,
            )
            # 范围端点不是另一项月份断言；掩去“月”但保持字符位置，
            # 使“2月为1—10月最低”仍可匹配2月，范围则从原文取回。
            masked = re.sub(
                r"(?<!\d)\d{1,2}月?\s*[–—~～至到-]\s*\d{1,2}月",
                lambda m: m[0].replace("月", "期"),
                text,
            )
            # “11月较10月减少，为最低值”中的10月是比较基期，不是极值主语。
            masked = re.sub(
                r"(?:较|相比于?|相较于?|比)\s*\d{1,2}月", lambda m: m[0].replace("月", "期"), masked
            )
            for match in re.finditer(pattern, masked):
                if re.search(
                    r"占比|比重|比例|环比|同比|增长率|降幅|增幅|组织明细|明细分组|分组组合",
                    match[0],
                ) or re.match(r"单项|单条", text[match.end() :]):
                    # 分项比例、变化率或组织明细极值不能用全院原始月序列复核。
                    continue
                high = match["kind"] in {"最高", "峰值"}
                clause_start = (
                    max(text.rfind(separator, 0, match.start()) for separator in ("。", "；", "\n"))
                    + 1
                )
                local = text[clause_start : match.end()]
                named_years = set(re.findall(r"(?<!\d)(\d{4})年", local))
                if named_years and named_years != {labels[0][:4]}:
                    continue
                ranges = list(
                    re.finditer(r"(?<!\d)(\d{1,2})月?\s*[–—~～至到-]\s*(\d{1,2})月", local)
                )
                selected = monthly
                if ranges:
                    start, stop = int(ranges[-1][1]), int(ranges[-1][2])
                    if start > stop or not all(
                        month in monthly for month in range(start, stop + 1)
                    ):
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
                    warnings.append(
                        f"月度极值陈述需复核：{match['month']}月被写为{label}，冻结月序列的{label}月份为{expected}。"
                    )
            trend_pattern = r"(?<!\d)(\d{1,2})月?\s*[–—~～至到-]\s*(\d{1,2})月[^。；\n]{0,20}?连续(?:[一二三四五六七八九十\d]+个月)?(?:上升|增长|增加|回升|下降|减少|回落)"
            for match in re.finditer(trend_pattern, text):
                clause_start = (
                    max(text.rfind(separator, 0, match.start()) for separator in ("。", "；", "\n"))
                    + 1
                )
                named_years = set(re.findall(r"(?<!\d)(\d{4})年", text[clause_start : match.end()]))
                if named_years and named_years != {labels[0][:4]}:
                    continue
                start, stop = int(match[1]), int(match[2])
                if start >= stop or not all(month in monthly for month in range(start, stop + 1)):
                    continue
                rising = not re.search(r"下降|减少|回落", match[0])
                inconsistent = [
                    f"{month}月→{month + 1}月"
                    for month in range(start, stop)
                    if (
                        monthly[month + 1] <= monthly[month]
                        if rising
                        else monthly[month + 1] >= monthly[month]
                    )
                ]
                if inconsistent:
                    warnings.append(
                        f"连续趋势陈述需复核：{match[0]}，冻结月序列在{'、'.join(inconsistent)}不满足该趋势。"
                    )
    return list(dict.fromkeys(warnings))
