"""Reporting PDF 渲染、页码和视觉验收能力。"""

from .runtime import (
    DEFAULT_PAGE_LAYOUT,
    MAX_PDF_BYTES,
    MAX_PDF_PAGES,
    REPORT_VISUAL_THEME,
    _apply_pdf_page_decorations,
    _page_number_context,
    _pdf_heading_pages,
    _pdf_link_count,
    _pdf_markdown,
    _pdf_section_pages,
    _toc_page_numbers,
)

__all__ = [
    "DEFAULT_PAGE_LAYOUT",
    "MAX_PDF_BYTES",
    "MAX_PDF_PAGES",
    "REPORT_VISUAL_THEME",
    "_apply_pdf_page_decorations",
    "_pdf_heading_pages",
    "_pdf_link_count",
    "_pdf_markdown",
    "_pdf_section_pages",
    "_page_number_context",
    "_toc_page_numbers",
]
