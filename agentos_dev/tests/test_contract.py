import ast
import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agno.agent._tools import parse_tools
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.openai import OpenAIChat
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.base import RunStatus
from agno.team import TeamMode
from agno.tools.function import Function

from agentos_dev import agents as agents_module
from agentos_dev import app
from agentos_dev.agents import (
    ODOO_HOST_COMMAND_NAMES,
    OPENAI_COMPATIBLE_ROLE_MAP,
    create_assistant_team,
)
from agentos_dev.agents.assistant import create_assistant
from agentos_dev.coding.reporting.instructions import (
    build_report_agent_instructions,
)
from agentos_dev.context_management import ContextBudgetController, ProjectedOpenAIChat
from agentos_dev.instructions import (
    BUSINESS_COMMAND_INSTRUCTIONS,
    CORE_INSTRUCTIONS,
    FORM_EDIT_INSTRUCTIONS,
    LIST_VIEW_INSTRUCTIONS,
    NAVIGATION_INSTRUCTIONS,
    ODOO_COMMAND_INSTRUCTIONS,
    PURE_CODING_PARALLEL_READ_INSTRUCTIONS,
    SELECTED_SKILL_INSTRUCTIONS,
    VIEW_CONTROL_INSTRUCTIONS,
    X2MANY_INSTRUCTIONS,
    build_agent_instructions,
    build_coding_agent_instructions,
    build_odoo_command_instructions,
    build_pure_coding_agent_instructions,
)
from agentos_dev.settings import AgentSettings
from agentos_dev.task_execution.execution import is_coding_tool_scheduler_hook

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


def team_context(*tools):
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
        session_state={},
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
    assert callable(app.assistant_team.instructions)
    assert "每轮最多跟进四次客户端页面工具" in "\n".join(
        app.assistant_team.instructions(team_context("odoo.navigate_menu"))
    )
    assert "不得向用户输出内部推理、执行计划" in "\n".join(
        app.assistant_team.instructions(team_context("odoo.navigate_menu"))
    )
    assert app.coding_agent.instructions is build_pure_coding_agent_instructions
    assert app.report_worker.instructions is build_report_agent_instructions
    assert "report_workflow_start" in "\n".join(app.report_agent.instructions)


def test_openai_compatible_role_map_preserves_system_instructions():
    assert OPENAI_COMPATIBLE_ROLE_MAP["system"] == "system"


def test_assistant_models_receive_configured_timeout(monkeypatch):
    configured = AgentSettings.from_environment(
        {
            "AGENT_MODEL_TIMEOUT_SECONDS": "123",
            "AGENT_ASSISTANT_ENABLE_THINKING": "true",
        },
        load_env_file=False,
    )
    captured = {}
    assistant = object()

    def capture_create_assistant(*args):
        captured["models"] = args[4:7]
        return assistant

    monkeypatch.setattr(agents_module, "create_assistant", capture_create_assistant)

    result = agents_module.create_assistants(
        configured,
        None,
        object(),
        [],
        SimpleNamespace(async_db=object()),
    )

    assert result is assistant
    assert [model.timeout for model in captured["models"]] == [123, 123, 123]
    assert [model.max_retries for model in captured["models"]] == [0, 0, 0]
    assert [model.extra_body for model in captured["models"]] == [
        {"enable_thinking": True},
        {"enable_thinking": False},
        {"enable_thinking": False},
    ]


def test_production_assistant_debug_mode_is_independent_from_thinking():
    settings = AgentSettings.from_environment(
        {
            "AGENT_DEBUG": "true",
            "AGENT_ASSISTANT_ENABLE_THINKING": "true",
            "AGENT_ENABLE_TOOL_RESULT_COMPRESSION": "false",
            "AGENT_ENABLE_SESSION_SUMMARIES": "false",
        },
        load_env_file=False,
    )
    model = OpenAIChat(id="test-model", api_key="test-key", extra_body={"enable_thinking": True})
    assistant = create_assistant(
        settings,
        None,
        object(),  # type: ignore[arg-type]
        [],
        model,
        model,
        model,
        None,  # type: ignore[arg-type]
    )
    team = create_assistant_team(assistant, lambda _run_context: [])

    assert assistant.debug_mode is True
    assert team.debug_mode is True
    assert team.model.extra_body == {"enable_thinking": True}


