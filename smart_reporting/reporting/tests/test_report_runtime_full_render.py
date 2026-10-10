"""全链路真实渲染冒烟测试。

不 mock 任何渲染环节：真实 WeasyPrint 渲染 PDF、pypdf 校验页数、
pypdf 页面装饰合并，以及 pandoc（缺失时 LibreOffice）Word 转换与
python-docx 结构校验。仅在本地依赖齐备时运行，离线、确定性输入。

此前真实探针已验证同一调用形态可产出 status=rendered、pageCount=1；
本文件把该探针固化为永久回归，并补充图文 + 封面/目录开启的富场景，
不弱化任何断言。
"""

from __future__ import annotations

import copy
import hashlib
import shutil
from pathlib import Path
from typing import Any

import pytest

from smart_reporting.reporting.delivery.report_runtime.markdown import format_heading_label
from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime

_TEMPORARY_PDF_PATH = ".reporting-tmp/workspace-report-full-render/render.pdf"


def _render_dependencies_available() -> tuple[bool, str]:
    missing = [name for name in ("pandoc", "soffice") if shutil.which(name) is None]
    if missing:
        return False, f"full render requires local commands: {', '.join(missing)}"
    try:
        import weasyprint  # noqa: F401
    except Exception as error:  # pragma: no cover - 环境相关
        return False, f"WeasyPrint 不可用: {error}"
    return True, ""


_DEPENDENCIES_OK, _SKIP_REASON = _render_dependencies_available()

pytestmark = pytest.mark.skipif(not _DEPENDENCIES_OK, reason=_SKIP_REASON)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _build_workspace(workspace: Path) -> dict[str, Any]:
    """构造离线、确定性的工作区，并返回哈希绑定的渲染状态。"""

    (workspace / "data").mkdir(parents=True)
    csv_path = workspace / "data" / "overview.csv"
    csv_path.write_text(
        "metric,value,unit,yoy\n"
        "营业收入,128.50,亿元,+8.6%\n"
        "经营现金流,32.10,亿元,+3.2%\n"
        "综合毛利率,41.8,%,+1.1pct\n",
        encoding="utf-8",
    )

    (workspace / "report.md").write_text(
        "# 智能运营全链路渲染验证报告\n"
        "\n"
        "[[section:overview]]\n"
        "\n"
        "## 1. 经营概览\n"
        "\n"
        "本节基于工作区内哈希绑定的 CSV 源数据完成端到端渲染验证，覆盖真实\n"
        "WeasyPrint PDF 渲染、pypdf 页面校验与 pandoc Word 转换链路。\n"
        "\n"
        "报告期内核心指标保持平稳：营业收入 **128.50 亿元**，同比增长 8.6%"
        "[[citation:citation_001]]。\n"
        "\n"
        "| 指标 | 本期 | 同比 |\n"
        "| --- | ---: | ---: |\n"
        "| 营业收入 | 128.50 亿元 | +8.6% |\n"
        "| 经营现金流 | 32.10 亿元 | +3.2% |\n"
        "| 综合毛利率 | 41.8% | +1.1pct |\n"
        "\n"
        "- PDF 与 Word 产物由同一份语义文档生成，标题编号与目录锚点一致。\n"
        "- 页眉、页脚与水印在发布前合并到 PDF 页面上。\n"
        "\n"
        "门诊收入持续增长\n"
        "住院收入有所回落。\n"
        "\n"
        "> 备注：本报告由 Reporting Workflow 在受限运行时内自动生成，封面与目录已按导出设置关闭。\n",
        encoding="utf-8",
    )

    return {
        "jobId": "job-full-render-smoke",
        "sources": [
            {
                "path": "data/overview.csv",
                "size": csv_path.stat().st_size,
                "sha256": _sha256_file(csv_path),
            }
        ],
        "_documentContext": {
            "title": "智能运营全链路渲染验证报告",
            "periodLabel": "2026 年",
            "organizationName": "智能运营验证机构",
            "generatedByLabel": "Reporting Agent",
            "watermarkText": "内部资料",
            "generatedDate": "2026-09-30",
            "sectionNumbers": ["1"],
            "sections": [{"code": "overview", "sectionNumber": "1", "title": "经营概览"}],
            "headingNumbers": [
                {
                    "level": 2,
                    "number": "1",
                    "title": "经营概览",
                    "sectionCode": "overview",
                    "anchor": "report-section-overview",
                }
            ],
        },
        # 与已验证探针一致：关闭封面与目录，正文从第 1 页直接开始。
        "_editorExportSettings": {"cover": False, "toc": False},
        "_citationPresentations": [
            {
                "citationId": "citation_001",
                "label": "集团医院营业收入按月汇总冻结数据长中文业务名称",
                "coverageItems": [
                    {"label": "营业收入明细", "periods": ["2026-01", "2026-12"]}
                ],
            }
        ],
    }


