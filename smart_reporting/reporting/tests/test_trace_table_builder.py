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
from smart_reporting.reporting.trace.table_builder import build_analysis_table, build_table_trace

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


def test_analysis_table_uses_default_cny_for_untyped_amount_columns() -> None:
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("revenue",)),
        ((
            "current",
            b"month,department,revenue\n2025-09,A,1200\n",
            context(
                "current",
                fields=("month", "department", "revenue"),
                semantics=({
                    "fieldRef": "dynamic_source.dynamic_db.dynamic_table.revenue",
                    "aggregation": "sum",
                    "additiveAcross": ["month", "department"],
                    "exclusiveScope": {},
                },),
            ),
            ("current",),
        ),),
        profile_metrics=({
            "code": "revenue_total",
            "description": "收入",
            "kind": "amount",
            "aggregation": "sum",
            "fieldRef": "dynamic_source.dynamic_db.dynamic_table.revenue",
        },),
    )
    trace, markdown = build_analysis_table(bundle, fact_file_resource_id=FACT_FILE_RESOURCE)

    assert trace is not None
    assert "收入（元）" in markdown
    assert "1,200" in markdown
    assert trace.column_keys == ("收入（元）",)
    assert trace.row_keys == ("period:2025-09",)
    assert trace.cells[0].fact_refs[0].fact_key == bundle.metrics[0].fact_id
    assert trace.cells[0].fact_refs[0].file_resource_id == FACT_FILE_RESOURCE


def test_analysis_table_reads_like_a_management_table():
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicAnalysisBundle,
    )

    def metric(letter, code, name, values):
        return {
            "factId": "fact-" + letter * 16, "datasetId": "ds", "datasetSha256": SHA, "periodRoles": ["current"],
            "metricCodes": [code], "field": code, "fieldRef": "src.db.t." + code, "displayName": name,
            "aggregation": "sum", "unit": "元", "formula": "sum", "total": sum(values),
            "missingCount": 0, "zeroCount": 0, "negativeCount": 0, "periodGranularity": "day",
            "periodValues": [{"period": f"2025-{index + 1:02d}-01", "value": value} for index, value in enumerate(values)],
        }

    bundle = DeterministicAnalysisBundle.model_validate({"analysisId": "analysis_001", "metrics": [
        metric("a", "income", "收入金额，也称医疗收入金额", [100, 200]),
        metric("b", "service", "医疗服务收入", [0, 0]),
    ]})
    trace, markdown = build_analysis_table(bundle, fact_file_resource_id=FACT_FILE_RESOURCE)
    assert "收入金额（元）" in markdown and "也称" not in markdown
    assert "医疗服务收入" not in markdown and len(trace.column_keys) == 1
    assert "2025年1月" in markdown and "1日" not in markdown


def test_analysis_table_keeps_zero_counts_and_single_dates():
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicAnalysisBundle,
    )

    def metric(letter, code, unit, periods, values):
        return {
            "factId": "fact-" + letter * 16, "datasetId": "ds", "datasetSha256": SHA, "periodRoles": ["current"],
            "metricCodes": [code], "field": code, "fieldRef": "src.db.t." + code, "displayName": code,
            "aggregation": "sum", "unit": unit, "formula": "sum", "total": sum(values),
            "missingCount": 0, "zeroCount": 0, "negativeCount": 0, "periodGranularity": "day",
            "periodValues": [{"period": period, "value": value} for period, value in zip(periods, values, strict=True)],
        }

    # 不良事件为零是结果，不能省略；只有一期的 2025-01-01 是日期，不改写为 1 月。
    single = DeterministicAnalysisBundle.model_validate({"analysisId": "analysis_001", "metrics": [
        metric("a", "不良事件", "人次", ["2025-01-01"], [0]),
    ]})
    trace, markdown = build_analysis_table(single, fact_file_resource_id=FACT_FILE_RESOURCE)
    assert "不良事件" in markdown and "2025年1月1日" in markdown
    # 不连续的月初日期同样按日期显示。
    gapped = DeterministicAnalysisBundle.model_validate({"analysisId": "analysis_001", "metrics": [
        metric("b", "收入", "元", ["2025-01-01", "2025-03-01"], [1, 2]),
    ]})
    assert "2025年3月1日" in build_analysis_table(gapped, fact_file_resource_id=FACT_FILE_RESOURCE)[1]
