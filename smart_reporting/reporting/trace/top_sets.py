"""Complete Top-N sets from a frozen partition; prefixes never mint a population."""

from __future__ import annotations

import math
import re
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from ..hospital_operation.deterministic_analysis import DeterministicMetricFact
from .group_ranking import registered_group_rank

TOP_SET_SELECTOR = re.compile(r"topSet\.(rank|items)\.([1-9]\d?|100)$")


def _identity(group) -> tuple:
    return tuple(sorted(group.group_values.items()))


def registered_top_sets(
    entry: Mapping[str, Any],
    *,
    profile_hash: str | None = None,
    warnings: Sequence[str] = (),
) -> tuple[dict[str, dict], tuple[str, ...]]:
    """Reconstruct all finite selection results once per registered fact.

    `rank.N` includes every group of competition rank <= N. `items.N` selects
    exactly N groups, breaking equal values by structured group identity. Those
    are different requests even when they happen to yield identical members.
    """
    try:
        metric = DeterministicMetricFact.model_validate(entry)
    except (TypeError, ValueError):
        return {}, ("top_set_input_invalid",)
    if not metric.group_population:
        return {}, ("complete_group_population_unavailable",)
    if metric.series_missing_count != 0:
        return {}, ("top_set_numeric_completeness_unproven",)
    from .subject_builder import fact_periods

    periods = fact_periods(entry)
    if metric.period_aggregation == "last":
        periods = periods[-1:]
    _, reasons = registered_group_rank(
        entry,
        "topGroups.0",
        periods,
        profile_hash=profile_hash,
        warnings=warnings,
        allow_row_counts=True,
    )
    if reasons:
        return {}, reasons
    population = metric.group_population
    grain = set(population[0].group_values)
    identities = set()
    for group in population:
        if (
            not grain
            or set(group.group_values) != grain
            or any(
                not isinstance(value, str) or not value.strip()
                for value in group.group_values.values()
            )
            or not math.isfinite(group.value)
        ):
            return {}, ("top_set_group_identity_invalid",)
        identity = _identity(group)
        if identity in identities:
            return {}, ("top_set_group_identity_duplicate",)
        if any(key in metric.scope and metric.scope[key] != value for key, value in identity):
            return {}, ("top_set_scope_conflict",)
        identities.add(identity)
    try:
        total = math.fsum(group.value for group in population)
    except (ValueError, OverflowError):
        return {}, ("top_set_partition_total_mismatch",)
    tolerance = max(math.ulp(total), math.ulp(metric.total)) * 4 if math.isfinite(total) else 0
    if not math.isfinite(total) or not math.isclose(
        total, metric.total, rel_tol=0, abs_tol=tolerance
    ):
        return {}, ("top_set_partition_total_mismatch",)
    # Frozen producer's extreme prefixes must be the actual extremes of this
    # same complete partition, not an unrelated correctly summing table.
    for candidates, descending in ((metric.top_groups, True), (metric.bottom_groups, False)):
        expected = sorted(
            population, key=lambda group: (-group.value if descending else group.value, group.group)
        )[:10]
        if [(_identity(group), group.value) for group in candidates] != [
            (_identity(group), group.value) for group in expected
        ]:
            return {}, ("top_set_extreme_prefix_mismatch",)
    ordered = sorted(population, key=lambda group: (-group.value, _identity(group)))
    ranks: list[int] = []
    for position, group in enumerate(ordered):
        ranks.append(
            position + 1
            if not position or group.value != ordered[position - 1].value
            else ranks[-1]
        )
    members = tuple(dict(group.group_values) for group in ordered)
    sums = [Decimal(0)]
    for group in ordered:
        sums.append(sums[-1] + Decimal(str(group.value)))
    result = {}
    for limit in range(1, 101):
        for mode in ("rank", "items"):
            if mode == "items" and limit > len(ordered):
                continue
            count = bisect_right(ranks, limit) if mode == "rank" else limit
            result[f"topSet.{mode}.{limit}"] = {
                "mode": mode,
                "limit": limit,
                "members": members[:count],
                "memberCount": count,
                "populationCount": len(population),
                "periods": tuple(periods),
                "populationScope": dict(metric.scope),
                "value": sums[count],
            }
    return result, ()


def display_members(members: Sequence[Mapping[str, str]]) -> str:
    """Readable full identities; delimiters in source data cannot mint members."""
    from .assertions import _label

    def atom(value: str) -> str:
        text = _label(value)
        for char in "。！？;；〔〕、，=":
            text = text.replace(char, f"\\u{ord(char):04x}")
        return text

    return "、".join(
        "〔"
        + "，".join(f"{atom(key)}={atom(value)}" for key, value in sorted(member.items()))
        + "〕"
        for member in members
    )


