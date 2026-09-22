from __future__ import annotations

import anyio
import pytest

from smart_reporting import model_routing
from smart_reporting.reporting import model_policy


def test_thinking_policy_api_is_available() -> None:
    assert hasattr(model_policy, "ThinkingRequest")
    assert hasattr(model_policy, "select_reporting_thinking")
    assert hasattr(model_routing, "log_thinking_selection")


ThinkingRequest = getattr(model_policy, "ThinkingRequest", None)
ThinkingDecision = getattr(model_policy, "ThinkingDecision", None)
bind_reporting_thinking = getattr(model_policy, "bind_reporting_thinking", None)
current_reporting_thinking_decision = getattr(
    model_policy, "current_reporting_thinking_decision", None
)
select_reporting_thinking = getattr(model_policy, "select_reporting_thinking", None)
log_thinking_selection = getattr(model_routing, "log_thinking_selection", None)


def _decision(operation: str, budget: int):
    return ThinkingDecision(
        operation=operation,
        complexity="standard",
        enabled=budget > 0,
        reasoning_effort="high" if budget else None,
        thinking_budget=budget,
        attempt=0,
        reason="test",
    )


def test_thinking_binding_restores_nested_and_exception_context() -> None:
    outer = _decision("data_understanding", 2048)
    inner = _decision("analysis_evidence", 4096)

    with bind_reporting_thinking(outer):
        assert current_reporting_thinking_decision() is outer
        with pytest.raises(RuntimeError, match="stop"):
            with bind_reporting_thinking(inner):
                assert current_reporting_thinking_decision() is inner
                raise RuntimeError("stop")
        assert current_reporting_thinking_decision() is outer
    assert current_reporting_thinking_decision() is None


@pytest.mark.anyio
async def test_thinking_binding_is_isolated_between_concurrent_tasks() -> None:
    decisions = (_decision("analysis_evidence", 4096), _decision("visualization_script", 0))
    observed: dict[str, object] = {}

    async def record(name: str, decision) -> None:
        with bind_reporting_thinking(decision):
            await anyio.sleep(0)
            observed[name] = current_reporting_thinking_decision()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(record, "analysis", decisions[0])
        task_group.start_soon(record, "visualization", decisions[1])

    assert observed == {"analysis": decisions[0], "visualization": decisions[1]}


@pytest.mark.parametrize(
    ("operation", "complexity", "budget"),
    [
        ("request_normalization", "standard", 0),
        ("domain_resolution", "standard", 0),
        ("data_understanding", "simple", 2048),
        ("data_understanding", "complex", 2048),
        ("measure_semantics", "standard", 2048),
        ("outline_planning", "complex", 0),
        ("sql_planning", "simple", 2048),
        ("sql_planning", "complex", 2048),
        ("analysis_planning", "complex", 2048),
        ("analysis_evidence", "simple", 1024),
        ("analysis_evidence", "standard", 2048),
        ("analysis_evidence", "complex", 4096),
        ("analysis_summary", "simple", 1024),
        ("analysis_summary", "standard", 2048),
        ("analysis_summary", "complex", 4096),
        ("analysis_script", "simple", 1024),
        ("analysis_script", "standard", 2048),
        ("analysis_script", "complex", 4096),
        ("visualization_plan", "simple", 1024),
        ("visualization_plan", "standard", 2048),
        ("visualization_plan", "complex", 4096),
        ("visualization_script", "simple", 1024),
        ("visualization_script", "standard", 2048),
        ("visualization_script", "complex", 4096),
        ("section_planning", "standard", 2048),
        ("section_generation", "complex", 0),
    ],
)
def test_initial_thinking_budget_matrix(operation: str, complexity: str, budget: int) -> None:
    decision = select_reporting_thinking(
        ThinkingRequest(operation=operation, complexity=complexity)  # type: ignore[arg-type]
    )

    assert decision.thinking_budget == budget
    assert decision.enabled is (budget > 0)
    expected_effort = "low" if operation in {"analysis_script", "visualization_script"} else "high"
    assert decision.reasoning_effort == (expected_effort if budget else None)
    assert decision.reason == ("initial_policy" if budget else "initial_off")


