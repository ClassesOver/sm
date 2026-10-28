"""无需数据库的任务调度锁重入与互斥契约。"""

import asyncio
from contextlib import nullcontext

import pytest

from smart_reporting.task_execution.execution import _AsyncRWLock


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("inner_failure", [False, True])
async def test_nested_writer_keeps_other_tasks_blocked_until_outer_exit(inner_failure):
    lock = _AsyncRWLock()
    reader_waiting, writer_waiting = asyncio.Event(), asyncio.Event()
    reader_entered, writer_entered = asyncio.Event(), asyncio.Event()

    async def read():
        reader_waiting.set()
        async with lock.read():
            reader_entered.set()

    async def write():
        writer_waiting.set()
        async with lock.write():
            writer_entered.set()

    async with lock.write():
        with pytest.raises(RuntimeError, match="inner failure") if inner_failure else nullcontext():
            async with lock.write():
                reader = asyncio.create_task(read())
                writer = asyncio.create_task(write())
                await asyncio.wait_for(
                    asyncio.gather(reader_waiting.wait(), writer_waiting.wait()), timeout=1
                )
                assert not reader_entered.is_set()
                assert not writer_entered.is_set()
                if inner_failure:
                    raise RuntimeError("inner failure")
        assert not reader_entered.is_set()
        assert not writer_entered.is_set()

    await asyncio.wait_for(asyncio.gather(reader, writer), timeout=1)
    assert reader_entered.is_set()
    assert writer_entered.is_set()
