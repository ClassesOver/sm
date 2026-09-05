import json
from unittest.mock import AsyncMock, Mock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.structured_output import ReportingStructuredOutputExecutor
from smart_reporting.reporting.workflow.execution import ReportingTaskInvocation
from smart_reporting.reporting.workflow.runtime.phase_models import VisualizationScriptDraft
from smart_reporting.task_execution import TaskExecutionScope


@pytest.mark.anyio
async def test_structured_executor_calls_arun_once_without_continuation() -> None:
    draft = Mock()
    draft.output_schema = VisualizationScriptDraft
    draft.arun = AsyncMock(return_value=Mock(content=VisualizationScriptDraft.model_construct()))
    executor = ReportingStructuredOutputExecutor(draft, idle_timeout_seconds=5)
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
    executor = ReportingStructuredOutputExecutor(agent, idle_timeout_seconds=5)
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


@pytest.mark.anyio
async def test_structured_executor_extracts_complete_json_object_from_model_preamble() -> None:
    payload = {
        "scriptPath": "charts/revenue.py",
        "pythonSource": 'print(json.dumps({"charts": []}))\n',
        "charts": [
            {
                "chartId": "chart_revenue",
                "sourcePath": "charts/revenue.png",
                "title": "收入趋势",
                "altText": "2025 年收入趋势",
                "citationIds": ["citation_001"],
                "metricCodes": ["revenue"],
                "currentPeriod": "2025",
                "comparisonType": "none",
                "sourceDatasetId": "dataset_001",
                "aggregationGrain": "month",
                "comparability": "strict",
            }
        ],
        "warnings": [],
    }
    agent = Mock()
    agent.output_schema = VisualizationScriptDraft
    agent.arun = AsyncMock(
        return_value=Mock(
            content=(
                "以下是结果：\n```json\n"
                f"{json.dumps(payload, ensure_ascii=False)}"
                "\n```\n请按 JSON 使用。"
            )
        )
    )
    executor = ReportingStructuredOutputExecutor(agent, idle_timeout_seconds=5)
    scope = TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "generator")

    result = await executor.run(
        "instruction", scope=scope, run_context=RunContext(run_id="r", session_id="s")
    )

    assert isinstance(result, VisualizationScriptDraft)
    assert result.charts[0].chart_id == "chart_revenue"


@pytest.mark.anyio
async def test_structured_executor_does_not_merge_partial_json_objects() -> None:
    agent = Mock()
    agent.output_schema = VisualizationScriptDraft
    agent.arun = AsyncMock(
        return_value=Mock(
            content=(
                '{"scriptPath":"charts/revenue.py","pythonSource":"print(1)"}\n'
                '{"charts":[],"warnings":[]}'
            )
        )
    )
    executor = ReportingStructuredOutputExecutor(agent, idle_timeout_seconds=5)
    scope = TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "generator")

    with pytest.raises(ReportingError) as caught:
        await executor.run(
            "instruction", scope=scope, run_context=RunContext(run_id="r", session_id="s")
        )

    assert caught.value.code == "report_phase_output_invalid"
