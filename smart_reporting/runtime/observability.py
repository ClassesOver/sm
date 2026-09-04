from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from agno.db.base import AsyncBaseDb, BaseDb


class TracingConfigurationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@contextmanager
def suppress_expected_probe_tracing() -> Iterator[None]:
    """隐藏正常的 Daytona 存在性探测 span，不影响真实失败的父级业务 span。

    工作区安装目录和临时清理路径允许在首次运行时不存在，底层 SDK 会以
    DaytonaNotFoundError 表示该分支。OpenTelemetry 默认仍会把这类被捕获的
    404 记录为 ERROR，造成业务成功但 trace 失败。仅对调用方已经明确将
    NotFound 作为正常分支的短探测使用该上下文；其余读写、权限和哈希错误仍照常追踪。
    """
    try:
        from opentelemetry.instrumentation.utils import suppress_instrumentation
    except (ImportError, AttributeError):
        yield
        return
    with suppress_instrumentation():
        yield


def configure_tracing(
    database: AsyncBaseDb | BaseDb,
    *,
    enabled: bool,
    batch_processing: bool = False,
) -> None:
    if not enabled:
        return

    try:
        from agno.tracing import setup_tracing

        if batch_processing:
            setup_tracing(db=database, batch_processing=True)
        else:
            setup_tracing(db=database)
    except ImportError as error:
        raise TracingConfigurationError("agent_tracing_dependency_missing") from error
    except Exception as error:
        raise TracingConfigurationError("agent_tracing_initialization_failed") from error


def flush_tracing(timeout_millis: int = 30_000) -> bool:
    from opentelemetry import trace as trace_api

    force_flush = getattr(trace_api.get_tracer_provider(), "force_flush", None)
    if not callable(force_flush):
        return True
    return bool(force_flush(timeout_millis))
