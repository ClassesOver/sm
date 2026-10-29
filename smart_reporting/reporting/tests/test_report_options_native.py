"""使用新版 SDK 验证原生表单预填和用户修改，不调用真实模型。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.response import ModelResponse
from agno.run.base import RunStatus
from dingyi_agno.chat.protocol import tool_requirement_block

from smart_reporting.context_management import ProjectedOpenAIChat
from smart_reporting.reporting.agent import ReportFacadeOpenAIChat
from smart_reporting.reporting.workflow.controller import ReportWorkflowToolkit
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
from smart_reporting.reporting.workflow.runtime.models import NormalizedReportPrompt


@pytest.mark.anyio
async def test_native_schema_prefills_and_confirmation_preserves_edits(monkeypatch):
    start = AsyncMock(return_value={"ok": True, "status": "completed"})
    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke", AsyncMock(return_value=ModelResponse(
        tool_calls=[{"id": "options", "type": "function", "function": {
            "name": "report_workflow_start", "arguments": '{"period_start":"2025-02-01","period_end":"2025-03-31","metrics":["收入","工作量"],"analysis_dimensions":["院区","科室"]}',
        }}],
    )))
    agent = Agent(model=ReportFacadeOpenAIChat(id="fixture", api_key="fixture"),
                  tools=[ReportWorkflowToolkit(SimpleNamespace(start=start))],
                  db=InMemoryDb(), telemetry=False)
    goal = "按院区和科室分析2025年2至3月收入和工作量"
    paused = await agent.arun(goal, session_id="options")
    assert paused.status is RunStatus.paused
    start.assert_not_awaited()
    requirement = paused.active_requirements[0]
    block = tool_requirement_block(requirement.tool_execution.to_dict())
    fields = block["schema"]["properties"]
    assert fields["period_start"]["format"] == "date"
    assert fields["period_start"]["title"] == "开始日期"
    assert fields["metrics"]["items"]["enum"] == ["收入", "预算", "成本", "工作量", "费用管控", "资金"]
    assert fields["report_length"]["default"] == "简要版"
    assert fields["analysis_dimensions"]["items"]["enum"][:3] == ["院区", "科室", "类型"]
    values = {item.name: item.value for item in requirement.user_input_schema}
    values.update(period_end="2025-04-30", metrics=["预算"], report_length="详细版")
    requirement.provide_user_input(values)
    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke", AsyncMock(return_value=ModelResponse(content="已确认")))
    completed = await agent.acontinue_run(run_id=paused.run_id, session_id=paused.session_id,
                                         requirements=paused.requirements)
    assert completed.status is RunStatus.completed
    start.assert_awaited_once()
    request = start.call_args.args[0]
    assert request.prompt == goal
    assert request.request_options.period.end.isoformat() == "2025-04-30"
    assert request.request_options.domains == ("budget",)
    assert request.request_options.report_length == "详细版"


@pytest.mark.anyio
async def test_confirmed_options_override_conflicting_planner_output():
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    runtime._run_planner = AsyncMock(return_value=NormalizedReportPrompt(
        reportType="topic", domains=("income",),
        period={"start": "2024-01-01", "end": "2024-12-31"},
    ))
    context = SimpleNamespace(session_state={})
    result = await runtime.normalize_report_request(SimpleNamespace(input={
        "prompt": "分析2025年收入", "requestOptions": {
            "period": {"start": "2025-02-01", "end": "2025-04-30"},
            "domains": ["budget"], "reportLength": "详细版", "analysisDimensions": ["科室"],
        },
    }, additional_data=None), context)
    assert result.content["period"] == {"start": "2025-02-01", "end": "2025-04-30"}
    assert result.content["domains"] == ["budget"]
    assert "详细版" in result.content["reportGoal"]
    assert "科室" in result.content["reportGoal"]
    assert context.session_state["report_request_context"]["originalGoal"] == result.content["reportGoal"]
