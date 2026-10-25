"""写作时的引用句核对：与发布后编辑器的语句核对走同一路径。

编辑器在发布后按质量包逐个核对数值引用所在语句的期间、期间角色与业务范围（statementReview）；
写作时只做数值与口径核对，模型看不到这些提醒，正确与否要等发布后才暴露。这里按最终渲染锚定
后，用质量包相同的检查函数与参数逐个核对，让写作时的纠错轮次看到与编辑器一致的提醒。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from .comparison_proofs import period_list_text
from .numeric_text import frozen_number_catalog, text_after_last_break, text_before_next_break
from .semantic_bindings import NumberReferenceResolver, anchor_bound_numbers, render_bound_numbers
from .subject_builder import (
    _PERIOD_TEXT_MISMATCH,
    _period_key,
    prepare_claim_status,
    written_period_span,
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
        position = anchored.find(f"[[claim:{reference.claim_id}]]")
        before = _MARKER.sub("", anchored[:position])
        text = before + _MARKER.sub("", anchored[position:])
        statement = (text_after_last_break(text, len(before)) + text_before_next_break(text, len(before)))[:200]
        for warning in detail["warnings"]:
            if warning.startswith(_PERIOD_TEXT_MISMATCH):
                warning += _period_mismatch_hint(reference, selected, statement, resolver, contents)
            warnings.append(f"{STATEMENT_REVIEW_PREFIX}{warning} 所在语句：{statement}")
    return list(dict.fromkeys(warnings))


def _period_mismatch_hint(reference, selected, statement, resolver, contents) -> str:
    """期间写错时指明是哪个数，并给出同一指标在句中所写期间的登记引用，由模型决定是否改用。

    只在唯一可确定时给候选：同一字段、同一范围与聚合、同一单位，登记期间的首末与句中所写一致，
    且所有候选取值相同；句中写了多个期间或找不到时只指明数值，不猜测。
    """
    hint = f"：“{reference.display_text}”的登记期间与句中所写不同。" if reference.display_text else ""
    span = written_period_span(statement)
    match = re.fullmatch(r"\{\{value:(fact-[0-9a-f]{16}):([^:{}]+):([^{}]*)\}\}", reference.token)
    if span is None or match is None:
        return hint
    fact_id, selector, unit = match.groups()
    entry = selected["entry"]
    candidates: dict[str, Any] = {}
    for other_id, other in resolver.entries.items():
        if (other_id == fact_id or other_id in resolver.conflicts
                or other.get("fieldRef") != entry.get("fieldRef")
                or (other.get("scope") or {}) != (entry.get("scope") or {})
                or other.get("aggregation") != entry.get("aggregation")
                or other.get("unit") != entry.get("unit")):
            continue
        token = f"{{{{value:{other_id}:{selector}:{unit}}}}}"
        resolved = resolver.resolve(token)
        keys = sorted(key for period in (resolved or {}).get("periods") or () if (key := _period_key(str(period))))
        if keys and len({len(key) for key in keys}) == 1 and (keys[0], keys[-1]) == span:
            candidates[token] = resolved
    if not candidates or len({str(item["value"]) for item in candidates.values()}) != 1:
        return hint
    token, resolved = next(iter(candidates.items()))
    shown = frozen_number_catalog(contents).get(token)
    return (hint + f"若要写{period_list_text(resolved['periods'])}，同一指标该期间已登记为 {token}"
            + (f"（{shown}）" if shown else "") + "。")


__all__ = ["STATEMENT_REVIEW_PREFIX", "statement_review_warnings"]
