import base64
import json
import os
import re
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentos_dev.coding.reporting.delivery import report_runtime
from agentos_dev.coding.reporting.delivery.report_runtime import ReportFailure, ReportRuntime

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_sandbox_tools_提供智能报表所需命令和分析库():
    dockerfile = Path("docker/sandbox-tools/Dockerfile").read_text(encoding="utf-8")
    matplotlibrc = Path("docker/sandbox-tools/matplotlibrc").read_text(encoding="utf-8")

    assert "        bash \\\n" in dockerfile
    assert "        file \\\n" in dockerfile
    assert "        ripgrep \\\n" in dockerfile
    assert "command -v" in dockerfile and " file " in dockerfile and " rg " in dockerfile
    assert " pdftoppm " in dockerfile
    assert " pandoc " in dockerfile
    assert " libreoffice " in dockerfile
    assert " libreoffice-writer " in dockerfile
    assert " docx," in dockerfile
    assert "COPY docker/sandbox-tools/matplotlibrc /tmp/matplotlibrc" in dockerfile
    assert "font.sans-serif: Noto Sans CJK JP, DejaVu Sans" in matplotlibrc
    assert "axes.unicode_minus: False" in matplotlibrc
    for package in ("matplotlib", "pandas", "polars", "scipy", "seaborn", "skimage"):
        assert package in dockerfile


def test_pdf_资源边界为200mib和600秒动作预算():
    assert report_runtime.MAX_PDF_BYTES == 200 * 1024 * 1024
    assert report_runtime.MAX_PDF_PAGES == 200
    assert report_runtime.MAX_DOCX_BYTES == 200 * 1024 * 1024
    assert report_runtime.PDF_VALIDATION_TIMEOUT_SECONDS == 540
    assert report_runtime.DOCX_RENDER_TIMEOUT_SECONDS == 540
    assert report_runtime.DOCX_VALIDATION_TIMEOUT_SECONDS == 540


def test_pdf_markdown无citation时仍清理analysis协议标记():
    markdown = (
        "# 运营报告\n\n"
        "[[section:summary]]\n"
        "## 运营摘要\n\n"
        "本节仅登记分析绑定。[[analysis:analysis_001]]"
    )

    visible_markdown, presentations = report_runtime._pdf_markdown(markdown, None)

    assert presentations == []
    assert "[[analysis:" not in visible_markdown
    assert "[[section:" not in visible_markdown
    assert "[[analysis:analysis_001]]" in markdown


def test_封面目录和正文使用同一视觉主题():
    context = {
        "title": "运营报告",
        "periodLabel": "2025年",
        "organizationName": "测试机构",
        "generatedByLabel": "AI 平台生成",
        "watermarkText": "AI 平台生成",
        "generatedDate": "2026-08-07",
        "sections": [{"code": "summary", "title": "运营摘要"}],
    }

    pdf_document, _word_document = report_runtime._semantic_documents(
        "<h2 id='report-section-summary'>运营摘要</h2>",
        context=context,
        layout=dict(report_runtime.DEFAULT_PAGE_LAYOUT),
    )

    theme = report_runtime.REPORT_VISUAL_THEME
    assert f".report-cover h1{{color:{theme['primary']}" in pdf_document
    assert f".report-toc h1{{color:{theme['primary']}" in pdf_document
    assert f"h2{{color:{theme['primary']};border-left:3pt solid {theme['accent']}" in pdf_document
    assert f"th{{background:{theme['surface']};color:{theme['primary']}" in pdf_document


def test_科技蓝主题契约提供统一基础色和多系列图表调色板():
    theme = report_runtime.REPORT_VISUAL_THEME

    assert theme["name"] == "enterprise-tech-blue"
    assert theme["primary"] == "#0B4F8A"
    assert theme["accent"] == "#007EA7"
    assert theme["highlight"] == "#F2B134"
    assert theme["surface"] == "#EDF5FC"
    assert len(theme["chartPalette"]) == 8
    assert len(theme["chartPalette"]) == len(set(theme["chartPalette"]))
    assert theme["primary"] in theme["chartPalette"]
    assert theme["accent"] in theme["chartPalette"]


