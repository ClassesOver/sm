from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.response import ModelResponse
from agno.run.base import RunStatus

from smart_reporting.context_management import ProjectedOpenAIChat
from smart_reporting.reporting.agent import ReportFacadeOpenAIChat
from smart_reporting.reporting.workflow.controller import ReportWorkflowToolkit


@pytest.mark.anyio
async def test_native_form_prefills_before_workflow_start_and_keeps_user_edits(monkeypatch):
    inputs = []

    async def start(workflow_input, _context):
        inputs.append(workflow_input)
        return {"ok": True, "status": "completed"}

    async def invoke(_model, _messages, *_args, **_kwargs):
        return ModelResponse(tool_calls=[{
            "id": "options", "type": "function", "function": {
                "name": "report_workflow_start", "arguments": json.dumps({
                    "period_start": "2025-02-01", "period_end": "2025-03-31",
                    "domains": ["income", "workload"],
                    "analysis_dimensions": ["院区", "科室"],
                }),
            },
        }])

    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke", invoke)
    agent = Agent(
        model=ReportFacadeOpenAIChat(id="fixture", api_key="fixture"),
        tools=[ReportWorkflowToolkit(SimpleNamespace(start=start))],
        db=InMemoryDb(), telemetry=False,
    )
    paused = await agent.arun("按院区和科室分析2025年2至3月收入和工作量", session_id="options")
    assert paused.status is RunStatus.paused
    assert inputs == []
    requirement = paused.active_requirements[0]
    fields = {item.name: item for item in requirement.user_input_schema}
    assert {name: item.value for name, item in fields.items()} == {
        "period_start": "2025-02-01", "period_end": "2025-03-31",
        "domains": ["income", "workload"], "report_length": "brief",
        "analysis_dimensions": ["院区", "科室"],
    }
    fields["period_end"].value = "2025-04-30"
    fields["report_length"].value = "detailed"
    fields["domains"].value = ["income", "full_cost"]
    fields["analysis_dimensions"].value = ["类型"]
    # 后续模型回复不再发起工具；此处验证确认后只启动一次。
    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke", AsyncMock(return_value=ModelResponse(content="已启动")))
    completed = await agent.acontinue_run(
        run_id=paused.run_id, session_id=paused.session_id, requirements=paused.requirements,
    )
    assert completed.status is RunStatus.completed
    assert len(inputs) == 1
    options = inputs[0].request_options
    assert options.period.model_dump(mode="json") == {"start": "2025-02-01", "end": "2025-04-30"}
    assert options.domains == ("income", "full_cost")
    assert options.report_length == "detailed"
    assert options.analysis_dimensions == ("类型",)


DOMAIN_CODES = ("income", "workload", "budget", "full_cost", "cost_control", "funds")


def _console_protocol_maps_option_schema() -> bool:
    """探测已安装的 Console 表单协议是否支持 format 与数组枚举（dingyi-agno>=0.5.5）。"""
    from dingyi_agno.chat.protocol import tool_requirement_block

    try:
        probe = tool_requirement_block({
            "tool_name": "probe",
            "requires_user_input": True,
            "user_input_schema": [
                {"name": "period_start", "field_type": "str", "format": "date", "value": ""},
                {"name": "domains", "field_type": "list", "allowed_values": ["income"], "required": False},
            ],
        })
        properties = probe["schema"]["properties"]
        return (
            properties.get("period_start", {}).get("format") == "date"
            and properties.get("domains", {}).get("type") == "array"
        )
    except Exception:
        return False


async def _pause_report_workflow_start(monkeypatch, session_id: str):
    async def invoke(_model, _messages, *_args, **_kwargs):
        return ModelResponse(tool_calls=[{
            "id": "choices", "type": "function", "function": {
                "name": "report_workflow_start", "arguments": "{}",
            },
        }])

    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke", invoke)
    agent = Agent(
        model=ReportFacadeOpenAIChat(id="fixture", api_key="fixture"),
        tools=[ReportWorkflowToolkit(SimpleNamespace())], db=InMemoryDb(), telemetry=False,
    )
    return await agent.arun("生成报告", session_id=session_id)


@pytest.mark.anyio
async def test_report_option_wire_payload_keeps_dates_choices_and_optional_flags(monkeypatch):
    paused = await _pause_report_workflow_start(monkeypatch, "wire-payload")
    assert paused.status is RunStatus.paused
    tool = paused.active_requirements[0].tool_execution.to_dict()
    fields = {item["name"]: item for item in tool["user_input_schema"]}
    assert fields["period_start"]["format"] == "date"
    assert fields["period_end"]["format"] == "date"
    assert tuple(fields["domains"]["allowed_values"]) == DOMAIN_CODES
    assert fields["domains"]["required"] is False
    assert fields["report_length"]["allowed_values"] == ["brief", "detailed"]
    assert fields["report_length"]["value"] == "brief"
    assert fields["analysis_dimensions"]["required"] is False
    assert fields["analysis_dimensions"]["allowed_values"][:5] == ["院区", "科室", "类型", "病种", "项目"]


@pytest.mark.anyio
@pytest.mark.skipif(
    not _console_protocol_maps_option_schema(),
    reason="Console 表单协议需 dingyi-agno>=0.5.5 才支持 format/数组枚举；发布并升级 pin 后自动启用",
)
async def test_console_protocol_maps_report_options_to_form_schema(monkeypatch):
    from dingyi_agno.chat.protocol import tool_requirement_block

    paused = await _pause_report_workflow_start(monkeypatch, "choices")
    assert paused.status is RunStatus.paused
    tool = paused.active_requirements[0].tool_execution.to_dict()
    properties = tool_requirement_block(tool)["schema"]["properties"]
    assert properties["period_start"]["format"] == "date"
    assert properties["domains"]["type"] == "array"
    assert "workload" in properties["domains"]["items"]["enum"]
    assert properties["report_length"]["enum"] == ["brief", "detailed"]
    assert properties["report_length"]["default"] == "brief"
    assert properties["analysis_dimensions"]["type"] == "array"
    assert "院区" in properties["analysis_dimensions"]["items"]["enum"]
