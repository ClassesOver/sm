from unittest.mock import AsyncMock, Mock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.workflow.execution import (
    ReportingStructuredAgentExecutor,
    ReportingTaskInvocation,
)
from smart_reporting.reporting.workflow.runtime.phase_models import VisualizationScriptDraft
from smart_reporting.task_execution import TaskExecutionScope


@pytest.mark.anyio
async def test_structured_executor_calls_arun_once_without_continuation() -> None:
    draft = Mock()
    draft.output_schema = VisualizationScriptDraft
    draft.arun = AsyncMock(return_value=Mock(content=VisualizationScriptDraft.model_construct()))
    executor = ReportingStructuredAgentExecutor(draft, idle_timeout_seconds=5)
    scope = TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "generator")

    result = await executor.run(
        "instruction", scope=scope, run_context=RunContext(run_id="r", session_id="s")
    )

    assert isinstance(result, VisualizationScriptDraft)
    draft.arun.assert_awaited_once()
    draft.acontinue_run = AsyncMock()
    draft.acontinue_run.assert_not_awaited()


@pytest.mark.anyio
async def test_structured_executor_implements_task_coordinator_protocol() -> None:
    agent = Mock()
    agent.output_schema = None
    agent.arun = AsyncMock(return_value=Mock(content={"status": "candidate"}))
    executor = ReportingStructuredAgentExecutor(agent, idle_timeout_seconds=5)
    scope = TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "generator")
    result = await executor(
        ReportingTaskInvocation(
            instruction="instruction",
            run_context=RunContext(run_id="r", session_id="s"),
            continuing=False,
            scope=scope,
            parent_run_id="",
            model_metrics_settlement=Mock(),
        )
    )
    assert result == {"status": "candidate"}
    agent.arun.assert_awaited_once()
