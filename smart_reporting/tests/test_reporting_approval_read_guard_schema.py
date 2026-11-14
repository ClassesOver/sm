"""共享pool的schema映射不能把行锁路由到另一份同内容状态。"""

from uuid import uuid4

import pytest
from agno.db.postgres import AsyncPostgresDb
from sqlalchemy import text, update

from smart_reporting.reporting.workflow.repository import REPORTING_DB_SCHEMA, ReportingStateRepository
from smart_reporting.reporting.workflow.state import ReportingStateError
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_reporting_approval_read_guard import states as states

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('source_mapped', [False, True])
async def test_guard_locks_the_observed_schema_despite_conflicting_management_connection_map(states, source_mapped):
    original, state = states
    engine = original.db.db_engine
    shadow = 'approval_guard_' + uuid4().hex
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{shadow}"'))
        await connection.execute(text(f'CREATE TABLE "{shadow}".reporting_run_states '
            f'(LIKE "{REPORTING_DB_SCHEMA}".reporting_run_states INCLUDING ALL)'))
        await connection.execute(text(f'INSERT INTO "{shadow}".reporting_run_states '
            f'SELECT * FROM "{REPORTING_DB_SCHEMA}".reporting_run_states WHERE report_run_id=:run_id'),
            {'run_id': state.report_run_id})
    try:
        source = engine.execution_options(schema_translate_map={REPORTING_DB_SCHEMA: shadow}) if source_mapped else engine
        repository = ReportingStateRepository(AsyncPostgresDb(db_engine=source))
        repository._initialized = True  # 两份实际表已创建，不让initialize改测试schema。
        management = engine.execution_options(schema_translate_map={
            REPORTING_DB_SCHEMA: REPORTING_DB_SCHEMA if source_mapped else shadow})
        async with repository.capture_read_dependencies() as guard:
            await repository.get(state.report_run_id)
            async with source.begin() as connection:
                await connection.execute(update(repository.states).where(
                    repository.states.c.report_run_id == state.report_run_id).values(payload={'changed': True}))
            async with management.begin() as connection:
                with pytest.raises(ReportingStateError):
                    await guard.lock(connection)
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{shadow}" CASCADE'))
