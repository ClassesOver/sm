from __future__ import annotations

import pytest
from agno.models.message import Message
from agno.run import RunContext

from smart_reporting.context_management import TaskExecutionContextProjector
from smart_reporting.reporting.agent import (
    ReportingPhaseOpenAIChat,
    _phase_filtered_report_messages,
    _phase_filtered_report_tools,
    _reporting_tools_cache_key,
    _visualization_history_state,
    normalize_reporting_tool_arguments,
)
from smart_reporting.reporting.delivery.report_runtime import REPORT_VISUAL_THEME
from smart_reporting.reporting.instructions import build_report_agent_instructions
from smart_reporting.reporting.model_policy import resolve_reporting_input_token_hard_cap
from smart_reporting.reporting.phase import (
    REPORTING_MODEL_ID_DEPENDENCY_KEY,
    REPORTING_MODEL_TIER_DEPENDENCY_KEY,
    REPORTING_PHASE_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
    REPORTING_TASK_KIND_DEPENDENCY_KEY,
    REPORTING_THINKING_BUDGET_DEPENDENCY_KEY,
    REPORTING_THINKING_EFFORT_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_SCRIPT_EXECUTED_STATE_KEY,
    REPORTING_VISUALIZATION_SCRIPT_WRITTEN_STATE_KEY,
    bind_reporting_run_context,
    reporting_python_script_failed,
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
    ("phase", "task_kind", "expected"),
    (
        ("analysis", "analysis_item", "auto"),
        ("analysis", "visualization_section", "required"),
        ("section", "section", "auto"),
    ),
)
def test_phase_agent_only_requires_a_tool_call_for_visualization_first_round(
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


def test_visualization_instructions_require_section_submission() -> None:
    instructions = "\n".join(
        build_report_agent_instructions(_context("analysis", "visualization_section"))
    )
    assert "submit_visualization_charts" in instructions
    assert "章节" in instructions
    assert "reportVisualTheme" in instructions
    assert "颜色不得成为唯一信息通道" in instructions


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
            "inspect_chart",
            "read_file",
            "read_tool_output",
            "submit_visualization_charts",
            "run_python_script",
            "view_image",
            "apply_analysis_patch",
        }
    )


def test_visualization_initial_projection_hides_read_tools() -> None:
    visible = _visible_tool_names(_context("analysis", "visualization_section"))

    assert {"read_file", "read_tool_output"}.isdisjoint(visible)


def test_visualization_written_script_projection_exposes_controlled_runner() -> None:
    context = _context("analysis", "visualization_section")
    context.session_state[REPORTING_VISUALIZATION_SCRIPT_WRITTEN_STATE_KEY] = True

    visible = _visible_tool_names(context)

    assert "run_python_script" in visible


def test_visualization_history_recognizes_controlled_runner_completion() -> None:
    messages = [
        Message(
            role="tool",
            tool_name="run_python_script",
            tool_call_id="call-1",
            content='{"ok":true,"status":"completed","exitCode":0}',
        )
    ]

    assert _visualization_history_state(messages) == (False, False, True)


def test_visualization_history_rejects_controlled_runner_failure_marker() -> None:
    messages = [
        Message(
            role="tool",
            tool_name="run_python_script",
            tool_call_id="call-1",
            content=(
                '{"ok":true,"status":"completed","exitCode":0,'
                '"output":"[FAIL] chart.png: image is blank"}'
            ),
        )
    ]

    assert _visualization_history_state(messages) == (False, False, False)


def test_visualization_failure_budget_counts_controlled_runner_failure() -> None:
    assert reporting_python_script_failed(
        {"ok": False, "status": "failed", "exit_code": 1, "output": "boom"}
    )


@pytest.mark.parametrize(
    "output",
    (
        "[FAIL] chart.png: image is blank",
        "chart.png: ERROR image is blank",
    ),
)
def test_visualization_failure_recognizes_protocol_markers(output: str) -> None:
    assert reporting_python_script_failed(
        {"ok": True, "status": "completed", "exitCode": 0, "output": output}
    )


def test_visualization_failure_checks_both_exit_code_fields() -> None:
    assert reporting_python_script_failed(
        {"ok": True, "status": "completed", "exitCode": None, "exit_code": 1}
    )


def test_visualization_rejection_does_not_count_as_script_execution_failure() -> None:
    assert not reporting_python_script_failed(
        {"ok": False, "status": "rejected", "code": "report_capability_invalid"}
    )


def test_visualization_missing_glyph_warning_does_not_count_as_script_failure() -> None:
    assert not reporting_python_script_failed(
        {
            "ok": True,
            "status": "completed",
            "exitCode": 0,
            "output": "UserWarning: Glyph 25910 missing from font(s) DejaVu Sans.",
        }
    )


@pytest.mark.anyio
async def test_visualization_failure_marker_does_not_set_executed_state() -> None:
    context = _context("analysis", "visualization_section")

    result = await normalize_reporting_tool_arguments(
        context,
        "run_python_script",
        lambda **_arguments: {
            "ok": True,
            "status": "completed",
            "exitCode": 0,
            "output": "[FAIL] chart.png: image is blank",
        },
        {"script_path": "charts/charts.py"},
    )

    assert result["ok"] is True
    assert REPORTING_VISUALIZATION_SCRIPT_EXECUTED_STATE_KEY not in context.session_state


def test_visualization_recovery_projection_exposes_signed_script_reads() -> None:
    context = _context("analysis", "visualization_section")
    context.dependencies[REPORTING_TASK_DEPENDENCY][
        REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY
    ] = True

    visible = _visible_tool_names(context)

    assert {"read_file", "read_tool_output"}.issubset(visible)
    assert "view_image" not in visible


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
