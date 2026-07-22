import base64
import json
import os
import shlex
import sys
from concurrent.futures import ThreadPoolExecutor
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
    assert "pdftoppm" in capabilities["commands"]


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


def test_分析命令自动使用隔离的中文绘图字体(runtime):
    (runtime.workspace / "data.csv").write_text("value\n1\n", encoding="utf-8")
    job_id = runtime.prepare_dataset(["data.csv"])["jobId"]
    python = shlex.quote(sys.executable)

    result = runtime.analyze_dataset(
        job_id,
        f"{python} -c 'import matplotlib; print(matplotlib.rcParams[\"font.sans-serif\"][0])'",
    )

    assert result["ok"] is True
    assert result["output"].strip() == "Noto Sans CJK JP"


def test_损坏的_matplotlib_配置返回稳定错误(runtime):
    (runtime.workspace / "data.csv").write_text("value\n1\n", encoding="utf-8")
    job_id = runtime.prepare_dataset(["data.csv"])["jobId"]
    config = runtime._job_path(job_id) / "matplotlib"
    config.mkdir()
    (config / "matplotlibrc").write_bytes(b"\xff")

    with pytest.raises(ReportFailure, match="绘图字体配置文件无效"):
        runtime._matplotlib_config_dir(job_id)


def test_确定性剖析已登记_csv并返回受限统计(runtime):
    (runtime.workspace / "income.csv").write_text(
        "科室,收入,日期\n外科,100.5,2026-01-01\n内科,,2026-01-02\n外科,300,2026-01-03\n",
        encoding="utf-8",
    )
    job_id = runtime.prepare_dataset(["income.csv"])["jobId"]

    result = runtime.profile_dataset(job_id)

    assert result["status"] == "profiled"
    assert result["jobId"] == job_id
    assert result["datasetCount"] == 1
    profile = result["datasets"][0]
    assert profile["path"] == "income.csv"
    assert profile["format"] == "csv"
    assert profile["rowCount"] == 3
    assert profile["columnCount"] == 3
    assert profile["sampled"] is False
    columns = {column["name"]: column for column in profile["columns"]}
    assert columns["收入"]["nullCount"] == 1
    assert columns["收入"]["numeric"]["min"] == 100.5
    assert columns["收入"]["numeric"]["max"] == 300.0
    assert columns["科室"]["topValues"][0] == {"value": "外科", "count": 2}
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) < 64 * 1024


def test_parquet_剖析只读取受限批次(runtime, monkeypatch):
    arrow = pytest.importorskip("pyarrow")
    parquet = pytest.importorskip("pyarrow.parquet")
    source = runtime.workspace / "income.parquet"
    parquet.write_table(
        arrow.table({"收入": range(report_runtime.MAX_PROFILE_ROWS + 10)}),
        source,
        row_group_size=25_000,
    )
    original_parquet_file = parquet.ParquetFile

    class BoundedParquetFile:
        def __init__(self, path):
            self._source = original_parquet_file(path)
            self.metadata = self._source.metadata
            self.schema_arrow = self._source.schema_arrow

        def iter_batches(self, **kwargs):
            return self._source.iter_batches(**kwargs)

        def read(self, *args, **kwargs):
            raise AssertionError("剖析不应读取完整 Parquet")

    monkeypatch.setattr(parquet, "ParquetFile", BoundedParquetFile)
    job_id = runtime.prepare_dataset(["income.parquet"])["jobId"]

    profile = runtime.profile_dataset(job_id)["datasets"][0]

    assert profile["rowCount"] == report_runtime.MAX_PROFILE_ROWS + 10
    assert profile["sampleRowCount"] == report_runtime.MAX_PROFILE_ROWS
    assert profile["sampled"] is True


def test_普通_json_超过剖析边界时返回稳定错误(runtime, monkeypatch):
    (runtime.workspace / "income.json").write_text('[{"收入": 1}]', encoding="utf-8")
    monkeypatch.setattr(report_runtime, "MAX_PROFILE_JSON_BYTES", 4)
    job_id = runtime.prepare_dataset(["income.json"])["jobId"]

    with pytest.raises(ReportFailure, match="普通 JSON 文件超过"):
        runtime.profile_dataset(job_id)


