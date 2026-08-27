from __future__ import annotations

import ast
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from agno.agent import Agent
from agno.models.response import ModelResponse
from pydantic import ValidationError
from sqlglot import parse_one

from smart_reporting.context_management import ProjectedOpenAIChat
from smart_reporting.reporting import contract as reporting_contract
from smart_reporting.reporting.agent import ReportWorkerOpenAIChat
from smart_reporting.reporting.contract import ReportPeriod
from smart_reporting.reporting.hospital_operation.detailed_analysis import (
    DetailedAnalysisPlan,
)
from smart_reporting.reporting.hospital_operation.outline import ReportOutlineProposal
from smart_reporting.reporting.instructions import (
    REPORT_ANALYSIS_ITEM_AGENT_INSTRUCTIONS,
)
from smart_reporting.reporting.model_policy import (
    ReportingThinkingProfile,
    reporting_thinking_profile_from_model,
)
from smart_reporting.reporting.workflow.checkpoint import MetricDefinition
from smart_reporting.reporting.workflow.query_pipeline import _has_complete_period_filter
from smart_reporting.reporting.workflow.runtime import (
    REPORT_WORKFLOW_INPUT_STATE_KEY,
    ReportWorkflowRuntime,
)
from smart_reporting.reporting.workflow.runtime import planning as reporting_runtime
from smart_reporting.reporting.workflow.runtime.analysis import _coding_detailed_analysis_plan
from smart_reporting.reporting.workflow.runtime.datasets import _requirement_measure_field_refs
from smart_reporting.reporting.workflow.runtime.models import (
    AnalysisBundle,
    DataUnderstandingPlan,
)
from smart_reporting.reporting.workflow.runtime.planning import _PLANNER_DISPLAY_NAMES
from smart_reporting.reporting.workflow.runtime.publication import (
    _analysis_quality_warnings,
)
from smart_reporting.reporting.workflow.runtime.validation import _normalize_requirement_periods


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
    assert "首次任务默认只调用一次 query_analysis_facts" in instructions
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
