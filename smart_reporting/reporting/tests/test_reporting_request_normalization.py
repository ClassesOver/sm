from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.workflow.controller import ReportWorkflowController
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
from smart_reporting.reporting.workflow.runtime.models import NormalizedReportPrompt


@pytest.mark.anyio
async def test_normalize_multi_domain_topic_without_requesting_clarification() -> None:
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    normalized = NormalizedReportPrompt(
        reportType="topic",
        domains=("income", "full_cost"),
    )
    runtime._run_planner = AsyncMock(return_value=normalized)
    run_context = SimpleNamespace(session_state={})

    output = await runtime.normalize_report_request(
        SimpleNamespace(
            input="分析2025年医院收入趋势及成本效率",
            additional_data=None,
        ),
        run_context,
    )

    assert output.content == {
        "version": "1",
        "reportGoal": "分析2025年医院收入趋势及成本效率",
        "reportType": "topic",
        "domains": ["income", "full_cost"],
        "period": {"start": "2025-01-01", "end": "2025-12-31"},
        "comparisonRoles": ["yoy"],
        "fileInputs": [],
    }


@pytest.mark.anyio
async def test_normalize_uses_sentence_semantics_for_domains_not_covered_by_aliases() -> None:
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    normalized = NormalizedReportPrompt(
        reportType="topic",
        domains=("income", "full_cost"),
    )
    runtime._run_planner = AsyncMock(return_value=normalized)
    run_context = SimpleNamespace(session_state={})

    output = await runtime.normalize_report_request(
        SimpleNamespace(
            input="分析2025年医院营收走势与经营投入产出效率",
            additional_data=None,
        ),
        run_context,
    )

    assert output.content["reportType"] == "topic"
    assert output.content["domains"] == ["income", "full_cost"]


@pytest.mark.anyio
async def test_normalize_keeps_clarification_when_semantics_do_not_resolve_cost() -> None:
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    runtime._run_planner = AsyncMock(
        return_value=NormalizedReportPrompt(
            reportType="topic",
            domains=("income",),
            clarificationQuestion="请明确成本指全成本还是费控。",
        )
    )
    run_context = SimpleNamespace(session_state={})

    output = await runtime.normalize_report_request(
        SimpleNamespace(input="分析2025年医院收入和成本", additional_data=None),
        run_context,
    )

    assert output.content == {"clarificationQuestion": "请明确成本指全成本还是费控。"}


@pytest.mark.anyio
async def test_normalize_warns_when_topic_domain_cannot_be_inferred() -> None:
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    runtime._run_planner = AsyncMock(
        return_value=NormalizedReportPrompt(
            reportType="topic",
            clarificationQuestion="请明确需要分析的业务主题。",
        )
    )
    run_context = SimpleNamespace(session_state={})

    output = await runtime.normalize_report_request(
        SimpleNamespace(input="分析2025年医院这个专项", additional_data=None),
        run_context,
    )

    assert output.content == {"clarificationQuestion": "请明确需要分析的业务主题。"}


@pytest.mark.anyio
async def test_normalize_keeps_clarification_when_model_cannot_classify_topic() -> None:
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    runtime._run_planner = AsyncMock(
        return_value=NormalizedReportPrompt(
            clarificationQuestion="请明确需要分析的业务主题。",
        )
    )
    run_context = SimpleNamespace(session_state={})

    output = await runtime.normalize_report_request(
        SimpleNamespace(input="分析2025年医院这个专项", additional_data=None),
        run_context,
    )

    assert output.content == {"clarificationQuestion": "请明确需要分析的业务主题。"}


def test_request_review_title_does_not_claim_only_period_is_missing() -> None:
    requirement = SimpleNamespace(
        step_name="规范化报表请求",
        step_output=SimpleNamespace(
            content={"clarificationQuestion": "请明确主分析领域：全成本或费控。"}
        ),
        confirmation_message=None,
        output_review_message="补充缺失的主分析领域或分析期间。",
        is_resolved=False,
    )
    output = SimpleNamespace(
        active_step_requirements=[requirement],
        step_requirements=[requirement],
        error_requirements=[],
    )

    controller = object.__new__(ReportWorkflowController)
    review = controller._review(output)

    assert review.title == "补充报表信息"
    assert review.preview == {"clarificationQuestion": "请明确主分析领域：全成本或费控。"}
