from __future__ import annotations

import ast
import hashlib
import inspect
import json
import textwrap
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from agno.agent import Agent
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.workflow.step import StepOutput
from pydantic import ValidationError
from sqlglot import parse_one

from smart_reporting.context_management import (
    ProjectedOpenAIChat,
    TaskExecutionContextHardLimitError,
)
from smart_reporting.reporting import contract as reporting_contract
from smart_reporting.reporting.agent import ReportingPhaseOpenAIChat
from smart_reporting.reporting.contract import ReportPeriod
from smart_reporting.reporting.data_source import DataShape
from smart_reporting.reporting.data_sources import DatasetHandle
from smart_reporting.reporting.hospital_operation.detailed_analysis import (
    AnalysisFileIdentity,
    DatasetAnalysisContext,
    DetailedAnalysisPlan,
    ProfiledDataset,
)
from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
)
from smart_reporting.reporting.hospital_operation.outline import (
    ReportOutline,
    ReportOutlineProposal,
)
from smart_reporting.reporting.instructions import (
    REPORT_ANALYSIS_ITEM_AGENT_INSTRUCTIONS,
    REPORT_SECTION_AGENT_INSTRUCTIONS,
    REPORT_VISUALIZATION_SECTION_AGENT_INSTRUCTIONS,
)
from smart_reporting.reporting.model_policy import (
    ReportingThinkingProfile,
    apply_reporting_thinking_profile,
    reporting_thinking_profile_from_model,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.checkpoint import (
    AnalysisEvidence,
    FileIdentity,
    MetricDefinition,
    ProfileCoverageDataset,
    ProfileCoverageManifest,
)
from smart_reporting.reporting.workflow.query_pipeline import (
    ApprovedQuery,
    _has_complete_period_filter,
    normalized_sql_hash,
    project_measure_semantics_to_query_outputs,
)
from smart_reporting.reporting.workflow.runtime import (
    REPORT_WORKFLOW_INPUT_STATE_KEY,
    ReportWorkflowRuntime,
)
from smart_reporting.reporting.workflow.runtime import base as reporting_runtime_base
from smart_reporting.reporting.workflow.runtime import datasets as reporting_datasets
from smart_reporting.reporting.workflow.runtime import planning as reporting_runtime
from smart_reporting.reporting.workflow.runtime.analysis import (
    _analysis_item_complexity,
    _analysis_item_dataset_inputs,
    _analysis_item_output_root,
    _analysis_item_thinking_policy,
    _model_facing_deterministic_facts,
    _reporting_detailed_analysis_plan,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisEvidenceDecision,
    AnalysisScriptDraft,
    AnalysisSummaryDraft,
)
from smart_reporting.reporting.workflow.runtime.base import (
    MAX_REPORT_SECTION_PHASE_ATTEMPTS,
    OUTLINE_SECTION_COUNT_INSTRUCTION,
    REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY,
    REPORT_ANALYSIS_PLAN_STATE_KEY,
    REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY,
    REPORT_OUTLINE_STATE_KEY,
    REPORT_PROFILE_COVERAGE_STATE_KEY,
    REPORT_WORKFLOW_RESULT_STATE_KEY,
)
from smart_reporting.reporting.workflow.runtime.datasets import (
    RuntimeDatasetsMixin,
    _requirement_measure_field_refs,
)
from smart_reporting.reporting.workflow.runtime.models import (
    AnalysisBundle,
    DataUnderstandingPlan,
    MeasureSemanticProposal,
)
from smart_reporting.reporting.workflow.runtime.planning import (
    _PLANNER_DISPLAY_NAMES,
    _outline_candidate,
    _outline_validation_issues,
    _row_preserving_requirement_ids,
    _validate_reporting_profile_schema,
)
from smart_reporting.reporting.workflow.runtime.publication import (
    _analysis_quality_warnings,
)
from smart_reporting.reporting.workflow.runtime.validation import (
    _measure_semantic_issues,
    _normalize_requirement_periods,
)


@pytest.mark.anyio
async def test_run_planner_maps_typed_context_hard_limit_without_message_matching(
    monkeypatch,
) -> None:
    metrics = {
        "canonical_estimated_tokens": 200_000,
        "irreducible_prefix_estimated_tokens": 180_000,
        "input_token_hard_cap": 160_000,
        "tool_schema_bytes": 2,
        "response_format_bytes": 22,
    }
    rejection = TaskExecutionContextHardLimitError(
        "此消息刻意不包含旧的中文匹配文本。",
        metrics=metrics,
    )

    class RejectingExecutor:
        def __init__(self, _agent) -> None:
            pass

        async def execute(self, *_args, **_kwargs):
            raise rejection

    monkeypatch.setattr(
        reporting_runtime_base,
        "ReportingStructuredOutputExecutor",
        RejectingExecutor,
    )
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._scope = lambda _run_context: {"userId": "user-1"}
    run_context = SimpleNamespace(run_id="run-1")

    with pytest.raises(ReportingError) as raised:
        await runtime._run_planner(
            SimpleNamespace(id="report-test-planner"),
            {"request": "complex"},
            run_context,
        )

    assert raised.value.code == "report_planner_context_budget_exceeded"
    assert raised.value.details == metrics
    assert raised.value.__cause__ is rejection


def test_row_preserving_requirements_follow_effective_profile_without_legacy_fields() -> None:
    requirement = type(
        "Requirement",
        (),
        {"requirement_id": "r1", "tables": (type("Table", (), {"table": "custom.metrics"})(),)},
    )()
    profile = type("EffectiveProfile", (), {})()
    profile.reconciliations = ()
    assert _row_preserving_requirement_ids((requirement,), profile) == ()


def test_reporting_profile_schema_validation_uses_replaced_profile_bindings() -> None:
    profile = type(
        "EffectiveProfile",
        (),
        {
            "metrics": (type("Metric", (), {"field_ref": "custom.analytics.fact.amount"})(),),
            "dimensions": (),
            "scope_filters": (),
            "measure_semantics": (),
        },
    )()
    snapshot = type(
        "Snapshot",
        (),
        {
            "tables": (
                type(
                    "Table",
                    (),
                    {
                        "source_id": "custom",
                        "database": "analytics",
                        "name": "fact",
                        "columns": (type("Column", (), {"name": "amount"})(),),
                    },
                )(),
            )
        },
    )()

    _validate_reporting_profile_schema(profile, (snapshot,))


def test_workflow_runtime_uses_package_boundaries() -> None:
    """运行时入口和规划模型必须来自拆分后的实际模块。"""
    assert ReportWorkflowRuntime.__module__ == ("smart_reporting.reporting.workflow.runtime.facade")
    assert AnalysisBundle.__module__ == "smart_reporting.reporting.workflow.runtime.models"
    assert DataUnderstandingPlan.__module__ == ("smart_reporting.reporting.workflow.runtime.models")


def test_reporting_fresh_retry_budget_allows_three_attempts() -> None:
    assert MAX_REPORT_SECTION_PHASE_ATTEMPTS == 3


def test_runtime_capability_modules_do_not_import_facade() -> None:
    """能力模块只能依赖中立层，Facade 只负责最终组合。"""
    runtime_dir = Path(__file__).parents[1] / "workflow" / "runtime"
    capability_modules = (
        "validation.py",
        "planning.py",
        "datasets.py",
        "analysis.py",
        "sections.py",
        "publication.py",
    )
    for filename in capability_modules:
        tree = ast.parse((runtime_dir / filename).read_text(encoding="utf-8"))
        assert all(
            not isinstance(node, ast.ImportFrom) or node.module != "facade"
            for node in ast.walk(tree)
        ), f"{filename} 不得运行时导入 facade"
    assert _normalize_requirement_periods.__module__ == (
        "smart_reporting.reporting.workflow.runtime.validation"
    )


def metric_definition(*, code: str, definition: str, period_basis: str) -> MetricDefinition:
    return MetricDefinition(
        code=code,
        name="同比指标",
        definition=definition,
        unit="%",
        periodBasis=period_basis,
    )


def test_publication_gate_returns_warnings_for_explicitly_incomparable_metrics() -> None:
    metrics = (
        metric_definition(
            code="income_yoy",
            definition="2025年1-11月相对2024年全年，仅作参考性对比",
            period_basis="2025年1-11月 vs 2024年全年（期间跨度不一致）",
        ),
        metric_definition(
            code="workload_yoy",
            definition="2025年全年（11-12月为0），同比基期2024年全年",
            period_basis="2025年全年 vs 2024年全年",
        ),
    )

    warnings = _analysis_quality_warnings(metrics, ())

    assert {item["details"]["metricCode"] for item in warnings} == {
        "income_yoy",
        "workload_yoy",
    }


def test_publication_gate_accepts_metrics_aligned_to_common_window() -> None:
    metrics = (
        metric_definition(
            code="income_yoy",
            definition="收入同比按服务端共同连续窗口计算",
            period_basis="2025年1-10月 vs 2024年1-10月",
        ),
    )

    assert _analysis_quality_warnings(metrics, ()) == ()


def test_planner_trace_names_use_human_display_labels_without_changing_ids() -> None:
    assert _PLANNER_DISPLAY_NAMES["report-outline-planner"] == "报告提纲规划"
    assert _PLANNER_DISPLAY_NAMES["report-sql-planner"] == "取数方案设计"


def test_outline_prompt_prioritizes_user_section_count_over_analysis_split() -> None:
    assert "reportGoal 中明确的章节数量约束" in OUTLINE_SECTION_COUNT_INSTRUCTION
    assert "高于按 analysisId 拆分章节" in OUTLINE_SECTION_COUNT_INSTRUCTION
    assert "不超过用户指定数量的章节" in OUTLINE_SECTION_COUNT_INSTRUCTION


def analysis_bundle(*, table: str, period_granularity: str) -> AnalysisBundle:
    return AnalysisBundle.model_validate(
        {
            "analyses": [
                {
                    "code": "income_trend",
                    "description": "分析收入趋势",
                    "managementQuestion": "收入趋势是否发生显著变化？",
                    "primaryMetricFamily": "收入",
                    "requirementIds": ["req_income"],
                }
            ],
            "requirements": [
                {
                    "requirementId": "req_income",
                    "sourceId": "rj",
                    "tables": [
                        {
                            "table": table,
                            "periodColumn": "data_date",
                            "periodGranularity": period_granularity,
                            "measureColumns": ["indicator_value"],
                        }
                    ],
                    "dimensionColumns": [],
                    "grainColumns": [],
                    "relations": [],
                }
            ],
        }
    )


def data_understanding() -> DataUnderstandingPlan:
    return DataUnderstandingPlan.model_validate(
        {
            "tables": [
                {
                    "sourceId": "rj",
                    "table": "rj.dwd_hdc_income_summary_view",
                    "role": "收入分析",
                    "periodColumn": "data_date",
                    "periodGranularity": "date",
                }
            ]
        }
    )


def test_single_table_query_compiler_keeps_unapproved_numeric_fields_in_grain() -> None:
    grain_columns = (
        "data_date",
        "area",
        "budget_service_income",
        "actual_service_income",
    )
    requirement = reporting_runtime.QueryRequirement.model_validate(
        {
            "requirementId": "req_income_budget",
            "sourceId": "rj",
            "tables": [
                {
                    "table": "rj.income_budget",
                    "periodColumn": "data_date",
                    "periodGranularity": "date",
                    "measureColumns": ["actual_medical_income"],
                }
            ],
            "dimensionColumns": list(grain_columns),
            "grainColumns": list(grain_columns),
            "relations": [],
        }
    )
    snapshot = reporting_contract.SourceSchemaSnapshot(
        source="metadata_api",
        revision="revision-1",
        schemaHash="a" * 64,
        tables=(
            reporting_contract.ModelTable(
                sourceId="rj",
                database="rj",
                name="income_budget",
                columns=tuple(
                    reporting_contract.ModelColumn(
                        name=name,
                        dataType="DATE" if name == "data_date" else "DECIMAL(18, 2)",
                        nullable=True,
                    )
                    for name in (*grain_columns, "actual_medical_income")
                ),
            ),
        ),
        measureSemantics=(
            reporting_contract.MeasureSemantic(
                fieldRef="rj.rj.income_budget.actual_medical_income",
                aggregation="sum",
            ),
        ),
    )
    envelope = reporting_contract.ReportRequestEnvelope.model_validate(
        {
            "reportGoal": "分析 2025 年收入预算执行情况",
            "period": {"start": "2025-01-01", "end": "2025-12-31"},
            "sourceIds": ["rj"],
            "comparisonRoles": ["yoy"],
        }
    )

    generated = reporting_runtime._compile_single_table_queries(
        (requirement,),
        snapshots=(snapshot,),
        envelope=envelope,
    )

    assert generated is not None
    approved, issues = reporting_runtime._approve_generated_queries(
        generated,
        sources={"rj": SimpleNamespace(id="rj", database="rj")},
        snapshots=(snapshot,),
        envelope=envelope,
        requirements=(requirement,),
    )
    assert issues == []
    assert len(approved) == 2
    assert all("SUM(budget_service_income)" not in query.sql for query in approved)
    assert all("SUM(actual_medical_income)" in query.sql for query in approved)


def test_analysis_grain_excludes_exact_constant_numeric_columns() -> None:
    snapshot = reporting_contract.SourceSchemaSnapshot(
        source="metadata_api",
        revision="revision-1",
        schemaHash="a" * 64,
        tables=(
            reporting_contract.ModelTable(
                sourceId="rj",
                database="rj",
                name="income_budget",
                columns=(
                    reporting_contract.ModelColumn(
                        name="data_date", dataType="DATE", nullable=False
                    ),
                    reporting_contract.ModelColumn(
                        name="department", dataType="VARCHAR(64)", nullable=False
                    ),
                    reporting_contract.ModelColumn(
                        name="actual_medical_income", dataType="DECIMAL(18,2)", nullable=False
                    ),
                    reporting_contract.ModelColumn(
                        name="actual_service_income", dataType="DECIMAL(18,2)", nullable=False
                    ),
                ),
            ),
        ),
        measureSemantics=(
            reporting_contract.MeasureSemantic(
                fieldRef="rj.rj.income_budget.actual_medical_income",
                aggregation="sum",
            ),
        ),
    )
    shape = DataShape.model_validate(
        {
            "sourceId": "rj",
            "metadataRevision": "revision-1",
            "schemaHash": "a" * 64,
            "statisticsVersion": "1",
            "queryCount": 3,
            "periodStart": "2025-01-01",
            "periodEnd": "2025-12-31",
            "tables": [
                {
                    "sourceId": "rj",
                    "database": "rj",
                    "table": "income_budget",
                    "totalRowCount": 12,
                    "periodRowCount": 12,
                    "outsidePeriodRowCount": 0,
                    "periodNullCount": 0,
                    "firstEffectiveDate": "2025-01-01",
                    "lastEffectiveDate": "2025-12-01",
                    "columnCount": 4,
                    "periodGranularity": "date",
                    "columns": [
                        {
                            "name": "data_date",
                            "dataType": "DATE",
                            "nullable": False,
                            "nullCount": 0,
                            "nullRate": 0,
                            "distinctCount": 12,
                            "distinctMode": "exact",
                            "cardinalityRate": 1,
                            "unique": True,
                        },
                        {
                            "name": "department",
                            "dataType": "VARCHAR(64)",
                            "nullable": False,
                            "nullCount": 0,
                            "nullRate": 0,
                            "distinctCount": 3,
                            "distinctMode": "exact",
                            "cardinalityRate": 0.25,
                            "unique": False,
                        },
                        {
                            "name": "actual_medical_income",
                            "dataType": "DECIMAL(18,2)",
                            "nullable": False,
                            "nullCount": 0,
                            "nullRate": 0,
                            "distinctCount": 12,
                            "distinctMode": "exact",
                            "cardinalityRate": 1,
                            "unique": True,
                            "zeroCount": 0,
                            "negativeCount": 0,
                        },
                        {
                            "name": "actual_service_income",
                            "dataType": "DECIMAL(18,2)",
                            "nullable": False,
                            "nullCount": 0,
                            "nullRate": 0,
                            "distinctCount": 1,
                            "distinctMode": "exact",
                            "cardinalityRate": 0.083333,
                            "unique": False,
                            "minimum": 0,
                            "maximum": 0,
                            "zeroCount": 12,
                            "negativeCount": 0,
                        },
                    ],
                }
            ],
        }
    )
    bundle = analysis_bundle(table="rj.income_budget", period_granularity="date")
    payload = bundle.model_dump(mode="json", by_alias=True)
    payload["requirements"][0]["tables"][0]["measureColumns"] = ["actual_medical_income"]
    bundle = AnalysisBundle.model_validate(payload)

    normalized, repairs = reporting_runtime._normalize_analysis_bundle_grain(
        bundle,
        (snapshot,),
        (shape,),
    )

    assert normalized.requirements[0].grain_columns == ("data_date", "department")
    assert normalized.requirements[0].dimension_columns == ("data_date", "department")
    assert repairs[0]["addedColumns"] == ["data_date", "department"]


def test_unapproved_measure_is_not_also_requested_as_grain_in_same_correction() -> None:
    snapshot = reporting_contract.SourceSchemaSnapshot(
        source="metadata_api",
        revision="revision-1",
        schemaHash="a" * 64,
        tables=(
            reporting_contract.ModelTable(
                sourceId="rj",
                database="rj",
                name="income_budget",
                columns=(
                    reporting_contract.ModelColumn(
                        name="data_date", dataType="DATE", nullable=False
                    ),
                    reporting_contract.ModelColumn(
                        name="income", dataType="DECIMAL(18,2)", nullable=False
                    ),
                    reporting_contract.ModelColumn(
                        name="unapproved_income", dataType="DECIMAL(18,2)", nullable=False
                    ),
                ),
            ),
        ),
        measureSemantics=(
            reporting_contract.MeasureSemantic(
                fieldRef="rj.rj.income_budget.income",
                aggregation="sum",
            ),
        ),
    )
    bundle = analysis_bundle(table="rj.income_budget", period_granularity="date")
    payload = bundle.model_dump(mode="json", by_alias=True)
    payload["requirements"][0]["tables"][0]["measureColumns"] = [
        "income",
        "unapproved_income",
    ]
    requirement = AnalysisBundle.model_validate(payload).requirements[0]

    issues = _measure_semantic_issues(requirement, 0, (snapshot,))

    assert any(str(issue["path"]).endswith(".measureColumns") for issue in issues)
    grain_issue = next(issue for issue in issues if str(issue["path"]).endswith(".grainColumns"))
    assert "unapproved_income" not in grain_issue["missingValues"]


def test_unsafe_multi_table_requirement_is_split_before_semantic_retry() -> None:
    snapshot = reporting_contract.SourceSchemaSnapshot(
        source="metadata_api",
        revision="revision-1",
        schemaHash="a" * 64,
        tables=(
            reporting_contract.ModelTable(
                sourceId="rj",
                database="rj",
                name="income",
                columns=(
                    reporting_contract.ModelColumn(
                        name="data_date", dataType="DATE", nullable=False
                    ),
                    reporting_contract.ModelColumn(
                        name="department", dataType="VARCHAR(64)", nullable=False
                    ),
                    reporting_contract.ModelColumn(
                        name="income", dataType="DECIMAL(18,2)", nullable=False
                    ),
                ),
            ),
            reporting_contract.ModelTable(
                sourceId="rj",
                database="rj",
                name="cost",
                columns=(
                    reporting_contract.ModelColumn(
                        name="data_date", dataType="DATE", nullable=False
                    ),
                    reporting_contract.ModelColumn(
                        name="cost_type", dataType="VARCHAR(64)", nullable=False
                    ),
                    reporting_contract.ModelColumn(
                        name="cost", dataType="DECIMAL(18,2)", nullable=False
                    ),
                ),
            ),
        ),
        measureSemantics=(
            reporting_contract.MeasureSemantic(fieldRef="rj.rj.income.income", aggregation="sum"),
            reporting_contract.MeasureSemantic(fieldRef="rj.rj.cost.cost", aggregation="sum"),
        ),
    )
    bundle = AnalysisBundle.model_validate(
        {
            "analyses": [
                {
                    "code": "income_cost",
                    "description": "联合分析收入与成本",
                    "managementQuestion": "收入增长是否伴随成本改善？",
                    "primaryMetricFamily": "收入成本",
                    "requirementIds": ["req_income_cost"],
                }
            ],
            "requirements": [
                {
                    "requirementId": "req_income_cost",
                    "sourceId": "rj",
                    "tables": [
                        {
                            "table": "rj.income",
                            "periodColumn": "data_date",
                            "periodGranularity": "date",
                            "measureColumns": ["income"],
                        },
                        {
                            "table": "rj.cost",
                            "periodColumn": "data_date",
                            "periodGranularity": "date",
                            "measureColumns": ["cost"],
                        },
                    ],
                    "dimensionColumns": ["data_date"],
                    "grainColumns": ["data_date"],
                    "relations": [
                        {
                            "leftTable": "rj.income",
                            "rightTable": "rj.cost",
                            "joinColumns": ["data_date"],
                        }
                    ],
                }
            ],
        }
    )

    split, repairs = reporting_runtime._normalize_unsafe_multi_table_requirements(
        bundle, (snapshot,)
    )
    normalized, grain_repairs = reporting_runtime._normalize_analysis_bundle_grain(
        split, (snapshot,)
    )

    assert len(repairs) == 1
    assert len(normalized.requirements) == 2
    assert normalized.analyses[0].requirement_ids == tuple(
        item.requirement_id for item in normalized.requirements
    )
    assert all(len(item.tables) == 1 and not item.relations for item in normalized.requirements)
    assert {tuple(item.grain_columns) for item in normalized.requirements} == {
        ("data_date", "department"),
        ("data_date", "cost_type"),
    }
    assert len(grain_repairs) == 2


def test_data_understanding_prefers_typed_date_over_unrequested_period_code() -> None:
    plan = DataUnderstandingPlan.model_validate(
        {
            "tables": [
                {
                    "sourceId": "rj",
                    "table": "rj.dwd_hdc_income_summary_view",
                    "role": "收入趋势",
                    "periodColumn": "period_code",
                    "periodGranularity": "month",
                }
            ]
        }
    )
    snapshot = reporting_contract.SourceSchemaSnapshot(
        source="metadata_api",
        revision="revision-1",
        schemaHash="a" * 64,
        tables=(
            reporting_contract.ModelTable(
                sourceId="rj",
                database="rj",
                name="dwd_hdc_income_summary_view",
                columns=(
                    reporting_contract.ModelColumn(
                        name="period_code",
                        dataType="VARCHAR(255)",
                        nullable=True,
                        description="数据月份",
                    ),
                    reporting_contract.ModelColumn(
                        name="data_date",
                        dataType="DATE",
                        nullable=True,
                        description="数据日期",
                    ),
                ),
            ),
        ),
    )

    normalized = reporting_runtime._normalize_preferred_typed_period_fields(
        plan,
        (snapshot,),
        report_goal="分析2025年月度收入趋势",
    )

    assert normalized.tables[0].period_column == "data_date"
    assert normalized.tables[0].period_granularity == "date"


def test_data_understanding_keeps_explicit_period_code() -> None:
    plan = DataUnderstandingPlan.model_validate(
        {
            "tables": [
                {
                    "sourceId": "rj",
                    "table": "rj.dwd_hdc_income_summary_view",
                    "role": "收入趋势",
                    "periodColumn": "period_code",
                    "periodGranularity": "month",
                }
            ]
        }
    )
    snapshot = reporting_contract.SourceSchemaSnapshot(
        source="metadata_api",
        revision="revision-1",
        schemaHash="a" * 64,
        tables=(
            reporting_contract.ModelTable(
                sourceId="rj",
                database="rj",
                name="dwd_hdc_income_summary_view",
                columns=(
                    reporting_contract.ModelColumn(
                        name="period_code",
                        dataType="VARCHAR(255)",
                        nullable=True,
                        description="数据月份",
                    ),
                    reporting_contract.ModelColumn(
                        name="data_date",
                        dataType="DATE",
                        nullable=True,
                        description="数据日期",
                    ),
                ),
            ),
        ),
    )

    normalized = reporting_runtime._normalize_preferred_typed_period_fields(
        plan,
        (snapshot,),
        report_goal="严格使用 period_code 分析2025年月度收入趋势",
    )

    assert normalized == plan


def test_requirement_periods_restore_frozen_data_understanding() -> None:
    bundle = analysis_bundle(
        table="rj.dwd_hdc_income_summary_view",
        period_granularity="month",
    )

    normalized, repairs = _normalize_requirement_periods(bundle, data_understanding())

    table = normalized.requirements[0].tables[0]
    assert table.period_column == "data_date"
    assert table.period_granularity == "date"
    assert repairs == [
        {
            "requirementId": "req_income",
            "tableIndex": 0,
            "table": "rj.dwd_hdc_income_summary_view",
            "periodColumn": "data_date",
            "periodGranularity": "date",
        }
    ]


def test_requirement_periods_do_not_guess_unknown_table() -> None:
    bundle = analysis_bundle(
        table="rj.unknown_income_view",
        period_granularity="month",
    )

    normalized, repairs = _normalize_requirement_periods(bundle, data_understanding())

    assert normalized is bundle
    assert repairs == []


@pytest.mark.parametrize(
    "table_ref",
    ["dwd_hdc_income_summary_view", "rj.dwd_hdc_income_summary_view"],
)
def test_requirement_measure_field_refs_use_snapshot_database(table_ref: str) -> None:
    requirement = analysis_bundle(table=table_ref, period_granularity="date").requirements[0]
    snapshot = reporting_contract.SourceSchemaSnapshot(
        source="metadata_api",
        revision="revision-1",
        schemaHash="a" * 64,
        tables=(
            reporting_contract.ModelTable(
                sourceId="rj",
                database="rj",
                name="dwd_hdc_income_summary_view",
                columns=(
                    reporting_contract.ModelColumn(
                        name="indicator_value",
                        dataType="DECIMAL(18,2)",
                        nullable=True,
                    ),
                ),
            ),
        ),
    )

    refs = _requirement_measure_field_refs(requirement, (snapshot,))

    assert refs == {"rj.rj.dwd_hdc_income_summary_view.indicator_value"}


def test_requirement_measure_field_refs_reject_ambiguous_bare_table() -> None:
    requirement = analysis_bundle(
        table="dwd_hdc_income_summary_view",
        period_granularity="date",
    ).requirements[0]
    snapshot = reporting_contract.SourceSchemaSnapshot(
        source="metadata_api",
        revision="revision-1",
        schemaHash="a" * 64,
        tables=tuple(
            reporting_contract.ModelTable(
                sourceId="rj",
                database=database,
                name="dwd_hdc_income_summary_view",
                columns=(
                    reporting_contract.ModelColumn(
                        name="indicator_value",
                        dataType="DECIMAL(18,2)",
                        nullable=True,
                    ),
                ),
            )
            for database in ("rj", "archive")
        ),
    )

    assert _requirement_measure_field_refs(requirement, (snapshot,)) == set()


def test_reporting_analysis_plan_projects_only_unfinished_items() -> None:
    plan = DetailedAnalysisPlan.model_validate(
        {
            "datasetIds": ["dataset-1"],
            "analyses": [
                {
                    "analysisId": analysis_id,
                    "domain": "income",
                    "managementQuestion": f"分析 {analysis_id}",
                    "primaryMetricFamily": "收入",
                    "datasetIds": ["dataset-1"],
                    "fields": ["income_amount"],
                    "metrics": ["收入"],
                    "periods": [],
                    "organizationGrain": ["department"],
                    "actions": ["趋势", "复算"],
                    "evidenceSummary": "保存证据",
                    "limitations": ["月度数据不完整"],
                    "suggestedSection": "overview",
                    "completionConditions": ["完成"],
                }
                for analysis_id in ("analysis_001", "analysis_002")
            ],
        }
    )

    projected = _reporting_detailed_analysis_plan(
        plan,
        analysis_ids=("analysis_002",),
    )

    assert [item["analysisId"] for item in projected["analyses"]] == ["analysis_002"]
    assert projected["analyses"][0] == {
        "analysisId": "analysis_002",
        "domain": "income",
        "step": "分析 analysis_002",
        "primaryMetricFamily": "收入",
        "datasetIds": ["dataset-1"],
        "fields": ["income_amount"],
        "metrics": ["收入"],
        "organizationGrain": ["department"],
        "actions": ["趋势", "复算"],
        "limitations": ["月度数据不完整"],
    }


def test_outline_section_can_reference_multiple_atomic_analysis_items() -> None:
    proposal = ReportOutlineProposal.model_validate(
        {
            "reportType": "comprehensive",
            "title": "年度运营分析报告",
            "sections": [
                {
                    "title": "经营结果与资源效率",
                    "focus": ["比较经营结果与资源投入"],
                    "analysisIds": ["analysis_001", "analysis_002", "analysis_003"],
                }
            ],
            "assumptions": [],
        }
    )

    assert proposal.sections[0].analysis_ids == (
        "analysis_001",
        "analysis_002",
        "analysis_003",
    )


@pytest.mark.anyio
async def test_confirm_source_keeps_internal_agent_out_of_request_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = "source-1"
    source = SimpleNamespace(id=source_id, name="测试数据源", database="reporting")
    profile = SimpleNamespace(
        dimensions=(),
        metrics=(),
        reconciliations=(),
        scope_filters=(),
        measure_semantics=(),
        profile_id="profile-1",
        effective_profile_hash="a" * 64,
        model_dump=lambda **_: {
            "profileId": "profile-1",
            "effectiveProfileHash": "a" * 64,
        },
    )
    snapshot = SimpleNamespace(
        revision="revision-1",
        schema_hash="b" * 64,
        tables=(),
        model_dump=lambda **_: {
            "source": "metadata_api",
            "revision": "revision-1",
            "schemaHash": "b" * 64,
            "tables": [],
            "terms": [],
            "measureSemantics": [],
        },
    )
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime.registry = SimpleNamespace(
        default_source_ids=(source_id,),
        sources={source_id: object()},
    )
    runtime.metadata_client = SimpleNamespace(
        query_agent=AsyncMock(return_value=SimpleNamespace(code="1")),
        query_model=AsyncMock(return_value=None),
    )
    runtime._starrocks_source = lambda _item: source
    runtime._resolve_profile = lambda _sources: profile
    runtime._state = lambda context: context.session_state
    runtime._assert_state_safe = lambda _state: None
    monkeypatch.setattr(
        reporting_runtime,
        "require_sources",
        lambda _sources, _source_ids: (object(),),
    )
    monkeypatch.setattr(
        reporting_runtime,
        "_schema_scope_tables",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        reporting_runtime,
        "StarRocksDataSourceAdapter",
        type(
            "EmptyAdapter",
            (),
            {
                "__init__": lambda self, *_args, **_kwargs: None,
                "catalog": lambda self: _empty_catalog(),
                "aclose": lambda self: _empty_close(),
            },
        ),
    )
    monkeypatch.setattr(
        reporting_runtime,
        "resolve_schema_snapshot",
        lambda *_args, **_kwargs: snapshot,
    )
    monkeypatch.setattr(
        reporting_runtime,
        "_apply_profile_scope_filters_to_snapshots",
        lambda snapshots, _profile: snapshots,
    )

    request = reporting_contract.ReportRequestEnvelope.model_validate(
        {
            "reportGoal": "验证请求状态边界",
            "reportType": "comprehensive",
            "period": {"start": "2025-01-01", "end": "2025-12-31"},
            "sourceIds": [source_id],
        }
    )
    context = SimpleNamespace(
        input=request.model_dump(mode="json", by_alias=True),
        previous_step_content=None,
        session_state={},
    )

    await runtime.confirm_source(context, context)

    workflow_input = context.session_state[REPORT_WORKFLOW_INPUT_STATE_KEY]
    assert "agentId" not in workflow_input
    assert reporting_contract.ReportRequestEnvelope.from_untrusted(workflow_input).report_goal == (
        "验证请求状态边界"
    )


async def _empty_catalog() -> tuple[object, ...]:
    return ()


async def _empty_close() -> None:
    return None


def test_analysis_item_instructions_submit_facts_without_model_evidence() -> None:
    instructions = "\n".join(REPORT_ANALYSIS_ITEM_AGENT_INSTRUCTIONS)

    assert "任务 JSON 的 sectionGoal 标识当前分析所属章节" in instructions
    assert "不得为其他章节生成证据或结论" in instructions
    assert "固定事实足够时不得创建脚本或 evidence 文件" in instructions
    assert "evidencePaths 传空数组" in instructions
    assert "deterministicFactFile 直接冻结为 evidence" in instructions
    assert "完整内联 deterministicFacts 时不得默认调用 query_analysis_facts" in instructions
    assert "facts 被标记为 truncated" in instructions
    assert (
        "currentAnalysis 已固定 fields、metrics、organizationGrain、actions 和 limitations"
        in instructions
    )
    assert "不得为探索 facts 结构" in instructions
    assert "固定事实足够时立即调用 complete_analysis_item" in instructions
    assert "truncated 或当前管理问题缺少必需事实" in instructions
    assert "不得猜测、补齐或替代缺失事实" in instructions
    assert "不执行摘要百分比启发式匹配" in instructions
    assert "脚本必须从工作区根目录执行" in instructions
    assert "python3 <analysisOutputRoot>/script.py" in instructions
    assert "不得 cd 到 evidence/analysis_*" in instructions
    assert "不得猜测 /workspace" in instructions
    assert "不得用 pwd、ls、find 或 wc 探测" in instructions
    assert "不要给成功的脚本执行附加探测命令" in instructions
    assert "脚本修改统一使用 apply_analysis_patch" in instructions
    assert (
        "成功脚本的 stdout 仅输出 evidencePath、处理行数、固定事实对账值和核心可比指标"
        in instructions
    )
    assert "完整聚合结果只写入 evidence JSON" in instructions
    assert "只有证据直接证明因果链时才使用“导致”或“完全由”" in instructions


def test_section_instructions_match_evidence_file_authorization() -> None:
    instructions = "\n".join(REPORT_SECTION_AGENT_INSTRUCTIONS)

    assert "factSummaries" in instructions
    assert "evidenceFiles" in instructions
    assert "factFiles 仅用于事实身份和追溯元数据" in instructions
    assert "只按 factFiles 定点读取" not in instructions
    assert "补读原始 facts/evidence" not in instructions


@pytest.mark.anyio
async def test_prepare_analysis_context_bounds_profile_upload_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_content = b"month,amount\n2025-01,1\n"
    profile_content = b'{"profile":"complete"}'
    dataset_id = "attachment-dataset"
    dataset_path = "reporting-inputs/input.csv"
    profile_path = f"报表/分析计划/run-1/profiles/{dataset_id}.profile.json"
    handle = DatasetHandle(
        dataset_id=dataset_id,
        source_id="attachment-001",
        source_type="url_csv",
        filename="input.csv",
        path=dataset_path,
        row_count=1,
        size=len(dataset_content),
        sha256=hashlib.sha256(dataset_content).hexdigest(),
        requirement_id="attachment-001",
        sql_hash="a" * 64,
    )
    context = DatasetAnalysisContext(
        profileFile=AnalysisFileIdentity(
            path=profile_path,
            size=len(profile_content),
            sha256=hashlib.sha256(profile_content).hexdigest(),
        ),
        profileModelView={},
        profileEngineVersion="test",
        datasetId=dataset_id,
        path=dataset_path,
        size=len(dataset_content),
        sha256=handle.sha256,
        rowCount=1,
        columnCount=2,
        fields=("month", "amount"),
        numericFields=("amount",),
        periodValues=("2025-01",),
        timeSeriesSortField="month",
    )

    class RecordingFileSystem:
        def __init__(self) -> None:
            self.files = {dataset_path: dataset_content}
            self.upload_timeouts: list[int] = []

        async def upload_file(self, content: bytes, path: str, timeout: int = 30 * 60) -> None:
            self.upload_timeouts.append(timeout)
            self.files[path] = content

    filesystem = RecordingFileSystem()
    sandbox = SimpleNamespace(fs=filesystem)

    class FakeWorkspaceService:
        @asynccontextmanager
        async def _async_client(self):
            yield object()

        async def _asandbox_for(self, _client: object, _thread_id: str):
            return sandbox

        @staticmethod
        def normalize_path(path: str, *, allow_root: bool) -> tuple[str, str]:
            assert allow_root is False
            return path, path

        @staticmethod
        async def _aensure_directory(_sandbox: object, _path: str) -> None:
            return None

        @staticmethod
        async def _adownload_file(_sandbox: object, path: str, _size: int) -> bytes:
            return filesystem.files[path]

        @staticmethod
        def _validate_content(_content: bytes) -> None:
            return None

    monkeypatch.setattr(
        reporting_datasets,
        "profile_csv_dataset",
        lambda *_args, **_kwargs: ProfiledDataset(
            context=context,
            profile={},
            profile_content=profile_content,
        ),
    )
    # 本用例验证上传超时，不验证进程池；局部 lambda 不能跨进程序列化。
    monkeypatch.setattr(reporting_datasets, "_profile_process_pool", lambda: None)
    state: dict[str, Any] = {REPORT_WORKFLOW_RESULT_STATE_KEY: {"datasets": [handle.public_dict()]}}
    runtime: Any = object.__new__(RuntimeDatasetsMixin)
    runtime.workspace_service = FakeWorkspaceService()
    runtime._state = lambda _run_context: state
    runtime._workflow_result = lambda _state: dict(state[REPORT_WORKFLOW_RESULT_STATE_KEY])
    runtime._scope = lambda _run_context: {"threadId": "thread-1"}
    runtime._snapshots = lambda _run_context: ()
    runtime._assert_state_safe = lambda _state: None

    await runtime.prepare_analysis_context(
        SimpleNamespace(),
        SimpleNamespace(run_id="run-1"),
    )

    assert filesystem.upload_timeouts == [5 * 60]


def test_phase_instructions_prioritize_signed_execution_directive() -> None:
    analysis = "\n".join(REPORT_ANALYSIS_ITEM_AGENT_INSTRUCTIONS)
    visualization = "\n".join(REPORT_VISUALIZATION_SECTION_AGENT_INSTRUCTIONS)
    section = "\n".join(REPORT_SECTION_AGENT_INSTRUCTIONS)

    for instructions in (analysis, visualization, section):
        assert "executionDirective 是本任务的首要动作契约" in instructions
        assert "不得输出解释文字" in instructions
    assert "process 不能启动命令" in analysis
    assert "不得重复完全相同的 patch 参数" in visualization
    assert "不得使用 read_file 读取 factFiles" in section


def test_patch_instructions_include_complete_unified_diff_templates() -> None:
    analysis_instructions = "\n".join(REPORT_ANALYSIS_ITEM_AGENT_INSTRUCTIONS)
    visualization_instructions = "\n".join(REPORT_VISUALIZATION_SECTION_AGENT_INSTRUCTIONS)

    for instructions in (analysis_instructions, visualization_instructions):
        assert "--- a/path/file.py\n+++ b/path/file.py\n@@ -1 +1 @@" in instructions
        assert "--- /dev/null\n+++ b/path/file.py\n@@ -0,0 +1 @@" in instructions
        assert "--- a/path/file.py\n+++ /dev/null\n@@ -1 +0,0 @@" in instructions
        assert "单行文件更新必须使用 @@ -1 +1 @@" in instructions
        assert "expected_sha256 的值必须是 64 位小写十六进制字符串" in instructions
        assert "不需要基线时省略 expected_sha256" in instructions


@pytest.mark.anyio
async def test_detailed_analysis_plan_only_requires_csv_evidence_for_fact_gaps() -> None:
    context = DatasetAnalysisContext(
        profileFile=AnalysisFileIdentity(path="profiles/dataset-1.json", size=1, sha256="a" * 64),
        profileModelView={},
        profileEngineVersion="4.19.1",
        datasetId="dataset-1",
        path="datasets/dataset-1.csv",
        size=1,
        sha256="b" * 64,
        rowCount=1,
        columnCount=3,
        fields=("month", "department", "amount"),
        organizationGrain=("department",),
        metricSemantics=(
            {
                "fieldRef": "source.database.income.amount",
                "aggregation": "sum",
            },
        ),
        numericFields=("amount",),
        periodValues=("2025-01",),
        timeSeriesSortField="month",
    )
    handle = DatasetHandle(
        dataset_id="dataset-1",
        source_id="source-1",
        path="datasets/dataset-1.csv",
        row_count=1,
        size=1,
        sha256="b" * 64,
        requirement_id="requirement-1",
        sql_hash="c" * 64,
    )
    attachment_context = context.model_copy(
        update={
            "dataset_id": "attachment-dataset",
            "path": "reporting-inputs/op/0-input.csv",
            "sha256": "e" * 64,
        }
    )
    attachment_handle = DatasetHandle(
        dataset_id="attachment-dataset",
        source_id="attachment-001",
        source_type="url_csv",
        filename="input.csv",
        path="reporting-inputs/op/0-input.csv",
        row_count=1,
        size=1,
        sha256="e" * 64,
        requirement_id="attachment-001",
        sql_hash="f" * 64,
    )
    coverage = ProfileCoverageManifest(
        authorizedDatasetCount=2,
        coveredDatasetCount=2,
        datasets=(
            ProfileCoverageDataset(
                datasetId="dataset-1",
                datasetPath="datasets/dataset-1.csv",
                datasetSize=1,
                datasetSnapshotHash="b" * 64,
                profileFile=FileIdentity(path="profiles/dataset-1.json", size=1, sha256="a" * 64),
                rowCount=1,
                fieldCount=3,
                fields=("month", "department", "amount"),
                periodCoverage=("2025-01",),
            ),
            ProfileCoverageDataset(
                datasetId="attachment-dataset",
                datasetPath="reporting-inputs/op/0-input.csv",
                datasetSize=1,
                datasetSnapshotHash="e" * 64,
                profileFile=FileIdentity(path="profiles/attachment.json", size=1, sha256="f" * 64),
                rowCount=1,
                fieldCount=3,
                fields=("month", "department", "amount"),
                periodCoverage=("2025-01",),
            ),
        ),
    )
    state: dict[str, Any] = {
        REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY: [
            context.model_dump(mode="json", by_alias=True),
            attachment_context.model_dump(mode="json", by_alias=True),
        ],
        REPORT_PROFILE_COVERAGE_STATE_KEY: coverage.model_dump(mode="json", by_alias=True),
        REPORT_ANALYSIS_PLAN_STATE_KEY: [
            {
                "code": "income",
                "description": "收入规模分析",
                "managementQuestion": "收入规模如何？",
                "primaryMetricFamily": "收入",
                "requirementIds": ["requirement-1"],
            }
        ],
        REPORT_WORKFLOW_RESULT_STATE_KEY: {
            "datasets": [handle.public_dict(), attachment_handle.public_dict()]
        },
    }
    runtime: Any = object.__new__(RuntimeDatasetsMixin)
    runtime._state = lambda _run_context: state
    runtime._envelope = lambda _run_context: SimpleNamespace(
        domains=("income",), report_goal="分析收入规模"
    )
    runtime._profile = lambda _run_context: SimpleNamespace(metrics=())
    runtime._workflow_result = lambda _state: dict(state[REPORT_WORKFLOW_RESULT_STATE_KEY])
    runtime._scope = lambda _run_context: {"threadId": "thread-1"}
    runtime._write_artifact_validation_context = AsyncMock(
        return_value=FileIdentity(path="analysis/context.json", size=1, sha256="d" * 64)
    )
    runtime._apply_durable_command = AsyncMock()
    runtime._assert_state_safe = lambda _state: None

    output = await runtime.generate_detailed_analysis_plan(
        SimpleNamespace(), SimpleNamespace(run_id="run-1")
    )

    analysis = DetailedAnalysisPlan.model_validate(output.content).analyses[0]
    assert analysis.dataset_ids == ("dataset-1", "attachment-dataset")
    assert (
        "仅当 deterministicFacts 未覆盖当前管理问题的必需事实时，从不可变 CSV 复算并保存补充 evidence"
        in analysis.actions
    )
    assert "deterministicFacts 覆盖当前管理问题时直接提交" in analysis.evidence_summary
    assert (
        "仅在必需事实缺口时由 Reporting 从 CSV 复算并保存补充 evidence" in analysis.evidence_summary
    )
    assert (
        "deterministicFacts 覆盖当前管理问题时立即且只调用一次 complete_analysis_item，"
        "evidencePaths 传空数组" in analysis.completion_conditions
    )
    assert (
        "仅当 deterministicFacts 未覆盖当前管理问题的必需事实时，按 analysisId 从 CSV 复算"
        "并保存最小补充 evidence" in analysis.completion_conditions
    )
    assert "按 analysisId 完成 CSV 复算并保存可复现证据" not in analysis.completion_conditions


def test_analysis_item_prompt_does_not_duplicate_detailed_plan() -> None:
    source = textwrap.dedent(inspect.getsource(ReportWorkflowRuntime._run_analysis_item_task))
    tree = ast.parse(source)
    string_keys = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert "analysisPlans" in string_keys
    assert "detailedAnalysisPlan" not in string_keys


def test_analysis_item_dataset_inputs_bind_columns_to_each_signed_path() -> None:
    first = DatasetHandle(
        dataset_id="dataset-income",
        source_id="source-1",
        path="datasets/income.csv",
        row_count=1,
        size=10,
        sha256="a" * 64,
        requirement_id="requirement-1",
        sql_hash="b" * 64,
    )
    second = DatasetHandle(
        dataset_id="dataset-budget",
        source_id="source-1",
        path="datasets/budget.csv",
        row_count=1,
        size=10,
        sha256="c" * 64,
        requirement_id="requirement-2",
        sql_hash="d" * 64,
    )
    context = DatasetAnalysisContext(
        profileFile=AnalysisFileIdentity(path="profiles/income.json", size=1, sha256="e" * 64),
        profileModelView={},
        profileEngineVersion="test",
        datasetId=first.dataset_id,
        path=first.path,
        size=first.size,
        sha256=first.sha256,
        rowCount=first.row_count,
        columnCount=2,
        fields=("income_type", "actual_income"),
        numericFields=("actual_income",),
        periodValues=(),
    )
    budget_context = context.model_copy(
        update={
            "dataset_id": second.dataset_id,
            "path": second.path,
            "size": second.size,
            "sha256": second.sha256,
            "fields": ("budget_type", "budget_income"),
            "numeric_fields": ("budget_income",),
        }
    )

    inputs = _analysis_item_dataset_inputs((first, second), (context, budget_context))

    assert inputs[0]["columns"] == ["income_type", "actual_income"]
    assert inputs[1]["columns"] == ["budget_type", "budget_income"]


def test_analysis_item_output_root_isolated_by_fresh_attempt() -> None:
    first = _analysis_item_output_root("run-1", "analysis_001", 0)
    second = _analysis_item_output_root("run-1", "analysis_001", 1)

    assert first == "报表/智能分析/run-1/evidence/analysis_001/attempt-1"
    assert second == "报表/智能分析/run-1/evidence/analysis_001/attempt-2"
    assert first != second


def test_analysis_thinking_effort_uses_explicit_planner_policy() -> None:
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._analysis_thinking_enabled = True
    assert runtime._analysis_thinking_effort() == "high"
    runtime._analysis_thinking_enabled = False
    assert runtime._analysis_thinking_effort() == "off"


def test_analysis_item_complexity_uses_structured_plan_fields() -> None:
    simple = {
        "datasetIds": ["ds-1"],
        "fields": ["month"],
        "metrics": ["income"],
        "periods": ["2025"],
        "comparisonBasis": [],
        "organizationGrain": [],
        "actions": ["summarize"],
        "recommendedCharts": [],
    }
    complex_plan = {
        "datasetIds": ["ds-1", "ds-2"],
        "fields": ["month", "area", "department"],
        "metrics": ["income", "volume"],
        "periods": ["2024", "2025"],
        "comparisonBasis": ["yoy"],
        "organizationGrain": ["area", "department"],
        "actions": ["compare", "attribute", "recommend"],
        "recommendedCharts": ["trend", "contribution"],
    }

    assert _analysis_item_complexity(simple) == (0, "simple")
    assert _analysis_item_complexity(complex_plan) == (9, "complex")

    standard = {**simple, "comparisonBasis": ["yoy"], "organizationGrain": ["area"]}
    assert _analysis_item_complexity(standard) == (3, "standard")


def test_analysis_item_thinking_policy_escalates_only_for_evidence_failures() -> None:
    plan = {"metrics": ["income"], "datasetIds": ["ds-1"]}

    assert _analysis_item_thinking_policy(plan, retry=False, retry_reason=None) == (
        "high",
        4096,
        "simple",
    )
    assert _analysis_item_thinking_policy(plan, retry=False, retry_reason="schema_validation") == (
        "high",
        4096,
        "simple",
    )
    assert _analysis_item_thinking_policy(plan, retry=True, retry_reason="evidence_incomplete") == (
        "max",
        8192,
        "simple",
    )


def test_analysis_evidence_accepts_legacy_evidence_paths_without_bypassing_identity() -> None:
    payload = {
        "analysisId": "analysis_001",
        "summary": "完成摘要",
        "datasetIds": ["dataset_001"],
        "evidenceFiles": [
            {"path": "evidence/analysis_001/facts.json", "size": 1, "sha256": "a" * 64}
        ],
        "evidencePaths": ["evidence/analysis_001/facts.json"],
        "citationIds": ["citation_001"],
    }

    evidence = AnalysisEvidence.model_validate(payload)

    assert evidence.evidence_files[0].path == "evidence/analysis_001/facts.json"
    assert "evidencePaths" not in evidence.model_dump(mode="json", by_alias=True)


def test_analysis_evidence_still_requires_hashed_evidence_files_when_only_paths_are_present() -> (
    None
):
    with pytest.raises(ValidationError):
        AnalysisEvidence.model_validate(
            {
                "analysisId": "analysis_001",
                "summary": "完成摘要",
                "datasetIds": ["dataset_001"],
                "evidencePaths": ["evidence/analysis_001/facts.json"],
                "citationIds": ["citation_001"],
            }
        )


@pytest.mark.anyio
async def test_analysis_script_repair_temporarily_escalates_to_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_context = RunContext(
        run_id="task-run-1",
        session_id="task-session-1",
        dependencies={
            "AgentOS 任务执行": {
                "reportingThinkingEffort": "high",
                "reportingThinkingBudget": 4096,
            }
        },
    )
    observed: list[tuple[str, str, int]] = []
    planner_requests: list[dict[str, Any]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = SimpleNamespace()
    runtime.task_runner = SimpleNamespace(repository=SimpleNamespace())
    runtime.state_repository = SimpleNamespace()
    runtime._analysis_evidence_agent = SimpleNamespace()
    runtime._analysis_script_agent = SimpleNamespace()
    runtime._analysis_summary_agent = SimpleNamespace()

    async def run_planner(_agent, payload, _parent_context):
        planner_requests.append(payload)
        binding = task_context.dependencies["AgentOS 任务执行"]
        observed.append(
            (
                payload["analysisBlock"]["blockId"],
                binding["reportingThinkingEffort"],
                binding["reportingThinkingBudget"],
            )
        )
        if payload["analysisBlock"]["blockId"].endswith(":summary"):
            return AnalysisSummaryDraft(summary="完成摘要", warnings=())
        if payload["analysisBlock"]["blockId"].endswith(":decision"):
            return AnalysisEvidenceDecision(
                requiresSupplementalEvidence=True,
                reason="缺少构成",
                missingFacts=("构成",),
            )
        return AnalysisScriptDraft(script="print('evidence')")

    class FakeAnalysisItemWorkflow:
        def __init__(self, *, plan_evidence, summarize, **_kwargs):
            self.plan_evidence = plan_evidence
            self.summarize = summarize

        async def run(self, _payload, _run_context):
            planner_payload = {
                "currentAnalysis": {"analysisId": "analysis_001"},
                "deterministicFacts": {"analysisId": "analysis_001", "metrics": []},
                "datasets": [{"datasetId": "dataset_001", "path": "datasets/data.csv"}],
                "analysisOutputRoot": "evidence/analysis_001",
                "scriptPath": "evidence/analysis_001/supplement.py",
                "evidencePath": "evidence/analysis_001/supplement.json",
            }
            initial = await self.plan_evidence(planner_payload, repair=False)
            await self.plan_evidence(
                {
                    **planner_payload,
                    "correction": {
                        "attempt": 2,
                        "previousPlan": initial.model_dump(mode="json", by_alias=True),
                        "error": {
                            "code": "report_analysis_script_failed",
                            "message": "脚本执行失败。",
                        },
                    },
                },
                repair=True,
            )
            await self.summarize({})
            return SimpleNamespace(output=StepOutput(content={"ok": True}))

    runtime._run_planner = run_planner
    monkeypatch.setattr(
        "smart_reporting.reporting.workflow.runtime.analysis.build_reporting_tools",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                read_file=AsyncMock(),
                apply_analysis_patch=AsyncMock(),
                terminal=AsyncMock(),
                complete_analysis_item=AsyncMock(),
            )
        ],
    )
    monkeypatch.setattr(
        "smart_reporting.reporting.workflow.runtime.analysis.AnalysisItemWorkflow",
        FakeAnalysisItemWorkflow,
    )

    await runtime._execute_analysis_item_workflow(
        '{"currentAnalysisId":"analysis_001"}',
        task_context,
        parent_run_context=RunContext(
            run_id="report-run-1", session_id="report-session-1", session_state={}
        ),
    )

    assert observed == [
        ("analysis_001:evidence:decision", "high", 4096),
        ("analysis_001:evidence:script:initial", "high", 4096),
        ("analysis_001:evidence:script:repair", "max", 8192),
        ("analysis_001:summary", "high", 4096),
    ]
    assert set(planner_requests[0]) == {
        "currentAnalysis",
        "deterministicFacts",
        "analysisBlock",
    }
    assert "deterministicFacts" not in planner_requests[1]
    assert planner_requests[1]["evidenceDecision"]["missingFacts"] == ["构成"]
    assert "deterministicFacts" not in planner_requests[2]
    assert planner_requests[2]["previousScript"] == "print('evidence')"
    assert task_context.dependencies["AgentOS 任务执行"] == {
        "reportingThinkingEffort": "high",
        "reportingThinkingBudget": 4096,
    }


