import hashlib
import json
import tempfile
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from agno.run import RunContext

from agentos_dev import report
from agentos_dev.report import report_tools
from agentos_dev.tests.workspace_fakes import service
from agentos_dev.workspace import WORKSPACE_ROOT, WorkspaceError


def context(thread="report-thread"):
    return RunContext(run_id="report-run", session_id=thread)


def tools(current):
    return {tool.name: tool for tool in report_tools(current)}


def call(tool, **arguments):
    return tool.entrypoint(**arguments)


def upload_datasets(current, thread="report-thread"):
    current.upload(
        thread,
        "data/sales.csv",
        ("region,category,amount\n华东,A,10\n华东,B,20\n华南,A,30\n").encode(),
    )
    current.upload(
        thread,
        "data/sales.json",
        json.dumps(
            [
                {"region": "华东", "category": "A", "amount": 10},
                {"region": "华南", "category": "B", "amount": 20},
            ],
            ensure_ascii=False,
        ).encode("utf-8"),
    )
    current.upload(
        thread,
        "data/sales.jsonl",
        (
            '{"region":"华东","category":"A","amount":10}\n'
            '{"region":"华南","category":"B","amount":20}\n'
        ).encode(),
    )
    workbook = BytesIO()
    pd.DataFrame(
        [
            {"region": "华东", "category": "A", "amount": 10},
            {"region": "华南", "category": "B", "amount": 20},
        ]
    ).to_excel(workbook, index=False, sheet_name="销售")
    current.upload(thread, "data/sales.xlsx", workbook.getvalue())


