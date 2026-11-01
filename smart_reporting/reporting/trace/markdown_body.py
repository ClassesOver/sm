"""保留正文位置，屏蔽不参与来源绑定的 Markdown 代码和注释。"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Iterable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from sys import getsizeof
from threading import RLock
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.rules_inline.backticks import backtick

MAX_TRACE_BODY_CACHE_BYTES = 4 * 1024 * 1024
MAX_TRACE_BODY_CACHE_ENTRIES = 16

# 来源复核共用的服务端表格协议块及其“候选表名”行，不参与导出布局或搬移。
# 候选表名只是结构位置（自成一段、紧邻表格、非标题/列表/句末）；它可能是正文引导句，
# 是否作为表名剔除由 strip_server_tables 按登记身份判定，不能直接用本正则整段删除。
SERVER_TABLE_BLOCK = re.compile(
    r"(?:(?:\A|(?<=\n\n))(?![\[|#!>])(?![-*+][ \t]|\d{1,3}[.)][ \t])(?![^\n]*\[\[)"
    r"(?P<caption>[^\n]*[^\n。！？；.!?])\n\n)?^\[\[table:(?P<id>[^\]\r\n]+)\]\]\n.*?"
    r"^\[\[/table:(?P=id)\]\][ \t]*(?:\n|\Z)",
    re.MULTILINE | re.DOTALL,
)
_TABLE_OPEN_AFTER_CAPTION = re.compile(r"\n\n\[\[table:(?P<id>[^\]\r\n]+)\]\]\n")


def registered_table_captions(tables: Iterable[Mapping[str, Any]] | None) -> dict[str, str]:
    """从表格追溯冻结的 originMarkdown 读取服务端表名：tableId → 表名。

    表名身份来自服务端渲染时的协议块，而非表名措辞或标点。
    """
    captions: dict[str, str] = {}
    for table in tables or ():
        if not isinstance(table, Mapping):
            continue
        origin, table_id = table.get("originMarkdown"), table.get("tableId")
        if not isinstance(origin, str) or not isinstance(table_id, str):
            continue
        opening = _TABLE_OPEN_AFTER_CAPTION.search(origin)
        if opening is not None and opening["id"] == table_id and "\n" not in origin[: opening.start()]:
            captions[table_id] = origin[: opening.start()].strip()
    return captions


def strip_server_tables(
    markdown: str,
    *,
    registered_captions: Mapping[str, str] | None = None,
    keep: Callable[[re.Match[str]], bool] | None = None,
) -> str:
    """剔除服务端表格协议块；候选表名只在能确认不是正文时随表剔除。

    - 与该表登记的服务端表名逐字一致：随表剔除；
    - 没有登记身份（旧报告、无追溯索引）：仅当候选行不含数字时剔除，含数字的引导句
      保留在正文中继续核对，避免“收入合计12.3亿元，明细如下：”中的数字逃过校验；
    - keep 返回 True 的协议块整体保留（如语义复核中包含当前数值引用的表）。
    """

    def replace(match: re.Match[str]) -> str:
        if keep is not None and keep(match):
            return match[0]
        caption = match["caption"]
        if caption is None:
            return ""
        registered = (registered_captions or {}).get(match["id"])
        is_caption = caption.strip() == registered if registered is not None else not re.search(r"\d", caption)
        return "" if is_caption else caption + "\n\n"

    return SERVER_TABLE_BLOCK.sub(replace, markdown)


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


@contextmanager
def trace_body_cache_scope_sync() -> Iterator[None]:
    """同步评估入口的同等作用域；已有外层作用域时直接复用。"""
    if _TRACE_BODY_CACHE.get() is not None:
        yield
        return
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