def test_render_markdown_full_runtime_publishes_hash_verified_pdf_and_docx(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    state = _build_workspace(workspace)

    try:
        result = ReportRuntime(workspace).render_markdown(
            state,
            "report.md",
            "out/report.pdf",
            _TEMPORARY_PDF_PATH,
        )
        # 运行时必须在返回前删除进程私有临时目录。
        assert not (workspace / _TEMPORARY_PDF_PATH).exists()
    finally:
        shutil.rmtree(workspace / ".reporting-tmp", ignore_errors=True)

    assert result["status"] == "rendered"
    assert result["jobId"] == "job-full-render-smoke"
    assert result["markdownPath"] == "report.md"
    assert result["pdfPath"] == "out/report.pdf"
    assert result["wordPath"] == "out/report.docx"
    assert result["imageCount"] == 0
    assert result["pageCount"] >= 1

    # 导出设置按服务端契约回显。
    assert result["render"]["exportSettings"] == {
        "cover": False,
        "toc": False,
        "headerFooter": True,
        "pageNumbers": True,
        "sources": True,
    }

    # PDF 产物存在且与返回身份逐字节一致。
    pdf_path = workspace / "out" / "report.pdf"
    assert pdf_path.is_file()
    pdf_bytes = pdf_path.read_bytes()
    assert pdf_bytes.startswith(b"%PDF")
    assert result["size"] == len(pdf_bytes) == result["render"]["pdf"]["size"]
    assert _sha256_bytes(pdf_bytes) == result["render"]["pdf"]["sha256"]
    assert result["render"]["pdf"]["path"] == "out/report.pdf"
    assert result["render"]["citationAppendixPresent"] is True

    # Word 产物存在且与返回身份逐字节一致。
    docx_path = workspace / "out" / "report.docx"
    assert docx_path.is_file()
    docx_bytes = docx_path.read_bytes()
    assert docx_bytes.startswith(b"PK")
    assert result["wordSize"] == len(docx_bytes) == result["render"]["word"]["size"]
    assert _sha256_bytes(docx_bytes) == result["render"]["word"]["sha256"]
    assert result["render"]["word"]["path"] == "out/report.docx"

    import pypdf
    from docx import Document

    pdf_text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(pdf_path).pages)
    word_text = "\n".join(paragraph.text for paragraph in Document(docx_path).paragraphs)
    for rendered_text in (pdf_text, word_text):
        assert "[来源 001]" in rendered_text
        assert "实际引用附录" in rendered_text
        assert "营业收入明细（2026年1月、2026年12月）" in rendered_text
        # 中文之间的段内换行不能渲染成空格。
        assert "门诊收入持续增长住院收入有所回落。" in rendered_text

    # 源 Markdown 的产物身份同样与磁盘内容一致，且未混入图片产物。
    assert result["render"]["images"] == []
    assert result["render"]["markdown"] == {
        "path": "report.md",
        "size": (workspace / "report.md").stat().st_size,
        "sha256": _sha256_file(workspace / "report.md"),
    }


