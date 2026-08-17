import asyncio
from collections.abc import Awaitable


async def complete_cleanup[T](operation: Awaitable[T]) -> T:
    task = asyncio.ensure_future(operation)
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()
