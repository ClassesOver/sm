from __future__ import annotations

import pytest
from pydantic import ValidationError

from smart_reporting.quality_warnings import (
    CheckScope,
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
