from __future__ import annotations

import pytest
from agno.models.message import Message
from agno.run import RunContext

from smart_reporting.context_management import TaskExecutionContextProjector
from smart_reporting.reporting.agent import (
    ReportingPhaseOpenAIChat,
    _phase_filtered_report_messages,
    _reporting_tools_cache_key,
    normalize_reporting_tool_arguments,
)
from smart_reporting.reporting.delivery.report_runtime import REPORT_VISUAL_THEME
from smart_reporting.reporting.instructions import build_report_agent_instructions
from smart_reporting.reporting.model_policy import (
    ThinkingDecision,
    bind_reporting_thinking,
    resolve_reporting_input_token_hard_cap,
)
from smart_reporting.reporting.phase import (
    REPORTING_MODEL_ID_DEPENDENCY_KEY,
    REPORTING_MODEL_TIER_DEPENDENCY_KEY,
    REPORTING_PHASE_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
    REPORTING_TASK_KIND_DEPENDENCY_KEY,
    REPORTING_THINKING_BUDGET_DEPENDENCY_KEY,
    REPORTING_THINKING_EFFORT_DEPENDENCY_KEY,
    bind_reporting_run_context,
    reporting_task_kind_from_acceptance_contract,
    reporting_task_kind_from_run_context,
    reporting_thinking_budget_from_acceptance_contract,
    reporting_thinking_effort_from_acceptance_contract,
)
from smart_reporting.reporting.tools.capabilities import tools_for_task


def _context(phase: str, task_kind: str) -> RunContext:
    return RunContext(
        run_id=f"run-{task_kind}",
        session_id=f"session-{task_kind}",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: phase,
                REPORTING_TASK_KIND_DEPENDENCY_KEY: task_kind,
            }
        },
    )


@pytest.mark.parametrize(
    ("phase", "task_kind"),
    (
        ("analysis", "analysis_item"),
        ("analysis", "visualization_section"),
        ("section", "section"),
    ),
)
def test_current_task_kinds_are_projected_from_run_context(phase: str, task_kind: str) -> None:
    assert reporting_task_kind_from_run_context(_context(phase, task_kind)) == task_kind


@pytest.mark.parametrize(
    ("phase", "task_kind", "expected"),
    (
        ("analysis", "analysis_item", "auto"),
        ("analysis", "visualization_section", "auto"),
        ("section", "section", "auto"),
    ),
)
def test_phase_agent_does_not_require_model_tool_calls(
    phase: str, task_kind: str, expected: str
) -> None:
    with bind_reporting_run_context(_context(phase, task_kind)):
        assert ReportingPhaseOpenAIChat._phase_request_kwargs(
            [Message(role="user", content="probe")], {"tool_choice": "auto"}
        ) == {"tool_choice": expected}


@pytest.mark.parametrize(
    ("phase", "task_kind", "expected"),
    (
        ("analysis", "analysis_item", "auto"),
        ("analysis", "visualization_section", "auto"),
        ("section", "section", "auto"),
    ),
)
def test_phase_agent_allows_tasks_to_finish_after_tool_history(
    phase: str, task_kind: str, expected: str
) -> None:
    messages = [
        Message(role="user", content="probe"),
        Message(role="assistant", tool_calls=[{"function": {"name": "probe"}}]),
        Message(role="tool", tool_call_id="call-1", content="ok"),
    ]

    with bind_reporting_run_context(_context(phase, task_kind)):
        assert ReportingPhaseOpenAIChat._phase_request_kwargs(
            messages, {"tool_choice": "auto"}
        ) == {"tool_choice": expected}


@pytest.mark.parametrize(
    ("phase", "task_kind"),
    (("analysis", "analysis_item"), ("analysis", "visualization_section")),
)
def test_fixed_workflows_keep_their_internal_tool_capabilities(phase: str, task_kind: str) -> None:
    tools = tools_for_task(phase, task_kind)

    assert tools
    assert "apply_analysis_patch" in tools
    assert "run_command" in tools
    assert "run_python_script" in tools


