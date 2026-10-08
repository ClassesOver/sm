"""正文事实复核：只给纠错建议和软告警，不替模型猜测业务原因。"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ..hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
from .numeric_text import (
    budget_comparison_values,
    frozen_number_catalog,
    money_text_warnings,
    period_extrema_warnings,
    registered_decline_magnitude,
    render_frozen_numbers,
    supplemental_number_values,
)

_VALUE = re.compile(r"(?<![\d.,])([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(亿元|万元|元|万人次|人次|床日|%)")
_INFERENCE = re.compile(
    r"(?:负值|零值|偏低|低点|异常)[^。\n]{0,60}(?:可能(?:源于|反映|存在)|系.{0,25}所致|属正常业务特征)"
    r"|(?:尚未启动(?:采购|合同)|字段未填充有效数值|尚无.{0,12}(?:数据|记录)入账|无实际支出记录|疑似未入账)"
    r"|\d{1,2}月因自然天数[^。\n]{0,25}"
)


def _documents(contents: Iterable[str]) -> list[dict[str, Any]]:
    documents = []
    for content in contents:
        try:
            value = json.loads(content)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            documents.append(value)
    return documents


def _numeric_literals(value: Any) -> set[Decimal]:
    """补充 evidence 的原始数值也可用；不从模型摘要文字反推数字。"""
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float)):
        number = Decimal(str(value))
        return {number} if number.is_finite() else set()
    if isinstance(value, dict):
        return set().union(*(_numeric_literals(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_numeric_literals(item) for item in value))
    return set()


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


def _project_ratio_ranking_warnings(text: str, documents: list[dict[str, Any]]) -> list[str]:
    warnings = []
    for label, numerator_field in (("签约率", "contract_amount"), ("付款率", "payment_amount")):
        tables: dict[tuple[tuple[str, Decimal], ...], dict[str, Decimal]] = {}
        for document in documents:
            pending = list(document.get("findings", ()))
            while pending:
                finding = pending.pop()
                if isinstance(finding, list):
                    pending.extend(finding)
                    continue
                if not isinstance(finding, dict):
                    continue
                columns, rows, metadata = (finding.get(key) for key in ("columns", "rows", "columnMeta"))
                if not isinstance(columns, list) or not isinstance(rows, list):
                    pending.extend(value for value in finding.values() if isinstance(value, (list, dict)))
                    continue
                fields = ("budget_type", "budget_project_amount", numerator_field)
                if not all(field in columns for field in fields) or not isinstance(metadata, dict):
                    continue
                metas = [metadata.get(field, {}) for field in fields[1:]]
                if (any(meta.get("unit") != "元" for meta in metas)
                        or any(meta.get("periodRole") != "current" for meta in metas)):
                    continue
                indices = [columns.index(field) for field in fields]
                rates: dict[str, set[Decimal]] = {}
                for row in rows:
                    if not isinstance(row, list) or len(row) != len(columns):
                        continue
                    group, denominator, numerator = (row[index] for index in indices)
                    if (not isinstance(group, str) or not group
                            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                                   for value in (denominator, numerator))):
                        continue
                    denominator, numerator = Decimal(str(denominator)), Decimal(str(numerator))
                    if denominator.is_finite() and numerator.is_finite() and denominator > 0:
                        rates.setdefault(group, set()).add(numerator / denominator * 100)
                if len(rates) >= 2 and all(len(values) == 1 for values in rates.values()):
                    values = {group: next(iter(numbers)) for group, numbers in rates.items()}
                    tables[tuple(sorted(values.items()))] = values
        for sentence in re.split(r"[。；\n]", text):
            groups = {group for values in tables.values() for group in values if group in sentence}
            claim = re.search(re.escape(label) + r"[^。；\n]{0,25}?(最高|最低)", sentence)
            if (len(groups) != 1 or claim is None
                    or re.search(r"不是|并非|不能|不可|无法|未必", claim[0])
                    or re.search(r"\d{1,2}月|上年|去年|同期|同比", sentence)):
                continue
            group = next(iter(groups))
            choices = [values for values in tables.values() if group in values]
            if len(choices) != 1:
                continue
            values = choices[0]
            high = claim[1] == "最高"
            contrary = [other for other in values if
                        (values[other] > values[group] if high else values[other] < values[group])]
            if contrary:
                other = (max if high else min)(contrary, key=values.get)
                warnings.append(f"{label}排名需复核：{group}被写为{claim[1]}，同一补证中{other}的{label}为{values[other]:.2f}%，"
                                f"{'高' if high else '低'}于{group}的{values[group]:.2f}%。按同期间合同或付款金额/预算金额复核。")
    return warnings


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


def review_content(markdown: str, contents: Iterable[str], *, field_definitions: Mapping[str, str] | None = None,
                   fact_ids: Iterable[str] | None = None) -> list[str]:
    contents = tuple(contents)
    catalog = frozen_number_catalog(contents)
    text = render_frozen_numbers(markdown, catalog).replace("**", "")
    # 数值锚点可能插在数字与单位之间；复核时只移除非分析协议标记。
    text = re.sub(r"\[\[(?:claim|citation|section|table|/table):[^\]]+\]\]", "", text)
    documents = _documents(contents)
    warnings = money_text_warnings(text)
    for token in re.findall(r"\{\{value:[^{}\r\n]+\}\}", markdown):
        if token not in catalog:
            warnings.append(f"数值引用未登记：{token}。请选择 frozenNumbers 中的引用；没有对应事实时写待核实。")
    bundles = [document for document in documents if document.get("metrics") and isinstance(document.get("analysisId"), str)]
    warnings.extend(_project_ratio_ranking_warnings(text, documents))
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
    for token, display in catalog.items():
        if ":budgetComparison." in token and ".percentage:%}}" in token:
            continue
        match = _VALUE.fullmatch(display)
        if match:
            number = Decimal(match[1].replace(",", ""))
            known.setdefault(match[2], set()).add(number)
            if match[2] == "人次":
                known.setdefault("万人次", set()).add(number / 10000)
    # 百分数复核直接按原值舍入，不能将两位小数显示值再次舍入成一位。
    for content in contents:
        try:
            bundle = DeterministicAnalysisBundle.model_validate_json(content)
        except ValueError:
            continue
        known.setdefault("%", set()).update(value["percentage"] for value in budget_comparison_values(bundle)
                                           if value["percentage"] is not None)
    # 原始证据中的数字同样是可核对来源；冻结目录之外的数字仍会在有目录时
    # 触发告警，但不能把简化证据对象中的已给定事实误报为无依据数字。
    supplemental = set().union(*(_numeric_literals(document) for document in documents if "findings" not in document))
    reported_values: set[tuple[Decimal, str]] = set()
    for match in _VALUE.finditer(text):
        number = Decimal(match[1].replace(",", ""))
        digits = len(match[1].split(".")[1]) if "." in match[1] else 0
        quantum = Decimal(1).scaleb(-digits)
        candidates = known.get(match[2], set()) | supplemental
        supported = (any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in candidates)
                     or registered_decline_magnitude(number, match[2], candidates,
                                                     prefix=text[max(0, match.start() - 12):match.start()],
                                                     quantum=quantum))
        if not supported and (number, match[2]) not in reported_values:
            reported_values.add((number, match[2]))
            warnings.append(f"数值缺少可核对的冻结依据：{match[0]}。请使用对应数值引用，或删去未登记的计算结果。")
    for match in _INFERENCE.finditer(text):
        # “不能证明尚未启动采购”等否定句没有作业务断言；只看当前分句，
        # 不能用前一句的否定来豁免后一句真实推测。
        prefix = re.split(r"[。！？；，,\n]", text[:match.start()])[-1]
        assertion = re.split(r"[。！？；，,\n]", prefix + match[0])[-1]
        if re.search(r"(?:不能|不可|不足以|不应|无法|不代表|不得|不要|未能|并非|尚不能).{0,30}", assertion):
            continue
        warnings.append(f"业务原因或数据状态需直接证据：{match[0]}。数值为零不能证明流程未启动、字段未填充或未入账。")
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
    return list(dict.fromkeys(warnings))