def test_word_渲染和验收命令缺失时失败关闭(tmp_path, monkeypatch):
    monkeypatch.setattr(report_runtime.shutil, "which", lambda _name: None)

    with pytest.raises(ReportFailure, match="Pandoc 不可用"):
        report_runtime._render_docx(
            "<p>report</p>",
            source_parent=tmp_path,
            output=tmp_path / "report.docx",
            context={},
            layout={},
        )
    with pytest.raises(ReportFailure, match="LibreOffice 不可用"):
        report_runtime._validate_docx_rendering(
            tmp_path / "report.docx",
            tmp_path / "validation",
            context={},
            layout={},
        )


def test_word_渲染和验收超时时失败关闭(tmp_path, monkeypatch):
    monkeypatch.setattr(report_runtime.shutil, "which", lambda name: f"/usr/bin/{name}")

    def timeout(command, *_args, **_kwargs):
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(report_runtime.subprocess, "run", timeout)

    with pytest.raises(ReportFailure, match="Word 渲染失败或超时"):
        report_runtime._render_docx(
            "<p>report</p>",
            source_parent=tmp_path,
            output=tmp_path / "report.docx",
            context={},
            layout={},
        )
    with pytest.raises(ReportFailure, match="Word 经 LibreOffice 转换失败或超时"):
        report_runtime._validate_docx_rendering(
            tmp_path / "report.docx",
            tmp_path / "validation",
            context={},
            layout={},
        )


@pytest.mark.parametrize(
    "member",
    [
        "word/vbaProject.bin",
        "word/embeddings/oleObject1.bin",
        "word/activeX/activeX1.bin",
    ],
)
def test_word_ooxml拒绝宏ole和activex(tmp_path, member):
    path = tmp_path / "report.docx"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr(member, b"forbidden")

    with pytest.raises(ReportFailure, match="宏、OLE 或 ActiveX"):
        report_runtime._validate_docx_structure(
            path,
            expected_sections=[{"code": "section_001", "title": "正文"}],
            expected_image_count=0,
            watermark_text="水印",
        )


def test_word_ooxml拒绝外部关系和损坏包(tmp_path):
    external = tmp_path / "external.docx"
    with zipfile.ZipFile(external, "w") as package:
        package.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="external" Target="https://example.invalid" '
            'TargetMode="External"/></Relationships>',
        )
    corrupt = tmp_path / "corrupt.docx"
    corrupt.write_bytes(b"not-a-zip")
    arguments = {
        "expected_sections": [{"code": "section_001", "title": "正文"}],
        "expected_image_count": 0,
        "watermark_text": "水印",
    }

    with pytest.raises(ReportFailure, match="外部关系"):
        report_runtime._validate_docx_structure(external, **arguments)
    with pytest.raises(ReportFailure, match="OOXML 无法解析"):
        report_runtime._validate_docx_structure(corrupt, **arguments)


def test_word_ooxml版式能力缺失仅记录观测值(tmp_path):
    path = tmp_path / "report.docx"
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{namespace}"><w:body><w:p/><w:sectPr/>'
            "</w:body></w:document>",
        )
        package.writestr("word/settings.xml", f'<w:settings xmlns:w="{namespace}"/>')
        package.writestr("[Content_Types].xml", "<Types/>")

    result = report_runtime._validate_docx_structure(
        path,
        expected_sections=[{"code": "section_001", "title": "正文"}],
        expected_image_count=0,
        watermark_text="水印",
    )

    assert result == {
        "nativeTocPresent": False,
        "sectionCount": 1,
        "tocEntryCount": 0,
        "embeddedImageCount": 0,
        "externalRelationshipCount": 0,
    }


