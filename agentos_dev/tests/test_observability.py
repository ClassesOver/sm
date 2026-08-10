import builtins
import os
import sys
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

import pytest

from agentos_dev.observability import (
    TracingConfigurationError,
    configure_tracing,
    flush_tracing,
    suppress_expected_probe_tracing,
)


def test_expected_probe_uses_opentelemetry_suppression(monkeypatch):
    calls = []

    @contextmanager
    def suppress():
        calls.append("enter")
        try:
            yield
        finally:
            calls.append("exit")

    monkeypatch.setattr(
        "opentelemetry.instrumentation.utils.suppress_instrumentation", suppress
    )

    with suppress_expected_probe_tracing():
        calls.append("probe")

    assert calls == ["enter", "probe", "exit"]


def test_configure_tracing_is_noop_when_disabled(monkeypatch):
    monkeypatch.setitem(os.environ, "OPENINFERENCE_HIDE_INPUTS", "true")
    before = dict(os.environ)
    original_import = builtins.__import__

    def reject_tracing_import(name, *args, **kwargs):
        if name == "agno.tracing":
            raise AssertionError("关闭 tracing 时不应加载 Agno tracing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_tracing_import)

    configure_tracing(object(), enabled=False)  # type: ignore[arg-type]

    assert dict(os.environ) == before


def test_configure_tracing_uses_agno_defaults(monkeypatch):
    calls = []
    database = object()
    before = {
        name: os.environ.get(name)
        for name in (
            "OPENINFERENCE_HIDE_INPUTS",
            "OPENINFERENCE_HIDE_OUTPUTS",
            "OPENINFERENCE_HIDE_INPUT_MESSAGES",
            "OPENINFERENCE_HIDE_OUTPUT_MESSAGES",
        )
    }
    monkeypatch.setattr("agno.tracing.setup_tracing", lambda **values: calls.append(values))

    configure_tracing(database, enabled=True)  # type: ignore[arg-type]

    assert calls == [{"db": database}]
    assert {name: os.environ.get(name) for name in before} == before


def test_configure_tracing_supports_batched_database_export(monkeypatch):
    calls = []
    database = object()
    monkeypatch.setattr("agno.tracing.setup_tracing", lambda **values: calls.append(values))

    configure_tracing(database, enabled=True, batch_processing=True)  # type: ignore[arg-type]

    assert calls == [{"db": database, "batch_processing": True}]


def test_flush_tracing_forces_current_provider(monkeypatch):
    calls = []

    class Provider:
        def force_flush(self, timeout_millis):
            calls.append(timeout_millis)
            return True

    monkeypatch.setattr("opentelemetry.trace.get_tracer_provider", lambda: Provider())

    assert flush_tracing() is True
    assert calls == [30_000]


def test_flush_tracing_is_a_noop_without_a_flushable_provider(monkeypatch):
    monkeypatch.setattr("opentelemetry.trace.get_tracer_provider", lambda: object())

    assert flush_tracing() is True


def test_configure_tracing_writes_to_database_and_phoenix(monkeypatch):
    created = {}

    class FakeDatabaseExporter:
        def __init__(self, **values):
            self.values = values

    class FakeOtlpExporter:
        def __init__(self, **values):
            self.values = values

    class FakeSimpleProcessor:
        def __init__(self, exporter):
            self.exporter = exporter

    class FakeBatchProcessor:
        def __init__(self, exporter):
            self.exporter = exporter

    class FakeProvider:
        def __init__(self, **values):
            self.values = values
            self.processors = []

        def add_span_processor(self, processor):
            self.processors.append(processor)

    class FakeResource:
        @staticmethod
        def create(attributes):
            return attributes

    class FakeInstrumentor:
        def instrument(self, **values):
            created["instrumented"] = values

    trace_api = SimpleNamespace(
        get_tracer_provider=lambda: object(),
        set_tracer_provider=lambda provider: created.setdefault("provider", provider),
    )

    def module(name, **attributes):
        value = ModuleType(name)
        value.__dict__.update(attributes)
        value.__path__ = []
        monkeypatch.setitem(sys.modules, name, value)
        return value

    module("agno.tracing.exporter", DatabaseSpanExporter=FakeDatabaseExporter)
    module("openinference")
    module("openinference.instrumentation")
    module("openinference.instrumentation.agno", AgnoInstrumentor=FakeInstrumentor)
    module("opentelemetry", trace=trace_api)
    module("opentelemetry.exporter")
    module("opentelemetry.exporter.otlp")
    module("opentelemetry.exporter.otlp.proto")
    module("opentelemetry.exporter.otlp.proto.http")
    module(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        OTLPSpanExporter=FakeOtlpExporter,
    )
    module("opentelemetry.sdk")
    module("opentelemetry.sdk.resources", Resource=FakeResource)
    module("opentelemetry.sdk.trace", TracerProvider=FakeProvider)
    module(
        "opentelemetry.sdk.trace.export",
        BatchSpanProcessor=FakeBatchProcessor,
        SimpleSpanProcessor=FakeSimpleProcessor,
    )
    database = object()

    configure_tracing(
        database,  # type: ignore[arg-type]
        enabled=True,
        phoenix_endpoint="https://phoenix.example/v1/traces",
        phoenix_api_key="secret",
        phoenix_project_name="hrp",
    )

    provider = created["provider"]
    assert provider.values == {"resource": {"openinference.project.name": "hrp"}}
    assert len(provider.processors) == 2
    assert isinstance(provider.processors[0], FakeSimpleProcessor)
    assert provider.processors[0].exporter.values == {"db": database}
    assert isinstance(provider.processors[1], FakeBatchProcessor)
    assert provider.processors[1].exporter.values == {
        "endpoint": "https://phoenix.example/v1/traces",
        "headers": {"api_key": "secret"},
    }
    assert created["instrumented"] == {"tracer_provider": provider}


def test_configure_tracing_fails_when_dependency_is_missing(monkeypatch):
    def fail(**_values):
        raise ImportError("missing")

    monkeypatch.setattr("agno.tracing.setup_tracing", fail)

    with pytest.raises(TracingConfigurationError) as rejected:
        configure_tracing(object(), enabled=True)  # type: ignore[arg-type]

    assert rejected.value.code == "agent_tracing_dependency_missing"


def test_configure_tracing_fails_when_initialization_fails(monkeypatch):
    def fail(**_values):
        raise RuntimeError("failed")

    monkeypatch.setattr("agno.tracing.setup_tracing", fail)

    with pytest.raises(TracingConfigurationError) as rejected:
        configure_tracing(object(), enabled=True)  # type: ignore[arg-type]

    assert rejected.value.code == "agent_tracing_initialization_failed"