def upload_manifest_dataset(current, fragments=None, thread="report-thread"):
    dataset_id = "11111111-1111-4111-8111-111111111111"
    base = f"报表/原始数据/{dataset_id}"
    contents = fragments or [
        b'{"region":"\xe5\x8d\x8e\xe4\xb8\x9c","category":"A","amount":10}\n',
        b'{"region":"\xe5\x8d\x8e\xe5\x8d\x97","category":"B","amount":20}\n',
    ]
    items = []
    row_count = 0
    for index, content in enumerate(contents, start=1):
        path = f"{base}/分片/数据-{index:04d}.jsonl"
        current.upload(thread, path, content)
        row_count += len(content.splitlines())
        items.append(
            {
                "path": path,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    manifest = {
        "version": report.DATASET_MANIFEST_VERSION,
        "datasetId": dataset_id,
        "model": "res.partner",
        "fields": [
            {"name": "region", "label": "区域", "type": "char"},
            {"name": "category", "label": "分类", "type": "char"},
            {"name": "amount", "label": "金额", "type": "float"},
        ],
        "rowCount": row_count,
        "columnCount": 3,
        "fragments": items,
        "totalSize": sum(len(content) for content in contents),
        "scope": "domain",
        "selectedCount": 0,
        "timezone": "Asia/Shanghai",
        "generatedAt": "2026-07-21 12:00:00",
        "scopeFingerprint": "a" * 64,
    }
    path = f"{base}/数据集.json"
    current.upload(
        thread,
        path,
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
    )
    return path, manifest


def test_profiles_csv_json_jsonl_and_xlsx(tmp_path):
    current = service(tmp_path)
    upload_datasets(current)
    current_tools = tools(current)

    for path in (
        "data/sales.csv",
        "data/sales.json",
        "data/sales.jsonl",
        "data/sales.xlsx",
    ):
        result = call(
            current_tools["pandas_profile_dataset"],
            path=path,
            sheet="销售" if path.endswith(".xlsx") else None,
            run_context=context(),
        )
        assert result["rowCount"] in {2, 3}
        assert result["columnCount"] == 3
        assert "sample" not in result
        assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= 32 * 1024


def test_manifest_dataset_validates_fragments_and_bounds_explicit_sample(tmp_path):
    current = service(tmp_path)
    path, _manifest = upload_manifest_dataset(current)
    current_tools = tools(current)

    profile = call(current_tools["pandas_profile_dataset"], path=path, run_context=context())
    assert profile["rowCount"] == 2
    assert profile["columnCount"] == 3
    assert "sample" not in profile

    sample = call(
        current_tools["pandas_sample_dataset"],
        path=path,
        columns=["region", "amount"],
        limit=20,
        run_context=context(),
    )
    assert sample["rowCount"] == 2
    assert sample["columnCount"] == 2
    assert sample["rows"] == [
        {"region": "华东", "amount": 10},
        {"region": "华南", "amount": 20},
    ]
    assert len(json.dumps(sample, ensure_ascii=False).encode("utf-8")) <= 32 * 1024

    grouped = call(
        current_tools["pandas_group_dataset"],
        path=path,
        dimensions=["category"],
        metrics=[{"field": "amount", "aggregation": "sum"}],
        run_context=context(),
    )
    assert grouped["rowCount"] == 2


def test_manifest_loader_streams_fragments_into_one_temporary_file(tmp_path):
    current = service(tmp_path)
    path, manifest = upload_manifest_dataset(current)
    with tempfile.TemporaryDirectory() as directory:
        loaded = report._load_dataset_manifest(
            current,
            "report-thread",
            path,
            Path(directory) / "dataset.jsonl",
        )
        assert loaded is not None
        loaded_manifest, local_path = loaded
        assert loaded_manifest == manifest
        assert isinstance(local_path, str)
        assert Path(local_path).read_bytes() == b"".join(
            current.file_bytes("report-thread", fragment["path"])[0]
            for fragment in manifest["fragments"]
        )


def test_final_report_config_uses_validated_chinese_uuid_path(tmp_path):
    current = service(tmp_path)
    manifest_path, manifest = upload_manifest_dataset(current)
    manifest_content, _mime = current.file_bytes("report-thread", manifest_path)
    result = call(
        tools(current)["pandas_create_report_config"],
        manifest_path=manifest_path,
        dataset_hash=hashlib.sha256(manifest_content).hexdigest(),
        title="区域销售分析",
        dimensions=["region"],
        metrics=[{"field": "amount", "aggregation": "sum", "label": "销售额"}],
        chart_type="bar",
        chart_metric="amount:sum",
        analysis_notes=["华东与华南按相同口径比较。"],
        purpose="比较区域销售表现并识别差异。",
        sections=["overview", "chart", "analysis"],
        run_context=context(),
    )
    assert result["configPath"] == f"报表/配置/{result['reportId']}/报表配置.json"
    config_content, _mime = current.file_bytes("report-thread", result["configPath"])
    config = json.loads(config_content)
    assert config["version"] == report.REPORT_CONFIG_VERSION
    assert config["reportId"] == result["reportId"]
    assert config["manifestPath"] == manifest_path
    assert config["analysis"]["metrics"][0]["label"] == "销售额"
    assert config["presentation"] == {
        "purpose": "比较区域销售表现并识别差异。",
        "sections": ["overview", "chart", "analysis"],
    }
    assert "fragments" not in config
    assert "rows" not in config
    assert "sample" not in config
    assert manifest["scope"] == "domain"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"purpose": ""}, "报表目的"),
        ({"sections": []}, "报表章节"),
        ({"sections": ["sample"]}, "报表章节"),
    ],
)
def test_final_report_config_rejects_explicit_empty_presentation(tmp_path, override, message):
    current = service(tmp_path)
    manifest_path, _manifest = upload_manifest_dataset(current)
    manifest_content, _mime = current.file_bytes("report-thread", manifest_path)
    arguments = {
        "manifest_path": manifest_path,
        "dataset_hash": hashlib.sha256(manifest_content).hexdigest(),
        "title": "区域销售分析",
        "dimensions": ["region"],
        "metrics": [{"field": "amount", "aggregation": "sum", "label": "销售额"}],
        "chart_type": "bar",
        "chart_metric": "amount:sum",
        "run_context": context(),
        **override,
    }

    with pytest.raises(WorkspaceError, match=message):
        call(tools(current)["pandas_create_report_config"], **arguments)


