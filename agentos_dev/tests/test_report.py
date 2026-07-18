from io import BytesIO
import json

from agno.run import RunContext
import pandas as pd
import pytest

from agentos_dev import report
from agentos_dev.report import report_tools
from agentos_dev.tests.test_workspace import service
from agentos_dev.workspace import WORKSPACE_ROOT, WorkspaceError


def context(thread="report-thread"):
    return RunContext(run_id="report-run", session_id=thread)


def tools(current):
    return {tool.name: tool for tool in report_tools(current)}


def call(tool, **arguments):
    return tool.entrypoint(**arguments)


def upload_datasets(current, thread="report-thread"):
    current.upload(thread, "data/sales.csv", (
        "region,category,amount\n华东,A,10\n华东,B,20\n华南,A,30\n"
    ).encode("utf-8"))
    current.upload(thread, "data/sales.json", json.dumps([
        {"region": "华东", "category": "A", "amount": 10},
        {"region": "华南", "category": "B", "amount": 20},
    ], ensure_ascii=False).encode("utf-8"))
    current.upload(thread, "data/sales.jsonl", (
        '{"region":"华东","category":"A","amount":10}\n'
        '{"region":"华南","category":"B","amount":20}\n'
    ).encode("utf-8"))
    workbook = BytesIO()
    pd.DataFrame([
        {"region": "华东", "category": "A", "amount": 10},
        {"region": "华南", "category": "B", "amount": 20},
    ]).to_excel(workbook, index=False, sheet_name="销售")
    current.upload(thread, "data/sales.xlsx", workbook.getvalue())


def test_profiles_csv_json_jsonl_and_xlsx(tmp_path):
    current = service(tmp_path)
    upload_datasets(current)
    current_tools = tools(current)

    for path in (
        "data/sales.csv", "data/sales.json", "data/sales.jsonl", "data/sales.xlsx",
    ):
        result = call(
            current_tools["pandas_profile_dataset"],
            path=path,
            sheet="销售" if path.endswith(".xlsx") else None,
            run_context=context(),
        )
        assert result["rowCount"] in {2, 3}
        assert result["columnCount"] == 3
        assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= 32 * 1024


def test_each_call_uses_and_releases_a_new_pandas_toolkit(tmp_path, monkeypatch):
    current = service(tmp_path)
    upload_datasets(current)
    instances = []
    original = report.PandasTools

    class TrackingPandasTools(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

    monkeypatch.setattr(report, "PandasTools", TrackingPandasTools)
    current_tools = tools(current)
    for _index in range(2):
        call(
            current_tools["pandas_profile_dataset"],
            path="data/sales.csv", run_context=context(),
        )

    assert len(instances) == 2
    assert instances[0] is not instances[1]
    assert all(not instance.dataframes for instance in instances)


def test_group_pivot_concat_and_thread_isolation(tmp_path):
    current = service(tmp_path)
    upload_datasets(current)
    current.upload("other-thread", "data/sales.csv", b"region,category,amount\nNorth,Z,99\n")
    current_tools = tools(current)

    grouped = call(
        current_tools["pandas_group_dataset"],
        path="data/sales.csv",
        dimensions=["region"],
        metrics=[
            {"field": "amount", "aggregation": "sum"},
            {"field": "amount", "aggregation": "avg"},
        ],
        run_context=context(),
    )
    east = next(item for item in grouped["rows"] if item["region"] == "华东")
    assert east["amount:sum"] == 30
    assert east["amount:avg"] == 15

    pivot = call(
        current_tools["pandas_pivot_dataset"],
        path="data/sales.csv", rows=["region"], columns=["category"],
        value="amount", aggregation="sum", run_context=context(),
    )
    assert pivot["rowCount"] == 2

    concatenated = call(
        current_tools["pandas_concat_datasets"],
        paths=["data/sales.json", "data/sales.jsonl"],
        source_labels=["JSON", "JSONL"], run_context=context(),
    )
    assert concatenated["rowCount"] == 4
    content, _mime = current.file_bytes("report-thread", concatenated["path"])
    assert {json.loads(line)["_source"] for line in content.splitlines()} == {"JSON", "JSONL"}

    isolated = call(
        current_tools["pandas_profile_dataset"],
        path="data/sales.csv", run_context=context("other-thread"),
    )
    assert isolated["rowCount"] == 1


def test_dataset_shape_and_memory_limits_are_enforced(tmp_path, monkeypatch):
    current = service(tmp_path)
    columns = ["c%s" % index for index in range(101)]
    current.upload("report-thread", "data/wide.csv", (
        ",".join(columns) + "\n" + ",".join("1" for _item in columns) + "\n"
    ).encode("utf-8"))

    with pytest.raises(WorkspaceError, match="100 列"):
        call(
            tools(current)["pandas_profile_dataset"],
            path="data/wide.csv", run_context=context(),
        )

    current.upload(
        "report-thread", "data/tall.csv",
        ("value\n" + "1\n" * (report.MAX_DATASET_ROWS + 1)).encode("utf-8"),
    )
    with pytest.raises(WorkspaceError, match="100000 行"):
        call(
            tools(current)["pandas_profile_dataset"],
            path="data/tall.csv", run_context=context(),
        )

    current.upload("report-thread", "data/memory.csv", b"value\nexpanded text\n")
    monkeypatch.setattr(report, "MAX_EXPANDED_BYTES", 1)
    with pytest.raises(WorkspaceError, match="128 MiB"):
        call(
            tools(current)["pandas_profile_dataset"],
            path="data/memory.csv", run_context=context(),
        )


def test_chart_outputs_png_and_download_only_html_without_confirmation(tmp_path):
    current = service(tmp_path)
    upload_datasets(current)
    current_tools = tools(current)
    for name in current_tools:
        assert current_tools[name].requires_confirmation is not True

    result = call(
        current_tools["pandas_generate_chart"],
        path="data/sales.csv", chart_type="bar", x="region", y="amount",
        aggregation="sum", title="区域销售额", run_context=context(),
    )
    png, png_mime = current.file_bytes("report-thread", result["pngPath"])
    html, html_mime = current.file_bytes("report-thread", result["htmlPath"])
    assert result["pngPath"].startswith("reports/")
    assert result["htmlPath"].startswith("reports/")
    assert png.startswith(b"\x89PNG")
    assert png_mime == "image/png"
    assert b"plotly" in html.lower()
    assert html_mime == "text/html"
    assert WORKSPACE_ROOT not in html.decode("utf-8")

    pie = call(
        current_tools["pandas_generate_chart"],
        path="data/sales.csv", chart_type="pie", x="region",
        run_context=context(),
    )
    assert pie["pointCount"] == 2

    current.upload("report-thread", "data/duplicates.csv", (
        "region,category,amount\n华东,A,10\n华东,A,20\n"
    ).encode("utf-8"))
    with pytest.raises(WorkspaceError, match="指定聚合方式"):
        call(
            current_tools["pandas_generate_chart"],
            path="data/duplicates.csv", chart_type="bar", x="region",
            y="amount", group="category", run_context=context(),
        )
