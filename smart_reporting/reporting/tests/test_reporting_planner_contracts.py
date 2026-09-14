from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import textwrap
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import anyio
import pytest
from agno.agent import Agent
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.session import AgentSession
from agno.workflow.step import StepOutput
from loguru import logger
from pydantic import ValidationError
from sqlglot import parse_one

from smart_reporting.context_management import (
    ProjectedOpenAIChat,
    TaskExecutionContextHardLimitError,
)
from smart_reporting.reporting import contract as reporting_contract
from smart_reporting.reporting.agent import (
    ReportingPhaseOpenAIChat,
    create_reporting_phase_agent,
)
from smart_reporting.reporting.contract import ReportPeriod
from smart_reporting.reporting.data_source import DataShape
from smart_reporting.reporting.data_sources import DatasetHandle
from smart_reporting.reporting.hospital_operation.detailed_analysis import (
    AnalysisFileIdentity,
    DatasetAnalysisContext,
    DetailedAnalysisPlan,
    FieldStatistic,
    ProfiledDataset,
)
from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
)
from smart_reporting.reporting.hospital_operation.outline import (
    ReportOutline,
    ReportOutlineProposal,
    freeze_outline,
)
from smart_reporting.reporting.instructions import (
    REPORT_ANALYSIS_ITEM_AGENT_INSTRUCTIONS,
    REPORT_SECTION_AGENT_INSTRUCTIONS,
    REPORT_VISUALIZATION_SECTION_AGENT_INSTRUCTIONS,
)
from smart_reporting.reporting.model_policy import (
    ReportingThinkingProfile,
    ThinkingPolicyConfig,
    ThinkingRequest,
    apply_reporting_thinking_profile,
    bind_reporting_thinking,
    current_reporting_thinking_decision,
    reporting_thinking_profile_from_model,
    select_reporting_thinking,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.phase import (
    REPORTING_MODEL_ID_DEPENDENCY_KEY,
    REPORTING_MODEL_TIER_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
)
from smart_reporting.reporting.structured_output import ReportingStructuredOutputExecutor
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
from smart_reporting.reporting.workflow.runtime import sections as reporting_sections
from smart_reporting.reporting.workflow.runtime.analysis import (
    _analysis_item_complexity,
    _analysis_item_dataset_inputs,
    _analysis_item_output_root,
    _analysis_item_thinking_policy,
    _analysis_summary_input_token_budget,
    _model_facing_deterministic_facts,
    _prepare_analysis_summary_request,
    _reporting_detailed_analysis_plan,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisEvidenceDecision,
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
    _normalize_analysis_bundle_table_refs,
)
from smart_reporting.reporting.workflow.runtime.phase_models import SectionBlockContent
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
from smart_reporting.runtime.settings import AgentSettings


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
    agent = SimpleNamespace(id="report-test-planner")
    agent._reporting_thinking = ThinkingPolicyConfig(
        operation="data_understanding",
        thinking_enabled=True,
        configured_budget_cap=8192,
    )

    with pytest.raises(ReportingError) as raised:
        await runtime._run_planner(
            agent,
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


def test_analysis_item_schema_distinguishes_required_description_and_question() -> None:
    bundle_schema = AnalysisBundle.model_json_schema()
    item_schema = bundle_schema["$defs"]["AnalysisItem"]

    assert "根对象" in bundle_schema["description"]
    assert "完整分析项对象" in bundle_schema["properties"]["analyses"]["description"]
    assert "完整取数需求对象" in bundle_schema["properties"]["requirements"]["description"]
    assert "description" in item_schema["required"]
    assert "managementQuestion" in item_schema["required"]
    assert "分析动作" in item_schema["properties"]["description"]["description"]
    assert "不得替代" in item_schema["properties"]["description"]["description"]
    assert "单一业务问题" in item_schema["properties"]["managementQuestion"]["description"]
    assert "不得替代" in item_schema["properties"]["managementQuestion"]["description"]


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


@pytest.mark.parametrize(
    "description",
    [
        "基于可用期间描述实际值，不做全年外推。",
        "汇总收入、成本和利润，不做后续外推。",
        "仅披露原始值，不得估算、年化或补齐数据。",
    ],
)
def test_analysis_bundle_allows_explicitly_negated_derivations(description: str) -> None:
    payload = analysis_bundle(
        table="rj.dwd_hdc_income_summary_view", period_granularity="date"
    ).model_dump(mode="json", by_alias=True)
    payload["analyses"][0]["description"] = description

    bundle = AnalysisBundle.model_validate(payload)

    assert bundle.analyses[0].description == description


@pytest.mark.parametrize(
    "description",
    [
        "基于可用期间估算全年收入。",
        "不做外推，但仍估算全年收入。",
        "禁止外推，然而继续平滑缺失期间。",
        "不得外推并继续估算全年收入。",
    ],
)
def test_analysis_bundle_soft_warns_positive_derivations(description: str) -> None:
    payload = analysis_bundle(
        table="rj.dwd_hdc_income_summary_view", period_granularity="date"
    ).model_dump(mode="json", by_alias=True)
    payload["analyses"][0]["description"] = description

    records: list[str] = []
    sink_id = logger.add(records.append, level="WARNING", format="{message}")
    try:
        bundle = AnalysisBundle.model_validate(payload)
    finally:
        logger.remove(sink_id)

    assert bundle.analyses[0].description == description
    assert records == ["report_analysis_forbidden_derivation_mentioned\n"]
    assert description not in "".join(records)


def test_normalize_analysis_bundle_collapses_qualified_column_refs() -> None:
    candidate = {
        "analyses": [
            {
                "code": "income_trend",
                "description": "分析收入趋势",
                "managementQuestion": "收入趋势是否变化？",
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
                        "table": "rj.rj.dwd_income_budget_view",
                        "periodColumn": "rj.rj.dwd_income_budget_view.data_date",
                        "periodGranularity": "date",
                        "measureColumns": [
                            "rj.rj.dwd_income_budget_view.actual_test_income",
                        ],
                    }
                ],
                "dimensionColumns": ["rj.rj.dwd_income_budget_view.budget_type"],
                "grainColumns": ["rj.rj.dwd_income_budget_view.budget_type"],
                "relations": [],
            },
            {
                "requirementId": "req_join",
                "sourceId": "rj",
                "tables": [
                    {
                        "table": "rj.rj.dwd_income_view",
                        "periodColumn": "data_date",
                        "periodGranularity": "month",
                        "measureColumns": ["rj.rj.dwd_income_view.income"],
                    },
                    {
                        "table": "rj.rj.dwd_dept_view",
                        "periodColumn": "data_date",
                        "periodGranularity": "month",
                        "measureColumns": ["rj.rj.dwd_dept_view.headcount"],
                    },
                ],
                "dimensionColumns": ["dept_code"],
                "grainColumns": ["dept_code"],
                "relations": [
                    {
                        "leftTable": "rj.rj.dwd_income_view",
                        "rightTable": "rj.rj.dwd_dept_view",
                        "joinColumns": ["rj.rj.dwd_income_view.dept_code"],
                    }
                ],
            },
        ],
    }
    original_measure = candidate["requirements"][0]["tables"][0]["measureColumns"]

    normalized = _normalize_analysis_bundle_table_refs(candidate)
    bundle = AnalysisBundle.model_validate(normalized)

    requirement = bundle.requirements[0]
    assert requirement.tables[0].table == "rj.dwd_income_budget_view"
    assert requirement.tables[0].measure_columns == ("actual_test_income",)
    assert requirement.tables[0].period_column == "data_date"
    assert requirement.dimension_columns == ("budget_type",)
    assert requirement.grain_columns == ("budget_type",)

    joined = bundle.requirements[1]
    assert [item.table for item in joined.tables] == [
        "rj.dwd_income_view",
        "rj.dwd_dept_view",
    ]
    assert joined.tables[0].measure_columns == ("income",)
    assert joined.relations[0].join_columns == ("dept_code",)
    assert joined.dimension_columns == ("dept_code",)

    assert candidate["requirements"][0]["tables"][0]["measureColumns"] == original_measure
    assert candidate["requirements"][0]["tables"][0]["periodColumn"] == (
        "rj.rj.dwd_income_budget_view.data_date"
    )
    assert candidate["requirements"][1]["relations"][0]["joinColumns"] == [
        "rj.rj.dwd_income_view.dept_code"
    ]