def test_model_route_is_projected_from_run_context() -> None:
    context = _context("analysis", "analysis_item")
    context.dependencies[REPORTING_TASK_DEPENDENCY].update(
        {
            REPORTING_MODEL_TIER_DEPENDENCY_KEY: "fast",
            REPORTING_MODEL_ID_DEPENDENCY_KEY: "qwen3.6-35b-a3b",
        }
    )
    from smart_reporting.reporting.phase import reporting_model_route_from_run_context

    assert reporting_model_route_from_run_context(context) == ("fast", "qwen3.6-35b-a3b")


def test_phase_agent_request_uses_model_id_selected_by_trusted_route() -> None:
    context = _context("analysis", "analysis_item")
    context.dependencies[REPORTING_TASK_DEPENDENCY].update(
        {
            REPORTING_MODEL_TIER_DEPENDENCY_KEY: "fast",
            REPORTING_MODEL_ID_DEPENDENCY_KEY: "qwen3.6-35b-a3b",
        }
    )
    phase_model = ReportingPhaseOpenAIChat(id="deepseek-v4-flash-0731", api_key="test-key")

    with bind_reporting_run_context(context):
        request_model = phase_model._phase_request_model([Message(role="user", content="test")])

    assert phase_model.id == "deepseek-v4-flash-0731"
    assert request_model.id == "qwen3.6-35b-a3b"


def test_phase_agent_request_uses_bound_budget_without_mutating_shared_model() -> None:
    context = _context("analysis", "analysis_item")
    context.dependencies[REPORTING_TASK_DEPENDENCY].update(
        {
            REPORTING_THINKING_EFFORT_DEPENDENCY_KEY: "off",
            REPORTING_THINKING_BUDGET_DEPENDENCY_KEY: 8192,
        }
    )
    phase_model = ReportingPhaseOpenAIChat(
        id="deepseek-v4-flash-0731",
        api_key="test-key",
        reasoning_effort="max",
        extra_body={"enable_thinking": True, "thinking_budget": 8192},
    )
    decision = ThinkingDecision(
        operation="data_understanding",
        complexity="standard",
        enabled=True,
        reasoning_effort="high",
        thinking_budget=2048,
        attempt=0,
        reason="initial_policy",
    )

    with bind_reporting_run_context(context), bind_reporting_thinking(decision):
        request_model = phase_model._phase_request_model([Message(role="user", content="test")])

    assert request_model.extra_body == {"enable_thinking": True, "thinking_budget": 2048}
    assert request_model.reasoning_effort == "high"
    assert phase_model.extra_body == {"enable_thinking": True, "thinking_budget": 8192}
    assert phase_model.reasoning_effort == "max"


def test_acceptance_contract_thinking_fields_remain_parseable() -> None:
    contract = {
        "requirements": [
            {
                "parameters": {
                    "phase": "section",
                    "phaseContract": {
                        "taskKind": "section",
                        "thinkingEffort": "high",
                        "thinkingBudget": 4096,
                    },
                }
            }
        ]
    }

    assert reporting_thinking_effort_from_acceptance_contract(contract) == "high"
    assert reporting_thinking_budget_from_acceptance_contract(contract) == 4096


def test_visualization_section_request_keeps_full_script_output_budget() -> None:
    phase_model = ReportingPhaseOpenAIChat(
        id="qwen3.6-flash",
        api_key="test-key",
        max_tokens=64 * 1024,
    )

    with bind_reporting_run_context(_context("analysis", "visualization_section")):
        request_model = phase_model._phase_request_model([Message(role="user", content="test")])

    assert request_model.max_tokens == 64 * 1024


def test_analysis_item_request_respects_verified_model_output_budget() -> None:
    phase_model = ReportingPhaseOpenAIChat(
        id="qwen3.6-flash",
        api_key="test-key",
        max_tokens=96 * 1024,
    )

    with bind_reporting_run_context(_context("analysis", "analysis_item")):
        request_model = phase_model._phase_request_model([Message(role="user", content="test")])

    assert request_model.max_tokens == 64 * 1024