def test_model_facing_deterministic_facts_strips_identity_metadata_and_deduplicates_warnings() -> (
    None
):
    bundle = DeterministicAnalysisBundle.model_validate(
        {
            "analysisId": "analysis_001",
            "metrics": [
                {
                    "datasetId": "dataset-1",
                    "datasetSha256": "a" * 64,
                    "profileHash": "b" * 64,
                    "periodRoles": ["current"],
                    "metricCodes": ["income_total"],
                    "field": "income",
                    "fieldRef": "rj.income",
                    "aggregation": "sum",
                    "unit": "元",
                    "formula": "sum(income)",
                    "total": 10,
                    "missingCount": 0,
                    "zeroCount": 0,
                    "negativeCount": 0,
                    "warnings": ["期间不完整", "期间不完整"],
                },
                {
                    "datasetId": "dataset-1",
                    "datasetSha256": "a" * 64,
                    "profileHash": "b" * 64,
                    "periodRoles": ["current"],
                    "metricCodes": ["income_count"],
                    "field": "count",
                    "fieldRef": "rj.count",
                    "aggregation": "sum",
                    "unit": "人次",
                    "formula": "sum(count)",
                    "total": 5,
                    "missingCount": 0,
                    "zeroCount": 0,
                    "negativeCount": 0,
                    "warnings": ["期间不完整", "字段缺失"],
                },
            ],
            "warnings": ["期间不完整", "全局告警", "全局告警"],
        }
    )

    projected = _model_facing_deterministic_facts(bundle)

    assert all(
        "datasetSha256" not in item and "profileHash" not in item for item in projected["metrics"]
    )
    assert projected["metrics"][0]["warnings"] == ["期间不完整"]
    assert projected["metrics"][1]["warnings"] == ["字段缺失"]
    assert projected["warnings"] == ["全局告警"]
    assert bundle.metrics[0].dataset_sha256 == "a" * 64
    assert bundle.metrics[0].warnings == ("期间不完整", "期间不完整")


