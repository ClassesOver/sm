"""通过原生 AgentOS HTTP 路由验证报表断流与显式取消。"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import pytest
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.models.response import ModelResponse
from agno.os.routers.agents.router import get_agent_router
from agno.os.settings import AgnoAPISettings
from agno.run import RunContext, RunStatus
from agno.tools import tool
from agno.workflow import Step
from agno.workflow.types import StepOutput
from fastapi import FastAPI
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall, ChoiceDeltaToolCallFunction
from sqlalchemy import create_engine

from smart_reporting.integrations.dingyi_process import DingyiProcessAdapter
from smart_reporting.reporting.contract import ReportingWorkflowInput
from smart_reporting.reporting.tests.test_managed_reporting_workflow import Lifecycle
from smart_reporting.reporting.tests.test_reporting_workflow_controller import _ThreadOwnership
from smart_reporting.reporting.workflow.controller import ReportWorkflowController
from smart_reporting.reporting.workflow.managed import ManagedReportingWorkflow
from smart_reporting.reporting.workflow.orchestration import _timed_step_executor
from smart_reporting.runtime.application import ApplicationContext, create_agentos_app
from smart_reporting.runtime.settings import AgentSettings


@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.mark.anyio
@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("explicit_cancel", [False, True])
async def test_disconnect_keeps_report_running_until_completion_or_explicit_cancel(
    tmp_path, monkeypatch, resume, explicit_cancel
):
    started = asyncio.Event()
    release = asyncio.Event()
    stopped = asyncio.Event()
    run_ids = []
    later_steps = []
    journal = DingyiProcessAdapter(create_engine(f"sqlite:///{tmp_path / 'process.db'}"))
    db = SqliteDb(db_file=str(tmp_path / "runs.db"))

    async def blocking(step_input, run_context):
        started.set()
        try:
            await release.wait()
            return StepOutput(content="done")
        finally:
            stopped.set()

    async def later(step_input):
        later_steps.append("published")
        return StepOutput(content="published")

    workflow = ManagedReportingWorkflow(
        id="enterprise-reporting-workflow-v1", lifecycle=Lifecycle(), db=db,
        steps=[
            Step(name="run-coding-analysis", executor=_timed_step_executor(blocking, step_id="run-coding-analysis")),
            Step(name="finalize-publication", executor=later),
        ],
    )
    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(
        lambda: workflow, thread_ownership=ownership, terminal_cleanup=AsyncMock(),
        process_lifecycle=journal,
    )

    @tool(requires_confirmation=resume)
    async def generate_report(run_context: RunContext):
        run_ids.append(run_context.run_id)
        return await controller.start(ReportingWorkflowInput(prompt="生成报告"), run_context)

    async def response(_model, messages, **kwargs):
        if any(message.role == "tool" for message in messages):
            return ModelResponse(content="已完成")
        return ModelResponse(tool_calls=[{
            "id": "call-report", "type": "function",
            "function": {"name": "generate_report", "arguments": "{}"},
        }])

    async def response_stream(model, messages, **kwargs):
        output = await response(model, messages, **kwargs)
        if output.tool_calls:
            output.tool_calls = [ChoiceDeltaToolCall(
                index=0, id="call-report", type="function",
                function=ChoiceDeltaToolCallFunction(name="generate_report", arguments="{}"),
            )]
        yield output

    monkeypatch.setattr(OpenAIChat, "ainvoke", response)
    monkeypatch.setattr(OpenAIChat, "ainvoke_stream", response_stream)
    agent = Agent(id="smart-reporting", model=OpenAIChat(id="test", api_key="test"),
                  db=db, tools=[generate_report], telemetry=False)

    # 使用真实 AgentOS 路由和执行器，省去无关的数据库启动及工作区维护循环。
    class RouterOS:
        def __init__(self, **kwargs):
            self.agents = kwargs["agents"]
            self.db = None
            self.registry = None
            self.app = kwargs["base_app"]

        def get_app(self):
            self.app.include_router(get_agent_router(self, AgnoAPISettings(os_security_key=None)))
            return self.app

    monkeypatch.setattr("smart_reporting.runtime.application.AgentOS", RouterOS)
    _, app = create_agentos_app(ApplicationContext(
        AgentSettings.from_environment({}, load_env_file=False), SimpleNamespace(), agent, workflow,
    ), FastAPI())
    session_id = str(uuid4())
    path = "/agents/smart-reporting/runs"
    fields = {"message": "生成报告", "session_id": session_id, "user_id": "user",
              "stream": "true", "background": "false"}
    if resume:
        paused = await agent.arun("生成报告", session_id=session_id, user_id="user")
        assert paused.status == RunStatus.paused
        requirement = paused.active_requirements[0]
        requirement.confirm()
        path += f"/{paused.run_id}/continue"
        fields["tools"] = json.dumps([requirement.tool_execution.to_dict()])
        fields.pop("message")

    body = urlencode(fields).encode()
    disconnect = asyncio.Event()
    sent_body = False
    responses = []

    async def receive():
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        responses.append(message)

    request = asyncio.create_task(app({
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
        "client": ("127.0.0.1", 1234), "server": ("test", 80),
    }, receive, send))
    try:
        await asyncio.wait_for(started.wait(), 5)
        disconnect.set()
        await asyncio.wait_for(asyncio.shield(request), 3)
        assert responses[0]["status"] == 200
        assert not stopped.is_set(), "HTTP 断连不应取消报表工作流"
        snapshot = await journal._snapshot(run_ids[0])
        assert snapshot["operation"]["status"] == "running"
        assert ownership.owners
        if explicit_cancel:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                result = await client.post(f"/agents/smart-reporting/runs/{run_ids[0]}/cancel")
                assert result.status_code == 200
        else:
            release.set()
        async with asyncio.timeout(5):
            while True:
                saved = await agent.aget_run_output(run_ids[0], session_id=session_id)
                if saved and saved.status in {RunStatus.cancelled, RunStatus.completed, RunStatus.error}:
                    break
                await asyncio.sleep(0.02)
        expected = "cancelled" if explicit_cancel else "completed"
        assert RunStatus(saved.status).value.lower() == expected
        snapshot = await journal._snapshot(run_ids[0])
        assert snapshot["operation"]["status"] == expected
        assert snapshot["activities"][-1]["status"] == expected
        assert snapshot["operation"]["endedAt"]
        assert stopped.is_set()
        assert ownership.owners == {}
        assert later_steps == ([] if explicit_cancel else ["published"])
    finally:
        release.set()
        disconnect.set()
        if not request.done():
            request.cancel()
        await asyncio.gather(request, return_exceptions=True)
