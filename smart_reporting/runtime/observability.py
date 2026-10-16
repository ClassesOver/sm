from __future__ import annotations

from time import perf_counter

from agno.db.base import AsyncBaseDb, BaseDb


class TracingConfigurationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def duration_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))


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
