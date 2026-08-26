"""Reporting DOCX 渲染、后处理和结构验收能力。"""

from .runtime import (
    _WORD_PAGE_FIELDS,
    _postprocess_docx,
    _render_docx,
    _validate_docx_rendering,
    _validate_docx_structure,
)

__all__ = [
    "_WORD_PAGE_FIELDS",
    "_postprocess_docx",
    "_render_docx",
    "_validate_docx_rendering",
    "_validate_docx_structure",
]