@pytest.mark.parametrize(
    ("operation", "failure_kind", "budget", "effort"),
    [
        ("request_normalization", "schema_failure", 1024, "high"),
        ("data_understanding", "schema_failure", 4096, "high"),
        ("data_understanding", "capability_mapping_failure", 4096, "high"),
        ("measure_semantics", "schema_failure", 4096, "high"),
        ("outline_planning", "schema_failure", 2048, "high"),
        ("sql_planning", "sql_validation_failure", 4096, "high"),
        ("analysis_planning", "schema_failure", 4096, "high"),
        ("analysis_evidence", "evidence_incomplete", 6144, "max"),
        ("analysis_evidence", "fact_incomplete", 6144, "max"),
        ("analysis_script", "python_compile_failure", 2048, "high"),
        ("analysis_script", "python_execution_failure", 2048, "high"),
        ("visualization_plan", "schema_failure", 4096, "high"),
        ("visualization_script", "python_compile_failure", 4096, "high"),
        ("visualization_script", "python_execution_failure", 4096, "high"),
        ("visualization_script", "visual_review_failure", 8192, "high"),
        ("section_planning", "schema_failure", 2048, "high"),
        ("section_generation", "schema_failure", 2048, "high"),
    ],
)
def test_recoverable_failure_upgrades_once(
    operation: str,
    failure_kind: str,
    budget: int,
    effort: str,
) -> None:
    decision = select_reporting_thinking(
        ThinkingRequest(
            operation=operation,  # type: ignore[arg-type]
            attempt=1,
            failure_kind=failure_kind,  # type: ignore[arg-type]
        )
    )

    assert decision.thinking_budget == budget
    assert decision.reasoning_effort == effort
    assert decision.reason == failure_kind


@pytest.mark.parametrize("failure_kind", ["transient", "semantic_warning"])
def test_non_reasoning_failure_keeps_initial_budget(failure_kind: str) -> None:
    decision = select_reporting_thinking(
        ThinkingRequest(
            operation="sql_planning",
            attempt=1,
            failure_kind=failure_kind,  # type: ignore[arg-type]
        )
    )

    assert decision.thinking_budget == 2048
    assert decision.reason == "retry_same_budget"


def test_later_attempt_cannot_raise_budget_again() -> None:
    decision = select_reporting_thinking(
        ThinkingRequest(
            operation="analysis_evidence",
            complexity="simple",
            attempt=2,
            failure_kind="evidence_incomplete",
        )
    )

    assert decision.thinking_budget == 1024
    assert decision.reasoning_effort == "high"
    assert decision.reason == "retry_limit_reached"


def test_configured_budget_is_only_a_hard_cap() -> None:
    decision = select_reporting_thinking(
        ThinkingRequest(
            operation="analysis_evidence",
            complexity="complex",
            attempt=1,
            failure_kind="fact_incomplete",
            configured_budget_cap=1536,
        )
    )

    assert decision.thinking_budget == 1536
    assert decision.reasoning_effort == "max"


def test_global_switch_disables_thinking_without_residual_budget() -> None:
    decision = select_reporting_thinking(
        ThinkingRequest(
            operation="sql_planning",
            attempt=1,
            failure_kind="sql_validation_failure",
            thinking_enabled=False,
        )
    )

    assert decision.enabled is False
    assert decision.reasoning_effort is None
    assert decision.thinking_budget == 0
    assert decision.reason == "thinking_disabled"


@pytest.mark.parametrize("budget_cap", [True, 0, -1])
def test_invalid_budget_cap_fails_closed(budget_cap: object) -> None:
    with pytest.raises(ValueError, match="configured_budget_cap"):
        ThinkingRequest(
            operation="sql_planning",
            configured_budget_cap=budget_cap,  # type: ignore[arg-type]
        )


def test_thinking_log_contains_only_stable_decision_fields(monkeypatch) -> None:
    recorded: list[tuple[str, tuple[object, ...]]] = []

    class FakeLogger:
        def info(self, template: str, *args: object) -> None:
            recorded.append((template, args))

    monkeypatch.setattr("smart_reporting.model_routing.observability.logger", FakeLogger())
    decision = select_reporting_thinking(
        ThinkingRequest(operation="data_understanding", complexity="complex")
    )

    log_thinking_selection(decision.event_fields())

    assert recorded == [
        (
            "report_thinking_selected operation={} complexity={} enabled={} effort={} "
            "budget={} attempt={} reason={} policy_version={}",
            (
                "data_understanding",
                "complex",
                True,
                "high",
                2048,
                0,
                "initial_policy",
                "v1",
            ),
        )
    ]