@pytest.mark.parametrize(
    "table, qualifier",
    [
        ("rj.dwd_income_budget_view", "dwd_income_budget_view"),
        ("rj.rj.dwd_income_budget_view", "dwd_income_budget_view"),
        ("rj.dwd_income_budget_view", "DWD_INCOME_BUDGET_VIEW"),
        ("RJ.DWD_INCOME_BUDGET_VIEW", "rj.dwd_income_budget_view"),
        ("rj.RJ.DWD_INCOME_BUDGET_VIEW", "rj.rj.dwd_income_budget_view"),
        ("rj.dwd_income_budget_view", "rj.RJ.DWD_INCOME_BUDGET_VIEW"),
    ],
)
def test_normalize_analysis_bundle_accepts_table_qualified_columns(
    table: str, qualifier: str
) -> None:
    candidate = analysis_bundle(
        table="rj.dwd_income_budget_view", period_granularity="date"
    ).model_dump(mode="json", by_alias=True)
    requirement = candidate["requirements"][0]
    requirement["tables"][0].update(
        table=table,
        measureColumns=[f"{qualifier}.actual_medical_income"],
    )
    requirement["dimensionColumns"] = [f"{qualifier}.area"]
    requirement["grainColumns"] = [f"{qualifier}.area"]

    bundle = AnalysisBundle.model_validate(_normalize_analysis_bundle_table_refs(candidate))

    assert bundle.requirements[0].tables[0].measure_columns == ("actual_medical_income",)
    assert bundle.requirements[0].dimension_columns == ("area",)
    assert bundle.requirements[0].grain_columns == ("area",)
    assert requirement["dimensionColumns"] == [f"{qualifier}.area"]


def test_normalize_analysis_bundle_accepts_dotted_source_id() -> None:
    candidate = analysis_bundle(
        table="rj.dwd_income_budget_view", period_granularity="date"
    ).model_dump(mode="json", by_alias=True)
    requirement = candidate["requirements"][0]
    requirement["sourceId"] = "prod.rj"
    requirement["tables"][0].update(
        table="prod.rj.rj.dwd_income_budget_view",
        periodColumn="prod.rj.rj.dwd_income_budget_view.data_date",
        measureColumns=["prod.rj.rj.dwd_income_budget_view.actual_medical_income"],
    )
    requirement["dimensionColumns"] = ["prod.rj.rj.dwd_income_budget_view.area"]
    requirement["grainColumns"] = ["prod.rj.rj.dwd_income_budget_view.area"]

    bundle = AnalysisBundle.model_validate(_normalize_analysis_bundle_table_refs(candidate))

    normalized = bundle.requirements[0]
    assert normalized.source_id == "prod.rj"
    assert normalized.tables[0].table == "rj.dwd_income_budget_view"
    assert normalized.tables[0].period_column == "data_date"
    assert normalized.tables[0].measure_columns == ("actual_medical_income",)
    assert normalized.dimension_columns == ("area",)
    assert normalized.grain_columns == ("area",)


