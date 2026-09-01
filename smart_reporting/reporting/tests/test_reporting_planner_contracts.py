from __future__ import annotations

import ast
import inspect
import json
import textwrap
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from agno.agent import Agent
from agno.models.response import ModelResponse
from agno.workflow.step import StepOutput
from pydantic import ValidationError
from sqlglot import parse_one

from smart_reporting.context_management import ProjectedOpenAIChat
from smart_reporting.reporting import contract as reporting_contract
from smart_reporting.reporting.agent import ReportWorkerOpenAIChat
from smart_reporting.reporting.contract import ReportPeriod
from smart_reporting.reporting.data_sources import DatasetHandle
from smart_reporting.reporting.hospital_operation.detailed_analysis import (
    AnalysisFileIdentity,
    DatasetAnalysisContext,
    DetailedAnalysisPlan,
)
from smart_reporting.reporting.hospital_operation.outline import (
    ReportOutline,
    ReportOutlineProposal,
)
from smart_reporting.reporting.instructions import (
    REPORT_ANALYSIS_ITEM_AGENT_INSTRUCTIONS,
    REPORT_VISUALIZATION_SECTION_AGENT_INSTRUCTIONS,
)
from smart_reporting.reporting.model_policy import (
    ReportingThinkingProfile,
    reporting_thinking_profile_from_model,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.checkpoint import (
    FileIdentity,
    MetricDefinition,
    ProfileCoverageDataset,
    ProfileCoverageManifest,
)
from smart_reporting.reporting.workflow.query_pipeline import _has_complete_period_filter
from smart_reporting.reporting.workflow.runtime import (
    REPORT_WORKFLOW_INPUT_STATE_KEY,
    ReportWorkflowRuntime,
)
from smart_reporting.reporting.workflow.runtime import planning as reporting_runtime
from smart_reporting.reporting.workflow.runtime.analysis import _coding_detailed_analysis_plan
from smart_reporting.reporting.workflow.runtime.base import (
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
from smart_reporting.reporting.workflow.runtime.validation import _normalize_requirement_periods


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


def test_coding_analysis_plan_projects_only_unfinished_items() -> None:
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

    projected = _coding_detailed_analysis_plan(
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
    assert "首次写入使用 create_analysis_file" in instructions
    assert "只有读取已有文件并取得当前 SHA-256 后才使用 overwrite_analysis_file" in instructions
    assert (
        "成功脚本的 stdout 仅输出 evidencePath、处理行数、固定事实对账值和核心可比指标"
        in instructions
    )
    assert "完整聚合结果只写入 evidence JSON" in instructions
    assert "只有证据直接证明因果链时才使用“导致”或“完全由”" in instructions


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
    coverage = ProfileCoverageManifest(
        authorizedDatasetCount=1,
        coveredDatasetCount=1,
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
        ),
    )
    state: dict[str, Any] = {
        REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY: [context.model_dump(mode="json", by_alias=True)],
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
        REPORT_WORKFLOW_RESULT_STATE_KEY: {"datasets": [handle.public_dict()]},
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
    assert (
        "仅当 deterministicFacts 未覆盖当前管理问题的必需事实时，从不可变 CSV 复算并保存补充 evidence"
        in analysis.actions
    )
    assert "deterministicFacts 覆盖当前管理问题时直接提交" in analysis.evidence_summary
    assert "仅在必需事实缺口时由 Coding 从 CSV 复算并保存补充 evidence" in analysis.evidence_summary
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


def test_analysis_item_thinking_effort_follows_worker_retry_policy() -> None:
    source = inspect.getsource(ReportWorkflowRuntime._run_analysis_item_task)

    assert "self._worker_thinking_effort(retry=retry)" in source
    assert 'self._worker_thinking_effort(retry=True) if retry else "off"' not in source


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
        model=ReportWorkerOpenAIChat(
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
    worker = Agent(
        model=ReportWorkerOpenAIChat(
            id="deepseek-v4-flash-0731",
            api_key="test",
            reasoning_effort="high",
            extra_body={"enable_thinking": True, "thinking_budget": 8192},
        )
    )

    runtime = ReportWorkflowRuntime(
        db=SimpleNamespace(),
        report_worker=worker,
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
    expected_profiles = (
        (runtime._data_understanding_agent, False, "high"),
        (runtime._measure_semantic_agent, False, "max"),
        (runtime._analysis_agent, True, "max"),
        (runtime._sql_agent, False, "max"),
    )
    for stage, enabled, expected_effort in expected_profiles:
        profile = reporting_thinking_profile_from_model(stage.model)
        assert profile.enabled is enabled
        if enabled:
            assert profile.reasoning_effort == expected_effort
            assert profile.thinking_budget == 8192
        escalation = getattr(stage.model, "_report_escalation_thinking_profile")
        assert escalation.enabled is True
        assert escalation.reasoning_effort == expected_effort
        assert escalation.thinking_budget == 8192


def test_runtime_planners_project_reasoning_to_vllm_chat_template() -> None:
    worker = Agent(
        model=ReportWorkerOpenAIChat(
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
        report_worker=worker,
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
        "thinking_budget": 8192,
        "chat_template_kwargs": {
            "enable_thinking": True,
            "thinking": True,
            "reasoning_effort": "max",
        },
    }


def test_analysis_planner_normalizes_repeated_source_prefix_before_schema_validation() -> None:
    planner = Agent(
        model=ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test"),
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


def test_analysis_planner_rejects_three_part_table_with_unrelated_source_prefix() -> None:
    planner = Agent(
        model=ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test"),
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
        model=ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test"),
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


def test_outline_validator_attaches_candidate_on_validation_error() -> None:
    """响应校验失败时把候选载荷附在异常上，供纠错循环用作 previousOutput 基线。"""
    planner = Agent(model=ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test"))
    stage = ReportWorkflowRuntime._planning_agent(
        planner,
        "report-outline-planner",
        ReportOutlineProposal,
        thinking_profile=ReportingThinkingProfile.off(),
    )
    validator = getattr(stage.model, "_report_response_validator")

    with pytest.raises(ValidationError) as raised:
        validator(json.dumps(_duplicate_analysis_outline_payload()))

    candidate = getattr(raised.value, "_report_candidate", None)
    assert isinstance(candidate, dict)
    assert candidate["reportType"] == "comprehensive"
    assert candidate["sections"][1]["analysisIds"] == ["analysis_001"]


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
        Agent(model=ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")),
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

    async def fake_run_planner(_agent, payload, _run_context):
        nonlocal planner_calls
        planner_calls += 1
        if planner_calls == 1:
            # 模拟 Agno Agent 重试耗尽后由 _raise_recorded_agent_error 抛出的校验异常。
            validator = getattr(_agent.model, "_report_response_validator")
            validator(json.dumps(_duplicate_analysis_outline_payload()))
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

    async def fake_run_planner(_agent, payload, _run_context):
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

    async def fake_run_planner(_agent, _payload, _run_context):
        nonlocal planner_calls
        planner_calls += 1
        validator = getattr(_agent.model, "_report_response_validator")
        validator(json.dumps(_duplicate_analysis_outline_payload()))

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
