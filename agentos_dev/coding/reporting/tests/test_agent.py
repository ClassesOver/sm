import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agno.exceptions import RetryAgentRun, StopAgentRun
from agno.models.message import Message
from agno.run import RunContext
from pydantic import BaseModel

from agentos_dev import app
from agentos_dev.coding.agent import create_coding_agent, create_coding_facade_agent
from agentos_dev.coding.reporting.agent import (
    ReportFacadeOpenAIChat,
    ReportWorkerOpenAIChat,
    _phase_filtered_report_messages,
    _phase_filtered_report_tools,
    _report_facade_model,
    _report_model,
    _report_worker_model,
    create_report_agent,
    create_report_worker,
    normalize_reporting_tool_arguments,
)
from agentos_dev.coding.reporting.contract import ReportPeriod
from agentos_dev.coding.reporting.hospital_operation import ReportOutlineProposal, make_outline
from agentos_dev.coding.reporting.instructions import (
    HOSPITAL_ANALYSIS_INSTRUCTIONS,
    HOSPITAL_DATA_UNDERSTANDING_INSTRUCTIONS,
)
from agentos_dev.coding.reporting.tests.workspace_fakes import service
from agentos_dev.coding.reporting.workflow.controller import ReportWorkflowController
from agentos_dev.coding.reporting.workflow.runtime import (
    AnalysisBundle,
    DataUnderstandingPlan,
    GeneratedQueryBatch,
    ReportOutline,
    ReportWorkflowRuntime,
    _report_pdf_filename,
    _report_pdf_path,
)
from agentos_dev.context_management import ProjectedOpenAIChat
from agentos_dev.instructions import build_pure_coding_agent_instructions
from agentos_dev.skills import SkillValidatorRegistry, is_skill_script_hook
from agentos_dev.task_execution.execution import is_coding_tool_scheduler_hook


def test_专题提纲允许业务章节子集并保持固定十章主序():
    income_only = make_outline(
        "topic",
        title="收入分析报告",
        selected_codes=("income",),
    )

    assert [section.code for section in income_only.sections] == [
        "operation_overview",
        "income",
        "risk_and_data_quality",
        "management_actions",
    ]

    payload = income_only.model_dump(mode="json", by_alias=True)
    payload["sections"][0], payload["sections"][1] = (
        payload["sections"][1],
        payload["sections"][0],
    )
    with pytest.raises(ValueError, match="主序"):
        ReportOutline.model_validate(payload)


def test_pdf文件名使用报告主题和完整时间段并清理路径字符():
    period = ReportPeriod(start="2025-01-01", end="2025-03-31")

    assert _report_pdf_filename("收入/成本分析报告", period) == (
        "收入_成本分析报告_2025-01-01至2025-03-31.pdf"
    )


def test_pdf内部路径按revision隔离且下载文件名保持稳定():
    period = ReportPeriod(start="2025-01-01", end="2025-12-31")

    first = _report_pdf_path("run-1", 1, "收入分析报告", period)
    second = _report_pdf_path("run-1", 2, "收入分析报告", period)

    assert first != second
    assert "/revision-1/" in first
    assert "/revision-2/" in second
    assert first.rsplit("/", 1)[-1] == second.rsplit("/", 1)[-1]


def test_提纲规划器基于analysis生成动态章节且不接收code():
    outline_rules = "\n".join(app.report_runtime._outline_agent.instructions)
    assert app.report_runtime._outline_agent.output_schema is ReportOutlineProposal
    assert "sections 不得提交 code" in outline_rules
    assert "analysisId" in outline_rules
    assert "动态章节" in outline_rules
    assert "comprehensive 必须精确返回固定十章" not in outline_rules


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


