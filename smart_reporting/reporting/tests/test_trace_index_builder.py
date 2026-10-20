"""B1 revision 追溯索引构建测试（发布侧 CSV 层）。"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.data_sources import DatasetHandle
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile, DatasetLineage
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace import RevisionTraceIndexV1
from smart_reporting.reporting.trace.contracts_v1 import (
    SubjectBindingV1,
    derive_resource_id,
)
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


TABLE_SOURCE = dict(path="报表/智能分析/run1/evidence/table.json", size=30, sha256=SHA)


def _table_subject(path=TABLE_SOURCE["path"], *, fact_file=None):
    fact_refs = () if fact_file is None else ({
        "analysisId": "analysis_001", "fileResourceId": derive_resource_id(fact_file.path),
        "factKind": "metric", "jsonPointer": "/metrics/0",
    },)
    return SubjectBindingV1.model_validate({
        "subjectId": "sub-" + "4" * 16, "subjectKind": "text_claim",
        "locator": {"sectionId": "section_001"}, "subjectSha256": SHA,
        "claimId": "claim-table", "factRefs": fact_refs,
        "numberReference": {
            "claimId": "claim-table", "token": "table-token", "statementSha256": SHA,
            "tableDerivation": {"unit": "万元", "operands": [{
                "fileResourceId": derive_resource_id(path), "tablePointer": "/tables/0",
                "rowIndex": 0, "columnIndex": 1, "coefficient": "1",
            }]},
        },
    })


def _build_table(**kwargs):
    return _build(
        (_handle("dataset-url-abc0001"),), (_lineage("dataset-url-abc0001"),), **kwargs,
    )


def test_table_sources_register_referenced_identities_without_fact_files():
    unused = {**TABLE_SOURCE, "path": "unused.json"}
    second = {**TABLE_SOURCE, "path": "second.json"}
    subject = _table_subject()
    second_subject = _table_subject(second["path"]).model_copy(update={
        "subject_id": "sub-" + "5" * 16,
    })
    sources = (TABLE_SOURCE, unused, second, TABLE_SOURCE)
    index = _build_table(table_source_files=sources, subject_bindings=(subject, second_subject))
    assert {file.path for file in index.files} == {
        MARKDOWN.path, _handle("dataset-url-abc0001").path, TABLE_SOURCE["path"], second["path"],
    }
    assert index.fact_files == ()
    assert index.subject_bindings == (subject, second_subject)
    assert encode_trace_index(index) == encode_trace_index(_build_table(
        table_source_files=tuple(reversed(sources)), subject_bindings=(subject, second_subject),
    ))
    assert RevisionTraceIndexV1.model_validate_json(encode_trace_index(index)) == index


@pytest.mark.parametrize("sources", [
    (),
    ({**TABLE_SOURCE, "size": 0},),
    ({**TABLE_SOURCE, "sha256": "invalid"},),
    ({**TABLE_SOURCE, "size": None},),
    ({"path": TABLE_SOURCE["path"]},),
    (TABLE_SOURCE, {**TABLE_SOURCE, "size": 31}, TABLE_SOURCE),
    (TABLE_SOURCE, {**TABLE_SOURCE, "size": None}, TABLE_SOURCE),
    ({**TABLE_SOURCE, "size": None}, TABLE_SOURCE),
])
@pytest.mark.parametrize("fact_backed", [False, True])
def test_invalid_table_sources_only_degrade_affected_subjects(sources, fact_backed):
    fact_file = ArtifactFile(
        path="facts.json", mediaType="application/json", size=40, sha256=OTHER_SHA,
    )
    subject = _table_subject(fact_file=fact_file if fact_backed else None)
    index = _build_table(
        fact_files={"analysis_001": fact_file},
        table_source_files=sources, subject_bindings=(subject,),
    )
    assert len(index.datasets) == 1
    assert len(index.fact_files) == 1
    assert TABLE_SOURCE["path"] not in {file.path for file in index.files}
    if fact_backed:
        assert index.subject_bindings[0].fact_refs == subject.fact_refs
        assert index.subject_bindings[0].number_reference.table_derivation is None
    else:
        assert index.subject_bindings == ()
    RevisionTraceIndexV1.model_validate_json(encode_trace_index(index))


def test_fractional_table_source_size_only_degrades_affected_subjects():
    fact_file = ArtifactFile(
        path="facts.json", mediaType="application/json", size=40, sha256=OTHER_SHA,
    )
    affected = _table_subject()
    unaffected = _table_subject("independent.json").model_copy(update={
        "subject_id": "sub-" + "5" * 16,
    })
    index = _build_table(
        fact_files={"analysis_001": fact_file},
        table_source_files=(
            {**TABLE_SOURCE, "size": 30.5},
            {**TABLE_SOURCE, "size": 30},
            {"path": "independent.json", "size": 12, "sha256": OTHER_SHA},
        ),
        subject_bindings=(affected, unaffected),
    )
    assert {item.subject_id for item in index.subject_bindings} == {unaffected.subject_id}
    assert {file.path for file in index.files} >= {"independent.json", "facts.json"}
    assert TABLE_SOURCE["path"] not in {file.path for file in index.files}
    assert RevisionTraceIndexV1.model_validate_json(encode_trace_index(index)) == index


def test_fractional_table_source_size_clears_only_invalid_fact_backed_derivation():
    fact_file = ArtifactFile(
        path="facts.json", mediaType="application/json", size=40, sha256=OTHER_SHA,
    )
    affected = _table_subject(fact_file=fact_file)
    unaffected = _table_subject("independent.json").model_copy(update={
        "subject_id": "sub-" + "5" * 16,
    })
    index = _build_table(
        fact_files={"analysis_001": fact_file},
        table_source_files=(
            {**TABLE_SOURCE, "size": 30.5},
            {"path": "independent.json", "size": 12, "sha256": OTHER_SHA},
        ),
        subject_bindings=(affected, unaffected),
    )
    subjects = {item.subject_id: item for item in index.subject_bindings}
    assert subjects[affected.subject_id].fact_refs == affected.fact_refs
    assert subjects[affected.subject_id].number_reference.table_derivation is None
    assert subjects[unaffected.subject_id].number_reference.table_derivation is not None
    assert RevisionTraceIndexV1.model_validate_json(encode_trace_index(index)) == index


def test_table_sources_reuse_matching_json_registration_and_preserve_chart_computations():

    from smart_reporting.reporting.workflow.checkpoint import FileIdentity

    from .test_trace_computation_service import EVIDENCE, SCRIPT, _record

    source = FileIdentity(**EVIDENCE)
    index = _build_table(
        computation_files=(FileIdentity(**SCRIPT), source), computations=(_record(),),
        chart_trace_files=(
            FileIdentity(path="报表/智能分析/run1/revision-1/chart-001.png", size=10, sha256=SHA),
            FileIdentity(path="报表/智能分析/run1/revision-1/chart-001--1.chart-input.json", size=10, sha256=SHA),
        ),
        chart_traces=(_chart_trace(),), table_source_files=(source,),
        subject_bindings=(_table_subject(source.path),),
    )
    assert sum(file.path == source.path for file in index.files) == 1
    assert len(index.computations) == len(index.chart_traces) == len(index.fact_files) == 1
    assert index.subject_bindings[0].number_reference.table_derivation is not None


@pytest.mark.parametrize("path,sha", [(MARKDOWN.path, OTHER_SHA), ("facts.json", OTHER_SHA)])
def test_table_source_collision_preserves_existing_files(path, sha):
    fact_file = ArtifactFile(path="facts.json", mediaType="application/json", size=30, sha256=SHA)
    source = dict(path=path, size=MARKDOWN.size if path == MARKDOWN.path else 30, sha256=sha)
    baseline = _build_table(fact_files={"analysis_001": fact_file})
    index = _build_table(
        fact_files={"analysis_001": fact_file}, table_source_files=(source,),
        subject_bindings=(_table_subject(path),),
    )
    assert index.files == baseline.files
    assert index.fact_files == baseline.fact_files
    assert index.subject_bindings == ()


def test_table_source_registration_budget_degrades_without_dropping_other_files():
    computation_files = tuple(
        dict(path=f"evidence/{number}.json", size=10, sha256=SHA) for number in range(1998)
    )
    index = _build_table(
        computation_files=computation_files, table_source_files=(TABLE_SOURCE,),
        subject_bindings=(_table_subject(),),
    )
    assert len(index.files) == 2000
    assert index.subject_bindings == ()
