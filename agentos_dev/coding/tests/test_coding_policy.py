from datetime import timedelta

from agentos_dev.coding import (
    AttemptOutcome,
    AttemptSnapshot,
    AttemptState,
    CodingScope,
    ContinuationAction,
    ContinuationPolicy,
    TaskSnapshot,
    TaskState,
)
from agentos_dev.task_execution.models import utcnow


def snapshots(**task_overrides):
    now = utcnow()
    task_values = {
        "scope": CodingScope("run", "user", "thread", "sandbox", "coding-agent"),
        "state": TaskState.ACTIVE,
        "state_version": 1,
        "lease_epoch": 1,
        "continuation_count": 0,
        "instruction_sequence": 1,
        "current_internal_run_id": "internal-0",
        "current_attempt_no": 0,
        "deadline_at": now + timedelta(hours=1),
    }
    task_values.update(task_overrides)
    task = TaskSnapshot(**task_values)
    attempt = AttemptSnapshot(
        internal_run_id=task.current_internal_run_id,
        external_run_id=task.scope.external_run_id,
        attempt_no=task.current_attempt_no,
        state=AttemptState.PAUSED,
        resume_count=0,
        lease_epoch=task.lease_epoch,
        outcome=AttemptOutcome.NO_FINISH,
    )
    return now, task, attempt


def test_policy_priority_cancel_then_finish_then_deadline():
    now, task, attempt = snapshots(
        finish_receipt={"summary": "done"}, deadline_at=utcnow() - timedelta(seconds=1)
    )
    policy = ContinuationPolicy()

    assert (
        policy.decide(task, attempt, cancel_requested=True, now=now).action
        is ContinuationAction.CANCEL
    )
    assert policy.decide(task, attempt, now=now).action is ContinuationAction.FINALIZE_FINISH

    _, expired, expired_attempt = snapshots(deadline_at=now - timedelta(seconds=1))
    assert (
        policy.decide(expired, expired_attempt, now=now).action is ContinuationAction.FAIL_DEADLINE
    )


def test_policy_budget_allows_attempt_twenty_but_not_another_continuation():
    _now, task, attempt = snapshots(continuation_count=20, current_attempt_no=20)

    decision = ContinuationPolicy().decide(task, attempt)

    assert decision.action is ContinuationAction.FAIL_BUDGET


def test_policy_pending_instruction_precedes_error_and_resume():
    _now, task, attempt = snapshots(same_error_count=3)

    decision = ContinuationPolicy().decide(
        task, attempt, pending_instruction_count=2, checkpoint_recoverable=True
    )

    assert decision.action is ContinuationAction.APPLY_INSTRUCTIONS


def test_policy_same_error_resume_and_continuation_paths():
    _now, failed, failed_attempt = snapshots(same_error_count=3)
    _now, active, active_attempt = snapshots()
    policy = ContinuationPolicy()

    assert policy.decide(failed, failed_attempt).action is ContinuationAction.FAIL_SAME_ERROR
    assert (
        policy.decide(active, active_attempt, checkpoint_recoverable=True).action
        is ContinuationAction.RESUME
    )
    assert policy.decide(active, active_attempt).action is ContinuationAction.CONTINUE


def test_policy_suspends_running_attempt_for_permanent_provider_error():
    _now, task, attempt = snapshots()
    attempt = AttemptSnapshot(
        **{
            **attempt.__dict__,
            "state": AttemptState.RUNNING,
        }
    )

    decision = ContinuationPolicy().decide(
        task,
        attempt,
        checkpoint_recoverable=True,
        suspend_code="model_insufficient_quota",
    )

    assert decision.action is ContinuationAction.SUSPEND
    assert decision.code == "model_insufficient_quota"


def test_policy_allows_explicit_resume_after_provider_error_was_suspended():
    _now, task, attempt = snapshots()

    decision = ContinuationPolicy().decide(
        task,
        attempt,
        checkpoint_recoverable=True,
        suspend_code="model_insufficient_quota",
    )

    assert decision.action is ContinuationAction.RESUME
