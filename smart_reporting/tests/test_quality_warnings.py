from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from smart_reporting.quality_warnings import (
    CheckContext,
    CheckScope,
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
