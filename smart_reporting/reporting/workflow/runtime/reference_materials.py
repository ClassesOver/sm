from __future__ import annotations

import asyncio
import io
import shutil
import subprocess
import tempfile
from collections.abc import Awaitable, Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from agno.workflow.types import StepInput, StepOutput
from loguru import logger

from ...delivery.office_engine import run_office_engine

REPORT_REFERENCE_MATERIALS_STATE_KEY = "report_reference_materials"
REPORT_REFERENCE_ISSUES_STATE_KEY = "report_reference_issues"

_SUPPORTED = {".docx", ".pdf", ".pptx", ".xlsx", ".xls"}
_MAX_REFERENCE_FILES = 4
_MAX_REFERENCE_FILE_BYTES = 50 * 1024 * 1024
_MAX_REFERENCE_TOTAL_BYTES = 200 * 1024 * 1024
_MAX_VISUAL_PAGES = 3
_MAX_SPREADSHEET_ROWS = 10_000
_MAX_SPREADSHEET_COLUMNS = 256
_MAX_SPREADSHEET_CELLS = 100_000
_MAX_SPREADSHEET_CONTENT_CHARS = 100_000
VisualAnalyzer = Callable[[dict[str, Any], list[bytes]], Awaitable[dict[str, Any]]]


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


def _spreadsheet(
    sheets: Sequence[tuple[str, int, int, Iterable[Iterable[Any]]]],
) -> tuple[str, dict[str, Any]]:
    content_parts: list[str] = []
    summaries: list[dict[str, Any]] = []
    content_chars = 0
    parsed_cells = 0
    truncated = False
    for name, row_count, column_count, rows in sheets:
        parsed_rows = 0
        sheet_truncated = row_count > _MAX_SPREADSHEET_ROWS or column_count > _MAX_SPREADSHEET_COLUMNS
        if parsed_cells >= _MAX_SPREADSHEET_CELLS or content_chars >= _MAX_SPREADSHEET_CONTENT_CHARS:
            summaries.append({
                "name": name,
                "rowCount": row_count,
                "columnCount": column_count,
                "parsedRows": parsed_rows,
                "truncated": True,
            })
            truncated = True
            continue
        if name and content_chars < _MAX_SPREADSHEET_CONTENT_CHARS:
            heading = f"工作表：{name}\n"
            remaining = _MAX_SPREADSHEET_CONTENT_CHARS - content_chars
            content_parts.append(heading[:remaining])
            content_chars += min(len(heading), remaining)
        for row_index, row in enumerate(rows):
            if row_index >= _MAX_SPREADSHEET_ROWS or parsed_cells >= _MAX_SPREADSHEET_CELLS:
                sheet_truncated = True
                break
            values = list(row)[:_MAX_SPREADSHEET_COLUMNS]
            parsed_cells += len(values)
            parsed_rows += 1
            cells = ["" if value is None else str(value) for value in values]
            while cells and not cells[-1]:
                cells.pop()
            if not cells:
                continue
            line = "\t".join(cells) + "\n"
            remaining = _MAX_SPREADSHEET_CONTENT_CHARS - content_chars
            if remaining <= 0:
                sheet_truncated = True
                break
            content_parts.append(line[:remaining])
            content_chars += min(len(line), remaining)
            if len(line) > remaining:
                sheet_truncated = True
                break
        if parsed_rows < row_count or column_count > _MAX_SPREADSHEET_COLUMNS:
            sheet_truncated = True
        truncated = truncated or sheet_truncated
        summaries.append({
            "name": name,
            "rowCount": row_count,
            "columnCount": column_count,
            "parsedRows": parsed_rows,
            "truncated": sheet_truncated,
        })
        if parsed_cells >= _MAX_SPREADSHEET_CELLS or content_chars >= _MAX_SPREADSHEET_CONTENT_CHARS:
            truncated = True
    return "".join(content_parts), {
        "type": "spreadsheet",
        "sheetCount": len(summaries),
        "sheets": summaries,
        "truncated": truncated,
    }


def _xlsx(raw: bytes) -> tuple[str, dict[str, Any]]:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=False)
    try:
        sheets = []
        for worksheet in workbook.worksheets:
            row_count = worksheet.max_row or 0
            column_count = worksheet.max_column or 0
            rows = worksheet.iter_rows(
                max_row=min(row_count, _MAX_SPREADSHEET_ROWS),
                max_col=min(column_count, _MAX_SPREADSHEET_COLUMNS),
                values_only=True,
            )
            sheets.append((worksheet.title, row_count, column_count, rows))
        return _spreadsheet(sheets)
    finally:
        workbook.close()