def test_render_markdown_can_hide_source_appendix_without_losing_render(
    tmp_path: Path,
) -> None:
    import pypdf
    from docx import Document

    workspace = tmp_path / "workspace"
    state = _build_workspace(workspace)
    state["_editorExportSettings"] = {
        "cover": False,
        "toc": False,
        "sources": False,
    }
    result = ReportRuntime(workspace).render_markdown(
        state,
        "report.md",
        "out/report.pdf",
        ".reporting-tmp/workspace-report-no-source-render/render.pdf",
    )

    assert result["render"]["citationAppendixPresent"] is False
    assert result["render"]["citationPresentations"][0]["citationId"] == "citation_001"
    pdf_text = "\n".join(
        page.extract_text() or ""
        for page in pypdf.PdfReader(workspace / "out/report.pdf").pages
    )
    word_text = "\n".join(
        paragraph.text
        for paragraph in Document(workspace / "out/report.docx").paragraphs
    )
    for rendered_text in (pdf_text, word_text):
        assert "[来源 001]" not in rendered_text
        assert "实际引用附录" not in rendered_text


_IMAGE_RENDER_TEMPORARY_PDF_PATH = (
    ".reporting-tmp/workspace-report-full-image-render/render.pdf"
)


def _build_image_workspace(workspace: Path) -> dict[str, Any]:
    """构造图文 + 封面/目录开启的工作区，返回哈希绑定的渲染状态。

    采用编辑器导出的真实目录形态（见 test_report_runtime.py 的图片绑定
    契约）：草稿位于 ``reports/r1/revision-1/draft/``，图片仍在报告根目录
    ``reports/r1/chart.png``。Markdown 里的相对 src 从草稿目录解析不到
    图片，必须经渲染清单（``render.images``）唯一定位后内联进 PDF 与 Word。
    """

    from PIL import Image, ImageDraw, ImageFont

    (workspace / "data").mkdir(parents=True)
    csv_path = workspace / "data" / "overview.csv"
    csv_path.write_text(
        "metric,value,unit,yoy\n"
        "营业收入,128.50,亿元,+8.6%\n"
        "经营现金流,32.10,亿元,+3.2%\n"
        "综合毛利率,41.8,%,+1.1pct\n",
        encoding="utf-8",
    )

    chart_path = workspace / "reports" / "r1" / "chart.png"
    chart_path.parent.mkdir(parents=True)
    chart = Image.new("RGB", (960, 400), "white")
    draw = ImageDraw.Draw(chart)
    font = ImageFont.load_default(size=24)
    draw.text((30, 20), "Operating metrics (CNY 100 million)", fill="#222222", font=font)
    for tick in range(0, 141, 20):
        x = 270 + tick * 4
        draw.line((x, 85, x, 310), fill="#dddddd", width=2)
        draw.text((x - 10, 325), str(tick), fill="#444444", font=font)
    for label, value, y, color in (
        ("Revenue", 128.50, 110, "#247e91"),
        ("Operating cash flow", 32.10, 220, "#b75468"),
    ):
        draw.text((30, y + 15), label, fill="#222222", font=font)
        draw.rectangle((270, y, 270 + value * 4, y + 60), fill=color)
        draw.text((280 + value * 4, y + 15), f"{value:.2f}", fill="#222222", font=font)
    chart.save(chart_path)

    draft_path = workspace / "reports" / "r1" / "revision-1" / "draft" / "report.md"
    draft_path.parent.mkdir(parents=True)
    draft_path.write_text(
        "# 智能运营图文渲染验证报告\n"
        "\n"
        "[[section:overview]]\n"
        "\n"
        "## 1. 经营概览\n"
        "\n"
        "本节验证封面与目录开启时的真实渲染链路：图片经渲染清单绑定后内联进\n"
        "PDF 与 Word，claim 协议标记只用于血缘定位，不得进入成品。\n"
        "报告期内营业收入保持平稳。[[claim:smoke-claim-1]]\n"
        "\n"
        "![核心指标对比](chart.png)\n"
        "\n"
        "*图表：核心指标对比*\n"
        "\n"
        "报告期内核心指标保持平稳：营业收入 **128.50 亿元**，同比增长 8.6%。\n"
        "\n"
        "| 指标 | 本期 | 同比 |\n"
        "| --- | ---: | ---: |\n"
        "| 营业收入 | 128.50 亿元 | +8.6% |\n"
        "| 经营现金流 | 32.10 亿元 | +3.2% |\n"
        "\n"
        "> 备注：封面与目录已按导出设置开启，标题编号与目录锚点保持一致。\n",
        encoding="utf-8",
    )

    return {
        "jobId": "job-full-render-image",
        "sources": [
            {
                "path": "data/overview.csv",
                "size": csv_path.stat().st_size,
                "sha256": _sha256_file(csv_path),
            }
        ],
        # 渲染清单提供工作区相对路径，供草稿目录相对解析失败时唯一定位。
        "render": {"images": [{"path": "reports/r1/chart.png"}]},
        "_documentContext": {
            "title": "智能运营图文渲染验证报告",
            "periodLabel": "2026 年",
            "organizationName": "智能运营验证机构",
            "generatedByLabel": "Reporting Agent",
            "watermarkText": "内部资料",
            "generatedDate": "2026-09-30",
            "sectionNumbers": ["1"],
            "sections": [{"code": "overview", "sectionNumber": "1", "title": "经营概览"}],
            "headingNumbers": [
                {
                    "level": 2,
                    "number": "1",
                    "title": "经营概览",
                    "sectionCode": "overview",
                    "anchor": "report-section-overview",
                }
            ],
        },
        # 与编辑器导出一致：封面与目录开启，正文自目录之后开始。
        "_editorExportSettings": {"cover": True, "toc": True},
    }