def test_normalize_analysis_bundle_rejects_qualified_dimension_for_multiple_tables() -> None:
    candidate = {
        "analyses": [
            {
                "code": "joined_analysis",
                "description": "分析跨表指标",
                "managementQuestion": "跨表指标如何变化？",
                "primaryMetricFamily": "income",
                "requirementIds": ["req_join"],
            }
        ],
        "requirements": [
            {
                "requirementId": "req_join",
                "sourceId": "rj",
                "tables": [
                    {
                        "table": "rj.left_fact",
                        "periodColumn": "data_date",
                        "periodGranularity": "date",
                        "measureColumns": ["income"],
                    },
                    {
                        "table": "rj.right_dim",
                        "periodColumn": "data_date",
                        "periodGranularity": "date",
                        "measureColumns": ["headcount"],
                    },
                ],
                "dimensionColumns": ["left_fact.right_only_dimension", "dept_code"],
                "grainColumns": ["dept_code"],
                "relations": [
                    {
                        "leftTable": "rj.left_fact",
                        "rightTable": "rj.right_dim",
                        "joinColumns": ["dept_code"],
                    }
                ],
            }
        ],
    }

    with pytest.raises(ValidationError, match="dimensionColumns"):
        AnalysisBundle.model_validate(_normalize_analysis_bundle_table_refs(candidate))


@pytest.mark.parametrize(
    "qualified_measure",
    [
        "other_source.rj.dwd_hdc_income_summary_view.indicator_value",
        "rj.rj.other_income_view.indicator_value",
        "other_income_view.indicator_value",
        "other_database.dwd_hdc_income_summary_view.indicator_value",
        "RJ.rj.dwd_hdc_income_summary_view.indicator_value",
    ],
)
def test_normalize_analysis_bundle_preserves_measure_qualified_to_other_table(
    qualified_measure: str,
) -> None:
    candidate = analysis_bundle(
        table="rj.dwd_hdc_income_summary_view",
        period_granularity="date",
    ).model_dump(mode="json", by_alias=True)
    candidate["requirements"][0]["tables"][0]["measureColumns"] = [qualified_measure]

    normalized = _normalize_analysis_bundle_table_refs(candidate)

    assert normalized["requirements"][0]["tables"][0]["measureColumns"] == [qualified_measure]
    with pytest.raises(ValidationError, match="measureColumns"):
        AnalysisBundle.model_validate(normalized)


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


def test_outline_proposal_rejects_legacy_focus_field() -> None:
    with pytest.raises(ValidationError):
        ReportOutlineProposal.model_validate(
            {
                "reportType": "comprehensive",
                "title": "年度运营分析报告",
                "sections": [
                    {
                        "title": "经营结果与资源效率",
                        "focus": ["比较经营结果与资源投入"],
                        "analysisIds": ["analysis_001"],
                    }
                ],
            }
        )


def test_outline_schema_exposes_analysis_id_pattern() -> None:
    schema = ReportOutlineProposal.model_json_schema()

    analysis_id_items = schema["$defs"]["OutlineSectionProposal"]["properties"]["analysisIds"][
        "items"
    ]

    assert analysis_id_items["pattern"] == "^analysis_[0-9]{3,6}$"


def test_freeze_outline_derives_focus_from_signed_management_questions() -> None:
    outline = freeze_outline(
        {
            "reportType": "comprehensive",
            "title": "年度运营分析报告",
            "sections": [
                {
                    "title": "经营结果与资源效率",
                    "analysisIds": ["analysis_002", "analysis_001"],
                }
            ],
        },
        analyses=[
            {"analysisId": "analysis_001", "managementQuestion": "收入趋势如何"},
            {"analysisId": "analysis_002", "managementQuestion": "成本效率如何"},
        ],
    )

    assert outline.sections[0].focus == ("成本效率如何", "收入趋势如何")


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


def test_analysis_item_instructions_delegate_execution_to_fixed_workflow() -> None:
    instructions = "\n".join(REPORT_ANALYSIS_ITEM_AGENT_INSTRUCTIONS)

    assert "AnalysisEvidenceDecision" in instructions
    assert "固定 Workflow" in instructions
    assert "Python 源码" in instructions
    assert "expected_sha256" not in instructions


def test_section_instructions_match_evidence_file_authorization() -> None:
    instructions = "\n".join(REPORT_SECTION_AGENT_INSTRUCTIONS)

    assert "factSummaries" in instructions
    assert "evidenceFiles" in instructions
    assert "factFiles 仅用于事实身份和追溯元数据" in instructions
    assert "只按 factFiles 定点读取" not in instructions
    assert "补读原始 facts/evidence" not in instructions


def test_section_block_stage_instructions_keep_heading_metadata_out_of_markdown() -> None:
    stage = reporting_sections._section_stage_agent(
        Agent(model=ReportingPhaseOpenAIChat(id="test", api_key="test")),
        SectionBlockContent,
        "block-0",
    )
    instructions = "\n".join(stage.instructions)

    assert "标题行后必须立即换行" in instructions
    assert "citationIds、chartIds" in instructions
    assert "<sup>" in instructions
    assert "report_draft_heading_title_too_long" in instructions


@pytest.mark.anyio
async def test_profile_job_runs_in_current_process_worker_thread() -> None:
    caller_pid = os.getpid()
    caller_thread_id = threading.get_ident()

    worker_pid, worker_thread_id = await reporting_datasets._run_profile_job(
        lambda: (os.getpid(), threading.get_ident()),
        anyio.CapacityLimiter(1),
    )

    assert worker_pid == caller_pid
    assert worker_thread_id != caller_thread_id


@pytest.mark.anyio
async def test_profile_job_enforces_wall_clock_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    monkeypatch.setattr(reporting_datasets, "PROFILE_GENERATION_TIMEOUT_SECONDS", 0.01)

    try:
        with pytest.raises(ReportingError) as raised:
            await reporting_datasets._run_profile_job(
                release.wait,
                anyio.CapacityLimiter(1),
            )
    finally:
        release.set()

    assert raised.value.code == "report_analysis_profile_timeout"


