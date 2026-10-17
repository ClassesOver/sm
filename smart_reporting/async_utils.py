import asyncio
from collections.abc import Awaitable
from contextvars import ContextVar, Token
from typing import Any

from loguru import logger


async def complete_cleanup[T](operation: Awaitable[T]) -> T:
    task = asyncio.ensure_future(operation)
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


def safe_reset_context_var(variable: ContextVar[Any], token: Token[Any], *, event: str) -> None:
    """取消跨任务清理时忽略已不属于当前 Context 的 token。"""

    try:
        variable.reset(token)
    except ValueError:
        logger.debug(event)
