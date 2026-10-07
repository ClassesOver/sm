"""发布时构建 revision 追溯索引（B1：CSV 快照层；facts/图表/绑定由 B2+ 扩展）。

索引由服务端在 finalize 阶段从已验收的 DatasetHandle/DatasetLineage 构建，
写入 revision 目录 ``trace-index-v1.json`` 并经权威 manifest 的
``traceIndex`` 字段登记；编辑器只从该登记解析，不从最新可变状态猜测。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Sequence

from ..data_sources import DatasetHandle
from ..delivery.artifacts_v1 import ArtifactFile, DatasetLineage
from ..models import ReportingError
from .contracts_v1 import (
    DatasetSnapshotRefV1,
    FactFileEntryV1,
    RevisionTraceIndexV1,
    TraceFileRefV1,
    canonical_json_bytes,
    derive_resource_id,
)

if TYPE_CHECKING:
    pass

TRACE_INDEX_FILENAME = "trace-index-v1.json"


def build_csv_trace_index(
    *,
    handles: Sequence[DatasetHandle],
    lineage: Sequence[DatasetLineage],
    report_id: str,
    revision: int,
    workflow_run_id: str,
    markdown_file: ArtifactFile,
    profile_hash: str | None = None,
    fact_files: Mapping[str, ArtifactFile] | None = None,
    server_table_traces: Sequence[Any] = (),
    chart_trace_files: Sequence[Any] = (),
    chart_traces: Sequence[Any] = (),
    computation_files: Sequence[Any] = (),
    computations: Sequence[Any] = (),
    subject_bindings: Sequence[Any] = (),
    drilldown_metrics: Sequence[Any] = (),
) -> RevisionTraceIndexV1:
    """从发布门禁已验收的句柄与血缘构建 revision 索引（全部追溯层）。

    调用方（publication）必须保证 handle 与 lineage 已通过七元组一致性校验；
    此处再做防御性核对，失败即发布失败关闭，不降级生成半份索引。
    fact_files：analysisId → 冻结事实文件（B2 起登记，供 FactRef 解析）。
    server_table_traces：服务端生成表格的 TableTraceV1（单元格绑定FactRef）。
    chart_trace_files：归档图片与 chart-input 文件身份（B3 图表层登记）。
    chart_traces：图表追溯 ChartTraceV1。
    computation_files：补证脚本与 evidence 文件身份（B4 计算层登记）。
    computations：补充分析计算记录 ComputationRecordV1。
    drilldown_metrics：服务端冻结的指标、维度、算法与固定范围声明（B7）。
    """

    handle_by_id = {item.dataset_id: item for item in handles}
    lineage_by_id = {item.dataset_id: item for item in lineage}
    if set(handle_by_id) != set(lineage_by_id) or len(handle_by_id) != len(handles):
        raise ReportingError(
            "report_trace_index_invalid", "数据集句柄与血缘未精确对应，索引拒绝生成。"
        )
    if not handles:
        raise ReportingError(
            "report_trace_index_invalid", "缺少数据集句柄，索引拒绝生成。"
        )

    markdown_ref = TraceFileRefV1(
        resourceId=derive_resource_id(markdown_file.path),
        path=markdown_file.path,
        mediaType=markdown_file.media_type,
        size=markdown_file.size,
        sha256=markdown_file.sha256,
    )
    files: list[TraceFileRefV1] = [markdown_ref]
    datasets: list[DatasetSnapshotRefV1] = []
    for dataset_id, handle in handle_by_id.items():
        source = lineage_by_id[dataset_id]
        if (
            handle.source_type != source.source_type
            or handle.size != source.size
            or handle.sha256 != source.sha256
            or handle.row_count != source.row_count
        ):
            raise ReportingError(
                "report_trace_index_invalid",
                f"数据集身份不一致，索引拒绝生成: {dataset_id}",
            )
        files.append(
            TraceFileRefV1(
                resourceId=derive_resource_id(handle.path),
                path=handle.path,
                mediaType="text/csv",
                size=handle.size,
                sha256=handle.sha256,
            )
        )
        datasets.append(
            DatasetSnapshotRefV1(
                datasetId=dataset_id,
                fileResourceId=derive_resource_id(handle.path),
                sourceType=handle.source_type,
                requirementId=handle.requirement_id,
                sqlHash=handle.sql_hash,
                periodRoles=tuple(handle.period_roles),
                queryWindowId=handle.query_window_id,
                rowCount=handle.row_count,
                materializedAt=handle.materialized_at,
                filename=handle.filename,
                businessLabel=handle.business_label,
                querySql=handle.query_sql,
            )
        )
    fact_entries: list[FactFileEntryV1] = []
    for analysis_id, fact_file in (fact_files or {}).items():
        files.append(
            TraceFileRefV1(
                resourceId=derive_resource_id(fact_file.path),
                path=fact_file.path,
                mediaType="application/json",
                size=fact_file.size,
                sha256=fact_file.sha256,
            )
        )
        fact_entries.append(
            FactFileEntryV1(
                analysisId=analysis_id,
                fileResourceId=derive_resource_id(fact_file.path),
                contentKind="deterministic_bundle",
            )
        )
    # B3 图表层：归档图片与 chart-input 文件登记进索引，ChartTraceV1 引用
    # 必须全部落在已登记文件上（契约全局校验兜底）。
    for identity in chart_trace_files:
        media_type = (
            "application/json"
            if str(identity.path).endswith(".json")
            else "image/png"
            if str(identity.path).endswith(".png")
            else "image/jpeg"
        )
        files.append(
            TraceFileRefV1(
                resourceId=derive_resource_id(str(identity.path)),
                path=str(identity.path),
                mediaType=media_type,
                size=int(identity.size),
                sha256=str(identity.sha256),
            )
        )
    # B4 计算层：补证脚本与 evidence 文件登记；evidence（json）同时登记为
    # supplemental_evidence 类事实文件条目，使 ComputationRecord 的
    # outputFactRefs 通过契约的 analysis↔文件一致性校验。同一文件去重。
    seen_paths = {item.path for item in files}
    supplemental_evidence: dict[str, str] = {}
    for record in computations:
        for ref in record.output_fact_refs:
            supplemental_evidence.setdefault(ref.analysis_id, ref.file_resource_id)

    def _identity_fields(identity: Any) -> tuple[str, int, str]:
        if isinstance(identity, Mapping):
            return str(identity["path"]), int(identity["size"]), str(identity["sha256"])
        return str(identity.path), int(identity.size), str(identity.sha256)

    for identity in computation_files:
        path_value, size_value, sha_value = _identity_fields(identity)
        if path_value in seen_paths:
            continue
        seen_paths.add(path_value)
        files.append(
            TraceFileRefV1(
                resourceId=derive_resource_id(path_value),
                path=path_value,
                mediaType="application/json",
                size=size_value,
                sha256=sha_value,
            )
        )
    resource_ids = {item.resource_id for item in files}
    for analysis_id, file_resource_id in supplemental_evidence.items():
        if file_resource_id in resource_ids and analysis_id not in {
            entry.analysis_id for entry in fact_entries
        }:
            fact_entries.append(
                FactFileEntryV1(
                    analysisId=analysis_id,
                    fileResourceId=file_resource_id,
                    contentKind="supplemental_evidence",
                )
            )
    return RevisionTraceIndexV1(
        reportId=report_id,
        revision=revision,
        workflowRunId=workflow_run_id,
        markdownFileResourceId=markdown_ref.resource_id,
        profileHash=profile_hash,
        files=tuple(files),
        datasets=tuple(datasets),
        factFiles=tuple(fact_entries),
        tables=tuple(server_table_traces),
        chartTraces=tuple(chart_traces),
        computations=tuple(computations),
        subjectBindings=tuple(subject_bindings),
        drilldownMetrics=tuple(drilldown_metrics),
    )


def encode_trace_index(index: RevisionTraceIndexV1) -> bytes:
    """索引 canonical JSON（排序键、紧凑、禁 NaN），用于落盘与回读校验。"""

    return canonical_json_bytes(index.model_dump(mode="json", by_alias=True))


def trace_index_path_for(manifest_path: str) -> str:
    from pathlib import PurePosixPath

    parent = PurePosixPath(manifest_path).parent
    return parent.joinpath(TRACE_INDEX_FILENAME).as_posix()