def test_render_markdown_full_runtime_binds_image_with_cover_and_toc(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    state = _build_image_workspace(workspace)

    try:
        result = ReportRuntime(workspace).render_markdown(
            state,
            "reports/r1/revision-1/draft/report.md",
            "reports/r1/revision-1/report.pdf",
            _IMAGE_RENDER_TEMPORARY_PDF_PATH,
        )
        # 运行时必须在返回前删除进程私有临时目录。
        assert not (workspace / _IMAGE_RENDER_TEMPORARY_PDF_PATH).exists()
    finally:
        shutil.rmtree(workspace / ".reporting-tmp", ignore_errors=True)

    assert result["status"] == "rendered"
    assert result["jobId"] == "job-full-render-image"
    assert result["markdownPath"] == "reports/r1/revision-1/draft/report.md"
    assert result["pdfPath"] == "reports/r1/revision-1/report.pdf"
    assert result["wordPath"] == "reports/r1/revision-1/report.docx"
    assert result["imageCount"] == 1
    # 封面与目录各占独立页面，正文另起一页，因此至少 2 页。
    assert result["pageCount"] >= 2

    # 导出设置按服务端契约回显：封面与目录开启。
    assert result["render"]["exportSettings"] == {
        "cover": True,
        "toc": True,
        "headerFooter": True,
        "pageNumbers": True,
        "sources": True,
    }

    # 标题编号契约：目录与正文共用 format_heading_label 的精确文本，锚点规范。
    heading_label = format_heading_label(level=2, number="1", title="经营概览")
    assert heading_label == "1. 经营概览"
    heading = result["render"]["documentContext"]["headingNumbers"][0]
    assert heading["anchor"] == "report-section-overview"

    # 图片按渲染清单绑定并登记为产物，身份与磁盘内容逐字节一致。
    chart_path = workspace / "reports" / "r1" / "chart.png"
    assert result["render"]["images"] == [
        {
            "path": "reports/r1/chart.png",
            "size": chart_path.stat().st_size,
            "sha256": _sha256_file(chart_path),
        }
    ]

    # PDF 产物存在，返回身份与磁盘字节的独立重算逐字节一致。
    pdf_path = workspace / "reports" / "r1" / "revision-1" / "report.pdf"
    assert pdf_path.is_file()
    pdf_bytes = pdf_path.read_bytes()
    assert pdf_bytes.startswith(b"%PDF")
    assert result["size"] == len(pdf_bytes) == result["render"]["pdf"]["size"]
    assert _sha256_bytes(pdf_bytes) == result["render"]["pdf"]["sha256"]
    assert result["render"]["pdf"]["path"] == "reports/r1/revision-1/report.pdf"

    # Word 产物存在，图片真实嵌入且目录结构完整。
    docx_path = workspace / "reports" / "r1" / "revision-1" / "report.docx"
    assert docx_path.is_file()
    docx_bytes = docx_path.read_bytes()
    assert docx_bytes.startswith(b"PK")
    assert result["wordSize"] == len(docx_bytes) == result["render"]["word"]["size"]
    assert _sha256_bytes(docx_bytes) == result["render"]["word"]["sha256"]
    word_structure = result["render"]["wordStructure"]
    assert word_structure["embeddedImageCount"] == 1
    assert word_structure["tocEntryCount"] == 1
    assert word_structure["nativeTocPresent"] is True
    # 封面、目录、正文各成一个分节。
    assert word_structure["sectionCount"] == 3

    from docx import Document

    picture = Document(docx_path).inline_shapes[0]
    assert picture.width / picture.height == pytest.approx(960 / 400, rel=0.01)

    # 真实 PDF 文本抽取：机器协议标记不泄露，封面/目录/正文语义可见。
    import pypdf

    reader = pypdf.PdfReader(str(pdf_path))
    pages_text = [page.extract_text() or "" for page in reader.pages]
    extracted = "\n".join(pages_text)
    assert len(pages_text) == result["pageCount"]
    assert "[[claim:" not in extracted
    assert "[[section:" not in extracted
    assert heading_label in extracted
    assert "目录" in extracted
    cover_compact = "".join(pages_text[0].split())
    assert "智能运营图文渲染验证报告" in cover_compact


_TRACE_APPENDIX_TEMPORARY_PDF_PATH = (
    ".reporting-tmp/workspace-report-trace-appendix-render/render.pdf"
)
_TRACE_BASE_URL = "https://reports.example.com/reports/v1/editor/report-1/2"


def _trace_links(subject_id: str) -> list[dict[str, str]]:
    return [
        {"subjectId": subject_id, "url": f"{_TRACE_BASE_URL}?subject={subject_id}"}
    ]


def _build_trace_appendix_workspace(workspace: Path) -> dict[str, Any]:
    """B8 双格式验收样本：claim 复用编号、表格、静态图与多 CSV 长中文名。

    正文锚点顺序：claim（两次复用）→ 图表 → 第二个 claim → 表格；
    未在正文出现的 unbound claim 排在全部锚点之后。封面与目录关闭，
    让文本抽取直接从正文开始。
    """
    from PIL import Image

    (workspace / "data").mkdir(parents=True)
    overview_csv = workspace / "data" / "overview.csv"
    overview_csv.write_text(
        "period,revenue\n2025-09,3600\n2025-08,3000\n", encoding="utf-8"
    )
    detail_csv = workspace / "data" / "detail.csv"
    detail_csv.write_text(
        "period,visits\n2025-09,30\n", encoding="utf-8"
    )
    chart_path = workspace / "reports" / "r1" / "chart.png"
    chart_path.parent.mkdir(parents=True)
    Image.new("RGB", (4, 4), "red").save(chart_path)

    draft_path = workspace / "reports" / "r1" / "revision-1" / "draft" / "report.md"
    draft_path.parent.mkdir(parents=True)
    draft_path.write_text(
        "# 数据来源追溯双格式验收报告\n"
        "\n"
        "[[section:overview]]\n"
        "\n"
        "## 1. 经营概览\n"
        "\n"
        "本期营业收入 3,600 万元[[claim:claim-rev]]，与上月口径一致[[claim:claim-rev]]。\n"
        "\n"
        "![核心指标趋势](chart.png)\n"
        "\n"
        "*图表：核心指标趋势示意*\n"
        "\n"
        "次均收入 120 元[[claim:claim-stale]]。\n"
        "\n"
        "[[table:tbl-1]]\n"
        "| 指标 | 本期 |\n"
        "| --- | ---: |\n"
        "| 营业收入 | 3,600 万元 |\n"
        "[[/table:tbl-1]]\n",
        encoding="utf-8",
    )
    subject_rev = "sub-" + "0" * 16
    subject_stale = "sub-" + "1" * 16
    return {
        "jobId": "job-full-render-trace-appendix",
        "sources": [
            {
                "path": "data/overview.csv",
                "size": overview_csv.stat().st_size,
                "sha256": _sha256_file(overview_csv),
            },
            {
                "path": "data/detail.csv",
                "size": detail_csv.stat().st_size,
                "sha256": _sha256_file(detail_csv),
            },
        ],
        "render": {"images": [{"path": "reports/r1/chart.png"}]},
        "_documentContext": {
            "title": "数据来源追溯双格式验收报告",
            "periodLabel": "2025 年 9 月",
            "organizationName": "智能运营验证机构",
            "generatedByLabel": "Reporting Agent",
            "watermarkText": "内部资料",
            "generatedDate": "2026-09-30",
            "sectionNumbers": ["1"],
            "sections": [{"code": "overview", "sectionNumber": "1", "title": "经营概览"}],
            "headingNumbers": [
                {
                    "level": 2,
                    "number": "1",
                    "title": "经营概览",
                    "sectionCode": "overview",
                    "anchor": "report-section-overview",
                }
            ],
        },
        "_editorExportSettings": {"cover": False, "toc": False},
        "_traceSourcePresentations": {
            "claims": [
                {
                    "claimId": "claim-rev",
                    "subjectIds": [subject_rev],
                    "status": "valid",
                    "factValue": 3600.0,
                    "unit": "万元",
                    "periods": ["2025-09", "2025-08"],
                    "formula": "sum(revenue)",
                    "scope": {"院区": "全部院区"},
                    "datasetIds": ["dataset-overview"],
                    "links": _trace_links(subject_rev),
                },
                {
                    "claimId": "claim-stale",
                    "subjectIds": [subject_stale],
                    "status": "stale",
                    "factValue": 120.0,
                    "unit": "元",
                    "periods": ["2025-09"],
                    "formula": "sum(revenue)/sum(visits)",
                    "scope": {},
                    "datasetIds": ["dataset-overview", "dataset-detail"],
                    "links": _trace_links(subject_stale),
                },
                {
                    "claimId": "claim-unbound",
                    "subjectIds": [],
                    "status": "unbound",
                    "factValue": None,
                    "unit": None,
                    "periods": [],
                    "formula": None,
                    "scope": {},
                    "datasetIds": [],
                    "links": [],
                },
            ],
            "tables": [
                {
                    "tableId": "tbl-1",
                    "subjectIds": [],
                    "status": "stale",
                    "datasetIds": ["dataset-overview"],
                    "methods": ["环比聚合"],
                    "links": [],
                }
            ],
            "charts": [
                {
                    "chartId": "chart_001",
                    "subjectIds": [],
                    "status": "valid",
                    "imagePath": "reports/r1/chart.png",
                    "datasetIds": ["dataset-overview"],
                    "methods": [],
                    "transformNotes": ["按期间升序排序"],
                    "unit": "元",
                    "links": [],
                }
            ],
            "datasets": {
                "dataset-overview": {
                    "filename": "收入明细.csv",
                    "businessLabel": "集团医院营业收入按月汇总冻结数据长中文业务名称",
                    "periodRoles": ["current", "mom"],
                },
                "dataset-detail": {
                    "filename": (
                        "超长中文文件名用于验证附录换行与截断场景的明细数据导出.csv"
                    ),
                    "businessLabel": None,
                    "periodRoles": ["current"],
                },
            },
        },
    }


def test_render_markdown_publishes_trace_source_appendix_in_pdf_and_word(
    tmp_path: Path,
) -> None:
    import pypdf
    from docx import Document

    workspace = tmp_path / "workspace"
    state = _build_trace_appendix_workspace(workspace)
    try:
        result = ReportRuntime(workspace).render_markdown(
            state,
            "reports/r1/revision-1/draft/report.md",
            "reports/r1/revision-1/report.pdf",
            _TRACE_APPENDIX_TEMPORARY_PDF_PATH,
        )
        assert not (workspace / _TRACE_APPENDIX_TEMPORARY_PDF_PATH).exists()
    finally:
        shutil.rmtree(workspace / ".reporting-tmp", ignore_errors=True)

    assert result["status"] == "rendered"
    assert result["render"]["traceSourceAppendixPresent"] is True
    entries = result["render"]["traceSourcePresentations"]["entries"]
    assert [(item["kind"], item["alias"]) for item in entries] == [
        ("claim", "[数据来源 001]"),
        ("chart", "[数据来源 002]"),
        ("claim", "[数据来源 003]"),
        ("table", "[数据来源 004]"),
        ("claim", "[数据来源 005]"),
    ]

    pdf_path = workspace / "reports" / "r1" / "revision-1" / "report.pdf"
    docx_path = workspace / "reports" / "r1" / "revision-1" / "report.docx"
    pdf_text = "\n".join(
        page.extract_text() or "" for page in pypdf.PdfReader(pdf_path).pages
    )
    word_text = "\n".join(
        paragraph.text for paragraph in Document(docx_path).paragraphs
    )
    for rendered_text in (pdf_text, word_text):
        # 编号按首次出现顺序：claim 两次复用、图表、claim、表格、未绑定 claim。
        assert rendered_text.count("[数据来源 001]") >= 3
        for alias in (
            "[数据来源 002]",
            "[数据来源 003]",
            "[数据来源 004]",
            "[数据来源 005]",
        ):
            assert alias in rendered_text
        assert "数据来源附录" in rendered_text
        assert "[[claim:" not in rendered_text
        assert "[[table:" not in rendered_text

    # PDF 专属：图注编号、失效说明与摘要字段（长中文名业务标签）。
    assert "核心指标趋势示意 [数据来源 002]" in pdf_text
    assert "状态：待复核" in pdf_text
    assert "状态：未绑定" in pdf_text
    assert "状态：有效" in pdf_text
    assert "事实值：3,600万元" in pdf_text
    assert "期间：2025年9月、2025年8月" in pdf_text
    assert "范围：院区=全部院区" in pdf_text
    assert "方法：revenue 求和" in pdf_text
    assert "集团医院营业收入按月汇总冻结数据长中文业务名称" in pdf_text
    assert "超长中文文件名用于验证附录换行与截断场景的明细数据导出.csv" in pdf_text
    assert "未提供在线定位" in pdf_text

    # 在线定位 URL 不进入可见文本；PDF 以链接注解、Word 以外部超链接关系表达，
    # 两处都必须指向 report/revision/subject 且与载荷一致。
    import zipfile

    expected_url = f"{_TRACE_BASE_URL}?subject=sub-" + "0" * 16
    pdf_uris: list[str] = []
    for page in pypdf.PdfReader(pdf_path).pages:
        for annotation in page.get("/Annots") or ():
            link = annotation.get_object()
            if link.get("/Subtype") != "/Link":
                continue
            action = link.get("/A")
            if action is not None and action.get("/URI") is not None:
                pdf_uris.append(str(action["/URI"]))
    assert expected_url in pdf_uris
    with zipfile.ZipFile(docx_path) as package:
        word_rels = package.read("word/_rels/document.xml.rels").decode("utf-8")
    assert expected_url in word_rels
    assert result["render"]["wordStructure"]["externalRelationshipCount"] >= 1

    # Word 专属：附录标题成段并保留编号。
    assert any(
        paragraph.text.strip() == "数据来源附录"
        for paragraph in Document(docx_path).paragraphs
    )

    # 真实联合验收（pdftoppm + python-docx）：数据来源编号/附录与导出设置
    # 三者一致性由 validate_pdf 的 B8 门禁复核，任一缺失即失败。
    validating_state = {**state, "render": copy.deepcopy(result["render"])}
    validating_state["render"]["pdf"]["path"] = result["pdfPath"]
    validating_state["render"]["word"]["path"] = result["wordPath"]
    validation = ReportRuntime(workspace).validate_pdf(
        validating_state,
        result["pdfPath"],
        ".reporting-tmp/workspace-report-trace-appendix-validate",
        word_path=result["wordPath"],
    )
    assert validation["ok"] is True
    shutil.rmtree(workspace / ".reporting-tmp", ignore_errors=True)


def test_render_summary_omission_counts_are_visible_in_pdf_and_word(tmp_path: Path) -> None:
    import pypdf
    from docx import Document

    workspace = tmp_path / "workspace"
    state = _build_trace_appendix_workspace(workspace)
    sources = state["_traceSourcePresentations"]
    sources["claims"][0]["omittedCounts"] = {"datasetIds": 2, "subjectIds": 2, "links": 2}
    sources["tables"][0]["omittedCounts"] = {"datasetIds": 1, "methods": 2}
    sources["charts"][0]["omittedCounts"] = {"transformNotes": 2}
    before = copy.deepcopy(sources)
    result = ReportRuntime(workspace).render_markdown(state,
        "reports/r1/revision-1/draft/report.md", "reports/r1/revision-1/report.pdf",
        _TRACE_APPENDIX_TEMPORARY_PDF_PATH)
    assert result["status"] == "rendered"
    pdf_path = workspace / result["pdfPath"]
    docx_path = workspace / result["wordPath"]
    pdf_text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(pdf_path).pages)
    word_text = "\n".join(paragraph.text for paragraph in Document(docx_path).paragraphs)
    for text in (pdf_text, word_text):
        for note in ("源文件省略 2 项", "源文件省略 1 项", "方法省略 2 项",
            "转换说明省略 2 项", "在线定位省略 2 项", "完整登记见在线数据来源"):
            assert note in text
        assert "[数据来源 001]" in text
        assert "[数据来源 002]" in text
        assert "状态：待复核" in text
        assert "状态：未绑定" in text
    assert sources == before


