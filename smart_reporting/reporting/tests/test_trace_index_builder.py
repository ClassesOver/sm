"""B1 revision 追溯索引构建测试（发布侧 CSV 层）。"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.data_sources import DatasetHandle
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile, DatasetLineage
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace import RevisionTraceIndexV1
from smart_reporting.reporting.trace.index_builder import (
    TRACE_INDEX_FILENAME,
    build_csv_trace_index,
    encode_trace_index,
    trace_index_path_for,
)

SHA = "a" * 64
OTHER_SHA = "b" * 64


def _handle(dataset_id: str, **overrides) -> DatasetHandle:
    values = dict(
        dataset_id=dataset_id,
        source_id="mcp-url",
        source_type="url_csv",
        path=f"报表/数据集/run1/{dataset_id}.csv",
        row_count=4,
        size=100,
        sha256=SHA,
        requirement_id="attachment-001",
        sql_hash=OTHER_SHA,
        filename="收入明细.csv",
        materialized_at="2026-09-29T08:00:00Z",
    )
    values.update(overrides)
    return DatasetHandle(**values)


def _lineage(dataset_id: str, **overrides) -> DatasetLineage:
    values = dict(
        datasetId=dataset_id,
        sourceId="mcp-url",
        sourceType="url_csv",
        requirementId="attachment-001",
        sqlHash=OTHER_SHA,
        rowCount=4,
        size=100,
        sha256=SHA,
    )
    values.update(overrides)
    return DatasetLineage(**values)


MARKDOWN = ArtifactFile(
    path="报表/智能分析/run1/revision-1/report.md",
    mediaType="text/markdown",
    size=200,
    sha256=OTHER_SHA,
)


def _build(handles, lineage, **overrides):
    params = dict(
        handles=handles,
        lineage=lineage,
        report_id="run1",
        revision=1,
        workflow_run_id="run1",
        markdown_file=MARKDOWN,
        profile_hash=SHA,
    )
    params.update(overrides)
    return build_csv_trace_index(**params)


def test_build_csv_trace_index_datasets_layer() -> None:
    index = _build(
        (_handle("dataset-url-abc0001"), _handle("dataset-def0002")),
        (_lineage("dataset-url-abc0001"), _lineage("dataset-def0002")),
    )
    assert index.revision == 1
    assert len(index.files) == 3  # markdown + 2 CSV
    assert {f.media_type for f in index.files} == {"text/markdown", "text/csv"}
    assert len(index.datasets) == 2
    first = index.datasets[0]
    assert first.source_type == "url_csv"
    assert first.materialized_at == "2026-09-29T08:00:00Z"
    assert first.filename == "收入明细.csv"
    assert first.row_count == 4
    assert first.sql_hash == OTHER_SHA
    # dataset 引用的文件与注册表一致（契约全局校验在构造时已跑通）。
    known = {f.resource_id: f for f in index.files}
    assert known[first.file_resource_id].sha256 == SHA


def test_snapshot_preserves_business_name_and_query_through_state() -> None:
    handle = _handle(
        "dataset-abc0001", source_type="starrocks_materialized", filename=None,
        business_label="医疗收入月度明细（2025，本期）",
        query_sql="SELECT indicator_value FROM rj.income",
    )
    restored = DatasetHandle.from_state(handle.public_dict())
    index = _build(
        (restored,), (_lineage("dataset-abc0001", sourceType="starrocks_materialized"),),
    )
    assert index.datasets[0].business_label == handle.business_label
    assert index.datasets[0].query_sql == handle.query_sql
    assert index.datasets[0].sql_hash == handle.sql_hash


def test_build_rejects_handle_lineage_mismatch() -> None:
    with pytest.raises(ReportingError, match="未精确对应"):
        _build(
            (_handle("dataset-url-abc0001"),),
            (_lineage("dataset-url-abc0001"), _lineage("dataset-other9999")),
        )
    # 身份字段不一致同样失败关闭。
    with pytest.raises(ReportingError, match="身份不一致"):
        _build(
            (_handle("dataset-url-abc0001"),),
            (_lineage("dataset-url-abc0001", sha256=OTHER_SHA),),
        )


def test_build_rejects_empty_handles() -> None:
    with pytest.raises(ReportingError, match="缺少数据集句柄"):
        _build((), ())


def test_encode_is_canonical_and_roundtrips() -> None:
    index = _build((_handle("dataset-url-abc0001"),), (_lineage("dataset-url-abc0001"),))
    content = encode_trace_index(index)
    payload = json.loads(content)
    assert payload["version"] == "1"
    assert RevisionTraceIndexV1.model_validate(payload) == index
    # canonical：两次编码字节一致。
    assert encode_trace_index(index) == content


def test_trace_index_path_lives_beside_manifest() -> None:
    assert trace_index_path_for("报表/智能分析/run1/manifest.json") == (
        f"报表/智能分析/run1/{TRACE_INDEX_FILENAME}"
    )


# ---------------------------------------------------------------------------
# B3 图表层：归档图片/chart-input 文件与 ChartTraceV1 联合登记
# ---------------------------------------------------------------------------


def _chart_trace():
    from smart_reporting.reporting.trace.contracts_v1 import ChartTraceV1, derive_resource_id

    return ChartTraceV1(
        chartId="chart_001",
        imageFileResourceId=derive_resource_id("报表/智能分析/run1/revision-1/chart-001.png"),
        plotDataFileResourceIds=(
            derive_resource_id(
                "报表/智能分析/run1/revision-1/chart-001--1.chart-input.json"
            ),
        ),
        datasetIds=("dataset-url-abc0001",),
        transformNotes=("作图数据由服务端 chart-input/v1 物化",),
    )


def test_index_registers_chart_trace_with_archived_files() -> None:
    from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity

    index = _build(
        (_handle("dataset-url-abc0001"),),
        (_lineage("dataset-url-abc0001"),),
        chart_trace_files=(
            FileIdentity(
                path="报表/智能分析/run1/revision-1/chart-001.png",
                size=10,
                sha256=SHA,
            ),
            FileIdentity(
                path="报表/智能分析/run1/revision-1/chart-001--1.chart-input.json",
                size=10,
                sha256=OTHER_SHA,
            ),
        ),
        chart_traces=(_chart_trace(),),
    )
    assert len(index.files) == 4  # markdown + CSV + 图 + chart-input
    assert index.chart_traces[0].chart_id == "chart_001"
    media = {f.path: f.media_type for f in index.files}
    assert media["报表/智能分析/run1/revision-1/chart-001.png"] == "image/png"
    assert (
        media["报表/智能分析/run1/revision-1/chart-001--1.chart-input.json"]
        == "application/json"
    )


def test_index_rejects_chart_trace_with_unknown_files() -> None:
    with pytest.raises(ValidationError):
        _build(
            (_handle("dataset-url-abc0001"),),
            (_lineage("dataset-url-abc0001"),),
            chart_traces=(_chart_trace(),),  # 图片与 chart-input 未登记
        )
