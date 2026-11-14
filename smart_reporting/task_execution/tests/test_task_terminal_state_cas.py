"""真实 SQL 故障交错：快照读取后的完成/状态变化不能被旧清理覆盖。"""

import pytest
from sqlalchemy import select, update

from smart_reporting.task_execution import TaskExecutionRepositoryError
from smart_reporting.task_execution.models import TaskState, utcnow
from smart_reporting.task_execution.tests.test_task_cancel_lease_fence import (
    repository as repository,
)


@pytest.mark.anyio
@pytest.mark.parametrize('action', ['cancel', 'owned_cancel', 'fail_indeterminate'])
@pytest.mark.parametrize('race', ['completed', 'failed', 'cancelled', 'version_only'])
async def test_stale_cleanup_cannot_overwrite_committed_state(repository, action, race):
    current, scope, lease, engine, adapter = repository
    terminal = race != 'version_only'
    outcome = {'completed': 'finish_accepted', 'failed': 'error', 'cancelled': 'cancelled'}

    def concurrent_transition(_connection, statement):
        if not getattr(statement, 'is_update', False) or statement.table is not current.tasks:
            return
        adapter.before_execute = None
        # 第二连接独立提交；不是注入到待回滚的清理事务内。
        with engine.begin() as other:
            other.execute(update(current.tasks).values(
                status=race if terminal else TaskState.ACTIVE,
                state_version=current.tasks.c.state_version + 1,
                lease_owner=None if terminal else lease.owner,
                lease_expires_at=None if terminal else lease.expires_at,
                completed_at=utcnow() if terminal else None,
            ))
            if terminal:
                other.execute(update(current.runs).values(
                    status='closed', outcome=outcome[race], completed_at=utcnow(),
                ))

    adapter.before_execute = concurrent_transition
    with pytest.raises(TaskExecutionRepositoryError):
        if action == 'fail_indeterminate':
            await current.fail_indeterminate_mutation(scope, lease.epoch)
        else:
            await current.cancel_and_reject(scope, **({'lease': lease} if action == 'owned_cancel' else {}))
    with engine.connect() as connection:
        task = connection.execute(select(current.tasks)).one()._mapping
        assert task['status'] == (race if terminal else 'active')
        assert task['state_version'] == 1
        run = connection.execute(select(current.runs)).one()._mapping
        assert run['status'] == ('closed' if terminal else 'running')
        assert run['outcome'] == (outcome[race] if terminal else None)
        assert connection.execute(select(current.instructions.c.status)).scalar_one() == 'pending'
