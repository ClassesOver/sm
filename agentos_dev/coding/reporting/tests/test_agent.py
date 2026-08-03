import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agno.exceptions import StopAgentRun
from agno.models.message import Message
from agno.run import RunContext

from agentos_dev import app
from agentos_dev.coding.agent import create_coding_agent, create_coding_facade_agent
from agentos_dev.coding.reporting.agent import (
    ReportFacadeOpenAIChat,
    ReportWorkerOpenAIChat,
    _report_facade_model,
    _report_model,
    _report_worker_model,
    create_report_agent,
    create_report_worker,
    normalize_reporting_tool_arguments,
)
from agentos_dev.coding.reporting.controller import ReportWorkflowController
from agentos_dev.coding.reporting.runtime import (
    AnalysisBundle,
    DataUnderstandingPlan,
    GeneratedQueryBatch,
    ReportOutline,
    ReportWorkflowRuntime,
)
from agentos_dev.coding.reporting.tests.workspace_fakes import service
from agentos_dev.context_management import ProjectedOpenAIChat
from agentos_dev.instructions import build_pure_coding_agent_instructions
from agentos_dev.skills import SkillValidatorRegistry, is_skill_script_hook
from agentos_dev.task_execution.execution import is_coding_tool_scheduler_hook


def test_reporting_model仅为siliconflow按完成chunk采集累计usage():
    siliconflow = _report_model(
        replace(app.settings, openai_base_url="https://api.siliconflow.cn/v1"),
        enable_thinking=False,
    )
    standard = _report_model(
        replace(app.settings, openai_base_url="https://api.openai.com/v1"),
        enable_thinking=False,
    )

    intermediate = SimpleNamespace(usage=object(), choices=[SimpleNamespace(finish_reason=None)])
    completed = SimpleNamespace(
        usage=object(), choices=[SimpleNamespace(finish_reason="tool_calls")]
    )
    trailing = SimpleNamespace(usage=object(), choices=[])

    assert siliconflow.collect_metrics_on_completion is True
    assert siliconflow._should_collect_metrics(intermediate) is False
    assert siliconflow._should_collect_metrics(completed) is True
    assert siliconflow._should_collect_metrics(trailing) is False
    assert standard.collect_metrics_on_completion is False
    assert standard._should_collect_metrics(trailing) is True


def test_reporting_model复制到worker和facade后保留累计usage配置():
    base = _report_model(
        replace(app.settings, openai_base_url="https://api.siliconflow.cn/v1"),
        enable_thinking=True,
    )
    worker = _report_worker_model(base)
    facade = _report_facade_model(worker)

    assert worker.collect_metrics_on_completion is True
    assert facade.collect_metrics_on_completion is True


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
        app.settings,
        app.agent_database.async_db,
        workspace_service,
        app.coding_repository,
        instructions=["测试报表"],
        report_coding_enable_thinking=False,
    )
    report_agent = create_report_agent(
        report_worker,
        ReportWorkflowController(lambda: None),
    )

    assert isinstance(report_agent.model, ReportFacadeOpenAIChat)
    assert coding_agent.id == "coding-agent"
    assert coding_facade is not coding_agent
    assert coding_facade.id == coding_agent.id
    assert coding_facade.model is not coding_agent.model
    assert coding_facade.model.id == coding_agent.model.id
    assert coding_facade.model.extra_body == {"enable_thinking": False}
    assert coding_facade.model.temperature is None
    assert coding_facade.model.reasoning_effort is None
    assert coding_agent.model.temperature == 0
    assert coding_agent.model.reasoning_effort == app.settings.coding_reasoning_effort
    assert (
        coding_agent.model.get_request_params()["reasoning_effort"]
        == app.settings.coding_reasoning_effort
    )
    assert coding_agent.model.extra_body["enable_thinking"] is True
    assert coding_agent.model.extra_body["thinking_budget"] == 16384
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
    assert report_worker.model.max_tokens == 32768
    assert report_worker.model.temperature == 0
    assert coding_agent.model.max_tokens is None
    assert report_worker.model.extra_body["enable_thinking"] is False
    assert "thinking_budget" not in report_worker.model.extra_body
    assert report_worker.model.reasoning_effort == app.settings.report_coding_reasoning_effort
    assert report_agent.id == "report-agent"
    facade_instructions = "\n".join(report_agent.instructions)
    assert "不得自行解析期间" in facade_instructions
    assert "Workflow 首步" in facade_instructions
    assert "HumanReview retry" in facade_instructions
    assert report_agent.model is not report_worker.model
    assert report_agent.model.extra_body == {"enable_thinking": False}
    assert report_agent.model.temperature is None
    assert report_worker.compression_manager.model is report_worker.model
    assert report_agent.compression_manager.model is report_agent.model
    assert report_worker.compression_manager is not coding_agent.compression_manager
    assert report_agent.compression_manager is not report_worker.compression_manager
    assert report_agent.compression_manager.stats is not report_worker.compression_manager.stats
    assert report_agent.model.request_params == {"parallel_tool_calls": True}
    assert app.assistant.model.request_params is None
    assert sum(is_coding_tool_scheduler_hook(hook) for hook in report_worker.tool_hooks) == 1
    assert not any(is_coding_tool_scheduler_hook(hook) for hook in report_agent.tool_hooks or [])
    assert report_worker.db is app.agent_database.async_db
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
    reporting_examples = {
        "register_report_charts": '示例：{"charts":[',
        "render_report_draft": '示例：{"draft":{',
        "resume_report_draft": "示例：{}",
        "verify_report_draft": "示例：{}",
        "repair_report_draft": '示例：{"changes":[',
    }
    for name, example in reporting_examples.items():
        assert example in worker_tools[0].async_functions[name].description
    for tool in worker_tools[0].async_functions.values():
        assert "示例：" in tool.description, tool.name
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
        "report_workflow_review",
        "report_workflow_approve",
        "report_workflow_reject",
    }
    expected_validators = SkillValidatorRegistry.from_skills(coding_agent.skills)
    assert app.coding_supervisor.validator_registry.script_sha256() == (
        expected_validators.script_sha256()
    )


