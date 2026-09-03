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
    QualityWarningPage,
    QualityWarningRecord,
    QualityWarningService,
    TenantScope,
    WarningFinding,
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