def test_instruction_component_bytes_reports_sizes_without_content() -> None:
    payload = {
        "currentAnalysis": {"summary": "收入"},
        "deterministicFacts": {"facts": [1, 2]},
        "analysisContextFile": {"path": "facts.json", "size": 10},
        "ignoredField": {"secret": "不应记录"},
    }

    sizes = ReportWorkflowRuntime._instruction_component_bytes(payload)

    assert sizes["current_analysis"] == len('{"summary":"收入"}'.encode())
    assert sizes["deterministic_facts"] == len('{"facts":[1,2]}')
    assert sizes["analysis_context_file"] == len('{"path":"facts.json","size":10}')
    assert "ignoredField" not in sizes


def test_visualization_instructions_fail_closed_for_untrusted_or_missing_chart_data() -> None:
    instructions = "\n".join(REPORT_VISUALIZATION_SECTION_AGENT_INSTRUCTIONS)

    assert "未签发文件" in instructions
    assert "缺失、为空或无法解析" in instructions
    assert "跳过对应图表" in instructions
    assert "结构化诊断" in instructions
    assert "不得让单张图表失败终止整批脚本" in instructions
    assert "先规范化为可迭代的空行集合" in instructions
    assert "查询结果为 None 时必须使用空行集合" in instructions


def test_planner_validation_runs_inside_agent_retry_boundary() -> None:
    planner = Agent(
        model=ReportingPhaseOpenAIChat(
            id="deepseek-v4-flash-0731",
            api_key="test",
            reasoning_effort="high",
            extra_body={"enable_thinking": True, "thinking_budget": 16384},
            retries=2,
            exponential_backoff=True,
        ),
        retries=2,
        exponential_backoff=True,
    )

    stage = ReportWorkflowRuntime._planning_agent(
        planner,
        "report-data-understanding-planner",
        DataUnderstandingPlan,
        thinking_profile=ReportingThinkingProfile.off(),
    )

    assert stage.retries == 2
    assert stage.exponential_backoff is True
    assert stage.telemetry is False
    assert stage.model.retries == 0
    assert stage.model.extra_body == {"enable_thinking": False}
    assert stage.model.reasoning_effort is None
    validator = getattr(stage.model, "_report_response_validator")
    with pytest.raises(ValidationError):
        validator("{}")


