import pytest
from agno.run import RunContext

from agentos_dev.agent_control import (
    AGENT_PLAN_STATE_KEY,
    AgentControlToolkit,
    validated_agent_plan,
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


def test_validated_agent_plan_rejects_untrusted_or_invalid_state():
    assert validated_agent_plan(
        {
            "plan": [
                {"step": "读取数据", "status": "completed"},
                {"step": "生成报表", "status": "in_progress"},
            ],
            "explanation": "已完成准备",
        }
    ) == {
        "plan": [
            {"step": "读取数据", "status": "completed"},
            {"step": "生成报表", "status": "in_progress"},
        ],
        "explanation": "已完成准备",
    }
    assert validated_agent_plan({"plan": [], "explanation": ""}) is None
    assert (
        validated_agent_plan(
            {
                "plan": [{"step": "snapshotId=secret", "status": "in_progress"}],
                "explanation": "",
            }
        )
        is None
    )
