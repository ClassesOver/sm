"""正文复核：比较口径与变化方向（变化额、约数、起止写法）。"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .numeric_text import (
    DIRECTION_WORD_PATTERN,
    FALLING_WORDS,
    RISING_WORDS,
    _frozen_number_entries,
    _unit_scales,
    describes_rate_level,
)
from .review_common import _CHINESE_DIGITS, _CLAUSE_BREAK

_COMPARISON_AMOUNT_CLAIM = re.compile(
    rf"(?P<kind>同比|环比|较上年同期|较去年同期|较上年|较去年|较上月)(?P<verb>{DIRECTION_WORD_PATTERN})"
    r"(?:了|约|为|达)?\s*(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*"
    r"(?P<unit>亿元|万元|元|万人次|人次|床日|个百分点)"
)


def _comparison_amount_warnings(text: str, contents: Iterable[str], documents: list[dict[str, Any]]) -> list[str]:
    """变化额的比较口径与方向核对（软告警），与变化率的同比/环比检查对应。

    “环比增加654.32万元”只对得上已登记的同比变化额，或“同比减少654.32万元”对应
    的登记变化额为正时提示复核；数字本身已登记，无依据数值检查不会拦下这类口径错误。
    """
    types = {entry["factId"]: entry["comparisonType"]
             for document in documents for entry in document.get("comparisons") or ()
             if isinstance(entry, dict) and isinstance(entry.get("factId"), str)
             and entry.get("comparisonType") in {"yoy", "mom"}}
    if not types:
        return []
    amounts: dict[tuple[str, str], set[Decimal]] = {}
    for token, value, unit, target in _frozen_number_entries(contents):
        _, fact_id, field, *_rest = token[2:-2].split(":")
        display_unit = target or unit
        if field != "change" or fact_id not in types or not display_unit or value is None:
            continue
        number = Decimal(str(value))
        if display_unit != unit and (scales := _unit_scales(unit)) is not None:
            number = number * scales[unit] / scales[display_unit]
        amounts.setdefault((types[fact_id], display_unit), set()).add(number)
    warnings: list[str] = []
    for match in _COMPARISON_AMOUNT_CLAIM.finditer(text):
        if describes_rate_level(text[:match.start()]):
            continue
        written = abs(Decimal(match["number"].replace(",", "")))
        quantum = Decimal(1).scaleb(-(len(match["number"].split(".")[1]) if "." in match["number"] else 0))
        stated = "mom" if match["kind"] in {"环比", "较上月"} else "yoy"
        other = "yoy" if stated == "mom" else "mom"

        def same_magnitude(kind: str) -> list[Decimal]:
            return [value for value in amounts.get((kind, match["unit"]), ())
                    if abs(value).quantize(quantum, rounding=ROUND_HALF_UP) == written]

        stated_values = same_magnitude(stated)
        if not stated_values and same_magnitude(other):
            label = "环比" if other == "mom" else "同比"
            warnings.append(f"同比/环比口径混淆：{match[0]}。该变化额对应已登记的{label}比较，请核对比较口径。")
            continue
        falling = match["verb"] in FALLING_WORDS
        signed = [value for value in stated_values if value]
        if (signed and not match["number"].startswith(("-", "+"))
                and all((value > 0) == falling for value in signed)):
            warnings.append(f"方向与登记变化额相反：{match[0]}。请核对增减方向。")
    return list(dict.fromkeys(warnings))


_FROM_TO_CHANGE = re.compile(
    r"(?:由|从)\s*(?P<a>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?P<ua>亿元|万元|元|万人次|人次|床日|%)"
    rf"[^。；，,\n\d]{{0,6}}?(?P<verb>{DIRECTION_WORD_PATTERN}|降|升)(?:到|至|为)"
    r"\s*(?P<b>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?P<ub>亿元|万元|元|万人次|人次|床日|%)"
)


# “同比增长约三成”“翻一番”“增长近一倍”“腰斩”：用中文约数概括变化率。“X成”须紧跟增减词，
# “三成科室”“占比约三成”是比例，不是变化率。
_APPROXIMATE_RATE = re.compile(
    rf"(?P<verb>{DIRECTION_WORD_PATTERN})了?(?:幅度)?(?:达|为)?"
    r"(?P<q>大约|接近|将近|超过|不足|不到|近|约|超|逾)?(?P<n>[一二两三四五六七八九])成"
    r"|翻(?:了)?(?P<turns>一|两|二|三)?番"
    r"|(?:增长|增加|提高|上升)了?(?P<qt>大约|接近|将近|超过|不足|不到|近|约|超|逾)?(?P<times>一|两|二|三)倍"
    r"|(?P<half>腰斩|减半)"
)


def _approximate_rate_bounds(match: re.Match[str]) -> tuple[Decimal, Decimal, str]:
    """约数对应的变化率幅度区间（百分数，下界含、上界含）与表述口径。"""
    if match["n"]:
        value, step, qualifier = Decimal(10 * _CHINESE_DIGITS[match["n"]]), Decimal(10), match["q"]
    elif match["half"]:
        value, step, qualifier = Decimal(50), Decimal(10), None
    else:
        turns = _CHINESE_DIGITS[match["turns"]] if match["turns"] else 1
        times = _CHINESE_DIGITS[match["times"]] if match["times"] else None
        value = Decimal(100 * times) if times else Decimal(2 ** turns * 100 - 100)
        step, qualifier = value / 2, match["qt"]
    if qualifier in {"近", "接近", "将近"}:
        return value - step / 2, value, qualifier
    if qualifier in {"超过", "超", "逾"}:
        return value, value + step, qualifier
    if qualifier in {"不足", "不到"}:
        return value - step, value, qualifier
    return value - step / 2, value + step / 2, qualifier or ""


def _adjacent_month_rates(contents: Iterable[str]) -> set[Decimal]:
    """服务端按月度登记值计算的相邻两月变化率（环比口径）。"""
    return {Decimal(str(value)) for token, value, _unit, _target in _frozen_number_entries(contents)
            if value is not None and token[2:-2].split(":")[2].startswith("periodChangeRates.")}


def _approximate_rate_warnings(text: str, documents: list[dict[str, Any]],
                               contents: Iterable[str] = ()) -> list[str]:
    """“同比增长约三成”与登记的同比变化率都不符时提示复核（软告警）。

    只在分句写明同比/环比（或较上年/较上月）时判定，保留登记变化率的增减方向；
    任一登记值方向一致且落在约数区间内即不告警，不判断该约数指向哪个指标。
    """
    rates: dict[str, set[Decimal]] = {"yoy": set(), "mom": set()}
    for document in documents:
        for entry in document.get("comparisons") or ():
            if (isinstance(entry, dict) and entry.get("comparisonType") in rates
                    and isinstance(entry.get("changeRate"), (int, float)) and not isinstance(entry.get("changeRate"), bool)):
                rates[entry["comparisonType"]].add(Decimal(str(entry["changeRate"])))
    rates["mom"].update(_adjacent_month_rates(contents))
    warnings: list[str] = []
    for clause in _CLAUSE_BREAK.split(text):
        kind = ("yoy" if re.search(r"同比|较上年|较去年|比上年|比去年", clause)
                else "mom" if re.search(r"环比|较上月|比上月", clause) else None)
        if kind is None or not rates[kind] or re.search(r"不是|并非|未必|不能", clause):
            continue
        for match in _APPROXIMATE_RATE.finditer(clause):
            low, high, _qualifier = _approximate_rate_bounds(match)
            if match["half"] or match["verb"] in FALLING_WORDS:
                low, high = -high, -low
            if any(low <= rate <= high for rate in rates[kind]):
                continue
            label = "同比" if kind == "yoy" else "环比"
            registered = "、".join(f"{rate:.2f}%" for rate in sorted(rates[kind])[:3])
            warnings.append(f"约数表述需复核：{match[0]}与登记的{label}变化率（{registered}）不符；"
                            "请直接写登记变化率或调整约数。")
    return list(dict.fromkeys(warnings))


def _from_to_direction_warnings(text: str) -> list[str]:
    """“由X增长至Y”而 X 大于 Y（或“下降至”而 X 小于 Y）时提示方向矛盾（软告警）。

    两端数值都写在句中，按同一量纲换算后直接比较，不依赖冻结事实。
    """
    warnings: list[str] = []
    for match in _FROM_TO_CHANGE.finditer(text):
        units = (match["ua"], match["ub"])
        scales = _unit_scales(units[0])
        if units[0] != units[1] and (scales is None or units[1] not in scales):
            continue
        start, end = (Decimal(match[key].replace(",", "")) for key in ("a", "b"))
        if scales is not None:
            start, end = start * scales[units[0]], end * scales[units[1]]
        if start == end:
            continue
        rising = match["verb"] in RISING_WORDS or match["verb"] == "升"
        if rising != (end > start):
            actual = "增加" if end > start else "减少"
            warnings.append(f"方向矛盾：{match[0]}。数值实际在{actual}，请核对增减措辞或起止数值。")
    return warnings
