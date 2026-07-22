from pathlib import Path

import pandas as pd
import pytest

from agentos_dev.report_runtime import ReportFailure, ReportRuntime


def test_sandbox_tools_提供_daytona_process_exec_所需_bash():
    dockerfile = Path("docker/sandbox-tools/Dockerfile").read_text(encoding="utf-8")
    assert "        bash \\\n" in dockerfile


@pytest.fixture
def runtime(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return ReportRuntime(workspace, tmp_path / "state")


def test_五种格式进入同一准备流程并规范化重复列(runtime):
    xlwt = pytest.importorskip("xlwt")
    workspace = runtime.workspace
    (workspace / "a.csv").write_text("名称,名称\n甲,1\n", encoding="utf-8")
    pd.DataFrame([{"名称": "乙", "名称2": 2}]).to_excel(workspace / "b.xlsx", index=False)
    book = xlwt.Workbook()
    sheet = book.add_sheet("Sheet1")
    for column, value in enumerate(("名称", "名称2")):
        sheet.write(0, column, value)
    for column, value in enumerate(("丙", 3)):
        sheet.write(1, column, value)
    book.save(str(workspace / "c.xls"))
    (workspace / "d.json").write_text('[{"名称":"丁","名称2":4}]', encoding="utf-8")
    (workspace / "e.jsonl").write_text('{"名称":"戊","名称2":5}\n', encoding="utf-8")

    csv = runtime.prepare(["a.csv"])
    assert [column["name"] for column in csv["schema"]] == ["名称", "名称 (2)"]
    for path in ("b.xlsx", "c.xls", "d.json", "e.jsonl"):
        assert runtime.prepare([path])["rowCount"] == 1


def test_同结构文件合并且源文件变化后拒绝继续(runtime):
    for name, value in (("a.csv", 1), ("b.csv", 2)):
        (runtime.workspace / name).write_text(f"name,value\na,{value}\n", encoding="utf-8")
    prepared = runtime.prepare(["a.csv", "b.csv"])
    assert prepared["rowCount"] == 2
    (runtime.workspace / "a.csv").write_text("name,value\na,9\n", encoding="utf-8")
    with pytest.raises(ReportFailure, match="发生变化"):
        runtime.analyze(prepared["jobId"], [{"type": "summary"}])


def test_excel_默认选择首个可见工作表(runtime):
    source = runtime.workspace / "sheets.xlsx"
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame({"隐藏": [1]}).to_excel(writer, sheet_name="hidden", index=False)
        pd.DataFrame({"可见": [2]}).to_excel(writer, sheet_name="visible", index=False)
        writer.book["hidden"].sheet_state = "hidden"

    prepared = runtime.prepare([source.name])

    assert [item["name"] for item in prepared["schema"]] == ["可见"]


def test_状态机分析编排与引用校验(runtime):
    (runtime.workspace / "data.csv").write_text(
        "region,amount\n华东,10\n华南,30\n", encoding="utf-8"
    )
    job = runtime.prepare(["data.csv"])["jobId"]
    analysis = runtime.analyze(job, [{"type": "top_bottom", "column": "amount", "limit": 1}])
    analysis_id = analysis["analyses"][0]["analysisId"]
    with pytest.raises(ReportFailure, match="analysis_id"):
        runtime.compile(job, "测试", "经营", [{"type": "table", "analysis_id": "missing"}])
    compiled = runtime.compile(job, "测试", "经营", [{"type": "table", "analysis_id": analysis_id}])
    assert compiled["status"] == "compiled"
    with pytest.raises(ReportFailure, match="状态"):
        runtime.analyze(job, [{"type": "summary"}])


def test_路径穿越格式伪装与输入上限(runtime):
    with pytest.raises(ReportFailure, match="相对路径"):
        runtime.prepare(["../data.csv"])
    (runtime.workspace / "fake.csv").write_bytes(b"PK\x03\x04bad")
    with pytest.raises(ReportFailure, match="签名"):
        runtime.prepare(["fake.csv"])
    with pytest.raises(ReportFailure, match="1 至 5"):
        runtime.prepare([])


def test_经营财务项目模板可生成有效中文_pdf(runtime):
    pypdf = pytest.importorskip("pypdf")
    for template in ("经营", "财务", "项目"):
        source = runtime.workspace / f"{template}.csv"
        source.write_text("项目,金额\n甲,10\n乙,20\n", encoding="utf-8")
        job = runtime.prepare([source.name])["jobId"]
        analysis = runtime.analyze(job, [{"type": "summary"}])
        analysis_id = analysis["analyses"][0]["analysisId"]
        runtime.compile(
            job,
            f"{template}分析",
            template,
            [{"type": "table", "analysis_id": analysis_id}, {"type": "appendix"}],
        )
        rendered = runtime.render(job)
        pdf = runtime.workspace / rendered["path"]
        reader = pypdf.PdfReader(str(pdf))
        assert len(reader.pages) >= 1
        assert template in "".join(page.extract_text() or "" for page in reader.pages)
        assert "截断：否" in "".join(page.extract_text() or "" for page in reader.pages)
        assert [item.name for item in pdf.parent.iterdir()] == [pdf.name]
