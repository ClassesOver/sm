"""正文事实复核：只给纠错建议和软告警，不替模型猜测业务原因。"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from ..delivery.report_runtime.markdown import normalize_number_notation
from .markdown_body import trace_body
from .numeric_text import (
    BARE_SCALED_NUMBER,
    DIRECTED_PLACEHOLDER,
    DIRECTION_WORD_PATTERN,
    FALLING_WORDS,
    MULTIPLE_NUMBER,
    NEUTRAL_DIFFERENCE_PREFIX,
    PERCENT_POINT,
    PERSON_COUNT,
    RATE_AS_PERCENT_POINT,
    RISING_WORDS,
    _frozen_number_entries,
    _paragraph_at,
    _statement_at,
    bounded_by_registered,
    derived_number_values,
    describes_rate_level,
    frozen_number_catalog,
    frozen_number_values,
    money_text_warnings,
    percent_point_written_for_rate,
    period_extrema_warnings,
    positive_directed_placeholders,
    profile_rate_supported,
    profile_rate_values,
    referenced_difference_matches,
    registered_change_rates,
    registered_decline_magnitude,
    registered_group_shares,
    registered_multiple_matches,
    registered_multiples,
    render_frozen_numbers,
    supplemental_number_values,
    table_unit_cells,
)
from .review_attribution import (
    _group_ranking_warnings,
    _group_top_n_warnings,
    _group_value_attribution_warnings,
    _metric_value_attribution_warnings,
    _monthly_budget_rate_warnings,
    _project_ratio_ranking_warnings,
    _project_ratio_value_warnings,
)
from .review_common import (
    _CLAUSE_BREAK_WITH_MARKS,
    _MAX_PERCENT_POINT_CANDIDATES,
    _VALUE,
    _documents,
    _numeric_literals,
)
from .review_periods import (
    _annual_budget_denominator_warnings,
    _comparison_window_warnings,
    _explicit_year_extrema_warnings,
    _full_year_warnings,
    _monthly_average_warnings,
    _non_additive_total_warnings,
    _paragraph_extrema_warnings,
    _year_label_warnings,
)
from .review_rates import (
    _adjacent_month_rates,
    _approximate_rate_warnings,
    _comparison_amount_warnings,
    _from_to_direction_warnings,
)
from .review_readability import readability_warnings, repeated_sentence_warnings
from .review_supplemental import supplemental_attribution_warnings

# 读者可见文本中不应出现的内部标识（正文复核与图表图注清理共用）。
INTERNAL_ID_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])(?:(?:analysis|section|citation|claim|dataset|chart|requirement)_\d{3,}"
    r"|(?:fact|sub)-[0-9a-f]{16})(?![A-Za-z0-9_])"
)

# 成品图表只有标题、不编号：正文“如图1所示”“见表2”读者无从对应。只认引用语境
# （如/见/据…之后，或后接所示/显示…），“代表1名”等词内数字不算。
_FIGURE_REFERENCE = re.compile(
    r"(?:(?<=[如见据由从（(])|(?<=参见)|(?<=详见))(?P<label>[图表])\s*(?P<number>\d{1,3})(?![\d.,%])"
    r"|(?P<label2>[图表])\s*(?P<number2>\d{1,3})(?=\s*(?:所示|显示|可见|反映|表明|展示))"
)

# 模型自拟的图表标题行（“表1：科室收入”“**图2 趋势**”）定义了编号，引用它不告警。
_FIGURE_DEFINITION = re.compile(r"^\s*[*_]*附?(?P<label>[图表])\s*(?P<number>\d{1,3})(?:[\s:：.、*_]|$)", re.MULTILINE)

# 数值目录与 numberGuide 的 JSON 字段名；模型照抄进正文时读者看不懂。
_CONTRACT_FIELD_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:currentTotal|baselineTotal|changeRate|periodValues|periodTotals|prefixTotals"
    r"|monthlyAverage|monthlyMinimum|monthlyMaximum|monthlyStatistics|rowStatistics|topGroups|bottomGroups"
    r"|budgetComparisons?|numberGuide|frozenNumbers|factId|analysisId|datasetId|total|average|minimum"
    r"|maximum|change|numerator|denominator|difference|percentage|(?i:yoy|mom))(?![A-Za-z0-9_])"
)

# 管理层正文不得泄漏生成/验收实现术语。协议标记会在此之前移除；这些词即使
# 数值和口径正确，也会让成品读起来像 harness 日志而不是经营报告。
_TECHNICAL_PRESENTATION_TERMS = {
    "block": "段落",
    "Markdown": "正文",
    "CSV": "明细数据",
    "SQL": "查询口径",
    "ACF/PACF": "时序相关性检验",
    "服务端": "登记结果",
    "数据集": "统计口径",
    "字段": "指标",
    "x轴": "横轴",
    "y轴": "纵轴",
    # 回放附录：“行级皮尔逊系数”“期间索引存在重复，行级时序统计已禁用”。
    "行级": "明细记录层面",
    "皮尔逊": "相关系数",
    "期间索引": "月份记录",
    "时序统计": "趋势检验",
}

# 冻结数据只覆盖本期与对比期：“创历史新高”“首次突破1亿元”“历年最高”需要更长历史才能判断。
_HISTORICAL_CLAIM = re.compile(
    r"历史(?:新高|新低|最高|最低|同期最高|同期最低)|历年(?:最高|最低)|史上|"
    r"首次(?:突破|超过|跌破|低于|高于)|创(?!年内|本年|今年|期内|月内)[^。；，,\n]{0,4}?(?:新高|新低)"
)

_INFERENCE = re.compile(
    r"(?:负值|零值|偏低|低点|异常)[^。\n]{0,60}(?:可能(?:源于|反映|存在)|系.{0,25}所致|属正常业务特征)"
    r"|(?:尚未启动(?:采购|合同)|字段未填充有效数值|尚无.{0,12}(?:数据|记录)入账|无实际支出记录|疑似未入账)"
    r"|\d{1,2}月因自然天数[^。\n]{0,25}"
)


@dataclass(frozen=True)
class ContentReviewResult:
    warnings: tuple[str, ...]
    accuracy_count: int

    @property
    def presentation_count(self) -> int:
        return len(self.warnings) - self.accuracy_count


def review_content(markdown: str, contents: Iterable[str], *, field_definitions: Mapping[str, str] | None = None,
                   fact_ids: Iterable[str] | None = None,
                   bound_chart_ids: Iterable[str] = ()) -> list[str]:
    """兼容既有调用方，继续返回完整软告警列表。"""
    return list(review_content_result(
        markdown, contents, field_definitions=field_definitions, fact_ids=fact_ids,
        bound_chart_ids=bound_chart_ids,
    ).warnings)


def review_content_result(markdown: str, contents: Iterable[str], *, field_definitions: Mapping[str, str] | None = None,
                          fact_ids: Iterable[str] | None = None,
                          bound_chart_ids: Iterable[str] = ()) -> ContentReviewResult:
    contents = tuple(contents)
    from .number_selection import align_number_selections

    _, selection_warnings = align_number_selections(markdown, contents, field_definitions)
    catalog = frozen_number_catalog(contents)
    # 编辑器复核的是用户可能手输的正文：全角数字与百分点缩写同样要识别。
    markdown = normalize_number_notation(trace_body(markdown, mask_inline_code=False))
    # 先去掉正文自带的锚点，再用临时服务端锚点记录每个占位符渲染值的身份。
    # 复核仍使用干净文本，保留的终点偏移只授权对应数字，不能豁免同句或同段的同值手写数。
    marker_pattern = r"\[\[(?:claim|citation|section|table|/table):[^\]]+\]\]"
    clean = re.sub(marker_pattern, "", markdown).replace("**", "")
    references: dict[str, str] = {}

    def annotate(token: str, shown: str) -> str:
        marker = f"[[claim:number-review-{len(references)}]]"
        references[marker] = token
        return shown + marker

    marked = render_frozen_numbers(clean, catalog, annotate=annotate)
    number_references: dict[int, str] = {}
    removed = 0

    def strip_marker(match: re.Match[str]) -> str:
        nonlocal removed
        if token := references.get(match[0]):
            number_references[match.start() - removed] = token
        removed += len(match[0])
        return ""

    text = re.sub(marker_pattern, strip_marker, marked)
    documents = _documents(contents)
    warnings = [*selection_warnings, *money_text_warnings(text)]
    warnings.extend(supplemental_attribution_warnings(text, documents, field_definitions or {}))
    for paragraph in re.split(r"\n\s*\n", text):
        if (re.search(r"相关系数|相关性|高度相关", paragraph)
                and re.search(r"(?:反映|代表)同一工作量|(?:因此|说明|证明|故).{0,12}口径等价", paragraph)
                and not re.search(r"不能|不足以|不代表|无法|并非", paragraph)):
            warnings.append("相关性不能证明口径等价：统计范围不同的指标须分别说明，不得据此认定可互换或择一使用。")
    if tuple(bound_chart_ids) and re.search(r"图[^。\n]{0,40}(?:未纳入引用|不予展示|已剔除|不再引用)", text):
        warnings.append("图表引用状态矛盾：当前段落仍绑定成品图表，不能声称已剔除或未引用；须核对结构化引用并客观说明口径限制。")
    if any("金额单位待核实" in paragraph and re.search(r"(?:原始元值|按(?:万元|亿元)换算)", paragraph)
           for paragraph in re.split(r"\n\s*\n", text)):
        warnings.append("金额单位断言矛盾：已标注金额单位待核实，不能断言原始值为元或按万元、亿元换算。")
    for token in re.findall(r"\{\{value:[^{}\r\n]+\}\}", markdown):
        if token not in catalog:
            warnings.append(f"数值引用未登记：{token}。请选择 frozenNumbers 中的引用；没有对应事实时写待核实。")
    for match in BARE_SCALED_NUMBER.finditer(text):
        warnings.append(
            f"数值缺少单位：{match[0]}。请使用带单位的冻结数值引用（如亿元、万元、万人次），不得省略单位。"
        )
    positive = positive_directed_placeholders(contents)
    for match in DIRECTED_PLACEHOLDER.finditer(markdown):
        if match["token"] not in positive or describes_rate_level(markdown[:match.start()]):
            continue
        # “同比/环比下降{变化率}”由下方变化率方向检查覆盖，避免同一问题报两次。
        if ":changeRate:" in match["token"] and re.search(r"(?:同比|环比)$", markdown[:match.start()]):
            continue
        shown = catalog.get(match["token"], match["token"])
        warnings.append(
            f"方向与登记变化相反：{match['verb']}{shown}。该变化已登记为正值（增加），"
            "请改写为增长/增加，并同步修正前后文的方向判断。"
        )
    bundles = [document for document in documents if document.get("metrics") and isinstance(document.get("analysisId"), str)]
    warnings.extend(_project_ratio_ranking_warnings(text, documents))
    warnings.extend(_project_ratio_value_warnings(text, documents))
    warnings.extend(_monthly_budget_rate_warnings(text, documents, field_definitions))
    warnings.extend(_group_ranking_warnings(text, documents, field_definitions))
    warnings.extend(_group_top_n_warnings(text, documents, field_definitions))
    warnings.extend(_group_value_attribution_warnings(text, documents))
    warnings.extend(_metric_value_attribution_warnings(text, contents, documents, field_definitions or {}))
    warnings.extend(_monthly_average_warnings(text, contents, documents, field_definitions or {}))
    warnings.extend(_comparison_amount_warnings(text, contents, documents))
    warnings.extend(_full_year_warnings(text, contents, documents, field_definitions or {}))
    warnings.extend(_non_additive_total_warnings(text, contents, documents))
    warnings.extend(_comparison_window_warnings(text, contents, documents))
    warnings.extend(_from_to_direction_warnings(text))
    warnings.extend(_approximate_rate_warnings(text, documents, contents))
    warnings.extend(_annual_budget_denominator_warnings(text, bundles))
    scoped_text = text
    if "[[analysis:" not in text and len(bundles) == 1:
        scoped_text = f"[[analysis:{bundles[0]['analysisId']}]]" + text
    warnings.extend(period_extrema_warnings(scoped_text, bundles))
    warnings.extend(_paragraph_extrema_warnings(text, bundles, field_definitions or {}))
    warnings.extend(_explicit_year_extrema_warnings(text, bundles, field_definitions or {},
                                                   set(fact_ids) if fact_ids is not None else None))
    for bundle in bundles:
        for entry in bundle.get("metrics", ()):
            periods = entry.get("periodValues", ())
            if entry.get("aggregation") != "sum" or entry.get("periodGranularity") != "month" or not periods:
                continue
            if any(not re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", item["period"]) for item in periods):
                continue
            if len({item["period"][:4] for item in periods}) != 1:
                continue
            monthly = {int(item["period"][5:7]): Decimal(str(item["value"])) for item in periods}
            if len(monthly) != len(periods):
                continue
            # 只比较明确写了月份范围、合计且恰好引用该事实总额的句子。
            pattern = r"(?<!\d)(\d{1,2})月?\s*[–—~～至到-]\s*(\d{1,2})月[^。；\n]{0,45}?(?:合计|累计|总额|总量)\s*(" + _VALUE.pattern + r")"
            for match in re.finditer(pattern, text):
                # 月度预算“系年度总量按月均摊”的解释引用的是年度值，
                # 不能把段首月份范围套到这个明确的年度预算上。
                if re.search(r"(?:系|由)(?:年度|全年)预算(?:总额|总量)\s*$", text[match.start():match.start(3)]):
                    continue
                start, stop = int(match[1]), int(match[2])
                value_match = _VALUE.fullmatch(match[3])
                if start > stop or not all(month in monthly for month in range(start, stop + 1)) or not value_match:
                    continue
                if value_match[2] != entry.get("unit"):
                    continue
                written = Decimal(value_match[1].replace(",", ""))
                expected = sum(monthly[month] for month in range(start, stop + 1))
                if written == Decimal(str(entry["total"])) and written != expected:
                    warnings.append(f"累计期间需复核：{start}—{stop}月合计应为{expected:,}{entry['unit']}，不能使用完整期间总额{written:,}{entry['unit']}。")
        metrics = [entry for entry in bundle.get("metrics", ()) if "current" in entry.get("periodRoles", ())]
        if len(metrics) < 2:
            continue
        # 多指标仅在小节标题唯一命中字段的中文定义时判定，不按数字大小猜指标。
        for heading in re.finditer(r"^#{3,4} .+(?:\n|$)", text, re.MULTILINE):
            title = heading[0]
            selected = [entry for entry in metrics
                        if (label := (field_definitions or {}).get(entry.get("field"), entry.get("field", "")))
                        and label in title]
            if len(selected) != 1:
                continue
            next_heading = re.search(r"^#{3,4} ", text[heading.end():], re.MULTILINE)
            end = heading.end() + next_heading.start() if next_heading else len(text)
            local = f"[[analysis:{bundle['analysisId']}]]" + text[heading.end():end]
            label = (field_definitions or {}).get(selected[0]["field"], selected[0]["field"])
            warnings.extend(f"{label}：{warning}" for warning in period_extrema_warnings(local, [{**bundle, "metrics": selected}]))
    known = supplemental_number_values(contents)
    derived = derived_number_values(contents)
    profile_rates = profile_rate_values(contents)
    # 复核直接按冻结原值舍入，不能将两位小数显示值再次舍入（如1.245万元→1.25→1.3）。
    for unit, values in frozen_number_values(contents, catalog).items():
        known.setdefault(unit, set()).update(values)
        if unit == "人次":
            known.setdefault("万人次", set()).update(value / 10000 for value in values)
    # 仅为旧格式简化证据保留无单位回退。事实包必须使用上面的带单位目录，
    # 否则金额、缺失行数等原始数字会被借作百分比或人次的依据。
    supplemental = set().union(*(_numeric_literals(document) for document in documents
                                 if not {"metrics", "comparisons", "derivedMetrics", "reconciliations",
                                         "correlations", "correlationDetails", "findings"}.intersection(document)
                                 and document.get("schema") != "chart-input/v1"))
    reported_values: set[tuple[Decimal, str]] = set()
    for match in _VALUE.finditer(text):
        number = Decimal(match[1].replace(",", ""))
        digits = len(match[1].split(".")[1]) if "." in match[1] else 0
        quantum = Decimal(1).scaleb(-digits)
        # 原始证据里的数字不区分百分数与百分点：只对得上百分点差值的“X%”先单独提示。
        if (match[2] == "%" and (number, match[2]) not in reported_values
                and not any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number
                            for value in known.get("%", ()))
                and any(abs(value).quantize(quantum, rounding=ROUND_HALF_UP) == abs(number)
                        for value in known.get(PERCENT_POINT, ()))):
            reported_values.add((number, match[2]))
            warnings.append(
                f"百分数指标的变化是百分点差值：{match[0]}应写为{abs(number)}个百分点，"
                "写成百分数会被读成相对变化率。"
            )
            continue
        candidates = known.get(match[2], set()) | supplemental
        prefix = text[max(0, match.start() - 12):match.start()]
        supported = (any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in candidates)
                     or registered_decline_magnitude(number, match[2], candidates,
                                                     prefix=text[max(0, match.start() - 12):match.start()],
                                                     quantum=quantum)
                     or bounded_by_registered(number, match[1], known.get(match[2], ()),
                                              prefix=text[max(0, match.start() - 12):match.start()])
                     or derived.supports(number, match[2], quantum, _paragraph_at(text, match.start()))
                     or (match[2] == "%" and profile_rate_supported(
                         profile_rates, number, quantum, _paragraph_at(text, match.start()))))
        if NEUTRAL_DIFFERENCE_PREFIX.search(prefix):
            supported = derived.supports(
                number, match[2], quantum, _paragraph_at(text, match.start()),
                statement=_statement_at(text, match.start()),
                claim=re.split(r'[。！？；;\n]', text[:match.end()])[-1],
            ) or referenced_difference_matches(number_references.get(match.end()), catalog, number, match[2])
        if not supported and (number, match[2]) not in reported_values:
            reported_values.add((number, match[2]))
            warnings.append(f"数值缺少可核对的冻结依据：{match[0]}。请使用对应数值引用，或删去未登记的计算结果。")
    # “是上年同期的1.05倍”：倍数只能由登记的本期与基期合计、变化率或比率得出。
    if catalog:
        multiples = registered_multiples(contents, catalog)
        for match in MULTIPLE_NUMBER.finditer(text):
            if not registered_multiple_matches(match, multiples):
                warnings.append(
                    f"倍数缺少可核对的冻结依据：{match[0]}。须由已登记的本期与基期合计或比率得出，"
                    "请改用变化率表述或删去该倍数。"
                )
    # 人次（就诊次数）写成人数：“门诊量35.3万人”。
    for match in PERSON_COUNT.finditer(text):
        number = Decimal(match["number"].replace(",", ""))
        quantum = Decimal(1).scaleb(-(len(match["number"].split(".")[1]) if "." in match["number"] else 0))
        visit_unit = "万人次" if match["scale"] else "人次"
        if (any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in known.get(visit_unit, ()))
                and not any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in known.get("人", ()))):
            warnings.append(f"单位混用：{match[0]}对应登记的{visit_unit}（就诊次数），不是人数；请写为{match['number']}{visit_unit}。")
    # 自写表格把单位写在表头、单元格只写数字：按表头单位同样核对。
    for _start, _end, number_text, unit in table_unit_cells(text):
        number = Decimal(number_text.replace(",", ""))
        quantum = Decimal(1).scaleb(-(len(number_text.split(".")[1]) if "." in number_text else 0))
        candidates = known.get(unit, set()) | known.get(PERCENT_POINT if unit == "%" else unit, set()) | supplemental
        if (not any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in candidates)
                and (number, unit) not in reported_values):
            reported_values.add((number, unit))
            warnings.append(
                f"表格数值缺少可核对的冻结依据：{number_text}（{unit}列）。"
                "请使用对应数值引用，或删去未登记的计算结果。"
            )
    # “超过1.37亿元”而登记值为1.3654亿元：数值按书写精度舍入后一致，但“超过/不足”的
    # 方向与真实值相反。
    for match in re.finditer(
        r"(?P<qualifier>超过|逾|高于|突破|多于|不足|低于|未达|少于|不到)\s*"
        r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?P<unit>亿元|万元|元|万人次|人次|床日|%)",
        text,
    ):
        number = Decimal(match["number"].replace(",", ""))
        quantum = Decimal(1).scaleb(-(len(match["number"].split(".")[1]) if "." in match["number"] else 0))
        rounded = [value for value in known.get(match["unit"], ())
                   if value.quantize(quantum, rounding=ROUND_HALF_UP) == number]
        above = match["qualifier"] in {"超过", "逾", "高于", "突破", "多于"}
        if rounded and all((value <= number) if above else (value >= number) for value in rounded):
            actual = rounded[0].quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize()
            warnings.append(
                f"约数方向需复核：{match[0]}，但登记值为{actual:f}{match['unit']}，"
                f"舍入后才是{match['number']}{match['unit']}；请改为“约{match['number']}{match['unit']}”。"
            )
    # 百分数指标的变化额以百分点登记；其余“个百分点”只能由两项已登记百分数相减得到，
    # 按书写精度舍入后相等才有依据。
    percents = sorted(known.get("%", ()))
    points = {abs(value) for value in known.get(PERCENT_POINT, ())}
    pairwise = len(percents) <= _MAX_PERCENT_POINT_CANDIDATES
    change_rates = registered_change_rates(contents)
    # 分组占比两两相减组合多、取整后易凑上变化率：判断“变化率误写为百分点”时不作依据。
    shares = registered_group_shares(contents)
    rate_level_percents = [value for value in percents if value not in shares]
    if points or pairwise:
        for match in RATE_AS_PERCENT_POINT.finditer(text):
            number = Decimal(match[1])
            quantum = Decimal(1).scaleb(-(len(match[1].split(".")[1]) if "." in match[1] else 0))
            if any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in points):
                continue
            if percent_point_written_for_rate(match, text, change_rates, points, rate_level_percents):
                warnings.append(
                    f"变化率单位误用：{match[0]}对应已登记的变化率{match[1]}%，应写作“{match[1]}%”；"
                    "百分点只用于两项百分数之差。"
                )
                continue
            if pairwise and not any(
                abs(left - right).quantize(quantum, rounding=ROUND_HALF_UP) == number
                for index, left in enumerate(percents) for right in percents[index + 1:]
            ):
                warnings.append(
                    f"百分点差值缺少可核对的冻结依据：{match[0]}。须由两项已登记百分数相减得到，"
                    "请写出两项百分数或删去该差值。"
                )
    warnings.extend(_year_label_warnings(text, contents))
    # 同比/环比口径混淆：数值本身已登记，但只对应另一种比较口径的变化率。
    rates: dict[str, set[Decimal]] = {"yoy": set(), "mom": set()}
    for document in documents:
        for entry in document.get("comparisons") or ():
            if (isinstance(entry, dict) and entry.get("comparisonType") in rates
                    and isinstance(entry.get("changeRate"), (int, float))
                    and not isinstance(entry.get("changeRate"), bool)):
                rates[entry["comparisonType"]].add(Decimal(str(entry["changeRate"])))
    # 冻结事实中不是变化率的百分数（占比、完成率、百分数指标本身）；补证脚本给出的
    # 变化率不在此列，不能据此判定“同比增长X%”写错了口径。
    other_percents = {
        Decimal(str(value)) for token, value, unit, target in _frozen_number_entries(contents)
        if (target or unit) == "%" and value is not None
        and token[2:-2].split(":")[2] not in {"changeRate", "change"}
        and not token[2:-2].split(":")[2].startswith(("periodChanges.", "periodChangeRates."))
    }
    # 相邻两月的变化率（某月较上月）属于环比口径。
    rates["mom"].update(_adjacent_month_rates(contents))
    if rates["yoy"] or rates["mom"] or other_percents:
        for match in re.finditer(
            rf"(?P<kind>同比|环比)(?P<verb>{DIRECTION_WORD_PATTERN}|变化|变动)?(?:率)?"
            r"(?:了|约|为|达)?\s*(?P<number>[+-]?\d+(?:\.\d+)?)%", text,
        ):
            written = abs(Decimal(match["number"]))
            quantum = Decimal(1).scaleb(-(len(match["number"].split(".")[1]) if "." in match["number"] else 0))
            stated, other = ("yoy", "mom") if match["kind"] == "同比" else ("mom", "yoy")

            def same_magnitude(values: set[Decimal]) -> list[Decimal]:
                return [value for value in values
                        if abs(value).quantize(quantum, rounding=ROUND_HALF_UP) == written]

            stated_values = same_magnitude(rates[stated])
            if not stated_values and same_magnitude(rates[other]):
                other_label = "环比" if other == "mom" else "同比"
                warnings.append(
                    f"同比/环比口径混淆：{match[0]}。该变化率对应已登记的{other_label}比较，请核对比较口径。"
                )
            elif not stated_values and same_magnitude(other_percents):
                # 数字本身已登记，但只是占比、完成率等其他百分数，不是任何比较的变化率。
                warnings.append(
                    f"变化率口径需复核：{match[0]}。该百分数对应已登记的其他指标（如占比、完成率），"
                    f"不是{match['kind']}变化率。"
                )
            # 幅度相同但方向相反：“下降”对应正的登记变化率，或“增长”对应负的登记变化率。
            falling = match["verb"] in FALLING_WORDS
            rising = match["verb"] in RISING_WORDS
            signed = [value for value in stated_values if value]
            if (signed and (falling or rising) and not match["number"].startswith(("-", "+"))
                    and all((value > 0) == falling for value in signed)):
                registered = ", ".join(f"{value:+}%" for value in stated_values)
                warnings.append(
                    f"方向与登记变化率相反：{match[0]}。已登记的{match['kind']}变化率为 {registered}，请核对增减方向。"
                )
    for match in _INFERENCE.finditer(text):
        # “不能证明尚未启动采购”等否定句没有作业务断言；只看当前分句，
        # 不能用前一句的否定来豁免后一句真实推测。
        prefix = _CLAUSE_BREAK_WITH_MARKS.split(text[:match.start()])[-1]
        assertion = _CLAUSE_BREAK_WITH_MARKS.split(prefix + match[0])[-1]
        if re.search(r"(?:不能|不可|不足以|不应|无法|不代表|不得|不要|未能|并非|尚不能).{0,30}", assertion):
            continue
        warnings.append(f"业务原因或数据状态需直接证据：{match[0]}。数值为零不能证明流程未启动、字段未填充或未入账。")
    for match in _HISTORICAL_CLAIM.finditer(text):
        clause = _CLAUSE_BREAK_WITH_MARKS.split(text[:match.start()])[-1] + match[0]
        if re.search(r"不能|无法|不足以|并非|不代表|尚不能", clause):
            continue
        warnings.append(
            f"历史比较需直接证据：{match[0]}。冻结数据只覆盖本期与对比期，不能判断历史新高或首次突破；"
            "请改为与对比期的比较。"
        )
    # 负值占位渲染后自带负号：与“下降/减少”连用成双重否定，与“增长/上升”连用方向矛盾。
    for match in re.finditer(
        rf"(?P<verb>{DIRECTION_WORD_PATTERN})"
        r"(?:了|约|为|达|幅度为)?\s*(?P<value>-\s*\d[\d,]*(?:\.\d+)?\s*(?:亿元|万元|元|万人次|人次|床日|%)?)",
        text,
    ):
        if describes_rate_level(text[:match.start()]):
            # “增速下降为-5.03%”说的是增速降到负值，不是符号重复或方向矛盾。
            continue
        decline = match["verb"] in FALLING_WORDS
        if decline:
            label = "变化率" if match["value"].rstrip().endswith("%") else "变化额"
            warnings.append(f"符号重复：{match[0]}。“{match['verb']}”后应写正的幅度，或改写为“{label}为{match['value']}”。")
        else:
            warnings.append(f"方向矛盾：{match[0]}。数值为负却写为“{match['verb']}”，请核对方向并改写为下降幅度。")
    # 读者可见正文不得出现内部标识或英文字段名（协议标记、图片与链接地址不可见，先移除）。
    # 软告警：进入一次纠错轮次，让模型改用业务名称，而不是等到成品验收才发现。
    presentation_start = len(warnings)
    visible = re.sub(r"!\[[^\]\r\n]*\]\([^)\r\n]*\)|\[\[[^\]\r\n]+\]\]", "", text)
    # 链接目标不可见，但链接文字属于读者可见正文，仍须复核。
    visible = re.sub(r"\[([^\]\r\n]*)\]\([^)\r\n]*\)", r"\1", visible)
    for identifier in dict.fromkeys(INTERNAL_ID_PATTERN.findall(visible)):
        warnings.append(f"正文出现内部标识：{identifier}。读者可见内容只用业务名称，内部 ID 只放在结构化引用字段。")
    defined_figures = {(match["label"], match["number"]) for match in _FIGURE_DEFINITION.finditer(visible)}
    for reference in dict.fromkeys(
        (match["label"] or match["label2"], match["number"] or match["number2"])
        for match in _FIGURE_REFERENCE.finditer(visible)
    ):
        if reference not in defined_figures:
            warnings.append(
                f"正文引用了图表编号：{''.join(reference)}。成品图表只有标题、不编号，"
                "请改用图表标题的主题词指代（如“门诊收入趋势图显示”）。"
            )
    for field in dict.fromkeys(_CONTRACT_FIELD_PATTERN.findall(re.sub(r"`[^`\r\n]*`", "", visible))):
        warnings.append(
            f"正文出现数据字段名：{field}。读者可见内容改用中文业务表述（如合计、同比、环比、月均、变化额）。"
        )
    for term, replacement in _TECHNICAL_PRESENTATION_TERMS.items():
        flags = re.IGNORECASE if term.isascii() else 0
        if re.search(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", visible, flags):
            warnings.append(
                f"正文出现技术实现术语：{term}。面向管理层请改为业务表达“{replacement}”，"
                "不要描述生成、验收或文件处理过程。"
            )
    for field, description in (field_definitions or {}).items():
        # 紧跟登记说明的写法（如“字段（三级科室）”）用于数据质量说明，保持既有口径不告警。
        if (re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{2,}", field)
                and re.search(rf"(?<![A-Za-z0-9_]){re.escape(field)}(?![A-Za-z0-9_])"
                              rf"(?!\s*[（(]\s*{re.escape(description)}\s*[）)])", visible)):
            warnings.append(f"正文出现内部字段名：{field}。请改用业务名称“{description}”。")
    presentation = set(warnings[presentation_start:])
    for field, description in (field_definitions or {}).items():
        if field not in text:
            continue
        # 仅在字段旁明确标注层级/院区时比较，缺失率本身不是语义映射错误。
        pattern = re.escape(field) + r"\s*[（(]([^）)]+)[）)]"
        descriptions = re.findall(pattern, text)
        descriptions.extend(re.findall(re.escape(field) + r"\s*字段(?:是|为|代表)([^。；\n]{1,30})", text))
        for written in descriptions:
            labels = re.findall(r"一级科室|二级科室|三级科室|四级科室|院区", written)
            if labels and any(label not in description for label in labels):
                warnings.append(f"字段口径需复核：{field} 的登记说明为“{description}”，不能解释成“{written}”。")
    unique = list(dict.fromkeys(warnings))
    # 段落级（带指标名）与期间级复核可能报出同一问题；保留更具体的带指标名形式。
    labelled = {warning.split("：", 1)[1] for warning in unique if "：" in warning}
    retained = tuple(warning for warning in unique if warning not in labelled)
    return ContentReviewResult(retained, sum(warning not in presentation for warning in retained))


__all__ = ["INTERNAL_ID_PATTERN", "readability_warnings", "repeated_sentence_warnings", "review_content", "review_content_result", "ContentReviewResult"]