def test_deepseek_analysis_request_respects_verified_model_output_budget() -> None:
    context = _context("analysis", "analysis_item")
    context.dependencies[REPORTING_TASK_DEPENDENCY].update(
        {
            REPORTING_MODEL_TIER_DEPENDENCY_KEY: "standard",
            REPORTING_MODEL_ID_DEPENDENCY_KEY: "deepseek-v4-flash-0731",
        }
    )
    phase_model = ReportingPhaseOpenAIChat(
        id="qwen3.8-flash",
        api_key="test-key",
        max_tokens=393_216,
    )

    with bind_reporting_run_context(context):
        request_model = phase_model._phase_request_model([Message(role="user", content="test")])

    assert request_model.id == "deepseek-v4-flash-0731"
    assert request_model.max_tokens == 128 * 1024


def test_section_projection_uses_configured_report_input_budget(monkeypatch) -> None:
    phase_model = ReportingPhaseOpenAIChat(id="qwen3.6-flash", api_key="test-key")
    phase_model._task_execution_input_token_budget = 196_608
    observed: dict[str, int] = {}

    def project_with_metrics(messages, **kwargs):
        observed["hard_cap"] = kwargs["hard_cap"]
        return messages, {}

    monkeypatch.setattr(TaskExecutionContextProjector, "project_with_metrics", project_with_metrics)
    with bind_reporting_run_context(_context("section", "section")):
        phase_model._project([Message(role="user", content="test")], (), {})

    assert observed["hard_cap"] == 196_608


@pytest.mark.parametrize(
    "model_id",
    (
        "qwen3.6-flash",
        "qwen3.8-flash",
        "deepseek-v4-flash-0731",
    ),
)
def test_reporting_input_cap_respects_verified_model_window(model_id: str) -> None:
    assert (
        resolve_reporting_input_token_hard_cap(
            configured_input_token_cap=655_360,
            model_id=model_id,
            output_token_reserve=65_536,
            absolute_input_token_cap=1_015_808,
        )
        == 196_608
    )


def test_reporting_input_cap_does_not_guess_unknown_model_window() -> None:
    assert (
        resolve_reporting_input_token_hard_cap(
            configured_input_token_cap=196_608,
            model_id="custom-model-endpoint",
            output_token_reserve=65_536,
            absolute_input_token_cap=1_015_808,
        )
        == 196_608
    )


def test_routed_request_projection_uses_final_model_cap(monkeypatch) -> None:
    context = _context("section", "section")
    context.dependencies[REPORTING_TASK_DEPENDENCY].update(
        {
            REPORTING_MODEL_TIER_DEPENDENCY_KEY: "fast",
            REPORTING_MODEL_ID_DEPENDENCY_KEY: "qwen3.8-flash",
        }
    )
    phase_model = ReportingPhaseOpenAIChat(
        id="custom-model-endpoint",
        api_key="test-key",
        max_tokens=65_536,
    )
    phase_model._task_execution_input_token_budget = 655_360
    observed: dict[str, int] = {}

    def project_with_metrics(messages, **kwargs):
        observed["hard_cap"] = kwargs["hard_cap"]
        return messages, {}

    monkeypatch.setattr(TaskExecutionContextProjector, "project_with_metrics", project_with_metrics)
    with bind_reporting_run_context(context):
        request_model = phase_model._phase_request_model([Message(role="user", content="test")])
        request_model._project([Message(role="user", content="test")], (), {})

    assert request_model.id == "qwen3.8-flash"
    assert observed["hard_cap"] == 229_376


def test_phase_agent_request_keeps_thinking_off_when_task_policy_requests_high() -> None:
    context = _context("analysis", "analysis_item")
    context.dependencies[REPORTING_TASK_DEPENDENCY].update(
        {
            REPORTING_MODEL_TIER_DEPENDENCY_KEY: "strong",
            REPORTING_MODEL_ID_DEPENDENCY_KEY: "deepseek-v4-flash-0731",
            REPORTING_THINKING_EFFORT_DEPENDENCY_KEY: "high",
            REPORTING_THINKING_BUDGET_DEPENDENCY_KEY: 8192,
        }
    )
    phase_model = ReportingPhaseOpenAIChat(id="qwen3.6-35b-a3b", api_key="test-key")

    with bind_reporting_run_context(context):
        request_model = phase_model._phase_request_model([Message(role="user", content="test")])

    assert request_model.id == "deepseek-v4-flash-0731"
    assert request_model.extra_body == {"enable_thinking": False}
    assert request_model.reasoning_effort is None


