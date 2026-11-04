"""Office 引擎子进程（Node 桥接、LibreOffice）的进程内并发上限。

每次调用都会启动一个 CPU 密集的子进程。默认线程池按 CPU 数放大并发，多人同时编辑
或预览时会把 CPU 占满。这里用固定大小的独立线程池串起所有引擎调用：超出上限的调用
排队等待；协程取消时尚未开始的任务直接放弃，不再启动子进程。
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from loguru import logger

_CONCURRENCY_ENV = "AGENT_REPORTING_OFFICE_ENGINE_CONCURRENCY"
_QUEUE_WAIT_WARNING_SECONDS = 5.0

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def office_engine_concurrency() -> int:
    """读取并发上限；未配置或无效时取 CPU 数的一半（1–4）。"""
    raw = os.environ.get(_CONCURRENCY_ENV, "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if value >= 1:
            return value
        logger.warning("office_engine_concurrency_invalid value={!r}", raw)
    return max(1, min(4, (os.cpu_count() or 2) // 2))


def _engine_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(
                    max_workers=office_engine_concurrency(),
                    thread_name_prefix="office-engine",
                )
    return _executor


async def run_office_engine[T](func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """在受限线程池中执行同步引擎调用，保留调用方上下文变量（含 loguru 上下文）。"""
    submitted = time.monotonic()
    name = getattr(func, "__qualname__", repr(func))

    def call() -> T:
        waited = time.monotonic() - submitted
        if waited >= _QUEUE_WAIT_WARNING_SECONDS:
            logger.warning("office_engine_queue_wait name={} waited_s={:.1f}", name, waited)
        return func(*args, **kwargs)

    context = contextvars.copy_context()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_engine_executor(), functools.partial(context.run, call))
