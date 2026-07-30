from agno.run import RunContext

from agentos_dev import app
from agentos_dev.coding.agent import create_coding_agent, create_coding_facade_agent
from agentos_dev.coding.execution import is_coding_tool_scheduler_hook
from agentos_dev.coding.reporting.agent import create_report_agent, create_report_worker
from agentos_dev.coding.reporting.controller import ReportWorkflowController
from agentos_dev.coding.reporting.runtime import (
    AnalysisBundle,
    DataUnderstandingPlan,
    GeneratedQueryBatch,
    ReportOutline,
    ReportWorkflowRuntime,
)
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
        coding_enable_thinking=False,
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
    assert coding_agent.use_instruction_tags is True
    assert sum(is_skill_script_hook(hook) for hook in coding_agent.tool_hooks) == 1
    assert sum(is_coding_tool_scheduler_hook(hook) for hook in coding_agent.tool_hooks) == 1
    assert [skill.name for skill in coding_agent.skills.get_all_skills()] == ["sandbox-tooling"]
    assert coding_agent.id not in {member.id for member in app.assistant_team.members}
    assert report_worker.id == "report-worker"
    assert [skill.name for skill in report_worker.skills.get_all_skills()] == [
        "sandbox-tooling",
        "report-artifact",
    ]
    assert report_worker.use_instruction_tags is True
    assert report_worker.send_media_to_model is False
    assert report_worker.model is not coding_agent.model
    assert report_worker.model.extra_body["enable_thinking"] is False
    assert coding_agent.model.extra_body == app.assistant.model.extra_body
    assert report_agent.id == "report-agent"
    assert report_agent.model is not report_worker.model
    assert report_agent.model.extra_body == {"enable_thinking": False}
    assert report_worker.compression_manager.model is report_worker.model
    assert report_agent.compression_manager.model is report_agent.model
    assert report_worker.compression_manager is not coding_agent.compression_manager
    assert report_agent.compression_manager is not report_worker.compression_manager
    assert report_agent.compression_manager.stats is not report_worker.compression_manager.stats
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
    worker_tools_without_injected_context = report_worker.tools()
    report_tools = report_agent.tools(run_context=run_context)
    report_tools_without_injected_context = report_agent.tools()
    assert [tool.name for tool in coding_tools] == ["workspace_coding"]
    assert [tool.name for tool in worker_tools] == ["workspace_coding"]
    assert [tool.name for tool in worker_tools_without_injected_context] == ["workspace_coding"]
    assert "view_image" not in worker_tools[0].async_functions
    assert "view_image" not in worker_tools_without_injected_context[0].async_functions
    assert worker_tools[0].kernel.validator_registry.script_sha256().keys() == {
        "report-artifact:manifest"
    }
    assert coding_tools[0].kernel.validator_registry.script_sha256() == {}
    assert [tool.name for tool in report_tools] == ["report_workflow"]
    assert [tool.name for tool in report_tools_without_injected_context] == ["report_workflow"]
    assert set(report_tools[0].async_functions) == {
        "report_workflow_start",
        "report_workflow_start_from_text",
        "report_workflow_select_agent",
        "report_workflow_approve",
        "report_workflow_reject",
        "report_workflow_cancel",
    }
    expected_validators = SkillValidatorRegistry.from_skills(coding_agent.skills)
    assert app.coding_supervisor.validator_registry.script_sha256() == (
        expected_validators.script_sha256()
    )


def test_report_worker_exposes_image_tool_only_when_vision_is_enabled(tmp_path):
    workspace_service = service(tmp_path)
    coding_agent = create_coding_agent(
        app.assistant,
        workspace_service,
        app.coding_repository,
    )

    report_worker = create_report_worker(
        coding_agent,
        workspace_service,
        app.coding_repository,
        instructions=["测试报表"],
        report_enable_vision=True,
    )

    assert report_worker.send_media_to_model is True
    assert "view_image" in report_worker.tools()[0].async_functions


def test_report_planner_uses_report_thinking_without_mutating_coding_worker():
    stage_instructions = (
        "优先选择可直接验证的日期字段。",
        "优先生成单表 requirement。",
    )
    planner = ReportWorkflowRuntime._planning_agent(
        app.report_worker,
        "report-test-planner",
        DataUnderstandingPlan,
        enable_thinking=app.settings.report_enable_thinking,
        stage_instructions=stage_instructions,
    )

    assert planner.model is not app.report_worker.model
    assert planner.model.extra_body["enable_thinking"] is app.settings.report_enable_thinking
    assert planner.model.reasoning_effort is None
    assert planner.model.timeout == app.settings.model_timeout_seconds
    assert planner.parse_response is False
    assert any("不得写占位符" in instruction for instruction in planner.instructions)
    assert any("不得把 correction" in instruction for instruction in planner.instructions)
    assert all(instruction in planner.instructions for instruction in stage_instructions)
    assert (
        app.report_worker.model.extra_body["enable_thinking"] is app.settings.coding_enable_thinking
    )
    assert any(
        "非聚合 SELECT 列和 GROUP BY 列必须逐项等于 grainColumns" in instruction
        for instruction in app.report_runtime._sql_agent.instructions
    )


def test_report_planners_expose_compact_schema_in_stable_instructions():
    expected_fields = {
        DataUnderstandingPlan: ("tables", "periodColumn", "periodGranularity"),
        ReportOutline: ("title", "sections", "assumptions"),
        AnalysisBundle: ("analyses", "requirements", "requirementIds"),
        GeneratedQueryBatch: ("queries", "requirementId", "sourceId"),
    }

    for output_schema, field_names in expected_fields.items():
        planner = ReportWorkflowRuntime._planning_agent(
            app.report_worker,
            f"report-{output_schema.__name__}-test-planner",
            output_schema,
            enable_thinking=False,
        )
        contract_instruction = next(
            instruction
            for instruction in planner.instructions
            if instruction.startswith("实际输出契约：")
        )

        assert all(f'"{field_name}"' in contract_instruction for field_name in field_names)
        assert '"required"' in contract_instruction
        assert '"description":"' not in contract_instruction
        assert '"title":"' not in contract_instruction
