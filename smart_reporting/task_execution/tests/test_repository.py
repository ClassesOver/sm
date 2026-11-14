import os

import pytest
from sqlalchemy import text

from smart_reporting.runtime.database import create_agent_database
from smart_reporting.task_execution.models import (
    AttemptOutcome,
    AttemptState,
    InstructionState,
    Lease,
    TaskExecutionScope,
    TaskState,
)
from smart_reporting.task_execution.repository import (
    MAX_INSTRUCTION_BYTES,
    TaskExecutionRepository,
    TaskExecutionRepositoryError,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def repository():
    database_url = os.getenv("REPORTING_TEST_DB_URL", "").strip()
    if not database_url:
        pytest.skip("未设置 REPORTING_TEST_DB_URL，跳过 PostgreSQL 任务仓储集成测试。")
    database = create_agent_database(database_url)
    repository = TaskExecutionRepository(database.async_db)
    await repository.initialize()
    try:
        async with database.async_engine.begin() as connection:
            await connection.execute(text("TRUNCATE agentos_coding.agentos_coding_tasks CASCADE"))
        yield repository
    finally:
        async with database.async_engine.begin() as connection:
            await connection.execute(text("TRUNCATE agentos_coding.agentos_coding_tasks CASCADE"))
        await database.async_engine.dispose()
        database.sync_engine.dispose()


def scope(run_id: str = "run") -> TaskExecutionScope:
    return TaskExecutionScope(run_id, "user", "thread", "sandbox", "coding-agent")


@pytest.mark.anyio
async def test_reporting可显式提高单条指令上限且默认边界不变(repository):
    content = "x" * (MAX_INSTRUCTION_BYTES + 1)
    with pytest.raises(TaskExecutionRepositoryError) as rejected:
        await repository.create_task_with_initial_attempt(scope("default-limit"), content)
    assert rejected.value.code == "instruction_too_large"

    task = await repository.create_task_with_initial_attempt(
        scope("report-limit"),
        content,
        max_instruction_bytes=512 * 1024,
    )

    assert task.scope.external_run_id == "report-limit"


@pytest.mark.anyio
async def test_create_aggregate_is_idempotent_and_attempt_zero_is_free(repository):
    task = await repository.create_task_with_initial_attempt(scope(), "实现目标")
    duplicate = await repository.create_task_with_initial_attempt(scope(), "实现目标")

    assert duplicate == task
    assert task.state is TaskState.NEW
    assert task.current_attempt_no == task.continuation_count == 0
    attempt = await repository.get_attempt(task.current_internal_run_id)
    assert attempt is not None and attempt.state is AttemptState.CREATED

    with pytest.raises(TaskExecutionRepositoryError, match="初始目标不一致") as conflict:
        await repository.create_task_with_initial_attempt(scope(), "另一个目标")
    assert conflict.value.code == "task_initial_instruction_conflict"


@pytest.mark.anyio
async def test_new_attempt_instruction_keeps_initial_goal_and_latest_supplement(repository):
    task = await repository.create_task_with_initial_attempt(scope(), "不可变目标")
    await repository.submit_instruction(scope(), "first", "较早补充")
    await repository.submit_instruction(scope(), "latest", "最新补充")
    lease = await repository.claim_lease("run", "worker")
    assert isinstance(lease, Lease)
    continued = await repository.close_and_decide(
        "run",
        lease,
        task.state_version + 2,
        outcome=AttemptOutcome.NO_FINISH,
        agno_status="COMPLETED",
        create_next=True,
    )

    assert (
        await repository.attempt_instruction("run", continued.current_attempt_no)
        == "不可变目标\n\n最新补充"
    )


@pytest.mark.anyio
async def test_acceptance_contract_is_persisted_and_immutable(repository):
    acceptance_contract = {
        "version": 1,
        "requirements": [
            {
                "id": "report",
                "validatorId": "analysis:report",
                "parameters": {"currency": "CNY"},
                "artifactPatterns": ["reports/*.json"],
            }
        ],
    }

    task = await repository.create_task_with_initial_attempt(
        scope(),
        "实现目标",
        acceptance_contract=acceptance_contract,
    )
    duplicate = await repository.create_task_with_initial_attempt(
        scope(),
        "实现目标",
        acceptance_contract=acceptance_contract,
    )

    assert task.acceptance_contract == acceptance_contract
    assert duplicate.acceptance_contract == acceptance_contract
    acceptance_contract["requirements"][0]["parameters"]["currency"] = "USD"
    assert (await repository.get_task_snapshot("run")).acceptance_contract != acceptance_contract
    with pytest.raises(TaskExecutionRepositoryError) as conflict:
        await repository.create_task_with_initial_attempt(
            scope(),
            "实现目标",
            acceptance_contract=acceptance_contract,
        )
    assert conflict.value.code == "task_acceptance_contract_conflict"


@pytest.mark.anyio
async def test_lease_epoch_fences_old_owner_and_heartbeat_does_not_change_version(repository):
    task = await repository.create_task_with_initial_attempt(scope(), "实现目标")
    first = await repository.claim_lease("run", "worker-a")
    assert isinstance(first, Lease)
    heartbeat = await repository.heartbeat_lease("run", first)

    assert heartbeat.epoch == first.epoch == 1
    assert (await repository.get_task_snapshot("run")).state_version == task.state_version
    assert await repository.claim_lease("run", "worker-b") is None

    expired = Lease(first.owner, first.epoch - 1, first.expires_at)
    with pytest.raises(TaskExecutionRepositoryError) as stale:
        await repository.resume_current("run", expired, task.state_version)
    assert stale.value.code == "task_cas_conflict"


@pytest.mark.anyio
async def test_instruction_inbox_idempotency_conflict_and_atomic_apply(repository):
    await repository.create_task_with_initial_attempt(scope(), "实现目标")
    first = await repository.submit_instruction(scope(), "instruction-1", "增加失败测试")
    duplicate = await repository.submit_instruction(scope(), "instruction-1", "增加失败测试")

    assert duplicate == first
    assert first.state is InstructionState.PENDING
    with pytest.raises(TaskExecutionRepositoryError) as conflict:
        await repository.submit_instruction(scope(), "instruction-1", "修改成别的内容")
    assert conflict.value.code == "instruction_id_conflict"

    current = await repository.get_task_snapshot("run")
    lease = await repository.claim_lease("run", "worker")
    assert current is not None and isinstance(lease, Lease)
    continued = await repository.close_and_decide(
        "run",
        lease,
        current.state_version,
        outcome=AttemptOutcome.NO_FINISH,
        agno_status="COMPLETED",
        create_next=True,
    )

    assert continued.current_attempt_no == continued.continuation_count == 1
    assert await repository.pending_instructions("run") == []


@pytest.mark.anyio
async def test_finish_is_two_phase_and_instruction_requires_successor(repository):
    task = await repository.create_task_with_initial_attempt(scope(), "实现目标")
    lease = await repository.claim_lease("run", "worker")
    assert isinstance(lease, Lease)
    receipt = {"summary": "完成", "digest": "abc"}
    finishing = await repository.request_finish(
        "run",
        lease,
        task.state_version,
        receipt,
        result_text="完成",
        retained_execution_ids=[],
    )

    assert finishing.state is TaskState.FINISHING
    attempt = await repository.get_attempt(finishing.current_internal_run_id)
    assert attempt is not None and attempt.state is AttemptState.FINISH_REQUESTED
    with pytest.raises(TaskExecutionRepositoryError) as successor:
        await repository.submit_instruction(scope(), "late", "继续修改")
    assert successor.value.code == "task_successor_required"

    completed = await repository.finalize_finish(
        "run", lease, finishing.state_version, agno_status="COMPLETED"
    )
    assert completed.state is TaskState.COMPLETED
    closed = await repository.get_attempt(completed.current_internal_run_id)
    assert closed is not None and closed.outcome is AttemptOutcome.FINISH_ACCEPTED


@pytest.mark.anyio
async def test_old_resume_rolls_back_before_queued_postgres_epoch_takeover(repository):
    """A real task lock serializes takeover; expired old run writes still roll back."""
    import asyncio
    from types import SimpleNamespace

    from sqlalchemy import select, text

    from smart_reporting.task_execution.tests.test_lifecycle_expiry_postgres import (
        blocked_statement,
        database_lease_expired,
    )

    task = await repository.create_task_with_initial_attempt(scope("late-resume"), "目标")
    old_lease = await repository.claim_lease(task.scope.external_run_id, "old-worker")
    task, initial_attempt = await repository.open_initial(
        task.scope.external_run_id, old_lease, task.state_version,
    )
    database = SimpleNamespace(async_engine=repository.db.db_engine)
    async with repository.db.db_engine.begin() as connection:
        expiry = (await connection.execute(text('UPDATE agentos_coding.agentos_coding_tasks '
            "SET lease_expires_at=clock_timestamp()+interval '1 second' "
            'WHERE external_run_id=:run RETURNING lease_expires_at'),
            {'run': task.scope.external_run_id})).scalar_one()
    old_lease = Lease(old_lease.owner, old_lease.epoch, expiry)
    actors = []
    try:
        async with repository.db.db_engine.begin() as blocker:
            await blocker.execute(select(repository.runs.c.internal_run_id).where(
                repository.runs.c.internal_run_id == initial_attempt.internal_run_id).with_for_update())
            holder = (await blocker.execute(text('SELECT pg_backend_pid()'))).scalar_one()
            actors.append(asyncio.create_task(repository.resume_current(
                task.scope.external_run_id, old_lease, task.state_version)))
            await blocked_statement(database, holder)
            async with repository.db.db_engine.connect() as observer:
                old_pid = (await observer.execute(text('SELECT pid FROM pg_stat_activity '
                    "WHERE datname=current_database() AND wait_event_type='Lock' "
                    'AND :holder = ANY(pg_blocking_pids(pid))'), {'holder': holder})).scalar_one()
            await database_lease_expired(repository, database, task.scope.external_run_id)
            actors.append(asyncio.create_task(repository.claim_lease(task.scope.external_run_id, "new-worker")))
            await blocked_statement(database, old_pid)
        results = await asyncio.wait_for(asyncio.gather(*actors, return_exceptions=True), 5)
        assert isinstance(results[0], TaskExecutionRepositoryError)
        assert results[0].code == "task_cas_conflict"
        new_lease = results[1]
        assert isinstance(new_lease, Lease) and new_lease.epoch == old_lease.epoch + 1
        after = await repository.get_attempt(initial_attempt.internal_run_id)
        assert after.resume_count == initial_attempt.resume_count
        assert after.lease_epoch == old_lease.epoch
        current = await repository.get_task_snapshot(task.scope.external_run_id)
        assert current.state_version == task.state_version
        assert current.lease_owner == "new-worker"
    finally:
        for actor in actors:
            actor.cancel()
        await asyncio.gather(*actors, return_exceptions=True)
