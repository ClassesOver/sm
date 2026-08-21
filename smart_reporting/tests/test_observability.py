import builtins
import os
from contextlib import contextmanager

import pytest

from smart_reporting.observability import (
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

    monkeypatch.setattr("opentelemetry.instrumentation.utils.suppress_instrumentation", suppress)

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
