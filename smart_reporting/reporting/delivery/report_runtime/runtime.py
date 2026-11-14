"""受限 Markdown 报表运行时；由 Reporting Workflow 在本地工作区中执行。"""

from __future__ import annotations

import base64
import html
import io
import re
import shutil
import subprocess
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

from loguru import logger as loguru_logger

from .chart_image_dpi import (
    DerivedChartImage,
    apply_chart_derivatives,
    chart_image_boxes,
    derive_chart_image,
    mark_chart_images,
    read_pdf_chart_dpi,
    verify_chart_image_sources,
)
from .design import (
    cover_layout_issues,
    page_decoration_texts,
    presentation_context,
    visible_cover_text,
    watermark_text,
)
from .docx import _render_docx, _validate_docx_rendering, _validate_docx_structure
from .markdown import (
    APPENDIX_TABLES_SENTINEL,
    APPENDIX_TABLES_TITLE,
    REPORT_VISUAL_THEME,
    SUMMARY_END,
    SUMMARY_END_SENTINEL,
    SUMMARY_SENTINEL,
    SUMMARY_TITLE,
    _bind_heading_anchors,
    _body_tokens,
    _document_context,
    _join_cjk_soft_breaks,
    _markdown_title,
    _semantic_documents,
    _strip_strong_boundaries,
    format_heading_label,
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
    _pdf_section_pages,
    _toc_page_numbers,
)
from .report_design import ReportDesign, resolve_design
from .validation import (
    IMAGE_SUFFIXES,
    MAX_DOCX_BYTES,
    MAX_IMAGE_BYTES,
    MAX_MARKDOWN_BYTES,
    MAX_PDF_BYTES,
    MAX_TOTAL_IMAGE_BYTES,
    ReportFailure,
    _check_image_signature,
    _cleanup_directory,
    _input_path,
    _output_path,
    _reject_symlinks,
    _relative_path,
    _sha256,
    _temporary_docx_path,
    _temporary_pdf_path,
    _validation_directory,
    _word_output_path,
)

MAX_DATASET_PATHS = 20
PDF_VALIDATION_TIMEOUT_SECONDS = 540
_SECTION_MARKER = re.compile(r"\[\[section:([^\]\r\n]+)\]\]")


def _toc_headings_present(text: str, headings) -> bool:
    compact = ''.join(text.split())
    return '目录' in compact and all(
        ''.join(format_heading_label(level=item['level'], number=item['number'], title=item['title']).split()) in compact
        for item in headings
    )


