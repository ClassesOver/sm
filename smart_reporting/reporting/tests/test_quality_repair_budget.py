"""New quality work uses durable CAS receipts and monotonically consumed slots."""

import pytest

from smart_reporting.reporting.tests.test_reporting_state import initial_state
from smart_reporting.reporting.workflow.state import ReportingPhase, ReportingStateError, apply


def command(state, name, **payload):
    return apply(
        state,
        {"name": name, "commandId": f"{name}:{state.state_version}", "payload": payload},
        expected_version=state.state_version,
    )


def test_reserved_attempt_replay_never_authorizes_a_second_execution():
    state = initial_state()
    first = command(state, "reserve_quality_attempt", attemptId="audit-1", kind="semantic_audit")
    assert [effect.kind for effect in first.effects] == ["quality_attempt_reserved"]
    restored = type(state).model_validate_json(first.state.model_dump_json(by_alias=True))
    replay = command(
        restored, "reserve_quality_attempt", attemptId="audit-1", kind="semantic_audit"
    )
    assert replay.effects == ()
    with pytest.raises(ReportingStateError, match="预算"):
        command(replay.state, "reserve_quality_attempt", attemptId="audit-2", kind="semantic_audit")


@pytest.mark.parametrize("status", ["failed", "unknown", "succeeded"])
def test_failed_and_unknown_attempts_are_consumed_after_restore(status):
    state = command(
        initial_state(),
        "reserve_quality_attempt",
        attemptId="one",
        kind="supplement",
        questionId="q1",
    ).state
    state = command(state, "settle_quality_attempt", attemptId="one", status=status).state
    state = type(state).model_validate_json(state.model_dump_json(by_alias=True))
    with pytest.raises(ReportingStateError, match="预算"):
        command(
            state, "reserve_quality_attempt", attemptId="two", kind="supplement", questionId="q1"
        )
    state = command(
        state, "reserve_quality_attempt", attemptId="two", kind="supplement", questionId="q2"
    ).state
    with pytest.raises(ReportingStateError, match="预算"):
        command(
            state, "reserve_quality_attempt", attemptId="three", kind="supplement", questionId="q3"
        )
    assert len(state.payload["qualityBudget"]["attempts"]) == 2


def test_attempt_identity_and_terminal_result_cannot_be_repurposed():
    state = command(
        initial_state(),
        "reserve_quality_attempt",
        attemptId="one",
        kind="supplement",
        questionId="q1",
    ).state
    with pytest.raises(ReportingStateError, match="不同"):
        command(
            state, "reserve_quality_attempt", attemptId="one", kind="supplement", questionId="q2"
        )
    state = command(state, "settle_quality_attempt", attemptId="one", status="failed").state
    with pytest.raises(ReportingStateError, match="不可改写"):
        command(state, "settle_quality_attempt", attemptId="one", status="succeeded")


def test_rework_reservation_and_invalidation_are_atomic():
    state = initial_state().model_copy(
        update={
            "phase": ReportingPhase.SECTIONS,
            "payload": {
                "analysisIds": ["a1", "a2", "a3"],
                "completedAnalysisIds": ["a1", "a2", "a3"],
                "analysisPlans": {
                    "a1": {"questionId": "q1"},
                    "a2": {"questionId": "q2"},
                    "a3": {"questionId": "q3"},
                },
                "analysisItems": {key: {"summary": key} for key in ("a1", "a2", "a3")},
            },
        }
    )
    before = state.model_dump_json()
    with pytest.raises(ReportingStateError, match="预算"):
        command(
            state,
            "request_analysis_rework",
            analysisIds=["a1", "a2", "a3"],
            missingEvidence=["required"],
            qualityRepair={"attemptId": "batch"},
        )
    assert state.model_dump_json() == before
    result = command(
        state,
        "request_analysis_rework",
        analysisIds=["a1", "a2"],
        missingEvidence=["required"],
        qualityRepair={"attemptId": "batch"},
    )
    assert result.state.payload["completedAnalysisIds"] == ["a3"]
    assert len(result.state.payload["qualityBudget"]["attempts"]) == 2
    assert sum(effect.kind == "quality_attempt_reserved" for effect in result.effects) == 2
    with pytest.raises(ReportingStateError, match="预算"):
        command(
            result.state,
            "request_analysis_rework",
            analysisIds=["a3"],
            missingEvidence=["required"],
            qualityRepair={"attemptId": "another-batch"},
        )
    assert result.state.payload["completedAnalysisIds"] == ["a3"]


