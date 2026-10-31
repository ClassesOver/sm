from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.contract import ReportRequestEnvelope
from smart_reporting.reporting.workflow.controller import ReportWorkflowController
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
from smart_reporting.reporting.workflow.runtime.models import NormalizedReportPrompt


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("prompt", "model_period", "expected", "expected_yoy"),
    [
        (
            "分析瑞金医院收入、成本、工作量，期间为2025年1月1日至12月31日",
            {"start": "2025-01-01", "end": "2025-12-31"},
            {"start": "2025-01-01", "end": "2025-12-31"},
            {"start": "2024-01-01", "end": "2024-12-31"},
        ),
        (
            "分析2025年1-9月医院收入",
            {"start": "2025-01-01", "end": "2025-06-30"},
            {"start": "2025-01-01", "end": "2025-06-30"},
            {"start": "2024-01-01", "end": "2024-06-30"},
        ),
        (
            "分析2025年1-9月医院收入",
            None,
            {"start": "2025-01-01", "end": "2025-09-30"},
            {"start": "2024-01-01", "end": "2024-09-30"},
        ),
    ],
)
async def test_normalization_prefers_model_period_and_only_falls_back_when_missing(
    prompt, model_period, expected, expected_yoy,
):
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    runtime._run_planner = AsyncMock(return_value=NormalizedReportPrompt(
        reportType="topic", domains=("income",), period=model_period,
    ))
    context = SimpleNamespace(session_state={})

    output = await runtime.normalize_report_request(
        SimpleNamespace(input=prompt, additional_data=None), context,
    )

    assert output.content["period"] == expected
    assert context.session_state["report_request_context"]["period"] == expected
    envelope = ReportRequestEnvelope.from_untrusted(output.content)
    windows = {
        window.role: window.period.model_dump(mode="json")
        for window in envelope.period_windows().windows
    }
    assert windows == {"current": expected, "yoy": expected_yoy}


@pytest.mark.anyio
async def test_normalization_preserves_semantically_interpreted_section_count():
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    runtime._run_planner = AsyncMock(return_value=NormalizedReportPrompt(
        reportType='topic', domains=('income',), sectionCount=1,
    ))
    context = SimpleNamespace(session_state={})
    output = await runtime.normalize_report_request(
        SimpleNamespace(input='分析2025年收入，所有内容放在同一个章内', additional_data=None), context,
    )
    assert output.content['sectionCount'] == 1
    assert context.session_state['report_request_context']['sectionCount'] == 1


@pytest.mark.anyio
async def test_assertion_mode_is_pinned_for_new_runs_and_legacy_resume_is_shadow(monkeypatch):
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    runtime._run_planner = AsyncMock(return_value=NormalizedReportPrompt(reportType="topic", domains=("income",)))
    monkeypatch.setenv("REPORT_ASSERTION_MODE", "enabled")
    context = SimpleNamespace(session_state={})
    step = SimpleNamespace(input="分析2025年医院收入趋势", additional_data=None)
    await runtime.normalize_report_request(step, context)
    policy = context.session_state["report_request_context"]["assertionPolicy"]
    assert policy["mode"] == "enabled"
    monkeypatch.setenv("REPORT_ASSERTION_MODE", "off")
    await runtime.normalize_report_request(step, context)
    assert context.session_state["report_request_context"]["assertionPolicy"] == policy
    del context.session_state["report_request_context"]["assertionPolicy"]
    monkeypatch.setenv("REPORT_ASSERTION_MODE", "enabled")
    await runtime.normalize_report_request(step, context)
    assert context.session_state["report_request_context"]["assertionPolicy"]["mode"] == "shadow"


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
        "visualizationMode": "static",
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
async def test_normalize_comprehensive_report_preserves_semantically_selected_domains() -> None:
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    runtime._run_planner = AsyncMock(
        return_value=NormalizedReportPrompt(
            reportType="comprehensive",
            domains=("income", "budget", "full_cost"),
        )
    )
    run_context = SimpleNamespace(session_state={})

    output = await runtime.normalize_report_request(
        SimpleNamespace(
            input="综合分析2025年医院收入、预算和成本",
            additional_data=None,
        ),
        run_context,
    )

    assert output.content["reportType"] == "comprehensive"
    assert output.content["domains"] == ["income", "budget", "full_cost"]


@pytest.mark.anyio
async def test_normalize_hospital_cost_analysis_selects_full_cost() -> None:
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    runtime._run_planner = AsyncMock(
        return_value=NormalizedReportPrompt(
            reportType="topic",
            domains=("full_cost",),
        )
    )
    run_context = SimpleNamespace(session_state={})

    output = await runtime.normalize_report_request(
        SimpleNamespace(input="分析2025年医院成本", additional_data=None),
        run_context,
    )

    assert output.content["reportType"] == "topic"
    assert output.content["domains"] == ["full_cost"]


@pytest.mark.anyio
async def test_normalize_uses_semantic_decision_for_cost_without_keyword_clarification() -> None:
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    runtime._run_planner = AsyncMock(
        return_value=NormalizedReportPrompt(
            reportType="topic",
            domains=("income", "full_cost"),
        )
    )
    run_context = SimpleNamespace(session_state={})

    output = await runtime.normalize_report_request(
        SimpleNamespace(input="分析2025年医院收入和成本", additional_data=None),
        run_context,
    )

    assert output.content["reportType"] == "topic"
    assert output.content["domains"] == ["income", "full_cost"]


@pytest.mark.anyio
async def test_normalize_overall_operation_defaults_comprehensive_to_all_domains() -> None:
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    runtime._run_planner = AsyncMock(
        return_value=NormalizedReportPrompt(reportType="comprehensive")
    )
    run_context = SimpleNamespace(session_state={})

    output = await runtime.normalize_report_request(
        SimpleNamespace(input="分析下2025年医院整体运营情况", additional_data=None),
        run_context,
    )

    assert output.content["reportType"] == "comprehensive"
    assert output.content["domains"] == [
        "income",
        "workload",
        "budget",
        "full_cost",
        "cost_control",
        "funds",
    ]


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


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("2025年1-9月全院经济运行分析报告", ("2025-01-01", "2025-09-30")),
        ("2025年1月至9月收入分析", ("2025-01-01", "2025-09-30")),
        ("截至2025年9月收入分析", ("2025-01-01", "2025-09-30")),
        ("2025年前三季度成本分析", ("2025-01-01", "2025-09-30")),
        ("2025年第二季度收入", ("2025-04-01", "2025-06-30")),
        ("2025年上半年工作量", ("2025-01-01", "2025-06-30")),
        ("2025年3月收入", ("2025-03-01", "2025-03-31")),
        ("分析2025年医院收入趋势", ("2025-01-01", "2025-12-31")),
    ],
)
def test_explicit_period_keeps_requested_months_instead_of_whole_year(prompt, expected) -> None:
    from smart_reporting.reporting.workflow.runtime.planning import _single_explicit_period

    period = _single_explicit_period(prompt, None)
    assert period is not None
    assert (period.start.isoformat(), period.end.isoformat()) == expected


@pytest.mark.parametrize("prompt", ["2025年1-3月和4-6月对比", "2025年13月收入", "2025-09收入"])
def test_ambiguous_period_is_left_to_model(prompt) -> None:
    from smart_reporting.reporting.workflow.runtime.planning import _single_explicit_period

    assert _single_explicit_period(prompt, None) is None
