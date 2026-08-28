"""受限 Markdown 报表运行时；由 Reporting Workflow 在 Daytona 中执行。"""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

from .docx import _render_docx, _validate_docx_rendering, _validate_docx_structure
from .markdown import (
    REPORT_VISUAL_THEME,
    _bind_heading_anchors,
    _body_tokens,
    _document_context,
    _html_document,
    _markdown_title,
    _normalize_cjk_strong_markers,
    _semantic_documents,
)
from .pdf import (
    MAX_PDF_PAGES,
    _apply_pdf_page_decorations,
    _formatted_page_text,
    _has_page_layout,
    _page_layout,
    _page_number_context,
    _pdf_heading_pages,
    _pdf_link_count,
    _pdf_markdown,
    _pdf_section_pages,
    _toc_page_numbers,
)
from .validation import (
    IMAGE_SUFFIXES,
    MAX_DOCX_BYTES,
    MAX_HTML_BYTES,
    MAX_IMAGE_BYTES,
    MAX_MARKDOWN_BYTES,
    MAX_PDF_BYTES,
    MAX_TOTAL_IMAGE_BYTES,
    ReportFailure,
    _check_image_signature,
    _cleanup_directory,
    _html_output_path,
    _input_path,
    _output_path,
    _reject_symlinks,
    _relative_path,
    _sha256,
    _temporary_docx_path,
    _temporary_html_path,
    _temporary_pdf_path,
    _validation_directory,
    _word_output_path,
)

MAX_DATASET_PATHS = 20
PDF_VALIDATION_TIMEOUT_SECONDS = 540
_SECTION_MARKER = re.compile(r"\[\[section:([^\]\r\n]+)\]\]")


