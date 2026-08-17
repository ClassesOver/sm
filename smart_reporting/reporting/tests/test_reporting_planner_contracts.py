from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from agno.agent import Agent
from agno.models.response import ModelResponse
from pydantic import ValidationError

from smart_reporting.reporting import contract as reporting_contract
from smart_reporting.reporting.agent import ReportWorkerOpenAIChat
from smart_reporting.reporting.hospital_operation.detailed_analysis import (
    DetailedAnalysisPlan,
)
from smart_reporting.reporting.hospital_operation.outline import ReportOutlineProposal
from smart_reporting.reporting.instructions import (
    REPORT_ANALYSIS_ITEM_AGENT_INSTRUCTIONS,
)
from smart_reporting.reporting.model_policy import ReportingThinkingProfile
from smart_reporting.reporting.workflow import runtime as reporting_runtime
from smart_reporting.reporting.workflow.runtime import (
    REPORT_WORKFLOW_INPUT_STATE_KEY,
    AnalysisBundle,
    DataUnderstandingPlan,
    ReportWorkflowRuntime,
    _coding_detailed_analysis_plan,
    _normalize_requirement_periods,
)
from smart_reporting.context_management import ProjectedOpenAIChat


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
                    "fields": [],
                    "metrics": [],
                    "periods": [],
                    "actions": ["复算"],
                    "evidenceSummary": "保存证据",
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
    assert "不执行摘要百分比启发式匹配" in instructions


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
    assert stage.model.retries == 0
    assert stage.model.extra_body == {"enable_thinking": False}
    assert stage.model.reasoning_effort is None
    validator = getattr(stage.model, "_report_response_validator")
    with pytest.raises(ValidationError):
        validator("{}")


@pytest.mark.anyio
async def test_planner_schema_validation_uses_agno_agent_retries(monkeypatch) -> None:
    attempts = 0

    async def fake_aresponse(_self, *args, **kwargs):
        nonlocal attempts
        _ = args, kwargs
        attempts += 1
        if attempts < 3:
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
    )
    stage.delay_between_retries = 0

    output = await stage.arun("plan")

    assert attempts == 3
    assert isinstance(output.content, DataUnderstandingPlan)