@pytest.mark.anyio
async def test_prepare_analysis_context_enforces_profile_upload_total_timeout(
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
            self.upload_timeouts: list[float] = []

        async def upload_file(self, content: bytes, path: str, timeout: int = 30 * 60) -> None:
            self.upload_timeouts.append(timeout)
            await anyio.sleep_forever()

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
    monkeypatch.setattr(reporting_datasets, "PROFILE_TRANSFER_TIMEOUT_SECONDS", 0.01)
    state: dict[str, Any] = {REPORT_WORKFLOW_RESULT_STATE_KEY: {"datasets": [handle.public_dict()]}}
    runtime: Any = object.__new__(RuntimeDatasetsMixin)
    runtime.workspace_service = FakeWorkspaceService()
    runtime._state = lambda _run_context: state
    runtime._workflow_result = lambda _state: dict(state[REPORT_WORKFLOW_RESULT_STATE_KEY])
    runtime._scope = lambda _run_context: {"threadId": "thread-1"}
    runtime._snapshots = lambda _run_context: ()
    runtime._envelope = lambda _run_context: SimpleNamespace(report_goal="月度趋势")
    runtime._assert_state_safe = lambda _state: None

    with pytest.raises(ReportingError, match="CSV 数据集画像生成失败"):
        await runtime.prepare_analysis_context(
            SimpleNamespace(),
            SimpleNamespace(run_id="run-1"),
        )

    assert filesystem.upload_timeouts == [0.01]


def test_phase_instructions_prioritize_signed_execution_directive() -> None:
    analysis = "\n".join(REPORT_ANALYSIS_ITEM_AGENT_INSTRUCTIONS)
    visualization = "\n".join(REPORT_VISUALIZATION_SECTION_AGENT_INSTRUCTIONS)
    section = "\n".join(REPORT_SECTION_AGENT_INSTRUCTIONS)

    assert "固定 Workflow" in analysis
    assert "固定 Workflow" in visualization
    assert "executionDirective 是本任务的首要动作契约" in section
    assert "不得使用 read_file 读取 factFiles" in section


def test_phase_instructions_do_not_expose_patch_hash_protocol() -> None:
    analysis_instructions = "\n".join(REPORT_ANALYSIS_ITEM_AGENT_INSTRUCTIONS)
    visualization_instructions = "\n".join(REPORT_VISUALIZATION_SECTION_AGENT_INSTRUCTIONS)

    for instructions in (analysis_instructions, visualization_instructions):
        assert "expected_sha256" not in instructions


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("requested_domain", "expected_domain"),
    (("income", "income"), ("full_cost", "full_cost")),
)
async def test_detailed_analysis_plan_uses_semantic_domain_and_only_requires_csv_for_fact_gaps(
    requested_domain: str,
    expected_domain: str,
) -> None:
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
                "domain": requested_domain,
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
        domains=(requested_domain,), report_goal="分析医院经营主题"
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
    assert analysis.domain == expected_domain
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
        fieldStats=(
            FieldStatistic(
                name="income_type",
                inferredType="categorical",
                nonNullCount=1,
                missingCount=0,
                missingRate=0,
                distinctCount=1,
                cardinalityRate=1,
                unique=True,
            ),
            FieldStatistic(
                name="actual_income",
                inferredType="numeric",
                nonNullCount=1,
                missingCount=0,
                missingRate=0,
                distinctCount=1,
                cardinalityRate=1,
                unique=True,
            ),
        ),
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
            "field_stats": (
                context.field_stats[0].model_copy(update={"name": "budget_type"}),
                context.field_stats[1].model_copy(update={"name": "budget_income"}),
            ),
            "numeric_fields": ("budget_income",),
        }
    )

    inputs = _analysis_item_dataset_inputs((first, second), (context, budget_context))

    assert inputs[0]["columns"] == ["income_type", "actual_income"]
    assert inputs[1]["columns"] == ["budget_type", "budget_income"]
    assert inputs[0]["format"] == "csv"
    assert inputs[0]["hasHeader"] is True
    assert inputs[0]["columnTypes"] == {
        "income_type": "categorical",
        "actual_income": "numeric",
    }
    assert inputs[1]["columnTypes"] == {
        "budget_type": "categorical",
        "budget_income": "numeric",
    }


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
    standard = {**plan, "comparisonBasis": ["yoy"], "organizationGrain": ["area"]}
    complex_plan = {
        "metrics": ["income", "volume"],
        "datasetIds": ["ds-1", "ds-2"],
        "comparisonBasis": ["yoy"],
        "organizationGrain": ["area", "department"],
        "actions": ["compare", "attribute", "recommend"],
    }

    assert _analysis_item_thinking_policy(plan, retry=False, retry_reason=None) == (
        "high",
        1024,
        "simple",
    )
    assert _analysis_item_thinking_policy(plan, retry=False, retry_reason="schema_validation") == (
        "high",
        1024,
        "simple",
    )
    assert _analysis_item_thinking_policy(standard, retry=False, retry_reason=None) == (
        "high",
        2048,
        "standard",
    )
    assert _analysis_item_thinking_policy(complex_plan, retry=False, retry_reason=None) == (
        "high",
        4096,
        "complex",
    )
    assert _analysis_item_thinking_policy(plan, retry=True, retry_reason="evidence_incomplete") == (
        "max",
        6144,
        "simple",
    )
    assert _analysis_item_thinking_policy(plan, retry=True, retry_reason="semantic_warning") == (
        "high",
        1024,
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
async def test_analysis_script_and_structured_stages_use_layered_request_budgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_context = RunContext(
        run_id="task-run-1",
        session_id="task-session-1",
        dependencies={
            "AgentOS 任务执行": {
                "reportingThinkingEffort": "high",
                "reportingThinkingBudget": 2048,
            }
        },
    )
    observed: list[tuple[str, str | None, int]] = []
    planner_requests: list[dict[str, Any]] = []
    code_prompts: list[dict[str, Any]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = SimpleNamespace()
    runtime.task_runner = SimpleNamespace(repository=SimpleNamespace())
    runtime.state_repository = SimpleNamespace()
    runtime._analysis_evidence_agent = SimpleNamespace()
    runtime._analysis_summary_agent = SimpleNamespace()
    runtime._analysis_thinking_enabled = True
    runtime._analysis_thinking_budget_cap = 8192

    async def run_planner(_agent, payload, _parent_context, **kwargs):
        planner_requests.append(payload)
        operation = (
            "analysis_summary"
            if payload["analysisBlock"]["blockId"].endswith(":summary")
            else "analysis_evidence"
        )
        decision = select_reporting_thinking(
            ThinkingRequest(
                operation=operation,
                complexity=kwargs["thinking_complexity"],
                configured_budget_cap=8192,
            )
        )
        observed.append(
            (
                payload["analysisBlock"]["blockId"],
                decision.reasoning_effort,
                decision.thinking_budget,
            )
        )
        if payload["analysisBlock"]["blockId"].endswith(":summary"):
            return AnalysisSummaryDraft(summary="完成摘要", warnings=())
        return AnalysisEvidenceDecision(
            requiresSupplementalEvidence=True,
            reason="缺少构成",
            missingFacts=("构成",),
        )

    class CapturingCodeAgent:
        def __init__(self):
            self.tools = []
            self.tool_choice = None

        async def arun(self, prompt, **_kwargs):
            request = json.loads(prompt)
            tool = self.tools[0]
            if tool.name == "read_file":
                return await tool.entrypoint(path=request["scriptPath"])
            decision = current_reporting_thinking_decision()
            assert decision is not None
            facts = request["facts"]
            observed.append(
                (
                    (
                        "analysis_001:evidence:script:repair"
                        if "taskFacts" in facts
                        else "analysis_001:evidence:script:initial"
                    ),
                    decision.reasoning_effort,
                    decision.thinking_budget,
                )
            )
            code_prompts.append(request)
            source = repaired_content if "taskFacts" in facts else initial_content
            return await tool.entrypoint(source=source)

    runtime._analysis_script_agent = CapturingCodeAgent()

    class FakeAnalysisItemWorkflow:
        def __init__(
            self, *, decide_evidence, generate_script, repair_script, summarize, **_kwargs
        ):
            self.decide_evidence = decide_evidence
            self.generate_script = generate_script
            self.repair_script = repair_script
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
            decision = await self.decide_evidence(planner_payload)
            script_path = planner_payload["scriptPath"]
            initial = await self.generate_script(
                script_path=script_path,
                task_facts={
                    **planner_payload,
                    "evidenceDecision": decision.model_dump(mode="json", by_alias=True),
                },
                diagnostic=None,
                run_context=task_context,
            )
            await self.repair_script(
                script_file=initial.script_file,
                diagnostic={
                    "code": "report_analysis_script_failed",
                    "message": "脚本执行失败。",
                },
                decision=decision,
                run_context=task_context,
            )
            await self.summarize({})
            return SimpleNamespace(output=StepOutput(content={"ok": True}))

    runtime._run_planner = run_planner
    script_path = "evidence/analysis_001/supplement.py"
    initial_content = "value = 1\nprint(value)\n"
    repaired_content = "value = 2\nprint(value)\n"

    def script_identity(content: str) -> dict[str, Any]:
        return {
            "path": script_path,
            "size": len(content.encode()),
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
        }

    toolkit = SimpleNamespace(
        read_file=AsyncMock(
            return_value={
                "ok": True,
                **script_identity(initial_content),
                "content": initial_content,
                "offset": 0,
                "nextOffset": len(initial_content.encode()),
                "totalBytes": len(initial_content.encode()),
            }
        ),
        apply_analysis_patch=AsyncMock(
            side_effect=[
                {"ok": True, "artifacts": [script_identity(initial_content)]},
                {"ok": True, "artifacts": [script_identity(repaired_content)]},
            ]
        ),
        run_python_script=AsyncMock(),
        complete_analysis_item=AsyncMock(),
        recover_signed_analysis_script=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "smart_reporting.reporting.workflow.runtime.analysis.build_reporting_tools",
        lambda *_args, **_kwargs: [toolkit],
    )
    monkeypatch.setattr(
        "smart_reporting.reporting.workflow.runtime.analysis.AnalysisItemWorkflow",
        FakeAnalysisItemWorkflow,
    )

    await runtime._execute_analysis_item_workflow(
        json.dumps(
            {
                "currentAnalysisId": "analysis_001",
                "currentAnalysis": {
                    "datasetIds": ["dataset_001"],
                    "metrics": ["income"],
                    "comparisonBasis": ["yoy"],
                    "organizationGrain": ["department"],
                },
            }
        ),
        task_context,
        parent_run_context=RunContext(
            run_id="report-run-1", session_id="report-session-1", session_state={}
        ),
    )

    assert observed == [
        ("analysis_001:evidence:decision", "high", 2048),
        ("analysis_001:evidence:script:initial", None, 0),
        ("analysis_001:evidence:script:repair", "high", 2048),
        ("analysis_001:summary", "high", 2048),
    ]
    assert set(planner_requests[0]) == {
        "currentAnalysis",
        "deterministicFacts",
        "analysisBlock",
    }
    assert len(planner_requests) == 2
    assert code_prompts[0]["facts"]["evidenceDecision"]["missingFacts"] == ["构成"]
    assert code_prompts[1]["scriptPath"] == script_path
    assert code_prompts[1]["facts"]["taskFacts"] == {
        "missingFacts": ["构成"],
        "outputContract": {
            "format": "json",
            "requiredRootKeys": ["findings", "reconciliations", "warnings"],
            "additionalRootKeys": False,
        },
    }
    assert code_prompts[1]["facts"]["diagnostic"] == {
        "code": "report_analysis_script_failed",
        "message": "脚本执行失败。",
    }
    assert task_context.dependencies["AgentOS 任务执行"] == {
        "reportingThinkingEffort": "high",
        "reportingThinkingBudget": 2048,
    }


def test_analysis_summary_request_projects_large_evidence_before_model_call() -> None:
    rows = [[f"group-{index:05d}", index if index % 2 == 0 else -index] for index in range(19_637)]
    payload = {
        "currentAnalysis": {"managementQuestion": "主要正负贡献是什么？"},
        "deterministicFacts": {"metrics": []},
        "supplementalEvidence": {
            "analysisId": "analysis_001",
            "datasetIds": ["dataset-1"],
            "findings": [
                {
                    "name": "高基数交叉贡献",
                    "columns": ["group", "change"],
                    "rows": rows,
                }
            ],
            "reconciliations": [{"name": "差额守恒", "passed": True}],
            "warnings": [],
        },
        "supplementalEvidenceSource": {
            "path": "evidence/analysis_001/supplement.json",
            "size": 1_900_000,
            "sha256": "b" * 64,
        },
    }
    calls: list[tuple[str, list[Any], Any]] = []

    class CountingModel:
        id = "base-model"
        max_tokens = None

        def count_tokens(self, messages, tools=None, output_schema=None):
            del tools
            calls.append((self.id, messages, output_schema))
            return sum(len(str(message.content).encode("utf-8")) for message in messages)

    agent = SimpleNamespace(
        model=CountingModel(),
        get_system_message=lambda **_kwargs: Message(role="system", content="system-contract"),
    )
    run_context = RunContext(
        run_id="report-run-1",
        session_id="report-session-1",
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_MODEL_TIER_DEPENDENCY_KEY: "standard",
                REPORTING_MODEL_ID_DEPENDENCY_KEY: "deepseek-v4-0731",
            }
        },
    )

    request = _prepare_analysis_summary_request(
        payload,
        analysis_id="analysis_001",
        agent=agent,
        run_context=run_context,
    )

    finding = request["supplementalEvidence"]["findings"][0]
    assert request["analysisBlock"] == {"blockId": "analysis_001:summary"}
    assert len(finding["rows"]) < len(rows)
    assert finding["view"]["rowCount"] == len(rows)
    assert request["supplementalEvidence"]["sourceFile"] == payload["supplementalEvidenceSource"]
    assert calls[-1][0] == "deepseek-v4-0731"
    assert calls[-1][2] is AnalysisSummaryDraft
    assert [message.role for message in calls[-1][1]] == ["system", "user"]
    assert calls[-1][1][-1].content == json.dumps(
        request, ensure_ascii=False, separators=(",", ":"), default=str
    )
    assert sum(len(str(message.content).encode("utf-8")) for message in calls[-1][1]) <= (
        _analysis_summary_input_token_budget(agent, run_context)
    )


