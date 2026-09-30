"""B2 服务端表格装配测试（计划 B2-3：行列键冻结 + 单元格事实绑定）。"""

from __future__ import annotations

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.contracts_v1 import (
    RevisionTraceIndexV1,
    derive_resource_id,
)
from smart_reporting.reporting.trace.table_builder import build_table_trace

from .test_deterministic_analysis import analysis, context

SHA = "b" * 64
FACT_PATH = "报表/智能分析/run-1/facts/revision-1/analysis_001.json"
FACT_FILE_RESOURCE = derive_resource_id(FACT_PATH)


def _bundle():
    """两个院区一个月度快照，metricCodes 唯一可定位。"""

    fields = ("month", "department", "revenue")
    semantics = (  # income_total 绑定 revenue
        None,
    )
    return build_deterministic_analysis_bundle(
        analysis(fields=("revenue",)),
        (
            (
                "current",
                b"month,department,revenue\n2025-09,A,1200\n2025-09,B,2400\n",
                context(
                    "current",
                    fields=fields,
                    semantics=(
                        {
                            "fieldRef": "dynamic_source.dynamic_db.dynamic_table.revenue",
                            "aggregation": "sum",
                            "additiveAcross": ["month", "department"],
                            "exclusiveScope": {},
                            "unit": "元",
                        },
                    ),
                ),
                ("current",),
            ),
        ),
        profile_metrics=(
            {
                "code": "income_total",
                "fieldRef": "dynamic_source.dynamic_db.dynamic_table.revenue",
            },
        ),
        profile_hash="c" * 64,
    )


def _spec() -> dict:
    return {
        "tableId": "table-income",
        "metricCodes": ["income_total"],
        "rows": [
            {"key": "period:2025-09", "label": "2025-09", "period": "2025-09"},
        ],
        "caption": "月度收入",
    }


def test_build_table_trace_freezes_keys_and_binds_cells() -> None:
    bundle = _bundle()
    fact = bundle.metrics[0]
    trace, markdown = build_table_trace(
        bundle,
        _spec(),
        fact_file_resource_id=FACT_FILE_RESOURCE,
    )
    assert trace.table_id == "table-income"
    assert trace.row_keys == ("period:2025-09",)
    assert trace.column_keys == ("income_total",)
    assert len(trace.cells) == 1
    cell = trace.cells[0]
    assert (cell.row_key, cell.column_key) == ("period:2025-09", "income_total")
    ref = cell.fact_refs[0]
    assert ref.fact_key == fact.fact_id
    assert ref.file_resource_id == FACT_FILE_RESOURCE
    assert ref.json_pointer == "/metrics/0"
    # Markdown 含协议块与手算值（1200+2400=3600）。
    assert "[[table:table-income]]" in markdown and "[[/table:table-income]]" in markdown
    assert "3,600" in markdown


def test_table_trace_embeds_into_revision_index() -> None:
    """生成的 TableTraceV1 与 FactRef 可通过契约的全局引用校验。"""

    from smart_reporting.reporting.trace.contracts_v1 import (
        DatasetSnapshotRefV1,
        FactFileEntryV1,
        TraceFileRefV1,
    )

    bundle = _bundle()
    trace, _markdown = build_table_trace(
        bundle, _spec(), fact_file_resource_id=FACT_FILE_RESOURCE
    )
    index = RevisionTraceIndexV1(
        reportId="report-1",
        revision=1,
        workflowRunId="run-1",
        markdownFileResourceId=derive_resource_id("报表/智能分析/run-1/revision-1/report.md"),
        files=(
            TraceFileRefV1(
                resourceId=derive_resource_id("报表/智能分析/run-1/revision-1/report.md"),
                path="报表/智能分析/run-1/revision-1/report.md",
                mediaType="text/markdown",
                size=10,
                sha256=SHA,
            ),
            TraceFileRefV1(
                resourceId=derive_resource_id("报表/数据集/input.csv"),
                path="报表/数据集/input.csv",
                mediaType="text/csv",
                size=100,
                sha256=SHA,
            ),
            TraceFileRefV1(
                resourceId=FACT_FILE_RESOURCE,
                path=FACT_PATH,
                mediaType="application/json",
                size=100,
                sha256=SHA,
            ),
        ),
        datasets=(
            DatasetSnapshotRefV1(
                datasetId="dataset-url-abc0001",
                fileResourceId=derive_resource_id("报表/数据集/input.csv"),
                sourceType="url_csv",
                requirementId="attachment-001",
                periodRoles=("current",),
                rowCount=2,
            ),
        ),
        factFiles=(
            FactFileEntryV1(
                analysisId="analysis_001",
                fileResourceId=FACT_FILE_RESOURCE,
                contentKind="deterministic_bundle",
            ),
        ),
        tables=(trace,),
    )
    assert index.tables[0].table_id == "table-income"


def test_table_builder_rejects_ambiguous_and_missing_columns() -> None:
    bundle = _bundle()
    with pytest.raises(ReportingError, match="不存在的指标"):
        build_table_trace(
            bundle,
            {**_spec(), "metricCodes": ("no_such_metric",)},
            fact_file_resource_id=FACT_FILE_RESOURCE,
        )
    # rowKey 重复拒绝（插入行列不能复用旧身份的镜像：重复键不得静默合并）。
    spec = _spec()
    spec["rows"] = [
        {"key": "period:2025-09", "label": "A", "period": "2025-09"},
        {"key": "period:2025-09", "label": "B", "period": "2025-09"},
    ]
    with pytest.raises(ReportingError, match="rowKey 重复"):
        build_table_trace(
            bundle, spec, fact_file_resource_id=FACT_FILE_RESOURCE
        )


def test_table_builder_requires_period_match_for_period_rows() -> None:
    bundle = _bundle()
    spec = _spec()
    spec["rows"] = [{"key": "period:2024-01", "label": "旧期间", "period": "2024-01"}]
    with pytest.raises(ReportingError, match="期间"):
        build_table_trace(bundle, spec, fact_file_resource_id=FACT_FILE_RESOURCE)
