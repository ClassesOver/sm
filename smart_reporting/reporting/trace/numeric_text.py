"""从冻结事实生成正文数值；模型只选择数值引用，不负责换算或千分位。"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from loguru import logger

from ..hospital_operation.deterministic_analysis import DeterministicAnalysisBundle

_MONEY_UNITS = {"元": Decimal(1), "万元": Decimal(10_000), "亿元": Decimal(100_000_000)}
_VALUE_TOKEN = re.compile(r"\{\{value:[^{}\r\n]+\}\}")
_NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_MONEY_PAIR = re.compile(
    rf"(?<![\d.,])(?P<large>{_NUMBER})\s*(?P<unit>亿元|万元)"
    rf"\s*[（(]\s*(?P<base>{_NUMBER})\s*元\s*[）)]"
)


def format_fact_value(value: Any, unit: str | None, display_unit: str | None = None) -> str:
    number = Decimal(str(value))
    target = display_unit or unit
    if target != unit:
        number = number * _MONEY_UNITS[unit] / _MONEY_UNITS[target]
    if target in {"万元", "亿元", "%", "‰"} or number != number.to_integral_value():
        text = f"{number.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,f}"
    else:
        text = f"{number:,.0f}"
    return text + (target or "")


def budget_comparison_values(bundle: DeterministicAnalysisBundle) -> list[dict[str, Any]]:
    """仅对唯一、同快照、同范围的 budget_/actual_ 月度事实提供数学比较。"""
    comparisons = []
    for actual in bundle.metrics:
        if not actual.fact_id or not actual.field.startswith("actual_") or not actual.unit:
            continue
        budgets = [fact for fact in bundle.metrics if fact.field == "budget_" + actual.field.removeprefix("actual_")
                   and fact.dataset_id == actual.dataset_id and fact.dataset_sha256 == actual.dataset_sha256
                   and fact.scope == actual.scope and fact.unit == actual.unit
                   and fact.field_ref.rsplit(".", 1)[0] == actual.field_ref.rsplit(".", 1)[0]
                   and fact.period_roles == actual.period_roles]
        if len(budgets) != 1 or not budgets[0].fact_id:
            continue
        budget = budgets[0]
        monthly = []
        for fact in (actual, budget):
            if fact.aggregation != "sum" or fact.period_granularity != "month" or not 0 < len(fact.period_values) <= 12:
                break
            if any(not re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", value.period) for value in fact.period_values):
                break
            values = {value.period[:7]: Decimal(str(value.value)) for value in fact.period_values}
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
            for window, current, planned in ((period, numerator, denominator),
                                             (f"{periods[0]}..{period}", actual_running, budget_running)):
                comparisons.append({
                    "actualFactId": actual.fact_id, "budgetFactId": budget.fact_id,
                    "numeratorMetric": actual.field, "denominatorMetric": budget.field,
                    "period": window, "unit": actual.unit,
                    "difference": current - planned,
                    "percentage": current / planned * 100 if planned != 0 else None,
                })
    return comparisons


def frozen_number_catalog(contents: Iterable[str]) -> dict[str, str]:
    catalog: dict[str, str] = {}
    for content in contents:
        try:
            bundle = DeterministicAnalysisBundle.model_validate_json(content)
        except ValueError:
            continue
        document = bundle.model_dump(mode="json", by_alias=True)
        for array, fields in (
            ("metrics", ("total", "average", "minimum", "maximum")),
            ("comparisons", ("currentTotal", "baselineTotal", "change", "changeRate")),
            ("derivedMetrics", ("value", "percentage", "numerator", "denominator", "difference")),
            ("reconciliations", ("difference",)),
        ):
            for entry in document[array]:
                fact_id = entry.get("factId")
                if not fact_id:
                    continue
                values = [(field, entry.get(field)) for field in fields]
                values.extend((f"periodValues.{index}", item["value"]) for index, item in enumerate(entry.get("periodValues", ())))
                for groups_key in ("topGroups", "bottomGroups"):
                    values.extend((f"{groups_key}.{index}", item["value"])
                                  for index, item in enumerate(entry.get(groups_key, ())))
                periods = entry.get("periodValues", ())
                if (array == "metrics" and entry.get("aggregation") == "sum"
                        and entry.get("periodGranularity") == "month" and periods
                        and len(periods) <= 12
                        and all(re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", item["period"]) for item in periods)
                        and len({item["period"][:7] for item in periods}) == len(periods)
                        and len({item["period"][:4] for item in periods}) == 1):
                    # 均值分母使用实际月桶数，前缀累计从原值相加，禁止先舍入再累加。
                    amounts = [Decimal(str(item["value"])) for item in periods]
                    values.extend((("monthlyAverage", sum(amounts) / len(amounts)),
                                   ("monthlyMinimum", min(amounts)), ("monthlyMaximum", max(amounts))))
                    running = Decimal(0)
                    for index, amount in enumerate(amounts):
                        running += amount
                        values.append((f"periodTotals.0-{index}", running))

                for field, value in values:
                    if value is None:
                        continue
                    # 派生事实的 unit 是分子/差额单位，比值本身无量纲。
                    unit = ("%" if field in {"changeRate", "percentage"}
                            else None if array == "derivedMetrics" and field == "value"
                            else entry.get("unit"))
                    units = _MONEY_UNITS if unit in _MONEY_UNITS else (unit or "",)
                    for target in units:
                        token = f"{{{{value:{fact_id}:{field}:{target}}}}}"
                        text = format_fact_value(value, unit, target or None)
                        if token in catalog and catalog[token] != text:
                            # 同一事实身份在不同证据中出现冲突时，不选择任意一个值。
                            catalog[token] = "数值待核实"
                        else:
                            catalog[token] = text
        for comparison in budget_comparison_values(bundle):
            for field, unit in (("difference", comparison["unit"]), ("percentage", "%")):
                if comparison[field] is None:
                    continue
                for target in (_MONEY_UNITS if unit in _MONEY_UNITS else (unit,)):
                    token = f"{{{{value:{comparison['actualFactId']}:budgetComparison.{comparison['budgetFactId']}.{comparison['period']}.{field}:{target}}}}}"
                    display = format_fact_value(comparison[field], unit, target)
                    if token in catalog and catalog[token] != display:
                        catalog[token] = "数值待核实"
                    else:
                        catalog[token] = display
    return catalog


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
        for fact in bundle.metrics:
            if not fact.fact_id or fact.fact_id in seen:
                continue
            seen.add(fact.fact_id)

            def reference(field: str) -> str | None:
                token = f"{{{{value:{fact.fact_id}:{field}:{fact.unit or ''}}}}}"
                return token if token in catalog and catalog[token] != "数值待核实" else None

            periods = [item.period for item in fact.period_values]
            item: dict[str, Any] = {
                "factId": fact.fact_id, "analysisId": bundle.analysis_id,
                "datasetId": fact.dataset_id,
                "metric": (field_definitions or {}).get(fact.field, fact.field),
                "metricCodes": list(fact.metric_codes), "scope": fact.scope,
                "unit": fact.unit, "periodRoles": list(fact.period_roles),
                "periodGranularity": fact.period_granularity,
                "total": {"reference": reference("total"), "periods": periods,
                          "periodStart": fact.period_start, "periodEnd": fact.period_end},
                "rowStatistics": {"average": reference("average"), "minimum": reference("minimum"),
                                  "maximum": reference("maximum"),
                                  "meaning": "原始行统计，不能称为月均值或月度极值"},
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
                                     for index, period in enumerate(periods)],
                    "meaning": "包含已登记的零值月份；零值本身不证明未入账或缺失。局部极值必须明确子期间",
                }
            item["groups"] = [{"group": group.group, "reference": reference(f"{key}.{index}"),
                               "meaning": "完整分组组合的数值，不能称为单一科室或院区累计"}
                              for key, groups in (("topGroups", fact.top_groups), ("bottomGroups", fact.bottom_groups))
                              for index, group in enumerate(groups)]
            item["budgetComparisons"] = []
            for comparison in comparisons:
                if comparison["actualFactId"] != fact.fact_id:
                    continue
                references = {}
                for field, unit in (("difference", comparison["unit"]), ("percentage", "%")):
                    token = f"{{{{value:{fact.fact_id}:budgetComparison.{comparison['budgetFactId']}.{comparison['period']}.{field}:{unit}}}}}"
                    references[field] = token if token in catalog and catalog[token] != "数值待核实" else None
                item["budgetComparisons"].append({
                    "budgetFactId": comparison["budgetFactId"], "period": comparison["period"],
                    "numeratorMetric": comparison["numeratorMetric"], "denominatorMetric": comparison["denominatorMetric"],
                    "references": references, "meaning": "同范围实际减预算、实际除预算×100%；百分数引用为空表示分母为零",
                })
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
                "periodStart": fact.period_start, "periodEnd": fact.period_end,
                "numeratorMetric": fact.numerator_metric, "denominatorMetric": fact.denominator_metric,
                "references": references,
                "meaning": "分母为零时不可计算；分子为零且分母非零时为0%。仅使用已登记的比率期间，不扩展为月度比率",
            })
    return guide


def render_frozen_numbers(markdown: str, catalog: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        text = catalog.get(match[0])
        if text is None:
            logger.warning("report_number_reference_unavailable token={}", match[0])
            return "数值待核实"
        return text

    rendered = _VALUE_TOKEN.sub(replace, markdown)
    for warning in money_text_warnings(rendered):
        logger.warning("report_number_conversion_warning message={}", warning)
    return rendered


def replace_unregistered_numbers(markdown: str, contents: Iterable[str]) -> str:
    """把没有冻结依据的带单位数字替换为待核实，避免手算结果落盘。"""

    contents = tuple(contents)
    catalog = frozen_number_catalog(contents)
    # 没有可解析的冻结事实时，服务端无法判断正文数字是否为派生值；
    # 保留原文，避免把仅含原始证据的旧格式内容全部改成“待核实”。
    if not catalog:
        return markdown
    known: dict[str, set[Decimal]] = {}
    value_pattern = re.compile(
        rf"(?P<number>{_NUMBER})(?P<unit>亿元|万元|元|万人次|人次|床日|%)"
    )
    for display in catalog.values():
        match = value_pattern.fullmatch(display)
        if match:
            known.setdefault(match["unit"], set()).add(Decimal(match["number"].replace(",", "")))

    def replace(match: re.Match[str]) -> str:
        number = Decimal(match["number"].replace(",", ""))
        digits = len(match["number"].split(".", 1)[1]) if "." in match["number"] else 0
        quantum = Decimal(1).scaleb(-digits)
        if any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in known.get(match["unit"], ())):
            return match[0]
        logger.warning("report_unregistered_number_replaced value={}", match[0])
        return "待核实"

    return re.sub(
        r"(?<![\d.,])(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?P<unit>亿元|万元|元|万人次|人次|床日|%)",
        replace,
        markdown,
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
    warnings = period_extrema_warnings(markdown, normalized)
    corrected = markdown
    for warning in warnings:
        match = re.search(r"(\d+)月被写为(最高|最低)，冻结月序列的\2月份为([^。]+)", warning)
        if match is None:
            continue
        wrong_month, kind, expected = match.groups()
        clause = re.compile(
            rf"(?<!\d){wrong_month}月[^。；\n]{{0,60}}?(?:最高|最低|峰值|低点)(?:值|月份)?[^。；\n]*"
        )
        corrected, count = clause.subn(
            f"冻结序列的{kind}月份为{expected}", corrected, count=1
        )
        if count:
            logger.warning("report_period_extrema_corrected wrong_month={} expected_months={}", wrong_month, expected)
    return corrected


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
        metrics = [entry for entry in bundle.get("metrics", ())
                   if "current" in entry.get("periodRoles", ())]
        if len(metrics) != 1 or metrics[0].get("periodGranularity") != "month":
            continue
        periods = metrics[0].get("periodValues", ())
        if not periods:
            continue
        labels = [str(item["period"]) for item in periods]
        if any(not re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", label) for label in labels):
            continue
        if len({label[:4] for label in labels}) != 1:
            continue
        monthly = {int(item["period"][5:7]): Decimal(str(item["value"])) for item in periods}
        if len(monthly) != len(periods):
            continue
        for index, marker in enumerate(markers):
            if marker[1] != bundle.get("analysisId"):
                continue
            end = markers[index + 1].start() if index + 1 < len(markers) else len(markdown)
            text = markdown[marker.end():end].replace("**", "")
            pattern = r"(?<![\d–—~-])(?P<month>\d{1,2})月(?:(?!\d{1,2}月)[^。；\n]){0,60}?(?P<kind>最高|最低|峰值|低点)"
            # “低点：2月”与“2月为最低”使用相同的冻结极值判定。
            text = re.sub(r"(低点|峰值)[：:]\s*(\d{1,2})月", r"\2月为\1", text)
            for match in re.finditer(pattern, text):
                high = match["kind"] in {"最高", "峰值"}
                local = text[text.rfind("\n\n", 0, match.start()) + 2:match.end()] if "\n\n" in text[:match.start()] else text[:match.end()]
                ranges = list(re.finditer(r"(?<!\d)(\d{1,2})月?\s*[–—~～至到-]\s*(\d{1,2})月", local))
                selected = monthly
                if ranges:
                    start, stop = int(ranges[-1][1]), int(ranges[-1][2])
                    if start > stop or not all(month in monthly for month in range(start, stop + 1)):
                        continue
                    selected = {month: monthly[month] for month in range(start, stop + 1)}
                extreme = (max if high else min)(selected.values())
                months = {month for month, value in selected.items() if value == extreme}
                if int(match["month"]) not in months:
                    label = "最高" if high else "最低"
                    expected = "、".join(f"{month}月" for month in sorted(months))
                    warnings.append(f"月度极值陈述需复核：{match['month']}月被写为{label}，冻结月序列的{label}月份为{expected}。")
            trend_pattern = r"(?<!\d)(\d{1,2})月?\s*[–—~～至到-]\s*(\d{1,2})月[^。；\n]{0,20}?连续(?:[一二三四五六七八九十\d]+个月)?(?:上升|增长|增加|回升|下降|减少|回落)"
            for match in re.finditer(trend_pattern, text):
                start, stop = int(match[1]), int(match[2])
                if start >= stop or not all(month in monthly for month in range(start, stop + 1)):
                    continue
                rising = not re.search(r"下降|减少|回落", match[0])
                inconsistent = [f"{month}月→{month + 1}月" for month in range(start, stop)
                                if (monthly[month + 1] <= monthly[month] if rising else monthly[month + 1] >= monthly[month])]
                if inconsistent:
                    warnings.append(f"连续趋势陈述需复核：{match[0]}，冻结月序列在{'、'.join(inconsistent)}不满足该趋势。")
    return list(dict.fromkeys(warnings))