def test_损坏的_excel_返回稳定剖析错误(runtime):
    (runtime.workspace / "broken.xlsx").write_bytes(b"not an excel workbook")
    job_id = runtime.prepare_dataset(["broken.xlsx"])["jobId"]

    with pytest.raises(ReportFailure, match="无法剖析数据集 broken.xlsx"):
        runtime.profile_dataset(job_id)


def test_runtime_未预期异常不暴露_traceback(monkeypatch, capsys):
    def fail():
        raise RuntimeError("private internal path")

    monkeypatch.setattr(ReportRuntime, "analysis_capabilities", staticmethod(fail))

    assert report_runtime.main(["capabilities", "{}"]) == 1
    output = capsys.readouterr().out
    assert "报表运行时执行失败" in output
    assert "private internal path" not in output
    assert "Traceback" not in output


def test_剖析结果按返回边界减少末尾列(runtime, monkeypatch):
    long_value = "甲" * 200
    columns = [f"字段{index}" for index in range(8)]
    (runtime.workspace / "wide.csv").write_text(
        ",".join(columns) + "\n" + ",".join(f"{long_value}{index}" for index in range(8)) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(report_runtime, "MAX_RESULT_BYTES", 2_000)
    job_id = runtime.prepare_dataset(["wide.csv"])["jobId"]

    result = runtime.profile_dataset(job_id)

    profile = result["datasets"][0]
    assert len(profile["columns"]) < len(columns)
    assert any("已减少末尾列" in warning for warning in profile["warnings"])
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) + 1 <= 2_000


def test_剖析不接受任务外路径且源文件变化后失效(runtime):
    source = runtime.workspace / "income.csv"
    source.write_text("收入\n1\n", encoding="utf-8")
    (runtime.workspace / "other.csv").write_text("收入\n2\n", encoding="utf-8")
    job_id = runtime.prepare_dataset(["income.csv"])["jobId"]

    with pytest.raises(TypeError):
        runtime.profile_dataset(job_id, "other.csv")

    source.write_text("收入\n3\n", encoding="utf-8")
    with pytest.raises(ReportFailure, match="源文件发生变化"):
        runtime.profile_dataset(job_id)


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

    status = runtime.job_status(job_id)
    assert status["status"] == "rendered"
    assert status["sources"][0]["sha256"]
    assert status["artifacts"]["markdown"]["path"] == rendered["markdownPath"]
    assert status["artifacts"]["pdf"]["path"] == rendered["pdfPath"]
    assert status["artifacts"]["pdf"]["sha256"]

    validation = runtime.validate_pdf(job_id, rendered["pdfPath"])
    assert validation["ok"] is True
    assert validation["status"] == "validated"
    assert validation["pageCount"] == rendered["pageCount"]
    assert validation["markdownImageCount"] == 2
    assert validation["renderedImageCount"] >= 2
    assert all(page["nonWhiteRatio"] > 0 for page in validation["pages"])
    assert runtime.job_status(job_id)["validation"]["ok"] is True

    pdf.write_bytes(pdf.read_bytes() + b"\n% changed")
    changed = runtime.job_status(job_id)
    assert changed["status"] == "artifact_changed"
    assert changed["artifacts"]["pdf"]["changed"] is True


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
    job_id = runtime.prepare_dataset(["data.csv"])["jobId"]
    runtime.analyze_dataset(job_id, "printf analyzed")
    rendered = runtime.render_markdown(job_id, "report.md", "report.pdf")

    validation = runtime.validate_pdf(job_id, rendered["pdfPath"])

    assert validation["ok"] is False
    assert validation["status"] == "validation_failed"
    assert validation["blankPages"] == [1]
    assert validation["pages"][0]["nonWhiteRatio"] == 0
    assert runtime.job_status(job_id)["status"] == "validation_failed"


def test_pdf_视觉验收只接受当前任务记录的产物(runtime):
    (runtime.workspace / "data.csv").write_text("value\n1\n", encoding="utf-8")
    (runtime.workspace / "other.pdf").write_bytes(b"not a pdf")
    job_id = runtime.prepare_dataset(["data.csv"])["jobId"]

    with pytest.raises(ReportFailure, match="未登记"):
        runtime.validate_pdf(job_id, "other.pdf")


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
