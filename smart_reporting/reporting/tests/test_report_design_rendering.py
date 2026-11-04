"""展示设计驱动真实双格式产物，业务事实仍由原文档契约绑定。"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pypdf
import pytest
from docx import Document
from docx.shared import Pt
from lxml import etree

from smart_reporting.reporting.delivery.report_design import ReportDesign
from smart_reporting.reporting.delivery.report_runtime.docx import _postprocess_docx
from smart_reporting.reporting.delivery.report_runtime.pdf import DEFAULT_PAGE_LAYOUT
from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime
from smart_reporting.reporting.delivery.report_runtime.validation import ReportFailure

from .test_report_runtime import _docx_postprocess_context, _docx_postprocess_fixture
from .test_report_runtime_full_render import _DEPENDENCIES_OK, _SKIP_REASON, _build_workspace


def test_partial_cover_design_preserves_role_defaults() -> None:
    design = ReportDesign.model_validate({"cover": {"title": {"text": "展示标题"}, "period": {"text": "展示期间"}}})
    assert design.cover.title.size == 28
    assert design.cover.title.y == 65
    assert design.cover.period.y == 140
    assert design.cover.period.size == 13


def test_compact_design_roundtrip_preserves_overrides_equal_to_generic_defaults() -> None:
    design = ReportDesign.model_validate({"cover": {"title": {"bold": False, "size": 11, "y": 70}}, "typography": {"body": {"font": "sans"}, "h1": {"bold": False}}})
    assert ReportDesign.model_validate(design.compact()) == design
    assert ReportDesign().compact() == {}


def test_word_caption_design_formats_visible_caption(tmp_path: Path) -> None:
    import docx

    path = tmp_path / "caption.docx"
    document = _docx_postprocess_fixture(docx)
    document.add_paragraph("图表：测试图注")
    document.save(path)
    design = ReportDesign.model_validate({"typography": {"caption": {"size": 8, "font": "serif", "color": "#123456", "spaceAfter": 12}}})
    _postprocess_docx(path, context=_docx_postprocess_context(), layout=DEFAULT_PAGE_LAYOUT, design=design, caption_texts={"图表：测试图注"})
    paragraph = Document(path).paragraphs[-1]
    assert paragraph.style.name == "Caption"
    assert paragraph.runs[0].font.size == Pt(8)
    assert str(paragraph.runs[0].font.color.rgb) == "123456"
    assert paragraph.style.paragraph_format.space_after == Pt(12)


def test_word_summary_title_follows_heading_design_without_direct_bold(tmp_path: Path) -> None:
    import docx

    path = tmp_path / "summary.docx"
    document = _docx_postprocess_fixture(docx)
    document.add_paragraph().add_run("核心结论").bold = True
    document.save(path)
    design = ReportDesign.model_validate({"typography": {"h1": {"size": 21, "bold": False}}})
    _postprocess_docx(path, context=_docx_postprocess_context(), layout=DEFAULT_PAGE_LAYOUT, design=design)
    title = next(item for item in Document(path).paragraphs if item.text == "核心结论")
    assert title.style.font.size == Pt(21)
    assert title.runs[0].bold is False


def test_word_design_keeps_cover_text_editable_at_page_coordinates(tmp_path: Path) -> None:
    import docx

    path = tmp_path / "report.docx"
    _docx_postprocess_fixture(docx).save(path)
    design = ReportDesign.model_validate({
        "cover": {"title": {"text": "展示标题", "x": 31, "y": 52, "width": 145, "height": 45,
                               "font": "serif", "size": 24, "color": "#225588", "align": "left"}},
        "typography": {"body": {"size": 12, "lineHeight": 1.8, "indent": 24},
                       "h2": {"size": 15, "spaceBefore": 18}},
        "watermark": {"enabled": False},
    })
    design.typography.h1.size = 20
    design.typography.h1.color = "#332211"
    _postprocess_docx(path, context=_docx_postprocess_context(), layout=DEFAULT_PAGE_LAYOUT, design=design)

    with zipfile.ZipFile(path) as package:
        xml = etree.fromstring(package.read("word/document.xml"))
        namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main", "v": "urn:schemas-microsoft-com:vml"}
        shape = xml.xpath("//v:shape[w:txbxContent or v:textbox/w:txbxContent][.//w:t='展示标题']", namespaces=namespaces)
        assert len(shape) == 1
        assert "margin-left:31mm" in shape[0].get("style")
        assert "margin-top:52mm" in shape[0].get("style")
        assert "mso-position-horizontal-relative:page" in shape[0].get("style")
        assert not [name for name in package.namelist() if name.startswith("word/media/")]
        assert all(b"PowerPlusWaterMarkObject" not in package.read(name) for name in package.namelist() if name.startswith("word/header"))
    styles = Document(path).styles
    assert styles["Report Source Appendix"].font.size == Pt(20)
    assert str(styles["Report Source Appendix"].font.color.rgb) == "332211"
    assert styles["Normal"].font.size == Pt(12)
    assert styles["Normal"].paragraph_format.line_spacing == 1.8
    assert styles["Normal"].paragraph_format.first_line_indent == Pt(24)
    assert styles["Heading 2"].font.size == Pt(15)
    assert styles["Heading 2"].paragraph_format.space_before == Pt(18)


@pytest.mark.skipif(not _DEPENDENCIES_OK, reason=_SKIP_REASON)
@pytest.mark.parametrize("hidden", [False, True])
def test_design_real_export_uses_visible_cover_and_independent_watermark(tmp_path: Path, hidden: bool) -> None:
    workspace = tmp_path / "workspace"
    state = _build_workspace(workspace)
    state.pop("_editorExportSettings")
    state["_reportDesign"] = {
        "options": {"toc": False, "headerFooter": False, "pageNumbers": False},
        "cover": {"title": {"text": "自定义展示标题", "visible": not hidden, "x": 30, "y": 45, "width": 150, "height": 60},
                  "period": {"text": "展示期间文本", "visible": not hidden},
                  "showOrganization": False, "showGeneratedBy": False, "showDate": False},
        "watermark": {"enabled": not hidden, "text": "设计专用水印", "cover": True,
                      "placement": "tile", "font": "serif", "angle": -20, "opacity": 0.15, "size": 19},
        "typography": {"body": {"size": 12, "font": "serif", "lineHeight": 1.7}, "table": {"size": 10}},
    }
    result = ReportRuntime(workspace).render_markdown(state, "report.md", "out/report.pdf", ".reporting-tmp/workspace-report-design-render/render.pdf")
    assert result["status"] == "rendered"
    assert ReportDesign.model_validate(result["render"]["reportDesign"]).watermark.enabled is (not hidden)
    assert result["render"]["documentContext"]["title"] == "智能运营全链路渲染验证报告"
    pdf = pypdf.PdfReader(workspace / "out/report.pdf")
    cover = "".join((pdf.pages[0].extract_text() or "").split())
    assert ("自定义展示标题" in cover) is (not hidden)
    assert ("展示期间文本" in cover) is (not hidden)
    assert "ReportingAgent" not in cover
    assert "营业收入" in "".join(page.extract_text() or "" for page in pdf.pages)
    assert all(("设计专用水印" in "".join((page.extract_text() or "").split())) is (not hidden) for page in pdf.pages)

    converted = tmp_path / "converted"
    converted.mkdir()
    subprocess.run([shutil.which("soffice"), "--headless", f"-env:UserInstallation={(tmp_path / 'profile').as_uri()}", "--convert-to", "pdf", "--outdir", str(converted), str(workspace / "out/report.docx")], check=True, capture_output=True, timeout=60)
    word_pdf = pypdf.PdfReader(converted / "report.pdf")
    word_cover = "".join((word_pdf.pages[0].extract_text() or "").split())
    assert ("自定义展示标题" in word_cover) is (not hidden)
    assert ("展示期间文本" in word_cover) is (not hidden)
    assert "ReportingAgent" not in word_cover
    # WordArt 经 LibreOffice 转为矢量轮廓，文本层不再包含字串；独立栅格检查水印区域。
    subprocess.run(["pdftoppm", "-f", "1", "-l", "1", "-scale-to", "900", "-png", "-singlefile", str(converted / "report.pdf"), str(converted / "cover")], check=True, capture_output=True, timeout=30)
    from PIL import Image

    with Image.open(converted / "cover.png") as image:
        width, height = image.size
        histogram = image.convert("L").crop((0, round(height * .6), width, round(height * .9))).histogram()
        assert (sum(histogram[:245]) > 100) is (not hidden)


def test_display_title_cannot_replace_bound_markdown_fact(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state = _build_workspace(workspace)
    state["_reportDesign"] = {"cover": {"title": {"text": "展示标题"}}}
    (workspace / "report.md").write_text((workspace / "report.md").read_text().replace("# 智能运营全链路渲染验证报告", "# 展示标题"))
    with pytest.raises(ReportFailure, match="Markdown 标题与服务端文档展示契约不一致"):
        ReportRuntime(workspace).render_markdown(state, "report.md", "out/report.pdf", ".reporting-tmp/workspace-report-design-fact/render.pdf")


def test_cover_layout_reports_clipping_and_overlap_from_actual_typesetting():
    from weasyprint import HTML

    from smart_reporting.reporting.delivery.report_runtime.design import (
        cover_html,
        cover_layout_issues,
        design_css,
    )
    design = ReportDesign()
    design.cover.title.text = "长中文封面标题" * 30
    design.cover.title.height = 10
    design.cover.period.y = 65
    context = _docx_postprocess_context()
    document = HTML(string="<style>@page{size:A4;margin:0}" + design_css(design) + "</style>" + cover_html(design, context)).render()
    issues = cover_layout_issues(document.pages, design)
    assert any(item["code"] == "report_cover_text_overflow" and "标题" in item["message"] for item in issues)
    assert any(item["code"] == "report_cover_overlap" for item in issues)
    design.options.cover = False
    assert cover_layout_issues(document.pages, design) == []