def test_coding_agent_uses_trusted_per_run_instructions():
    instructions = build_coding_agent_instructions(instruction_context())
    text = "\n".join(instructions)
    resumed = build_coding_agent_instructions(
        RunContext(
            run_id="run-1",
            session_id="thread-1",
            session_state={
                "agentos_plan": {
                    "plan": [
                        {"step": "检查现状", "status": "completed"},
                        {"step": "运行验证", "status": "in_progress"},
                    ],
                    "explanation": "已完成代码检查",
                },
                "odoo": {"snapshotId": "不得注入"},
            },
        )
    )
    invalid = build_coding_agent_instructions(
        RunContext(
            run_id="run-1",
            session_id="thread-1",
            session_state={
                "agentos_plan": {
                    "plan": [{"step": "snapshotId=secret", "status": "in_progress"}],
                    "explanation": "",
                }
            },
        )
    )

    assert "当前可用工具、其 schema、确认要求" in text
    assert "生产 Coding Toolkit 声明的工具全部不要求确认" in text
    assert "受控只读工具" in text
    assert "普通 terminal 不计为验证" in text
    assert "确认缺失后再安装" in text
    assert "不要扫描或输出完整环境清单" in text
    assert "网络由 sandbox 策略决定" in text
    assert "不得改用标准库或其他框架冒充完成" in text
    assert "禁止用 shell 后台 &" in text
    assert "不得用 sed -i" in text
    assert "不是 OS PID" in text
    assert "只围绕 failedRequirements 定位和修复" in text
    assert "保护 passedRequirements 已通过行为" in text
    assert "只有 finish_task 返回 accepted 才能结束任务" in text
    assert "不得因中间验证或上下文压缩重置计划" in text
    assert "当前会话没有可复用的任务计划" in text
    resumed_text = "\n".join(resumed)
    assert "当前会话保存了以下服务端任务计划" in resumed_text
    assert "检查现状" in resumed_text
    assert "运行验证" in resumed_text
    assert "已完成代码检查" in resumed_text
    assert "snapshotId" not in resumed_text
    assert "当前会话没有可复用的任务计划" in "\n".join(invalid)


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


def test_assistant_team_has_one_static_production_member():
    assert app.assistant.id == "general-assistant"
    assert app.assistant_team.mode is TeamMode.coordinate
    assert app.assistant_team.determine_input_for_members is False
    assert app.assistant_team.tool_choice == "auto"
    assert app.assistant_team.model.id == app.assistant.model.id
    assert app.assistant_team.model is not app.assistant.model
    assert app.assistant_team.model.extra_body == {"enable_thinking": False}
    assert app.assistant_team.members == [app.assistant]
    assert app.assistant_team.id == "hrp-assistant-team"
    assert app.assistant_team.cache_callables is False
    assert app.coding_agent not in app.assistant_team.members
    assert app.report_agent not in app.assistant_team.members


def test_odoo_client_tools_remain_on_team_run_context():
    context = team_context(
        "odoo.navigate_menu",
        "odoo.apply_filter",
        "odoo.export_current_view",
        "odoo.business.test.execute",
    )

    instructions = app.assistant_team.instructions(context)

    assert {tool.name for tool in context.client_tools or []} == {
        "odoo.navigate_menu",
        "odoo.apply_filter",
        "odoo.export_current_view",
        "odoo.business.test.execute",
    }
    assert "调用 odoo.navigate_menu" in "\n".join(instructions)