def test_report_worker禁用视觉时将过期view_image调用转为跳过回执():
    model = ReportWorkerOpenAIChat(id="report-worker-vision-test", api_key="test-key")
    model._report_vision_enabled = False
    assistant = Message(
        role="assistant",
        tool_calls=[
            {
                "id": "call-image",
                "type": "function",
                "function": {"name": "view_image", "arguments": "{}"},
            }
        ],
    )
    messages = [assistant]

    assert model.get_function_calls_to_run(assistant, messages, {}) == []
    assert json.loads(messages[-1].content) == {
        "ok": False,
        "status": "skipped",
        "code": "report_vision_disabled",
        "message": "当前 Reporting Worker 未启用图片视觉工具，继续使用文本和文件证据。",
    }


def test_report_worker模型schema在section只暴露章节工具():
    messages = [Message(role="user", content='{"phase":"section"}')]
    tools = [
        {"type": "function", "function": {"name": name, "parameters": {}}}
        for name in (
            "terminal",
            "get_skill_script",
            "read_file",
            "read_tool_output",
            "render_report_section",
            "request_analysis_rework",
            "finish_task",
        )
    ]

    projected = _phase_filtered_report_tools(messages, tools)

    assert [item["function"]["name"] for item in projected] == [
        "read_file",
        "read_tool_output",
        "render_report_section",
        "request_analysis_rework",
        "finish_task",
    ]


def test_report_worker_section系统投影移除agno自动skill规则():
    messages = [
        Message(
            role="system",
            content=(
                "<instructions>当前章节规则</instructions>\n"
                "<skills_system>\n必须调用 get_skill_instructions\n</skills_system>\n"
            ),
        ),
        Message(role="user", content='{"phase":"section"}'),
    ]

    projected = _phase_filtered_report_messages(messages)

    assert projected is not messages
    assert projected[0] is not messages[0]
    assert projected[0].content == "<instructions>当前章节规则</instructions>\n"
    assert "skills_system" in str(messages[0].content)
    assert (
        _phase_filtered_report_messages(
            [messages[0], Message(role="user", content='{"phase":"analysis"}')]
        )[0].content
        == messages[0].content
    )


