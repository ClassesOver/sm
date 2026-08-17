from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

import pytest
from agno.agent import Agent
from agno.agent._tools import parse_tools
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.base import RunStatus
from openai.types.chat.chat_completion_chunk import (
    ChoiceDeltaToolCall,
    ChoiceDeltaToolCallFunction,
)

from agentos_dev import app
from agentos_dev.reporting.agent import ReportFacadeOpenAIChat, create_report_agent
from agentos_dev.reporting.workflow.controller import (
    ReportWorkflowController,
    ReportWorkflowToolkit,
)
from agentos_dev.context_management import ProjectedOpenAIChat
from agentos_dev.instructions import (
    PURE_CODING_PARALLEL_READ_INSTRUCTIONS,
    build_coding_agent_instructions,
    build_pure_coding_agent_instructions,
)
from agentos_dev.model_config import OPENAI_COMPATIBLE_ROLE_MAP


def instruction_context(*tools, dependencies=None):
    return RunContext(
        run_id="run-1",
        session_id="thread-1",
        client_tools=[SimpleNamespace(name=name) for name in tools],
        dependencies=dependencies,
    )



@dataclass
class ScriptedModel(Model):
    responses: list[ModelResponse] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def _next_response(self, **kwargs: Any) -> ModelResponse:
        self.calls.append(kwargs)
        return self.responses.pop(0)

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next_response(args=args, **kwargs)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next_response(args=args, **kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield await self.ainvoke(*args, **kwargs)

    def _parse_provider_response(self, response: Any, **_kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response




def test_openai_compatible_role_map_preserves_system_instructions():
    assert OPENAI_COMPATIBLE_ROLE_MAP["system"] == "system"





def test_pure_coding_agent_batches_only_independent_reads():
    context = instruction_context()
    base = build_coding_agent_instructions(context)
    instructions = build_pure_coding_agent_instructions(context)
    text = "\n".join(instructions)

    assert instructions == [*base, *PURE_CODING_PARALLEL_READ_INSTRUCTIONS]
    assert "2 到 10 个只读操作" in text
    assert "同一次模型响应中并行调用" in text
    assert "彼此独立且服务于同一当前步骤" in text
    assert "路径未知" in text and "数据依赖的读取必须串行" in text
    assert "不得批量调用无关读取、超大范围读取" in text
    for tool_name in (
        "list_files",
        "read_file",
        "read_lines",
        "search_text",
        "tree",
        "git_status",
        "git_diff",
        "read_tool_output",
        "view_image",
    ):
        assert tool_name in text
    assert "非执行型 Skill 读取" in text
    assert (
        "并行批次不得包含 terminal、process、update_plan、任何 mutation、verify 或 finish_task"
        in text
    )




@pytest.mark.anyio

@pytest.mark.anyio
async def test_report_start_tool从当前用户消息启动workflow():
    calls = []

    class FakeController:
        async def start(self, workflow_input, run_context):
            calls.append((workflow_input.prompt, run_context.session_id))
            return {"ok": True, "status": "completed"}

    model = ScriptedModel(
        id="scripted-report-start-model",
        responses=[
            ModelResponse(
                tool_calls=[
                    {
                        "id": "call-report-start",
                        "type": "function",
                        "function": {
                            "name": "report_workflow_start",
                            "arguments": "{}",
                        },
                    }
                ]
            ),
            ModelResponse(content="报表工作流已启动。"),
        ],
    )
    agent = Agent(
        id="report-start-test",
        model=model,
        tools=[ReportWorkflowToolkit(cast(ReportWorkflowController, FakeController()))],
        db=InMemoryDb(),
        telemetry=False,
    )
    goal = "生成瑞金医院2025年收入、预算、成本和工作量分析报告"

    completed = await agent.arun(
        goal,
        run_id="run-report-start",
        session_id="thread-report-start",
        user_id="user-report-start",
    )

    assert completed.status is RunStatus.completed
    assert completed.content == "报表工作流已启动。"
    assert calls == [(goal, "thread-report-start")]


@pytest.mark.anyio
async def test_report_facade把workflow暂停确定性提升为agent原生hitl(monkeypatch):
    provider_calls = []

    async def provider_ainvoke(_model, messages, *_args, **_kwargs):
        provider_calls.append(messages)
        if len(provider_calls) > 1:
            raise AssertionError("Workflow paused 后不应再次请求供应商模型")
        return ModelResponse(
            tool_calls=[
                {
                    "id": "call-report-start",
                    "type": "function",
                    "function": {"name": "report_workflow_start", "arguments": "{}"},
                }
            ]
        )

    class FakeController:
        async def start(self, _workflow_input, _run_context):
            return {
                "ok": True,
                "status": "paused",
                "review": {
                    "stage": "outline",
                    "title": "审核报告提纲",
                    "message": "请审核报告提纲。",
                    "preview": {"title": "瑞金医院2025年整体运营分析报告"},
                },
            }

    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke", provider_ainvoke)
    model = ReportFacadeOpenAIChat(id="report-facade-routing-test", api_key="test-key")
    agent = Agent(
        id="report-facade-routing-test",
        model=model,
        tools=[ReportWorkflowToolkit(cast(ReportWorkflowController, FakeController()))],
        db=InMemoryDb(),
        telemetry=False,
    )

    paused = await agent.arun(
        "生成瑞金医院2025年整体运营分析报告",
        run_id="run-report-routing",
        session_id="thread-report-routing",
        user_id="user-report-routing",
    )

    assert paused.status is RunStatus.paused
    assert "审核报告提纲" in str(paused.content)
    assert "瑞金医院2025年整体运营分析报告" in str(paused.content)
    assert len(provider_calls) == 1
    assert len(paused.active_requirements) == 1
    requirement = paused.active_requirements[0]
    assert requirement.tool_execution.tool_name == "report_workflow_approve"
    assert requirement.needs_confirmation is True
    assert requirement.needs_user_input is False


@pytest.mark.anyio
async def test_report_facade流式运行把workflow暂停提升为agent原生hitl(monkeypatch):
    provider_calls = []

    async def provider_ainvoke_stream(_model, messages, *_args, **_kwargs):
        provider_calls.append(messages)
        if len(provider_calls) > 1:
            raise AssertionError("Workflow paused 后不应再次请求供应商模型")
        yield ModelResponse(
            tool_calls=[
                ChoiceDeltaToolCall(
                    index=0,
                    id="call-report-start",
                    type="function",
                    function=ChoiceDeltaToolCallFunction(
                        name="report_workflow_start", arguments="{}"
                    ),
                )
            ]
        )

    class FakeController:
        async def start(self, _workflow_input, _run_context):
            return {
                "ok": True,
                "status": "paused",
                "review": {
                    "stage": "outline",
                    "title": "审核报告提纲",
                    "message": "请审核报告提纲。",
                    "preview": {"title": "瑞金医院2025年整体运营分析报告"},
                },
            }

    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke_stream", provider_ainvoke_stream)
    worker = Agent(
        id="report-facade-stream-worker-test",
        model=ProjectedOpenAIChat(id="report-facade-stream-routing-test", api_key="test-key"),
        db=InMemoryDb(),
        checkpoint="tool-batch",
        telemetry=False,
    )
    agent = create_report_agent(worker, cast(ReportWorkflowController, FakeController()))

    events = [
        event
        async for event in agent.arun(
            "生成瑞金医院2025年整体运营分析报告",
            run_id="run-report-stream-routing",
            session_id="thread-report-stream-routing",
            user_id="user-report-stream-routing",
            stream=True,
            stream_events=True,
        )
    ]

    assert len(provider_calls) == 1
    paused_index = next(index for index, event in enumerate(events) if event.event == "RunPaused")
    assert any(
        event.event == "RunContent"
        and "审核报告提纲" in str(getattr(event, "content", ""))
        and "瑞金医院2025年整体运营分析报告" in str(getattr(event, "content", ""))
        for event in events[:paused_index]
    )
    paused = events[-1]
    assert paused.event == "RunPaused"
    assert len(paused.active_requirements) == 1
    requirement = paused.active_requirements[0]
    assert requirement.tool_execution.tool_name == "report_workflow_approve"
    assert requirement.needs_confirmation is True


@pytest.mark.anyio
async def test_report_review_tool暂停agent并用用户反馈继续同run():
    calls = []

    class FakeController:
        async def reject(self, feedback, run_context):
            calls.append((feedback, run_context.session_id))
            return {"ok": True, "status": "completed"}

    model = ScriptedModel(
        id="scripted-report-review-model",
        responses=[
            ModelResponse(
                tool_calls=[
                    {
                        "id": "call-report-review",
                        "type": "function",
                        "function": {
                            "name": "report_workflow_review",
                            "arguments": "{}",
                        },
                    }
                ]
            ),
            ModelResponse(content="已按修改意见继续报表工作流。"),
        ],
    )
    agent = Agent(
        id="report-review-test",
        model=model,
        tools=[ReportWorkflowToolkit(cast(ReportWorkflowController, FakeController()))],
        db=InMemoryDb(),
        telemetry=False,
    )

    paused = await agent.arun(
        "审核当前提纲",
        run_id="run-report-review",
        session_id="thread-report-review",
        user_id="user-report-review",
    )

    assert paused.status is RunStatus.paused
    assert len(paused.active_requirements) == 1
    requirement = paused.active_requirements[0]
    assert requirement.needs_user_input is True
    fields = {field.name: field for field in requirement.user_input_schema or []}
    fields["action"].value = "reject"
    fields["feedback"].value = "补充异常原因和改进责任人"

    completed = await agent.acontinue_run(
        run_id=paused.run_id,
        session_id=paused.session_id,
        requirements=paused.requirements,
    )

    assert completed.status is RunStatus.completed
    assert completed.run_id == paused.run_id
    assert completed.content == "已按修改意见继续报表工作流。"
    assert calls == [("补充异常原因和改进责任人", "thread-report-review")]


@pytest.mark.anyio
async def test_report原生确认拒绝后把备注确定性交给workflow(monkeypatch):
    provider_calls = []
    controller_calls = []

    async def provider_ainvoke(_model, _messages, *_args, **_kwargs):
        provider_calls.append(None)
        if len(provider_calls) == 1:
            return ModelResponse(
                tool_calls=[
                    {
                        "id": "call-report-start",
                        "type": "function",
                        "function": {"name": "report_workflow_start", "arguments": "{}"},
                    }
                ]
            )
        return ModelResponse(content="已按拒绝意见继续报表工作流。")

    class FakeController:
        async def start(self, _workflow_input, _run_context):
            return {
                "ok": True,
                "status": "paused",
                "review": {
                    "stage": "outline",
                    "title": "审核报告提纲",
                    "message": "请审核报告提纲。",
                    "preview": {"title": "瑞金医院2025年整体运营分析报告"},
                },
            }

        async def reject(self, feedback, run_context):
            controller_calls.append((feedback, run_context.session_id))
            return {"ok": True, "status": "completed"}

    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke", provider_ainvoke)
    agent = Agent(
        id="report-confirmation-reject-test",
        model=ReportFacadeOpenAIChat(id="report-confirmation-reject-test", api_key="test-key"),
        tools=[ReportWorkflowToolkit(cast(ReportWorkflowController, FakeController()))],
        db=InMemoryDb(),
        telemetry=False,
    )

    paused = await agent.arun(
        "生成瑞金医院2025年整体运营分析报告",
        run_id="run-report-confirmation-reject",
        session_id="thread-report-confirmation-reject",
        user_id="user-report-confirmation-reject",
    )
    requirement = paused.active_requirements[0]
    requirement.reject(note="补充异常原因和改进责任人")

    completed = await agent.acontinue_run(
        run_id=paused.run_id,
        session_id=paused.session_id,
        requirements=paused.requirements,
    )

    assert completed.status is RunStatus.completed
    assert completed.run_id == paused.run_id
    assert completed.content == "已按拒绝意见继续报表工作流。"
    assert len(provider_calls) == 2
    assert controller_calls == [("补充异常原因和改进责任人", "thread-report-confirmation-reject")]


@pytest.mark.anyio



def test_toolkit_instructions_are_injected_by_agno():
    (workflow_toolkit,) = app.report_agent.tools(
        run_context=RunContext(
            run_id="run",
            session_id="thread",
            session_state={"agentos_loaded_toolkits": ["report"]},
        )
    )

    assert workflow_toolkit.add_instructions is True
    assert "report_workflow_start" in workflow_toolkit.instructions
    assert "不得绕过 Workflow" in workflow_toolkit.instructions

    parsed = parse_tools(
        app.report_agent,
        [workflow_toolkit],
        app.report_agent.model,
        run_context=instruction_context(),
        async_mode=True,
    )
    assert workflow_toolkit.instructions in app.report_agent._tool_instructions
    parsed_tools = {function.name: function for function in parsed if hasattr(function, "name")}
    assert set(parsed_tools) == {
        "report_workflow_start",
        "report_workflow_review",
        "report_workflow_approve",
        "report_workflow_reject",
    }
    assert parsed_tools["report_workflow_review"].requires_user_input is True
    assert parsed_tools["report_workflow_approve"].requires_confirmation is True
    assert parsed_tools["report_workflow_start"].parameters == {
        "type": "object",
        "properties": {},
        "required": [],
    }