def test_two_analyses_cannot_evade_same_question_budget():
    state = initial_state().model_copy(
        update={
            "phase": ReportingPhase.SECTIONS,
            "payload": {
                "analysisIds": ["a1", "a2"],
                "completedAnalysisIds": ["a1", "a2"],
                "analysisPlans": {"a1": {"questionId": "same"}, "a2": {"questionId": "same"}},
                "analysisItems": {"a1": {"summary": "original-1"}, "a2": {"summary": "original-2"}},
            },
        }
    )
    with pytest.raises(ReportingStateError, match="预算"):
        command(
            state,
            "request_analysis_rework",
            analysisIds=["a1", "a2"],
            missingEvidence=["required"],
            qualityRepair={"attemptId": "batch"},
        )
    assert "qualityBudget" not in state.payload


@pytest.mark.parametrize("status", ["failed", "unknown"])
def test_failed_repair_restores_only_missing_baseline_after_restart(status):
    state = initial_state().model_copy(
        update={
            "phase": ReportingPhase.SECTIONS,
            "payload": {
                "analysisIds": ["a1", "a2"],
                "completedAnalysisIds": ["a1", "a2"],
                "analysisPlans": {"a1": {"questionId": "q1"}},
                "analysisItems": {"a1": {"summary": "original"}, "a2": {"summary": "independent"}},
                "completedSections": ["s1"],
                "sectionArtifacts": {"s1": {"analysisIds": ["a1"]}},
            },
        }
    )
    state = command(
        state,
        "request_analysis_rework",
        sectionCode="s1",
        analysisIds=["a1"],
        missingEvidence=["baseline"],
        qualityRepair={"attemptId": "batch"},
    ).state
    state = type(state).model_validate_json(state.model_dump_json(by_alias=True))
    attempt_id = state.payload["qualityRepairOwners"]["a1"]
    restored = command(state, "settle_quality_attempt", attemptId=attempt_id, status=status)
    assert restored.state.payload["analysisItems"] == {
        "a1": {"summary": "original"},
        "a2": {"summary": "independent"},
    }
    assert set(restored.state.payload["completedAnalysisIds"]) == {"a1", "a2"}
    assert restored.state.payload["completedSections"] == []
    assert restored.state.payload["sectionArtifacts"] == {}
    replay = command(restored.state, "settle_quality_attempt", attemptId=attempt_id, status=status)
    assert replay.effects == ()
    with pytest.raises(ReportingStateError, match="不可再次"):
        command(
            replay.state,
            "request_analysis_rework",
            sectionCode="s1",
            analysisIds=["a1"],
            missingEvidence=["baseline"],
            qualityRepair={"attemptId": "batch"},
        )


def test_failed_repair_does_not_overwrite_committed_evidence():
    state = initial_state().model_copy(
        update={
            "phase": ReportingPhase.SECTIONS,
            "payload": {
                "analysisIds": ["a1"],
                "completedAnalysisIds": ["a1"],
                "analysisItems": {"a1": {"summary": "baseline"}},
            },
        }
    )
    state = command(
        state,
        "request_analysis_rework",
        analysisIds=["a1"],
        missingEvidence=["required"],
        qualityRepair={"attemptId": "batch"},
    ).state
    state = command(state, "complete_analysis_item", analysisId="a1", summary="new committed").state
    attempt_id = state.payload["qualityRepairOwners"]["a1"]
    result = command(state, "settle_quality_attempt", attemptId=attempt_id, status="failed")
    assert result.state.payload["analysisItems"]["a1"]["summary"] == "new committed"
    assert not any(effect.kind == "quality_baseline_restored" for effect in result.effects)