def test_report_worker拒绝section旧schema中的terminal调用():
    model = ReportWorkerOpenAIChat(id="report-worker-phase-test", api_key="test-key")
    assistant = Message(
        role="assistant",
        tool_calls=[
            {
                "id": "call-terminal",
                "type": "function",
                "function": {"name": "terminal", "arguments": '{"command":"pwd"}'},
            }
        ],
    )
    messages = [Message(role="user", content='{"phase":"section"}'), assistant]

    assert model.get_function_calls_to_run(assistant, messages, {}) == []
    assert json.loads(messages[-1].content) == {
        "ok": False,
        "status": "rejected",
        "code": "report_phase_tool_forbidden",
        "message": "当前 Reporting phase 不允许调用该工具，请使用本阶段已提供工具继续。",
    }


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
        context_token_budget=app.settings.report_context_token_budget,
        output_token_reserve=app.settings.report_output_token_reserve,
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
    assert coding_facade.model.temperature == 1.0
    assert coding_facade.model.reasoning_effort is None
    assert coding_agent.model.temperature == 0.1
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
    assert {skill.name for skill in report_worker.skills.get_all_skills()} == {
        "sandbox-tooling",
        "report-artifact",
        "report-visualization",
    }
    assert report_worker.use_instruction_tags is True
    assert report_worker.send_media_to_model is False
    assert report_worker.model is not coding_agent.model
    assert report_worker.model.max_tokens == app.settings.report_output_token_reserve
    assert report_worker.model.temperature == app.settings.report_coding_temperature
    assert report_worker.model.top_p == 0.95
    assert coding_agent.model.max_tokens is None
    assert report_worker.model.extra_body["enable_thinking"] is False
    assert "thinking_budget" not in report_worker.model.extra_body
    assert report_worker.model.reasoning_effort == app.settings.report_coding_reasoning_effort
    assert report_agent.id == "report-agent"
    facade_instructions = "\n".join(report_agent.instructions)
    assert "不得自行解析期间" in facade_instructions
    assert "Workflow 首步" in facade_instructions
    assert "HumanReview retry" in facade_instructions
    assert "downloadUrl 必须逐字保留" in facade_instructions
    assert "[下载 PDF]" in facade_instructions
    assert "[下载 Word]" in facade_instructions
    assert "不得输出为裸路径" in facade_instructions
    assert report_agent.model is not report_worker.model
    assert report_agent.model.extra_body == {"enable_thinking": False}
    assert report_agent.model.temperature == 1.0
    assert report_agent.model.top_p == 0.95
    assert report_worker.compression_manager.model is report_worker.model
    assert (
        report_worker.compression_manager.context_token_limit
        == app.settings.report_context_token_budget
    )
    assert (
        report_worker.compression_manager.output_token_reserve
        == app.settings.report_output_token_reserve
    )
    assert report_worker.model._coding_input_token_budget == (
        report_worker.compression_manager.input_token_budget
    )
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
        "complete_report_analysis": '示例：{"reportBrief":',
        "inspect_profile_index": '示例：{"datasetId":',
        "read_profile_pointer": '示例：{"datasetId":',
        "register_report_charts": '示例：{"charts":[',
        "render_report_section": '示例：{"sectionCode":',
        "request_analysis_rework": '示例：{"analysisIds":[',
    }
    for name, example in reporting_examples.items():
        assert example in worker_tools[0].async_functions[name].description
    for tool in worker_tools[0].async_functions.values():
        assert "示例：" in tool.description, tool.name
    assert "view_image" not in worker_tools[0].async_functions
    assert "view_image" not in worker_tools_without_injected_context[0].async_functions
    assert worker_tools[0]._vision_reviewer is None
    assert "verify" not in worker_tools[0].async_functions
    assert worker_tools[0].kernel.validator_registry.script_sha256() == {}
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

    tools = report_worker.tools()[0]
    assert report_worker.send_media_to_model is False
    assert "view_image" in tools.async_functions
    assert "独立视觉模型" in tools.async_functions["view_image"].description
    assert "不向 Report Worker 回传媒体" in tools.async_functions["view_image"].description
    assert tools._vision_reviewer is not None
    assert tools._vision_reviewer.model_id == app.settings.report_vision_model


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
        reasoning_effort=app.settings.report_planner_reasoning_effort,
        stage_instructions=stage_instructions,
    )

    assert planner.model is not app.report_worker.model
    assert planner.model.extra_body["enable_thinking"] is app.settings.report_enable_thinking
    assert planner.model.temperature == 1.0
    assert planner.model.top_p == 1.0
    assert planner.model.reasoning_effort == (
        app.settings.report_planner_reasoning_effort
        if app.settings.report_enable_thinking
        else None
    )
    assert planner.model.timeout == app.settings.model_timeout_seconds
    assert planner.parse_response is True
    assert planner.enable_session_summaries is False
    assert planner.add_session_summary_to_context is False
    assert planner.session_summary_manager is None
    assert planner.add_session_state_to_context is False
    assert any("不得写占位符" in instruction for instruction in planner.instructions)
    assert any("不得把 correction" in instruction for instruction in planner.instructions)
    assert all(instruction in planner.instructions for instruction in stage_instructions)
    assert (
        app.report_worker.model.extra_body["enable_thinking"]
        is app.settings.report_coding_enable_thinking
    )


def test_医院运营规划规则按阶段隔离():
    data_instructions = app.report_runtime._data_understanding_agent.instructions
    analysis_instructions = app.report_runtime._analysis_agent.instructions

    assert all(rule in data_instructions for rule in HOSPITAL_DATA_UNDERSTANDING_INSTRUCTIONS)
    assert not any(
        "跨域分析仅在期间、粒度、组织和口径可比时执行" in rule for rule in data_instructions
    )
    assert all(rule in analysis_instructions for rule in HOSPITAL_ANALYSIS_INSTRUCTIONS)
    assert not any(
        "只能依据 Schema Snapshot、字段说明和业务术语判断表的用途" in rule
        for rule in analysis_instructions
    )

    unrelated_planners = (
        app.report_runtime._request_normalizer,
        app.report_runtime._measure_semantic_agent,
        app.report_runtime._outline_agent,
        app.report_runtime._sql_agent,
    )
    hospital_planning_rules = (
        *HOSPITAL_DATA_UNDERSTANDING_INSTRUCTIONS,
        *HOSPITAL_ANALYSIS_INSTRUCTIONS,
    )
    assert all(
        not any(rule in planner.instructions for rule in hospital_planning_rules)
        for planner in unrelated_planners
    )

    analysis_prompt = "\n".join(HOSPITAL_ANALYSIS_INSTRUCTIONS)
    for scenario in ("收入", "工作量", "预算", "全成本", "费控", "资金"):
        assert scenario in analysis_prompt
    assert "相关性不得表述为确定因果" in analysis_prompt
    assert "跨域分析仅在期间、粒度、组织和口径可比时执行" in analysis_prompt