@pytest.mark.anyio
async def test_report_facade流式路径把普通审核路由到原生确认工具():
    model = ReportFacadeOpenAIChat(id="report-facade-stream-test", api_key="test-key")
    messages = [
        Message(
            role="tool",
            tool_name="report_workflow_start",
            tool_call_id="call-start",
            content=(
                "{'ok': True, 'status': 'paused', "
                "'review': {'stage': 'outline', 'title': '审核报告提纲'}}"
            ),
        )
    ]

    responses = [response async for response in model.ainvoke_stream(messages)]

    assert len(responses) == 1
    assert "审核报告提纲" in str(responses[0].content)
    tool_calls = model.parse_tool_calls(responses[0].tool_calls)
    assert tool_calls[0]["function"] == {
        "name": "report_workflow_approve",
        "arguments": "{}",
    }


def test_report_worker_exposes_image_tool_only_when_vision_is_enabled(tmp_path):
    workspace_service = service(tmp_path)
    report_worker = create_report_worker(
        app.settings,
        app.agent_database.async_db,
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
    assert planner.parse_response is True
    assert any("不得写占位符" in instruction for instruction in planner.instructions)
    assert any("不得把 correction" in instruction for instruction in planner.instructions)
    assert all(instruction in planner.instructions for instruction in stage_instructions)
    assert (
        app.report_worker.model.extra_body["enable_thinking"]
        is app.settings.report_coding_enable_thinking
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


@pytest.mark.anyio
async def test_reporting_tool_hook只展开一层arguments且错误不产生traceback():
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})

    async def render_report_draft(draft):
        return {"ok": True, "draft": draft}

    corrected = await normalize_reporting_tool_arguments(
        context,
        "render_report_draft",
        render_report_draft,
        {"arguments": {"draft": {"title": "报告", "sections": []}}},
    )
    nested = await normalize_reporting_tool_arguments(
        context,
        "render_report_draft",
        render_report_draft,
        {"arguments": {"arguments": {"draft": {}}}},
    )

    assert corrected["ok"] is True
    assert corrected["draft"]["title"] == "报告"
    assert context.session_state["agentos_reporting_tool_argument_autofixes"] == [
        {
            "code": "report_tool_arguments_unwrapped",
            "toolName": "render_report_draft",
            "mutationSequence": 0,
        }
    ]
    assert nested["code"] == "report_tool_arguments_invalid"
    assert nested["severity"] == "warning"
    assert nested["executionBlocking"] is False
    assert nested["failedRequirements"] == []
    expected = nested["expectedCallShape"]
    assert expected["draft"]["title"] == "报告标题"
    assert expected["draft"]["sections"][0]["blocks"][0]["text"] == "图表题注"
    assert nested["correctCallExample"] == {
        "name": "render_report_draft",
        "arguments": expected,
    }
    assert "Traceback" not in str(nested)