def test_render_markdown_hides_trace_source_appendix_when_sources_disabled(
    tmp_path: Path,
) -> None:
    import pypdf
    from docx import Document

    workspace = tmp_path / "workspace"
    state = _build_trace_appendix_workspace(workspace)
    state["_editorExportSettings"] = {"cover": False, "toc": False, "sources": False}
    try:
        result = ReportRuntime(workspace).render_markdown(
            state,
            "reports/r1/revision-1/draft/report.md",
            "reports/r1/revision-1/report.pdf",
            _TRACE_APPENDIX_TEMPORARY_PDF_PATH,
        )
    finally:
        shutil.rmtree(workspace / ".reporting-tmp", ignore_errors=True)

    assert result["status"] == "rendered"
    assert result["render"]["traceSourceAppendixPresent"] is False
    assert result["render"]["traceSourcePresentations"]["entries"]

    pdf_path = workspace / "reports" / "r1" / "revision-1" / "report.pdf"
    docx_path = workspace / "reports" / "r1" / "revision-1" / "report.docx"
    pdf_text = "\n".join(
        page.extract_text() or "" for page in pypdf.PdfReader(pdf_path).pages
    )
    word_text = "\n".join(
        paragraph.text for paragraph in Document(docx_path).paragraphs
    )
    for rendered_text in (pdf_text, word_text):
        assert "[数据来源" not in rendered_text
        assert "数据来源附录" not in rendered_text
        assert "本期营业收入 3,600 万元" in rendered_text
