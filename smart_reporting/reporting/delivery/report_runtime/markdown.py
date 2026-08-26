"""Reporting Markdown 规范化与语义文档能力。"""

from .runtime import (
    _bind_heading_anchors,
    _body_tokens,
    _document_context,
    _markdown_title,
    _normalize_cjk_strong_markers,
    _normalize_report_markdown_segments,
    _normalize_strong_spacing_line,
    _semantic_documents,
    normalize_report_markdown_strong_spacing,
)

__all__ = [
    "_bind_heading_anchors",
    "_body_tokens",
    "_document_context",
    "_markdown_title",
    "_normalize_cjk_strong_markers",
    "_normalize_report_markdown_segments",
    "_normalize_strong_spacing_line",
    "_semantic_documents",
    "normalize_report_markdown_strong_spacing",
]