@pytest.mark.anyio
async def test_team_top_level_client_tool_pauses_and_continues_same_run():
    model = ScriptedModel(
        id="scripted-team-model",
        responses=[
            ModelResponse(
                tool_calls=[
                    {
                        "id": "call-navigation",
                        "type": "function",
                        "function": {
                            "name": "odoo.navigate_menu",
                            "arguments": json.dumps({"query": "入口看板"}),
                        },
                    }
                ]
            ),
            ModelResponse(content="已打开入口看板。"),
        ],
    )
    database = InMemoryDb()
    team = app.assistant_team.deep_copy(
        update={
            "model": model,
            "db": database,
            "enable_session_summaries": False,
            "session_summary_manager": None,
            "compress_tool_results": False,
            "compression_manager": None,
            "post_hooks": [],
            "telemetry": False,
        }
    )
    context = RunContext(
        run_id="run-navigation",
        session_id="thread-navigation",
        session_state={},
        client_tools=[
            Function(
                name="odoo.navigate_menu",
                description="打开 Odoo 菜单",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                external_execution=True,
            )
        ],
    )

    paused = await asyncio.wait_for(
        team.arun(
            "打开入口看板",
            run_id=context.run_id,
            session_id=context.session_id,
            run_context=context,
        ),
        timeout=10,
    )

    assert paused.status is RunStatus.paused
    assert paused.run_id == "run-navigation"
    assert len(paused.requirements or []) == 1
    requirement = paused.requirements[0]
    assert requirement.member_agent_id is None
    assert requirement.tool_execution.tool_name == "odoo.navigate_menu"
    requirement.set_external_execution_result('{"ok":true}')

    completed = await asyncio.wait_for(
        team.acontinue_run(
            run_id=paused.run_id,
            session_id=paused.session_id,
            requirements=paused.requirements,
            run_context=context,
        ),
        timeout=10,
    )

    assert completed.status is RunStatus.completed
    assert completed.run_id == paused.run_id
    assert completed.content == "已打开入口看板。"
    assert len(model.calls) == 2
    assert (
        len(
            [
                tool
                for call in model.calls
                for tool in call.get("tools") or []
                if tool.get("function", {}).get("name") == "odoo.navigate_menu"
            ]
        )
        == 2
    )


@pytest.mark.anyio
async def test_team_does_not_call_declared_odoo_tool_for_plain_question():
    model = ScriptedModel(
        id="scripted-plain-model",
        responses=[ModelResponse(content="你好，我可以直接回答普通问题。")],
    )
    database = InMemoryDb()
    team = app.assistant_team.deep_copy(
        update={
            "model": model,
            "db": database,
            "enable_session_summaries": False,
            "session_summary_manager": None,
            "compress_tool_results": False,
            "compression_manager": None,
            "post_hooks": [],
            "telemetry": False,
        }
    )
    context = team_context("odoo.navigate_menu")

    completed = await asyncio.wait_for(
        team.arun(
            "你好",
            run_id=context.run_id,
            session_id=context.session_id,
            run_context=context,
        ),
        timeout=10,
    )

    assert completed.status is RunStatus.completed
    assert completed.content == "你好，我可以直接回答普通问题。"
    assert completed.requirements is None
    assert len(model.calls) == 1
    assert any(
        tool.get("function", {}).get("name") == "odoo.navigate_menu"
        for tool in model.calls[0].get("tools") or []
    )


def test_agent_history_runs_are_not_truncated():
    assert app.assistant.num_history_runs is None
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

    report_toolkits = app.report_agent.tools(
        run_context=RunContext(run_id="run", session_id="thread", session_state={})
    )
    assert [toolkit.name for toolkit in report_toolkits] == ["report_workflow"]
    report_registered = [
        set(toolkit.functions) | set(toolkit.async_functions) for toolkit in report_toolkits
    ]
    assert report_registered == [
        {
            "report_workflow_start",
            "report_workflow_start_from_prompt",
            "report_workflow_select_agent",
            "report_workflow_approve",
            "report_workflow_reject",
            "report_workflow_cancel",
        }
    ]
    assert (
        report_toolkits[0].async_functions["report_workflow_approve"].requires_confirmation is True
    )
    assert all(
        report_toolkits[0].async_functions[name].requires_confirmation is False
        for name in (
            "report_workflow_start",
            "report_workflow_start_from_prompt",
            "report_workflow_select_agent",
            "report_workflow_reject",
            "report_workflow_cancel",
        )
    )
    worker_toolkits = app.report_worker.tools(
        run_context=RunContext(run_id="run", session_id="thread", session_state={})
    )
    assert [toolkit.name for toolkit in worker_toolkits] == ["workspace_coding"]
    assert set(worker_toolkits[0].functions) | set(worker_toolkits[0].async_functions) == {
        "terminal",
        "process",
        "create_files",
        "overwrite_file",
        "replace_text",
        "apply_patch",
        "verify",
        "list_files",
        "read_file",
        "read_lines",
        "search_text",
        "tree",
        "git_status",
        "git_diff",
        "read_tool_output",
        "update_plan",
        "finish_task",
    }


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
        "report_workflow_start_from_prompt",
        "report_workflow_select_agent",
        "report_workflow_approve",
        "report_workflow_reject",
        "report_workflow_cancel",
    }
    assert parsed_tools["report_workflow_approve"].requires_confirmation is True
    assert set(parsed_tools["report_workflow_start_from_prompt"].parameters["properties"]) == {
        "prompt"
    }


