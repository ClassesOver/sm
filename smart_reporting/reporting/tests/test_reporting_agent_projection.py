from __future__ import annotations

import pytest
from agno.models.message import Message
from agno.run import RunContext

from smart_reporting.reporting.agent import (
    ReportingPhaseOpenAIChat,
    _phase_filtered_report_messages,
    _phase_filtered_report_tools,
)
from smart_reporting.reporting.delivery.report_runtime import REPORT_VISUAL_THEME
from smart_reporting.reporting.instructions import build_report_agent_instructions
from smart_reporting.reporting.phase import (
    REPORTING_MODEL_ID_DEPENDENCY_KEY,
    REPORTING_MODEL_TIER_DEPENDENCY_KEY,
    REPORTING_PHASE_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
    REPORTING_TASK_KIND_DEPENDENCY_KEY,
    REPORTING_THINKING_BUDGET_DEPENDENCY_KEY,
    REPORTING_THINKING_EFFORT_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY,
    bind_reporting_run_context,
    reporting_task_kind_from_acceptance_contract,
    reporting_task_kind_from_run_context,
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


def _visible_tool_names(context: RunContext) -> set[str]:
    source_tools = [
        {"function": {"name": name}}
        for name in tools_for_task("analysis", "visualization_section") or ()
    ]
    with bind_reporting_run_context(context):
        return {
            tool["function"]["name"]
            for tool in _phase_filtered_report_tools(
                [Message(role="user", content="probe")], source_tools
            )
        }


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
    ("phase", "task_kind"),
    (
        ("analysis", "analysis_item"),
        ("analysis", "visualization_section"),
        ("section", "section"),
    ),
)
def test_phase_agent_requires_a_tool_call_for_first_task_round(phase: str, task_kind: str) -> None:
    with bind_reporting_run_context(_context(phase, task_kind)):
        assert ReportingPhaseOpenAIChat._phase_request_kwargs(
            [Message(role="user", content="probe")], {"tool_choice": "auto"}
        ) == {"tool_choice": "required"}


@pytest.mark.parametrize(
    ("phase", "task_kind", "expected"),
    (
        ("analysis", "analysis_item", "auto"),
        ("analysis", "visualization_section", "required"),
        ("section", "section", "auto"),
    ),
)
def test_phase_agent_allows_non_visualization_tasks_to_finish_after_tool_history(
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


def test_visualization_instructions_require_section_submission() -> None:
    instructions = "\n".join(
        build_report_agent_instructions(_context("analysis", "visualization_section"))
    )
    assert "submit_visualization_charts" in instructions
    assert "章节" in instructions
    assert "reportVisualTheme" in instructions
    assert "颜色不得成为唯一信息通道" in instructions


def test_visualization_instruction_theme_projects_report_theme() -> None:
    from smart_reporting.reporting.workflow.runtime.analysis import _visualization_instruction_theme

    assert _visualization_instruction_theme() == REPORT_VISUAL_THEME


def test_capability_matrix_exposes_only_section_visualization_tools() -> None:
    visualization_tools = tools_for_task("analysis", "visualization_section")
    assert visualization_tools is not None
    assert visualization_tools == frozenset(
        {
            "inspect_chart",
            "process",
            "read_file",
            "read_tool_output",
            "submit_visualization_charts",
            "terminal",
            "view_image",
            "apply_analysis_patch",
        }
    )


def test_visualization_initial_projection_hides_read_and_process_tools() -> None:
    visible = _visible_tool_names(_context("analysis", "visualization_section"))

    assert {"read_file", "read_tool_output", "process"}.isdisjoint(visible)


def test_visualization_session_projection_exposes_only_process_addition() -> None:
    context = _context("analysis", "visualization_section")
    context.session_state["reportingVisualizationSessions"] = ["session-1"]

    visible = _visible_tool_names(context)

    assert "process" in visible
    assert {"read_file", "read_tool_output"}.isdisjoint(visible)


def test_visualization_recovery_projection_exposes_signed_script_reads() -> None:
    context = _context("analysis", "visualization_section")
    context.dependencies[REPORTING_TASK_DEPENDENCY][
        REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY
    ] = True

    visible = _visible_tool_names(context)

    assert {"read_file", "read_tool_output"}.issubset(visible)
    assert {"process", "view_image"}.isdisjoint(visible)


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