class ReportRuntime:
    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).resolve()

    def _validate_datasets(self, state: dict[str, Any]) -> None:
        sources = state.get("sources")
        if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_DATASET_PATHS:
            raise ReportFailure("分析任务缺少源文件校验信息")
        for source in sources:
            if not isinstance(source, dict):
                raise ReportFailure("分析任务缺少源文件校验信息")
            value = source.get("path")
            if not isinstance(value, str):
                raise ReportFailure("分析任务缺少源文件校验信息")
            relative = _relative_path(value)
            path = self.workspace.joinpath(*relative.parts)
            _reject_symlinks(self.workspace, path)
            if (
                not path.is_file()
                or path.stat().st_size != source.get("size")
                or _sha256(path) != source.get("sha256")
            ):
                raise ReportFailure("源文件发生变化，分析任务已失效")

    def _artifact(self, path: Path) -> dict[str, Any]:
        _reject_symlinks(self.workspace, path)
        if not path.is_file():
            raise ReportFailure("报表产物不存在或不是普通文件")
        return {
            "path": str(path.relative_to(self.workspace)),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }

    def _images(self, markdown_path: Path, tokens: list[Any]) -> set[Path]:
        images: list[Path] = []
        for token in tokens:
            for child in token.children or []:
                if child.type != "image":
                    continue
                source = child.attrGet("src") or ""
                parsed = urlsplit(source)
                if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                    raise ReportFailure("Markdown 图片只能引用工作区内的相对路径")
                decoded = unquote(parsed.path)
                if not decoded or "\\" in decoded:
                    raise ReportFailure("Markdown 图片路径无效")
                relative = PurePosixPath(decoded)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ReportFailure("Markdown 图片只能引用工作区内的相对路径")
                image = markdown_path.parent.joinpath(*relative.parts)
                _reject_symlinks(self.workspace, image)
                try:
                    image.relative_to(self.workspace)
                except ValueError as error:
                    raise ReportFailure("Markdown 图片路径越界") from error
                if image.suffix.lower() not in IMAGE_SUFFIXES or not image.is_file():
                    raise ReportFailure("Markdown 图片不存在或格式不受支持")
                if image.stat().st_size > MAX_IMAGE_BYTES:
                    raise ReportFailure("单张 Markdown 图片超过 10 MiB")
                _check_image_signature(image)
                images.append(image.resolve())
        unique = set(images)
        if sum(path.stat().st_size for path in unique) > MAX_TOTAL_IMAGE_BYTES:
            raise ReportFailure("Markdown 图片合计超过 50 MiB")
        return unique

    @staticmethod
    def _inline_images(body: str, source_parent: Path, allowed_images: set[Path]) -> str:
        image_pattern = re.compile(r'(<img\b[^>]*\bsrc=)(["\'])([^"\']+)(\2)', re.I)

        def replace(match: re.Match[str]) -> str:
            source = match.group(3)
            parsed = urlsplit(source)
            if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                raise ReportFailure("HTML 图片只能引用已校验的工作区资源")
            path = (source_parent / unquote(parsed.path)).resolve()
            if path not in allowed_images:
                raise ReportFailure("HTML 图片引用了未校验资源")
            mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(
                path.suffix.lower(), f"image/{path.suffix.lower().lstrip('.')}"
            )
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return f"{match.group(1)}{match.group(2)}data:{mime};base64,{encoded}{match.group(4)}"

        return image_pattern.sub(replace, body)

    @staticmethod
    def _reject_html_links(body: str) -> None:
        link_pattern = re.compile(r'<a\b[^>]*\bhref=(?:"([^"]*)"|\'([^\']*)\')', re.I)
        for match in link_pattern.finditer(body):
            href = match.group(1) if match.group(1) is not None else match.group(2)
            if not href.startswith("#") or urlsplit(href).scheme or urlsplit(href).netloc:
                raise ReportFailure("HTML 预览不允许外部或工作区链接")

    def render_markdown(
        self,
        state: dict[str, Any],
        markdown_path: str,
        output_path: str,
        temporary_path: str,
        page_layout: dict[str, str] | None = None,
        word_output_path: str | None = None,
        html_output_path: str | None = None,
    ) -> dict[str, Any]:
        try:
            import pypdf
            from markdown_it import MarkdownIt
            from weasyprint import HTML, URLFetcher
        except ImportError as error:
            raise ReportFailure("PDF 运行时依赖不可用") from error

        self._validate_datasets(state)
        temporary: Path | None = None
        html_output: Path | None = None
        temporary_html: Path | None = None
        succeeded = False
        try:
            source = _input_path(self.workspace, markdown_path, ".md")
            if source.stat().st_size > MAX_MARKDOWN_BYTES:
                raise ReportFailure("Markdown 文件超过 1 MiB")
            try:
                markdown = source.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise ReportFailure("Markdown 文件必须使用 UTF-8 编码") from error

            pdf_markdown, citation_presentations = _pdf_markdown(
                markdown, state.get("_citationPresentations")
            )
            pdf_markdown = _normalize_cjk_strong_markers(pdf_markdown)
            parser = MarkdownIt("commonmark", {"html": False}).enable("table")
            tokens = parser.parse(pdf_markdown)
            layout = _page_layout(page_layout)
            context = _document_context(state.get("_documentContext"))
            title = _markdown_title(tokens)
            if title != context["title"]:
                raise ReportFailure("Markdown 标题与服务端文档展示契约不一致")
            marker_sections = _SECTION_MARKER.findall(markdown)
            expected_section_codes = [item["code"] for item in context["sections"]]
            if marker_sections != expected_section_codes:
                raise ReportFailure("Markdown 正式章节标识与已批准提纲不一致")
            _bind_heading_anchors(tokens, context["headingNumbers"])
            allowed_images = self._images(source, tokens)
            source_artifact = self._artifact(source)
            image_artifacts = [self._artifact(path) for path in sorted(allowed_images)]
            body = parser.renderer.render(_body_tokens(tokens), parser.options, {})
            html_body = self._inline_images(body, source.parent, allowed_images)
            self._reject_html_links(html_body)
            output = _output_path(self.workspace, output_path)
            word_output = _word_output_path(
                self.workspace,
                word_output_path or str(PurePosixPath(output_path).with_suffix(".docx")),
            )
            html_output = _html_output_path(
                self.workspace,
                html_output_path or str(PurePosixPath(output_path).with_suffix(".html")),
            )
            if output.parent != word_output.parent or output.parent != html_output.parent:
                raise ReportFailure("PDF、Word 和 HTML 必须发布到同一 revision 目录")
            temporary = _temporary_pdf_path(temporary_path)
            temporary_docx = _temporary_docx_path(temporary)
            temporary_html = _temporary_html_path(temporary)
            file_fetcher = URLFetcher(allowed_protocols={"file"}, fail_on_errors=True)

            def fetch_resource(url: str) -> dict[str, Any]:
                parsed = urlsplit(url)
                if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
                    raise ReportFailure("PDF 渲染禁止访问外部资源")
                path = Path(unquote(parsed.path)).resolve()
                if path not in allowed_images:
                    raise ReportFailure("PDF 渲染引用了未校验资源")
                return file_fetcher(url)

            pdf_document, word_document = _semantic_documents(
                body,
                context=context,
                layout=layout,
            )
            preflight_document = HTML(
                string=pdf_document,
                base_url=str(source.parent),
                url_fetcher=fetch_resource,
            ).render()
            toc_page_numbers = _toc_page_numbers(
                preflight_document.pages, context["headingNumbers"]
            )
            pdf_document, _ = _semantic_documents(
                body,
                context=context,
                layout=layout,
                toc_page_numbers=toc_page_numbers,
            )
            final_document = HTML(
                string=pdf_document,
                base_url=str(source.parent),
                url_fetcher=fetch_resource,
            ).render()
            if (
                _toc_page_numbers(final_document.pages, context["headingNumbers"])
                != toc_page_numbers
            ):
                # 目录页码使用固定宽度，正常不会改变分页；若字体或渲染器升级导致
                # 锚点漂移，则不能发布目录与正文不一致的产物。
                raise ReportFailure("PDF 目录页码在最终渲染时发生漂移")
            final_document.write_pdf(str(temporary), pdf_variant="pdf/ua-1")
            if temporary.stat().st_size > MAX_PDF_BYTES:
                raise ReportFailure("PDF 文件不能超过 200 MiB")
            base_page_count = len(final_document.pages)
            if not base_page_count:
                raise ReportFailure("PDF 校验失败")
            if base_page_count > MAX_PDF_PAGES:
                raise ReportFailure("PDF 页数不能超过 200 页")
            _apply_pdf_page_decorations(
                temporary,
                context=context,
                layout=layout,
            )
            word_structure = _render_docx(
                word_document,
                source_parent=source.parent,
                output=temporary_docx,
                context=context,
                layout=layout,
            )
            pdf_size = temporary.stat().st_size
            if pdf_size > MAX_PDF_BYTES:
                raise ReportFailure("PDF 文件不能超过 200 MiB")
            reader = pypdf.PdfReader(str(temporary))
            page_count = len(reader.pages)
            if not page_count:
                raise ReportFailure("PDF 校验失败")
            if page_count > MAX_PDF_PAGES:
                raise ReportFailure("PDF 页数不能超过 200 页")
            docx_size = temporary_docx.stat().st_size
            if docx_size > MAX_DOCX_BYTES:
                raise ReportFailure("Word 文件不能超过 200 MiB")
            word_structure = _validate_docx_structure(
                temporary_docx,
                expected_sections=context["sections"],
                expected_headings=context["headingNumbers"],
                expected_image_count=len(allowed_images),
                watermark_text=context["watermarkText"],
            )
            html_document = _html_document(html_body, context=context, layout=layout)
            html_bytes = html_document.encode("utf-8")
            if len(html_bytes) > MAX_HTML_BYTES:
                raise ReportFailure("HTML 文件不能超过 200 MiB")
            temporary_html.write_bytes(html_bytes)
            if self._artifact(source)["sha256"] != source_artifact["sha256"] or any(
                self._artifact(path)["sha256"] != artifact["sha256"]
                for path, artifact in zip(sorted(allowed_images), image_artifacts, strict=True)
            ):
                raise ReportFailure("Markdown 或图片在渲染期间发生变化，请重新生成报表")
            pdf_artifact = {
                "path": str(output.relative_to(self.workspace)),
                "size": pdf_size,
                "sha256": _sha256(temporary),
            }
            word_artifact = {
                "path": str(word_output.relative_to(self.workspace)),
                "size": docx_size,
                "sha256": _sha256(temporary_docx),
            }
            html_artifact = {
                "path": str(html_output.relative_to(self.workspace)),
                "size": len(html_bytes),
                "sha256": _sha256(temporary_html),
            }
            render = {
                "markdown": source_artifact,
                "pdf": pdf_artifact,
                "word": word_artifact,
                "html": html_artifact,
                "images": image_artifacts,
                "pageCount": page_count,
                "imageCount": len(allowed_images),
                "pageLayout": layout,
                "reportTitle": title,
                "documentContext": context,
                "visualTheme": deepcopy(REPORT_VISUAL_THEME),
                "wordStructure": word_structure,
                "citationPresentations": citation_presentations,
                "citationAppendixPresent": False,
            }
            result = {
                "status": "rendered",
                "jobId": state["jobId"],
                "markdownPath": str(source.relative_to(self.workspace)),
                "pdfPath": str(output.relative_to(self.workspace)),
                "wordPath": str(word_output.relative_to(self.workspace)),
                "htmlPath": str(html_output.relative_to(self.workspace)),
                "htmlSize": len(html_bytes),
                "htmlSha256": html_artifact["sha256"],
                "pageCount": page_count,
                "imageCount": len(allowed_images),
                "size": pdf_size,
                "wordSize": docx_size,
                "render": render,
            }
            succeeded = True
            return result
        finally:
            if temporary is not None and not succeeded:
                shutil.rmtree(temporary.parent, ignore_errors=True)

    def validate_pdf(
        self,
        state: dict[str, Any],
        pdf_path: str,
        temporary_directory: str,
        artifact_manifest: dict[str, Any] | None = None,
        word_path: str | None = None,
    ) -> dict[str, Any]:
        try:
            import pypdf
            from PIL import Image
        except ImportError as error:
            raise ReportFailure("PDF 视觉验收依赖不可用") from error
        if not shutil.which("pdftoppm"):
            raise ReportFailure("PDF 视觉验收命令不可用")

        self._validate_datasets(state)
        temp_path: Path | None = None
        try:
            render = state.get("render")
            if not isinstance(render, dict) or render.get("pdf", {}).get("path") != pdf_path:
                raise ReportFailure("PDF 未登记为当前分析任务的渲染产物")
            registered_word = render.get("word")
            current_word_path = word_path or (
                registered_word.get("path") if isinstance(registered_word, dict) else None
            )
            if (
                not isinstance(registered_word, dict)
                or not isinstance(current_word_path, str)
                or registered_word.get("path") != current_word_path
            ):
                raise ReportFailure("Word 未登记为当前分析任务的渲染产物")
            supporting_artifacts = [render["markdown"], *render.get("images", [])]
            for artifact in supporting_artifacts:
                supporting = self.workspace.joinpath(*_relative_path(artifact["path"]).parts)
                if self._artifact(supporting)["sha256"] != artifact["sha256"]:
                    raise ReportFailure("Markdown 或图片产物发生变化，请重新渲染后验收")
            relative = _relative_path(pdf_path, ".pdf")
            path = self.workspace.joinpath(*relative.parts)
            self._check_pdf_bounds(path)
            current = self._artifact(path)
            if current["sha256"] != render["pdf"]["sha256"]:
                raise ReportFailure("PDF 产物发生变化，请重新渲染后验收")
            word_relative = _relative_path(current_word_path, ".docx")
            word = self.workspace.joinpath(*word_relative.parts)
            word_current = self._artifact(word)
            if word_current["sha256"] != registered_word.get("sha256"):
                raise ReportFailure("Word 产物发生变化，请重新渲染后验收")
            pages: list[dict[str, Any]] = []
            blank_pages: list[int] = []
            missing_page_layout: list[int] = []
            rendered_image_count = 0
            temp_path = _validation_directory(temporary_directory)
            with _cleanup_directory(temp_path):
                prefix = temp_path / "page"
                try:
                    process = subprocess.run(
                        [
                            "pdftoppm",
                            "-gray",
                            "-r",
                            "72",
                            "-png",
                            str(path),
                            str(prefix),
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=PDF_VALIDATION_TIMEOUT_SECONDS,
                        check=False,
                    )
                    reader = pypdf.PdfReader(str(path))
                except (OSError, subprocess.TimeoutExpired, pypdf.errors.PdfReadError) as error:
                    raise ReportFailure("PDF 视觉验收无法打开产物") from error
                rendered_pages = sorted(
                    temp_path.glob("page-*.png"),
                    key=lambda item: int(item.stem.rsplit("-", 1)[-1]),
                )
                if process.returncode != 0 or len(rendered_pages) != len(reader.pages):
                    raise ReportFailure("PDF 视觉验收栅格化失败")
                extracted_pages: list[str] = []
                layout = _page_layout(render.get("pageLayout"))
                title = str(render.get("reportTitle") or "智能运营报表")
                context = _document_context(render.get("documentContext"))
                section_pages = _pdf_section_pages(reader, context["sections"])
                _pdf_heading_pages(reader, context["headingNumbers"])
                body_start_page = min(section_pages.values())
                toc_link_count = (
                    _pdf_link_count(
                        reader,
                        start_page=2,
                        end_page=body_start_page - 1,
                    )
                    if body_start_page > 2
                    else 0
                )
                for index, (page, rendered_page) in enumerate(
                    zip(reader.pages, rendered_pages, strict=True), start=1
                ):
                    page_text = page.extract_text() or ""
                    extracted_pages.append(page_text)
                    with Image.open(rendered_page) as image:
                        grayscale = image.convert("L")
                        samples = grayscale.tobytes()
                        width, height = grayscale.size
                    non_white = sum(value < 250 for value in samples)
                    ratio = round(non_white / len(samples), 6) if samples else 0.0
                    image_count = len(page.images)
                    rendered_image_count += image_count
                    if index == 1:
                        role = "cover"
                        page_value: str | int = 1
                        pages_value: str | int = 1
                        layout_present = False
                    else:
                        role = "toc" if index < body_start_page else "body"
                        page_value, pages_value = _page_number_context(
                            index,
                            body_start_page=body_start_page,
                            physical_page_count=len(reader.pages),
                        )
                        layout_present = _has_page_layout(
                            page_text,
                            layout,
                            title=title,
                            organization=context["organizationName"],
                            page=page_value,
                            pages=pages_value,
                        )
                    watermark_present = index > 1 and context["watermarkText"] in page_text
                    substantive_text = "".join(page_text.split())
                    if index > 1:
                        decorations = [
                            context["watermarkText"],
                            *(
                                _formatted_page_text(
                                    value,
                                    title=title,
                                    organization=context["organizationName"],
                                    page=page_value,
                                    pages=pages_value,
                                )
                                for value in layout.values()
                                if value
                            ),
                        ]
                        # 页眉、页脚和水印即使存在，也不能把无正文页面伪装成非空白页。
                        for decoration in decorations:
                            substantive_text = substantive_text.replace(
                                "".join(decoration.split()), "", 1
                            )
                    text_char_count = len(substantive_text)
                    if index > 1 and not layout_present:
                        missing_page_layout.append(index)
                    blank = (
                        text_char_count == 0 and image_count == 0 and (index > 1 or ratio < 0.0005)
                    )
                    if blank:
                        blank_pages.append(index)
                    pages.append(
                        {
                            "page": index,
                            "width": width,
                            "height": height,
                            "nonWhiteRatio": ratio,
                            "textCharCount": text_char_count,
                            "imageCount": image_count,
                            "pageLayoutPresent": layout_present,
                            "pageLayoutExpected": index > 1,
                            "watermarkPresent": watermark_present,
                            "role": role,
                            "blank": blank,
                        }
                    )
                extracted_text = "\n".join(extracted_pages)
                cover_text = extracted_pages[0]
                toc_text = "\n".join(extracted_pages[1 : body_start_page - 1])
                final_text = extracted_pages[-1]
                cover_values = (
                    context["title"],
                    context["periodLabel"],
                    context["organizationName"],
                    context["generatedByLabel"],
                )
                cover_compact = "".join(cover_text.split())
                watermark_compact = "".join(context["watermarkText"].split())
                expected_cover_occurrences = sum(
                    "".join(value.split()).count(watermark_compact) for value in cover_values
                )
                # generatedByLabel 与默认水印文字相同，不能用简单的“不包含水印文字”判断封面。
                # 这里只允许封面固定事实本身贡献的出现次数，额外重复即视为水印泄漏。
                cover_ok = (
                    all("".join(value.split()) in cover_compact for value in cover_values)
                    and cover_compact.count(watermark_compact) == expected_cover_occurrences
                )
                toc_ok = "目录" in toc_text and all(
                    f"{item['number']} {item['title']}" in toc_text
                    for item in context["headingNumbers"]
                )
                signature_ok = (
                    context["organizationName"] in final_text
                    and context["generatedDate"] in final_text
                )
                watermark_pages = [
                    item["page"] for item in pages if item["page"] > 1 and item["watermarkPresent"]
                ]
                word_structure = _validate_docx_structure(
                    word,
                    expected_sections=context["sections"],
                    expected_headings=context["headingNumbers"],
                    expected_image_count=int(render.get("imageCount") or 0),
                    watermark_text=context["watermarkText"],
                )
                word_rendering = _validate_docx_rendering(
                    word,
                    temp_path / "word-validation",
                    context=context,
                    layout=layout,
                )
            markdown_image_count = int(render.get("imageCount") or 0)
            missing_images = max(0, markdown_image_count - rendered_image_count)
            chart_ids, citation_ids, section_ids = self._validate_manifest_markers(
                artifact_manifest,
                render=render,
                extracted_text=extracted_text,
            )
            ok = (
                bool(pages)
                and not blank_pages
                and missing_images == 0
                and not word_rendering["blankPages"]
                and word_structure["embeddedImageCount"] >= markdown_image_count
                and cover_ok
                and toc_ok
                and toc_link_count >= len(context["headingNumbers"])
                and signature_ok
                and word_structure["nativeTocPresent"]
                and word_structure["tocEntryCount"] == len(context["headingNumbers"])
            )
            validation = {
                "ok": ok,
                "status": "validated" if ok else "validation_failed",
                "pdfPath": pdf_path,
                "pdfSha256": current["sha256"],
                "wordPath": current_word_path,
                "wordSha256": word_current["sha256"],
                "pageCount": len(pages),
                "markdownImageCount": markdown_image_count,
                "renderedImageCount": rendered_image_count,
                "missingImageCount": missing_images,
                "chartIds": chart_ids,
                "citationIds": citation_ids,
                "sectionIds": section_ids,
                "blankPages": blank_pages,
                "missingPageLayoutPages": missing_page_layout,
                "coverPresent": cover_ok,
                "tocPresent": toc_ok,
                "tocLinkCount": toc_link_count,
                "bodyStartPage": body_start_page,
                "watermarkPages": watermark_pages,
                "signaturePresent": signature_ok,
                "generatedByLabelPresent": context["generatedByLabel"] in cover_text,
                "word": {**word_structure, **word_rendering},
                "pages": pages,
            }
            if _sha256(path) != current["sha256"] or path.stat().st_size != current["size"]:
                raise ReportFailure("PDF 产物在验收期间发生变化，请重新验收")
            if (
                _sha256(word) != word_current["sha256"]
                or word.stat().st_size != word_current["size"]
            ):
                raise ReportFailure("Word 产物在验收期间发生变化，请重新验收")
            return validation
        finally:
            if temp_path is not None:
                shutil.rmtree(temp_path, ignore_errors=True)

    def _validate_manifest_markers(
        self,
        manifest: dict[str, Any] | None,
        *,
        render: dict[str, Any],
        extracted_text: str,
    ) -> tuple[list[str], list[str], list[str]]:
        if manifest is None:
            return [], [], []
        charts = manifest.get("charts")
        citations = manifest.get("citations")
        sections = manifest.get("sections")
        section_numbers = manifest.get("sectionNumbers")
        heading_numbers = manifest.get("headingNumbers")
        context = render.get("documentContext")
        if (
            not isinstance(charts, list)
            or not isinstance(citations, list)
            or not isinstance(sections, list)
            or not isinstance(context, dict)
            or section_numbers != context.get("sectionNumbers")
            or heading_numbers != context.get("headingNumbers")
        ):
            raise ReportFailure("报告产物清单无效")
        chart_paths = {
            item.get("path")
            for item in charts
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        rendered_paths = {
            item.get("path")
            for item in render.get("images", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        if len(chart_paths) != len(charts) or chart_paths != rendered_paths:
            raise ReportFailure("PDF 图表与产物清单不一致")
        chart_ids: list[str] = []
        for item in charts:
            value = item.get("chartId") if isinstance(item, dict) else None
            if isinstance(value, str):
                chart_ids.append(value)
        citation_ids: list[str] = []
        for item in citations:
            value = item.get("citationId") if isinstance(item, dict) else None
            if isinstance(value, str):
                citation_ids.append(value)
        presentations = render.get("citationPresentations")
        if (
            len(citation_ids) != len(citations)
            or not isinstance(presentations, list)
            or len(presentations) != len(citation_ids)
            or any(
                not isinstance(item, dict)
                or item.get("citationId") != citation_id
                or item.get("alias") != f"[引用 {index:03d}]"
                or not isinstance(item.get("label"), str)
                for index, (citation_id, item) in enumerate(
                    zip(citation_ids, presentations, strict=True), start=1
                )
            )
            or any(item["alias"] in extracted_text for item in presentations)
            or "实际引用附录" in extracted_text
            or "[[citation:" in extracted_text
        ):
            raise ReportFailure("PDF 不应显示引用标识或实际引用附录")
        section_ids = [item for item in sections if isinstance(item, str)]
        if len(section_ids) != len(sections) or "[[section:" in extracted_text:
            raise ReportFailure("PDF 不应显示关键章节标识")
        return chart_ids, citation_ids, section_ids

    @staticmethod
    def _check_pdf_bounds(path: Path) -> None:
        try:
            import pypdf
        except ImportError as error:
            raise ReportFailure("PDF 视觉验收依赖不可用") from error
        if not path.is_file() or path.stat().st_size > MAX_PDF_BYTES:
            raise ReportFailure("PDF 文件不能超过 200 MiB")
        try:
            page_count = len(pypdf.PdfReader(str(path)).pages)
        except pypdf.errors.PdfReadError as error:
            raise ReportFailure("PDF 视觉验收无法打开产物") from error
        if not 1 <= page_count <= MAX_PDF_PAGES:
            raise ReportFailure("PDF 页数必须在 1 至 200 页之间")