def test_unknown_task_kind_is_not_projected() -> None:
    contract = {
        "requirements": [
            {"parameters": {"phase": "analysis", "phaseContract": {"taskKind": "unknown"}}}
        ]
    }
    assert reporting_task_kind_from_acceptance_contract(contract) is None


def test_phase_agent_tool_cache_uses_smart_reporting_identity() -> None:
    assert _reporting_tools_cache_key(_context("analysis", "analysis_item")) == (
        "smart-reporting:session-analysis_item:run-analysis_item:analysis:analysis_item"
    )


def test_visualization_instructions_delegate_execution_to_fixed_workflow() -> None:
    instructions = "\n".join(
        build_report_agent_instructions(_context("analysis", "visualization_section"))
    )
    assert "VisualizationPlanDraft" in instructions
    assert "固定 Workflow" in instructions
    assert "submit_visualization_charts" not in instructions


def test_section_instructions_require_h3_before_h4() -> None:
    instructions = "\n".join(build_report_agent_instructions(_context("section", "section")))

    assert "每个 block 的首个子标题必须是三级标题" in instructions
    assert "四级标题只能出现在已有三级标题之后" in instructions


def test_visualization_instruction_theme_projects_report_theme() -> None:
    from smart_reporting.reporting.workflow.runtime.analysis import _visualization_instruction_theme

    assert _visualization_instruction_theme() == REPORT_VISUAL_THEME


def test_capability_matrix_exposes_only_section_visualization_tools() -> None:
    visualization_tools = tools_for_task("analysis", "visualization_section")
    assert visualization_tools is not None
    assert visualization_tools == frozenset(
        {
            "delete_file",
            "edit_file",
            "inspect_chart",
            "list_files",
            "move_file",
            "read_file",
            "read_tool_output",
            "run_command",
            "run_python_script",
            "search_content",
            "submit_visualization_charts",
            "view_image",
            "write_file",
            "apply_analysis_patch",
        }
    )


@pytest.mark.parametrize("tool_name", ("read_file", "apply_analysis_patch"))
def test_coding_runner_single_tool_survives_response_sanitizer(
    monkeypatch: pytest.MonkeyPatch, tool_name: str
) -> None:
    context = _context("analysis", "visualization_section")
    model = ReportingPhaseOpenAIChat(id="test", api_key="test")
    call = {
        "id": "call-1",
        "type": "function",
        "function": {"name": tool_name, "arguments": "{}"},
    }
    assistant = Message(role="assistant", tool_calls=[call])
    observed: list[object] = []
    monkeypatch.setattr(
        model,
        "_run_reporting_tool_calls",
        lambda _assistant, _messages, _functions, calls: observed.extend(calls) or calls,
    )

    with bind_reporting_run_context(context):
        result = model.get_function_calls_to_run(
            assistant,
            [Message(role="user", content="probe")],
            functions={tool_name: object()},
        )

    assert result == [call]
    assert observed == [call]


@pytest.mark.anyio
async def test_visualization_tool_receipt_does_not_project_next_model_action() -> None:
    context = _context("analysis", "visualization_section")

    result = await normalize_reporting_tool_arguments(
        context,
        "read_file",
        lambda **_arguments: {"ok": True, "content": "source"},
        {"path": "charts/charts.py"},
    )

    assert result == {"ok": True, "content": "source"}
    assert "nextTool" not in result
    assert "requiredFields" not in result
    assert "expected_sha256" not in result


def test_visualization_projection_removes_skill_system_message() -> None:
    messages = [
        Message(
            role="system",
            content="before\n<skills_system>removed skills</skills_system>\nafter",
        )
    ]

    with bind_reporting_run_context(_context("analysis", "visualization_section")):
        projected = _phase_filtered_report_messages(messages)

    assert projected[0].content == "before\nafter"
