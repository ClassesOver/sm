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
    phoenix_endpoint: str | None = None,
    phoenix_api_key: str | None = None,
    phoenix_project_name: str = "agentos",
) -> None:
    if not enabled:
        return

    try:
        if phoenix_endpoint is None:
            from agno.tracing import setup_tracing

            if batch_processing:
                setup_tracing(db=database, batch_processing=True)
            else:
                setup_tracing(db=database)
        else:
            _configure_phoenix_tracing(
                database,
                endpoint=phoenix_endpoint,
                api_key=phoenix_api_key,
                project_name=phoenix_project_name,
                batch_processing=batch_processing,
            )
    except ImportError as error:
        raise TracingConfigurationError("agent_tracing_dependency_missing") from error
    except Exception as error:
        raise TracingConfigurationError("agent_tracing_initialization_failed") from error


def _configure_phoenix_tracing(
    database: AsyncBaseDb | BaseDb,
    *,
    endpoint: str,
    api_key: str | None,
    project_name: str,
    batch_processing: bool,
) -> None:
    from agno.tracing.exporter import DatabaseSpanExporter
    from openinference.instrumentation.agno import AgnoInstrumentor
    from opentelemetry import trace as trace_api
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

    current_provider = trace_api.get_tracer_provider()
    if isinstance(current_provider, TracerProvider):
        return

    provider = TracerProvider(
        resource=Resource.create({"openinference.project.name": project_name})
    )
    database_processor = BatchSpanProcessor if batch_processing else SimpleSpanProcessor
    provider.add_span_processor(database_processor(DatabaseSpanExporter(db=database)))
    headers = {"api_key": api_key} if api_key is not None else None
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
    )
    trace_api.set_tracer_provider(provider)
    AgnoInstrumentor().instrument(tracer_provider=provider)


def flush_tracing(timeout_millis: int = 30_000) -> bool:
    from opentelemetry import trace as trace_api

    force_flush = getattr(trace_api.get_tracer_provider(), "force_flush", None)
    if not callable(force_flush):
        return True
    return bool(force_flush(timeout_millis))