def test_runtime_planners_use_stage_specific_thinking_profiles() -> None:
    agent_template = Agent(
        model=ReportingPhaseOpenAIChat(
            id="deepseek-v4-flash-0731",
            api_key="test",
            reasoning_effort="high",
            extra_body={"enable_thinking": True, "thinking_budget": 8192},
        )
    )

    runtime = ReportWorkflowRuntime(
        db=SimpleNamespace(),
        reporting_agent_template=agent_template,
        task_runner=SimpleNamespace(),
        workspace_service=SimpleNamespace(),
        registry=SimpleNamespace(),
        profiles=SimpleNamespace(),
        planner_enable_thinking=True,
        planner_thinking_budget=8192,
        state_repository=SimpleNamespace(),
    )

    assert runtime.analysis_concurrency == 1
    assert runtime.section_concurrency == 1
    assert any(
        "不得生成 script" in instruction
        for instruction in runtime._analysis_evidence_agent.instructions
    )
    assert any(
        "所有后续读取的局部变量" in instruction
        for instruction in runtime._analysis_script_agent.instructions
    )
    assert all(
        "32000" not in instruction and "240 行" not in instruction
        for instruction in runtime._analysis_script_agent.instructions
    )
    expected_profiles = (
        (runtime._data_understanding_agent, False, None, None, "high"),
        (runtime._measure_semantic_agent, False, None, None, "max"),
        (runtime._analysis_agent, True, "high", 4096, "max"),
        (runtime._analysis_evidence_agent, True, "high", 8192, "max"),
        (runtime._analysis_script_agent, True, "high", 8192, "max"),
        (runtime._sql_agent, False, None, None, "max"),
    )
    for stage, enabled, initial_effort, initial_budget, escalation_effort in expected_profiles:
        profile = reporting_thinking_profile_from_model(stage.model)
        assert profile.enabled is enabled
        if enabled:
            assert profile.reasoning_effort == initial_effort
            assert profile.thinking_budget == initial_budget
        escalation = getattr(stage.model, "_report_escalation_thinking_profile")
        assert escalation.enabled is True
        assert escalation.reasoning_effort == escalation_effort
        assert escalation.thinking_budget == 8192


