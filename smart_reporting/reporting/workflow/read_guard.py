"""批准核验实际读取行的稳定见证；复用SQL行锁，不提供跨库写事务。"""

import asyncio
from contextlib import AsyncExitStack
from copy import deepcopy

from sqlalchemy import select

from .checkpoint import payload_sha256
from .state import ReportingStateError


class ReportingReadGuard:
    def __init__(self, repository):
        self.repository = repository
        self.engine = repository.db.db_engine
        self.schema_map = deepcopy(self.engine.get_execution_options().get('schema_translate_map'))
        self.owner = asyncio.current_task()
        self.rows = {}
        self.invalid = False
        self.sealed = False
        self.closed = False
        self.stack = AsyncExitStack()

    def fail(self):
        self.invalid = True

    def check_read(self):
        if (self.closed or self.sealed or asyncio.current_task() is not self.owner
            or self.repository.db.db_engine is not self.engine
            or self.engine.get_execution_options().get('schema_translate_map') != self.schema_map):
            self.fail()
            raise self._changed()

    def observe(self, table, row):
        self.check_read()
        if row is None:
            self.fail()
            return
        # 在模型转换或交给调用方前计算完整原始行身份，JSON类型差异不能被==吞掉。
        value = dict(row._mapping)
        key = (table.name, value['report_run_id'])
        fingerprint = payload_sha256(value)
        previous = self.rows.setdefault(key, (table, fingerprint))
        if previous[1] != fingerprint:
            self.fail()

    @staticmethod
    def _changed():
        return ReportingStateError('report_state_read_changed', '批准依赖的工作流状态缺失、变化或未完整读取，请重新验收。')

    def shares_pool(self, engine):
        return self.engine.pool is engine.pool

    async def lock(self, connection=None):
        self.check_read()
        if self.invalid or not self.rows:
            raise self._changed()
        self.sealed = True
        if connection is None:
            connection = await self.stack.enter_async_context(self.engine.begin())
        elif not self.shares_pool(connection.engine):
            self.fail()
            raise self._changed()
        for (_, run_id), (table, expected) in sorted(self.rows.items()):
            query = select(table).where(table.c.report_run_id == run_id).with_for_update(read=True)
            # execute级显式覆盖连接级映射（包括None），不能改共享连接的全局选项。
            row = (await connection.execute(query, execution_options={
                'schema_translate_map': self.schema_map})).first()
            if row is None or payload_sha256(dict(row._mapping)) != expected:
                self.fail()
                raise self._changed()
        if self.invalid:
            raise self._changed()

    async def close(self):
        self.closed = True
        await self.stack.aclose()
