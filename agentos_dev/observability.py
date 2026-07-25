from __future__ import annotations

from agno.db.base import AsyncBaseDb, BaseDb


class TracingConfigurationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def configure_tracing(
    database: AsyncBaseDb | BaseDb,
    *,
    enabled: bool,
    phoenix_endpoint: str | None = None,
    phoenix_api_key: str | None = None,
    phoenix_project_name: str = "agentos",
) -> None:
    if not enabled:
        return

    try:
        if phoenix_endpoint is None:
            from agno.tracing import setup_tracing

            setup_tracing(db=database)
        else:
            _configure_phoenix_tracing(
                database,
                endpoint=phoenix_endpoint,
                api_key=phoenix_api_key,
                project_name=phoenix_project_name,
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
    provider.add_span_processor(SimpleSpanProcessor(DatabaseSpanExporter(db=database)))
    headers = {"api_key": api_key} if api_key is not None else None
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
    )
    trace_api.set_tracer_provider(provider)
    AgnoInstrumentor().instrument(tracer_provider=provider)