@pytest.mark.anyio
async def test_reporting_tool_hook同一参数错误无mutation第五次停止重试():
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})

    async def render_report_draft(draft):
        return {"ok": True, "draft": draft}

    results = [
        await normalize_reporting_tool_arguments(
            context,
            "render_report_draft",
            render_report_draft,
            {"title": "错误调用"},
        )
        for _attempt in range(4)
    ]

    assert all(result["retryable"] is True for result in results)
    assert all(result["severity"] == "warning" for result in results)
    assert all(result["executionBlocking"] is False for result in results)
    with pytest.raises(StopAgentRun) as stopped:
        await normalize_reporting_tool_arguments(
            context,
            "render_report_draft",
            render_report_draft,
            {"title": "错误调用"},
        )
    blocked = json.loads(str(stopped.value))
    assert blocked["retryable"] is False
    assert blocked["severity"] == "error"
    assert blocked["executionBlocking"] is True
    assert blocked["requiredActions"] == [
        "逐字使用 correctCallExample 重试；不要增加 arguments 包装或其他字段。"
    ]


@pytest.mark.anyio
async def test_reporting_tool_hook业务拒绝交错出现且无mutation时第五次停止执行():
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})

    async def repair_report_draft(changes):
        return {
            "ok": False,
            "status": "rejected",
            "code": "report_repair_changes_incomplete",
            "message": "结构化修复未覆盖全部 issueId。",
            "retryable": True,
        }

    async def read_file(path):
        return {
            "ok": False,
            "status": "rejected",
            "code": "report_repair_tool_forbidden",
            "message": "首次验收失败后禁止读取完整 Markdown。",
            "retryable": True,
        }

    for _attempt in range(4):
        repair = await normalize_reporting_tool_arguments(
            context,
            "repair_report_draft",
            repair_report_draft,
            {"changes": [{"issueId": "period_claim_income", "newText": "错误修复"}]},
        )
        assert repair["retryable"] is True
        read = await normalize_reporting_tool_arguments(
            context,
            "read_file",
            read_file,
            {"path": "report.md"},
        )
        assert read["retryable"] is True

    with pytest.raises(StopAgentRun) as stopped:
        await normalize_reporting_tool_arguments(
            context,
            "repair_report_draft",
            repair_report_draft,
            {"changes": [{"issueId": "period_claim_income", "newText": "错误修复"}]},
        )

    blocked = json.loads(str(stopped.value))
    assert blocked["code"] == "report_repair_changes_incomplete"
    assert blocked["retryable"] is False
    assert blocked["executionBlocking"] is True
    assert blocked["details"]["noProgressCount"] == 5


@pytest.mark.anyio
async def test_reporting_tool_hook对通用工具也只展开一层arguments():
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})
    called = False

    async def terminal(command):
        nonlocal called
        called = True
        return {"ok": True, "command": command}

    result = await normalize_reporting_tool_arguments(
        context,
        "terminal",
        terminal,
        {"arguments": {"command": "echo ok"}},
    )

    assert called is True
    assert result == {"ok": True, "command": "echo ok"}
    assert "Traceback" not in str(result)


@pytest.mark.anyio
async def test_reporting_tool_hook展开arguments并保留同级参数():
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})

    async def terminal(command, timeout):
        return {"ok": True, "command": command, "timeout": timeout}

    result = await normalize_reporting_tool_arguments(
        context,
        "terminal",
        terminal,
        {"arguments": {"command": "python3 analysis/run_analysis.py"}, "timeout": 300},
    )

    assert result == {
        "ok": True,
        "command": "python3 analysis/run_analysis.py",
        "timeout": 300,
    }


@pytest.mark.anyio
async def test_reporting_tool_hook展开字符串arguments对象():
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})

    async def create_files(files):
        return {"ok": True, "files": files}

    result = await normalize_reporting_tool_arguments(
        context,
        "create_files",
        create_files,
        {"arguments": '{"files":[{"path":"analysis/run_analysis.py"}]}'},
    )

    assert result == {
        "ok": True,
        "files": [{"path": "analysis/run_analysis.py"}],
    }


@pytest.mark.anyio
async def test_reporting_tool_hook兼容字符串arguments缺少末尾对象括号():
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})

    async def create_files(files):
        return {"ok": True, "files": files}

    result = await normalize_reporting_tool_arguments(
        context,
        "create_files",
        create_files,
        {
            "arguments": (
                '{"files":[{"path":"analysis/run_analysis.py","content":"print(\\"报告\\")\\n"}]'
            )
        },
    )

    assert result["code"] == "report_tool_arguments_invalid"


@pytest.mark.anyio
async def test_reporting_tool_hook展开含三引号文本的arguments对象():
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})

    async def create_files(files):
        return {"ok": True, "files": files}

    result = await normalize_reporting_tool_arguments(
        context,
        "create_files",
        create_files,
        {
            "arguments": (
                '{"files":[{"path":"analysis/run_analysis.py",'
                '\'content\':"""print(\'报告\')\n"""}]}'
            )
        },
    )

    assert result["code"] == "report_tool_arguments_invalid"


