"""写作时的引用句核对：与发布后编辑器的语句核对走同一路径。

编辑器在发布后按质量包逐个核对数值引用所在语句的期间、期间角色与业务范围（statementReview）；
写作时只做数值与口径核对，模型看不到这些提醒，正确与否要等发布后才暴露。这里按最终渲染锚定
后，用质量包相同的检查函数与参数逐个核对，让写作时的纠错轮次看到与编辑器一致的提醒。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from .comparison_proofs import period_list_text
from .numeric_text import frozen_number_catalog, text_after_last_break, text_before_next_break
from .semantic_bindings import NumberReferenceResolver, anchor_bound_numbers, render_bound_numbers
from .subject_builder import (
    _PERIOD_TEXT_MISMATCH,
    _period_key,
    _reference_local_window,
    prepare_claim_status,
    written_period_keys,
)

STATEMENT_REVIEW_PREFIX = "引用句与登记口径不一致："
_MARKER = re.compile(r"\[\[[^\]\r\n]+\]\]")


def statement_review_warnings(
    markdown: str,
    contents: Iterable[str],
    *,
    field_definitions: Mapping[str, str] | None = None,
    table_sources: Mapping[str, bytes] | None = None,
    assertions: Mapping[str, Any] | None = None,
) -> list[str]:
    """返回与编辑器语句核对一致的提醒（附所在语句）；全部一致时返回空列表。"""
    contents = tuple(contents)
    rendered, references, notices = render_bound_numbers(
        markdown, contents, key="statement-review", field_definitions=field_definitions,
        table_sources=table_sources, assertions=assertions,
    )[:3]
    if not references:
        return []
    anchored = anchor_bound_numbers(rendered, references, notices)
    check_claim = prepare_claim_status(anchored)
    resolver = NumberReferenceResolver(contents)
    number_catalog = frozen_number_catalog(contents)
    alternative_index = _metric_alternative_index(resolver)
    warnings: list[str] = []
    for reference in references:
        # 与质量包一致：能由服务端解析的数值引用（含派生值）与计算引用都核对所在语句，补证表推导不做语句核对。
        if reference.table_derivation is not None:
            continue
        selected = resolver.resolve(reference.token)
        if selected is None:
            continue
        detail = check_claim(
            reference.claim_id,
            selected["value"],
            expected_unit=selected["unit"],
            expected_periods=selected["periods"],
            expected_scope=selected["scope"],
            expected_period_roles=selected["period_roles"],
            expected_reference=selected,
        )
        if not detail["warnings"]:
            continue
        marker = f"[[claim:{reference.claim_id}]]"
        position = anchored.find(marker)
        raw_before = text_after_last_break(anchored, position)
        raw_after = text_before_next_break(anchored, position + len(marker))
        visible_before = _MARKER.sub("", raw_before)
        visible_after = _MARKER.sub("", raw_after)
        statement = _claim_centered_text(visible_before, visible_after)
        selector = str(selected.get("selector") or "")
        reference_window = _reference_local_window(
            raw_before,
            raw_after,
            comparison=selector in {"change", "changeRate"}
            or selector.startswith(("periodChanges.", "periodChangeRates.", "cumulativeChanges.")),
        )
        if reference_window is None:
            # 与 ClaimStatusChecker 相同，以当前引用为中心取可见正文；不能从长句左端截 200 字，
            # 否则会拿远离当前数值的背景期间推荐替代事实。
            reference_window = visible_before[-200:] + visible_after[:200]
        for warning in detail["warnings"]:
            if warning.startswith(_PERIOD_TEXT_MISMATCH):
                warning += _period_mismatch_hint(
                    reference,
                    selected,
                    reference_window,
                    resolver,
                    number_catalog,
                    alternative_index,
                )
            warnings.append(f"{STATEMENT_REVIEW_PREFIX}{warning} 所在语句：{statement}")
    return list(dict.fromkeys(warnings))


def _claim_centered_text(before: str, after: str, *, limit: int = 200) -> str:
    """展示当前引用附近的语句，短句保持原样，长句始终保留紧邻引用的两侧正文。"""
    if len(before) + len(after) <= limit:
        return before + after
    right = after[: min(len(after), limit // 2)]
    left = before[-(limit - len(right)):]
    if len(left) + len(right) < limit:
        right = after[: limit - len(left)]
    return left + right


def _metric_alternative_semantics(entry: Mapping[str, Any]) -> str | None:
    """跨期间可替换的基础指标语义；比较/派生事实宁可不推荐，也不按字段名猜测。"""
    if (
        not isinstance(entry.get("fieldRef"), str)
        or not isinstance(entry.get("aggregation"), str)
        or entry.get("comparisonType") is not None
        or entry.get("inputFactIds")
        or entry.get("kind") is not None
        or entry.get("code") is not None
    ):
        return None
    identity = {
        "field": entry.get("field"),
        "fieldRef": entry.get("fieldRef"),
        "aggregation": entry.get("aggregation"),
        "unit": entry.get("unit"),
        "scope": entry.get("scope") or {},
        "formula": entry.get("formula"),
        "metricCodes": entry.get("metricCodes") or [],
        "periodGranularity": entry.get("periodGranularity"),
        "periodAggregation": entry.get("periodAggregation"),
        "periodField": entry.get("periodField"),
        "cumulativePolicy": entry.get("cumulativePolicy"),
    }
    return json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _metric_alternative_index(resolver: NumberReferenceResolver) -> dict[str, tuple[tuple[str, Any], ...]]:
    grouped: dict[str, list[tuple[str, Any]]] = {}
    for fact_id, entry in resolver.entries.items():
        if (
            not isinstance(fact_id, str)
            or not re.fullmatch(r"fact-[0-9a-f]{16}", fact_id)
            or fact_id in resolver.conflicts
            or (semantics := _metric_alternative_semantics(entry)) is None
        ):
            continue
        grouped.setdefault(semantics, []).append((fact_id, entry))
    return {
        semantics: tuple(sorted(entries, key=lambda item: item[0]))
        for semantics, entries in grouped.items()
    }


def _resolved_period_keys(resolved: Mapping[str, Any]) -> tuple[tuple[int, ...], ...] | None:
    keys = tuple(
        key
        for period in resolved.get("periods") or ()
        if (key := _period_key(str(period))) is not None
    )
    if not keys or len(keys) != len(resolved.get("periods") or ()) or len({len(key) for key in keys}) != 1:
        return None
    return tuple(sorted(dict.fromkeys(keys)))


def _period_mismatch_hint(
    reference,
    selected,
    statement,
    resolver,
    number_catalog: Mapping[str, str],
    alternative_index: Mapping[str, tuple[tuple[str, Any], ...]],
) -> str:
    """期间写错时指明是哪个数，并给出同一指标在句中所写期间的登记引用，由模型决定是否改用。

    只在唯一可确定时给候选：同一基础指标的完整业务语义、同一选择器，登记期间的完整桶集合与
    当前引用附近唯一连续期间一致。比较/派生事实、多个期间窗口、稀疏期间或多身份候选均不猜测。
    """
    hint = f"：“{reference.display_text}”的登记期间与句中所写不同。" if reference.display_text else ""
    written_keys = written_period_keys(statement)
    match = re.fullmatch(r"\{\{value:(fact-[0-9a-f]{16}):([^:{}]+):([^{}]*)\}\}", reference.token)
    if written_keys is None or match is None:
        return hint
    fact_id, selector, unit = match.groups()
    entry = selected["entry"]
    semantics = _metric_alternative_semantics(entry)
    if semantics is None:
        return hint
    candidates: dict[str, Any] = {}
    for other_id, _other in alternative_index.get(semantics, ()):
        if other_id == fact_id:
            continue
        token = f"{{{{value:{other_id}:{selector}:{unit}}}}}"
        resolved = resolver.resolve(token)
        if resolved is not None and _resolved_period_keys(resolved) == written_keys:
            candidates[token] = resolved
    if len(candidates) != 1:
        return hint
    token, resolved = next(iter(candidates.items()))
    shown = number_catalog.get(token)
    return (hint + f"若要写{period_list_text(resolved['periods'])}，同一指标该期间已登记为 {token}"
            + (f"（{shown}）" if shown else "") + "。")


__all__ = ["STATEMENT_REVIEW_PREFIX", "statement_review_warnings"]