def _xls(raw: bytes) -> tuple[str, dict[str, Any]]:
    import xlrd

    workbook = xlrd.open_workbook(file_contents=raw, on_demand=True)
    try:
        sheets = []
        for name in workbook.sheet_names():
            worksheet = workbook.sheet_by_name(name)

            def rows(sheet=worksheet):
                for row_index in range(min(sheet.nrows, _MAX_SPREADSHEET_ROWS)):
                    values = []
                    for column_index in range(min(sheet.ncols, _MAX_SPREADSHEET_COLUMNS)):
                        cell = sheet.cell(row_index, column_index)
                        value = (
                            xlrd.xldate_as_datetime(cell.value, workbook.datemode).isoformat(sep=" ")
                            if cell.ctype == xlrd.XL_CELL_DATE
                            else cell.value
                        )
                        values.append(value)
                    yield values

            sheets.append((name, worksheet.nrows, worksheet.ncols, rows()))
        return _spreadsheet(sheets)
    finally:
        workbook.release_resources()


def _parse(file: Any) -> dict[str, Any]:
    filename = str(getattr(file, "filename", "") or "reference")
    suffix = Path(filename).suffix.lower()
    if suffix not in _SUPPORTED:
        raise ValueError(f"不支持的参考附件格式：{suffix or 'unknown'}")
    raw = _raw_file(file)
    parser = {".docx": _docx, ".pdf": _pdf, ".pptx": _pptx, ".xlsx": _xlsx, ".xls": _xls}[suffix]
    content, layout = parser(raw)
    return {
        "filename": filename,
        "content": content[:100_000],
        "layout": layout,
    }


def _render_visual_pages(filename: str, raw: bytes) -> list[bytes]:
    """将参考文档前几页转换为模型可识别的 PNG 页面。"""
    suffix = Path(filename).suffix.lower()
    pdf_bytes = raw
    if suffix != ".pdf":
        converter = shutil.which("libreoffice") or shutil.which("soffice")
        if converter is None:
            raise RuntimeError("未安装 Office 页面渲染器")
        with tempfile.TemporaryDirectory(prefix="report-reference-") as temporary:
            root = Path(temporary)
            source = root / f"reference{suffix}"
            source.write_bytes(raw)
            profile = root / ".libreoffice-profile"
            profile.mkdir()
            result = subprocess.run(
                [
                    converter,
                    "--headless",
                    f"-env:UserInstallation=file://{profile}",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(root),
                    str(source),
                ],
                capture_output=True,
                timeout=45,
                check=False,
            )
            rendered = root / "reference.pdf"
            if result.returncode != 0 or not rendered.is_file():
                raise RuntimeError("Office 页面转换失败")
            pdf_bytes = rendered.read_bytes()
    import fitz

    pages: list[bytes] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        for index in range(min(document.page_count, _MAX_VISUAL_PAGES)):
            page = document[index]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25), alpha=False)
            pages.append(pixmap.tobytes("png"))
    return pages


async def prepare_reference_materials(
    step_input: StepInput,
    run_context: Any,
    *,
    visual_analyzer: VisualAnalyzer | None = None,
) -> StepOutput:
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
            # 解析与页面渲染都是同步 CPU/子进程操作，不能占用事件循环。
            reference = await asyncio.to_thread(_parse, file)
            if visual_analyzer is not None:
                try:
                    raw = await asyncio.to_thread(_raw_file, file)
                    visual_pages = await run_office_engine(_render_visual_pages, filename, raw)
                    reference["visualLayout"] = await visual_analyzer(reference, visual_pages)
                except Exception as error:  # noqa: BLE001 - visual layout is supplemental
                    logger.warning(
                        "report_reference_visual_layout_failed filename={} error_type={}",
                        filename,
                        type(error).__name__,
                    )
                    issues.append({
                        "filename": filename,
                        "code": "report_reference_visual_layout_failed",
                        "message": str(error)[:500],
                    })
            references.append(reference)
        except Exception as error:  # noqa: BLE001 - reference parsing is non-blocking
            logger.warning("report_reference_parse_failed filename={} error_type={}", filename, type(error).__name__)
            issues.append({"filename": filename, "code": "report_reference_parse_failed", "message": str(error)[:500]})
    state = run_context.session_state if isinstance(run_context.session_state, dict) else {}
    run_context.session_state = state
    state[REPORT_REFERENCE_MATERIALS_STATE_KEY] = references
    state[REPORT_REFERENCE_ISSUES_STATE_KEY] = issues
    return StepOutput(content={"references": references, "issues": issues})


__all__ = ["REPORT_REFERENCE_MATERIALS_STATE_KEY", "REPORT_REFERENCE_ISSUES_STATE_KEY", "prepare_reference_materials"]
