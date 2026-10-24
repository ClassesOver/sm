"""写作时的引用句核对：与发布后编辑器的语句核对走同一路径。

编辑器在发布后按质量包逐个核对数值引用所在语句的期间、期间角色与业务范围（statementReview）；
写作时只做数值与口径核对，模型看不到这些提醒，正确与否要等发布后才暴露。这里按最终渲染锚定
后，用质量包相同的检查函数与参数逐个核对，让写作时的纠错轮次看到与编辑器一致的提醒。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from .assertions import assertion_request_for_token
from .numeric_text import text_after_last_break, text_before_next_break
from .semantic_bindings import NumberReferenceResolver, anchor_bound_numbers, render_bound_numbers
from .subject_builder import prepare_claim_status

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
        # 与质量包一致：核对已登记运算语义的数值引用与能重算的计算引用，补证表推导等不做语句核对。
        if reference.table_derivation is not None or (
            not reference.token.startswith("{{calc:")
            and assertion_request_for_token(reference.token, resolver) is None
        ):
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
        warnings.extend(f"{STATEMENT_REVIEW_PREFIX}{warning} 所在语句：{statement}" for warning in detail["warnings"])
    return list(dict.fromkeys(warnings))


__all__ = ["STATEMENT_REVIEW_PREFIX", "statement_review_warnings"]
