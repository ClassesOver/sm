from agno.run import RunContext

from agentos_dev import app
from agentos_dev.coding.agent import create_coding_agent, create_coding_facade_agent
from agentos_dev.coding.execution import is_coding_tool_scheduler_hook
from agentos_dev.coding.reporting.agent import create_report_agent, create_report_worker
from agentos_dev.coding.reporting.controller import ReportWorkflowController
from agentos_dev.coding.reporting.tests.workspace_fakes import service
from agentos_dev.instructions import build_pure_coding_agent_instructions
from agentos_dev.skills import SkillValidatorRegistry, is_skill_script_hook


def test_report_agent_facade_wraps_unregistered_report_worker(tmp_path):
    workspace_service = service(tmp_path)
    coding_agent = create_coding_agent(
        app.assistant,
        workspace_service,
        app.coding_repository,
    )
    coding_facade = create_coding_facade_agent(
        coding_agent,
        app.coding_supervisor,
        workspace_service,
    )
    report_worker = create_report_worker(
        coding_agent,
        workspace_service,
        app.coding_repository,
        instructions=["测试报表"],
    )
    report_agent = create_report_agent(
        report_worker,
        ReportWorkflowController(lambda: None),
    )

    assert coding_agent.id == "coding-agent"
    assert coding_facade is not coding_agent
    assert coding_facade.id == coding_agent.id
    assert coding_facade.model is not coding_agent.model
    assert coding_facade.model.id == coding_agent.model.id
    assert coding_facade.model.extra_body == {"enable_thinking": False}
    assert coding_facade.model.reasoning_effort is None
    assert coding_agent.model.reasoning_effort == "medium"
    assert coding_agent.model.get_request_params()["reasoning_effort"] == "medium"
    assert coding_agent.model.extra_body == app.assistant.model.extra_body
    assert [tool.name for tool in coding_facade.tools] == ["run_coding_task"]
    assert coding_facade.tools[0].parameters == {
        "type": "object",
        "properties": {"instruction": {"type": "string", "minLength": 1}},
        "required": ["instruction"],
        "additionalProperties": False,
    }
    assert not any(is_skill_script_hook(hook) for hook in coding_facade.tool_hooks or [])
    assert not any(is_coding_tool_scheduler_hook(hook) for hook in coding_facade.tool_hooks or [])
    assert coding_agent.instructions is build_pure_coding_agent_instructions
    assert sum(is_skill_script_hook(hook) for hook in coding_agent.tool_hooks) == 1
    assert sum(is_coding_tool_scheduler_hook(hook) for hook in coding_agent.tool_hooks) == 1
    assert [skill.name for skill in coding_agent.skills.get_all_skills()] == ["sandbox-tooling"]
    assert coding_agent.id not in {member.id for member in app.assistant_team.members}
    assert report_worker.id == "report-worker"
    assert report_agent.id == "report-agent"
    assert report_agent.model is not report_worker.model
    assert report_agent.model.extra_body == {"enable_thinking": False}
    assert report_agent.model.request_params == {"parallel_tool_calls": True}
    assert app.assistant.model.request_params is None
    assert sum(is_coding_tool_scheduler_hook(hook) for hook in report_worker.tool_hooks) == 1
    assert not any(is_coding_tool_scheduler_hook(hook) for hook in report_agent.tool_hooks or [])
    assert report_worker.db is coding_agent.db
    assert report_agent.db is report_worker.db
    assert report_worker.checkpoint == coding_agent.checkpoint == "tool-batch"
    assert report_agent.skills is None
    run_context = RunContext(run_id="run", session_id="thread", user_id="user")
    coding_tools = coding_agent.tools(run_context=run_context)
    worker_tools = report_worker.tools(run_context=run_context)
    report_tools = report_agent.tools(run_context=run_context)
    assert [tool.name for tool in coding_tools] == ["workspace_coding"]
    assert [tool.name for tool in worker_tools] == ["workspace_coding"]
    assert [tool.name for tool in report_tools] == ["report_workflow"]
    assert set(report_tools[0].async_functions) == {
        "report_workflow_start",
        "report_workflow_select_agent",
        "report_workflow_approve",
        "report_workflow_reject",
        "report_workflow_cancel",
    }
    expected_validators = SkillValidatorRegistry.from_skills(coding_agent.skills)
    assert app.coding_supervisor.validator_registry.script_sha256() == (
        expected_validators.script_sha256()
    )