def test_analysis_summary_instructions_define_projected_evidence_semantics() -> None:
    source = inspect.getsource(reporting_runtime_base._ReportWorkflowRuntimeBase.__init__)

    assert "view.truncated 为 true 时 rows 只是投影视图" in source
    assert "omittedNumericSums 只汇总未进入 rows 的有限数值" in source
    assert "完整总量等于 rows 数值与 omittedNumericSums 之和" in source


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
            "correlations": {
                "dataset-1:income~count": 0.82,
                "dataset-1:income~other": 0.41,
            },
        }
    )

    projected = _model_facing_deterministic_facts(bundle)

    assert all(
        "datasetSha256" not in item and "profileHash" not in item for item in projected["metrics"]
    )
    assert projected["metrics"][0]["warnings"] == ["期间不完整"]
    assert projected["metrics"][1]["warnings"] == ["字段缺失"]
    assert projected["warnings"] == ["全局告警"]
    assert projected["correlations"] == {
        "datasets": ["dataset-1"],
        "columns": ["dataset", "left", "right", "value"],
        "rows": [[0, "income", "count", 0.82], [0, "income", "other", 0.41]],
    }
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

    assert "VisualizationPlanDraft" in instructions
    assert "Python 源码" in instructions
    assert "执行、检查和提交均由固定 Workflow 编排" in instructions


