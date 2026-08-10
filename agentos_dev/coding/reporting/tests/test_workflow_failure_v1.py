from __future__ import annotations

from typing import Any

import pytest
from agno.db.in_memory import InMemoryDb
from agno.models.metrics import RunMetrics
from agno.workflow import OnError
from agno.workflow.types import StepInput, StepOutput

from agentos_dev.coding.reporting.workflow import orchestration as orchestration_module
from agentos_dev.coding.reporting.workflow.orchestration import (
    create_reporting_workflow,
    record_step_model_metrics,
)


def _workflow(first_step: Any, later_step: Any, *, event_sink=None):
    return create_reporting_workflow(
        db=InMemoryDb(),
        event_sink=event_sink,
        normalize_report_request=first_step,
        confirm_source=first_step,
        plan_data_scope=later_step,
        profile_source=later_step,
        propose_measure_semantics=later_step,
        commit_measure_semantics=later_step,
        resolve_capabilities=later_step,
        reconcile_sources=later_step,
        generate_outline=later_step,
        generate_analysis_plan=later_step,
        generate_query_candidates=later_step,
        materialize_datasets=later_step,
        prepare_analysis_context=later_step,
        generate_detailed_analysis_plan=later_step,
        run_coding_analysis=later_step,
        validate_report=later_step,
        publish_report=later_step,
        finalize_publication=later_step,
    )


@pytest.mark.anyio
async def test_步骤失败后工作流终止且不进入后续审核():
    later_calls = 0

    async def fail(_step_input: StepInput) -> StepOutput:
        raise RuntimeError("schema failure")

    async def later(_step_input: StepInput) -> StepOutput:
        nonlocal later_calls
        later_calls += 1
        return StepOutput(content={})

    workflow = _workflow(fail, later)
    workflow.steps[0].max_retries = 0

    with pytest.raises(RuntimeError, match="schema failure"):
        await workflow.arun({"version": "1", "prompt": "report request"})

    assert later_calls == 0
    assert workflow.steps[13].requires_output_review is True


def test_所有报表步骤都显式失败关闭且请求与提纲启用审核():
    def execute(_step_input: StepInput) -> StepOutput:
        return StepOutput(content={})

    workflow = _workflow(execute, execute)

    assert len(workflow.steps) == 18
    assert [step.step_id for step in workflow.steps] == [
        "normalize-report-request",
        "confirm-source",
        "plan-data-scope",
        "profile-source",
        "propose-measure-semantics",
        "commit-measure-semantics",
        "resolve-capabilities",
        "reconcile-sources",
        "generate-analysis-plan",
        "generate-query-candidates",
        "materialize-datasets",
        "prepare-analysis-context",
        "generate-detailed-analysis-plan",
        "generate-outline",
        "run-coding-analysis",
        "validate-report",
        "publish-report",
        "finalize-publication",
    ]
    assert all(step.on_error == OnError.fail for step in workflow.steps)
    assert workflow.steps[2].name == "生成数据理解计划"
    assert workflow.steps[2].max_retries == 0
    assert workflow.steps[8].name == "生成分析计划与取数需求"
    assert workflow.steps[8].max_retries == 0
    assert workflow.steps[9].name == "生成并审核取数方案"
    assert workflow.steps[9].max_retries == 0
    assert workflow.steps[14].name == "Coding 分析与成稿"
    assert workflow.steps[14].max_retries == 0
    assert workflow.steps[15].max_retries == 0
    review_steps = [step for step in workflow.steps if bool(step.requires_output_review)]
    assert [step.step_id for step in review_steps] == [
        "normalize-report-request",
        "generate-outline",
    ]
    assert workflow.steps[13].human_review is not None
    assert workflow.steps[13].human_review.max_retries == 5


@pytest.mark.anyio
async def test_function步骤记录执行耗时且保留已有metrics(monkeypatch):
    times = iter((10.0, 11.25))
    monkeypatch.setattr(orchestration_module, "perf_counter", lambda: next(times))

    async def execute(_step_input: StepInput) -> StepOutput:
        return StepOutput(content={"ok": True}, metrics=RunMetrics(total_tokens=42))

    workflow = _workflow(execute, execute)
    result = await workflow.steps[0].executor(StepInput(input={}))

    assert result.content == {"ok": True}
    assert result.metrics is not None
    assert result.metrics.duration == 1.25
    assert result.metrics.total_tokens == 42


@pytest.mark.anyio
async def test_function步骤计时不改变异常语义(monkeypatch):
    times = iter((20.0, 20.5))
    monkeypatch.setattr(orchestration_module, "perf_counter", lambda: next(times))

    async def fail(_step_input: StepInput) -> StepOutput:
        raise RuntimeError("step failed")

    workflow = _workflow(fail, fail)

    with pytest.raises(RuntimeError, match="step failed"):
        await workflow.steps[0].executor(StepInput(input={}))


@pytest.mark.anyio
async def test_function步骤实时发布开始和完成事件(monkeypatch):
    times = iter((30.0, 30.4))
    events: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(orchestration_module, "perf_counter", lambda: next(times))

    async def sink(_run_context, event_type: str, data: dict[str, Any]) -> None:
        events.append((event_type, data))

    async def execute(_step_input: StepInput, _run_context) -> StepOutput:
        record_step_model_metrics(RunMetrics(input_tokens=30, output_tokens=12, total_tokens=42))
        return StepOutput(content={"ok": True})

    workflow = _workflow(execute, execute, event_sink=sink)
    run_context = object()
    await workflow.steps[0].executor(StepInput(input={}), run_context)

    assert events == [
        (
            "workflow_step_started",
            {
                "stepId": "normalize-report-request",
                "stepName": "规范化报表请求",
                "executorName": "execute",
            },
        ),
        (
            "workflow_step_completed",
            {
                "stepId": "normalize-report-request",
                "stepName": "规范化报表请求",
                "executorName": "execute",
                "metrics": {
                    "input_tokens": 30,
                    "output_tokens": 12,
                    "total_tokens": 42,
                    "duration": pytest.approx(0.4),
                },
            },
        ),
    ]
