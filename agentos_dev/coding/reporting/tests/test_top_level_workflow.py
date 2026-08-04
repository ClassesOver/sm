from __future__ import annotations

from types import MethodType

import pytest
from agno.db.in_memory import InMemoryDb
from agno.run import RunContext
from agno.workflow.types import StepInput

from agentos_dev.coding.reporting.contract import ReportingWorkflowInput
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.coding.reporting.workflow.runtime import (
    NormalizedReportPrompt,
    ReportWorkflowRuntime,
)


def _runtime_with_normalized(value: NormalizedReportPrompt) -> ReportWorkflowRuntime:
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()

    async def run_planner(self, _agent, _payload, _context):
        return value

    runtime._run_planner = MethodType(run_planner, runtime)
    return runtime


def _context() -> RunContext:
    return RunContext(run_id="run-1", session_id="thread-1", user_id="user-1")


def test_workflow_input严格区分prompt与envelope():
    assert (
        ReportingWorkflowInput.model_validate(
            {"version": "1", "prompt": "分析2025年经营情况"}
        ).prompt
        == "分析2025年经营情况"
    )
    assert (
        ReportingWorkflowInput.model_validate(
            {
                "version": "1",
                "reportGoal": "分析经营情况",
                "period": {"start": "2025-01-01", "end": "2025-12-31"},
            }
        ).report_goal
        == "分析经营情况"
    )
    with pytest.raises(ValueError):
        ReportingWorkflowInput.model_validate(
            {
                "version": "1",
                "prompt": "分析经营情况",
                "period": {"start": "2025-01-01", "end": "2025-12-31"},
            }
        )


@pytest.mark.anyio
async def test_envelope首步直接校验且不调用模型():
    runtime = _runtime_with_normalized(NormalizedReportPrompt(clarificationQuestion="不应调用"))

    result = await runtime.normalize_report_request(
        StepInput(
            input={
                "version": "1",
                "reportGoal": "分析经营情况",
                "period": {"start": "2025-01-01", "end": "2025-12-31"},
            }
        ),
        _context(),
    )

    assert result.content["reportGoal"] == "分析经营情况"
    assert result.content["period"] == {"start": "2025-01-01", "end": "2025-12-31"}


@pytest.mark.anyio
async def test_prompt单个明确年份转换全年并保持原文():
    prompt = "瑞金医院2025年整体运营分析报告，涵盖收入、预算、成本和工作量"
    runtime = _runtime_with_normalized(NormalizedReportPrompt(clarificationQuestion="请提供期间"))

    result = await runtime.normalize_report_request(
        StepInput(input={"version": "1", "prompt": prompt}), _context()
    )

    assert result.content["reportGoal"] == prompt
    assert result.content["period"] == {"start": "2025-01-01", "end": "2025-12-31"}


@pytest.mark.anyio
@pytest.mark.parametrize("prompt", ["分析整体经营情况", "对比2024年和2025年经营情况"])
async def test_prompt缺失或冲突期间返回补充问题(prompt):
    runtime = _runtime_with_normalized(
        NormalizedReportPrompt(clarificationQuestion="请明确唯一的分析期间。")
    )

    result = await runtime.normalize_report_request(
        StepInput(input={"version": "1", "prompt": prompt}), _context()
    )

    assert result.content == {"clarificationQuestion": "请明确唯一的分析期间。"}


@pytest.mark.anyio
async def test_rejection_feedback在同一首步重试并保持原始目标():
    prompt = "分析整体经营情况"
    runtime = _runtime_with_normalized(
        NormalizedReportPrompt(period={"start": "2025-01-01", "end": "2025-12-31"})
    )

    result = await runtime.normalize_report_request(
        StepInput(
            input={"version": "1", "prompt": prompt},
            additional_data={"rejection_feedback": "分析2025年"},
        ),
        _context(),
    )

    assert result.content["reportGoal"] == prompt
    assert result.content["period"] == {"start": "2025-01-01", "end": "2025-12-31"}


@pytest.mark.anyio
async def test_发布签发是workflow审核后的正式末步骤():
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.db = InMemoryDb()
    calls = []

    async def issue(scope, session_id, run_id, output):
        calls.append((scope, session_id, run_id, output))
        return {"path": "reports/result.pdf", "size": 12, "sha256": "a" * 64}

    workflow = runtime.workflow(publication_issuer=issue)
    context = RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state={},
    )
    content = {
        "reportId": "report-1",
        "revision": 1,
        "pdfPath": "reports/internal.pdf",
        "pdfSize": 12,
        "pdfSha256": "a" * 64,
    }

    result = await workflow.steps[-1].executor(StepInput(previous_step_content=content), context)

    assert workflow.steps[-1].step_id == "finalize-publication"
    assert result.content == {"path": "reports/result.pdf", "size": 12, "sha256": "a" * 64}
    assert calls == [
        (
            {
                "external_run_id": "workflow-run",
                "thread_id": "workflow-session",
                "user_id": "user-1",
            },
            "workflow-session",
            "workflow-run",
            content,
        )
    ]


@pytest.mark.anyio
async def test_正式发布拒绝验收后被替换的pdf():
    runtime = object.__new__(ReportWorkflowRuntime)

    class Workspace:
        async def ahash_file(self, thread_id, path):
            assert thread_id == "thread-1"
            assert path == "reports/result.pdf"
            return {"path": path, "size": 7, "sha256": "b" * 64}

    runtime.workspace_service = Workspace()

    with pytest.raises(ReportingError) as raised:
        await runtime.issue_cli_publication(
            {"thread_id": "thread-1"},
            "session-1",
            "run-1",
            {
                "reportId": "report-1",
                "revision": 1,
                "pdfPath": "reports/result.pdf",
                "pdfSize": 12,
                "pdfSha256": "a" * 64,
            },
        )

    assert raised.value.code == "report_pdf_changed"