def test_visualization_instructions_describe_overridable_noto_cjk_default() -> None:
    instructions = "\n".join(REPORT_VISUALIZATION_SECTION_AGENT_INSTRUCTIONS)

    assert "read_file" not in instructions
    assert "run_python_script" not in instructions
    assert "submit_visualization_charts" not in instructions
    assert "fallback_to_default=False" not in instructions


def test_planner_validation_is_exposed_to_structured_executor() -> None:
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
        thinking_policy=ThinkingPolicyConfig(
            operation="data_understanding",
            thinking_enabled=True,
            configured_budget_cap=8192,
        ),
    )

    assert stage.retries == 0
    assert stage.exponential_backoff is False
    assert stage.telemetry is False
    assert stage.model.retries == 0
    assert stage.model.extra_body == {"enable_thinking": False}
    assert stage.model.reasoning_effort is None
    validator = getattr(stage.model, "_report_response_validator")
    with pytest.raises(ValidationError):
        validator("{}")


def test_reporting_phase_agent_injects_current_shanghai_date_into_planner_context() -> None:
    template = create_reporting_phase_agent(
        AgentSettings.from_environment({}, load_env_file=False),
        object(),
        object(),
        object(),
        state_repository=object(),
    )

    stage = ReportWorkflowRuntime._planning_agent(
        template,
        "report-data-understanding-planner",
        DataUnderstandingPlan,
        thinking_policy=ThinkingPolicyConfig(
            operation="data_understanding",
            thinking_enabled=True,
            configured_budget_cap=8192,
        ),
    )
    dates = {datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()}
    system_message = stage.get_system_message(AgentSession(session_id="test-current-date"))
    dates.add(datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())

    assert stage.add_datetime_to_context is True
    assert stage.timezone_identifier == "Asia/Shanghai"
    assert stage.datetime_format == "%Y-%m-%d"
    assert system_message is not None
    assert any(f"The current time is {current_date}." in system_message.content for current_date in dates)