def test_report_planner_reasoning_effort_can_be_overridden():
    planner = ReportWorkflowRuntime._planning_agent(
        app.report_worker,
        "report-test-planner-low",
        DataUnderstandingPlan,
        enable_thinking=True,
        reasoning_effort="low",
    )

    assert planner.model.get_request_params()["reasoning_effort"] == "low"
    assert any(
        "非聚合 SELECT 列和 GROUP BY 列必须逐项等于 grainColumns" in instruction
        for instruction in app.report_runtime._sql_agent.instructions
    )


def test_report_planners_expose_compact_schema_in_stable_instructions():
    expected_fields = {
        DataUnderstandingPlan: ("tables", "periodColumn", "periodGranularity"),
        ReportOutlineProposal: ("title", "sections", "analysisIds"),
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

    async def render_report_section(sectionCode, blocks):
        return {"ok": True, "sectionCode": sectionCode, "blocks": blocks}

    corrected = await normalize_reporting_tool_arguments(
        context,
        "render_report_section",
        render_report_section,
        {"arguments": {"sectionCode": "summary", "blocks": []}},
    )
    nested = await normalize_reporting_tool_arguments(
        context,
        "render_report_section",
        render_report_section,
        {"arguments": {"arguments": {"sectionCode": "summary", "blocks": []}}},
    )

    assert corrected["ok"] is True
    assert corrected["sectionCode"] == "summary"
    assert context.session_state["agentos_reporting_tool_argument_autofixes"] == [
        {
            "code": "report_tool_arguments_unwrapped",
            "toolName": "render_report_section",
            "mutationSequence": 0,
        }
    ]
    assert nested["code"] == "report_tool_arguments_invalid"
    assert nested["severity"] == "warning"
    assert nested["executionBlocking"] is False
    assert nested["failedRequirements"] == []
    expected = nested["expectedCallShape"]
    assert expected["sectionCode"] == "executive_summary"
    assert expected["blocks"][0]["markdown"].startswith("### 核心结论")
    assert nested["correctCallExample"] == {
        "name": "render_report_section",
        "arguments": expected,
    }
    assert "Traceback" not in str(nested)


@pytest.mark.anyio
async def test_reporting_tool_hook保留RetryAgentRun给Agno当前循环重试():
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})

    async def render_report_section(sectionCode, blocks):
        raise RetryAgentRun(f"章节 {sectionCode} 需要修正")

    with pytest.raises(RetryAgentRun, match="章节 summary 需要修正"):
        await normalize_reporting_tool_arguments(
            context,
            "render_report_section",
            render_report_section,
            {"sectionCode": "summary", "blocks": []},
        )


@pytest.mark.anyio
async def test_reporting_tool_hook真实mutation代表进展并重置同一错误预算():
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})

    async def render_report_section(sectionCode, blocks):
        return {"ok": True, "sectionCode": sectionCode, "blocks": blocks}

    results = []
    for attempt in range(4):
        context.session_state["agentos_coding_tool_progress"] = {"mutation": attempt}
        results.append(
            await normalize_reporting_tool_arguments(
                context,
                "render_report_section",
                render_report_section,
                {"title": "错误调用"},
            )
        )

    assert all(result["retryable"] is True for result in results)
    assert all(result["severity"] == "warning" for result in results)
    assert all(result["executionBlocking"] is False for result in results)
    # 工作区 mutation 变化表示模型取得了真实进展，错误预算从新进度重新计数。
    context.session_state["agentos_coding_tool_progress"] = {"mutation": 99}
    result = await normalize_reporting_tool_arguments(
        context,
        "render_report_section",
        render_report_section,
        {"title": "错误调用"},
    )
    assert result["retryable"] is True
    assert result["severity"] == "warning"
    assert result["executionBlocking"] is False


