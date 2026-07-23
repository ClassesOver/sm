import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from agno.agent import Agent
from agno.agent._tools import parse_tools
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team import TeamMode
from agno.tools.function import Function
from agno.utils.callables import resolve_callable_members

from agentos_dev import app
from agentos_dev.agents import ODOO_HOST_COMMAND_NAMES, TEAM_ROUTE_DEPENDENCY
from agentos_dev.instructions import (
    BUSINESS_COMMAND_INSTRUCTIONS,
    CORE_INSTRUCTIONS,
    FORM_EDIT_INSTRUCTIONS,
    LIST_VIEW_INSTRUCTIONS,
    NAVIGATION_INSTRUCTIONS,
    ODOO_COMMAND_INSTRUCTIONS,
    SELECTED_SKILL_INSTRUCTIONS,
    VIEW_CONTROL_INSTRUCTIONS,
    X2MANY_INSTRUCTIONS,
    build_agent_instructions,
    build_odoo_command_instructions,
    build_report_agent_instructions,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def odoo_contract():
    source = (REPO_ROOT / "agui_chat/models/agui_chat_config.py").read_text(encoding="utf-8")
    values = {}
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
    material = {
        "protocol": values["PROTOCOL"],
        "commands": values["HOST_COMMAND_NAMES"],
        "revision": values["COMMAND_CATALOG_REVISION"],
    }
    digest = hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return values, digest


def instruction_context(*tools, dependencies=None):
    return RunContext(
        run_id="run-1",
        session_id="thread-1",
        client_tools=[SimpleNamespace(name=name) for name in tools],
        dependencies=dependencies,
    )


def team_context(*tools, member_id=None, member_ids=None):
    if member_id is not None:
        dependencies = {TEAM_ROUTE_DEPENDENCY: {"memberId": member_id}}
    elif member_ids is not None:
        dependencies = {TEAM_ROUTE_DEPENDENCY: {"memberIds": member_ids}}
    else:
        dependencies = None
    return RunContext(
        run_id="run-1",
        session_id="thread-1",
        client_tools=[
            Function(
                name=name,
                description="客户端工具",
                parameters={"type": "object", "properties": {}},
                external_execution=True,
            )
            for name in tools
        ],
        dependencies=dependencies,
        session_state={},
    )


def test_agentos_contract_matches_odoo_source():
    values, digest = odoo_contract()
    assert values["COMMAND_CATALOG_REVISION"] == 16
    assert digest == "6529262bf0a1c05a61a1238c67415ed3734e0db58bc12dcd59cf6c534d2467f4"
    assert app.PROTOCOL == values["PROTOCOL"]
    assert app.BUNDLE_VERSION == values["MODULE_VERSION"]
    assert app.COMMAND_CATALOG_HASH == digest
    assert ODOO_HOST_COMMAND_NAMES == frozenset(values["HOST_COMMAND_NAMES"])


def test_agent_uses_dynamic_instructions_callable():
    assert app.assistant.instructions is build_agent_instructions
    assert app.odoo_command_assistant.instructions is build_odoo_command_instructions
    assert app.report_agent.instructions is build_report_agent_instructions


def test_assistant_team_routes_to_specialized_members():
    assert app.assistant.id == "general-assistant"
    assert app.odoo_command_assistant.id == "odoo-command-assistant"
    assert app.assistant_team.mode is TeamMode.route
    assert app.assistant_team.determine_input_for_members is False
    assert app.assistant_team.tool_choice == {
        "type": "function",
        "function": {"name": "delegate_task_to_member"},
    }
    all_members = [
        app.assistant,
        app.odoo_command_assistant,
        app.report_agent,
    ]
    assert callable(app.assistant_team.members)
    resolved = app.assistant_team.members(team_context())
    assert [member.id for member in resolved] == [member.id for member in all_members]
    assert all(
        member is not original for member, original in zip(resolved, all_members, strict=True)
    )
    for member in all_members:
        resolved = app.assistant_team.members(team_context(member_id=member.id))
        assert [current.id for current in resolved] == [member.id]
        assert resolved[0] is not member
    resolved = app.assistant_team.members(
        team_context(member_ids=[app.assistant.id, app.odoo_command_assistant.id])
    )
    assert [member.id for member in resolved] == [
        app.assistant.id,
        app.odoo_command_assistant.id,
    ]
    assert app.assistant_team.members(team_context(member_id="unknown")) == []
    assert app.assistant_team.id == "hrp-assistant-team"
    assert app.assistant_team.cache_callables is False
    assert "Python 编码" in app.report_agent.role


def test_team_members_bind_only_their_allowed_client_tools():
    context = team_context(
        "odoo.navigate_menu",
        "odoo.apply_filter",
        "odoo.export_current_view",
        "odoo.business.test.execute",
        "odoo.unknown_command",
        "custom.browser_tool",
    )

    members = {member.id: member for member in app.assistant_team.members(context)}

    assert context.client_tools is None
    assistant_tools = members[app.assistant.id].tools
    command_tools = members[app.odoo_command_assistant.id].tools
    report_tools = members[app.report_agent.id].tools
    assert [tool.name for tool in assistant_tools] == ["agent_control", "base"]
    assert {tool.name for tool in command_tools} == {
        "odoo.navigate_menu",
        "odoo.apply_filter",
        "odoo.export_current_view",
        "odoo.business.test.execute",
    }
    assert [tool.name for tool in report_tools[:-1]] == [
        "coding",
        "report_data_sources",
        "workspace_report",
    ]
    assert report_tools[-1].name == "odoo.export_current_view"
    assert "odoo.unknown_command" not in {tool.name for tool in command_tools}
    assert "custom.browser_tool" not in {tool.name for tool in command_tools}


def test_team_delegate_runs_command_member_with_only_odoo_commands(monkeypatch):
    calls = []

    def fake_run(member, *args, **kwargs):
        calls.append(
            (
                member.id,
                [tool.name for tool in member.tools or []],
            )
        )
        return RunOutput(
            run_id=kwargs["run_id"],
            session_id=kwargs["session_id"],
            agent_id=member.id,
            content="ok",
        )

    monkeypatch.setattr(Agent, "run", fake_run)
    context = team_context(
        "odoo.navigate_menu",
        "odoo.business.expense.submit",
        "odoo.unknown_command",
        "custom.browser_tool",
        member_ids=[app.assistant.id, app.odoo_command_assistant.id],
    )
    resolve_callable_members(app.assistant_team, context)
    delegate = app.assistant_team._get_delegate_task_function(
        TeamRunOutput(
            run_id=context.run_id,
            session_id=context.session_id,
            team_id=app.assistant_team.id,
        ),
        context,
        TeamSession(session_id=context.session_id, team_id=app.assistant_team.id),
        {},
        input="提交费用单",
    )

    result = list(
        delegate.entrypoint(
            member_id=app.odoo_command_assistant.id,
            task="提交费用单",
        )
    )

    assert result == ["ok"]
    assert calls == [
        (
            app.odoo_command_assistant.id,
            ["odoo.navigate_menu", "odoo.business.expense.submit"],
        )
    ]


def test_agent_history_runs_are_not_truncated():
    assert app.assistant.num_history_runs is None
    assert app.odoo_command_assistant.num_history_runs is None
    assert app.report_agent.num_history_runs is None


def test_agent_registers_main_and_report_toolkits_without_overlap():
    control_and_base = [
        {
            "agent_update_plan",
            "agent_context_status",
            "agent_prepare_continuation",
            "agent_tool_search",
            "agent_load_toolkit",
        },
        {
            "sandbox_exec",
            "sandbox_process_poll",
            "sandbox_process_write",
            "sandbox_process_interrupt",
            "sandbox_process_stop",
            "workspace_list_files",
            "workspace_read_file",
            "workspace_read_lines",
            "workspace_stat",
            "workspace_tree",
            "workspace_search_files",
            "workspace_search_text",
            "workspace_hash_file",
            "workspace_git_status",
            "workspace_git_diff",
            "workspace_git_log",
            "workspace_git_show",
            "workspace_write_file",
            "workspace_replace_file",
            "workspace_move_file",
            "workspace_apply_patch",
            "workspace_apply_patch_set",
            "workspace_apply_hunks",
            "workspace_apply_changes",
            "workspace_create_directory",
            "workspace_copy_file",
            "workspace_delete_file",
            "workspace_view_image",
            "workspace_inspect_pdf",
        },
    ]
    for assistant in (app.assistant,):
        toolkits = assistant.tools(
            run_context=RunContext(
                run_id="run",
                session_id="thread",
                session_state={"agentos_loaded_toolkits": ["report"]},
            )
        )
        assert assistant.cache_callables is False
        assert [toolkit.name for toolkit in toolkits] == ["agent_control", "base"]
        registered = [set(toolkit.functions) | set(toolkit.async_functions) for toolkit in toolkits]
        assert registered == control_and_base
        assert all(
            left.isdisjoint(right)
            for index, left in enumerate(registered)
            for right in registered[index + 1 :]
        )

    assert app.odoo_command_assistant.tools == []

    report_toolkits = app.report_agent.tools(
        run_context=RunContext(run_id="run", session_id="thread", session_state={})
    )
    assert [toolkit.name for toolkit in report_toolkits] == [
        "coding",
        "report_data_sources",
        "workspace_report",
    ]
    report_registered = [
        set(toolkit.functions) | set(toolkit.async_functions) for toolkit in report_toolkits
    ]
    coding_registered = report_registered[0]
    assert coding_registered == {
        "exec_command",
        "write_stdin",
        "apply_patch",
        "view_image",
        "update_plan",
    }
    assert report_registered[1] == {
        "report_list_data_sources",
        "report_describe_data_source",
        "report_materialize_dataset",
    }
    assert report_registered[2] == {
        "report_list_analysis_capabilities",
        "report_prepare_dataset",
        "report_profile_dataset",
        "report_job_status",
        "report_analyze_dataset",
        "report_render_markdown",
        "report_validate_pdf",
    }
    assert all(
        left.isdisjoint(right)
        for index, left in enumerate(report_registered)
        for right in report_registered[index + 1 :]
    )


def test_toolkit_instructions_are_injected_by_agno():
    coding_toolkit, data_source_toolkit, report_toolkit = app.report_agent.tools(
        run_context=RunContext(
            run_id="run",
            session_id="thread",
            session_state={"agentos_loaded_toolkits": ["report"]},
        )
    )

    assert coding_toolkit.add_instructions is True
    assert "exec_command" in coding_toolkit.instructions
    assert "apply_patch" in coding_toolkit.instructions
    assert "write_stdin" in coding_toolkit.instructions
    assert report_toolkit.add_instructions is True
    assert data_source_toolkit.add_instructions is True
    assert "同一 jobId 多轮调用 report_analyze_dataset" in report_toolkit.instructions
    assert "apply_patch" in report_toolkit.instructions
    assert "python3 <工作区相对脚本路径>" in report_toolkit.instructions
    assert "report_validate_pdf" in report_toolkit.instructions

    toolkits = [coding_toolkit, data_source_toolkit, report_toolkit]
    parsed = parse_tools(
        app.report_agent,
        toolkits,
        app.report_agent.model,
        run_context=instruction_context(),
        async_mode=True,
    )

    assert coding_toolkit.instructions in app.report_agent._tool_instructions
    assert data_source_toolkit.instructions in app.report_agent._tool_instructions
    assert report_toolkit.instructions in app.report_agent._tool_instructions
    parsed_tools = {function.name: function for function in parsed if hasattr(function, "name")}
    parsed_exec_schema = parsed_tools["exec_command"].parameters
    assert parsed_exec_schema["additionalProperties"] is False
    assert parsed_exec_schema["properties"]["cmd"]["minLength"] == 1
    assert parsed_exec_schema["properties"]["yield_time_ms"]["maximum"] == 30000
    parsed_patch_schema = parsed_tools["apply_patch"].parameters["properties"]
    assert parsed_patch_schema["patch"]["minLength"] == 1


def test_report_agent_instructions_support_iterative_python_scripts():
    instructions = "\n".join(build_report_agent_instructions(instruction_context()))

    assert "exec_command" in instructions
    assert "apply_patch" in instructions
    assert "write_stdin" in instructions
    assert "view_image" in instructions
    assert "python3 <工作区相对脚本路径>" in instructions
    assert "不得把裸 Python 代码直接作为 command" in instructions


def test_agent_long_running_tool_loop_is_checkpointed_and_retried():
    for assistant in (
        app.assistant,
        app.odoo_command_assistant,
        app.report_agent,
    ):
        assert assistant.checkpoint == "tool-batch"
        assert assistant.tool_call_limit is None
        assert assistant.retries == 0
        assert assistant.exponential_backoff is False
        assert assistant.model.retries == 2
        assert assistant.model.exponential_backoff is True
        assert assistant.model.extra_body["enable_thinking"] is True
        assert assistant.compression_manager.model.extra_body["enable_thinking"] is False
        assert assistant.session_summary_manager.model.extra_body["enable_thinking"] is False
        assert assistant.compression_manager.model.retries == 2
        assert assistant.session_summary_manager.model.retries == 2
        assert assistant.add_history_to_context is False
        assert assistant.compress_tool_results is True
        assert assistant.enable_session_summaries is True
        assert assistant.post_hooks


def test_plain_request_only_uses_core_instructions():
    assert build_agent_instructions(instruction_context()) == CORE_INSTRUCTIONS


def test_plain_command_request_only_uses_command_instructions():
    assert build_odoo_command_instructions(instruction_context()) == ODOO_COMMAND_INSTRUCTIONS


def test_navigation_tools_only_add_navigation_policy():
    instructions = build_odoo_command_instructions(instruction_context("odoo.navigate_menu"))

    assert instructions == ODOO_COMMAND_INSTRUCTIONS + NAVIGATION_INSTRUCTIONS
    assert not set(FORM_EDIT_INSTRUCTIONS) & set(instructions)
    assert "stage_current_form" not in "\n".join(instructions)
    assert "requiredFirstTool" not in "\n".join(instructions)


def test_list_view_tools_add_list_policy():
    instructions = build_odoo_command_instructions(instruction_context("odoo.apply_group"))
    text = "\n".join(instructions)

    assert instructions == ODOO_COMMAND_INSTRUCTIONS + LIST_VIEW_INSTRUCTIONS
    assert "viewType 为 list 或 kanban" in text
    assert "groupBy 是有序的完整目标状态" in text
    assert "切到 form 会进入空白新建表单" in text
    assert "当前 viewType 为 form 时禁止调用" in text


def test_discard_form_tool_adds_form_view_policy():
    instructions = build_odoo_command_instructions(instruction_context("odoo.discard_current_form"))

    assert instructions == ODOO_COMMAND_INSTRUCTIONS + FORM_EDIT_INSTRUCTIONS
    assert "viewType 为 form" in "\n".join(instructions)


def test_view_control_tools_add_ambiguous_navigation_policy():
    instructions = build_odoo_command_instructions(
        instruction_context("odoo.activate_view_control")
    )

    assert instructions == ODOO_COMMAND_INSTRUCTIONS + VIEW_CONTROL_INSTRUCTIONS
    text = "\n".join(instructions)
    assert "控件语义不明确或存在多个合理路径时停止并请用户选择" in text
    assert "不得猜测控件、目标模型、action 或记录" in text


def test_form_tools_add_staged_edit_policy_without_report_workflow():
    instructions = build_odoo_command_instructions(instruction_context("odoo.stage_current_form"))
    text = "\n".join(instructions)

    assert instructions == ODOO_COMMAND_INSTRUCTIONS + FORM_EDIT_INSTRUCTIONS
    assert "能力发现 → stage_current_form 暂存依赖标量" in text
    assert "独立确认后 save_current_form" in text
    assert "odoo-current-view-report" not in text
    assert "scripts/generate_reports.py" not in text


def test_x2many_business_and_selected_skill_policies_are_selected_independently():
    x2many = build_odoo_command_instructions(instruction_context("odoo.open_x2many_record"))
    business = build_odoo_command_instructions(instruction_context("odoo.business.test.execute"))
    selected_skill = build_agent_instructions(
        instruction_context(dependencies={"已选智能体技能": [{"name": "report"}]})
    )

    assert x2many == ODOO_COMMAND_INSTRUCTIONS + X2MANY_INSTRUCTIONS
    assert business == ODOO_COMMAND_INSTRUCTIONS + BUSINESS_COMMAND_INSTRUCTIONS
    assert selected_skill == CORE_INSTRUCTIONS + SELECTED_SKILL_INSTRUCTIONS


def test_instruction_character_budgets():
    core_length = len("\n".join(CORE_INSTRUCTIONS))
    scenario_lengths = [
        len("\n".join(ODOO_COMMAND_INSTRUCTIONS + policy))
        for policy in (
            NAVIGATION_INSTRUCTIONS,
            LIST_VIEW_INSTRUCTIONS,
            VIEW_CONTROL_INSTRUCTIONS,
            FORM_EDIT_INSTRUCTIONS,
            X2MANY_INSTRUCTIONS,
            BUSINESS_COMMAND_INSTRUCTIONS,
            SELECTED_SKILL_INSTRUCTIONS,
        )
    ]

    assert core_length <= 1500
    assert len("\n".join(ODOO_COMMAND_INSTRUCTIONS)) <= 1500
    assert max(scenario_lengths) <= 2200


def test_主智能体说明明确工作区确认边界():
    instructions = "\n".join(build_agent_instructions(instruction_context()))

    assert "工作区只属于当前 thread" in instructions
    assert "同一个 Daytona sandbox" in instructions
    assert "不是 AgentOS 宿主机" in instructions
    assert "独立的只读探查可在同一工具批次并行" in instructions
    assert "有数据依赖时串行" in instructions
    assert "修改前先读取并校验 SHA-256" in instructions
    assert "修改后重新读取或检查" in instructions
    assert "新建、覆盖、补丁、移动、删除" in instructions
    assert "sandbox_exec 须独立确认" in instructions
    assert "后台进程轮询" in instructions
    assert "sandbox_process_poll" in instructions
    assert "sandbox_exec 默认工作目录是 /home/daytona/workspace" in instructions
    assert "可信技能脚本" not in instructions


def test_报表智能体说明明确泛化数据源和验收链路():
    instructions = "\n".join(build_report_agent_instructions(instruction_context()))

    assert "独立的智能报表 Agent" in instructions
    assert "report_list_data_sources" in instructions
    assert "不可变 DatasetHandle" in instructions
    assert "具体分析命令和轮次由你" in instructions
    assert "至少一轮分析成功" in instructions
    assert "最终 job 状态为 validated" in instructions
    assert "只读 PostgreSQL" in instructions


def test_智能报表技能统一使用工作区相对路径和报表工具():
    skill = (REPO_ROOT / "deploy/agentos/skills/workspace-smart-report/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "相对 `/home/daytona/workspace` 的工作区路径" in skill
    assert "`report_list_analysis_capabilities`" in skill
    assert "`report_profile_dataset`" in skill
    assert "`exec_command` 检查相关文件" in skill
    assert "`apply_patch` 创建或修改任意 Python 脚本" in skill
    assert "`write_stdin` 轮询或输入" in skill
    assert "`view_image` 检查生成的图表" in skill
    assert "workspace_write_file" not in skill
    assert "workspace_apply_changes" not in skill
    assert "模型根据每轮结果自行决定轮数" in skill
    assert "若返回 `ok: false`" in skill
    assert "直到至少一轮返回 `ok: true`" in skill
    assert "`report_analyze_dataset` 无需确认" in skill
    assert "直接调用无需确认的 `report_render_markdown`" in skill
    assert "`report_validate_pdf`" in skill
    assert "状态为 `validated`" in skill
    assert "不使用 `report_compile`、`blocks`" in skill