def test_manifest_rejects_hash_path_and_row_count_mismatches(tmp_path):
    current = service(tmp_path)
    path, manifest = upload_manifest_dataset(current)

    for mutation, message in (
        (lambda value: value["fragments"][0].update({"sha256": "0" * 64}), "SHA-256"),
        (lambda value: value["fragments"][0].update({"path": "../escape.jsonl"}), "路径"),
        (lambda value: value.update({"rowCount": 99}), "总行数"),
    ):
        changed = json.loads(json.dumps(manifest))
        mutation(changed)
        current.upload(
            "report-thread",
            path,
            json.dumps(changed, ensure_ascii=False).encode("utf-8"),
        )
        with pytest.raises(WorkspaceError, match=message):
            call(
                tools(current)["pandas_profile_dataset"],
                path=path,
                run_context=context(),
            )


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
            path="data/sales.csv",
            run_context=context(),
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
        path="data/sales.csv",
        rows=["region"],
        columns=["category"],
        value="amount",
        aggregation="sum",
        run_context=context(),
    )
    assert pivot["rowCount"] == 2

    concatenated = call(
        current_tools["pandas_concat_datasets"],
        paths=["data/sales.json", "data/sales.jsonl"],
        source_labels=["JSON", "JSONL"],
        run_context=context(),
    )
    assert concatenated["rowCount"] == 4
    assert concatenated["path"].startswith("报表/分析数据/")
    content, _mime = current.file_bytes("report-thread", concatenated["path"])
    assert {json.loads(line)["_source"] for line in content.splitlines()} == {"JSON", "JSONL"}

    isolated = call(
        current_tools["pandas_profile_dataset"],
        path="data/sales.csv",
        run_context=context("other-thread"),
    )
    assert isolated["rowCount"] == 1


def test_dataset_shape_and_memory_limits_are_enforced(tmp_path, monkeypatch):
    current = service(tmp_path)
    columns = [f"c{index}" for index in range(101)]
    current.upload(
        "report-thread",
        "data/wide.csv",
        (",".join(columns) + "\n" + ",".join("1" for _item in columns) + "\n").encode("utf-8"),
    )

    with pytest.raises(WorkspaceError, match="100 列"):
        call(
            tools(current)["pandas_profile_dataset"],
            path="data/wide.csv",
            run_context=context(),
        )

    current.upload(
        "report-thread",
        "data/tall.csv",
        ("value\n" + "1\n" * (report.MAX_DATASET_ROWS + 1)).encode("utf-8"),
    )
    with pytest.raises(WorkspaceError, match="100000 行"):
        call(
            tools(current)["pandas_profile_dataset"],
            path="data/tall.csv",
            run_context=context(),
        )

    current.upload("report-thread", "data/memory.csv", b"value\nexpanded text\n")
    monkeypatch.setattr(report, "MAX_EXPANDED_BYTES", 1)
    with pytest.raises(WorkspaceError, match="128 MiB"):
        call(
            tools(current)["pandas_profile_dataset"],
            path="data/memory.csv",
            run_context=context(),
        )


def test_delimited_loaders_bound_rows_before_creating_dataframes(tmp_path, monkeypatch):
    current = service(tmp_path)
    upload_datasets(current)
    calls = {}
    original = report.PandasTools.create_pandas_dataframe

    def tracking(self, name, function_name, parameters):
        key = function_name + ("_lines" if parameters.get("lines") else "")
        calls[key] = dict(parameters)
        return original(self, name, function_name, parameters)

    monkeypatch.setattr(report.PandasTools, "create_pandas_dataframe", tracking)
    current_tools = tools(current)
    call(current_tools["pandas_profile_dataset"], path="data/sales.csv", run_context=context())
    call(current_tools["pandas_profile_dataset"], path="data/sales.jsonl", run_context=context())

    assert calls["read_csv"]["nrows"] == report.MAX_DATASET_ROWS + 1
    assert calls["read_json_lines"]["nrows"] == report.MAX_DATASET_ROWS + 1


@pytest.mark.parametrize(
    ("path", "content"),
    [
        ("data/memory.csv", b"value\nexpanded text\nexpanded text\n"),
        (
            "data/memory.jsonl",
            b'{"value":"expanded text"}\n{"value":"expanded text"}\n',
        ),
        (
            "data/memory.json",
            b'[{"value":"expanded text"},{"value":"expanded text"}]',
        ),
    ],
)
def test_memory_is_rejected_before_pandas_materializes_dataset(
    tmp_path, monkeypatch, path, content
):
    current = service(tmp_path)
    current.upload("report-thread", path, content)
    monkeypatch.setattr(report, "MAX_EXPANDED_BYTES", 1)
    monkeypatch.setattr(
        report.PandasTools,
        "create_pandas_dataframe",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("pandas loader called")),
    )

    with pytest.raises(WorkspaceError, match="数据集展开内存超过"):
        call(tools(current)["pandas_profile_dataset"], path=path, run_context=context())