def test_team_and_internal_workers_keep_separate_execution_settings():
    for assistant in (
        app.assistant,
        app.coding_agent,
        app.report_worker,
    ):
        assert assistant.tool_call_limit is None
        assert assistant.retries == 0
        assert assistant.exponential_backoff is False
        assert assistant.model.retries == 2
        assert assistant.model.exponential_backoff is True
        if assistant is app.report_worker:
            assert isinstance(app.coding_agent.model, ProjectedOpenAIChat)
            assert isinstance(assistant.model, ProjectedOpenAIChat)
            assert isinstance(assistant.compression_manager, ContextBudgetController)
            assert assistant.compression_manager.model is assistant.model
        elif assistant is app.assistant:
            assert assistant.compression_manager.model.extra_body["enable_thinking"] is False
        assert assistant.session_summary_manager.model.extra_body["enable_thinking"] is False
        assert assistant.compression_manager.model.retries == 2
        assert assistant.session_summary_manager.model.retries == 2
        assert assistant.add_history_to_context is False
        assert assistant.compress_tool_results is True
        assert assistant.enable_session_summaries is True
        assert assistant.post_hooks
    assert app.assistant.checkpoint == "runs"
    assert app.assistant.model.extra_body["enable_thinking"] is False
    assert app.assistant_team.checkpoint == "runs"
    assert app.assistant_team.tool_choice == "auto"
    assert app.assistant_team.model.extra_body["enable_thinking"] is False
    for worker in (app.coding_agent, app.report_worker):
        assert worker.checkpoint == "tool-batch"
    assert (
        app.coding_agent.model.extra_body["enable_thinking"] is app.settings.coding_enable_thinking
    )
    assert (
        app.report_worker.model.extra_body["enable_thinking"]
        is app.settings.report_coding_enable_thinking
    )
    assert (
        app.report_runtime._analysis_agent.model.extra_body["enable_thinking"]
        is app.settings.report_enable_thinking
    )
    assert app.report_agent.model.extra_body["enable_thinking"] is False
    assert not any(
        is_coding_tool_scheduler_hook(hook) for hook in app.report_agent.tool_hooks or []
    )


def test_plain_request_only_uses_core_instructions():
    assert build_agent_instructions(instruction_context()) == CORE_INSTRUCTIONS


def test_plain_command_request_only_uses_command_instructions():
    assert build_odoo_command_instructions(instruction_context()) == ODOO_COMMAND_INSTRUCTIONS
    assert "页面操作必须通过对应工具调用实现，不能用文字代替执行" in "\n".join(
        ODOO_COMMAND_INSTRUCTIONS
    )


def test_navigation_tools_only_add_navigation_policy():
    instructions = build_odoo_command_instructions(instruction_context("odoo.navigate_menu"))

    assert instructions == ODOO_COMMAND_INSTRUCTIONS + NAVIGATION_INSTRUCTIONS
    assert not set(FORM_EDIT_INSTRUCTIONS) & set(instructions)
    assert "stage_current_form" not in "\n".join(instructions)
    assert "requiredFirstTool" not in "\n".join(instructions)
    assert "本轮必须直接调用 odoo.navigate_menu" in "\n".join(instructions)
    assert "不得在调用前输出说明、计划或确认文字" in "\n".join(instructions)
    assert "允许调用前简短说明" not in "\n".join(instructions)
    assert "不得用文字代替调用" in "\n".join(instructions)
    assert "输入包含多个序号时不得调用工具或自行取舍" in "\n".join(instructions)


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
