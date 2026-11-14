"""PostgreSQL双连接：生产清理方法不能覆盖快照后独立提交的状态。"""

import os
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.task_execution import TaskExecutionRepository, TaskExecutionRepositoryError
from smart_reporting.task_execution.models import Lease, TaskExecutionScope, TaskState, utcnow


@pytest.mark.integration
@pytest.mark.anyio
@pytest.mark.parametrize('action', ['cancel', 'owned_cancel', 'fail_indeterminate'])
@pytest.mark.parametrize('race', ['completed', 'failed', 'cancelled', 'version_only'])
async def test_postgres_stale_cleanup_preserves_independent_commit(action, race):
    url = os.getenv('REPORTING_TEST_DB_URL', '').strip()
    if not url:
        pytest.skip('未设置REPORTING_TEST_DB_URL，跳过PostgreSQL双连接竞争回归。')
    engine = create_async_engine(url)
    current = TaskExecutionRepository(SimpleNamespace(db_engine=engine))
    suffix = uuid4().hex
    scope = TaskExecutionScope(f'cas-{suffix}', 'user', 'thread', 'workspace', 'reporting')
    attempt_id = f'attempt-{suffix}'
    now = utcnow()
    lease = Lease('worker-a', 1, now + timedelta(minutes=1))
    terminal = race != 'version_only'
    outcome = {'completed': 'finish_accepted', 'failed': 'error', 'cancelled': 'cancelled'}
    raced = False

    async def concurrent_transition():
        async with engine.begin() as other:
            await other.execute(update(current.tasks).where(
                current.tasks.c.external_run_id == scope.external_run_id,
            ).values(
                status=race if terminal else TaskState.ACTIVE,
                state_version=current.tasks.c.state_version + 1,
                lease_owner=None if terminal else lease.owner,
                lease_expires_at=None if terminal else lease.expires_at,
                completed_at=utcnow() if terminal else None,
            ))
            if terminal:
                await other.execute(update(current.runs).where(
                    current.runs.c.internal_run_id == attempt_id,
                ).values(status='closed', outcome=outcome[race], completed_at=utcnow()))

    class SnapshotRaceEngine:
        @asynccontextmanager
        async def begin(self):
            async with engine.begin() as connection:
                async def execute(statement):
                    nonlocal raced
                    result = await connection.execute(statement)
                    if (not raced and getattr(statement, 'is_select', False)
                            and current.tasks in statement.get_final_froms()):
                        # 已缓冲旧快照；第二连接提交后才交还给生产方法。
                        raced = True
                        await concurrent_transition()
                    return result
                yield SimpleNamespace(execute=execute)

    try:
        await current.initialize()
        async with engine.begin() as connection:
            await connection.execute(insert(current.tasks).values(
                external_run_id=scope.external_run_id, owner_user_id=scope.owner_user_id,
                thread_id=scope.thread_id, sandbox_id=scope.sandbox_id, agent_id=scope.executor_id,
                current_internal_run_id=attempt_id, status=TaskState.ACTIVE,
                deadline_at=now + timedelta(hours=1), lease_owner=lease.owner,
                lease_epoch=lease.epoch, lease_expires_at=lease.expires_at, created_at=now,
            ))
            await connection.execute(insert(current.runs).values(
                external_run_id=scope.external_run_id, internal_run_id=attempt_id,
                continuation_index=0, status='running', lease_epoch=1, created_at=now,
            ))
            await connection.execute(insert(current.instructions).values(
                external_run_id=scope.external_run_id, instruction_id=f'pending-{suffix}',
                sequence=1, content='next', content_hash='hash', content_bytes=4,
                status='pending', created_at=now, updated_at=now,
            ))
        current.db = SimpleNamespace(db_engine=SnapshotRaceEngine())
        with pytest.raises(TaskExecutionRepositoryError):
            if action == 'fail_indeterminate':
                await current.fail_indeterminate_mutation(scope, lease.epoch)
            else:
                await current.cancel_and_reject(scope, **({'lease': lease} if action == 'owned_cancel' else {}))
        assert raced
        async with engine.connect() as connection:
            task = (await connection.execute(select(current.tasks).where(
                current.tasks.c.external_run_id == scope.external_run_id,
            ))).one()._mapping
            run = (await connection.execute(select(current.runs).where(
                current.runs.c.internal_run_id == attempt_id,
            ))).one()._mapping
            assert task['status'] == (race if terminal else 'active')
            assert task['state_version'] == 1
            assert run['status'] == ('closed' if terminal else 'running')
            assert run['outcome'] == (outcome[race] if terminal else None)
            assert (await connection.execute(select(current.instructions.c.status).where(
                current.instructions.c.external_run_id == scope.external_run_id,
            ))).scalar_one() == 'pending'
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(current.tasks).where(
                current.tasks.c.external_run_id == scope.external_run_id,
            ))
        await engine.dispose()
