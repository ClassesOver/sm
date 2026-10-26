from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from smart_reporting.quality_warnings import (
    CheckContext,
    CheckScope,
    QualityWarningEvent,
    QualityWarningEventPage,
    QualityWarningPage,
    QualityWarningRecord,
    QualityWarningService,
    TenantScope,
    WarningFinding,
    WarningQuery,
    warning_fingerprint,
)


def test_warning_fingerprint_ignores_dynamic_detail_values() -> None:
    first = WarningFinding(
        rule_code="report_metric_definition_incomplete",
        subject_type="metric",
        subject_id="income_summary_total",
        message="指标定义不完整。",
        details={"missingFields": ["unit"], "value": 1},
    )
    second = first.model_copy(update={"details": {"missingFields": ["unit"], "value": 99}})

    assert warning_fingerprint(first) == warning_fingerprint(second)


def test_check_scope_requires_explicit_complete_coverage() -> None:
    with pytest.raises(ValidationError):
        CheckScope(
            domain="reporting",
            rule_code="report_metric_definition_incomplete",
            subject_type="metric",
            covered_subject_ids=(),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rule_code", ""),
        ("subject_type", ""),
        ("subject_id", ""),
        ("rule_code", "x" * 129),
    ],
)
def test_warning_finding_rejects_empty_or_oversized_identity(field: str, value: str) -> None:
    values = {
        "rule_code": "report_metric_definition_incomplete",
        "subject_type": "metric",
        "subject_id": "income_summary_total",
        "message": "指标定义不完整。",
    }
    values[field] = value

    with pytest.raises(ValidationError):
        WarningFinding(**values)


