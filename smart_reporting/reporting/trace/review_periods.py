"""正文复核：期间、窗口与统计口径（月均、全年、合计、年度标注、局部极值）。"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .numeric_text import (
    _frozen_number_entries,
    _unit_scales,
    period_extrema_warnings,
)
from .review_common import _AGGREGATION_NOUNS, _CLAUSE_BREAK, _VALUE, _documents


def _paragraph_extrema_warnings(text: str, bundles: list[dict[str, Any]],
                               field_definitions: Mapping[str, str]) -> list[str]:
    warnings = []
    markers = list(re.finditer(r"\[\[analysis:([^\]]+)\]\]", text))
    labels = sorted({label for label in field_definitions.values() if label},
                    key=lambda label: (-len(label), label))
    if not labels:
        return warnings
    label_pattern = re.compile("|".join(re.escape(label) for label in labels))
    for paragraph in re.finditer(r"[^\n]+(?:\n(?!\s*\n)[^\n]+)*", text):
        if paragraph[0].lstrip().startswith("#"):
            continue
        preceding = [marker for marker in markers if marker.start() <= paragraph.end()]
        analysis_id = preceding[-1][1] if preceding else None
        # 按最长完整定义识别每个出现位置；同时明确提及总量和子集时保留歧义。
        matched_labels = {match[0] for match in label_pattern.finditer(paragraph[0])}
        candidates = []
        for bundle in bundles:
            if analysis_id is not None and bundle.get("analysisId") != analysis_id:
                continue
            for entry in bundle.get("metrics", ()):
                label = field_definitions.get(entry.get("field", ""))
                if label in matched_labels and "current" in entry.get("periodRoles", ()):
                    candidates.append((label, bundle, entry))
        unique = {(label, json.dumps(entry, sort_keys=True, ensure_ascii=False)):
                  (label, bundle, entry) for label, bundle, entry in candidates}
        if len(unique) != 1:
            continue
        label, bundle, entry = next(iter(unique.values()))
        local = f"[[analysis:{bundle['analysisId']}]]" + paragraph[0]
        warnings.extend(f"{label}：{warning}" for warning in period_extrema_warnings(
            local, [{**bundle, "metrics": [entry]}]))
    return warnings


def _explicit_year_extrema_warnings(
    text: str, bundles: list[dict[str, Any]], field_definitions: Mapping[str, str],
    fact_ids: set[str] | None,
) -> list[str]:
    """明确写出的年份单独匹配冻结月序列，覆盖上年同期且避免跨年套值。"""
    warnings = []
    markers = list(re.finditer(r"\[\[analysis:([^\]]+)\]\]", text))
    labels = sorted({label for label in field_definitions.values() if label},
                    key=lambda label: (-len(label), label))
    label_pattern = re.compile("|".join(re.escape(label) for label in labels)) if labels else None
    for clause in re.finditer(r"[^。；\n]+", text):
        years = set(re.findall(r"(?<!\d)(\d{4})年", clause[0]))
        if len(years) != 1 or not re.search(r"最高|最低|峰值|低点|连续", clause[0]):
            continue
        year = next(iter(years))
        preceding = [marker for marker in markers if marker.start() <= clause.start()]
        analysis_id = preceding[-1][1] if preceding else None
        matched_labels = {match[0] for match in label_pattern.finditer(clause[0])} if label_pattern else set()
        candidates = {}
        for bundle in bundles:
            if analysis_id is not None and bundle.get("analysisId") != analysis_id:
                continue
            for entry in bundle.get("metrics", ()):
                if fact_ids is not None and entry.get("factId") not in fact_ids:
                    continue
                if entry.get("aggregation") != "sum" or entry.get("periodGranularity") != "month":
                    continue
                periods = entry.get("periodValues", ())
                if not periods or {str(item["period"])[:4] for item in periods} != {year}:
                    continue
                if matched_labels and field_definitions.get(entry.get("field", "")) not in matched_labels:
                    continue
                candidates[json.dumps(entry, sort_keys=True, ensure_ascii=False)] = (bundle, entry)
        if len(candidates) != 1:
            continue
        bundle, entry = next(iter(candidates.values()))
        local = f"[[analysis:{bundle['analysisId']}]]" + clause[0]
        # 只改变复核视图的选择角色，原始冻结事实和文件身份保持不变。
        selected = {**entry, "periodRoles": ["current"]}
        prefix = f"{year}年：" if "current" not in entry.get("periodRoles", ()) else ""
        warnings.extend(f"{prefix}{warning}" for warning in period_extrema_warnings(
            local, [{**bundle, "metrics": [selected]}]))
    return warnings


_MONTHLY_AVERAGE_CLAIM = re.compile(
    r"(?:月均|月平均|平均每月|每月平均)[^。；，,\n\d]{0,12}?"
    r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?P<unit>亿元|万元|元|万人次|人次|床日)"
)


def _monthly_average_warnings(text: str, contents: Iterable[str]) -> list[str]:
    """“月均X”中的 X 不是登记月均值、却等于原始行平均或合计/单月值时提示复核（软告警）。

    原始行统计的 average 按数据行求平均，行数不等于月数时不是月均值；合计或单月值
    写成月均同样是口径错误。对不上任何登记值的数字由无依据数值检查处理。
    """
    monthly: dict[str, set[Decimal]] = {}
    row_average: dict[str, set[Decimal]] = {}
    others: dict[str, set[Decimal]] = {}
    for token, value, unit, target in _frozen_number_entries(contents):
        display_unit = target or unit
        if not display_unit or value is None:
            continue
        number = Decimal(str(value))
        if display_unit != unit and (scales := _unit_scales(unit)) is not None:
            number = number * scales[unit] / scales[display_unit]
        field = token[2:-2].split(":")[2]
        bucket = monthly if field == "monthlyAverage" else row_average if field == "average" else others
        bucket.setdefault(display_unit, set()).add(number)
    warnings: list[str] = []
    for match in _MONTHLY_AVERAGE_CLAIM.finditer(text):
        number = Decimal(match["number"].replace(",", ""))
        quantum = Decimal(1).scaleb(-(len(match["number"].split(".")[1]) if "." in match["number"] else 0))

        def matches(values: dict[str, set[Decimal]]) -> bool:
            return any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number
                       for value in values.get(match["unit"], ()))

        if matches(monthly):
            continue
        expected = sorted(monthly.get(match["unit"], ()))
        hint = (f"冻结月均值为{expected[0].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,f}{match['unit']}。"
                if len(expected) == 1 else "请改用月度统计中的月均值引用。")
        if matches(row_average):
            warnings.append(f"月均值需复核：{match[0]}使用的是原始行平均值，不是月均值；{hint}")
        elif expected and matches(others):
            warnings.append(f"月均值需复核：{match[0]}对应的是合计、单月或累计登记值，不是月均值；{hint}")
    return list(dict.fromkeys(warnings))


def _full_year_warnings(text: str, contents: Iterable[str], documents: list[dict[str, Any]]) -> list[str]:
    """“全年”配不足 12 个月的完整期间合计时提示复核（软告警）。

    冻结数据只覆盖 1—10 月时，10 个月合计写成“2025年全年收入…”会被读成全年实际；
    只在分句数值等于该指标完整期间合计时判定，“全年预算/目标”不在此列。
    """
    partial: dict[str, str] = {}
    labels: dict[str, str] = {}
    for document in documents:
        for entry in document.get("metrics") or ():
            if not isinstance(entry, dict) or entry.get("periodGranularity") != "month":
                continue
            if isinstance(entry.get("factId"), str):
                labels[entry["factId"]] = _AGGREGATION_NOUNS.get(entry.get("aggregation"), "合计")
            periods = [str(item.get("period", "")) for item in entry.get("periodValues") or ()
                       if isinstance(item, dict)]
            months = sorted({int(period[5:7]) for period in periods
                             if re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", period)})
            years = {period[:4] for period in periods}
            if months and len(years) == 1 and len(months) < 12 and isinstance(entry.get("factId"), str):
                span = f"{months[0]}—{months[-1]}月" if months == list(range(months[0], months[-1] + 1)) \
                    else "、".join(f"{month}月" for month in months)
                partial[entry["factId"]] = f"{years.pop()}年{span}（{len(months)}个月）"
    if not partial:
        return []
    totals: dict[str, list[tuple[str, Decimal]]] = {}
    for token, value, unit, target in _frozen_number_entries(contents):
        _, fact_id, field, *_rest = token[2:-2].split(":")
        display_unit = target or unit
        if field != "total" or fact_id not in partial or not display_unit or value is None:
            continue
        number = Decimal(str(value))
        if display_unit != unit and (scales := _unit_scales(unit)) is not None:
            number = number * scales[unit] / scales[display_unit]
        totals.setdefault(display_unit, []).append((fact_id, number))
    warnings: list[str] = []
    for sentence in re.split(r"[。；\n]", text):
        if "全年" not in sentence or re.search(r"全年(?:预算|目标|计划)", sentence):
            continue
        for match in _VALUE.finditer(sentence):
            number = Decimal(match[1].replace(",", ""))
            quantum = Decimal(1).scaleb(-(len(match[1].split(".")[1]) if "." in match[1] else 0))
            for fact_id, value in totals.get(match[2], ()):
                if value.quantize(quantum, rounding=ROUND_HALF_UP) == number:
                    warnings.append(
                        f"期间口径需复核：{match[0]}是{partial[fact_id]}的{labels.get(fact_id, '合计')}，"
                        "不能称为全年；请写明实际覆盖月份。"
                    )
    return list(dict.fromkeys(warnings))


def _non_additive_total_warnings(text: str, contents: Iterable[str], documents: list[dict[str, Any]]) -> list[str]:
    """平均值、最小值、最大值写成“合计/累计/总计”时提示复核（软告警）。

    平均口径指标（床位使用率等）的完整期间值是均值，不是加总；只在分句数值等于该
    指标完整期间值时判定。
    """
    labels = {entry["factId"]: _AGGREGATION_NOUNS[entry["aggregation"]]
              for document in documents for entry in document.get("metrics") or ()
              if isinstance(entry, dict) and isinstance(entry.get("factId"), str)
              and entry.get("aggregation") in {"average", "min", "max"}}
    if not labels:
        return []
    values: dict[str, list[tuple[str, Decimal]]] = {}
    for token, value, unit, target in _frozen_number_entries(contents):
        _, fact_id, field, *_rest = token[2:-2].split(":")
        display_unit = target or unit
        if field != "total" or fact_id not in labels or not display_unit or value is None:
            continue
        number = Decimal(str(value))
        if display_unit != unit and (scales := _unit_scales(unit)) is not None:
            number = number * scales[unit] / scales[display_unit]
        values.setdefault(display_unit, []).append((fact_id, number))
    warnings: list[str] = []
    for sentence in _CLAUSE_BREAK.split(text):
        if not re.search(r"合计|累计|总计|总额|总和|汇总", sentence):
            continue
        for match in _VALUE.finditer(sentence):
            number = Decimal(match[1].replace(",", ""))
            quantum = Decimal(1).scaleb(-(len(match[1].split(".")[1]) if "." in match[1] else 0))
            for fact_id, value in values.get(match[2], ()):
                if value.quantize(quantum, rounding=ROUND_HALF_UP) == number:
                    warnings.append(
                        f"统计口径需复核：{match[0]}是{labels[fact_id]}，不能称为合计或累计；"
                        f"请写明为{labels[fact_id]}。"
                    )
    return list(dict.fromkeys(warnings))


def _comparison_window_warnings(text: str, contents: Iterable[str], documents: list[dict[str, Any]]) -> list[str]:
    """多月窗口的同比/环比变化写成单月变化时提示复核（软告警）。

    “9月收入同比增长5.03%”中的 5.03% 若是 1—9 月累计窗口的变化率，读者会理解为
    9 月单月；只在分句点名单个月份、没有区间或累计表述，且数值等于多月窗口变化时判定。
    """
    windows: dict[str, str] = {}
    for document in documents:
        for entry in document.get("comparisons") or ():
            if not isinstance(entry, dict) or not isinstance(entry.get("factId"), str):
                continue
            start, end = str(entry.get("periodStart") or ""), str(entry.get("periodEnd") or "")
            if (re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", start) and re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", end)
                    and start[:7] != end[:7]):
                same_year = start[:4] == end[:4]
                windows[entry["factId"]] = (
                    f"{start[:4]}年{int(start[5:7])}—{int(end[5:7])}月" if same_year
                    else f"{start[:4]}年{int(start[5:7])}月至{end[:4]}年{int(end[5:7])}月"
                )
    if not windows:
        return []
    values: dict[str, list[tuple[str, Decimal]]] = {}
    for token, value, unit, target in _frozen_number_entries(contents):
        _, fact_id, field, *_rest = token[2:-2].split(":")
        display_unit = target or unit
        if field not in {"change", "changeRate"} or fact_id not in windows or not display_unit or value is None:
            continue
        number = Decimal(str(value))
        if display_unit != unit and (scales := _unit_scales(unit)) is not None:
            number = number * scales[unit] / scales[display_unit]
        values.setdefault(display_unit, []).append((fact_id, abs(number)))
    warnings: list[str] = []
    for clause in _CLAUSE_BREAK.split(text):
        months = re.findall(r"(?<![\d—–~～至到-])(\d{1,2})月(?!\s*[—–~～至到-]\s*\d)", clause)
        if (len(set(months)) != 1 or not re.search(r"同比|环比|较上年|较去年|较上月", clause)
                or re.search(r"\d{1,2}月?\s*[—–~～至到-]\s*\d{1,2}月|累计|截至|前三季度|上半年|下半年|季度|全年", clause)):
            continue
        for match in _VALUE.finditer(clause):
            number = abs(Decimal(match[1].replace(",", "")))
            quantum = Decimal(1).scaleb(-(len(match[1].split(".")[1]) if "." in match[1] else 0))
            for fact_id, value in values.get(match[2], ()):
                if value.quantize(quantum, rounding=ROUND_HALF_UP) == number:
                    warnings.append(
                        f"比较口径需复核：{match[0]}是{windows[fact_id]}的累计比较结果，"
                        f"不是{months[0]}月单月；请写明比较期间。"
                    )
    return list(dict.fromkeys(warnings))


def _annual_budget_denominator_warnings(text: str, bundles: list[dict[str, Any]]) -> list[str]:
    warnings = []
    annual_pattern = re.compile(r"(?:全年|年度)预算(?:总额|总量)\s*(?:为|是|：|:)?\s*(" + _VALUE.pattern + r")")
    rate_pattern = re.compile(r"(?:执行率|完成率)\s*(?:约为|为|约|是|：|:)?\s*([\d.]+)\s*%")
    for paragraph in re.split(r"\n\s*\n", text):
        annual = annual_pattern.search(paragraph)
        rates = list(rate_pattern.finditer(paragraph))
        ranges = {(int(m[1]), int(m[2])) for m in re.finditer(r"(?<!\d)(\d{1,2})月?\s*[–—~～至到-]\s*(\d{1,2})月", paragraph)}
        if annual is None or len(rates) != 1 or len(ranges) != 1:
            continue
        if re.search(r"(?:按|以)[^。；\n]{0,80}(?:同期|同期间)预算[^。；\n]{0,25}(?:之比|分母)", paragraph):
            # 同段可同时介绍年度目标和同期预算；明确的同期比率不套年度分母。
            continue
        start, stop = next(iter(ranges))
        if not 1 <= start <= stop <= 12:
            continue
        denominator_value = _VALUE.fullmatch(annual[1])
        candidates = []
        for bundle in bundles:
            metrics = bundle.get("metrics", ())
            for actual in metrics:
                if not actual.get("field", "").startswith("actual_") or "current" not in actual.get("periodRoles", ()):
                    continue
                budgets = [b for b in metrics if b.get("field") == "budget_" + actual["field"].removeprefix("actual_")
                           and all(b.get(k) == actual.get(k) for k in ("datasetId", "datasetSha256", "scope", "unit", "periodRoles"))
                           and b.get("fieldRef", "").rsplit(".", 1)[0] == actual.get("fieldRef", "").rsplit(".", 1)[0]]
                if len(budgets) != 1:
                    continue
                budget = budgets[0]
                if any(f.get("aggregation") != "sum" or f.get("periodGranularity") != "month" for f in (actual, budget)):
                    continue
                actual_periods = actual.get("periodValues", ())
                budget_periods = budget.get("periodValues", ())
                labels = [p["period"] for p in (*actual_periods, *budget_periods)]
                if not labels or any(not re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", p) for p in labels) or len({p[:4] for p in labels}) != 1:
                    continue
                monthly = {int(p["period"][5:7]): Decimal(str(p["value"])) for p in actual_periods}
                if len(monthly) != len(actual_periods) or len(budget_periods) != 12 or {int(p["period"][5:7]) for p in budget_periods} != set(range(1, 13)):
                    continue
                if not all(month in monthly for month in range(start, stop + 1)):
                    continue
                numerator = sum(monthly[month] for month in range(start, stop + 1))
                denominator = Decimal(str(budget["total"]))
                unit = actual.get("unit")
                if denominator == 0 or denominator_value[2] != unit or Decimal(denominator_value[1].replace(",", "")) != denominator:
                    continue
                if not any(m[2] == unit and Decimal(m[1].replace(",", "")) == numerator for m in _VALUE.finditer(paragraph[:annual.start()])):
                    continue
                candidates.append(numerator / denominator * 100)
        if len(set(candidates)) != 1:
            continue
        written = Decimal(rates[0][1])
        precision = Decimal(1).scaleb(-len(rates[0][1].partition(".")[2]))
        expected = candidates[0].quantize(precision, rounding=ROUND_HALF_UP)
        if written != expected:
            warnings.append(f"预算分母口径需复核：{start}—{stop}月实际与全年预算之比应为{expected}%，正文写为{written}%；若使用同期预算，请明确同期分母及金额。")
    return warnings


def _years_between(start: Any, end: Any) -> frozenset[int] | None:
    years = [int(value[:4]) for value in (start, end) if isinstance(value, str) and re.match(r"\d{4}", value)]
    return frozenset(range(min(years), max(years) + 1)) if years else None


def _registered_value_years(contents: Iterable[str]) -> list[tuple[str, Decimal, frozenset[int] | None]]:
    """冻结数值（按显示单位）及其登记期间覆盖的年份；期间未登记时为 None。"""
    contents = tuple(contents)
    fact_years: dict[str, frozenset[int] | None] = {}
    fact_periods: dict[str, list[str]] = {}
    for document in _documents(contents):
        for array in ("metrics", "comparisons", "derivedMetrics", "reconciliations"):
            for entry in document.get(array) or ():
                if not isinstance(entry, dict) or not isinstance(entry.get("factId"), str):
                    continue
                periods = [str(item.get("period", "")) for item in entry.get("periodValues") or ()
                           if isinstance(item, dict)]
                fact_periods[entry["factId"]] = periods
                fact_years[entry["factId"]] = (
                    _years_between(entry.get("periodStart"), entry.get("periodEnd"))
                    or _years_between(periods[0] if periods else None, periods[-1] if periods else None)
                )
    values: list[tuple[str, Decimal, frozenset[int] | None]] = []
    for token, value, unit, target in _frozen_number_entries(contents):
        _, fact_id, field, *_rest = token[2:-2].split(":")
        if field == "baselineTotal":
            years = None
        elif field.startswith("periodValues."):
            periods = fact_periods.get(fact_id, [])
            index = int(field.split(".")[1])
            years = _years_between(periods[index], periods[index]) if index < len(periods) else None
        elif field.startswith("budgetComparison."):
            period = field.split(".")[2]
            years = _years_between(period, period)
        else:
            years = fact_years.get(fact_id)
        display_unit = target or unit
        if not display_unit:
            continue
        number = Decimal(str(value))
        if display_unit != unit and (scales := _unit_scales(unit)) is not None:
            number = number * scales[unit] / scales[display_unit]
        values.append((display_unit, number, years))
    return values


def _year_label_warnings(text: str, contents: Iterable[str]) -> list[str]:
    """只写一个年份的句子里，数值仅对应其他年份的登记期间时，提示年份标注需复核。"""
    registered = _registered_value_years(contents)
    warnings: list[str] = []
    for sentence in re.split(r"[。；\n]", text):
        years = {int(year) for year in re.findall(r"(?<!\d)(20\d{2})年", sentence)}
        if len(years) != 1:
            continue
        year = years.pop()
        for match in _VALUE.finditer(sentence):
            number = Decimal(match[1].replace(",", ""))
            quantum = Decimal(1).scaleb(-(len(match[1].split(".")[1]) if "." in match[1] else 0))
            candidates = [years for unit, value, years in registered
                          if unit == match[2] and value.quantize(quantum, rounding=ROUND_HALF_UP) == number]
            if candidates and all(item is not None and year not in item for item in candidates):
                spans = sorted({value for item in candidates if item for value in item})
                warnings.append(
                    f"年份标注需复核：{sentence.strip()}。{match[0]}对应的登记期间为"
                    f"{'、'.join(f'{value}年' for value in spans)}，不是{year}年。"
                )
    return warnings
