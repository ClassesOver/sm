"""从冻结事实生成正文数值；模型只选择数值引用，不负责换算或千分位。"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from loguru import logger

from ..hospital_operation.deterministic_analysis import DeterministicAnalysisBundle

_MONEY_UNITS = {"元": Decimal(1), "万元": Decimal(10_000), "亿元": Decimal(100_000_000)}
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
_VISIT_UNITS = {"人次": Decimal(1), "万人次": Decimal(10_000)}


def _unit_scales(unit: str | None) -> dict[str, Decimal] | None:
    """同一量纲内可互换的显示单位及倍率；只有金额与人次按固定倍率换算。"""
    return next((family for family in (_MONEY_UNITS, _VISIT_UNITS) if unit in family), None)
_VALUE_TOKEN = re.compile(r"\{\{value:[^{}\r\n]+\}\}")
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


def _frozen_number_entries(contents: Iterable[str]) -> Iterator[tuple[str, Any, str | None, str | None]]:
    """逐项给出 (数值引用, 未舍入原值, 原单位, 显示单位)；目录与复核共用同一来源。"""
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
                    if percent_point_field(field, unit):
                        yield f"{{{{value:{fact_id}:{field}:%}}}}", value, unit, PERCENT_POINT
                        continue
                    units = _unit_scales(unit) or (unit or "",)
                    for target in units:
                        yield f"{{{{value:{fact_id}:{field}:{target}}}}}", value, unit, target or None
        for comparison in budget_comparison_values(bundle):
            for field, unit in (("difference", comparison["unit"]), ("percentage", "%")):
                if comparison[field] is None:
                    continue
                if percent_point_field(field, unit):
                    token = f"{{{{value:{comparison['actualFactId']}:budgetComparison.{comparison['budgetFactId']}.{comparison['period']}.{field}:%}}}}"
                    yield token, comparison[field], unit, PERCENT_POINT
                    continue
                for target in (_unit_scales(unit) or (unit,)):
                    token = f"{{{{value:{comparison['actualFactId']}:budgetComparison.{comparison['budgetFactId']}.{comparison['period']}.{field}:{target}}}}}"
                    yield token, comparison[field], unit, target


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


def frozen_number_catalog(contents: Iterable[str]) -> dict[str, str]:
    catalog: dict[str, str] = {}
    for token, value, unit, target in _frozen_number_entries(contents):
        text = format_fact_value(value, unit, _readable_display_unit(value, unit, target))
        if token in catalog and catalog[token] != text:
            # 同一事实身份在不同证据中出现冲突时，不选择任意一个值。
            catalog[token] = "数值待核实"
        else:
            catalog[token] = text
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


def supplemental_number_values(contents: Iterable[str]) -> dict[str, set[Decimal]]:
    """只登记补证列元数据声明的数值及单位，不从数字大小猜测用途。"""
    known: dict[str, set[Decimal]] = {}
    for content in contents:
        try:
            document = json.loads(content)
        except (TypeError, ValueError):
            continue
        if not isinstance(document, dict) or not isinstance(document.get("findings"), list):
            continue
        pending = list(document["findings"])
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
                    if unit in _MONEY_UNITS:
                        for target, scale in _MONEY_UNITS.items():
                            known.setdefault(target, set()).add(number * _MONEY_UNITS[unit] / scale)
                    elif unit == "人次":
                        known.setdefault("万人次", set()).add(number / 10000)
    return known


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

    return re.sub(
        rf"(?P<verb>{DIRECTION_WORD_PATTERN})"
        r"(?P<filler>了|约|为|达|幅度为)?(?P<space>\s*)-\s*(?P<value>\d[\d,]*(?:\.\d+)?)",
        replace,
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


def replace_unregistered_numbers(markdown: str, contents: Iterable[str]) -> str:
    """把没有冻结依据的带单位数字替换为待核实，避免手算结果落盘。"""

    contents = tuple(contents)
    catalog = frozen_number_catalog(contents)
    known = supplemental_number_values(contents)
    # 没有可解析的冻结事实时，服务端无法判断正文数字是否为派生值；
    # 保留原文，避免把仅含原始证据的旧格式内容全部改成“待核实”。
    if not catalog and not known:
        return markdown
    for unit, values in frozen_number_values(contents, catalog).items():
        known.setdefault(unit, set()).update(values)

    def replace(match: re.Match[str]) -> str:
        number = Decimal(match["number"].replace(",", ""))
        digits = len(match["number"].split(".", 1)[1]) if "." in match["number"] else 0
        quantum = Decimal(1).scaleb(-digits)
        candidates = known.get(match["unit"], ())
        if (any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in candidates)
                or registered_decline_magnitude(number, match["unit"], candidates,
                                                prefix=markdown[max(0, match.start() - 12):match.start()],
                                                quantum=quantum)):
            return _display_precision(match["number"]) + match[0][len(match["number"]):]
        # 百分数指标的变化写成“提高2.10%”：数值只对得上登记的百分点差值时改写单位，
        # 避免把两项百分数之差读成相对变化率。
        points = known.get(PERCENT_POINT, ()) if match["unit"] == "%" else ()
        if points and (any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in points)
                       or registered_decline_magnitude(number, PERCENT_POINT, points,
                                                       prefix=markdown[max(0, match.start() - 12):match.start()],
                                                       quantum=quantum)):
            logger.warning("report_percent_point_unit_corrected value={}", match[0])
            return f"{_display_precision(match['number'])}{PERCENT_POINT}"
        logger.warning("report_unregistered_number_replaced value={}", match[0])
        return "待核实"

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
            return "待核实"
        written = _display_precision(match["number"]) + match["scale"]
        return written + matched[0][1:] if len(matched) == 1 else written

    return BARE_SCALED_NUMBER.sub(replace_bare, replaced)


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


def _series_year(bundle: dict[str, Any]) -> str | None:
    metrics = [entry for entry in bundle.get("metrics", ()) if "current" in entry.get("periodRoles", ())]
    periods = metrics[0].get("periodValues", ()) if len(metrics) == 1 else ()
    return str(periods[0]["period"])[:4] if periods else None


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
            # 范围端点不是另一项月份断言；掩去“月”但保持字符位置，
            # 使“2月为1—10月最低”仍可匹配2月，范围则从原文取回。
            masked = re.sub(r"(?<!\d)\d{1,2}月?\s*[–—~～至到-]\s*\d{1,2}月",
                            lambda m: m[0].replace("月", "期"), text)
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