def test_word_libreoffice空白页检测忽略服务端装饰(tmp_path, monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    context = {
        "title": "经营分析报告",
        "periodLabel": "2025-01-01 至 2025-12-31",
        "organizationName": "测试机构",
        "generatedByLabel": "测试平台生成",
        "watermarkText": "测试水印",
        "generatedDate": "2026-08-05",
        "sections": [{"code": "section_001", "title": "第一章"}],
    }
    layout = dict(report_runtime.DEFAULT_PAGE_LAYOUT)

    def decorations(page):
        values = [
            context["watermarkText"],
            *(
                report_runtime._formatted_page_text(
                    value,
                    title=context["title"],
                    organization=context["organizationName"],
                    page=page,
                    pages=4,
                )
                for value in layout.values()
            ),
        ]
        return " ".join(values)

    page_texts = [
        " ".join(
            (
                context["title"],
                context["periodLabel"],
                context["organizationName"],
                context["generatedByLabel"],
            )
        ),
        f"{decorations('i')} 目录 第一章",
        decorations("ii"),
        f"{decorations(1)} 第一章 正文 {context['generatedDate']}",
    ]
    pages = [SimpleNamespace(extract_text=lambda text=text: text, images=()) for text in page_texts]
    monkeypatch.setattr(pypdf, "PdfReader", lambda _path: SimpleNamespace(pages=pages))
    monkeypatch.setattr(report_runtime.shutil, "which", lambda name: f"/usr/bin/{name}")

    def run(command, *_args, **_kwargs):
        if "--convert-to" in command:
            output = Path(command[command.index("--outdir") + 1])
            output.joinpath("report.pdf").write_bytes(b"pdf")
        else:
            prefix = Path(command[-1])
            for index in range(1, 5):
                prefix.with_name(f"{prefix.name}-{index}.png").write_bytes(PNG)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(report_runtime.subprocess, "run", run)
    source = tmp_path / "report.docx"
    source.write_bytes(b"PK")

    with pytest.raises(ReportFailure, match="缺少正式内容或包含空白页"):
        report_runtime._validate_docx_rendering(
            source,
            tmp_path / "validation",
            context=context,
            layout=layout,
        )


def test_word_libreoffice中文标题布局空格不误判目录正文分页(tmp_path, monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    context = {
        "title": "瑞金医院2025年综合运营报告",
        "periodLabel": "2025-01-01 至 2025-12-31",
        "organizationName": "测试机构",
        "generatedByLabel": "测试平台生成",
        "watermarkText": "测试水印",
        "generatedDate": "2026-08-07",
        "sections": [
            {"code": "section_001", "title": "2025年整体经营规模与结构分析"}
        ],
    }
    layout = dict(report_runtime.DEFAULT_PAGE_LAYOUT)

    def decorations(page):
        values = [
            context["watermarkText"],
            *(
                report_runtime._formatted_page_text(
                    value,
                    title=context["title"],
                    organization=context["organizationName"],
                    page=page,
                    pages=3,
                )
                for value in layout.values()
            ),
        ]
        return " ".join(values)

    split_heading = "2 0 2 5 年 整 体 经 营 规 模 与 结 构 分 析"
    page_texts = [
        " ".join(
            (
                context["title"],
                context["periodLabel"],
                context["organizationName"],
                context["generatedByLabel"],
            )
        ),
        f"{decorations('i')} 目录 {split_heading}",
        f"{decorations(1)} {split_heading} 正文 {context['generatedDate']}",
    ]
    pages = [SimpleNamespace(extract_text=lambda text=text: text, images=()) for text in page_texts]
    monkeypatch.setattr(pypdf, "PdfReader", lambda _path: SimpleNamespace(pages=pages))
    monkeypatch.setattr(report_runtime.shutil, "which", lambda name: f"/usr/bin/{name}")

    def run(command, *_args, **_kwargs):
        if "--convert-to" in command:
            output = Path(command[command.index("--outdir") + 1])
            output.joinpath("report.pdf").write_bytes(b"pdf")
        else:
            prefix = Path(command[-1])
            for index in range(1, 4):
                prefix.with_name(f"{prefix.name}-{index}.png").write_bytes(PNG)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(report_runtime.subprocess, "run", run)
    source = tmp_path / "report.docx"
    source.write_bytes(b"PK")

    result = report_runtime._validate_docx_rendering(
        source,
        tmp_path / "validation",
        context=context,
        layout=layout,
    )

    assert result["convertedPageCount"] == 3
    assert result["blankPages"] == []


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def word_structure(expected_sections, expected_image_count):
        return {
            "nativeTocPresent": True,
            "sectionCount": 3,
            "tocEntryCount": len(expected_sections),
            "embeddedImageCount": expected_image_count or 0,
            "externalRelationshipCount": 0,
        }

    def render_docx(
        _html_document,
        *,
        source_parent,
        output,
        context,
        layout,
    ):
        del source_parent, layout
        output.write_bytes(b"PK\x03\x04unit-test-docx")
        return word_structure(context["sections"], 0)

    def validate_docx_structure(
        _path,
        *,
        expected_sections,
        expected_image_count,
        watermark_text,
    ):
        assert watermark_text == "AI 智能报告平台生成"
        return word_structure(expected_sections, expected_image_count)

    def validate_docx_rendering(_path, _directory, *, context, layout):
        assert context["organizationName"] == "上海鼎医信息技术有限公司"
        assert layout["headerLeft"] == "{organization}"
        return {"convertedPageCount": 3, "blankPages": [], "renderedImageCount": 0}

    monkeypatch.setattr(report_runtime, "_render_docx", render_docx)
    monkeypatch.setattr(report_runtime, "_validate_docx_structure", validate_docx_structure)
    monkeypatch.setattr(report_runtime, "_validate_docx_rendering", validate_docx_rendering)
    return ReportRuntime(workspace)


def prepare_job(runtime, paths):
    return {
        "jobId": str(uuid.uuid4()),
        "sources": [runtime._artifact(runtime.workspace / path) for path in paths],
    }


def bind_document_context(runtime, job, markdown_path):
    source = runtime.workspace / markdown_path
    markdown = source.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
    if title_match is None:
        markdown = f"# 报表\n\n{markdown}"
        title = "报表"
    else:
        title = title_match.group(1)
    headings = re.findall(r"^##\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
    markers = report_runtime._SECTION_MARKER.findall(markdown)
    if not headings:
        markdown = f"{markdown.rstrip()}\n\n[[section:main]]\n## 正文\n"
        headings = ["正文"]
        markers = ["main"]
    elif not markers:
        counter = 0

        def add_marker(match):
            nonlocal counter
            counter += 1
            return f"[[section:section_{counter}]]\n{match.group(0)}"

        markdown = re.sub(r"^##\s+.+?\s*$", add_marker, markdown, flags=re.MULTILINE)
        markers = [f"section_{index}" for index in range(1, len(headings) + 1)]
    source.write_text(markdown, encoding="utf-8")
    job["_documentContext"] = {
        "title": title,
        "periodLabel": "2025-01-01 至 2025-12-31",
        "organizationName": "上海鼎医信息技术有限公司",
        "generatedByLabel": "AI 智能报告平台生成",
        "watermarkText": "AI 智能报告平台生成",
        "generatedDate": "2026-08-05",
        "sections": [
            {"code": code, "title": heading}
            for code, heading in zip(markers, headings, strict=True)
        ],
    }


def render_job(runtime, job, markdown_path, output_path, page_layout=None):
    temporary_root = Path("/tmp") / f"workspace-report-{uuid.uuid4().hex}-render"
    temporary = temporary_root / "render.pdf"
    try:
        bind_document_context(runtime, job, markdown_path)
        result = runtime.render_markdown(
            job,
            markdown_path,
            output_path,
            str(temporary),
            page_layout,
        )
        render = result.pop("render")
        os.link(temporary, runtime.workspace / output_path)
        os.link(
            temporary.with_name("render.docx"),
            runtime.workspace / result["wordPath"],
        )
        job["render"] = render
        job.pop("validation", None)
        return result
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def validate_job(runtime, job, pdf_path):
    temporary = f"/tmp/workspace-report-{uuid.uuid4().hex}-validate"
    render = job.get("render")
    word_path = render.get("word", {}).get("path") if isinstance(render, dict) else None
    validation = runtime.validate_pdf(
        job,
        pdf_path,
        temporary,
        word_path=word_path,
    )
    job["validation"] = validation
    return validation


def test_runtime_接受任意格式的可信快照并拒绝越界路径(runtime):
    (runtime.workspace / "data.custom").write_bytes(b"content")

    prepared = prepare_job(runtime, ["data.custom"])

    runtime._validate_datasets(prepared)
    with pytest.raises(ReportFailure, match="相对路径"):
        runtime._validate_datasets(
            {"sources": [{"path": "../data.custom", "size": 7, "sha256": "0" * 64}]}
        )


def test_源文件变化后拒绝渲染(runtime):
    source = runtime.workspace / "data.csv"
    source.write_text("value\n1\n", encoding="utf-8")
    job = prepare_job(runtime, ["data.csv"])
    (runtime.workspace / "report.md").write_text("# 报表", encoding="utf-8")
    source.write_text("value\n3\n", encoding="utf-8")

    with pytest.raises(ReportFailure, match="源文件发生变化"):
        render_job(runtime, job, "report.md", "report.pdf")


def test_matplotlib_中文字体配置不产生缺字警告():
    matplotlib = pytest.importorskip("matplotlib")
    import warnings

    config = Path("docker/sandbox-tools/matplotlibrc")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        with matplotlib.rc_context(fname=str(config)):
            import matplotlib.pyplot as pyplot

            figure, axis = pyplot.subplots()
            axis.set_title("医院收入趋势")
            axis.set_xlabel("月份")
            axis.plot([1, 2], [10, 20])
            figure.canvas.draw()
            pyplot.close(figure)

    assert not any("Glyph" in str(item.message) for item in captured)


def test_runtime_未预期异常不暴露_traceback(monkeypatch, capsys):
    def fail(*_args, **_kwargs):
        raise RuntimeError("private internal path")

    monkeypatch.setattr(ReportRuntime, "render_markdown", fail)

    assert (
        report_runtime.main(
            [
                "render_markdown",
                json.dumps(
                    {
                        "job": {},
                        "markdown_path": "report.md",
                        "output_path": "report.pdf",
                        "temporary_path": "/tmp/workspace-report-test-render/render.pdf",
                    }
                ),
            ]
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "报表运行时执行失败" in output
    assert "private internal path" not in output
    assert "Traceback" not in output


def test_runtime_不再接受工作区外的job状态操作(capsys):
    assert report_runtime.main(["status", json.dumps({"job_id": str(uuid.uuid4())})]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output == {"error": "未知报表操作"}


def test_markdown_正文表格和多图完整渲染为_pdf(runtime):
    pypdf = pytest.importorskip("pypdf")
    (runtime.workspace / "data.csv").write_text("科室,人数\n外科,30\n", encoding="utf-8")
    report = runtime.workspace / "报表" / "生成结果" / "demo"
    assets = report / "assets"
    assets.mkdir(parents=True)
    (assets / "chart-01.png").write_bytes(PNG)
    (assets / "chart-02.png").write_bytes(PNG)
    (report / "智能报表.md").write_text(
        "# 医院人力资源报告\n\n"
        "| 科室 | 人数 |\n| --- | ---: |\n| 外科 | 30 |\n\n"
        "![人员分布](assets/chart-01.png)\n\n"
        "![人员占比](assets/chart-02.png)\n\n"
        "<script>alert('x')</script>\n",
        encoding="utf-8",
    )
    job = prepare_job(runtime, ["data.csv"])

    rendered = render_job(
        runtime,
        job,
        "报表/生成结果/demo/智能报表.md",
        "报表/生成结果/demo/智能报表.pdf",
    )

    pdf = runtime.workspace / rendered["pdfPath"]
    reader = pypdf.PdfReader(str(pdf))
    text = "".join(page.extract_text() or "" for page in reader.pages)
    assert rendered["markdownPath"] == "报表/生成结果/demo/智能报表.md"
    assert rendered["imageCount"] == 2
    assert job["render"]["visualTheme"] == report_runtime.REPORT_VISUAL_THEME
    assert "医院人力资源报告" in text
    assert "外科" in text
    compact_pages = ["".join((page.extract_text() or "").split()) for page in reader.pages]
    assert "企业智能运营报表" not in compact_pages[0]
    assert compact_pages[0].count("AI智能报告平台生成") == 1
    for page_text in compact_pages[1:]:
        assert "上海鼎医信息技术有限公司" in page_text
        assert "医院人力资源报告" in page_text
        assert "企业智能运营报表" in page_text
        assert "AI智能报告平台生成" in page_text
    assert sum(len(page.images) for page in reader.pages) >= 2

    validation = validate_job(runtime, job, rendered["pdfPath"])
    assert validation["ok"] is True, json.dumps(validation, ensure_ascii=False)
    assert validation["status"] == "validated"
    assert validation["pageCount"] == rendered["pageCount"]
    assert validation["markdownImageCount"] == 2
    assert validation["renderedImageCount"] >= 2
    assert validation["missingPageLayoutPages"] == []
    assert validation["pages"][0]["pageLayoutPresent"] is False
    assert validation["pages"][0]["watermarkPresent"] is False
    assert all(page["pageLayoutPresent"] for page in validation["pages"][1:])
    assert all(page["watermarkPresent"] for page in validation["pages"][1:])
    assert all(page["nonWhiteRatio"] > 0 for page in validation["pages"])

    pdf.write_bytes(pdf.read_bytes() + b"\n% changed")
    with pytest.raises(ReportFailure, match="发生变化"):
        validate_job(runtime, job, rendered["pdfPath"])


def test_pdf_长标题和多页目录保持页码角色与章节链接(runtime):
    (runtime.workspace / "data.csv").write_text("value\n1\n", encoding="utf-8")
    title = "医院综合运营管理分析报告" * 5
    sections = [
        f"第{index:02d}章 医疗服务质量、运营效率与资源配置综合分析" for index in range(1, 46)
    ]
    markdown = [f"# {title}"]
    for section in sections:
        markdown.extend(
            [
                f"## {section}",
                "本章基于已批准事实分析经营表现、风险边界和管理行动。",
            ]
        )
    (runtime.workspace / "long-report.md").write_text("\n\n".join(markdown), encoding="utf-8")
    job = prepare_job(runtime, ["data.csv"])

    rendered = render_job(runtime, job, "long-report.md", "long-report.pdf")
    validation = validate_job(runtime, job, rendered["pdfPath"])

    toc_pages = [page for page in validation["pages"] if page["role"] == "toc"]
    body_pages = [page for page in validation["pages"] if page["role"] == "body"]
    assert validation["ok"] is True, json.dumps(validation, ensure_ascii=False)
    assert len(toc_pages) >= 2
    assert body_pages
    assert all(page["pageLayoutPresent"] for page in toc_pages)
    assert all(page["watermarkPresent"] for page in toc_pages)
    assert validation["tocLinkCount"] >= len(sections)
    assert validation["bodyStartPage"] == toc_pages[-1]["page"] + 1
    assert validation["word"]["tocEntryCount"] == len(sections)


def test_pdf_不显示引用或实际引用附录但保留_manifest_绑定(runtime, monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    word_documents = []
    render_docx = report_runtime._render_docx

    def capture_word_document(html_document, **kwargs):
        word_documents.append(html_document)
        return render_docx(html_document, **kwargs)

    monkeypatch.setattr(report_runtime, "_render_docx", capture_word_document)
    long_business_label = (
        "按院区、一级核算单元和预算类型汇总医疗收入预算执行情况，"
        "对比实际医疗收入与预算医疗收入并形成已审核业务数据说明"
    )
    (runtime.workspace / "data.csv").write_text("月份,金额\n2025-01,1\n", encoding="utf-8")
    markdown = (
        "# 经营分析报告\n\n"
        "[[section:executive_summary]]\n"
        "## 执行摘要\n\n"
        "预算执行保持稳定。[[citation:citation_002]][[analysis:analysis_002]]\n\n"
        "收入趋势可控。[[citation:citation_001]][[analysis:analysis_001]]\n"
    )
    (runtime.workspace / "report.md").write_text(markdown, encoding="utf-8")
    job = prepare_job(runtime, ["data.csv"])
    job["_citationPresentations"] = [
        {
            "citationId": "citation_001",
            "label": long_business_label,
            "coverageItems": [{"label": "收入数据", "periods": ["2025-01", "2025-02"]}],
        },
        {
            "citationId": "citation_002",
            "label": "支出预算执行",
            "coverageItems": [
                {"label": "预算数据", "periods": ["2025-01", "2025-02"]},
                {"label": "实际支出数据", "periods": ["2025-02"]},
            ],
        },
    ]
    rendered = render_job(runtime, job, "report.md", "report.pdf")
    assert job["render"]["citationAppendixPresent"] is False

    reader = pypdf.PdfReader(str(runtime.workspace / rendered["pdfPath"]))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "[引用 001]" not in text
    assert "[引用 002]" not in text
    assert "[[citation:" not in text
    assert "[[analysis:" not in text
    assert "[[section:executive_summary]]" not in text
    assert len(word_documents) == 1
    assert "[[citation:" not in word_documents[0]
    assert "[[analysis:" not in word_documents[0]
    assert "[[section:" not in word_documents[0]
    assert "实际引用附录" not in text
    assert "支出预算执行" not in text
    assert "".join(long_business_label.split()) not in "".join(text.split())
    assert "2025年1月至2月" not in text
    assert "dataset" not in text
    assert "requirement" not in text
    assert "[[citation:citation_002]]" in (runtime.workspace / "report.md").read_text(
        encoding="utf-8"
    )
    assert "[[section:executive_summary]]" in (runtime.workspace / "report.md").read_text(
        encoding="utf-8"
    )
    assert "[[analysis:analysis_001]]" in (runtime.workspace / "report.md").read_text(
        encoding="utf-8"
    )
    assert "[[analysis:analysis_002]]" in (runtime.workspace / "report.md").read_text(
        encoding="utf-8"
    )

    temporary = f"/tmp/workspace-report-{uuid.uuid4().hex}-validate"
    validation = runtime.validate_pdf(
        job,
        rendered["pdfPath"],
        temporary,
        {
            "charts": [],
            "citations": [
                {
                    "citationId": "citation_001",
                    "datasetId": "dataset-income",
                    "requirementId": "income",
                },
                {
                    "citationId": "citation_002",
                    "datasetId": "dataset-budget",
                    "requirementId": "budget",
                },
            ],
            "sections": ["executive_summary"],
        },
    )
    assert validation["ok"] is True, json.dumps(validation, ensure_ascii=False)
    assert validation["citationIds"] == ["citation_001", "citation_002"]


def test_pdf_视觉验收识别空白页且不把失败当作完成(runtime, monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    from weasyprint import HTML

    def write_blank_pdf(_document, target):
        writer = pypdf.PdfWriter()
        page_count = 2 if str(target).endswith("render.decorations.pdf") else 3
        for _index in range(page_count):
            writer.add_blank_page(width=595, height=842)
        if not str(target).endswith("render.decorations.pdf"):
            writer.add_named_destination("report-section-main", 2)
        with open(target, "wb") as stream:
            writer.write(stream)

    monkeypatch.setattr(HTML, "write_pdf", write_blank_pdf)
    (runtime.workspace / "data.csv").write_text("value\n1\n", encoding="utf-8")
    (runtime.workspace / "report.md").write_text("# 报表", encoding="utf-8")
    job = prepare_job(runtime, ["data.csv"])
    rendered = render_job(runtime, job, "report.md", "report.pdf")

    validation = validate_job(runtime, job, rendered["pdfPath"])

    assert validation["ok"] is False
    assert validation["status"] == "validation_failed"
    assert validation["blankPages"] == [1, 2, 3]
    assert validation["pages"][0]["nonWhiteRatio"] == 0


def test_pdf_视觉验收记录缺少页面版式但不阻断(runtime, monkeypatch):
    (runtime.workspace / "data.csv").write_text("value\n1\n", encoding="utf-8")
    (runtime.workspace / "report.md").write_text("# 报表", encoding="utf-8")
    job = prepare_job(runtime, ["data.csv"])
    rendered = render_job(runtime, job, "report.md", "report.pdf")
    monkeypatch.setattr(report_runtime, "_has_page_layout", lambda *_args, **_kwargs: False)

    validation = validate_job(runtime, job, rendered["pdfPath"])

    assert validation["ok"] is True
    assert validation["missingPageLayoutPages"] == list(range(2, validation["pageCount"] + 1))


def test_pdf_视觉验收只接受当前任务记录的产物(runtime):
    (runtime.workspace / "data.csv").write_text("value\n1\n", encoding="utf-8")
    (runtime.workspace / "other.pdf").write_bytes(b"not a pdf")
    job = prepare_job(runtime, ["data.csv"])

    with pytest.raises(ReportFailure, match="未登记"):
        validate_job(runtime, job, "other.pdf")


@pytest.mark.parametrize(
    "image",
    [
        "https://example.com/chart.png",
        "../chart.png",
        "data:image/png;base64,AAAA",
    ],
)
def test_markdown_拒绝外部和越界图片(runtime, image):
    (runtime.workspace / "data").write_bytes(b"data")
    (runtime.workspace / "report.md").write_text(f"![图表]({image})", encoding="utf-8")
    job = prepare_job(runtime, ["data"])

    with pytest.raises(ReportFailure, match="图片只能引用工作区内的相对路径"):
        render_job(runtime, job, "report.md", "report.pdf")


def test_markdown_拒绝符号链接图片(runtime):
    (runtime.workspace / "data").write_bytes(b"data")
    outside = runtime.workspace.parent / "outside.png"
    outside.write_bytes(PNG)
    (runtime.workspace / "link.png").symlink_to(outside)
    (runtime.workspace / "report.md").write_text("![图表](link.png)", encoding="utf-8")
    job = prepare_job(runtime, ["data"])

    with pytest.raises(ReportFailure, match="符号链接"):
        render_job(runtime, job, "report.md", "report.pdf")


def test_commonmark_将_file图片降级为普通文本且不读取文件(runtime):
    from markdown_it import MarkdownIt

    (runtime.workspace / "data").write_bytes(b"data")
    source = runtime.workspace / "report.md"
    source.write_text("# 报表\n\n![禁止读取](file:///etc/passwd)", encoding="utf-8")
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = parser.parse(source.read_text(encoding="utf-8"))

    assert runtime._images(source, tokens) == set()
    assert "file:///etc/passwd" in parser.renderer.render(tokens, parser.options, {})


def test_markdown_拒绝覆盖已有_pdf且不触碰固定临时文件(runtime):
    (runtime.workspace / "data").write_bytes(b"data")
    (runtime.workspace / "report.md").write_text("# 报表", encoding="utf-8")
    output = runtime.workspace / "report.pdf"
    legacy_temporary = runtime.workspace / "report.tmp.pdf"
    output.write_bytes(b"existing")
    legacy_temporary.write_bytes(b"keep")
    job = prepare_job(runtime, ["data"])

    with pytest.raises(ReportFailure, match="已经存在"):
        render_job(runtime, job, "report.md", "report.pdf")

    assert output.read_bytes() == b"existing"
    assert legacy_temporary.read_bytes() == b"keep"


def test_markdown_使用唯一临时文件发布_pdf(runtime, monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    from weasyprint import HTML

    def write_minimal_pdf(_document, target):
        writer = pypdf.PdfWriter()
        page_count = 2 if str(target).endswith("render.decorations.pdf") else 3
        for _index in range(page_count):
            writer.add_blank_page(width=100, height=100)
        if not str(target).endswith("render.decorations.pdf"):
            writer.add_named_destination("report-section-main", 2)
        with open(target, "wb") as stream:
            writer.write(stream)

    monkeypatch.setattr(HTML, "write_pdf", write_minimal_pdf)
    (runtime.workspace / "data").write_bytes(b"data")
    (runtime.workspace / "report.md").write_text("# 报表", encoding="utf-8")
    legacy_temporary = runtime.workspace / "report.tmp.pdf"
    legacy_temporary.write_bytes(b"keep")
    job = prepare_job(runtime, ["data"])

    rendered = render_job(runtime, job, "report.md", "report.pdf")

    assert (runtime.workspace / rendered["pdfPath"]).is_file()
    assert legacy_temporary.read_bytes() == b"keep"


def test_markdown_拒绝超过200mib的_pdf且不发布产物(runtime, monkeypatch):
    from weasyprint import HTML

    def write_oversized_pdf(_document, target):
        with open(target, "wb") as stream:
            stream.truncate(report_runtime.MAX_PDF_BYTES + 1)

    monkeypatch.setattr(HTML, "write_pdf", write_oversized_pdf)
    (runtime.workspace / "data").write_bytes(b"data")
    (runtime.workspace / "report.md").write_text("# 报表", encoding="utf-8")
    job = prepare_job(runtime, ["data"])

    with pytest.raises(ReportFailure, match="不能超过 200 MiB"):
        render_job(runtime, job, "report.md", "report.pdf")

    assert not (runtime.workspace / "report.pdf").exists()
    assert "render" not in job


def test_markdown_拒绝超过页数边界的_pdf且不发布产物(runtime, monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    from weasyprint import HTML

    def write_oversized_pdf(_document, target):
        writer = pypdf.PdfWriter()
        for _index in range(report_runtime.MAX_PDF_PAGES + 1):
            writer.add_blank_page(width=100, height=100)
        with open(target, "wb") as stream:
            writer.write(stream)

    monkeypatch.setattr(HTML, "write_pdf", write_oversized_pdf)
    (runtime.workspace / "data").write_bytes(b"data")
    (runtime.workspace / "report.md").write_text("# 报表", encoding="utf-8")
    job = prepare_job(runtime, ["data"])

    with pytest.raises(ReportFailure, match="不能超过 200 页"):
        render_job(runtime, job, "report.md", "report.pdf")

    assert not (runtime.workspace / "report.pdf").exists()
    assert "render" not in job
