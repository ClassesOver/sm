from __future__ import annotations

from typing import Any

import pytest
from agno.db.in_memory import InMemoryDb
from agno.workflow import OnError
from agno.workflow.types import StepInput, StepOutput

from agentos_dev.coding.reporting.workflow import create_reporting_workflow


def _workflow(first_step: Any, later_step: Any):
    return create_reporting_workflow(
        db=InMemoryDb(),
        confirm_source=first_step,
        plan_data_scope=later_step,
        profile_source=later_step,
        resolve_capabilities=later_step,
        reconcile_sources=later_step,
        generate_outline=later_step,
        generate_analysis_plan=later_step,
        generate_query_candidates=later_step,
        materialize_datasets=later_step,
        run_coding_analysis=later_step,
        validate_report=later_step,
        publish_report=later_step,
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
        await workflow.arun("report request")

    assert later_calls == 0
    assert workflow.steps[5].requires_output_review is True


def test_所有报表步骤都显式失败关闭():
    def execute(_step_input: StepInput) -> StepOutput:
        return StepOutput(content={})

    workflow = _workflow(execute, execute)

    assert len(workflow.steps) == 12
    assert all(step.on_error == OnError.fail for step in workflow.steps)
    assert workflow.steps[1].name == "生成数据理解计划"
    assert workflow.steps[1].max_retries == 0
    assert workflow.steps[6].name == "生成分析计划与取数需求"
    assert workflow.steps[6].max_retries == 0
    assert workflow.steps[7].name == "生成并审核取数方案"
    assert workflow.steps[7].max_retries == 0
    assert workflow.steps[9].name == "Coding 分析与成稿"
    assert workflow.steps[9].max_retries == 0
    assert workflow.steps[10].max_retries == 0
    review_steps = [workflow.steps[index] for index in (0, 5, 7, 11)]
    assert [step.name for step in review_steps] == [
        "解析数据来源与 Schema",
        "生成报告提纲",
        "生成并审核取数方案",
        "发布审核",
    ]
    review_retries = []
    for step in review_steps:
        assert step.human_review is not None
        review_retries.append(step.human_review.max_retries)
    assert review_retries == [5, 5, 5, 5]
