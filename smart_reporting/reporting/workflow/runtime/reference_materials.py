from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from agno.workflow.types import StepInput, StepOutput
from loguru import logger

REPORT_REFERENCE_MATERIALS_STATE_KEY = "report_reference_materials"
REPORT_REFERENCE_ISSUES_STATE_KEY = "report_reference_issues"

_SUPPORTED = {".docx", ".pdf", ".pptx"}
_MAX_REFERENCE_FILES = 4
_MAX_REFERENCE_FILE_BYTES = 50 * 1024 * 1024
_MAX_REFERENCE_TOTAL_BYTES = 200 * 1024 * 1024


def _raw_file(file: Any) -> bytes:
    content = getattr(file, "content", None)
    if isinstance(content, bytes):
        return content
    filepath = getattr(file, "filepath", None)
    if filepath:
        return Path(filepath).read_bytes()
    raise ValueError("附件没有可读取的内容")


def _docx(raw: bytes) -> tuple[str, dict[str, Any]]:
    from docx import Document

    document = Document(io.BytesIO(raw))
    paragraphs = [item.text.strip() for item in document.paragraphs if item.text.strip()]
    tables = [
        [[cell.text.strip() for cell in row.cells] for row in table.rows]
        for table in document.tables
    ]
    content = "\n".join(paragraphs)
    sections = [{"width": section.page_width, "height": section.page_height,
                 "aspectRatio": round(section.page_width / section.page_height, 3)}
                for section in document.sections]
    return content, {"type": "document", "paragraphCount": len(paragraphs), "tableCount": len(tables),
                     "tables": tables[:10], "sections": sections}


def _pdf(raw: bytes) -> tuple[str, dict[str, Any]]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    page_layout = []
    for page in reader.pages:
        box = page.mediabox
        width, height = float(box.width), float(box.height)
        page_layout.append({"width": width, "height": height,
                            "aspectRatio": round(width / height, 3) if height else None})
    return "\n\n".join(item for item in pages if item), {
        "type": "document", "pageCount": len(reader.pages), "pages": [len(item) for item in pages],
        "pageLayout": page_layout,
    }


def _pptx(raw: bytes) -> tuple[str, dict[str, Any]]:
    from pptx import Presentation

    presentation = Presentation(io.BytesIO(raw))
    slides: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for index, slide in enumerate(presentation.slides, start=1):
        texts = [shape.text.strip() for shape in slide.shapes if hasattr(shape, "text") and shape.text.strip()]
        text_parts.extend(texts)
        shape_count = len(slide.shapes)
        slides.append({"number": index, "textCount": len(texts), "textBlocks": len(texts),
                       "shapeCount": shape_count, "texts": texts[:20],
                       "aspectRatio": round(presentation.slide_width / presentation.slide_height, 3)})
    return "\n\n".join(text_parts), {
        "type": "presentation", "slideCount": len(slides),
        "size": {"width": presentation.slide_width, "height": presentation.slide_height},
        "slides": slides,
    }


def _parse(file: Any) -> dict[str, Any]:
    filename = str(getattr(file, "filename", "") or "reference")
    suffix = Path(filename).suffix.lower()
    if suffix not in _SUPPORTED:
        raise ValueError(f"不支持的参考附件格式：{suffix or 'unknown'}")
    raw = _raw_file(file)
    parser = {".docx": _docx, ".pdf": _pdf, ".pptx": _pptx}[suffix]
    content, layout = parser(raw)
    return {"filename": filename, "content": content[:100_000], "layout": layout}


async def prepare_reference_materials(step_input: StepInput, run_context: Any) -> StepOutput:
    references: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    files = list(step_input.files or [])
    if len(files) > _MAX_REFERENCE_FILES:
        issues.append({"filename": "", "code": "report_reference_limit_exceeded",
                       "message": f"参考附件最多支持 {_MAX_REFERENCE_FILES} 个。"})
    total_bytes = 0
    for index, file in enumerate(files):
        if index >= _MAX_REFERENCE_FILES:
            break
        filename = str(getattr(file, "filename", "") or "reference")
        try:
            size = getattr(file, "size", None)
            if not isinstance(size, int):
                size = len(getattr(file, "content", b"")) if isinstance(getattr(file, "content", None), bytes) else 0
            total_bytes += size
            if size > _MAX_REFERENCE_FILE_BYTES or total_bytes > _MAX_REFERENCE_TOTAL_BYTES:
                raise ValueError("参考附件超过大小限制（单个 50 MiB、总计 200 MiB）")
            references.append(_parse(file))
        except Exception as error:  # noqa: BLE001 - reference parsing is non-blocking
            logger.warning("report_reference_parse_failed filename={} error_type={}", filename, type(error).__name__)
            issues.append({"filename": filename, "code": "report_reference_parse_failed", "message": str(error)[:500]})
    state = run_context.session_state if isinstance(run_context.session_state, dict) else {}
    run_context.session_state = state
    state[REPORT_REFERENCE_MATERIALS_STATE_KEY] = references
    state[REPORT_REFERENCE_ISSUES_STATE_KEY] = issues
    return StepOutput(content={"references": references, "issues": issues})


__all__ = ["REPORT_REFERENCE_MATERIALS_STATE_KEY", "REPORT_REFERENCE_ISSUES_STATE_KEY", "prepare_reference_materials"]