def test_runtime_planners_project_reasoning_to_vllm_chat_template() -> None:
    agent_template = Agent(
        model=ReportingPhaseOpenAIChat(
            id="deepseek-v4-flash-0731",
            api_key="test",
            base_url="http://self-hosted.example/v1",
            reasoning_effort="high",
            extra_body={
                "enable_thinking": True,
                "thinking_budget": 8192,
                "chat_template_kwargs": {},
            },
        )
    )
    runtime = ReportWorkflowRuntime(
        db=SimpleNamespace(),
        reporting_agent_template=agent_template,
        task_runner=SimpleNamespace(),
        workspace_service=SimpleNamespace(),
        registry=SimpleNamespace(),
        profiles=SimpleNamespace(),
        planner_enable_thinking=True,
        planner_thinking_budget=8192,
        state_repository=SimpleNamespace(),
    )

    request_params = runtime._analysis_agent.model.get_request_params()

    assert "reasoning_effort" not in request_params
    assert request_params["extra_body"] == {
        "enable_thinking": True,
        "thinking_budget": 4096,
        "chat_template_kwargs": {
            "enable_thinking": True,
            "thinking": True,
            "reasoning_effort": "high",
        },
    }


def test_qwen_max_reasoning_uses_supported_xhigh_transport() -> None:
    model = ReportingPhaseOpenAIChat(id="qwen3.6-flash", api_key="test")

    apply_reporting_thinking_profile(
        model,
        ReportingThinkingProfile.on(reasoning_effort="max", thinking_budget=8192),
    )

    assert model.reasoning_effort == "xhigh"
    assert reporting_thinking_profile_from_model(model) == ReportingThinkingProfile.on(
        reasoning_effort="max",
        thinking_budget=8192,
    )


