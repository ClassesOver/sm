"""数值引用失败的检测与说明：服务端只诊断，不替模型改写引用。

模型写出的 ``{{value:...}}`` / ``{{calc:...}}`` 无法登记时，逐项给出所在语句、原因和同一指标
可用的引用（含显示值），交回模型纠正；书写差异（编号缺前缀或大写、期间分隔符、单位写法）
只作为候选提示，不静默替换。纠正轮次用尽仍失败的引用才在正文标注待核实并记录原因。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

VALUE_TOKEN = re.compile(r"\{\{\s*value\s*:[^{}\r\n]+\}\}")
REVOKED_SELECTOR = "unverified."
UNVERIFIED_TEXT = "数值待核实"
# 模型写了数值目录中不存在的短编号时，解码为该事实名下的未登记引用（见 number_handles）。
UNKNOWN_FACT = "unknown"

_UNIT_ALIASES = {
    "亿": "亿元", "万": "万元", "％": "%", "百分比": "%", "percent": "%", "pct": "%",
    "百分点": "个百分点", "pp": "个百分点", "万人": "万人次",
}
_BARE_FACT = re.compile(r"(?<![\w-])(?:fact-)?([0-9a-fA-F]{16})(?![\w])")
_RANGE = re.compile(r"(\d{4})-(\d{1,2})\s*(?:\.\.|…|[—–~～至到]|--?)\s*(\d{4})-(\d{1,2})(?!\d)")
_MONTH = re.compile(r"(?<![\d-])(\d{4})-(\d{1,2})(?![\d-])")
_MAX_CANDIDATES = 5


def _parts(token: str) -> list[str] | None:
    parts = [part.strip() for part in token.strip()[2:-2].split(":")]
    if parts[0] != "value" or len(parts) not in (3, 4):
        return None
    return parts if len(parts) == 4 else [*parts, ""]


def _normalized(text: str) -> str:
    text = _BARE_FACT.sub(lambda match: "fact-" + match[1].lower(), re.sub(r"\s+", "", text))
    text = _RANGE.sub(lambda m: f"{m[1]}-{int(m[2]):02d}..{m[3]}-{int(m[4]):02d}", text)
    return _MONTH.sub(lambda m: f"{m[1]}-{int(m[2]):02d}", text)


def restore_revoked_references(markdown: str) -> str:
    """把对齐时撤销的引用还原为模型原写法，交回纠正时模型看到的是自己的原文。"""
    return markdown.replace(":" + REVOKED_SELECTOR, ":")


def value_reference_failure(token: str, catalog: Mapping[str, str]) -> tuple[str, str | None, list[str]]:
    """返回（面向读者的原因, 可展示的原引用值, 可选引用）。原因不含内部编号。"""
    parts = _parts(token)
    if parts is None:
        return "数值引用格式无法识别", None, []
    fact, selector, unit = parts[1], parts[2], parts[3]
    if fact == UNKNOWN_FACT:
        return "引用编号不存在于本章数值目录", None, []
    if selector.startswith(REVOKED_SELECTOR):
        original = "{{value:" + fact + ":" + selector[len(REVOKED_SELECTOR):] + ":" + unit + "}}"
        shown = catalog.get(original)
        return (
            "正文写出的指标、期间或统计方式与所选引用不一致，且找不到唯一匹配的登记值",
            shown if shown and shown != UNVERIFIED_TEXT else None,
            [],
        )
    if catalog.get(token) == UNVERIFIED_TEXT:
        return "该指标存在互相冲突的来源数值，无法确定采用哪一个", None, []
    fact, selector, unit = _normalized(fact), _normalized(selector), _UNIT_ALIASES.get(unit, unit)
    written = "{{value:" + fact + ":" + selector + ":" + unit + "}}"
    if written in catalog:
        return "引用写法不规范（编号、期间或单位写法）", None, [written]
    same_fact = [item for item in catalog if item.startswith("{{value:" + fact + ":")]
    if not same_fact:
        return "引用的指标不在本章的登记数值中", None, []
    same_selector = [item for item in same_fact if (_parts(item) or ["", "", ""])[2] == selector]
    if same_selector:
        return "该取值方式没有登记所写的显示单位", None, same_selector[:_MAX_CANDIDATES]
    head = selector.split(".", 1)[0]
    suggestions = [item for item in same_fact if (_parts(item) or ["", "", ""])[2].split(".", 1)[0] == head]
    if unit:
        suggestions = [item for item in suggestions if item.endswith(":" + unit + "}}")] or suggestions
    if not suggestions:
        suggestions = [item for item in same_fact if not unit or item.endswith(":" + unit + "}}")]
    total = "{{value:" + fact + ":total:" + unit + "}}"
    if total in catalog and head != "total":
        # 区间写法缺失时，完整统计窗口通常就是该指标的合计。
        suggestions = [total, *(item for item in suggestions if item != total)]
    return "该指标没有登记这种取值方式（统计口径或期间）", None, suggestions[:_MAX_CANDIDATES]


def number_reference_failures(markdown: str, contents: Iterable[str]) -> list[dict[str, Any]]:
    """列出正文中无法登记的数值与计算引用，供模型逐项纠正；全部有效时返回空列表。"""
    from .calc_references import CALC_TOKEN, CalcEvaluator
    from .numeric_text import (
        frozen_number_catalog,
        prompt_number_catalog,
        text_after_last_break,
        text_before_next_break,
    )

    contents = tuple(contents)
    catalog = frozen_number_catalog(contents)
    # 可用引用只列模型可见目录中的引用；仅供服务端核对的引用不作为改写候选。
    visible = prompt_number_catalog(catalog)
    failures: list[dict[str, Any]] = []

    def statement(match: re.Match[str]) -> str:
        return (text_after_last_break(markdown, match.start()) + match[0]
                + text_before_next_break(markdown, match.end()))[:240]

    for match in VALUE_TOKEN.finditer(markdown):
        if catalog.get(match[0], UNVERIFIED_TEXT) != UNVERIFIED_TEXT:
            continue
        reason, shown, candidates = value_reference_failure(match[0], catalog)
        failure: dict[str, Any] = {
            "reference": restore_revoked_references(match[0]),
            "statement": restore_revoked_references(statement(match)),
            "reason": reason,
            "candidates": [{"reference": item, "value": catalog[item]} for item in candidates if item in visible],
        }
        if REVOKED_SELECTOR in match[0]:
            failure["currentValue"] = shown
        failures.append(failure)
    if "{{calc:" in markdown:
        evaluator = CalcEvaluator(contents)
        for match in CALC_TOKEN.finditer(markdown):
            reason = evaluator.failure(match[0])
            if reason is not None:
                failures.append({"reference": match[0], "statement": statement(match),
                                 "reason": f"计算引用无法求值：{reason}", "candidates": []})
    return failures


def reference_failure_message(failure: Mapping[str, Any], hints: Iterable[str] = ()) -> str:
    """交回模型的单条纠错事实：引用、原因、所在语句与可用引用；修正方式由模型决定。"""
    parts = [f"数值引用无法登记：{failure['reference']}。原因：{failure['reason']}。所在语句：{failure['statement']}。"]
    if "currentValue" in failure:
        if failure["currentValue"]:
            parts.append(f"该引用的登记值为{failure['currentValue']}。")
        parts.extend(f"对齐提示：{hint}" for hint in hints)
    if failure["candidates"]:
        parts.append("可用引用：" + "；".join(f"{item['reference']}={item['value']}" for item in failure["candidates"]) + "。")
    parts.append(
        "按语句写出的指标、期间与统计方式改用可用引用；所需占比、合计、差额或完成率未登记时用 {{calc:...}} "
        "由登记值计算；正文与引用口径不符时改用对应引用或改写正文使两者一致；仍无依据时改写句子、不写该数值。"
        "不得手写数字，不得写待核实。"
    )
    return "".join(parts)


__all__ = [
    "REVOKED_SELECTOR",
    "UNKNOWN_FACT",
    "VALUE_TOKEN",
    "number_reference_failures",
    "reference_failure_message",
    "restore_revoked_references",
    "value_reference_failure",
]
