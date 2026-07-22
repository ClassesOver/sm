import base64
import os
import shlex
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agentos_dev.report_runtime import ReportFailure, ReportRuntime

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_sandbox_tools_提供智能报表所需命令和分析库():
    dockerfile = Path("docker/sandbox-tools/Dockerfile").read_text(encoding="utf-8")

    assert "        bash \\\n" in dockerfile
    for package in ("matplotlib", "pandas", "polars", "scipy", "seaborn", "sklearn"):
        assert package in dockerfile


@pytest.fixture
def runtime(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return ReportRuntime(workspace, tmp_path / "state")


def test_准备数据集接受任意格式并拒绝越界路径(runtime):
    (runtime.workspace / "data.custom").write_bytes(b"content")

    prepared = runtime.prepare_dataset(["data.custom"])

    assert prepared["paths"] == ["data.custom"]
    assert prepared["hashes"]["data.custom"]
    assert prepared["roundCount"] == 0
    assert prepared["successfulRoundCount"] == 0
    with pytest.raises(ReportFailure, match="相对路径"):
        runtime.prepare_dataset(["../data.custom"])


def test_分析失败反馈模型且同一任务可以继续多轮(runtime):
    (runtime.workspace / "data.csv").write_text("value\n1\n", encoding="utf-8")
    job_id = runtime.prepare_dataset(["data.csv"])["jobId"]

    python = shlex.quote(sys.executable)
    failed = runtime.analyze_dataset(job_id, f"{python} -c 'raise ValueError(\"bad data\")'")
    succeeded = runtime.analyze_dataset(
        job_id,
        f'{python} -c \'from pathlib import Path; Path("result.txt").write_text("ok"); print("written")\'',
    )
    verified = runtime.analyze_dataset(job_id, 'test "$(cat result.txt)" = ok && printf verified')

    assert failed["ok"] is False
    assert failed["status"] == "analysis_failed"
    assert "Traceback" in failed["output"]
    assert "bad data" in failed["output"]
    assert failed["roundCount"] == 1
    assert failed["successfulRoundCount"] == 0
    assert succeeded["ok"] is True
    assert succeeded["roundCount"] == 2
    assert verified["ok"] is True
    assert verified["roundCount"] == 3
    assert verified["successfulRoundCount"] == 2


def test_空输出不能计为成功分析(runtime):
    (runtime.workspace / "data.csv").write_text("value\n1\n", encoding="utf-8")
    job_id = runtime.prepare_dataset(["data.csv"])["jobId"]

    result = runtime.analyze_dataset(job_id, "true")

    assert result["ok"] is False
    assert result["status"] == "analysis_failed"
    assert result["exitCode"] == 0
    assert result["successfulRoundCount"] == 0
    assert "没有返回分析结果" in result["output"]


def test_源文件变化后拒绝继续分析或渲染(runtime):
    source = runtime.workspace / "data.csv"
    source.write_text("value\n1\n", encoding="utf-8")
    job_id = runtime.prepare_dataset(["data.csv"])["jobId"]
    source.write_text("value\n2\n", encoding="utf-8")

    with pytest.raises(ReportFailure, match="源文件发生变化"):
        runtime.analyze_dataset(job_id, "printf analyzed")

    source.write_text("value\n1\n", encoding="utf-8")
    runtime.analyze_dataset(job_id, "printf analyzed")
    (runtime.workspace / "report.md").write_text("# 报表", encoding="utf-8")
    source.write_text("value\n3\n", encoding="utf-8")

    with pytest.raises(ReportFailure, match="源文件发生变化"):
        runtime.render_markdown(job_id, "report.md", "report.pdf")


def test_分析命令执行中修改源文件会使任务失效(runtime):
    (runtime.workspace / "data.csv").write_text("value\n1\n", encoding="utf-8")
    job_id = runtime.prepare_dataset(["data.csv"])["jobId"]

    with pytest.raises(ReportFailure, match="源文件发生变化"):
        runtime.analyze_dataset(job_id, "printf 'value\\n2\\n' > data.csv; printf analyzed")


def test_同一任务并发分析不会丢失轮次(runtime):
    (runtime.workspace / "data.csv").write_text("value\n1\n", encoding="utf-8")
    job_id = runtime.prepare_dataset(["data.csv"])["jobId"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: runtime.analyze_dataset(job_id, "sleep 0.05; printf analyzed"),
                range(2),
            )
        )

    assert sorted(result["roundCount"] for result in results) == [1, 2]
    assert all(result["ok"] for result in results)
    assert runtime._load(job_id)["successfulRoundCount"] == 2