def test_dashscope_qwen_request_does_not_send_two_thinking_controls() -> None:
    model = ReportingPhaseOpenAIChat(
        id="qwen3.8-flash",
        api_key="test",
        base_url="https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    apply_reporting_thinking_profile(
        model,
        ReportingThinkingProfile.on(reasoning_effort="high", thinking_budget=8192),
    )

    request_params = model.get_request_params()

    assert "reasoning_effort" not in request_params
    assert request_params["extra_body"] == {
        "enable_thinking": True,
        "thinking_budget": 8192,
    }
    assert reporting_thinking_profile_from_model(model) == ReportingThinkingProfile.on(
        reasoning_effort="high",
        thinking_budget=8192,
    )


def test_measure_semantic_projection_drops_non_candidate_context_fields() -> None:
    candidate = "rj.rj.dwd_hdc_income_summary_view.indicator_value"
    proposal = MeasureSemanticProposal.model_validate(
        {
            "decisions": [
                {
                    "fieldRef": candidate,
                    "classification": "measure",
                    "reason": "收入金额字段。",
                    "measureSemantic": {
                        "fieldRef": candidate,
                        "aggregation": "sum",
                        "additiveAcross": ["period_code"],
                    },
                },
                {
                    "fieldRef": "rj.rj.dwd_hdc_income_summary_view.period_code",
                    "classification": "dimension",
                    "reason": "月份上下文字段。",
                },
            ]
        }
    )

    projected = reporting_runtime._project_measure_semantic_candidates(proposal, (candidate,))

    assert tuple(item.field_ref for item in projected.decisions) == (candidate,)


