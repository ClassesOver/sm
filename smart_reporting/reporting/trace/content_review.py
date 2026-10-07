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
    render_frozen_numbers,
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


def review_content(markdown: str, contents: Iterable[str], *, field_definitions: Mapping[str, str] | None = None) -> list[str]:
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
    scoped_text = text
    if "[[analysis:" not in text and len(bundles) == 1:
        scoped_text = f"[[analysis:{bundles[0]['analysisId']}]]" + text
    warnings.extend(period_extrema_warnings(scoped_text, bundles))
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
    known: dict[str, set[Decimal]] = {}
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
    supplemental = set().union(*(_numeric_literals(document) for document in documents))
    reported_values: set[tuple[Decimal, str]] = set()
    for match in _VALUE.finditer(text):
        number = Decimal(match[1].replace(",", ""))
        digits = len(match[1].split(".")[1]) if "." in match[1] else 0
        quantum = Decimal(1).scaleb(-digits)
        candidates = known.get(match[2], set()) | supplemental
        if not any(value.quantize(quantum, rounding=ROUND_HALF_UP) == number for value in candidates) and (number, match[2]) not in reported_values:
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