def top_set_wording_warnings(text: str, reference: Mapping[str, Any]) -> list[str]:
    selector = reference["selector"]
    mentions = bool(
        re.search(
            r"(?:Top\s*\d+|前\s*[一二三四五六七八九十百\d]+\s*[名个位]|完整成员清单)", text, re.I
        )
    )
    if not selector.startswith("topSet."):
        return (
            ["完整排名集合需复核：普通合计或单个分组引用不能证明完整Top-N集合。"]
            if mentions
            else []
        )
    reasons: tuple[str, ...]
    if "_top_set_proof" in reference:
        proof = reference["_top_set_proof"]
        reasons = ()
    else:
        sets, reasons = registered_top_sets(reference["entry"])
        proof = sets.get(selector)
    if reasons or proof is None or tuple(reference["periods"]) != proof["periods"]:
        return ["完整排名集合需复核：当前来源没有可验证的完整分组总体和选择规则。"]
    rule = (
        "竞赛排名，含边界全部并列" if proof["mode"] == "rank" else "同值按结构化分组键升序打破平局"
    )
    noun = "名" if proof["mode"] == "rank" else "个"
    expected = f"降序取前{proof['limit']}{noun}（{rule}）"
    marker = "完整成员清单："
    try:
        start = text.index(marker) + len(marker)
        observed = text[start:].split("，所列成员合计为", 1)[0]
        if observed != display_members(proof["members"]):
            return ["完整排名集合需复核：成员被增删、替换或并列边界未完整保留。"]
        from .business_semantics import mask_registered_display_data

        qualifiers = mask_registered_display_data(text, reference)
        normalized = qualifiers.replace(",", "，").replace("(", "（").replace(")", "）")
        from .group_ranking import _rank_number

        def limit_number(raw: str) -> int | None:
            return 100 if raw in {"一百", "百"} else _rank_number(raw)

        if (
            proof["limit"] > proof["populationCount"]
            and "当前登记总体成员少于所请求名次上限" not in qualifiers
        ):
            return ["完整排名集合需复核：当前总体不足所请求名次上限，必须保留实际容量说明。"]
        for count in re.finditer(
            r"(?:成员共|成员数量为|成员总数为|共包含)\s*(\d+)个?|(?<!总体)共\s*(\d+)个(?:成员|分组)",
            qualifiers,
        ):
            if int(count[1] or count[2]) != proof["memberCount"]:
                return ["完整排名集合需复核：正文成员数量与完整名单不一致。"]
        for count in re.finditer(r"总体(?:共|包含|有)\s*(\d+)个(?:分组|成员)", qualifiers):
            if int(count[1]) != proof["populationCount"]:
                return ["完整排名集合需复核：正文总体数量与冻结总体不一致。"]
        for mention in re.finditer(
            r"(?:Top\s*([1-9]\d{0,2})(?!\d)|前\s*([一二三四五六七八九十百\d]+)\s*([名个]))",
            normalized,
            re.I,
        ):
            if limit_number(mention[1] or mention[2]) != proof["limit"] or (
                mention[3] and mention[3] != noun
            ):
                return ["完整排名集合需复核：正文包含不同数量或不同选择口径的Top-N限定。"]
        normalized = re.sub(
            r"前\s*([一二三四五六七八九十百\d]+)\s*([名个])",
            lambda match: f"前{limit_number(match[1])}{match[2]}",
            normalized,
        )
        if expected not in normalized or re.search(
            r"唯一|独占|倒数|升序|并非|不是|不代表|不含并列", qualifiers.replace(rule, "")
        ):
            return ["完整排名集合需复核：Top-N数量、方向、并列规则或限定与冻结证明不一致。"]
    except (ValueError, TypeError):
        return ["完整排名集合需复核：成员清单缺失或不可唯一解析。"]
    return []


def requested_top_set_limits(text: str) -> tuple[int, ...]:
    """A request chooses an existing finite proof; it never defines its result."""
    from .group_ranking import _rank_number

    limits = set()
    mentions = list(
        re.finditer(
            r"Top\s*(\d+)(?!\d)|前\s*([零一二三四五六七八九十百\d]+)\s*[名个项组]", text, re.I
        )
    )
    for match in mentions:
        raw_limit = match[1] or match[2]
        number = 100 if raw_limit in {"百", "一百"} else _rank_number(raw_limit)
        if number is not None and 1 <= number <= 100:
            limits.add(number)
    return tuple(sorted(limits)) if mentions else (3, 5, 10)
