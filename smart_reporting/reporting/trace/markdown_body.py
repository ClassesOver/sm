"""保留正文位置，屏蔽不参与来源绑定的 Markdown 代码和注释。"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from sys import getsizeof
from threading import RLock

from markdown_it import MarkdownIt
from markdown_it.rules_inline.backticks import backtick

MAX_TRACE_BODY_CACHE_BYTES = 4 * 1024 * 1024
MAX_TRACE_BODY_CACHE_ENTRIES = 16


@dataclass
class _TraceBodyCache:
    entries: dict[tuple[str, bool], str] = field(default_factory=dict)
    size: int = 0
    lock: RLock = field(default_factory=RLock)


_TRACE_BODY_CACHE: ContextVar[_TraceBodyCache | None] = ContextVar("trace_body_cache", default=None)


@asynccontextmanager
async def trace_body_cache_scope() -> AsyncIterator[None]:
    """仅在一次来源校验内复用不可变结果，AnyIO 工作线程沿用本次上下文。"""
    token = _TRACE_BODY_CACHE.set(_TraceBodyCache())
    try:
        yield
    finally:
        _TRACE_BODY_CACHE.reset(token)


def trace_body(markdown: str, *, mask_inline_code: bool = True) -> str:
    cache = _TRACE_BODY_CACHE.get()
    if cache is None:
        return _parse_trace_body(markdown, mask_inline_code=mask_inline_code)
    key = (markdown, mask_inline_code)
    # 同一请求的工作线程可能重叠；锁也确保相同正文不会同时重新解析。
    with cache.lock:
        if key in cache.entries:
            return cache.entries[key]
        result = _parse_trace_body(markdown, mask_inline_code=mask_inline_code)
        size = getsizeof(markdown) + getsizeof(result) + getsizeof(key)
        if (len(cache.entries) < MAX_TRACE_BODY_CACHE_ENTRIES
                and cache.size + size <= MAX_TRACE_BODY_CACHE_BYTES):
            cache.entries[key] = result
            cache.size += size
        return result


def _parse_trace_body(markdown: str, *, mask_inline_code: bool = True) -> str:
    parser = MarkdownIt("commonmark")
    tokens = parser.parse(markdown)
    offsets = [0]
    for line in markdown.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    characters = list(markdown)

    def mask(start: int, end: int) -> None:
        for index in range(start, end):
            if characters[index] not in "\r\n":
                characters[index] = " "

    for token in tokens:
        if token.type in {"fence", "code_block"} and token.map:
            mask(offsets[token.map[0]], offsets[token.map[1]])

    code_spans: list[tuple[int, int]] = []

    def mask_backticks(state, silent):
        start, count = state.pos, len(state.tokens)
        matched = backtick(state, silent)
        if not silent and len(state.tokens) > count and state.tokens[-1].type == "code_inline":
            state.env["code_spans"].append((start, state.pos))
        return matched

    parser.inline.ruler.at("backticks", mask_backticks)
    for token in tokens:
        if token.type == "inline" and token.map:
            start, end = offsets[token.map[0]], offsets[token.map[1]]
            environment = {"code_spans": []}
            parser.inline.parse("".join(characters[start:end]), parser, environment, [])
            code_spans.extend((start + left, start + right) for left, right in environment["code_spans"])

    # 行内代码中的 <!-- 是字面量，不能把后面的真实表格吞进注释。
    for start, end in code_spans:
        mask(start, end)
    comment_source = "".join(characters)
    if not mask_inline_code:
        for start, end in code_spans:
            characters[start:end] = markdown[start:end]

    # 未闭合注释按 Markdown 语义延伸到文档末尾；代码中的注释符已被屏蔽。
    for match in re.finditer(r"<!--(?:[\s\S]*?-->|[\s\S]*\Z)", comment_source):
        mask(match.start(), match.end())
    return "".join(characters)
