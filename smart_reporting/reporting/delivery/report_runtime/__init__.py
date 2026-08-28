"""Reporting 交付运行时的稳定入口。"""

from typing import Any

from .docx import _WORD_PAGE_FIELDS, _postprocess_docx
from .markdown import (
    _document_context,
    _html_document,
    _normalize_cjk_strong_markers,
    _semantic_documents,
    normalize_report_markdown_strong_spacing,
)
from .pdf import (
    DEFAULT_PAGE_LAYOUT,
    REPORT_VISUAL_THEME,
    _pdf_markdown,
)
from .runtime import ReportRuntime
from .validation import ReportFailure


def __getattr__(name: str) -> Any:
    if name == "main":
        from .cli import main

        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DEFAULT_PAGE_LAYOUT",
    "REPORT_VISUAL_THEME",
    "ReportFailure",
    "ReportRuntime",
    "_WORD_PAGE_FIELDS",
    "_document_context",
    "_html_document",
    "_normalize_cjk_strong_markers",
    "_pdf_markdown",
    "_postprocess_docx",
    "_semantic_documents",
    "main",
    "normalize_report_markdown_strong_spacing",
]