def test_analysis_planner_normalizes_repeated_source_prefix_before_schema_validation() -> None:
    planner = Agent(
        model=ReportingPhaseOpenAIChat(id="deepseek-v4-flash-0731", api_key="test"),
    )
    stage = ReportWorkflowRuntime._planning_agent(
        planner,
        "report-analysis-planner",
        AnalysisBundle,
        thinking_profile=ReportingThinkingProfile.off(),
    )
    payload = analysis_bundle(
        table="rj.dwd_hdc_income_summary_view",
        period_granularity="date",
    ).model_dump(mode="json", by_alias=True)
    payload["requirements"][0]["tables"][0]["table"] = "rj.rj.dwd_hdc_income_summary_view"

    validator = getattr(stage.model, "_report_response_validator")
    result = validator(json.dumps(payload))

    assert result.requirements[0].tables[0].table == "rj.dwd_hdc_income_summary_view"


def test_analysis_planner_normalizes_grain_into_dimensions_before_schema_validation() -> None:
    planner = Agent(
        model=ReportingPhaseOpenAIChat(id="deepseek-v4-flash-0731", api_key="test"),
    )
    stage = ReportWorkflowRuntime._planning_agent(
        planner,
        "report-analysis-planner",
        AnalysisBundle,
        thinking_profile=ReportingThinkingProfile.off(),
    )
    payload = analysis_bundle(
        table="rj.dwd_hdc_income_summary_view",
        period_granularity="date",
    ).model_dump(mode="json", by_alias=True)
    payload["requirements"][0]["grainColumns"] = ["data_date"]

    validator = getattr(stage.model, "_report_response_validator")
    result = validator(json.dumps(payload))

    assert result.requirements[0].dimension_columns == ("data_date",)
    assert result.requirements[0].grain_columns == ("data_date",)


