from types import SimpleNamespace

import pytest
from agno.models.message import Message
from agno.run import RunContext

from agentos_dev.agent_control import (
    AGENT_CONTEXT_STATUS_DEPENDENCY,
    AGENT_CONTINUATION_STATE_KEY,
    AGENT_PLAN_STATE_KEY,
    AgentControlToolkit,
    build_agent_tools,
    build_report_agent_tools,
)
from agentos_dev.tests.workspace_fakes import service


def test_agent_update_plan_only_changes_reserved_plan_state(tmp_path):
    toolkit = AgentControlToolkit(service(tmp_path))
    context = RunContext(
        run_id="run",
        session_id="thread",
        session_state={"odoo": {"snapshotId": "authoritative"}},
    )

    result = toolkit.agent_update_plan(
        plan=[
            {"step": "读取数据", "status": "completed"},
            {"step": "生成报表", "status": "in_progress"},
        ],
        explanation="已完成数据准备",
        run_context=context,
    )

    assert result["ok"] is True
    assert context.session_state["odoo"] == {"snapshotId": "authoritative"}
    assert context.session_state[AGENT_PLAN_STATE_KEY]["plan"][1]["status"] == "in_progress"


def test_agent_update_plan_rejects_multiple_active_steps(tmp_path):
    toolkit = AgentControlToolkit(service(tmp_path))

    with pytest.raises(ValueError, match="最多只能有一个"):
        toolkit.agent_update_plan(
            plan=[
                {"step": "第一步", "status": "in_progress"},
                {"step": "第二步", "status": "in_progress"},
            ],
            run_context=RunContext(run_id="run", session_id="thread", session_state={}),
        )


class CountingModel:
    def count_tokens(self, messages, tools=None, output_schema=None):
        return sum(len(str(message.content)) for message in messages) + len(tools or []) * 10


def test_agent_context_status_returns_full_context_estimate_without_business_data(tmp_path):
    toolkit = AgentControlToolkit(
        service(tmp_path),
        model=CountingModel(),
        context_token_budget=262144,
        output_token_reserve=32768,
    )
    context = RunContext(
        run_id="run",
        session_id="thread",
        dependencies={
            AGENT_CONTEXT_STATUS_DEPENDENCY: {
                "historyTokenBudget": 65536,
                "historyTokensUsed": 120,
                "historyTokensRemaining": 65416,
                "summaryIncluded": True,
                "tokenCountReliable": True,
            },
            "宿主": {"snapshotId": "secret"},
        },
        messages=[Message(role="user", content="当前请求")],
        tools=[],
    )

    result = toolkit.agent_context_status(run_context=context)

    assert result["historyTokensUsed"] == 120
    assert "snapshotId" not in str(result)
    assert result["contextTokenBudget"] == 262144
    assert result["outputReserveTokens"] == 32768
    assert result["estimatedTokensUsed"] == 4
    assert result["estimatedTokensRemaining"] == 229372
    assert result["scope"] == "full_context_estimate"
    assert result["tokenCountReliable"] is True


def test_agent_prepare_continuation_only_stores_sanitized_handoff(tmp_path):
    toolkit = AgentControlToolkit(service(tmp_path))
    context = RunContext(
        run_id="run",
        session_id="thread",
        session_state={"odoo": {"snapshotId": "authoritative"}},
    )

    result = toolkit.agent_prepare_continuation(
        summary="已完成收入数据剖析",
        pending_steps=["生成 Markdown", "渲染并验收 PDF"],
        artifact_paths=["报表/分析.json"],
        run_context=context,
    )

    assert result["ok"] is True
    assert result["appliesFrom"] == "next_run"
    assert context.session_state["odoo"] == {"snapshotId": "authoritative"}
    assert context.session_state[AGENT_CONTINUATION_STATE_KEY]["sourceRunId"] == "run"

    with pytest.raises(ValueError, match="Odoo"):
        toolkit.agent_prepare_continuation(
            summary="snapshotId=secret",
            pending_steps=["继续"],
            run_context=context,
        )

    with pytest.raises(ValueError, match="Odoo"):
        toolkit.agent_prepare_continuation(
            summary='{"token":"secret"}',
            pending_steps=["继续"],
            run_context=context,
        )


def test_report_toolkit_is_discoverable_but_requires_skill_route(tmp_path):
    workspace_service = service(tmp_path)
    toolkit = AgentControlToolkit(workspace_service)
    context = RunContext(run_id="run", session_id="thread", session_state={})

    found = toolkit.agent_tool_search("报表", run_context=context)

    assert found["matches"][0]["name"] == "report"
    assert found["matches"][0]["routeSkill"] == "workspace-smart-report"
    with pytest.raises(ValueError, match="workspace-smart-report Skill"):
        toolkit.agent_load_toolkit("report", run_context=context)
    assert "agentos_loaded_toolkits" not in context.session_state

    tools = build_agent_tools(
        workspace_service,
        run_context=SimpleNamespace(session_state=context.session_state, dependencies={}),
    )
    assert [tool.name for tool in tools] == ["agent_control", "base"]

    report_tools = build_report_agent_tools(
        workspace_service,
        run_context=SimpleNamespace(session_state=context.session_state, dependencies={}),
    )
    assert [tool.name for tool in report_tools] == [
        "agent_control",
        "base",
        "report_data_sources",
        "workspace_report",
    ]


def test_tool_factory_injects_model_budget_and_continuation(tmp_path):
    model = CountingModel()
    handoff = {
        "summary": "已完成剖析",
        "pendingSteps": ["生成 PDF"],
        "artifactPaths": ["报表/分析.json"],
    }

    tools = build_agent_tools(
        service(tmp_path),
        run_context=SimpleNamespace(
            session_state={AGENT_CONTINUATION_STATE_KEY: handoff},
            dependencies={},
        ),
        agent=SimpleNamespace(model=model),
        context_token_budget=262144,
        output_token_reserve=32768,
    )

    control = tools[0]
    assert isinstance(control, AgentControlToolkit)
    assert control.model is model
    assert control.context_token_budget == 262144
    assert "已完成剖析" in control.instructions
