"""Run a native Office candidate under a durable task lease."""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from datetime import UTC, datetime

from loguru import logger

from ..task_execution.models import AttemptOutcome, TaskState
from ..task_execution.repository import TaskExecutionRepositoryError
from ..task_execution.session import TaskSession
from .native_ai import _invalid


async def run_native_candidate(service, task_scope, job, context, prepare, persist_candidate):
    repository = service.task_repository
    task_id = task_scope.external_run_id
    try:
        async with asyncio.timeout(service.timeout_seconds):
            while job.status == "running":
                task = await repository.get_task_snapshot(task_id)
                if task is None or task.scope != task_scope:
                    raise _invalid("native_ai_job_missing", f"{context.format.upper()} 任务不存在或已过期。")
                if task.state is TaskState.COMPLETED:
                    receipt = await service._read_durable_candidate(task_scope, context)
                    if receipt is None or job.snapshot_sha256 != receipt["snapshotSha256"]:
                        raise _invalid("native_ai_snapshot_changed", f"{context.format.upper()} 候选快照已变化。")
                    if job.status == "running":
                        job.proposal, job.accepted, job.status = receipt["proposal"], receipt["accepted"], "succeeded"
                    return
                if task.state is TaskState.CANCELLED:
                    job.status = "cancelled"
                    return
                now = datetime.now(UTC)
                if task.state is TaskState.FAILED or task.deadline_at <= now:
                    raise _invalid("native_ai_not_ready", f"{context.format.upper()} 任务已结束。")
                if task.lease_owner and task.lease_expires_at and task.lease_expires_at > now:
                    await asyncio.sleep(0.25)
                    continue
                async with AsyncExitStack() as stack:
                    try:
                        claim = await stack.enter_async_context(TaskSession(repository, task_scope))
                    except TaskExecutionRepositoryError as error:
                        if error.code != "task_lease_conflict":
                            raise
                    else:
                        await _execute_candidate(service, claim, job, context, prepare, persist_candidate)
                        return
                await asyncio.sleep(0.25)
    except asyncio.CancelledError:
        job.status = "cancelled"
        raise
    except Exception as error:
        if job.status == "running":
            logger.warning(
                "native_candidate_task_failed format={} edit_id={} error_type={}",
                context.format, job.edit_id, type(error).__name__,
            )
            job.status = "failed"
            job.error = {"code": getattr(error, "code", "native_ai_proposal_invalid"),
                         "message": f"{context.format.upper()} 候选未能完成，人工草稿已保留。"}
    finally:
        await job.event_log.finish(job.status)


async def _execute_candidate(service, claim, job, context, prepare, persist_candidate):
    repository = service.task_repository
    task_scope = claim.scope
    task_id = task_scope.external_run_id
    task = await repository.get_task_snapshot(task_id)
    if task.state is TaskState.NEW:
        task, _ = await repository.open_initial(task_id, claim.lease, task.state_version)
    elif task.state in {TaskState.ACTIVE, TaskState.SUSPENDED}:
        task, _ = await repository.resume_current(task_id, claim.lease, task.state_version)
    elif task.state is TaskState.FINISHING:
        await repository.finalize_finish(task_id, claim.lease, task.state_version, agno_status="recovered")
        receipt = await service._read_durable_candidate(task_scope, context)
        if receipt is None or job.snapshot_sha256 != receipt["snapshotSha256"]:
            raise _invalid("native_ai_snapshot_changed", f"{context.format.upper()} 候选快照已变化。")
        if job.status == "running":
            job.proposal, job.accepted, job.status = receipt["proposal"], receipt["accepted"], "succeeded"
        return
    else:
        raise _invalid("native_ai_not_ready", f"{context.format.upper()} 任务已结束。")

    async def persist(proposal):
        claim.assert_alive()
        finishing = await persist_candidate(
            task_scope, claim.lease, task.state_version, job.request_sha256,
            service._durable_candidate(job, proposal),
        )
        await repository.finalize_finish(task_id, claim.lease, finishing.state_version, agno_status="completed")

    await prepare(persist=persist)
    if job.status == "failed":
        current = await repository.get_task_snapshot(task_id)
        if current.state is TaskState.CANCELLED:
            job.status, job.error = "cancelled", None
        elif current.state is TaskState.ACTIVE and current.lease_owner == claim.lease.owner:
            await repository.close_and_decide(
                task_id, claim.lease, current.state_version, outcome=AttemptOutcome.ERROR,
                agno_status="error", error=job.error["code"], create_next=False,
            )