@pytest.mark.anyio
@pytest.mark.parametrize("outcome", ["failed", "cancelled", "completed_before_restart"])
async def test_runtime_recovery_uses_reserved_contract_and_never_refills_budget(outcome):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from agno.run import RunContext

    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.checkpoint import AnalysisReworkRequest, payload_sha256
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime

    request = AnalysisReworkRequest(
        sectionCode="s1", analysisIds=("a1",), reason="需要同比基期", missingEvidence=("基期",)
    )
    digest = payload_sha256(request.model_dump(mode="json", by_alias=True))
    prefix = "1:" + digest
    state = initial_state().model_copy(
        update={
            "phase": ReportingPhase.SECTIONS,
            "payload": {
                "analysisIds": ["a1"],
                "completedAnalysisIds": ["a1"],
                "analysisItems": {"a1": {"summary": "baseline"}},
            },
        }
    )
    state = command(
        state,
        "request_analysis_rework",
        **request.model_dump(mode="json", by_alias=True),
        qualityRepair={"attemptId": prefix},
    ).state
    state = type(state).model_validate_json(state.model_dump_json(by_alias=True))
    attempt_id = state.payload["qualityRepairOwners"]["a1"]
    trace = ()
    if outcome == "completed_before_restart":
        state = command(state, "complete_analysis_item", analysisId="a1", summary="candidate").state
        trace = (
            SimpleNamespace(
                phase="analysis",
                work_kind="analysis_item",
                analysis_id="a1",
                retry_reason="analysis_rework:" + digest,
                status="completed",
            ),
        )
    checkpoint = SimpleNamespace(trace=trace)
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._scope = lambda _context: {"externalRunId": "run", "threadId": "thread"}
    runtime.state_repository = SimpleNamespace(get=AsyncMock(side_effect=lambda _run: state))
    runtime._current_reporting_checkpoint = AsyncMock(return_value=checkpoint)
    runtime._execute_analysis_item_task = AsyncMock(
        side_effect=(
            asyncio.CancelledError()
            if outcome == "cancelled"
            else ReportingError("report_analysis_script_failed", "failed")
        )
    )

    async def apply_command(_context, cmd):
        nonlocal state
        state = apply(state, cmd, expected_version=state.state_version).state

    runtime._apply_durable_command = apply_command
    context = RunContext(run_id="run", session_id="thread")
    kwargs = dict(
        checkpoint=checkpoint, revision=1, analysis_id="a1", retry_reason=None, rework_request=None
    )
    if outcome == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await runtime._run_analysis_item_task(context, **kwargs)
    else:
        await runtime._run_analysis_item_task(context, **kwargs)
    expected = {
        "failed": "failed",
        "cancelled": "unknown",
        "completed_before_restart": "succeeded",
    }[outcome]
    assert state.payload["qualityBudget"]["attempts"][attempt_id]["status"] == expected
    assert len(state.payload["qualityBudget"]["attempts"]) == 1
    if outcome == "completed_before_restart":
        runtime._execute_analysis_item_task.assert_not_awaited()
        assert state.payload["analysisItems"]["a1"]["summary"] == "candidate"
    else:
        assert state.payload["analysisItems"]["a1"]["summary"] == "baseline"
        submitted = runtime._execute_analysis_item_task.await_args.kwargs
        assert submitted["retry_reason"] == "analysis_rework:" + digest
        assert submitted["rework_request"] == request
        assert state.payload["warnings"][0]["code"] == "report_quality_supplement_failed"
    calls = runtime._execute_analysis_item_task.await_count
    await runtime._run_analysis_item_task(context, **kwargs)
    assert runtime._execute_analysis_item_task.await_count == calls


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_budget_rejection_survives_durable_command_error_translation(anyio_backend):
    # 审阅：reducer 的预算拒绝经 _apply_durable_command 转成 ReportingError，rework_analysis 只捕获
    # ReportingStateError，降级为 budget_exhausted 的分支永远不执行，整份报告失败。
    import asyncio
    from types import SimpleNamespace

    from agno.run import RunContext

    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.runtime.analysis import quality_budget_code
    from smart_reporting.reporting.workflow.runtime.base import _ReportWorkflowRuntimeBase

    durable = SimpleNamespace(report_run_id="run", state_version=1)

    async def get(_run):
        return durable

    async def reject(*_args, **_kwargs):
        raise ReportingStateError("report_quality_budget_exhausted", "新增质量工作预算已耗尽。")

    runtime = SimpleNamespace(
        _scope=lambda _context: {"externalRunId": "run", "callerThreadId": "t", "userId": "u"},
        state_repository=SimpleNamespace(get_by_external_run_id=get, apply=reject),
        _durable_command_lock=asyncio.Lock(),
    )
    with pytest.raises(ReportingError) as caught:
        await _ReportWorkflowRuntimeBase._apply_durable_command(
            runtime, RunContext(run_id="run", session_id="t"), SimpleNamespace(name="request_analysis_rework"),
        )
    assert quality_budget_code(caught.value) == "report_quality_budget_exhausted"
    assert quality_budget_code(ReportingStateError("report_quality_baseline_unavailable", "x")) == (
        "report_quality_baseline_unavailable"
    )
    assert quality_budget_code(ReportingError("report_state_conflict", "x")) is None
