"""Finite business qualifiers over registered evidence, without causal inference."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, localcontext
from typing import Any

_SHAPE = re.compile(
    r"先(?:严格)?(?:上升|增长|增加|回升|升|增)后(?:严格)?(?:下降|回落|减少|降|减)"
    r"|先(?:严格)?(?:下降|回落|减少|降|减)后(?:严格)?(?:上升|增长|增加|回升|升|增)|单峰|单谷"
)
_PATH = re.compile(
    r"(?:先|后|再|随后|继而|接着|最后)(?:严格)?(?:上升|增长|下降|回落|持平|不变|升|降)"
)
_NET = re.compile(
    r"(?:总体|整体|期末(?:较|比)期初)(?:仍|继续|保持)?(?P<direction>增长|上升|下降|回落|持平|不变)"
)
_DELTA = re.compile(r"相邻月绝对(?P<kind>增量|减量)(?:严格|逐月)?(?P<direction>扩大|缩小|持平)")
_RATE = re.compile(
    r"相邻月环比(?P<kind>增长率|相对变化率)(?:严格|逐月)?(?P<direction>上升|下降|持平)"
)
_TURN_DECL = re.compile(
    r"(?:唯一)?(?:峰值|谷值)(?:月份(?:为|在|[=：:])|(?:为|在|[=：:])(?=\s*(?:\d{4}[-/年]|今年|去年|明年|本月)))"
)
_TURN = re.compile(
    r"(?:唯一)?(?P<kind>峰值|谷值)(?:月份)?(?:为|在|[=：:])\s*"
    r"(?P<year>\d{4})[-/年](?P<month>\d{1,2})月?(?![\d/.-])"
)
_NEGATION = re.compile(
    r"(?:不(?:能|可|足以)?(?:据此)?(?:证明|认定|说明|推断)?|尚未(?:证明|建立)"
    r"|并非|不是|不代表|不作为|不构成|不建立|不涉及|不存在|非|无"
    r"|(?:无法|未能|尚不能)(?:据此)?(?:证明|认定|说明|推断)?"
    r"|不能(?:据此)?(?:认定|证明|判定)(?:其)?为(?:增长|变化)?"
    r"|没有证据(?:证明|表明))\s*$"
)


def monthly_shape_details(entry: Mapping[str, Any]) -> dict:
    """Arithmetic only; caller must first establish full monthly window support."""
    with localcontext() as context:
        context.prec = 64
        amounts = [Decimal(str(item["value"])) for item in entry["periodValues"]]
        differences = [right - left for left, right in zip(amounts, amounts[1:])]
        signs = [1 if value > 0 else -1 if value < 0 else 0 for value in differences]
        turning = [index for index in range(1, len(signs)) if signs[index] != signs[index - 1]]
        shape = None
        turn = None
        if 0 not in signs and len(turning) == 1:
            shape = "single_peak" if signs[0] == 1 else "single_valley"
            from ..hospital_operation.deterministic_analysis import _parse_fact_period

            parsed = _parse_fact_period(entry["periodValues"][turning[0]]["period"], "month")
            turn = (
                f"{parsed.value.year:04d}-{parsed.value.month:02d}" if parsed is not None else None
            )
        rates = (
            [difference / baseline * 100 for difference, baseline in zip(differences, amounts)]
            if all(value > 0 for value in amounts)
            else None
        )
        return {
            "shape": shape,
            "turningPeriod": turn,
            "amounts": amounts,
            "differences": differences,
            "relativeRates": rates,
        }


def _direction(values, direction: str) -> bool:
    if len(values) < 2:
        return False
    if direction in {"扩大", "上升"}:
        return all(right > left for left, right in zip(values, values[1:]))
    if direction in {"缩小", "下降"}:
        return all(right < left for left, right in zip(values, values[1:]))
    return len(set(values)) == 1


def complex_monthly_semantics(text: str, reference: Mapping[str, Any]) -> tuple[list[str], str]:
    matches = (
        list(_SHAPE.finditer(text))
        + list(_DELTA.finditer(text))
        + list(_RATE.finditer(text))
        + list(_TURN_DECL.finditer(text))
        + list(_TURN.finditer(text))
    )
    if reference["selector"] == "monthlyTrend":
        matches += list(_NET.finditer(text))
    if not matches:
        return (
            (["复杂趋势需复核：该路径形状或连接规则尚未完成验证。"], text)
            if _PATH.search(text)
            else ([], text)
        )
    if reference["selector"] != "monthlyTrend":
        return ["复杂趋势需复核：当前引用不是覆盖完整登记月份的趋势证明。"], text
    from .monthly_trends import registered_monthly_trend

    proof, reasons = registered_monthly_trend(reference["entry"])
    if reasons or proof is None or tuple(reference["periods"]) != proof["periods"]:
        return ["复杂趋势需复核：期间、完整性或统计口径尚未核验。"], text
    if re.search(r"预计|预测|有望|并非|不是|未必|不代表|不能|累计|同比", text):
        return ["复杂趋势需复核：预测、否定、累计或同比路径不由登记月值形状证明。"], text
    details = monthly_shape_details(reference["entry"])
    warnings = []
    for match in _SHAPE.finditer(text):
        expected = (
            "single_valley"
            if match[0].startswith(
                (
                    "先下降",
                    "先严格下降",
                    "先回落",
                    "先严格回落",
                    "先降",
                    "先严格降",
                    "先减",
                    "先严格减",
                    "单谷",
                )
            )
            else "single_peak"
        )
        if details["shape"] != expected:
            warnings.append(
                "复杂趋势需复核：全部未舍入月值不满足所述严格单峰/单谷路径，平台与多次反转不能忽略。"
            )
    for match in _DELTA.finditer(text):
        differences = details["differences"]
        if match["kind"] == "增量":
            valid = all(value > 0 for value in differences)
            amounts = differences
        else:
            valid = all(value < 0 for value in differences)
            amounts = [-value for value in differences]
        if not valid or not _direction(amounts, match["direction"]):
            warnings.append("复杂趋势需复核：绝对增量/减量的逐月变化与登记差额不一致。")
    for match in _RATE.finditer(text):
        rates = details["relativeRates"]
        if (
            rates is None
            or (match["kind"] == "增长率" and any(value <= 0 for value in rates))
            or not _direction(rates or (), match["direction"])
        ):
            warnings.append(
                "复杂趋势需复核：相对增速需正基期及全部相邻月变化率，不能用绝对增量代替。"
            )
    for match in _NET.finditer(text):
        start, end = details["amounts"][0], details["amounts"][-1]
        direction = match["direction"]
        supported = (
            end > start
            if direction in {"增长", "上升"}
            else end < start
            if direction in {"下降", "回落"}
            else end == start
        )
        if not supported:
            warnings.append(
                "复杂趋势需复核：整体首末变化方向与登记窗口不一致，不能用中间反弹替代整体变化。"
            )
    for declaration in _TURN_DECL.finditer(text):
        if _TURN.match(text, declaration.start()) is None:
            warnings.append("复杂趋势需复核：峰值/谷值期间未提供可唯一核对的登记年月。")
    for match in _TURN.finditer(text):
        amounts = details["amounts"]
        extreme = max(amounts) if match["kind"] == "峰值" else min(amounts)
        indices = [index for index, value in enumerate(amounts) if value == extreme]
        period = f"{int(match['year']):04d}-{int(match['month']):02d}"
        if len(indices) != 1 or proof["periods"][indices[0]] != period:
            warnings.append("复杂趋势需复核：峰值/谷值月份或唯一性与登记月份不一致。")
    # Remove only qualifiers that this finite checker actually evaluated. The
    # existing trend checker still reviews the remaining direction/limitations.
    mask = list(text)
    for match in matches:
        mask[match.start() : match.end()] = " " * len(match[0])
    cleaned = "".join(mask)
    if _PATH.search(cleaned):
        warnings.append("复杂趋势需复核：剩余路径形状或连接规则未由当前证明覆盖。")
    return list(dict.fromkeys(warnings)), cleaned


def unsupported_business_warnings(text: str) -> list[str]:
    """A deterministic level/rank/trend proof has no causal/study/forecast design."""
    checks = (
        (
            r"导致|造成|归因于|驱动|拉动|主因|根因|因果关系",
            "业务推断需复核：登记值、排名或时间路径不能证明因果与驱动机制。",
        ),
        (
            r"统计显著|显著性|显著(?:增长|上升|下降|改善|降低|增加)",
            "业务推断需复核：统计显著性需要明确检验设计与登记结果。",
        ),
        (
            r"预计|预测|有望|未来|明年|将(?:增长|下降|达到|增加|减少)",
            "业务推断需复核：历史登记值不能直接支持未来预测。",
        ),
        (
            r"贡献率|算术贡献|贡献了|贡献占",
            "业务推断需复核：贡献分解需要同期完整可加分项及统一差额分母，不能从占比推断。",
        ),
    )
    warnings = []
    for pattern, warning in checks:
        for match in re.finditer(pattern, text):
            prefix = text[: match.start()]
            if not _NEGATION.search(prefix):
                warnings.append(warning)
                break
    for match in re.finditer(
        r"(?:全部|所有|每个|各)(?:分组|科室|院区|部门|地区)(?:均|都|全部)?(?:增长|上升|下降|改善|增加|减少)",
        text,
    ):
        if not re.search(
            r"(?:不能|不可|无法|不足以)(?:据此)?(?:证明|推断|认定|判定)\s*$", text[: match.start()]
        ):
            warnings.append(
                "业务推断需复核：总体或部分分组的变化不能证明全部分组同向变化，需完整同期分组对照。"
            )
            break
    return warnings


def registered_trend_qualifiers(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """Deterministic display qualifiers; call only after full trend validation."""
    details = monthly_shape_details(entry)
    qualifiers = []
    if details["shape"] is not None:
        if details["shape"] == "single_peak":
            qualifiers.append(f"先严格上升后严格下降（唯一峰值月份={details['turningPeriod']}）")
        else:
            qualifiers.append(f"先严格下降后严格上升（唯一谷值月份={details['turningPeriod']}）")
    differences = details["differences"]
    if all(value > 0 for value in differences):
        for word in ("扩大", "缩小", "持平"):
            if _direction(differences, word):
                qualifiers.append("相邻月绝对增量严格" + word)
    if all(value < 0 for value in differences):
        for word in ("扩大", "缩小", "持平"):
            if _direction([-value for value in differences], word):
                qualifiers.append("相邻月绝对减量严格" + word)
    rates = details["relativeRates"]
    if rates is not None:
        for word in ("上升", "下降", "持平"):
            if _direction(rates, word):
                qualifiers.append("相邻月环比相对变化率严格" + word)
    return tuple(qualifiers)


def mask_registered_display_data(text: str, reference: Mapping[str, Any]) -> str:
    """Quoted Top-N members are source data, not unquoted business predicates."""
    if reference["selector"].startswith("topSet."):
        marker = "完整成员清单："
        try:
            start = text.index(marker) + len(marker)
            end = text.index("，所列成员合计为", start)
            text = text[:start] + " " * (end - start) + text[end:]
        except ValueError:
            pass  # An invalid list already receives a Top-N membership warning.
    for key, value in reference.get("scope", {}).items():
        text = text.replace(f"{key}={value}", "")
    from .assertions import _label

    entry = reference.get("entry", {})
    for name in (entry.get("displayName"), entry.get("field"), *(entry.get("aliases") or ())):
        if isinstance(name, str) and name:
            label = _label(name)
            text = text.replace(f"{label}按未舍入登记月值", "指标按未舍入登记月值")
            text = text.replace(f"按{label}未舍入登记分组值", "按指标未舍入登记分组值")
    return text
