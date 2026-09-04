import asyncio
import os
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete, select

from smart_reporting.runtime.database import create_agent_database
from smart_reporting.task_execution.repository import (
    MAX_TERMINAL_OUTPUT_BYTES,
    TASK_SCHEMA_VERSION,
    TaskExecutionRepository,
    TaskExecutionRepositoryError,
    utcnow,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def repository():
    database_url = os.getenv("REPORTING_TEST_DB_URL", "").strip()
    if not database_url:
        pytest.skip("未设置 REPORTING_TEST_DB_URL，跳过 PostgreSQL 任务仓储集成测试。")
    database = create_agent_database(database_url)
    current = TaskExecutionRepository(database.async_db)
    await current.initialize()
    try:
        async with database.async_engine.begin() as connection:
            await connection.execute(delete(current.tasks))
        yield current, database
    finally:
        async with database.async_engine.begin() as connection:
            await connection.execute(delete(current.tasks))
        await database.async_engine.dispose()
        database.sync_engine.dispose()


async def create_task(repository: TaskExecutionRepository, run_id: str = "external-run"):
    return await repository.create_task(
        external_run_id=run_id,
        owner_user_id="user-7",
        thread_id="thread-9",
        executor_id="coding-agent",
        sandbox_id="sandbox-3",
        deadline_at=utcnow() + timedelta(hours=24),
    )


@pytest.mark.anyio
async def test_postgres_repository_initializes_schema_versions_and_supports_cas(repository):
    current, database = repository
    task = await create_task(current)

    assert task.mutation_sequence == 0
    assert await current.claim_lease(task.external_run_id, "worker-a") is True
    assert await current.claim_lease(task.external_run_id, "worker-b") is False

    running = await current.bind_initial_run(task.external_run_id, "internal-1")
    assert running.continuation_count == 0
    assert running.current_internal_run_id == "internal-1"
    assert await current.increment_mutation(task.external_run_id) == 1

    async with database.async_engine.connect() as connection:
        versions = {
            row.component: row.version
            for row in (await connection.execute(select(current.schema_versions))).all()
        }
    assert versions["agentos_coding_repository"] == TASK_SCHEMA_VERSION
    assert versions["agentos_coding_tasks"] == TASK_SCHEMA_VERSION
    assert versions["agentos_coding_task_runs"] == TASK_SCHEMA_VERSION
    assert versions["agentos_coding_executions"] == TASK_SCHEMA_VERSION
    assert versions["agentos_coding_task_instructions"] == TASK_SCHEMA_VERSION
    assert (
        await database.async_db._get_table(  # type: ignore[attr-defined]
            table_type="versions", create_table_if_not_found=False
        )
        is None
    )


@pytest.mark.anyio
async def test_execution_scope_terminal_receipt_and_output_are_persistent_and_bounded(repository):
    current, _database = repository
    task = await create_task(current)
    await current.bind_initial_run(task.external_run_id, "internal-1")
    await current.reserve_execution(
        execution_id="execution-1",
        external_run_id=task.external_run_id,
        internal_run_id="internal-1",
        owner_user_id=task.owner_user_id,
        thread_id=task.thread_id,
        sandbox_id=task.sandbox_id,
        daytona_session_id="agent-coding-execution-1",
        mutation_sequence=task.mutation_sequence,
        is_verification=True,
    )

    completed = await current.update_execution(
        "execution-1",
        status="completed",
        output="x" * (MAX_TERMINAL_OUTPUT_BYTES + 32),
        output_cursor=MAX_TERMINAL_OUTPUT_BYTES + 32,
        exit_code=0,
    )

    assert len(completed.terminal_output.encode()) == MAX_TERMINAL_OUTPUT_BYTES
    assert await current.successful_verification(task.external_run_id, "execution-1", 0)
    assert (
        await current.scoped_execution(
            "execution-1",
            owner_user_id=task.owner_user_id,
            thread_id=task.thread_id,
            sandbox_id=task.sandbox_id,
        )
    ).status == "completed"
    with pytest.raises(TaskExecutionRepositoryError) as rejected:
        await current.scoped_execution(
            "execution-1",
            owner_user_id="other-user",
            thread_id=task.thread_id,
            sandbox_id=task.sandbox_id,
        )
    assert rejected.value.code == "execution_scope_mismatch"


@pytest.mark.anyio
async def test_complete_task_rejects_stale_mutation_and_closes_active_task(repository):
    current, _database = repository
    task = await create_task(current)
    task = await current.bind_initial_run(task.external_run_id, "internal-0")
    assert await current.claim_lease(task.external_run_id, "request-a") is True
    assert await current.increment_mutation(task.external_run_id) == 1

    with pytest.raises(TaskExecutionRepositoryError) as stale:
        await current.complete_task(
            task.external_run_id,
            expected_mutation_sequence=0,
            expected_lease_owner="request-a",
            result_text="stale",
            finish_payload={"summary": "stale"},
            retained_execution_ids=[],
        )
    assert stale.value.code == "task_cas_conflict"

    await current.complete_task(
        task.external_run_id,
        expected_mutation_sequence=1,
        expected_lease_owner="request-a",
        result_text="done",
        finish_payload={"summary": "done"},
        retained_execution_ids=[],
    )
    completed = await current.get_task(task.external_run_id)
    assert completed is not None
    assert completed.status == "completed"
    with pytest.raises(TaskExecutionRepositoryError) as closed:
        await current.increment_mutation(task.external_run_id)
    assert closed.value.code == "task_not_active"


@pytest.mark.anyio
async def test_repository_initialization_and_lease_are_safe_across_instances(repository):
    current, database = repository
    other = TaskExecutionRepository(database.async_db)
    await asyncio.gather(current.initialize(), other.initialize())
    await asyncio.gather(create_task(current), create_task(other))

    claims = await asyncio.gather(
        current.claim_lease("external-run", "worker-a"),
        other.claim_lease("external-run", "worker-b"),
    )

    assert sum(claims) == 1


@pytest.mark.anyio
async def test_cleanup_removes_only_terminal_records_after_seven_days(repository):
    current, _database = repository
    expired = await create_task(current, "expired-run")
    expired = await current.bind_initial_run(expired.external_run_id, "expired-internal")
    await current.reserve_execution(
        execution_id="expired-execution",
        external_run_id=expired.external_run_id,
        internal_run_id="expired-internal",
        owner_user_id=expired.owner_user_id,
        thread_id=expired.thread_id,
        sandbox_id=expired.sandbox_id,
        daytona_session_id="agent-exec-expired",
        mutation_sequence=0,
    )
    await current.update_execution(
        "expired-execution",
        status="completed",
        output="visible result",
        exit_code=0,
    )
    assert await current.claim_lease(expired.external_run_id, "completion-worker") is True
    await current.complete_task(
        expired.external_run_id,
        expected_mutation_sequence=0,
        expected_lease_owner="completion-worker",
        result_text="done",
        finish_payload={"summary": "done"},
        retained_execution_ids=[],
    )
    active = await create_task(current, "active-run")

    removed = await current.cleanup_expired(
        lease_owner="cleanup-worker",
        now=utcnow() + timedelta(days=8),
    )

    assert removed == 2
    assert await current.get_task(expired.external_run_id) is None
    assert await current.get_execution("expired-execution") is None
    assert await current.get_task(active.external_run_id) is not None


@pytest.mark.anyio
async def test_postgres_repository_uses_the_same_core_contract():
    db_url = os.environ.get("REPORTING_TEST_DB_URL")
    if not db_url:
        pytest.skip("未设置 REPORTING_TEST_DB_URL，跳过 PostgreSQL 任务仓储集成测试。")
    database = create_agent_database(db_url)
    assert database.backend == "postgresql"
    current = TaskExecutionRepository(database.async_db)
    suffix = uuid.uuid4().hex
    external_run_id = f"integration-{suffix}"
    internal_run_id = f"internal-{suffix}"
    execution_id = f"execution-{suffix}"
    try:
        task = await current.create_task(
            external_run_id=external_run_id,
            owner_user_id="integration-user",
            thread_id=f"thread-{suffix}",
            executor_id="coding-agent",
            sandbox_id=f"sandbox-{suffix}",
            deadline_at=utcnow() + timedelta(hours=24),
        )
        task = await current.bind_initial_run(external_run_id, internal_run_id)
        assert await current.claim_lease(external_run_id, "integration-worker")
        mutation_sequence = await current.increment_mutation(external_run_id)
        await current.reserve_execution(
            execution_id=execution_id,
            external_run_id=external_run_id,
            internal_run_id=internal_run_id,
            owner_user_id=task.owner_user_id,
            thread_id=task.thread_id,
            sandbox_id=task.sandbox_id,
            daytona_session_id=f"agent-exec-{suffix}",
            mutation_sequence=mutation_sequence,
            is_verification=True,
        )
        await current.update_execution(execution_id, status="completed", exit_code=0)
        assert await current.successful_verification(
            external_run_id, execution_id, mutation_sequence
        )
        await current.complete_task(
            external_run_id,
            expected_mutation_sequence=mutation_sequence,
            expected_lease_owner="integration-worker",
            result_text="done",
            finish_payload={"summary": "done"},
            retained_execution_ids=[],
        )
        completed = await current.get_task(external_run_id)
        assert completed is not None and completed.status == "completed"
    finally:
        await current.initialize()
        async with database.async_engine.begin() as connection:
            await connection.execute(
                delete(current.executions).where(
                    current.executions.c.external_run_id == external_run_id
                )
            )
            await connection.execute(
                delete(current.runs).where(current.runs.c.external_run_id == external_run_id)
            )
            await connection.execute(
                delete(current.tasks).where(current.tasks.c.external_run_id == external_run_id)
            )
        await database.async_engine.dispose()
        database.sync_engine.dispose()
