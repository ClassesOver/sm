from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

import smart_reporting.reporting.diagnostics as diagnostics_module
from smart_reporting.reporting.data_source.starrocks import parse_starrocks_source
from smart_reporting.reporting.diagnostics import (
    ReportingDependencyDiagnostics,
    create_reporting_dependency_diagnostics_router,
)
from smart_reporting.reporting.models import ReportingError


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _source(source_id: str = "rj"):
    return parse_starrocks_source(
        {
            "id": source_id,
            "type": "starrocks",
            "name": "测试数据源",
            "dsnEnv": "REPORT_STARROCKS_DSN",
        },
        {
            "REPORT_STARROCKS_DSN": (
                "starrocks://diagnostic-user:diagnostic-password@starrocks.internal:9030/dwd"
            )
        },
    )


class FakeAdapter:
    def __init__(self, _source: Any, *, error: ReportingError | None = None):
        self.error = error
        self.queries: list[str] = []
        self.closed = False

    async def query(self, sql: str) -> None:
        self.queries.append(sql)
        if self.error is not None:
            raise self.error

    async def aclose(self) -> None:
        self.closed = True


class FakeMetadataClient:
    def __init__(self, error: ReportingError | None = None):
        self.error = error
        self.calls = 0

    async def query_agent(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


class FakeSandboxCheck:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = 0

    async def __call__(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


def _app(diagnostics: ReportingDependencyDiagnostics) -> FastAPI:
    application = FastAPI()
    application.include_router(create_reporting_dependency_diagnostics_router(diagnostics))
    return application


@pytest.mark.anyio
async def test_reporting_dependency_diagnostics_checks_configured_services() -> None:
    adapters: list[FakeAdapter] = []
    metadata = FakeMetadataClient()
    sandbox = FakeSandboxCheck()

    def adapter_factory(source: Any) -> FakeAdapter:
        adapter = FakeAdapter(source)
        adapters.append(adapter)
        return adapter

    diagnostics = ReportingDependencyDiagnostics(
        sources=(_source(),),
        metadata_client=metadata,
        sandbox_check=sandbox,
        starrocks_adapter_factory=adapter_factory,
    )

    result = await diagnostics.check()

    assert result.status == "ok"
    assert result.checks.starrocks.ok is True
    assert result.checks.starrocks.sources[0].source_id == "rj"
    assert result.checks.starrocks.sources[0].code == "ok"
    assert result.checks.metadata.ok is True
    assert result.checks.sandbox.ok is True
    assert adapters[0].queries == ["SELECT 1 AS connection_test"]
    assert adapters[0].closed is True
    assert metadata.calls == 1
    assert sandbox.calls == 1


@pytest.mark.anyio
async def test_reporting_dependency_diagnostics_returns_safe_failure_codes(caplog) -> None:
    adapter = FakeAdapter(
        _source(),
        error=ReportingError("source_query_failed", "包含 diagnostic-password"),
    )
    diagnostics = ReportingDependencyDiagnostics(
        sources=(_source(),),
        metadata_client=FakeMetadataClient(
            ReportingError(
                "report_metadata_rejected",
                "包含 metadata-secret",
                details={"httpStatus": 404},
            )
        ),
        sandbox_check=FakeSandboxCheck(RuntimeError("包含 daytona-secret")),
        starrocks_adapter_factory=lambda _source: adapter,
    )

    with caplog.at_level(logging.INFO, logger="smart_reporting.reporting.diagnostics"):
        result = await diagnostics.check()
    payload = result.model_dump(mode="json", by_alias=True)

    assert result.status == "failed"
    assert result.checks.starrocks.sources[0].code == "source_query_failed"
    assert result.checks.metadata.code == "report_metadata_rejected"
    assert result.checks.metadata.http_status == 404
    assert result.checks.sandbox.code == "sandbox_unavailable"
    assert adapter.closed is True
    serialized = str(payload)
    assert "diagnostic-password" not in serialized
    assert "metadata-secret" not in serialized
    assert "daytona-secret" not in serialized
    assert "dependency=starrocks" in caplog.text
    assert "dependency=metadata" in caplog.text
    assert "http_status=404" in caplog.text
    assert "dependency=sandbox" in caplog.text
    assert "diagnostic-password" not in caplog.text
    assert "metadata-secret" not in caplog.text
    assert "daytona-secret" not in caplog.text


def test_reporting_dependency_diagnostics_extracts_safe_nested_error_facts() -> None:
    database_error = OSError(2003, "连接 root:secret@starrocks.internal 失败")
    wrapped = ReportingError("source_query_failed", "包含 secret")
    wrapped.__cause__ = database_error

    facts = diagnostics_module._safe_error_facts(wrapped)

    assert facts == (("ReportingError", "OSError"), (2003,))


@pytest.mark.anyio
async def test_reporting_dependency_diagnostics_reports_missing_configuration() -> None:
    diagnostics = ReportingDependencyDiagnostics(
        sources=(),
        metadata_client=None,
        sandbox_check=None,
    )

    result = await diagnostics.check()

    assert result.status == "failed"
    assert result.checks.starrocks.code == "starrocks_not_configured"
    assert result.checks.metadata.code == "report_metadata_not_configured"
    assert result.checks.sandbox.code == "sandbox_not_configured"


@pytest.mark.anyio
async def test_reporting_dependency_diagnostics_times_out_sandbox_probe(monkeypatch) -> None:
    async def blocked_sandbox_check() -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(diagnostics_module, "SANDBOX_CHECK_TIMEOUT_SECONDS", 0.001)
    diagnostics = ReportingDependencyDiagnostics(
        sources=(_source(),),
        metadata_client=FakeMetadataClient(),
        sandbox_check=blocked_sandbox_check,
        starrocks_adapter_factory=lambda source: FakeAdapter(source),
    )

    result = await diagnostics.check()

    assert result.status == "failed"
    assert result.checks.sandbox.code == "sandbox_timeout"


@pytest.mark.anyio
async def test_reporting_dependency_diagnostics_times_out_starrocks_source(monkeypatch) -> None:
    class BlockedAdapter(FakeAdapter):
        async def query(self, sql: str) -> None:
            self.queries.append(sql)
            await asyncio.Event().wait()

    adapter = BlockedAdapter(_source())
    monkeypatch.setattr(diagnostics_module, "STARROCKS_CHECK_TIMEOUT_SECONDS", 0.001)
    diagnostics = ReportingDependencyDiagnostics(
        sources=(_source(),),
        metadata_client=FakeMetadataClient(),
        sandbox_check=FakeSandboxCheck(),
        starrocks_adapter_factory=lambda _source: adapter,
    )

    result = await diagnostics.check()

    assert result.status == "failed"
    assert result.checks.starrocks.sources[0].code == "starrocks_timeout"
    assert adapter.closed is True


@pytest.mark.anyio
async def test_reporting_dependency_diagnostics_limits_starrocks_concurrency(monkeypatch) -> None:
    active = 0
    maximum_active = 0

    class CountingAdapter(FakeAdapter):
        async def query(self, sql: str) -> None:
            nonlocal active, maximum_active
            self.queries.append(sql)
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0.01)
            active -= 1

    monkeypatch.setattr(diagnostics_module, "STARROCKS_CHECK_CONCURRENCY", 2)
    sources = tuple(_source(f"source-{index}") for index in range(5))
    diagnostics = ReportingDependencyDiagnostics(
        sources=sources,
        metadata_client=FakeMetadataClient(),
        sandbox_check=FakeSandboxCheck(),
        starrocks_adapter_factory=CountingAdapter,
    )

    result = await diagnostics.check()

    assert result.status == "ok"
    assert maximum_active == 2


@pytest.mark.anyio
async def test_reporting_dependency_diagnostics_route_returns_failed_status() -> None:
    diagnostics = ReportingDependencyDiagnostics(
        sources=(),
        metadata_client=None,
        sandbox_check=None,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(diagnostics)),
        base_url="http://test",
    ) as client:
        response = await client.post("/diagnostics/reporting-dependencies")

    assert response.status_code == 503
    assert response.json()["status"] == "failed"


@pytest.mark.anyio
async def test_reporting_dependency_diagnostics_route_returns_success() -> None:
    diagnostics = ReportingDependencyDiagnostics(
        sources=(_source(),),
        metadata_client=FakeMetadataClient(),
        sandbox_check=FakeSandboxCheck(),
        starrocks_adapter_factory=lambda source: FakeAdapter(source),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(diagnostics)),
        base_url="http://test",
    ) as client:
        response = await client.post("/diagnostics/reporting-dependencies")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["status"] == "ok"
