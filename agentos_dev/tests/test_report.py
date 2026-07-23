import base64
import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

from agentos_dev import report_runtime
from agentos_dev.report_runtime import ReportFailure, ReportRuntime

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
    assert "COPY docker/sandbox-tools/matplotlibrc /tmp/matplotlibrc" in dockerfile
    assert "font.sans-serif: Noto Sans CJK JP, DejaVu Sans" in matplotlibrc
    assert "axes.unicode_minus: False" in matplotlibrc
    for package in ("matplotlib", "pandas", "polars", "scipy", "seaborn", "skimage"):
        assert package in dockerfile


def test_pdf_资源边界为200mib和600秒动作预算():
    assert report_runtime.MAX_PDF_BYTES == 200 * 1024 * 1024
    assert report_runtime.MAX_PDF_PAGES == 200
    assert report_runtime.PDF_VALIDATION_TIMEOUT_SECONDS == 540


@pytest.fixture
def runtime(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return ReportRuntime(workspace)


def prepare_job(runtime, paths):
    return {
        "jobId": str(uuid.uuid4()),
        "sources": [runtime._artifact(runtime.workspace / path) for path in paths],
    }


def render_job(runtime, job, markdown_path, output_path):
    temporary_root = Path("/tmp") / f"workspace-report-{uuid.uuid4().hex}-render"
    temporary = temporary_root / "render.pdf"
    try:
        result = runtime.render_markdown(
            job,
            markdown_path,
            output_path,
            str(temporary),
        )
        render = result.pop("render")
        os.link(temporary, runtime.workspace / output_path)
        job["render"] = render
        job.pop("validation", None)
        return result
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def validate_job(runtime, job, pdf_path):
    temporary = f"/tmp/workspace-report-{uuid.uuid4().hex}-validate"
    validation = runtime.validate_pdf(job, pdf_path, temporary)
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
    assert "医院人力资源报告" in text
    assert "外科" in text
    assert sum(len(page.images) for page in reader.pages) >= 2

    validation = validate_job(runtime, job, rendered["pdfPath"])
    assert validation["ok"] is True
    assert validation["status"] == "validated"
    assert validation["pageCount"] == rendered["pageCount"]
    assert validation["markdownImageCount"] == 2
    assert validation["renderedImageCount"] >= 2
    assert all(page["nonWhiteRatio"] > 0 for page in validation["pages"])

    pdf.write_bytes(pdf.read_bytes() + b"\n% changed")
    with pytest.raises(ReportFailure, match="发生变化"):
        validate_job(runtime, job, rendered["pdfPath"])


def test_pdf_视觉验收识别空白页且不把失败当作完成(runtime, monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    from weasyprint import HTML

    def write_blank_pdf(_document, target):
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=595, height=842)
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
    assert validation["blankPages"] == [1]
    assert validation["pages"][0]["nonWhiteRatio"] == 0


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
        writer.add_blank_page(width=100, height=100)
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