@pytest.mark.parametrize("details", [{"token": "secret"}, {"nested": {"password": "secret"}}])
def test_warning_finding_rejects_sensitive_details(details: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        WarningFinding(
            rule_code="report_metric_definition_incomplete",
            subject_type="metric",
            subject_id="income_summary_total",
            message="指标定义不完整。",
            details=details,
        )


def test_warning_finding_rejects_source_phase_larger_than_database_column() -> None:
    with pytest.raises(ValidationError):
        WarningFinding(
            rule_code="report_metric_definition_incomplete",
            subject_type="metric",
            subject_id="income_summary_total",
            message="指标定义不完整。",
            sourcePhase="p" * 65,
        )


@pytest.mark.parametrize("field", ["first_observed_after", "last_observed_before"])
def test_warning_query_rejects_naive_time_filters(field: str) -> None:
    with pytest.raises(ValidationError, match="必须包含时区"):
        WarningQuery(**{field: datetime(2026, 1, 1)})


def test_tenant_scope_is_an_internal_contract_not_http_query_model() -> None:
    scope = TenantScope(database_name="hospital", company_id="42")

    assert scope.database_name == "hospital"
    assert "databaseName" not in scope.model_json_schema().get("properties", {})


@pytest.mark.anyio
async def test_quality_warning_list_uses_capability_tenant_and_defaults_to_open() -> None:
    from smart_reporting.quality_warnings.api import create_quality_warning_router

    record = QualityWarningRecord(
        warning_id=uuid4(),
        tenant=TenantScope(database_name="hospital", company_id="42"),
        domain="reporting",
        rule_code="report_metric_definition_incomplete",
        subject_type="metric",
        subject_id="income_summary_total",
        fingerprint="a" * 64,
        status="open",
        severity="warning",
        message="指标定义不完整。",
        details={},
        first_observed_at=datetime.now(UTC),
        last_observed_at=datetime.now(UTC),
        resolved_at=None,
        occurrence_count=1,
        last_check_id="analysis-1",
        version=1,
    )

    class Service:
        async def list_warning_page(self, *, tenant, query):
            assert tenant == record.tenant
            assert query.status == "open"
            assert query.disposition == "quality_warning"
            return QualityWarningPage(records=(record,))

    application = FastAPI()
    application.state.agentos_context = SimpleNamespace(quality_warning_service=Service())

    @application.middleware("http")
    async def capability(request, call_next):
        request.state.capability = SimpleNamespace(database="hospital", company=42)
        return await call_next(request)

    application.include_router(create_quality_warning_router())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/quality-warnings?disposition=quality_warning")

    assert response.status_code == 200
    assert response.json()["records"][0]["warning_id"] == str(record.warning_id)


@pytest.mark.anyio
async def test_quality_warning_events_are_cursor_paginated() -> None:
    from smart_reporting.quality_warnings.api import create_quality_warning_router

    tenant = TenantScope(database_name="hospital", company_id="42")
    warning_id = uuid4()
    record = QualityWarningRecord(
        warning_id=warning_id,
        tenant=tenant,
        domain="reporting",
        rule_code="report_metric_definition_incomplete",
        subject_type="metric",
        subject_id="income_summary_total",
        fingerprint="a" * 64,
        status="open",
        severity="warning",
        message="指标定义不完整。",
        details={},
        first_observed_at=datetime.now(UTC),
        last_observed_at=datetime.now(UTC),
        resolved_at=None,
        occurrence_count=1,
        last_check_id="analysis-1",
        version=1,
    )
    event = QualityWarningEvent(
        event_id=uuid4(),
        warning_id=warning_id,
        tenant=tenant,
        event_type="detected",
        check_id="analysis-1",
        occurred_at=datetime.now(UTC),
        details={},
    )

    class Service:
        async def list_warning_page(self, **_kwargs):
            raise AssertionError("warning list is not used by the event endpoint")

        async def get_warning(self, *, tenant, warning_id):
            return record

        async def list_event_page(self, *, tenant, warning_id, query):
            assert query.limit == 1 and query.cursor is None
            return QualityWarningEventPage(records=(event,), next_cursor="next")

    application = FastAPI()
    application.state.agentos_context = SimpleNamespace(quality_warning_service=Service())

    @application.middleware("http")
    async def capability(request, call_next):
        request.state.capability = SimpleNamespace(database="hospital", company=42)
        return await call_next(request)

    application.include_router(create_quality_warning_router())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get(f"/quality-warnings/{warning_id}/events?limit=1")
        malformed = await client.get(f"/quality-warnings/{warning_id}/events?cursor=not-a-cursor")

    assert response.status_code == 200
    assert response.json() == {"records": [event.model_dump(mode="json")], "next_cursor": "next"}
    assert malformed.status_code == 400
    assert malformed.json() == {"detail": "quality_warning_event_cursor_invalid"}


@pytest.mark.anyio
async def test_quality_warning_queries_require_verified_capability() -> None:
    from smart_reporting.quality_warnings.api import create_quality_warning_router

    application = FastAPI()
    application.state.agentos_context = SimpleNamespace(quality_warning_service=object())
    application.include_router(create_quality_warning_router())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/quality-warnings")

    assert response.status_code == 401
    assert response.json() == {"detail": "quality_warning_capability_required"}


@pytest.mark.anyio
async def test_service_rejects_findings_outside_declared_successful_check_scope() -> None:
    repository = SimpleNamespace(record_successful_check=None)
    service = QualityWarningService(repository)
    tenant = TenantScope(database_name="hospital", company_id="42")
    scope = CheckScope(
        domain="reporting",
        rule_code="report_metric_definition_incomplete",
        subject_type="metric",
        covered_subject_ids=("income_summary_total",),
    )
    finding = WarningFinding(
        rule_code="report_metric_definition_incomplete",
        subject_type="metric",
        subject_id="other_metric",
        message="指标定义不完整。",
    )

    with pytest.raises(ValueError, match="覆盖范围"):
        await service.record_successful_check(
            tenant=tenant,
            check_scope=scope,
            findings=(finding,),
            context=CheckContext(check_id="analysis-1"),
        )


@pytest.mark.anyio
async def test_quality_warning_list_rejects_malformed_cursor_as_bad_request() -> None:
    from smart_reporting.quality_warnings.api import create_quality_warning_router

    class Service:
        async def list_warning_page(self, *, tenant, query):
            raise AssertionError("malformed cursor must not reach the repository")

    application = FastAPI()
    application.state.agentos_context = SimpleNamespace(quality_warning_service=Service())

    @application.middleware("http")
    async def capability(request, call_next):
        request.state.capability = SimpleNamespace(database="hospital", company=42)
        return await call_next(request)

    application.include_router(create_quality_warning_router())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/quality-warnings?cursor=not-a-cursor")

    assert response.status_code == 400
    assert response.json() == {"detail": "quality_warning_cursor_invalid"}


@pytest.mark.anyio
async def test_quality_warning_list_rejects_naive_time_filter_at_http_boundary() -> None:
    from smart_reporting.quality_warnings.api import create_quality_warning_router

    class Service:
        async def list_warning_page(self, *, tenant, query):
            raise AssertionError("naive time filter must not reach the repository")

    application = FastAPI()
    application.state.agentos_context = SimpleNamespace(quality_warning_service=Service())

    @application.middleware("http")
    async def capability(request, call_next):
        request.state.capability = SimpleNamespace(database="hospital", company=42)
        return await call_next(request)

    application.include_router(create_quality_warning_router())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/quality-warnings?firstObservedAfter=2026-01-01T00:00:00")

    assert response.status_code == 422
    assert response.json() == {"detail": "quality_warning_time_filter_timezone_required"}