def test_runtime_planners_use_operation_thinking_policies() -> None:
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
    assert runtime._analysis_script_agent.output_schema is None
    assert runtime._analysis_script_agent.tools == []
    assert runtime._analysis_script_agent.add_history_to_context is False
    assert runtime._analysis_script_agent.reasoning_model is not None
    assert runtime._analysis_script_agent.reasoning_agent is not None
    assert any(
        "只含 findings、reconciliations、warnings" in instruction
        and "不得输出 analysisId 或 datasetIds" in instruction
        for instruction in runtime._analysis_script_agent.instructions
    )
    assert all(
        "32000" not in instruction and "240 行" not in instruction
        for instruction in runtime._analysis_script_agent.instructions
    )
    analysis_instructions = "\n".join(runtime._analysis_agent.instructions)
    assert "根 JSON 必须是对象且只能包含 analyses 和 requirements" in analysis_instructions
    assert "不得返回单个 analysis、单个 requirement、裸数组或占位值" in analysis_instructions
    assert "同时显式输出 description 和 managementQuestion" in analysis_instructions
    assert "即使内容相近也不得省略" in analysis_instructions
    request_instructions = "\n".join(runtime._request_normalizer.instructions)
    assert "相对日期必须以系统上下文中的当前日期为基准" in request_instructions
    assert "“去年”表示当前年份减一对应的完整日历年" in request_instructions
    expected_policies = (
        (runtime._request_normalizer, "request_normalization"),
        (runtime._data_understanding_agent, "data_understanding"),
        (runtime._measure_semantic_agent, "measure_semantics"),
        (runtime._outline_agent, "outline_planning"),
        (runtime._analysis_agent, "analysis_planning"),
        (runtime._analysis_evidence_agent, "analysis_evidence"),
        (runtime._analysis_summary_agent, "analysis_summary"),
        (runtime._sql_agent, "sql_planning"),
    )
    for stage, operation in expected_policies:
        assert getattr(stage, "_reporting_thinking") == ThinkingPolicyConfig(
            operation=operation,
            thinking_enabled=True,
            configured_budget_cap=8192,
        )
        assert not hasattr(stage.model, "_report_escalation_thinking_profile")
        assert not hasattr(stage.model, "_report_thinking_escalation_fields")


def test_runtime_planner_policies_honor_disabled_thinking() -> None:
    runtime = ReportWorkflowRuntime(
        db=SimpleNamespace(),
        reporting_agent_template=Agent(
            model=ReportingPhaseOpenAIChat(
                id="deepseek-v4-flash-0731",
                api_key="test",
                reasoning_effort="high",
                extra_body={"enable_thinking": True, "thinking_budget": 8192},
            )
        ),
        task_runner=SimpleNamespace(),
        workspace_service=SimpleNamespace(),
        registry=SimpleNamespace(),
        profiles=SimpleNamespace(),
        planner_enable_thinking=False,
        planner_thinking_budget=8192,
        state_repository=SimpleNamespace(),
    )

    stages = (
        runtime._request_normalizer,
        runtime._data_understanding_agent,
        runtime._measure_semantic_agent,
        runtime._outline_agent,
        runtime._analysis_agent,
        runtime._analysis_evidence_agent,
        runtime._analysis_summary_agent,
        runtime._sql_agent,
    )
    for stage in stages:
        policy = getattr(stage, "_reporting_thinking")
        assert select_reporting_thinking(
            ThinkingRequest(
                operation=policy.operation,
                complexity="complex",
                attempt=1,
                failure_kind="schema_failure",
                configured_budget_cap=policy.configured_budget_cap,
                thinking_enabled=policy.thinking_enabled,
            )
        ).thinking_budget == 0
    assert runtime._analysis_script_agent.reasoning_model is None
    assert runtime._analysis_script_agent.reasoning_agent is None


@pytest.mark.parametrize(
    ("operation", "failure_kind", "expected_budgets"),
    [
        ("data_understanding", "capability_mapping_failure", [2048, 4096]),
        ("sql_planning", "sql_validation_failure", [2048, 4096]),
    ],
)
@pytest.mark.anyio
async def test_run_planner_passes_layered_thinking_request(
    monkeypatch,
    operation: str,
    failure_kind: str,
    expected_budgets: list[int],
) -> None:
    observed = []
    content = DataUnderstandingPlan.model_construct()

    class RecordingExecutor:
        def __init__(self, _agent) -> None:
            pass

        async def execute(self, *_args, **kwargs):
            request = kwargs["thinking_request"]
            observed.append(request)
            return SimpleNamespace(content=content, run_output=SimpleNamespace(metrics=None))

    monkeypatch.setattr(reporting_runtime_base, "ReportingStructuredOutputExecutor", RecordingExecutor)
    agent = Agent(
        id=f"report-{operation}-planner",
        model=ReportingPhaseOpenAIChat(id="deepseek-v4-flash-0731", api_key="test"),
        output_schema=DataUnderstandingPlan,
    )
    setattr(
        agent,
        "_reporting_thinking",
        ThinkingPolicyConfig(
            operation=operation,
            thinking_enabled=True,
            configured_budget_cap=8192,
        ),
    )
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._scope = lambda _run_context: {"userId": "user-1"}
    run_context = SimpleNamespace(run_id="run-1")

    await runtime._run_planner(agent, {}, run_context)
    await runtime._run_planner(
        agent,
        {"correction": {}},
        run_context,
        attempt=1,
        failure_kind=failure_kind,
    )

    assert [select_reporting_thinking(request).thinking_budget for request in observed] == expected_budgets


@pytest.mark.anyio
async def test_run_planner_honors_disabled_thinking_policy(monkeypatch) -> None:
    observed = []
    content = DataUnderstandingPlan.model_construct()

    class RecordingExecutor:
        def __init__(self, _agent) -> None:
            pass

        async def execute(self, *_args, **kwargs):
            observed.append(kwargs["thinking_request"])
            return SimpleNamespace(content=content, run_output=SimpleNamespace(metrics=None))

    monkeypatch.setattr(reporting_runtime_base, "ReportingStructuredOutputExecutor", RecordingExecutor)
    agent = Agent(
        id="report-data-understanding-planner",
        model=ReportingPhaseOpenAIChat(id="deepseek-v4-flash-0731", api_key="test"),
        output_schema=DataUnderstandingPlan,
    )
    setattr(
        agent,
        "_reporting_thinking",
        ThinkingPolicyConfig(
            operation="data_understanding",
            thinking_enabled=False,
            configured_budget_cap=8192,
        ),
    )
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._scope = lambda _run_context: {"userId": "user-1"}

    await runtime._run_planner(agent, {}, SimpleNamespace(run_id="run-1"))

    assert select_reporting_thinking(observed[0]).thinking_budget == 0


