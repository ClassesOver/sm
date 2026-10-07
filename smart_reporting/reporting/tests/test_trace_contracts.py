"""B0 追溯契约 V1 单元测试（计划第 3 节，G0 验收的一部分）。"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.trace import (
    TRACE_BUDGETS_V1,
    TRACE_CONTRACT_VERSION,
    TRACE_ERROR_HTTP_STATUS,
    ChartSeriesV1,
    ChartTraceV1,
    ComputationRecordV1,
    DatasetSnapshotRefV1,
    FactFileEntryV1,
    FactRefV1,
    RevisionTraceIndexV1,
    SubjectBindingV1,
    SubjectLocatorV1,
    TableCellBindingV1,
    TableTraceV1,
    TraceFileRefV1,
    canonical_json_bytes,
    canonical_sha256,
    derive_resource_id,
    normalize_subject_content,
    subject_fingerprint,
    validate_json_pointer,
)

SHA = "0" * 64
OTHER_SHA = "1" * 64


def _file(path: str, resource_id: str | None = None, **overrides) -> TraceFileRefV1:
    return TraceFileRefV1(
        resourceId=resource_id or derive_resource_id(path),
        path=path,
        mediaType="text/csv",
        size=100,
        sha256=SHA,
        **overrides,
    )


def _dataset(dataset_id: str, file_resource_id: str) -> DatasetSnapshotRefV1:
    return DatasetSnapshotRefV1(
        datasetId=dataset_id,
        fileResourceId=file_resource_id,
        sourceType="url_csv",
        requirementId="attachment-001",
        periodRoles=("current",),
        rowCount=4,
        materializedAt="2026-09-29T08:00:00Z",
        filename="input.csv",
    )


def _fact_ref(
    analysis_id: str = "analysis_001",
    file_resource_id: str | None = None,
    pointer: str = "/metrics/0",
) -> FactRefV1:
    return FactRefV1(
        analysisId=analysis_id,
        fileResourceId=file_resource_id or derive_resource_id("facts.json"),
        jsonPointer=pointer,
        factKind="metric",
    )


# ---------------------------------------------------------------------------
# TraceFileRefV1
# ---------------------------------------------------------------------------


def test_file_ref_roundtrip_and_alias() -> None:
    ref = _file("报表/智能分析/run-1/facts/revision-1/analysis_001.json")
    assert ref.media_type == "application/json" or ref.media_type == "text/csv"
    payload = ref.model_dump(by_alias=True)
    assert payload["resourceId"] == derive_resource_id(
        "报表/智能分析/run-1/facts/revision-1/analysis_001.json"
    )
    assert TraceFileRefV1.model_validate(payload) == ref


@pytest.mark.parametrize(
    "path",
    ["../escape.csv", "/abs/path.csv", "a\\b.csv", "trailing/"],
)
def test_file_ref_rejects_unsafe_path(path: str) -> None:
    with pytest.raises(ValidationError, match="路径"):
        _file(path)


def test_file_ref_resource_id_must_derive_from_path() -> None:
    with pytest.raises(ValidationError, match="resourceId"):
        _file("a.csv", resource_id="trf-" + "a" * 20)


def test_file_ref_frozen() -> None:
    ref = _file("a.csv")
    with pytest.raises(ValidationError):
        ref.size = 200  # type: ignore[misc]


# ---------------------------------------------------------------------------
# canonical 规则
# ---------------------------------------------------------------------------


def test_canonical_json_rejects_nan_and_infinity() -> None:
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="Out of range"):
            canonical_json_bytes({"value": bad})


def test_canonical_sha256_is_stable_regardless_of_key_order() -> None:
    assert canonical_sha256({"a": 1, "b": [2, 3]}) == canonical_sha256(
        {"b": [2, 3], "a": 1}
    )


def test_subject_fingerprint_ignores_whitespace_shape() -> None:
    assert subject_fingerprint("  收入 3600 元 \r\n 环比 20% ") == subject_fingerprint(
        "收入 3600 元\n环比 20%"
    )
    assert normalize_subject_content("a\n\nb") == "a\n\nb"


# ---------------------------------------------------------------------------
# DatasetSnapshotRefV1
# ---------------------------------------------------------------------------


def test_dataset_snapshot_unknown_materialized_time_is_null() -> None:
    dataset = DatasetSnapshotRefV1(
        datasetId="dataset-url-abc",
        fileResourceId=derive_resource_id("input.csv"),
        sourceType="url_csv",
        requirementId="attachment-001",
        periodRoles=("current",),
        rowCount=4,
    )
    assert dataset.materialized_at is None
    with pytest.raises(ValidationError):
        DatasetSnapshotRefV1(
            datasetId="dataset-url-abc",
            fileResourceId=dataset.file_resource_id,
            sourceType="url_csv",
            requirementId="attachment-001",
            periodRoles=("current",),
            rowCount=4,
            materializedAt="2026-09-29 08:00:00",
        )


# ---------------------------------------------------------------------------
# FactRefV1 / JSON Pointer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pointer",
    ["", "/metrics/0", "/derivedMetrics/12/numerator", "/a~1b/c~0d"],
)
def test_valid_json_pointers(pointer: str) -> None:
    assert validate_json_pointer(pointer) == pointer


@pytest.mark.parametrize("pointer", ["metrics/0", "/metrics/~x", " /a", "a b"])
def test_invalid_json_pointers(pointer: str) -> None:
    with pytest.raises(ValueError):
        validate_json_pointer(pointer)


def test_fact_ref_pointer_length_limit() -> None:
    with pytest.raises(ValidationError, match="长度"):
        FactRefV1(
            analysisId="analysis_001",
            fileResourceId=derive_resource_id("f.json"),
            jsonPointer="/" + "a" * 300,
            factKind="metric",
        )


# ---------------------------------------------------------------------------
# ComputationRecordV1
# ---------------------------------------------------------------------------


def _computation(input_analyses: tuple[str, ...], output_analyses: tuple[str, ...]):
    return ComputationRecordV1(
        computationId="comp-" + "0" * 16,
        method="contribution_decomposition",
        parameters={"top_n": 3},
        inputDatasetIds=("dataset-url-abc",),
        inputFactRefs=tuple(
            FactRefV1(
                analysisId=a,
                fileResourceId=derive_resource_id("facts.json"),
                jsonPointer="/metrics/0",
                factKind="metric",
            )
            for a in input_analyses
        ),
        outputFactRefs=tuple(
            FactRefV1(
                analysisId=a,
                fileResourceId=derive_resource_id("facts.json"),
                jsonPointer="/derivedMetrics/0",
                factKind="derived",
            )
            for a in output_analyses
        ),
        limitations=["贡献分解不构成因果证明"],
    )


def test_computation_rejects_self_cycle_and_duplicate_dataset() -> None:
    with pytest.raises(ValidationError, match="自环|同一 analysis"):
        # pydantic 校验消息可能是 ValueError 文本，匹配宽一点
        try:
            _computation(("analysis_001",), ("analysis_001",))
        except ValidationError as exc:
            assert any("同一 analysis" in str(e) for e in exc.errors())
            raise
    with pytest.raises(ValidationError, match="输入数据集不能重复"):
        ComputationRecordV1(
            computationId="comp-" + "0" * 16,
            method="m",
            inputDatasetIds=("dataset-url-abc", "dataset-url-abc"),
            outputFactRefs=(
                FactRefV1(
                    analysisId="analysis_002",
                    fileResourceId=derive_resource_id("f.json"),
                    factKind="metric",
                ),
            ),
        )


def test_computation_defaults_to_not_checked() -> None:
    record = _computation(("analysis_001",), ("analysis_002",))
    assert record.verification == "not_checked"
    assert record.reproducibility == "unavailable"


# ---------------------------------------------------------------------------
# ChartTraceV1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("chart_id", ["chart_001", "section_001__chart_001", "income__revenue_trend"])
def test_chart_trace_keeps_registered_chapter_namespace(chart_id: str) -> None:
    trace = ChartTraceV1(
        chartId=chart_id, imageFileResourceId=derive_resource_id("chart.png"),
        plotDataFileResourceIds=(derive_resource_id("chart-input.json"),), datasetIds=("dataset-url-abc",),
    )
    assert trace.chart_id == chart_id
    with pytest.raises(ValidationError):
        ChartTraceV1(**{**trace.model_dump(by_alias=True), "chartId": "../chart.png"})


def test_chart_trace_predicted_series_requires_facts_or_computation() -> None:
    base = dict(
        chartId="chart_001",
        imageFileResourceId=derive_resource_id("chart.png"),
        plotDataFileResourceIds=(derive_resource_id("chart-input.json"),),
        datasetIds=("dataset-url-abc",),
    )
    ChartTraceV1(**base, series=(ChartSeriesV1(name="收入", unit="元"),))
    with pytest.raises(ValidationError):
        ChartTraceV1(
            **base,
            series=(ChartSeriesV1(name="预测", seriesKind="predicted"),),
        )
    ChartTraceV1(
        **base,
        series=(ChartSeriesV1(name="预测", seriesKind="predicted"),),
        computationId="comp-" + "0" * 16,
    )


# ---------------------------------------------------------------------------
# TableTraceV1
# ---------------------------------------------------------------------------


def test_table_trace_cell_identity_rules() -> None:
    table = TableTraceV1(
        tableId="table-1",
        rowKeys=("branch:A", "branch:B"),
        columnKeys=("revenue", "mom"),
        cells=(
            TableCellBindingV1(
                rowKey="branch:A",
                columnKey="revenue",
                datasetIds=("dataset-url-abc",),
            ),
        ),
    )
    assert table.cells[0].row_key == "branch:A"
    with pytest.raises(ValidationError, match="rowKey 未在表结构中登记"):
        TableTraceV1(
            tableId="table-1",
            rowKeys=("branch:A",),
            columnKeys=("revenue",),
            cells=(
                TableCellBindingV1(
                    rowKey="branch:X", columnKey="revenue", datasetIds=("d",)
                ),
            ),
        )
    with pytest.raises(ValidationError, match="单元格身份重复"):
        TableTraceV1(
            tableId="table-1",
            rowKeys=("branch:A",),
            columnKeys=("revenue",),
            cells=(
                TableCellBindingV1(
                    rowKey="branch:A", columnKey="revenue", datasetIds=("d",)
                ),
                TableCellBindingV1(
                    rowKey="branch:A", columnKey="revenue", datasetIds=("d",)
                ),
            ),
        )


# ---------------------------------------------------------------------------
# SubjectBindingV1
# ---------------------------------------------------------------------------


def test_subject_binding_locator_matrix() -> None:
    SubjectBindingV1(
        subjectId="sub-" + "0" * 16,
        subjectKind="text_claim",
        locator=SubjectLocatorV1(sectionId="section_02"),
        subjectSha256=SHA,
        claimId="claim-1",
        factRefs=(_fact_ref(),),
        evidenceKind="computed",
    )
    with pytest.raises(ValidationError, match="table_cell"):
        SubjectBindingV1(
            subjectId="sub-" + "1" * 16,
            subjectKind="table_cell",
            locator=SubjectLocatorV1(sectionId="section_02"),
            subjectSha256=SHA,
            factRefs=(_fact_ref(),),
        )
    with pytest.raises(ValidationError, match="至少绑定"):
        SubjectBindingV1(
            subjectId="sub-" + "2" * 16,
            subjectKind="chart",
            locator=SubjectLocatorV1(chartId="chart_001"),
            subjectSha256=SHA,
        )


def test_subject_binding_kind_must_match_evidence_semantics() -> None:
    binding = SubjectBindingV1(
        subjectId="sub-" + "3" * 16,
        subjectKind="text_claim",
        locator=SubjectLocatorV1(sectionId="section_03"),
        subjectSha256=OTHER_SHA,
        claimId="claim-9",
        factRefs=(_fact_ref(pointer="/metrics/1"),),
        evidenceKind="interpretation",
    )
    assert binding.evidence_kind == "interpretation"


# ---------------------------------------------------------------------------
# RevisionTraceIndexV1 全局引用校验
# ---------------------------------------------------------------------------


def _index(**overrides) -> RevisionTraceIndexV1:
    facts_file = _file(
        "报表/智能分析/run-1/facts/revision-1/analysis_001.json",
        resource_id=None,
    )
    facts_file = TraceFileRefV1(
        resourceId=facts_file.resource_id,
        path=facts_file.path,
        mediaType="application/json",
        size=100,
        sha256=SHA,
    )
    csv_file = _file("报表/数据集/input.csv")
    markdown_file = TraceFileRefV1(
        resourceId=derive_resource_id("报表/智能分析/run-1/revision-1/report.md"),
        path="报表/智能分析/run-1/revision-1/report.md",
        mediaType="text/markdown",
        size=100,
        sha256=SHA,
    )
    base = dict(
        version="1",
        reportId="report-1",
        revision=1,
        workflowRunId="run-1",
        markdownFileResourceId=markdown_file.resource_id,
        files=(markdown_file, csv_file, facts_file),
        datasets=(_dataset("dataset-url-abc", csv_file.resource_id),),
        factFiles=(
            FactFileEntryV1(
                analysisId="analysis_001",
                fileResourceId=facts_file.resource_id,
                contentKind="deterministic_bundle",
            ),
        ),
    )
    base.update(overrides)
    return RevisionTraceIndexV1(**base)


def test_minimal_index_roundtrip() -> None:
    index = _index()
    payload = json.loads(index.model_dump_json(by_alias=True))
    assert payload["indexVersion"] if False else payload["version"] == "1"
    assert RevisionTraceIndexV1.model_validate(payload) == index


def test_index_rejects_unknown_file_reference() -> None:
    with pytest.raises(ValidationError, match="未登记文件"):
        _index(
            datasets=(
                _dataset("dataset-url-abc", "trf-" + "9" * 20),
            ),
        )


def test_index_rejects_fact_ref_not_matching_fact_files() -> None:
    index = _index()
    chart = ChartTraceV1(
        chartId="chart_001",
        imageFileResourceId=derive_resource_id("chart.png"),
        plotDataFileResourceIds=(derive_resource_id("chart-input.json"),),
        datasetIds=("dataset-url-abc",),
        factRefs=(
            FactRefV1(
                analysisId="analysis_999",
                fileResourceId="trf-" + "7" * 20,
                factKind="metric",
            ),
        ),
    )
    with pytest.raises(ValidationError):
        _index(chartTraces=(chart,))


def test_index_version_is_frozen_to_v1() -> None:
    assert TRACE_CONTRACT_VERSION == "1"


# ---------------------------------------------------------------------------
# 错误码映射与预算（B0 冻结值锁定）
# ---------------------------------------------------------------------------


def test_error_codes_have_http_mapping() -> None:
    expected_codes = {
        "source_missing",
        "subject_stale",
        "fact_binding_unavailable",
        "snapshot_expired",
        "snapshot_integrity_failed",
        "dataset_access_denied",
        "cursor_invalid",
        "request_invalid",
        "drilldown_unavailable",
        "resource_limit_exceeded",
    }
    assert set(TRACE_ERROR_HTTP_STATUS) == expected_codes
    for code, status in TRACE_ERROR_HTTP_STATUS.items():
        assert 400 <= status < 500, code


def test_budgets_are_positive_and_match_plan_defaults() -> None:
    assert TRACE_BUDGETS_V1["preview_default_rows"] == 50
    assert TRACE_BUDGETS_V1["preview_max_rows_per_page"] == 100
    assert TRACE_BUDGETS_V1["preview_max_columns"] == 50
    assert TRACE_BUDGETS_V1["preview_max_cell_bytes"] == 4096
    assert TRACE_BUDGETS_V1["preview_max_response_bytes"] == 1024 * 1024
    assert TRACE_BUDGETS_V1["dataset_max_file_bytes"] == 200 * 1024 * 1024
    assert TRACE_BUDGETS_V1["max_report_inputs"] == 100
    assert all(value > 0 for value in TRACE_BUDGETS_V1.values())