def test_json_requires_a_top_level_array_before_pandas_loads_it(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.upload("report-thread", "data/columns.json", b'{"value":{"0":"one"}}')
    monkeypatch.setattr(
        report.PandasTools,
        "create_pandas_dataframe",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("pandas loader called")),
    )

    with pytest.raises(WorkspaceError, match="JSON 数据集仅支持顶层数组"):
        call(
            tools(current)["pandas_profile_dataset"],
            path="data/columns.json",
            run_context=context(),
        )


def test_json_shape_is_rejected_before_pandas_materializes_the_dataset(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.upload(
        "report-thread",
        "data/tall.json",
        json.dumps([{"value": 1}, {"value": 2}, {"value": 3}]).encode(),
    )
    current.upload(
        "report-thread",
        "data/wide.json",
        json.dumps([{"first": 1, "second": 2}]).encode(),
    )
    monkeypatch.setattr(
        report.PandasTools,
        "create_pandas_dataframe",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("pandas loader called")),
    )

    monkeypatch.setattr(report, "MAX_DATASET_ROWS", 2)
    with pytest.raises(WorkspaceError, match="数据集超过.*行"):
        call(tools(current)["pandas_profile_dataset"], path="data/tall.json", run_context=context())

    monkeypatch.setattr(report, "MAX_DATASET_ROWS", 100_000)
    monkeypatch.setattr(report, "MAX_DATASET_COLUMNS", 1)
    with pytest.raises(WorkspaceError, match="数据集超过.*列"):
        call(tools(current)["pandas_profile_dataset"], path="data/wide.json", run_context=context())


def test_xlsx_expanded_size_is_rejected_before_pandas_loads_it(tmp_path, monkeypatch):
    current = service(tmp_path)
    upload_datasets(current)
    monkeypatch.setattr(report, "MAX_EXPANDED_BYTES", 1)
    monkeypatch.setattr(
        report.PandasTools,
        "create_pandas_dataframe",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("pandas loader called")),
    )

    with pytest.raises(WorkspaceError, match="XLSX 展开内容超过"):
        call(
            tools(current)["pandas_profile_dataset"],
            path="data/sales.xlsx",
            sheet="销售",
            run_context=context(),
        )

    monkeypatch.setattr(report, "MAX_EXPANDED_BYTES", 128 * 1024 * 1024)
    monkeypatch.setattr(report, "MAX_XLSX_MEMBERS", 1)
    with pytest.raises(WorkspaceError, match="XLSX 压缩包成员超过"):
        call(
            tools(current)["pandas_profile_dataset"],
            path="data/sales.xlsx",
            sheet="销售",
            run_context=context(),
        )


def test_chart_outputs_png_and_download_only_html_without_confirmation(tmp_path):
    current = service(tmp_path)
    upload_datasets(current)
    current_tools = tools(current)
    for name in current_tools:
        assert current_tools[name].requires_confirmation is not True

    result = call(
        current_tools["pandas_generate_chart"],
        path="data/sales.csv",
        chart_type="bar",
        x="region",
        y="amount",
        aggregation="sum",
        title="区域销售额",
        run_context=context(),
    )
    png, png_mime = current.file_bytes("report-thread", result["pngPath"])
    html, html_mime = current.file_bytes("report-thread", result["htmlPath"])
    assert result["pngPath"].startswith("报表/图表/")
    assert result["htmlPath"].startswith("报表/图表/")
    assert png.startswith(b"\x89PNG")
    assert png_mime == "image/png"
    assert b"plotly" in html.lower()
    assert html_mime == "text/html"
    assert WORKSPACE_ROOT not in html.decode("utf-8")

    pie = call(
        current_tools["pandas_generate_chart"],
        path="data/sales.csv",
        chart_type="pie",
        x="region",
        run_context=context(),
    )
    assert pie["pointCount"] == 2

    current.upload(
        "report-thread",
        "data/duplicates.csv",
        ("region,category,amount\n华东,A,10\n华东,A,20\n").encode(),
    )
    with pytest.raises(WorkspaceError, match="指定聚合方式"):
        call(
            current_tools["pandas_generate_chart"],
            path="data/duplicates.csv",
            chart_type="bar",
            x="region",
            y="amount",
            group="category",
            run_context=context(),
        )