def test_runtime_planners_project_request_decision_to_vllm_chat_template() -> None:
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

    decision = select_reporting_thinking(
        ThinkingRequest(operation="analysis_planning", configured_budget_cap=8192)
    )
    with bind_reporting_thinking(decision):
        request_model = runtime._analysis_agent.model._phase_request_model([])
    request_params = request_model.get_request_params()

    assert "reasoning_effort" not in request_params
    assert request_params["extra_body"] == {
        "enable_thinking": True,
        "thinking_budget": 2048,
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
        thinking_policy=ThinkingPolicyConfig(
            operation="analysis_planning",
            thinking_enabled=True,
            configured_budget_cap=8192,
        ),
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
        thinking_policy=ThinkingPolicyConfig(
            operation="analysis_planning",
            thinking_enabled=True,
            configured_budget_cap=8192,
        ),
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
        thinking_policy=ThinkingPolicyConfig(
            operation="analysis_planning",
            thinking_enabled=True,
            configured_budget_cap=8192,
        ),
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
        thinking_policy=ThinkingPolicyConfig(
            operation="analysis_planning",
            thinking_enabled=True,
            configured_budget_cap=8192,
        ),
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
        thinking_policy=ThinkingPolicyConfig(
            operation="analysis_planning",
            thinking_enabled=True,
            configured_budget_cap=8192,
        ),
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
async def test_structured_executor_retries_planner_schema_with_layered_budget(monkeypatch) -> None:
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
        thinking_policy=ThinkingPolicyConfig(
            operation="data_understanding",
            thinking_enabled=True,
            configured_budget_cap=8192,
        ),
    )
    output = await ReportingStructuredOutputExecutor(stage, idle_timeout_seconds=5).execute(
        "plan",
        routing_context=None,
        session_id="planner-schema-thinking",
        user_id="user-1",
        thinking_request=ThinkingRequest(
            operation="data_understanding",
            configured_budget_cap=8192,
        ),
    )

    assert attempts == 2
    assert request_profiles == [
        ReportingThinkingProfile.on(reasoning_effort="high", thinking_budget=2048),
        ReportingThinkingProfile.on(reasoning_effort="high", thinking_budget=4096),
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
                "analysisIds": ["analysis_001"],
            },
            {
                "title": "利润与效率",
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
        thinking_policy=ThinkingPolicyConfig(
            operation="outline_planning",
            thinking_enabled=True,
            configured_budget_cap=8192,
        ),
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
        thinking_policy=ThinkingPolicyConfig(
            operation="outline_planning",
            thinking_enabled=True,
            configured_budget_cap=8192,
        ),
    )


@pytest.mark.anyio
async def test_generate_outline_logs_compact_frozen_section_plan_once() -> None:
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
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._outline_agent = _outline_planner_stage()
    runtime._state = lambda _run_context: state
    runtime._envelope = lambda _run_context: envelope
    runtime._assert_state_safe = lambda _state: None
    runtime._run_planner = AsyncMock(return_value=_valid_outline_proposal())
    records: list[str] = []
    sink_id = logger.add(records.append, level="INFO", format="{message}")
    try:
        await runtime.generate_outline(
            SimpleNamespace(additional_data=None), SimpleNamespace(session_state=state)
        )
    finally:
        logger.remove(sink_id)

    planned = [line for line in "".join(records).splitlines() if line.startswith("report_outline_")]
    assert planned == [
        'report_outline_planned outline={"reportTitle":"整体运营分析报告","sectionCount":1,'
        '"sections":[{"sectionNumber":"1","sectionCode":"section_001",'
        '"title":"经营结果与资源效率","analysisCount":1}]}'
    ]


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
async def test_generate_outline_repairs_missing_analysis_reference_in_same_run() -> None:
    planner_calls = 0
    stage = _outline_planner_stage()
    incomplete = _valid_outline_proposal()
    complete = incomplete.model_copy(
        update={
            "sections": (
                incomplete.sections[0].model_copy(
                    update={"analysis_ids": ("analysis_001", "analysis_002")}
                ),
            )
        }
    )

    async def fake_run_planner(_agent, payload, _run_context, **_kwargs):
        nonlocal planner_calls
        planner_calls += 1
        if planner_calls == 1:
            return incomplete
        correction = payload["correction"]
        assert correction["allowedPaths"] == ["sections"]
        assert correction["previousOutput"]["sections"][0]["analysisIds"] == ["analysis_001"]
        assert "analysis_002" in correction["validationFeedback"]["issues"][0]["reason"]
        return complete

    envelope = reporting_contract.ReportRequestEnvelope.model_validate(
        {
            "reportGoal": "整体运营分析",
            "reportType": "comprehensive",
            "period": {"start": "2025-01-01", "end": "2025-12-31"},
            "sourceIds": ["source-1"],
        }
    )
    detailed_plan = _detailed_analysis_plan_payload()
    second_analysis = dict(detailed_plan["analyses"][0])
    second_analysis.update(
        {
            "analysisId": "analysis_002",
            "managementQuestion": "成本效率如何",
        }
    )
    detailed_plan["analyses"].append(second_analysis)
    state: dict[str, Any] = {
        REPORT_WORKFLOW_INPUT_STATE_KEY: envelope.model_dump(mode="json", by_alias=True),
        REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY: detailed_plan,
    }
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._outline_agent = stage
    runtime._state = lambda _run_context: state
    runtime._envelope = lambda _run_context: envelope
    runtime._assert_state_safe = lambda _state: None
    runtime._run_planner = fake_run_planner

    output = await runtime.generate_outline(
        SimpleNamespace(additional_data=None), SimpleNamespace(session_state=state)
    )

    assert planner_calls == 2
    outline = ReportOutline.model_validate(output.content)
    assert outline.sections[0].analysis_ids == ("analysis_001", "analysis_002")


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