@pytest.mark.skipif(sys.platform != "linux", reason="进程隔离运行时仅部署在 Linux sandbox")
def test_分析完成后回收脱离进程(runtime):
    (runtime.workspace / "data.csv").write_text("value\n1\n", encoding="utf-8")
    job_id = runtime.prepare_dataset(["data.csv"])["jobId"]

    result = runtime.analyze_dataset(
        job_id,
        "setsid sh -c 'exec sleep 30' >/dev/null 2>&1 & printf $!",
    )
    child_pid = int(result["output"])

    assert result["ok"] is True
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_分析超时返回失败并回收进程(runtime):
    (runtime.workspace / "data.csv").write_text("value\n1\n", encoding="utf-8")
    job_id = runtime.prepare_dataset(["data.csv"])["jobId"]

    result = runtime.analyze_dataset(job_id, "sleep 30", timeout=1)

    assert result["ok"] is False
    assert result["exitCode"] == 124
    assert result["roundCount"] == 1
    assert result["successfulRoundCount"] == 0


def test_分析能力返回沙箱实际库版本(runtime):
    capabilities = runtime.analysis_capabilities()

    assert capabilities["python"]
    assert capabilities["packages"]["pandas"]
    assert "sqlite3" in capabilities["sql"]


def test_没有成功分析不能渲染(runtime):
    (runtime.workspace / "data.csv").write_text("value\n1\n", encoding="utf-8")
    (runtime.workspace / "report.md").write_text("# 报表", encoding="utf-8")
    job_id = runtime.prepare_dataset(["data.csv"])["jobId"]
    runtime.analyze_dataset(job_id, "false")

    with pytest.raises(ReportFailure, match="至少成功完成一轮分析"):
        runtime.render_markdown(job_id, "report.md", "report.pdf")


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
    job_id = runtime.prepare_dataset(["data.csv"])["jobId"]
    runtime.analyze_dataset(job_id, "printf analyzed")

    rendered = runtime.render_markdown(
        job_id,
        "报表/生成结果/demo/智能报表.md",
        "报表/生成结果/demo/智能报表.pdf",
    )

    pdf = runtime.workspace / rendered["pdfPath"]
    reader = pypdf.PdfReader(str(pdf))
    text = "".join(page.extract_text() or "" for page in reader.pages)
    assert rendered["markdownPath"] == "报表/生成结果/demo/智能报表.md"
    assert rendered["imageCount"] == 2
    assert rendered["roundCount"] == 1
    assert rendered["successfulRoundCount"] == 1
    assert "医院人力资源报告" in text
    assert "外科" in text
    assert sum(len(page.images) for page in reader.pages) >= 2


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
    job_id = runtime.prepare_dataset(["data"])["jobId"]
    runtime.analyze_dataset(job_id, "printf analyzed")

    with pytest.raises(ReportFailure, match="图片只能引用工作区内的相对路径"):
        runtime.render_markdown(job_id, "report.md", "report.pdf")


def test_markdown_拒绝符号链接图片(runtime):
    (runtime.workspace / "data").write_bytes(b"data")
    outside = runtime.workspace.parent / "outside.png"
    outside.write_bytes(PNG)
    (runtime.workspace / "link.png").symlink_to(outside)
    (runtime.workspace / "report.md").write_text("![图表](link.png)", encoding="utf-8")
    job_id = runtime.prepare_dataset(["data"])["jobId"]
    runtime.analyze_dataset(job_id, "printf analyzed")

    with pytest.raises(ReportFailure, match="符号链接"):
        runtime.render_markdown(job_id, "report.md", "report.pdf")


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
    job_id = runtime.prepare_dataset(["data"])["jobId"]
    runtime.analyze_dataset(job_id, "printf analyzed")

    with pytest.raises(ReportFailure, match="已经存在"):
        runtime.render_markdown(job_id, "report.md", "report.pdf")

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
    job_id = runtime.prepare_dataset(["data"])["jobId"]
    runtime.analyze_dataset(job_id, "printf analyzed")

    rendered = runtime.render_markdown(job_id, "report.md", "report.pdf")

    assert (runtime.workspace / rendered["pdfPath"]).is_file()
    assert legacy_temporary.read_bytes() == b"keep"