@pytest.mark.anyio
async def test_reporting_tool_hook跨工具和错误码累计到阶段预算时停止执行():
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})

    async def reject_with(code, **_arguments):
        return {
            "ok": False,
            "status": "rejected",
            "code": code,
            "message": "当前阶段没有产生有效进展。",
            "retryable": True,
        }

    attempts = [
        (
            "render_report_section",
            "report_section_chart_unknown",
            {"sectionCode": "a", "blocks": []},
        ),
        ("begin_report_draft", "report_draft_state_invalid", {}),
        ("register_report_charts", "report_chart_registration_conflict", {"charts": []}),
        (
            "render_report_section",
            "report_section_already_submitted",
            {"sectionCode": "a", "blocks": []},
        ),
        ("finalize_report_draft", "report_draft_sections_incomplete", {}),
        ("register_report_charts", "report_chart_registration_conflict", {"charts": []}),
        (
            "render_report_section",
            "report_tool_arguments_invalid",
            {"sectionCode": "a", "blocks": []},
        ),
    ]
    for function_name, code, arguments in attempts:
        result = await normalize_reporting_tool_arguments(
            context,
            function_name,
            lambda **kwargs: reject_with(code, **kwargs),
            arguments,
        )
        assert result["retryable"] is True

    with pytest.raises(StopAgentRun) as stopped:
        await normalize_reporting_tool_arguments(
            context,
            "register_report_charts",
            lambda **kwargs: reject_with("report_chart_registration_conflict", **kwargs),
            {"charts": []},
        )

    blocked = json.loads(str(stopped.value))
    assert blocked["code"] == "report_chart_registration_conflict"
    assert blocked["retryable"] is False
    assert blocked["executionBlocking"] is True
    assert blocked["details"]["noProgressCount"] == 8
    assert blocked["details"]["phaseFailureCount"] == 8
    assert blocked["details"]["sameFailureCount"] == 3


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
async def test_report_worker_finalize通过后确定性调用finish而不再请求模型(monkeypatch):
    model = ReportWorkerOpenAIChat(id="report-worker-test", api_key="test-key")
    messages = [
        Message(
            role="tool",
            tool_name="finalize_report_draft",
            tool_call_id="finalize-call",
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
        raise AssertionError("finalize 通过后不应再请求供应商模型")

    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke", unexpected)
    response = await model.ainvoke(messages)

    assert response.tool_calls[0]["function"]["name"] == "finish_task"
    assert json.loads(response.tool_calls[0]["function"]["arguments"]) == {
        "summary": "报告已通过服务端正式验收。",
        "artifact_paths": ["report.md"],
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool_name",
    ["complete_report_analysis", "render_report_section", "request_analysis_rework"],
)
async def test_report_worker阶段产物通过后确定性调用finish(monkeypatch, tool_name):
    model = ReportWorkerOpenAIChat(id="report-worker-phase-test", api_key="test-key")
    messages = [
        Message(
            role="tool",
            tool_name=tool_name,
            tool_call_id="phase-call",
            content=json.dumps(
                {
                    "ok": True,
                    "status": "accepted",
                    "nextToolCall": {
                        "name": "finish_task",
                        "arguments": {
                            "summary": "阶段产物已冻结。",
                            "artifact_paths": ["phases/output.json"],
                        },
                    },
                },
                ensure_ascii=False,
            ),
        )
    ]

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("阶段工具通过后不应再请求供应商模型")

    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke", unexpected)
    response = await model.ainvoke(messages)

    assert response.tool_calls[0]["function"]["name"] == "finish_task"


@pytest.mark.anyio
async def test_report_worker流式finalize通过后确定性调用finish而不再请求模型(monkeypatch):
    model = ReportWorkerOpenAIChat(id="report-worker-stream-test", api_key="test-key")
    messages = [
        Message(
            role="tool",
            tool_name="finalize_report_draft",
            tool_call_id="finalize-call",
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
        raise AssertionError("finalize 通过后流式路径不应再请求供应商模型")

    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke_stream", unexpected)
    responses = [response async for response in model.ainvoke_stream(messages)]

    assert len(responses) == 1
    tool_calls = model.parse_tool_calls(responses[0].tool_calls)
    assert tool_calls[0]["function"]["name"] == "finish_task"
    assert json.loads(tool_calls[0]["function"]["arguments"]) == {
        "summary": "报告已通过服务端正式验收。",
        "artifact_paths": ["report.md", "charts/trend.png"],
    }


@pytest.mark.anyio
async def test_report_worker接受agno工具返回的python字典文本并使用定稿产物(monkeypatch):
    model = ReportWorkerOpenAIChat(id="report-worker-repr-test", api_key="test-key")
    trusted_paths = ["report.md", "charts/income.png", "charts/workload.png"]
    messages = [
        Message(
            role="tool",
            tool_name="finalize_report_draft",
            tool_call_id="finalize-call",
            content=str(
                {
                    "ok": True,
                    "status": "completed",
                    "artifactPaths": trusted_paths,
                    "nextToolCall": {
                        "name": "finish_task",
                        "arguments": {
                            "summary": "报告已完成逐章拼装。",
                            "artifact_paths": trusted_paths,
                        },
                    },
                }
            ),
        )
    ]

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("Agno 字典文本应直接收敛到服务端签发的 finish_task")

    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke", unexpected)
    response = await model.ainvoke(messages)

    assert response.tool_calls[0]["function"]["name"] == "finish_task"
    assert json.loads(response.tool_calls[0]["function"]["arguments"])["artifact_paths"] == (
        trusted_paths
    )


def test_report_worker缺少受信任next_call时不强制finish(monkeypatch):
    model = ReportWorkerOpenAIChat(id="report-worker-invalid-next-call", api_key="test-key")

    def upstream(*_args, **_kwargs):
        return "upstream-response"

    monkeypatch.setattr(ProjectedOpenAIChat, "invoke", upstream)
    response = model.invoke(
        [
            Message(
                role="tool",
                tool_name="finalize_report_draft",
                tool_call_id="finalize-call",
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
        "details": {
            "issues": [
                {
                    "loc": "$",
                    "message": "test_reporting_tool_hook通用工具兼容失败时恢复原始调用并返回warning.<locals>.terminal() got an unexpected keyword argument 'arguments'",
                    "type": "type_error",
                }
            ],
            "topLevelTypes": {"arguments": "dict"},
        },
    }
    assert "Traceback" not in str(result)


@pytest.mark.anyio
async def test_reporting_tool_hook返回有界ValidationError位置且不泄露参数值():
    class FileInput(BaseModel):
        path: str
        content: str

    class CreateFilesInput(BaseModel):
        files: list[FileInput]

    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})

    async def create_files(files):
        CreateFilesInput.model_validate({"files": files})

    secret = "不应出现在错误诊断中的脚本正文"
    result = await normalize_reporting_tool_arguments(
        context,
        "create_files",
        create_files,
        {"files": [{"path": "analysis/report_analysis.py", "unknown": secret}]},
    )

    assert result["details"] == {
        "issues": [
            {
                "loc": "files.0.content",
                "message": "Field required",
                "type": "missing",
            }
        ],
        "topLevelTypes": {"files": "list"},
    }
    assert secret not in json.dumps(result, ensure_ascii=False)
    assert len(result["details"]["issues"]) <= 8
    assert all(len(issue["loc"]) <= 256 for issue in result["details"]["issues"])
    assert all(len(issue["message"]) <= 512 for issue in result["details"]["issues"])


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