class ReportRuntime:
    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).resolve()
        # _images 按原始 src 记录已唯一解析的图片，供 HTML 内联复用。
        self._image_sources: dict[str, Path] = {}

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

    def _manifest_image(
        self, markdown_path: Path, relative: PurePosixPath, manifest_paths: list[str]
    ) -> Path | None:
        """草稿与图文目录分离时，按渲染清单唯一定位图片。

        清单路径与 Markdown 直接路径同一规则：拒绝绝对路径、.. 与反斜杠，不能借回退
        绕过越界校验。同名候选优先取 Markdown 所在目录的祖先目录；仍不唯一时报错，
        不静默取第一个。
        """

        target = relative.as_posix()
        candidates: list[Path] = []
        for value in manifest_paths:
            candidate = PurePosixPath(value)
            if (
                "\\" in value
                or candidate.is_absolute()
                or ".." in candidate.parts
                or not (value == target or value.endswith("/" + target))
            ):
                continue
            path = self.workspace.joinpath(*candidate.parts)
            if path not in candidates:
                candidates.append(path)
        if len(candidates) > 1:
            ancestors = set(markdown_path.resolve().parents)
            preferred = [item for item in candidates if item.parent.resolve() in ancestors]
            if len(preferred) == 1:
                candidates = preferred
        if len(candidates) > 1:
            raise ReportFailure("Markdown 图片在渲染清单中有多个同名候选，无法唯一定位")
        return candidates[0] if candidates else None

    def _images(
        self, markdown_path: Path, tokens: list[Any], state: dict[str, Any] | None = None
    ) -> set[Path]:
        # 编辑器导出的草稿位于 revision-N/draft/ 子目录，图片仍在报告根目录；
        # 相对解析失败时按渲染清单（工作区相对路径）回退定位。解析结果按原始 src
        # 记录，HTML 内联直接复用，避免两处各自猜测选中不同文件。
        self._image_sources = {}
        manifest_paths: list[str] = []
        render = state.get("render") if isinstance(state, dict) else None
        raw_images = render.get("images") if isinstance(render, dict) else None
        if isinstance(raw_images, list):
            for item in raw_images:
                if isinstance(item, dict) and isinstance(item.get("path"), str):
                    manifest_paths.append(item["path"].replace("\\", "/"))
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
                if not image.is_file():
                    matched = self._manifest_image(markdown_path, relative, manifest_paths)
                    if matched is not None:
                        image = matched
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
                resolved = image.resolve()
                images.append(resolved)
                self._image_sources[source] = resolved
        unique = set(images)
        if sum(path.stat().st_size for path in unique) > MAX_TOTAL_IMAGE_BYTES:
            raise ReportFailure("Markdown 图片合计超过 50 MiB")
        return unique

    @staticmethod
    def _inline_images(
        body: str,
        source_parent: Path,
        allowed_images: set[Path],
        sources: Mapping[str, Path] | None = None,
    ) -> str:
        image_pattern = re.compile(r'(<img\b[^>]*\bsrc=)(["\'])([^"\']+)(\2)', re.I)

        def replace(match: re.Match[str]) -> str:
            source = html.unescape(match.group(3))
            parsed = urlsplit(source)
            if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                raise ReportFailure("HTML 图片只能引用已校验的工作区资源")
            # 优先使用 _images 已唯一解析的结果（含草稿目录的清单回退）。
            path = (sources or {}).get(source) or (source_parent / unquote(parsed.path)).resolve()
            if path not in allowed_images:
                raise ReportFailure("HTML 图片引用了未校验资源")
            mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(
                path.suffix.lower(), f"image/{path.suffix.lower().lstrip('.')}"
            )
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return f"{match.group(1)}{match.group(2)}data:{mime};base64,{encoded}{match.group(4)}"

        return image_pattern.sub(replace, body)

    @staticmethod
    def _reject_html_links(body: str, *, allowed_links: set[str] | None = None) -> None:
        allowed = allowed_links or set()
        link_pattern = re.compile(r'<a\b[^>]*\bhref=(?:"([^"]*)"|\'([^\']*)\')', re.I)
        for match in link_pattern.finditer(body):
            href = match.group(1) if match.group(1) is not None else match.group(2)
            if href in allowed:
                continue
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
        chart_images: list[dict[str, Any]] | None = None,
        chart_image_issues: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        try:
            from markdown_it import MarkdownIt
        except ImportError as error:
            raise ReportFailure("PDF 运行时依赖不可用") from error

        self._validate_datasets(state)
        temporary: Path | None = None
        try:
            source = _input_path(self.workspace, markdown_path, ".md")
            if source.stat().st_size > MAX_MARKDOWN_BYTES:
                raise ReportFailure("Markdown 文件超过 1 MiB")
            try:
                source_bytes = source.read_bytes()
                markdown = source_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            except UnicodeDecodeError as error:
                raise ReportFailure("Markdown 文件必须使用 UTF-8 编码") from error

            design = resolve_design(state, format="pdf")
            word_design = resolve_design(state, format="word")
            # 导出的 PDF/Word 默认不带来源编号与附录；只有导出设置显式开启时才展示。
            include_sources = design.options.sources
            context = _document_context(state.get("_documentContext"))
            from .overview import load_overview
            from .projection import build_render_projection
            from .table_captions import (
                load_table_caption_input,
                prepare_table_captions,
                render_table_captions,
            )

            needs_table_captions = bool(prepare_table_captions(markdown, {})[2])
            table_caption_source = (load_table_caption_input(state, self.workspace,
                str(source.relative_to(self.workspace)), source_bytes) if needs_table_captions
                else {'status': 'not_required', 'captions': None, 'issues': [], 'source': None})

            projection = build_render_projection(
                source_bytes, context["sections"], citation_presentations=state.get("_citationPresentations"),
                include_sources=include_sources, trace_sources=state.get("_traceSourcePresentations"),
                management_overview=load_overview(state, self.workspace),
                claim_support=state.get('_claimSupportProjection'),
                table_captions=table_caption_source['captions'],
            )
            pdf_markdown, citation_presentations, trace_source_render = (
                projection.markdown, projection.citation_presentations, projection.trace_source_render,
            )
            parser = MarkdownIt("commonmark", {"html": False}).enable("table")
            tokens = parser.parse(pdf_markdown)
            include_cover = design.options.cover
            include_toc = design.options.toc
            include_header_footer = design.options.header_footer
            include_page_numbers = design.options.page_numbers
            layout = _page_layout(
                page_layout,
                include_header_footer=include_header_footer,
                include_page_numbers=include_page_numbers,
            )
            title = _markdown_title(tokens)
            if title != context["title"]:
                raise ReportFailure("Markdown 标题与服务端文档展示契约不一致")
            marker_sections = _SECTION_MARKER.findall(markdown)
            expected_section_codes = [item["code"] for item in context["sections"]]
            if marker_sections != expected_section_codes:
                raise ReportFailure("Markdown 正式章节标识与已批准提纲不一致")
            _bind_heading_anchors(tokens, context["headingNumbers"])
            allowed_images = self._images(source, tokens, state)
            verified_chart_images = verify_chart_image_sources(
                self.workspace, chart_images or [], allowed_images,
            )
            source_artifact = self._artifact(source)
            if source_artifact["sha256"] != projection.receipt["sourceSha256"]:
                raise ReportFailure("Markdown 在投影期间发生变化")
            image_artifacts = [self._artifact(path) for path in sorted(allowed_images)]
            body = _strip_strong_boundaries(
                parser.renderer.render(
                    _join_cjk_soft_breaks(_body_tokens(tokens)), parser.options, {}
                )
            )
            body = render_table_captions(body, projection.table_captions,
                numbered=bool(design.tables and design.tables.caption_numbering))
            body = mark_chart_images(body, self._image_sources, verified_chart_images)
            html_body = self._inline_images(
                body.replace(f"<p>{APPENDIX_TABLES_SENTINEL}</p>", APPENDIX_TABLES_TITLE)
                .replace(f"<p>{SUMMARY_SENTINEL}</p>", SUMMARY_TITLE)
                .replace(f"<p>{SUMMARY_END_SENTINEL}</p>", SUMMARY_END),
                source.parent, allowed_images, self._image_sources,
            )
            self._reject_html_links(
                html_body,
                allowed_links={
                    item["url"]
                    for item in citation_presentations
                    if isinstance(item.get("url"), str)
                },
            )
            output = _output_path(self.workspace, output_path)
            word_output = _word_output_path(
                self.workspace,
                word_output_path or str(PurePosixPath(output_path).with_suffix(".docx")),
            )
            if output.parent != word_output.parent:
                raise ReportFailure("PDF 和 Word 必须发布到同一 revision 目录")
            temporary = _temporary_pdf_path(self.workspace, temporary_path)
            temporary_docx = _temporary_docx_path(temporary)
            # html_body 已将工作区图片内联为 data URI，PDF 与 Word 都必须用它：
            # 草稿目录与图文目录分离时，相对 src 在两路渲染器里都解析不到。
            pdf_document, word_document = _semantic_documents(
                html_body,
                context=context,
                layout=layout,
                include_cover=include_cover,
                include_toc=include_toc,
                citation_presentations=(citation_presentations if include_sources else []),
                trace_sources=(trace_source_render if include_sources else None),
                design=design,
            )
            context["filename"] = output.name
            word_context = dict(context)
            word_context["filename"] = word_output.name
            word_preferences = state.get("_formatPreferences", {}).get("word")
            pdf_preferences = state.get("_formatPreferences", {}).get("pdf")
            for document_context, preferences in ((context, pdf_preferences), (word_context, word_preferences)):
                if preferences:
                    document_context.update(organizationName=preferences["common"]["signer"],
                        generatedByLabel=preferences["common"]["generatedByLabel"])
            if pdf_preferences:
                pdf_document, _ = _semantic_documents(html_body, context=context, layout=layout,
                    include_cover=include_cover, include_toc=include_toc,
                    citation_presentations=(citation_presentations if include_sources else []),
                    trace_sources=(trace_source_render if include_sources else None), design=design)
            if word_preferences or word_design != design:
                # Word 使用自身的排版、落款和导出开关，不借用 PDF 的解析结果。
                word_sources = word_design.options.sources
                word_projection = build_render_projection(source_bytes, word_context["sections"],
                    citation_presentations=state.get("_citationPresentations"), include_sources=word_sources,
                    trace_sources=state.get("_traceSourcePresentations"), management_overview=load_overview(state, self.workspace),
                    claim_support=state.get('_claimSupportProjection'), table_captions=table_caption_source['captions'])
                word_tokens = parser.parse(word_projection.markdown)
                _bind_heading_anchors(word_tokens, word_context["headingNumbers"])
                word_html = _strip_strong_boundaries(parser.renderer.render(
                    _join_cjk_soft_breaks(_body_tokens(word_tokens)), parser.options, {}))
                word_html = render_table_captions(word_html, word_projection.table_captions,
                    numbered=bool(word_design.tables and word_design.tables.caption_numbering))
                word_html = self._inline_images(
                    word_html.replace(f"<p>{APPENDIX_TABLES_SENTINEL}</p>", APPENDIX_TABLES_TITLE)
                    .replace(f"<p>{SUMMARY_SENTINEL}</p>", SUMMARY_TITLE)
                    .replace(f"<p>{SUMMARY_END_SENTINEL}</p>", SUMMARY_END),
                    source.parent, allowed_images, self._image_sources)
                _, word_document = _semantic_documents(word_html, context=word_context, layout=layout,
                    include_cover=word_design.options.cover, include_toc=word_design.options.toc,
                    citation_presentations=(word_projection.citation_presentations if word_sources else []),
                    trace_sources=(word_projection.trace_source_render if word_sources else None), design=word_design)
            render_issues: list[dict[str, str]] = [
                *table_caption_source['issues'], *projection.table_caption_issues,
                *(chart_image_issues or []),
            ]
            if pdf_preferences and pdf_preferences.get('embedFonts') is False:
                render_issues.append({'code': 'pdf_font_embedding_required',
                    'message': 'PDF/UA 输出始终嵌入字体；旧版关闭字体嵌入设置已忽略，文件与下载继续保留。'})
            if projection.claim_support_check is not None and projection.claim_support_check['status'] != 'verified':
                render_issues.append({'code': 'claim_support_projection_unknown', 'message': '解释与建议支持状态未能核验，已保留提示和可读报告。'})
            if projection.overview_check is not None and projection.overview_check["status"] != "verified":
                render_issues.append({"code": "management_overview_projection_unknown", "message": "经营总览身份未获核验，已保留缺项说明和可读报告。"})
            chart_image_dpi_evidence: list[dict[str, Any]] = []

            def render_pdf() -> tuple[int, int]:
                nonlocal pdf_document

                import pypdf
                from weasyprint import HTML, URLFetcher

                output_options = {'jpeg_quality': design.pdf_output.image_quality} if design.pdf_output else {}
                target_dpi = design.charts.image_dpi if design.charts is not None else None
                if target_dpi is None:
                    legacy_preferences = state.get('_formatPreferences', {}).get('pdf', {})
                    legacy_charts = legacy_preferences.get('charts') if isinstance(legacy_preferences, dict) else None
                    target_dpi = legacy_charts.get('imageDpi') if isinstance(legacy_charts, dict) else None
                if not isinstance(target_dpi, int) or isinstance(target_dpi, bool):
                    target_dpi = None
                chart_derivatives: dict[str, DerivedChartImage] = {}

                file_fetcher = URLFetcher(allowed_protocols={"file"}, fail_on_errors=True)
                # default_url_fetcher 已弃用（WeasyPrint 后续版本移除），data URI 同样交给只放行
                # 该协议的 URLFetcher 解码。
                data_fetcher = URLFetcher(allowed_protocols={"data"}, fail_on_errors=True)

                def fetch_resource(url: str) -> dict[str, Any]:
                    parsed = urlsplit(url)
                    if parsed.scheme == "data":
                        # data URI 由 _inline_images 从已校验工作区图片生成，自包含内容。
                        return data_fetcher(url)
                    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
                        raise ReportFailure("PDF 渲染禁止访问外部资源")
                    path = Path(unquote(parsed.path)).resolve()
                    if path not in allowed_images:
                        raise ReportFailure("PDF 渲染引用了未校验资源")
                    return file_fetcher(url)

                preflight_document = HTML(
                    string=pdf_document,
                    base_url=str(source.parent),
                    url_fetcher=fetch_resource,
                ).render(**output_options)
                image_boxes = chart_image_boxes(preflight_document)
                pdf_html_body = html_body
                if target_dpi is not None:
                    for image_path, chart_source in verified_chart_images.items():
                        boxes = image_boxes.get(chart_source.chart_id, [])
                        if not boxes:
                            render_issues.append({
                                'code': 'pdf_chart_image_box_unverified',
                                'message': '图表图片显示区域无法唯一核验，PDF 保留原图并继续生成。',
                            })
                            continue
                        derived = derive_chart_image(
                            image_path, chart_source,
                            # 同一图片可多次绘制；按最小框派生，各处仍保留自己的版面尺寸。
                            display_width_css_px=min(box[0] for box in boxes),
                            display_height_css_px=min(box[1] for box in boxes),
                            target_dpi=target_dpi,
                        )
                        if derived is None:
                            content = image_path.read_bytes()
                            from PIL import Image
                            with Image.open(io.BytesIO(content)) as image:
                                image.load()
                                width, height = image.size
                            derived = DerivedChartImage(
                                chart_id=chart_source.chart_id,
                                source_path=chart_source.path,
                                source_sha256=chart_source.sha256,
                                derived_sha256=chart_source.sha256,
                                media_type='image/png' if image_path.suffix.lower() == '.png' else 'image/jpeg',
                                width=width, height=height, data=content,
                            )
                        chart_derivatives[chart_source.chart_id] = derived
                    changed = {
                        chart_id: item for chart_id, item in chart_derivatives.items()
                        if item.derived_sha256 != item.source_sha256
                    }
                    if changed:
                        pdf_html_body = apply_chart_derivatives(html_body, changed, image_boxes)
                        pdf_document, _ = _semantic_documents(
                            pdf_html_body, context=context, layout=layout,
                            include_cover=include_cover, include_toc=include_toc,
                            citation_presentations=(citation_presentations if include_sources else []),
                            trace_sources=(trace_source_render if include_sources else None),
                            design=design,
                        )
                        preflight_document = HTML(
                            string=pdf_document,
                            base_url=str(source.parent),
                            url_fetcher=fetch_resource,
                        ).render(**output_options)
                        final_boxes = chart_image_boxes(preflight_document)
                        changed_boxes = {
                            key: {'before': image_boxes.get(key), 'after': final_boxes.get(key)}
                            for key in changed
                            if len(final_boxes.get(key, [])) != len(image_boxes.get(key, []))
                            or any(abs(before - after) > 0.001 for before_box, after_box in zip(
                                image_boxes.get(key, []), final_boxes.get(key, []), strict=False
                            ) for before, after in zip(before_box, after_box, strict=True))
                        }
                        if changed_boxes:
                            pdf_document, _ = _semantic_documents(
                                html_body, context=context, layout=layout,
                                include_cover=include_cover, include_toc=include_toc,
                                citation_presentations=(citation_presentations if include_sources else []),
                                trace_sources=(trace_source_render if include_sources else None),
                                design=design,
                            )
                            pdf_html_body = html_body
                            chart_derivatives.clear()
                            preflight_document = HTML(
                                string=pdf_document,
                                base_url=str(source.parent),
                                url_fetcher=fetch_resource,
                            ).render(**output_options)
                            render_issues.append({
                                'code': 'pdf_chart_image_layout_changed',
                                'message': '图表派生后版面尺寸发生变化，PDF 保留原图并继续生成。',
                                'details': changed_boxes,
                            })
                toc_page_numbers = _toc_page_numbers(
                    preflight_document.pages, context["headingNumbers"]
                )
                if not include_toc:
                    # 不输出目录时页码不进入 HTML，预排版即最终排版；
                    # 锚点完整性已由上面的 _toc_page_numbers 校验，无需再排版一遍。
                    final_document = preflight_document
                else:
                    pdf_document, _ = _semantic_documents(
                        pdf_html_body,
                        context=context,
                        layout=layout,
                        toc_page_numbers=toc_page_numbers,
                        include_cover=include_cover,
                        include_toc=include_toc,
                        citation_presentations=(citation_presentations if include_sources else []),
                        trace_sources=(trace_source_render if include_sources else None),
                        design=design,
                    )
                    final_document = HTML(
                        string=pdf_document,
                        base_url=str(source.parent),
                        url_fetcher=fetch_resource,
                    ).render(**output_options)
                    if (
                        _toc_page_numbers(final_document.pages, context["headingNumbers"])
                        != toc_page_numbers
                    ):
                        # 目录页码使用固定宽度，正常不会改变分页；若字体或渲染器升级导致
                        # 锚点漂移，则不能发布目录与正文不一致的产物。
                        raise ReportFailure("PDF 目录页码在最终渲染时发生漂移")
                render_issues.extend(cover_layout_issues(final_document.pages, design))
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
                    include_cover=include_cover,
                    design=design,
                )
                if chart_derivatives:
                    try:
                        readback = read_pdf_chart_dpi(temporary, chart_derivatives)
                        for chart_id, values in readback.items():
                            expected_count = len(image_boxes.get(chart_id, []))
                            if (
                                not values or len(values) != expected_count
                                or any(max(item['widthDpi'], item['heightDpi']) > target_dpi + 0.05 for item in values)
                            ):
                                raise ValueError('chart dpi readback mismatch')
                            item = chart_derivatives[chart_id]
                            chart_image_dpi_evidence.append({
                                'chartId': chart_id,
                                'sourcePath': item.source_path,
                                'sourceSha256': item.source_sha256,
                                'derivedSha256': item.derived_sha256,
                                'targetDpi': target_dpi,
                                'draws': values,
                            })
                    except Exception as error:
                        loguru_logger.warning('pdf_chart_image_dpi_readback_unverified reason={}', type(error).__name__)
                        chart_image_dpi_evidence.clear()
                        render_issues.append({
                            'code': 'pdf_chart_image_dpi_unverified',
                            'message': 'PDF 图表有效分辨率未能独立核验，文件保留并继续交付。',
                        })
                pdf_size = temporary.stat().st_size
                if pdf_size > MAX_PDF_BYTES:
                    raise ReportFailure("PDF 文件不能超过 200 MiB")
                reader = pypdf.PdfReader(str(temporary))
                page_count = len(reader.pages)
                if not page_count:
                    raise ReportFailure("PDF 校验失败")
                if page_count > MAX_PDF_PAGES:
                    raise ReportFailure("PDF 页数不能超过 200 页")
                return pdf_size, page_count

            def render_word() -> tuple[int, dict[str, Any]]:
                rendered_word_structure = _render_docx(
                    word_document,
                    source_parent=source.parent,
                    output=temporary_docx,
                    context=word_context,
                    layout=layout,
                    include_cover=word_design.options.cover,
                    include_toc=word_design.options.toc,
                    design=word_design,
                    chart_image_dpi=(word_design.charts.image_dpi if word_design.charts is not None
                        and word_design.charts.image_dpi is not None else
                        (word_preferences or {}).get("charts", {}).get("imageDpi")),
                    chart_source_sha256s={item["sha256"] for item in image_artifacts},
                )
                docx_size = temporary_docx.stat().st_size
                if docx_size > MAX_DOCX_BYTES:
                    raise ReportFailure("Word 文件不能超过 200 MiB")
                word_structure = _validate_docx_structure(
                    temporary_docx,
                    expected_sections=context["sections"],
                    expected_headings=context["headingNumbers"],
                    expected_image_count=len(allowed_images),
                )
                if isinstance(rendered_word_structure, dict) and "chartImageDpi" in rendered_word_structure:
                    word_structure["chartImageDpi"] = rendered_word_structure["chartImageDpi"]
                return docx_size, word_structure

            completed: dict[str, tuple[Path, Path]] = {}
            pdf_size, page_count, docx_size = 0, 0, 0
            word_structure: dict[str, Any] = {}
            for label, renderer, candidate, destination in (
                ("pdf", render_pdf, temporary, output),
                ("word", render_word, temporary_docx, word_output),
            ):
                try:
                    receipt: Any = renderer()
                    if label == "pdf":
                        pdf_size, page_count = receipt
                    else:
                        docx_size, word_structure = receipt
                    completed[label] = (candidate, destination)
                except Exception as error:
                    from loguru import logger

                    logger.warning("report_format_render_failed format={} error_type={}", label, type(error).__name__)
                    candidate.unlink(missing_ok=True)
                    render_issues.append({"code": f"report_{label}_render_failed", "message": f"{'PDF' if label == 'pdf' else 'Word'} 生成或结构检查失败，其他成功格式仍可下载。"})
            if not completed:
                raise ReportFailure("PDF 和 Word 均未成功生成")
            if self._artifact(source)["sha256"] != source_artifact["sha256"] or any(
                self._artifact(path)["sha256"] != artifact["sha256"]
                for path, artifact in zip(sorted(allowed_images), image_artifacts, strict=True)
            ):
                raise ReportFailure("Markdown 或图片在渲染期间发生变化，请重新生成报表")
            artifacts = {
                label: {"path": str(destination.relative_to(self.workspace)),
                        "size": candidate.stat().st_size, "sha256": _sha256(candidate)}
                for label, (candidate, destination) in completed.items()
            }
            created_output_directory = False
            published: list[Path] = []
            try:
                if not output.parent.exists():
                    output.parent.mkdir(mode=0o700)
                    created_output_directory = True
                for label, (candidate, destination) in completed.items():
                    try:
                        shutil.copyfile(candidate, destination)
                    except Exception as error:
                        from loguru import logger

                        logger.warning("report_format_copy_failed format={} error_type={}", label, type(error).__name__)
                        destination.unlink(missing_ok=True)
                        artifacts.pop(label, None)
                        render_issues.append({"code": f"report_{label}_copy_failed", "message": f"{'PDF' if label == 'pdf' else 'Word'} 写入失败，其他成功格式仍可下载。"})
                    else:
                        published.append(destination)
                if not artifacts:
                    raise ReportFailure("PDF 和 Word 均未成功写入")
            except BaseException:
                for path in published:
                    path.unlink(missing_ok=True)
                if created_output_directory:
                    output.parent.rmdir()
                raise
            render = {
                "markdown": source_artifact,
                **artifacts,
                "renderIssues": render_issues,
                "projection": projection.receipt,
                "tableCaptionSource": {key: value for key, value in table_caption_source.items() if key != 'captions'},
                "images": image_artifacts,
                "chartImageDpi": chart_image_dpi_evidence,
                "pageCount": page_count,
                "imageCount": len(allowed_images),
                "pageLayout": layout,
                "exportSettings": {
                    "cover": include_cover,
                    "toc": include_toc,
                    "headerFooter": include_header_footer,
                    "pageNumbers": include_page_numbers,
                    "sources": include_sources,
                },
                "reportTitle": presentation_context(design, context)["title"],
                "documentContext": {key: value for key, value in context.items() if key != "filename"},
                "reportDesign": design.compact(),
                "wordReportDesign": word_design.compact(),
                "wordDocumentContext": {key: value for key, value in word_context.items() if key != "filename"},
                "visualTheme": deepcopy(REPORT_VISUAL_THEME),
                "wordStructure": word_structure,
                "citationPresentations": citation_presentations,
                "citationAppendixPresent": include_sources and bool(citation_presentations),
                "traceSourcePresentations": trace_source_render,
                "traceSourceAppendixPresent": include_sources
                and bool(trace_source_render["entries"]),
                "knowledgeSourceAppendixPresent": include_sources
                and bool(trace_source_render.get('knowledge')),
            }
            result = {
                "status": "rendered" if len(artifacts) == 2 else "partial_rendered",
                "renderIssues": render_issues,
                "jobId": state["jobId"],
                "markdownPath": str(source.relative_to(self.workspace)),
                **({"pdfPath": artifacts["pdf"]["path"], "size": pdf_size} if "pdf" in artifacts else {}),
                **({"wordPath": artifacts["word"]["path"], "wordSize": docx_size} if "word" in artifacts else {}),
                "pageCount": page_count,
                "imageCount": len(allowed_images),
                "render": render,
            }
            return result
        finally:
            if temporary is not None:
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
            temp_path = _validation_directory(self.workspace, temporary_directory)
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
                export_settings = render.get("exportSettings")
                include_header_footer = not isinstance(
                    export_settings, dict
                ) or export_settings.get("headerFooter", True)
                include_page_numbers = not isinstance(export_settings, dict) or export_settings.get(
                    "pageNumbers", True
                )
                include_cover = not isinstance(export_settings, dict) or export_settings.get(
                    "cover", True
                )
                include_toc = not isinstance(export_settings, dict) or export_settings.get(
                    "toc", True
                )
                # 首个参与编号和页面装饰的物理页；无封面导出时正文或目录从第 1 页开始。
                first_numbered_page = 2 if include_cover else 1
                layout = _page_layout(
                    render.get("pageLayout"),
                    include_header_footer=include_header_footer,
                    include_page_numbers=include_page_numbers,
                )
                title = str(render.get("reportTitle") or "智能运营报表")
                context = _document_context(render.get("documentContext"))
                design = ReportDesign.model_validate(render.get("reportDesign") or {})
                mark_text = watermark_text(design, context)
                section_pages = _pdf_section_pages(reader, context["sections"])
                _pdf_heading_pages(reader, context["headingNumbers"])
                body_start_page = min(section_pages.values())
                toc_link_count = (
                    _pdf_link_count(
                        reader,
                        start_page=first_numbered_page,
                        end_page=body_start_page - 1,
                    )
                    if include_toc and body_start_page > first_numbered_page
                    else 0
                )
                for index, (page, rendered_page) in enumerate(
                    zip(reader.pages, rendered_pages, strict=True), start=1
                ):
                    page_text = page.extract_text() or ""
                    extracted_pages.append(page_text)
                    with Image.open(rendered_page) as image:
                        grayscale = image.convert("L")
                        histogram = grayscale.histogram()
                        width, height = grayscale.size
                    # 灰度直方图在 C 层统计，避免逐像素 Python 迭代（200 页约 1 亿次）。
                    sample_count = width * height
                    non_white = sum(histogram[:250])
                    ratio = round(non_white / sample_count, 6) if sample_count else 0.0
                    image_count = len(page.images)
                    rendered_image_count += image_count
                    if index < first_numbered_page:
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
                            first_numbered_page=first_numbered_page,
                        )
                        layout_present = _has_page_layout(
                            page_text,
                            layout,
                            title=title,
                            organization=context["organizationName"],
                            page=page_value,
                            pages=pages_value,
                        )
                    numbered = index >= first_numbered_page
                    preference_decorations = page_decoration_texts(design, context, physical_page=index,
                        body_start_page=body_start_page, page=page_value, pages=pages_value,
                        filename=Path(render["pdf"]["path"]).name) if design.header_footer and numbered else None
                    if preference_decorations is not None:
                        compact = "".join(page_text.split())
                        layout_present = all("".join(value.split()) in compact for value in preference_decorations.values())
                    watermark_present = bool(design.watermark.enabled and mark_text and mark_text in page_text and (numbered or design.watermark.cover))
                    substantive_text = "".join(page_text.split())
                    if numbered:
                        decorations = [
                            mark_text if design.watermark.enabled else "",
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
                        if preference_decorations is not None:
                            decorations = [mark_text if design.watermark.enabled else "", *preference_decorations.values()]
                        # 页眉、页脚和水印即使存在，也不能把无正文页面伪装成非空白页。
                        for decoration in decorations:
                            if decoration:
                                substantive_text = substantive_text.replace("".join(decoration.split()), "")
                    text_char_count = len(substantive_text)
                    if numbered and not layout_present:
                        missing_page_layout.append(index)
                    blank = (
                        text_char_count == 0 and image_count == 0 and (numbered or ratio < 0.0005)
                        and not (role == "cover" and not visible_cover_text(design, context))
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
                            "pageLayoutExpected": numbered,
                            "watermarkPresent": watermark_present,
                            "role": role,
                            "blank": blank,
                        }
                    )
                extracted_text = "\n".join(extracted_pages)
                self._validate_trace_source_visibility(render, extracted_text)
                cover_text = extracted_pages[0]
                toc_text = "\n".join(extracted_pages[first_numbered_page - 1 : body_start_page - 1])
                cover_values = visible_cover_text(design, context)
                cover_compact = "".join(cover_text.split())
                cover_ok = all("".join(value.split()) in cover_compact for value in cover_values)
                # 无封面导出时标题随正文首页出现；目录关闭时不存在目录页与目录链接。
                title_ok = (
                    cover_ok
                    if include_cover
                    else "".join(title.split())
                    in "".join(extracted_pages[body_start_page - 1].split())
                )
                toc_ok = _toc_headings_present(toc_text, context["headingNumbers"])
                from .design import signature_date

                signature_ok = any(context["organizationName"] in text
                    and signature_date(design, context) in text for text in extracted_pages[body_start_page - 1:])
                watermark_pages = [
                    item["page"]
                    for item in pages
                    if item["watermarkPresent"]
                ]
                word_structure = _validate_docx_structure(
                    word,
                    expected_sections=context["sections"],
                    expected_headings=context["headingNumbers"],
                    expected_image_count=int(render.get("imageCount") or 0),
                )
                word_rendering = _validate_docx_rendering(
                    word,
                    temp_path / "word-validation",
                    context=render.get("wordDocumentContext", context),
                    layout=layout,
                    include_cover=ReportDesign.model_validate(render.get("wordReportDesign") or render.get("reportDesign") or {}).options.cover,
                    design=ReportDesign.model_validate(render.get("wordReportDesign") or render.get("reportDesign") or {}),
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
                and title_ok
                and signature_ok
                and word_structure["tocEntryCount"] == len(context["headingNumbers"])
                and (
                    not include_toc
                    or (
                        toc_ok
                        and toc_link_count >= len(context["headingNumbers"])
                        and word_structure["nativeTocPresent"]
                    )
                )
            )
            validation = {
                "ok": ok,
                "issues": [
                    {"code": code, "message": message}
                    for passed, code, message in (
                        (bool(pages), 'pdf_pages_missing', 'PDF 无可读取页面。'),
                        (not blank_pages, 'pdf_blank_pages', 'PDF 存在空白页。'),
                        (missing_images == 0, 'pdf_images_missing', 'PDF 缺少登记图表。'),
                        (not word_rendering['blankPages'], 'word_blank_pages', 'Word 转换后存在空白页。'),
                        (word_structure['embeddedImageCount'] >= markdown_image_count, 'word_images_missing', 'Word 缺少登记图表。'),
                        (title_ok, 'report_title_missing', '报告标题或封面内容不完整。'),
                        (signature_ok, 'report_signature_missing', '报告落款不完整。'),
                        (word_structure['tocEntryCount'] == len(context['headingNumbers']), 'word_heading_count_mismatch', 'Word 标题数量与提纲不一致。'),
                        (not include_toc or toc_ok, 'pdf_toc_heading_missing', 'PDF 目录未完整覆盖批准标题。'),
                        (not include_toc or toc_link_count >= len(context['headingNumbers']), 'pdf_toc_links_missing', 'PDF 目录链接不完整。'),
                        (not include_toc or word_structure['nativeTocPresent'], 'word_toc_missing', 'Word 原生目录缺失。'),
                    ) if not passed
                ],
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
                "coverPresent": include_cover and cover_ok,
                "tocPresent": include_toc and toc_ok,
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
            from .overview import load_overview
            from .projection import verify_render_projection
            from .table_captions import load_table_caption_input, prepare_table_captions

            try:
                source_path = _input_path(self.workspace, render["markdown"]["path"], ".md")
                source_bytes = source_path.read_bytes()
                caption_source = (load_table_caption_input(state, self.workspace, render['markdown']['path'], source_bytes)
                    if prepare_table_captions(source_bytes.decode().replace('\r\n', '\n').replace('\r', '\n'), {})[2]
                    else {'captions': None})
                projection_check = verify_render_projection(
                    render.get("projection"), source_bytes, context["sections"],
                    citation_presentations=state.get("_citationPresentations"),
                    include_sources=isinstance(export_settings, dict) and export_settings.get("sources") is True,
                    trace_sources=state.get("_traceSourcePresentations"),
                    management_overview=load_overview(state, self.workspace),
                    claim_support=state.get('_claimSupportProjection'),
                    table_captions=caption_source['captions'],
                )
            except Exception:
                projection_check = {"status": "unknown", "reason": "projection_source_unavailable"}
            validation["projectionCheck"] = projection_check
            table_caption_issues = [issue for issue in render.get('renderIssues', ()) if issue.get('code') in {
                'report_table_caption_source_unavailable', 'report_table_caption_unverified'}]
            if table_caption_issues:
                validation['ok'] = False
                validation['status'] = 'validation_failed'
                validation['issues'].extend(table_caption_issues)
            layout_issues = [issue for issue in render.get("renderIssues", ()) if issue.get("code") in {"report_cover_text_overflow", "report_cover_overlap"}]
            if layout_issues:
                validation["ok"] = False
                validation["status"] = "validation_failed"
                validation["issues"].extend(layout_issues)
            if any(issue.get("code") == "management_overview_projection_unknown" for issue in render.get("renderIssues", ())):
                validation["ok"] = False
                validation["status"] = "validation_failed"
                validation["issues"].append({"code": "management_overview_projection_unknown", "message": "经营总览未通过核验，产物及缺项说明已保留。"})
            if any(issue.get('code') == 'claim_support_projection_unknown' for issue in render.get('renderIssues', ())):
                validation['ok'] = False
                validation['status'] = 'validation_failed'
                validation['issues'].append({'code': 'claim_support_projection_unknown',
                    'message': '解释与建议支持状态未能核验，产物及提示已保留。'})
            if projection_check["status"] != "verified":
                validation["ok"] = False
                validation["status"] = "validation_failed"
                validation["issues"].append({"code": "render_projection_unknown", "message": "最终渲染投影身份未获核验，产物保留供复核。"})
            return validation
        finally:
            if temp_path is not None:
                shutil.rmtree(temp_path, ignore_errors=True)

    def _validate_trace_source_visibility(
        self,
        render: dict[str, Any],
        extracted_text: str,
    ) -> None:
        """数据来源附录验收（B8 G8）：编号、附录与导出设置三者一致。

        来源展示开启时，每个已分配编号必须出现在 PDF 文本中（正文或附录），
        附录标题存在且登记标志为真；关闭时三者都必须缺失。协议标记在任何
        设置下都不得出现在成品文本里。
        """
        trace = render.get("traceSourcePresentations")
        raw_entries = trace.get("entries") if isinstance(trace, dict) else None
        entries = [item for item in raw_entries or [] if isinstance(item, dict)]
        sources_enabled = render.get("exportSettings", {}).get("sources", False)
        appendix_present = render.get("traceSourceAppendixPresent")
        aliases = [item.get("alias") for item in entries]
        if sources_enabled:
            if appendix_present is not bool(entries) or (
                entries and "数据来源附录" not in extracted_text
            ):
                raise ReportFailure("PDF 数据来源附录不完整")
            if any(
                not isinstance(alias, str) or alias not in extracted_text
                for alias in aliases
            ):
                raise ReportFailure("PDF 数据来源编号不完整")
        else:
            if (
                appendix_present is not False
                or "数据来源附录" in extracted_text
                or any(isinstance(alias, str) and alias in extracted_text for alias in aliases)
            ):
                raise ReportFailure("PDF 关闭来源展示后仍出现数据来源内容")
        if "[[claim:" in extracted_text or "[[table:" in extracted_text:
            raise ReportFailure("PDF 不应显示数据来源协议标记")
        knowledge = trace.get('knowledge', []) if isinstance(trace, dict) else []
        knowledge_present = render.get('knowledgeSourceAppendixPresent', False)
        compact = re.sub(r'\s+', '', extracted_text)
        if sources_enabled:
            if knowledge_present is not bool(knowledge) or (knowledge and '业务知识来源' not in compact):
                raise ReportFailure('PDF 业务知识来源附录不完整')
            for number, item in enumerate(knowledge, 1):
                expected = [f'[知识来源{number:03d}]', *item['summary']]
                if any(re.sub(r'\s+', '', text) not in compact for text in expected):
                    raise ReportFailure('PDF 业务知识来源编号或原文摘要不完整')
        elif knowledge_present is not False or '业务知识来源' in compact or '[知识来源' in compact:
            raise ReportFailure('PDF 关闭来源展示后仍出现业务知识来源')

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
        source_display_enabled = render.get("exportSettings", {}).get("sources", False)
        invalid_presentation = (
            len(citation_ids) != len(citations)
            or not isinstance(presentations, list)
            or len(presentations) != len(citation_ids)
            or {item.get("citationId") for item in presentations if isinstance(item, dict)}
            != set(citation_ids)
            or any(
                not isinstance(item, dict)
                or item.get("alias") != f"[来源 {index:03d}]"
                or not isinstance(item.get("label"), str)
                for index, item in enumerate(presentations, start=1)
            )
        )
        if source_display_enabled:
            invalid_visibility = (
                isinstance(presentations, list)
                and any(item["alias"] not in extracted_text for item in presentations)
            ) or (
                bool(citation_ids) and "实际引用附录" not in extracted_text
            ) or render.get("citationAppendixPresent") is not bool(citation_ids)
        else:
            invalid_visibility = (
                isinstance(presentations, list)
                and any(item["alias"] in extracted_text for item in presentations)
            ) or "实际引用附录" in extracted_text or render.get(
                "citationAppendixPresent"
            ) is not False
        if invalid_presentation or invalid_visibility or "[[citation:" in extracted_text:
            raise ReportFailure("PDF 来源编号或实际引用附录不完整")
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