def test_analysis_planner_disables_blind_agno_retries() -> None:
    stage = ReportWorkflowRuntime._planning_agent(
        Agent(model=ReportingPhaseOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")),
        "report-analysis-planner",
        AnalysisBundle,
        thinking_profile=ReportingThinkingProfile.off(),
    )

    assert stage.retries == 0
    assert stage.exponential_backoff is False


def test_analysis_correction_restores_unapproved_changes() -> None:
    previous = analysis_bundle(
        table="rj.dwd_hdc_income_summary_view",
        period_granularity="date",
    ).model_dump(mode="json", by_alias=True)
    corrected = json.loads(json.dumps(previous))
    corrected["analyses"][0]["description"] = "模型意外改写的描述"
    corrected["requirements"][0]["dimensionColumns"] = ["data_date"]
    corrected["requirements"][0]["grainColumns"] = ["data_date"]

    projected = reporting_runtime._restore_unapproved_correction_changes(
        previous,
        corrected,
        ("analyses[0].description",),
    )

    assert projected["analyses"][0]["description"] == "分析收入趋势"
    assert projected["requirements"][0]["dimensionColumns"] == ["data_date"]
    assert projected["requirements"][0]["grainColumns"] == ["data_date"]


def test_analysis_grain_correction_allows_related_join_columns() -> None:
    previous = {
        "analyses": [],
        "requirements": [
            {
                "requirementId": "req_combined",
                "relations": [
                    {
                        "leftTable": "rj.income",
                        "rightTable": "rj.cost",
                        "joinColumns": ["data_date"],
                    }
                ],
            }
        ],
    }
    issues = [
        {
            "path": "requirements[0].grainColumns",
            "repairTargets": [
                "requirements[0].dimensionColumns",
                "requirements[0].grainColumns",
            ],
        }
    ]

    allowed = reporting_runtime._analysis_allowed_mutation_paths(
        issues,
        previous_output=previous,
    )

    assert allowed == (
        "requirements[0].dimensionColumns",
        "requirements[0].grainColumns",
        "requirements[0].relations[0].joinColumns",
    )


@pytest.mark.anyio
async def test_generate_analysis_plan_retries_with_structural_validation_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = analysis_bundle(
        table="rj.dwd_hdc_income_summary_view",
        period_granularity="date",
    )
    invalid_payload = valid.model_dump(mode="json", by_alias=True)
    invalid_payload["requirements"][0]["tables"][0]["table"] = (
        "other.rj.dwd_hdc_income_summary_view"
    )
    stage = ReportWorkflowRuntime._planning_agent(
        Agent(model=ReportingPhaseOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")),
        "report-analysis-planner",
        AnalysisBundle,
        thinking_profile=ReportingThinkingProfile.off(),
    )
    planner_calls = 0

    async def fake_run_planner(_agent, payload, _run_context, **_kwargs):
        nonlocal planner_calls
        planner_calls += 1
        if planner_calls == 1:
            validator = getattr(_agent.model, "_report_response_validator")
            validator(json.dumps(invalid_payload))
        correction = payload["correction"]
        assert correction["allowedMutationPaths"] == ["requirements[0].tables[0].table"]
        assert correction["validationFeedback"]["code"] == "report_analysis_plan_invalid"
        return valid

    envelope = reporting_contract.ReportRequestEnvelope.model_validate(
        {
            "reportGoal": "分析2025年收入趋势",
            "reportType": "topic",
            "period": {"start": "2025-01-01", "end": "2025-12-31"},
            "domains": ["income"],
            "sourceIds": ["rj"],
        }
    )
    understanding = data_understanding()
    state: dict[str, Any] = {
        REPORT_WORKFLOW_INPUT_STATE_KEY: envelope.model_dump(mode="json", by_alias=True),
        reporting_runtime.REPORT_DATA_UNDERSTANDING_STATE_KEY: understanding.model_dump(
            mode="json", by_alias=True
        ),
    }
    profile = SimpleNamespace(reconciliations=(), duplicate_conflicts=())
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._analysis_agent = stage
    runtime._state = lambda _run_context: state
    runtime._snapshots = lambda _run_context: ()
    runtime._profile = lambda _run_context: profile
    runtime._capabilities = lambda _run_context: SimpleNamespace()
    runtime._data_shapes = lambda _run_context: ()
    runtime._data_understanding = lambda _run_context: understanding
    runtime._envelope = lambda _run_context: envelope
    runtime.resolve_capabilities = AsyncMock()
    runtime._run_planner = fake_run_planner
    monkeypatch.setattr(reporting_runtime, "build_outline_shape_view", lambda *args: None)
    monkeypatch.setattr(reporting_runtime, "_analysis_context_payload", lambda _value: {})
    monkeypatch.setattr(reporting_runtime, "_analysis_bundle_semantic_issues", lambda *args: [])

    output = await runtime.generate_analysis_plan(
        SimpleNamespace(), SimpleNamespace(session_state=state)
    )

    assert planner_calls == 2
    assert AnalysisBundle.model_validate(output.content) == valid


def test_analysis_planner_rejects_three_part_table_with_unrelated_source_prefix() -> None:
    planner = Agent(
        model=ReportingPhaseOpenAIChat(id="deepseek-v4-flash-0731", api_key="test"),
    )
    stage = ReportWorkflowRuntime._planning_agent(
        planner,
        "report-analysis-planner",
        AnalysisBundle,
        thinking_profile=ReportingThinkingProfile.off(),
    )
    payload = analysis_bundle(
        table="rj.dwd_hdc_income_summary_view",
        period_granularity="date",
    ).model_dump(mode="json", by_alias=True)
    payload["requirements"][0]["tables"][0]["table"] = "other.rj.dwd_hdc_income_summary_view"

    validator = getattr(stage.model, "_report_response_validator")
    with pytest.raises(ValidationError, match="database.table"):
        validator(json.dumps(payload))


@pytest.mark.parametrize(
    "sql",
    [
        (
            "SELECT data_date, SUM(indicator_value) AS indicator_value "
            "FROM rj.dwd_hdc_income_summary_view "
            "WHERE data_date >= DATE '2025-01-01' "
            "AND data_date <= DATE '2025-12-31' "
            "GROUP BY data_date"
        ),
        (
            "SELECT data_date, SUM(indicator_value) AS indicator_value "
            "FROM rj.dwd_hdc_income_summary_view "
            "WHERE data_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31' "
            "GROUP BY data_date"
        ),
    ],
)
def test_period_filter_accepts_exact_typed_date_bounds(sql: str) -> None:
    statement = parse_one(sql, read="mysql")

    assert _has_complete_period_filter(
        statement,
        alias="dwd_hdc_income_summary_view",
        column="data_date",
        period=ReportPeriod(start=date(2025, 1, 1), end=date(2025, 12, 31)),
        granularity="date",
    )


def test_measure_semantics_follow_cte_projection_alias() -> None:
    sql = (
        "WITH agg AS ("
        "SELECT data_date, SUM(indicator_value) AS measure_val "
        "FROM rj.dwd_hdc_income_summary_view "
        "GROUP BY data_date"
        ") SELECT data_date, measure_val FROM agg"
    )
    query = ApprovedQuery(
        requirementId="req_income",
        sourceId="rj",
        sql=sql,
        sqlHash=normalized_sql_hash(sql),
    )
    semantic = reporting_contract.MeasureSemantic(
        fieldRef="rj.rj.dwd_hdc_income_summary_view.indicator_value",
        aggregation="sum",
    )

    projected = project_measure_semantics_to_query_outputs(query, (semantic,))

    assert projected == (
        {
            "fieldRef": "rj.rj.dwd_hdc_income_summary_view.indicator_value",
            "aggregation": "sum",
            "unit": None,
            "additiveAcross": [],
            "exclusiveScope": {},
            "reconcileWith": None,
            "tolerance": None,
            "datasetField": "measure_val",
        },
    )


@pytest.mark.anyio
async def test_planner_schema_validation_uses_agno_agent_retries(monkeypatch) -> None:
    attempts = 0
    request_profiles: list[ReportingThinkingProfile] = []

    async def fake_aresponse(request_model, *args, **kwargs):
        nonlocal attempts
        _ = args, kwargs
        attempts += 1
        request_profiles.append(reporting_thinking_profile_from_model(request_model))
        if attempts == 1:
            return ModelResponse(content="{}")
        return ModelResponse(
            content=(
                '{"tables":[{"sourceId":"rj","table":"rj.income",'
                '"role":"收入分析","periodColumn":"data_date",'
                '"periodGranularity":"date"}]}'
            )
        )

    monkeypatch.setattr(ProjectedOpenAIChat, "aresponse", fake_aresponse)
    planner = Agent(
        model=ReportingPhaseOpenAIChat(id="deepseek-v4-flash-0731", api_key="test"),
        retries=0,
    )
    stage = ReportWorkflowRuntime._planning_agent(
        planner,
        "report-data-understanding-planner",
        DataUnderstandingPlan,
        thinking_profile=ReportingThinkingProfile.off(),
        escalation_thinking_profile=ReportingThinkingProfile.on(
            reasoning_effort="high",
            thinking_budget=8192,
        ),
    )
    stage.delay_between_retries = 0

    output = await stage.arun("plan")

    assert attempts == 2
    assert request_profiles == [
        ReportingThinkingProfile.off(),
        ReportingThinkingProfile.on(reasoning_effort="high", thinking_budget=8192),
    ]
    assert isinstance(output.content, DataUnderstandingPlan)


def _duplicate_analysis_outline_payload() -> dict[str, Any]:
    """复现同一 analysisId 被多个动态章节引用的非法提纲候选。"""
    return {
        "reportType": "comprehensive",
        "title": "整体运营分析报告",
        "sections": [
            {
                "title": "收入与成本",
                "focus": ["比较收入与成本"],
                "analysisIds": ["analysis_001"],
            },
            {
                "title": "利润与效率",
                "focus": ["比较利润与效率"],
                "analysisIds": ["analysis_001"],
            },
        ],
        "assumptions": ["收入数据来自财务系统"],
    }


def _duplicate_title_outline_payload() -> dict[str, Any]:
    """复现两个动态章节使用相同展示标题的非法提纲候选。"""
    payload = _duplicate_analysis_outline_payload()
    payload["sections"][1]["title"] = payload["sections"][0]["title"]
    payload["sections"][1]["analysisIds"] = ["analysis_002"]
    return payload


def test_outline_validator_attaches_candidate_on_validation_error() -> None:
    """响应校验失败时把候选载荷附在异常上，供纠错循环用作 previousOutput 基线。"""
    planner = Agent(model=ReportingPhaseOpenAIChat(id="deepseek-v4-flash-0731", api_key="test"))
    stage = ReportWorkflowRuntime._planning_agent(
        planner,
        "report-outline-planner",
        ReportOutlineProposal,
        thinking_profile=ReportingThinkingProfile.off(),
    )
    validator = getattr(stage.model, "_report_response_validator")

    with pytest.raises(ValidationError) as raised:
        validator(json.dumps(_duplicate_title_outline_payload()))

    candidate = getattr(raised.value, "_report_candidate", None)
    assert isinstance(candidate, dict)
    assert candidate["reportType"] == "comprehensive"
    assert candidate["sections"][1]["analysisIds"] == ["analysis_002"]


def test_outline_candidate_falls_back_to_model_level_input() -> None:
    payload = _duplicate_analysis_outline_payload()
    with pytest.raises(ValidationError) as raised:
        ReportOutlineProposal.model_validate(payload)

    candidate = _outline_candidate(raised.value)

    assert candidate is not None
    assert candidate["reportType"] == "comprehensive"


def test_outline_validation_issues_report_duplicate_analysis_id() -> None:
    payload = _duplicate_analysis_outline_payload()
    with pytest.raises(ValidationError) as raised:
        ReportOutlineProposal.model_validate(payload)

    issues = _outline_validation_issues(raised.value)
    reasons = " ".join(issue["reason"] for issue in issues)

    assert "同一 analysisId 只能归属一个动态章节" in reasons
    assert any(issue["path"] == "sections" for issue in issues)


def _detailed_analysis_plan_payload() -> dict[str, Any]:
    return {
        "analyses": [
            {
                "analysisId": "analysis_001",
                "domain": "revenue",
                "managementQuestion": "收入趋势如何",
                "primaryMetricFamily": "收入",
                "datasetIds": ["dataset_1"],
                "fields": ["data_date"],
                "metrics": ["indicator_value"],
                "periods": ["2025-01"],
                "actions": ["描述收入趋势"],
                "evidenceSummary": "收入逐月上升",
                "suggestedSection": "经营结果",
                "completionConditions": ["完成趋势描述"],
            }
        ],
        "datasetIds": ["dataset_1"],
    }


def _valid_outline_proposal() -> ReportOutlineProposal:
    return ReportOutlineProposal.model_validate(
        {
            "reportType": "comprehensive",
            "title": "整体运营分析报告",
            "sections": [
                {
                    "title": "经营结果与资源效率",
                    "focus": ["比较经营结果与资源投入"],
                    "analysisIds": ["analysis_001"],
                }
            ],
            "assumptions": ["收入数据来自财务系统"],
        }
    )


def _outline_proposal_with_forbidden_assumption() -> ReportOutlineProposal:
    return _valid_outline_proposal().model_copy(
        update={"assumptions": ("次均费用按成本与工作量之比估算。",)}
    )


def _outline_planner_stage() -> Agent:
    return ReportWorkflowRuntime._planning_agent(
        Agent(model=ReportingPhaseOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")),
        "report-outline-planner",
        ReportOutlineProposal,
        thinking_profile=ReportingThinkingProfile.off(),
    )


@pytest.mark.anyio
async def test_generate_outline_retries_on_validation_error_instead_of_crashing() -> None:
    """planner 首次返回重复 analysisId 的非法提纲时，generate_outline 应回灌 correction
    并重试，而不是让整条 workflow 失败。"""
    planner_calls = 0
    stage = _outline_planner_stage()

    async def fake_run_planner(_agent, payload, _run_context, **_kwargs):
        nonlocal planner_calls
        planner_calls += 1
        if planner_calls == 1:
            # 模拟 Agno Agent 重试耗尽后由 _raise_recorded_agent_error 抛出的校验异常。
            validator = getattr(_agent.model, "_report_response_validator")
            validator(json.dumps(_duplicate_title_outline_payload()))
        assert isinstance(payload.get("correction"), dict)
        assert payload["correction"]["allowedPaths"] == ["sections"]
        feedback = payload["correction"]["validationFeedback"]
        assert feedback["code"] == "report_outline_invalid"
        return _valid_outline_proposal()

    envelope = reporting_contract.ReportRequestEnvelope.model_validate(
        {
            "reportGoal": "整体运营分析",
            "reportType": "comprehensive",
            "period": {"start": "2025-01-01", "end": "2025-12-31"},
            "sourceIds": ["source-1"],
        }
    )
    state: dict[str, Any] = {
        REPORT_WORKFLOW_INPUT_STATE_KEY: envelope.model_dump(mode="json", by_alias=True),
        REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY: _detailed_analysis_plan_payload(),
    }
    run_context = SimpleNamespace(session_state=state)
    step_input = SimpleNamespace(additional_data=None)
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._outline_agent = stage
    runtime._state = lambda _run_context: state
    runtime._envelope = lambda _run_context: envelope
    runtime._assert_state_safe = lambda _state: None
    runtime._run_planner = fake_run_planner

    output = await runtime.generate_outline(step_input, run_context)

    assert planner_calls == 2
    assert isinstance(output, StepOutput)
    outline = ReportOutline.model_validate(output.content)
    assert outline.sections[0].analysis_ids == ("analysis_001",)
    assert state[REPORT_OUTLINE_STATE_KEY]["sections"][0]["code"] == "section_001"


@pytest.mark.anyio
async def test_generate_outline_routes_assumption_failure_to_assumptions_only() -> None:
    planner_calls = 0
    stage = _outline_planner_stage()

    async def fake_run_planner(_agent, payload, _run_context, **_kwargs):
        nonlocal planner_calls
        planner_calls += 1
        if planner_calls == 1:
            return _outline_proposal_with_forbidden_assumption()
        correction = payload["correction"]
        assert correction["allowedPaths"] == ["assumptions"]
        assert correction["validationFeedback"]["issues"][0]["path"] == "assumptions"
        return _valid_outline_proposal()

    envelope = reporting_contract.ReportRequestEnvelope.model_validate(
        {
            "reportGoal": "整体运营分析",
            "reportType": "comprehensive",
            "period": {"start": "2025-01-01", "end": "2025-12-31"},
            "sourceIds": ["source-1"],
        }
    )
    state: dict[str, Any] = {
        REPORT_WORKFLOW_INPUT_STATE_KEY: envelope.model_dump(mode="json", by_alias=True),
        REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY: _detailed_analysis_plan_payload(),
    }
    run_context = SimpleNamespace(session_state=state)
    step_input = SimpleNamespace(additional_data=None)
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._outline_agent = stage
    runtime._state = lambda _run_context: state
    runtime._envelope = lambda _run_context: envelope
    runtime._assert_state_safe = lambda _state: None
    runtime._run_planner = fake_run_planner

    output = await runtime.generate_outline(step_input, run_context)

    assert planner_calls == 2
    assert ReportOutline.model_validate(output.content).assumptions == ("收入数据来自财务系统",)


@pytest.mark.anyio
async def test_generate_outline_fails_after_exhausting_correction_attempts() -> None:
    """连续五次校验失败时以 report_outline_invalid 失败关闭，而非抛出原始 ValidationError。"""
    planner_calls = 0
    stage = _outline_planner_stage()

    async def fake_run_planner(_agent, _payload, _run_context, **_kwargs):
        nonlocal planner_calls
        planner_calls += 1
        validator = getattr(_agent.model, "_report_response_validator")
        validator(json.dumps(_duplicate_title_outline_payload()))

    envelope = reporting_contract.ReportRequestEnvelope.model_validate(
        {
            "reportGoal": "整体运营分析",
            "reportType": "comprehensive",
            "period": {"start": "2025-01-01", "end": "2025-12-31"},
            "sourceIds": ["source-1"],
        }
    )
    state: dict[str, Any] = {
        REPORT_WORKFLOW_INPUT_STATE_KEY: envelope.model_dump(mode="json", by_alias=True),
        REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY: _detailed_analysis_plan_payload(),
    }
    run_context = SimpleNamespace(session_state=state)
    step_input = SimpleNamespace(additional_data=None)
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._outline_agent = stage
    runtime._state = lambda _run_context: state
    runtime._envelope = lambda _run_context: envelope
    runtime._assert_state_safe = lambda _state: None
    runtime._run_planner = fake_run_planner

    with pytest.raises(ReportingError) as raised:
        await runtime.generate_outline(step_input, run_context)

    assert raised.value.code == "report_outline_invalid"
    assert planner_calls == 5
