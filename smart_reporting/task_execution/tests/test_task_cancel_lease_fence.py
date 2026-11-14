from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, insert, select, update

from smart_reporting.task_execution import (
    Lease,
    TaskExecutionRepository,
    TaskExecutionRepositoryError,
)
from smart_reporting.task_execution.models import TaskExecutionScope, TaskState, utcnow


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _SqliteAsyncAdapter:
    """仅适配同步 SQLite 事务的 await 接口，不模拟 SQL 或事务结果。"""

    def __init__(self, engine):
        self.engine = engine
        self.before_execute = None

    @asynccontextmanager
    async def begin(self):
        with self.engine.begin() as connection:
            yield SimpleNamespace(execute=lambda statement: self._execute(connection, statement))

    @asynccontextmanager
    async def connect(self):
        with self.engine.connect() as connection:
            yield SimpleNamespace(execute=lambda statement: self._execute(connection, statement))

    async def _execute(self, connection, statement):
        if self.before_execute is not None:
            self.before_execute(connection, statement)
        return connection.execute(statement)


@pytest.fixture
def repository(tmp_path):
    # 生产仓储只支持 PG；这里只绕过初始化，复用真实表与生产取消方法验证 SQL 事务。
    database = SimpleNamespace(db_engine=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    repository = TaskExecutionRepository(database)
    engine = create_engine(f"sqlite:///{tmp_path / 'lease-fence.sqlite'}").execution_options(
        schema_translate_map={repository.metadata.schema: None}
    )
    repository.metadata.create_all(engine)
    adapter = _SqliteAsyncAdapter(engine)
    repository.db = SimpleNamespace(db_engine=adapter)
    repository._initialized = True
    now = utcnow()
    scope = TaskExecutionScope("run", "user", "thread", "workspace", "reporting")
    lease = Lease("worker-a", 1, now + timedelta(minutes=1))
    with engine.begin() as connection:
        connection.execute(insert(repository.tasks).values(
            external_run_id=scope.external_run_id, owner_user_id=scope.owner_user_id,
            thread_id=scope.thread_id, sandbox_id=scope.sandbox_id, agent_id=scope.executor_id,
            current_internal_run_id="attempt", status=TaskState.ACTIVE,
            deadline_at=now + timedelta(hours=1), lease_owner=lease.owner,
            lease_epoch=lease.epoch, lease_expires_at=lease.expires_at, created_at=now,
        ))
        connection.execute(insert(repository.runs).values(
            external_run_id=scope.external_run_id, internal_run_id="attempt",
            continuation_index=0, status="running", lease_epoch=1, created_at=now,
        ))
        connection.execute(insert(repository.instructions).values(
            external_run_id=scope.external_run_id, instruction_id="pending", sequence=1,
            content="next", content_hash="hash", content_bytes=4, status="pending",
            created_at=now, updated_at=now,
        ))
    yield repository, scope, lease, engine, adapter
    engine.dispose()


@pytest.mark.anyio
async def test_owned_cancel_updates_task_attempt_and_pending_instruction(repository):
    current, scope, lease, engine, _adapter = repository
    cancelled = await current.cancel_and_reject(scope, lease=lease)
    assert cancelled.state is TaskState.CANCELLED
    assert cancelled.lease_epoch == 2
    with engine.connect() as connection:
        assert connection.execute(select(current.runs.c.outcome)).scalar_one() == "cancelled"
        assert connection.execute(select(current.instructions.c.status)).scalar_one() == "rejected"


@pytest.mark.anyio
@pytest.mark.parametrize("race", [False, True])
async def test_stale_owner_cannot_cancel_new_epoch_even_after_snapshot_read(repository, race):
    current, scope, lease, engine, adapter = repository

    def take_over(connection):
        connection.execute(update(current.tasks).values(lease_owner="worker-b", lease_epoch=2))

    if race:
        # 在取消事务已读旧快照、尚未 UPDATE 时接管；真实 CAS 必须拒绝且回滚子表。
        def before_execute(connection, statement):
            if getattr(statement, "is_update", False) and statement.table is current.tasks:
                adapter.before_execute = None
                take_over(connection)
        adapter.before_execute = before_execute
    else:
        with engine.begin() as connection:
            take_over(connection)
    with pytest.raises(TaskExecutionRepositoryError) as captured:
        await current.cancel_and_reject(scope, lease=lease)
    assert captured.value.code == "task_lease_lost"
    with engine.connect() as connection:
        task = connection.execute(select(current.tasks)).one()._mapping
        # 注入在同一 SQLite 事务中的接管也会一起回滚；预先接管则保持新 owner。
        assert task["status"] == "active"
        assert task["lease_epoch"] == (1 if race else 2)
        assert task["lease_owner"] == ("worker-a" if race else "worker-b")
        assert connection.execute(select(current.runs.c.status)).scalar_one() == "running"
        assert connection.execute(select(current.instructions.c.status)).scalar_one() == "pending"


@pytest.mark.anyio
async def test_explicit_scope_cancel_remains_supported(repository):
    current, scope, _lease, _engine, _adapter = repository
    assert (await current.cancel_and_reject(scope)).state is TaskState.CANCELLED


@pytest.mark.anyio
@pytest.mark.parametrize("race", [False, True])
async def test_indeterminate_old_patch_cleanup_cannot_fail_new_epoch(repository, race):
    current, scope, _lease, engine, adapter = repository

    def take_over(connection):
        connection.execute(update(current.tasks).values(lease_owner="worker-b", lease_epoch=2))

    if race:
        def before_execute(connection, statement):
            if getattr(statement, "is_update", False) and statement.table is current.tasks:
                adapter.before_execute = None
                take_over(connection)
        adapter.before_execute = before_execute
    else:
        with engine.begin() as connection:
            take_over(connection)
    with pytest.raises(TaskExecutionRepositoryError) as captured:
        await current.fail_indeterminate_mutation(scope, 1)
    assert captured.value.code == "task_cas_conflict"
    with engine.connect() as connection:
        task = connection.execute(select(current.tasks)).one()._mapping
        assert task["status"] == "active"
        assert task["lease_epoch"] == (1 if race else 2)
        assert connection.execute(select(current.runs.c.status)).scalar_one() == "running"
        assert connection.execute(select(current.instructions.c.status)).scalar_one() == "pending"


@pytest.mark.anyio
async def test_indeterminate_owned_patch_cleanup_still_fails_current_task(repository):
    current, scope, _lease, engine, _adapter = repository
    result = await current.fail_indeterminate_mutation(scope, 1)
    assert result.state is TaskState.FAILED
    with engine.connect() as connection:
        assert connection.execute(select(current.runs.c.outcome)).scalar_one() == "error"
        assert connection.execute(select(current.instructions.c.status)).scalar_one() == "rejected"
