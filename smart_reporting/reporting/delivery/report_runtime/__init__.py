"""Reporting 交付运行时的稳定入口。"""

from .cli import main
from .docx import _WORD_PAGE_FIELDS, _postprocess_docx
from .markdown import (
    _document_context,
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

__all__ = [
    "DEFAULT_PAGE_LAYOUT",
    "REPORT_VISUAL_THEME",
    "ReportFailure",
    "ReportRuntime",
    "_WORD_PAGE_FIELDS",
    "_document_context",
    "_normalize_cjk_strong_markers",
    "_pdf_markdown",
    "_postprocess_docx",
    "_semantic_documents",
    "main",
    "normalize_report_markdown_strong_spacing",
]