@pytest.mark.anyio
async def test_report_worker_verify通过后确定性调用finish而不再请求模型(monkeypatch):
    model = ReportWorkerOpenAIChat(id="report-worker-test", api_key="test-key")
    messages = [
        Message(
            role="tool",
            tool_name="verify_report_draft",
            tool_call_id="verify-call",
            content=json.dumps(
                {
                    "ok": True,
                    "failedRequirements": [],
                    "warnings": [{"code": "period_binding_ambiguous"}],
                    "nextToolCall": {
                        "name": "finish_task",
                        "arguments": {
                            "summary": "报告已通过服务端正式验收。",
                            "artifact_paths": ["report.md"],
                        },
                    },
                },
                ensure_ascii=False,
            ),
        )
    ]

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("verify 通过后不应再请求供应商模型")

    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke", unexpected)
    response = await model.ainvoke(messages)

    assert response.tool_calls[0]["function"]["name"] == "finish_task"
    assert json.loads(response.tool_calls[0]["function"]["arguments"]) == {
        "summary": "报告已通过服务端正式验收。",
        "artifact_paths": ["report.md"],
    }


@pytest.mark.anyio
async def test_report_worker流式verify通过后确定性调用finish而不再请求模型(monkeypatch):
    model = ReportWorkerOpenAIChat(id="report-worker-stream-test", api_key="test-key")
    messages = [
        Message(
            role="tool",
            tool_name="verify_report_draft",
            tool_call_id="verify-call",
            content=json.dumps(
                {
                    "ok": True,
                    "warnings": [{"code": "period_binding_ambiguous"}],
                    "nextToolCall": {
                        "name": "finish_task",
                        "arguments": {
                            "summary": "报告已通过服务端正式验收。",
                            "artifact_paths": ["report.md", "charts/trend.png"],
                        },
                    },
                },
                ensure_ascii=False,
            ),
        )
    ]

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("verify 通过后流式路径不应再请求供应商模型")

    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke_stream", unexpected)
    responses = [response async for response in model.ainvoke_stream(messages)]

    assert len(responses) == 1
    tool_calls = model.parse_tool_calls(responses[0].tool_calls)
    assert tool_calls[0]["function"]["name"] == "finish_task"
    assert json.loads(tool_calls[0]["function"]["arguments"]) == {
        "summary": "报告已通过服务端正式验收。",
        "artifact_paths": ["report.md", "charts/trend.png"],
    }


def test_report_worker缺少受信任next_call时不强制finish(monkeypatch):
    model = ReportWorkerOpenAIChat(id="report-worker-invalid-next-call", api_key="test-key")

    def upstream(*_args, **_kwargs):
        return "upstream-response"

    monkeypatch.setattr(ProjectedOpenAIChat, "invoke", upstream)
    response = model.invoke(
        [
            Message(
                role="tool",
                tool_name="verify_report_draft",
                tool_call_id="verify-call",
                content='{"ok":true}',
            )
        ]
    )

    assert response == "upstream-response"


@pytest.mark.anyio
async def test_reporting_tool_hook通用工具兼容失败时恢复原始调用并返回warning():
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})
    calls = []

    async def terminal(command):
        calls.append(command)
        return {"ok": True, "command": command}

    result = await normalize_reporting_tool_arguments(
        context,
        "terminal",
        terminal,
        {"arguments": {"unknown": "echo ok"}},
    )

    assert calls == []
    assert result == {
        "ok": False,
        "status": "rejected",
        "code": "report_tool_arguments_invalid",
        "message": "工具参数不符合当前工具的调用 schema。",
        "severity": "warning",
        "executionBlocking": False,
        "warnings": [
            {
                "code": "report_tool_arguments_invalid",
                "toolName": "terminal",
            }
        ],
        "autoFixes": [],
        "failedRequirements": [],
        "requiredActions": ["参照当前工具描述中的示例直接传参，不要增加 arguments 包装。"],
        "retryable": True,
    }
    assert "Traceback" not in str(result)


@pytest.mark.anyio
async def test_reporting_tool_hook不会把工具内部TypeError降级为参数warning():
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})

    async def terminal(command):
        raise TypeError(f"internal failure while running {command}")

    with pytest.raises(TypeError, match="internal failure"):
        await normalize_reporting_tool_arguments(
            context,
            "terminal",
            terminal,
            {"command": "echo ok"},
        )
