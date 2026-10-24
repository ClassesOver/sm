"""数值引用的书写规范化与失败原因。

模型写出的 ``{{value:fact:selector:unit}}`` 常有不改变身份的书写差异：事实编号缺前缀或大写、
期间区间用“—/~/至”分隔、月份不补零、单位写成“亿/％”。这些只按语法归一，引用身份
（事实与选择器）不变；仍无法登记的引用给出原因与同一事实的可选引用，供纠错轮次和编辑器说明。
"""

from __future__ import annotations

import re
from collections.abc import Mapping

VALUE_TOKEN = re.compile(r"\{\{\s*value\s*:[^{}\r\n]+\}\}")
REVOKED_SELECTOR = "unverified."
UNVERIFIED_TEXT = "数值待核实"

_UNIT_ALIASES = {
    "亿": "亿元", "万": "万元", "％": "%", "百分比": "%", "percent": "%", "pct": "%",
    "百分点": "个百分点", "pp": "个百分点", "万人": "万人次",
}
_BARE_FACT = re.compile(r"(?<![\w-])(?:fact-)?([0-9a-fA-F]{16})(?![\w])")
_RANGE = re.compile(r"(\d{4})-(\d{1,2})\s*(?:\.\.|…|[—–~～至到]|--?)\s*(\d{4})-(\d{1,2})(?!\d)")
_MONTH = re.compile(r"(?<![\d-])(\d{4})-(\d{1,2})(?![\d-])")


def _parts(token: str) -> list[str] | None:
    parts = [part.strip() for part in token.strip()[2:-2].split(":")]
    if parts[0] != "value" or len(parts) not in (3, 4):
        return None
    return parts if len(parts) == 4 else [*parts, ""]


def _selector(text: str) -> str:
    text = _BARE_FACT.sub(lambda match: "fact-" + match[1].lower(), re.sub(r"\s+", "", text))
    text = _RANGE.sub(lambda m: f"{m[1]}-{int(m[2]):02d}..{m[3]}-{int(m[4]):02d}", text)
    return _MONTH.sub(lambda m: f"{m[1]}-{int(m[2]):02d}", text)


def _identity_index(catalog: Mapping[str, str]) -> dict[tuple[str, str], list[str]]:
    index: dict[tuple[str, str], list[str]] = {}
    for token in catalog:
        parts = _parts(token)
        if parts is not None:
            index.setdefault((parts[1], parts[2]), []).append(token)
    return index


def canonical_value_references(markdown: str, catalog: Mapping[str, str]) -> str:
    """把书写差异的引用归一为已登记引用；身份不唯一或未登记时原样保留。"""
    index: dict[tuple[str, str], list[str]] | None = None

    def replace(match: re.Match[str]) -> str:
        nonlocal index
        token = match[0]
        parts = _parts(token)
        if token in catalog or parts is None:
            return token
        fact = _selector(parts[1])
        selector = _selector(parts[2])
        unit = _UNIT_ALIASES.get(parts[3], parts[3])
        candidate = "{{value:" + fact + ":" + selector + ":" + unit + "}}"
        if candidate in catalog:
            return candidate
        if index is None:
            index = _identity_index(catalog)
        # 同一事实与选择器只登记了一种显示单位时，单位只影响显示，不影响数值身份。
        same = index.get((fact, selector), [])
        return same[0] if len(same) == 1 else token

    return VALUE_TOKEN.sub(replace, markdown)


def value_reference_failure(token: str, catalog: Mapping[str, str]) -> tuple[str, str | None, list[str]]:
    """返回（面向读者的原因, 可展示的原引用值, 同一事实的可选引用）。原因不含内部编号。"""
    parts = _parts(token)
    if parts is None:
        return "数值引用格式无法识别", None, []
    fact, selector, unit = parts[1], parts[2], parts[3]
    if selector.startswith(REVOKED_SELECTOR):
        original = "{{value:" + fact + ":" + selector[len(REVOKED_SELECTOR):] + ":" + unit + "}}"
        shown = catalog.get(original)
        return (
            "正文写出的指标、期间或统计方式与所选引用不一致，且找不到唯一匹配的登记值，引用已撤销",
            shown if shown and shown != UNVERIFIED_TEXT else None,
            [],
        )
    if catalog.get(token) == UNVERIFIED_TEXT:
        return "该指标存在互相冲突的来源数值，无法确定采用哪一个", None, []
    same_fact = [item for item in catalog if item.startswith("{{value:" + fact + ":")]
    if not same_fact:
        return "引用的指标不在本章的登记数值中", None, []
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
    return "该指标没有登记这种取值方式（统计口径或期间）", None, suggestions[:5]


__all__ = [
    "REVOKED_SELECTOR",
    "VALUE_TOKEN",
    "canonical_value_references",
    "value_reference_failure",
]
