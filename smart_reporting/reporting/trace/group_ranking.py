"""Competition ranks over server-frozen extreme prefixes, never list positions.

The deterministic producer sorts all groups before retaining each prefix. A
prefix contains every strictly better value for any member, including when a
tie crosses the truncation boundary. It cannot establish uniqueness or the
number of groups sharing a rank.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from ..hospital_operation.deterministic_analysis import DeterministicMetricFact, _parse_period


def registered_group_rank(
    entry: Mapping[str, Any],
    selector: str,
    periods: Sequence[str],
    *,
    profile_hash: str | None = None,
    warnings: Sequence[str] = (),
    allow_row_counts: bool = False,
) -> tuple[dict | None, tuple[str, ...]]:
    """Use only an identity-checked producer record; reject malformed prefixes."""
    try:
        metric = DeterministicMetricFact.model_validate(entry)
        array, raw_index = selector.split(".")
        if array not in {"topGroups", "bottomGroups"} or not raw_index.isdigit():
            return None, ("ranking_selector_invalid",)
        groups = metric.top_groups if array == "topGroups" else metric.bottom_groups
        selected = groups[int(raw_index)]
    except (ValueError, TypeError, IndexError):
        return None, ("ranking_input_invalid",)
    if profile_hash is not None and metric.profile_hash != profile_hash:
        return None, ("ranking_input_identity_mismatch",)
    if not metric.scope or not metric.unit or not periods:
        return None, ("ranking_context_unknown",)
    if (
        metric.aggregation not in ({"sum", "count"} if allow_row_counts else {"sum"})
        or metric.unit in {"%", "个百分点"}
        or "/" in metric.unit
        or "／" in metric.unit
    ):
        return None, ("ranking_aggregation_not_supported",)
    if metric.missing_count != 0 or metric.period_missing_count != 0 or metric.warnings or warnings:
        return None, ("ranking_completeness_unproven",)
    if len(periods) > 1:
        parsed = [_parse_period(period) for period in periods]
        if metric.period_aggregation != "sum" or any(
            period is None or period.granularity != "month" for period in parsed
        ):
            return None, ("ranking_time_additivity_unproven",)
        months = [
            period.value.year * 12 + period.value.month for period in parsed if period is not None
        ]
        if months != list(range(months[0], months[0] + len(months))):
            return None, ("ranking_time_additivity_unproven",)
    grain = set(selected.group_values)
    if not grain or not math.isfinite(metric.total):
        return None, ("ranking_group_identity_unavailable",)
    all_values: dict[tuple[tuple[str, str | None], ...], float] = {}
    identities_by_side = []
    for candidates, descending in ((metric.top_groups, True), (metric.bottom_groups, False)):
        local = set()
        previous = None
        for group in candidates:
            if set(group.group_values) != grain or any(
                not isinstance(value, str) or not value.strip()
                for value in group.group_values.values()
            ):
                return None, ("ranking_group_identity_unavailable",)
            if any(
                key in metric.scope and metric.scope[key] != value
                for key, value in group.group_values.items()
            ):
                return None, ("ranking_scope_conflict",)
            identity = tuple(sorted(group.group_values.items()))
            if (
                not math.isfinite(group.value)
                or identity in local
                or (identity in all_values and all_values[identity] != group.value)
            ):
                return None, ("ranking_group_conflict",)
            if previous is not None and (
                group.value > previous if descending else group.value < previous
            ):
                return None, ("ranking_order_invalid",)
            previous = group.value
            local.add(identity)
            all_values[identity] = group.value
        identities_by_side.append(local)
    # Opposite tails must not reveal an omitted strictly better group.
    for candidates, identities, descending in (
        (metric.top_groups, identities_by_side[0], True),
        (metric.bottom_groups, identities_by_side[1], False),
    ):
        if candidates and any(
            value > candidates[-1].value if descending else value < candidates[-1].value
            for identity, value in all_values.items()
            if identity not in identities
        ):
            return None, ("ranking_prefix_conflict",)
    descending = array == "topGroups"
    rank = 1 + sum(
        group.value > selected.value if descending else group.value < selected.value
        for group in groups
    )
    return {
        "rank": rank,
        "order": "descending" if descending else "ascending",
        "groupScope": dict(selected.group_values),
        "populationScope": dict(metric.scope),
    }, ()


_ORDINAL = r"[0-9]+|[一二三四五六七八九十百]+"
_RANK = re.compile(
    rf"(?:排名|位居|位列|排行|独占|独居|单独|并列|唯一)(?:为)?\s*第?\s*(?P<qualified>{_ORDINAL})(?:\s*[名位])?"
    rf"|第\s*(?P<plain>{_ORDINAL})\s*[名位]"
)


def _rank_number(word: str) -> int | None:
    if word.isdigit():
        return int(word)
    digits = {word: number for number, word in enumerate("一二三四五六七八九", 1)}
    if word in digits:
        return digits[word]
    if word == "十":
        return 10
    if word.count("十") == 1:
        left, right = word.split("十")
        if (not left or left in digits) and (not right or right in digits):
            return digits.get(left, 1) * 10 + digits.get(right, 0)
    return None


def group_rank_wording_warnings(text: str, reference: Mapping[str, Any]) -> list[str]:
    """Check rank qualifiers owned by this numeric reference, including edits."""
    if not reference["selector"].startswith(("topGroups.", "bottomGroups.")):
        return []
    # Source dimension values are data, not wording supplied by the author.
    for key, value in reference.get("scope", {}).items():
        text = text.replace(f"{key}={value}", "")
    matches = list(_RANK.finditer(text))
    extremes = re.findall(r"最高|最大|最多|居首|最低|最小|最少|垫底", text)
    if not matches and not extremes:
        return []
    if re.search(r"不是|并非|未必|不能|并不|不在|未进入", text):
        return ["分组排名需复核：否定或复合排名表述尚未完成语义校验。"]
    proof, reasons = registered_group_rank(
        reference["entry"], reference["selector"], reference["periods"]
    )
    if reasons or proof is None:
        return ["分组排名需复核：当前冻结来源不足以证明名次。"]
    warnings = []
    ascending = bool(re.search(r"升序|从低到高|由低到高|从小到大|倒数", text))
    descending = bool(re.search(r"降序|从高到低|由高到低|从大到小", text))
    # A bottom prefix proves ascending ranks, not descending ranks in an
    # unknown-size population. Never infer the opposite direction.
    if matches and (
        ascending == descending
        and ascending
        or proof["order"] != ("ascending" if ascending else "descending")
    ):
        warnings.append("分组排名需复核：当前引用不能证明正文所用的排序方向。")
    elif any(
        _rank_number(match["qualified"] or match["plain"]) != proof["rank"] for match in matches
    ):
        warnings.append(f"分组排名需复核：按同值同名次的竞赛排名，当前分组为第{proof['rank']}名。")
    for word in extremes:
        expected_order = "ascending" if word in {"最低", "最小", "最少", "垫底"} else "descending"
        if proof["order"] != expected_order or proof["rank"] != 1:
            warnings.append("分组排名需复核：当前引用不能证明该最高/最低表述。")
    if re.search(r"唯一|独占|独居|独自|单独|仅此|密集排名|顺序排名", text):
        warnings.append("分组排名需复核：截断的分组目录不证明唯一名次，也不能改用其他排名规则。")
    return list(dict.fromkeys(warnings))
