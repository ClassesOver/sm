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
    assert workflow.steps[8].requires_output_review is True


def test_所有报表步骤都显式失败关闭且只有提纲暂停审核():
    def execute(_step_input: StepInput) -> StepOutput:
        return StepOutput(content={})

    workflow = _workflow(execute, execute)

    assert len(workflow.steps) == 16
    assert [step.step_id for step in workflow.steps] == [
        "normalize-report-request",
        "confirm-source",
        "plan-data-scope",
        "profile-source",
        "propose-measure-semantics",
        "commit-measure-semantics",
        "resolve-capabilities",
        "reconcile-sources",
        "generate-outline",
        "generate-analysis-plan",
        "generate-query-candidates",
        "materialize-datasets",
        "run-coding-analysis",
        "validate-report",
        "publish-report",
        "finalize-publication",
    ]
    assert all(step.on_error == OnError.fail for step in workflow.steps)
    assert workflow.steps[2].name == "生成数据理解计划"
    assert workflow.steps[2].max_retries == 0
    assert workflow.steps[9].name == "生成分析计划与取数需求"
    assert workflow.steps[9].max_retries == 0
    assert workflow.steps[10].name == "生成并审核取数方案"
    assert workflow.steps[10].max_retries == 0
    assert workflow.steps[12].name == "Coding 分析与成稿"
    assert workflow.steps[12].max_retries == 0
    assert workflow.steps[13].max_retries == 0
    review_steps = [step for step in workflow.steps if bool(step.requires_output_review)]
    assert [step.step_id for step in review_steps] == ["generate-outline"]
    assert review_steps[0].human_review.max_retries == 5
