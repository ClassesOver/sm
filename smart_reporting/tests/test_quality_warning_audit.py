from __future__ import annotations

import pytest

from smart_reporting.quality_warnings import (
    QualityAuditCollector,
    QualityWarningContractError,
    TenantScope,
    WarningAdapter,
    WarningEmitter,
    get_warning_rule,
)


def test_registered_rule_exposes_disposition_and_subject_types() -> None:
    rule = get_warning_rule("report_period_basis_conflict")
    assert rule.disposition == "review_required"
    assert "section_claim" in rule.subject_types
    assert get_warning_rule("chart_path_normalized").disposition == "informational"


@pytest.mark.parametrize(
    "code",
    [
        "report_aggregation_duplicate_unresolved",
        "report_entity_grain_unproven",
        "report_cross_source_inference_unsupported",
    ],
)
def test_review_required_semantic_rule_accepts_section_claim(code: str) -> None:
    notice = WarningEmitter(source_phase="publication").emit(
        code=code,
        subject_type="section_claim",
        subject_id="claim-1",
        message="需要人工复核",
    )

    assert notice.subject_id == "claim-1"
    assert get_warning_rule(code).subject_types == {"section_claim"}


def test_duplicate_chart_binding_warning_is_auditable() -> None:
    notice = WarningEmitter(source_phase="publication").emit(
        code="report_section_chart_duplicate_binding",
        subject_type="analysis_chart",
        subject_id="chart-1",
        message="同一图表重复绑定",
    )
    collector = QualityAuditCollector(report_run_id="run-1", revision=2)
    collector.add(notice)

    result = collector.build()

    assert result.total == 1
    assert result.requires_review is False


def test_unknown_rule_is_rejected() -> None:
    with pytest.raises(QualityWarningContractError, match="规则未登记"):
        WarningEmitter(source_phase="publication").emit(
            code="unregistered_rule",
            subject_type="report",
            subject_id="run-1",
            message="未知规则",
        )


def test_collector_merges_same_root_cause_and_keeps_source_phases() -> None:
    collector = QualityAuditCollector(report_run_id="run-1", revision=2)
    collector.extend(
        (
            WarningEmitter(source_phase="analysis").emit(
                code="report_period_basis_conflict",
                subject_type="section_claim",
                subject_id="claim-1",
                message="期间口径冲突",
                details={"claimId": "claim-1", "field": "periodBasis"},
            ),
            WarningEmitter(source_phase="publication").emit(
                code="report_period_basis_conflict",
                subject_type="section_claim",
                subject_id="claim-1",
                message="期间口径冲突（发布复核）",
                details={"claimId": "claim-1", "field": "periodBasis"},
            ),
        )
    )
    audit = collector.build()
    assert len(audit.findings) == 1
    assert audit.findings[0].source_phases == ("analysis", "publication")
    assert audit.requires_review is True


def test_source_warning_adapter_preserves_dataset_references() -> None:
    source_warning = {
        "code": "source_data_quality",
        "message": "数据存在空值",
        "datasetIds": ["dataset-1"],
        "details": {"emptyRows": 1},
    }
    notice = WarningAdapter.from_source_warning(source_warning, source_phase="analysis")
    assert notice.details["datasetIds"] == ["dataset-1"]


@pytest.mark.anyio
async def test_collector_flushes_one_stable_check_per_scope() -> None:
    calls = []

    class Service:
        async def record_successful_checks(self, *, tenant, checks):
            calls.append((tenant, checks))

    collector = QualityAuditCollector(report_run_id="run-1", revision=2)
    collector.add(
        WarningEmitter(source_phase="publication").emit(
            code="report_period_basis_conflict",
            subject_type="section_claim",
            subject_id="claim-1",
            message="期间口径冲突",
            details={"field": "periodBasis"},
        )
    )
    result = await collector.flush(
        service=Service(),
        tenant=TenantScope(database_name="db", company_id="42"),
    )

    assert result.flush_status == "committed"
    assert len(calls) == 1
    assert calls[0][1][0].context.check_id == (
        "publication:run-1:2:report_period_basis_conflict:section_claim"
    )
    assert calls[0][1][0].findings[0].details["sourcePhases"] == ["publication"]
