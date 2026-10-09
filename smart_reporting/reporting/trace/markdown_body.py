"""保留正文位置，屏蔽不参与来源绑定的 Markdown 代码和注释。"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.rules_inline.backticks import backtick


def trace_body(markdown: str, *, mask_inline_code: bool = True) -> str:
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
