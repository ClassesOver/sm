from types import SimpleNamespace

import pytest
from agno.run import RunContext

from agentos_dev import app
from agentos_dev.agent_control import AgentControlToolkit, build_agent_tools
from agentos_dev.coding.reporting.tests.workspace_fakes import service
from agentos_dev.coding.reporting.tools import build_report_worker_tools


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

    report_tools = build_report_worker_tools(
        workspace_service,
        app.coding_repository,
        run_context=SimpleNamespace(session_state=context.session_state, dependencies={}),
    )
    assert [tool.name for tool in report_tools] == ["workspace_coding"]
