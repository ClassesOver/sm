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
from smart_reporting.quality_warnings.policy import warning_rules


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


def test_source_warning_with_many_datasets_uses_bounded_stable_subject() -> None:
    # 真实 dataset id 为 40 字符；3 个以上直接拼接会超过 128 字符主体上限。
    dataset_ids = [f"dataset-{str(index) * 32}" for index in range(5)]
    notices = [
        WarningAdapter.from_source_warning(
            {"code": "source_coverage_difference", "message": "覆盖不同", "datasetIds": ids},
            source_phase="analysis",
        )
        for ids in (dataset_ids, list(reversed(dataset_ids)))
    ]

    assert notices[0].subject_id == notices[1].subject_id
    assert notices[0].subject_id.startswith("datasets:sha256:")
    assert len(notices[0].subject_id) <= 128
    assert notices[0].details["datasetIds"] == dataset_ids
    short = WarningAdapter.from_source_warning(
        {"code": "source_coverage_difference", "message": "覆盖不同", "datasetIds": ["b", "a"]},
        source_phase="analysis",
    )
    assert short.subject_id == "datasets:a,b"


def test_structurally_invalid_notice_is_contract_error() -> None:
    with pytest.raises(QualityWarningContractError):
        WarningEmitter(source_phase="publication").emit(
            code="report_period_basis_conflict",
            subject_type="section_claim",
            subject_id="c" * 129,
            message="期间口径冲突",
        )


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
    checks = {
        (check.check_scope.rule_code, check.check_scope.subject_type): check
        for check in calls[0][1]
    }
    # 每个已登记规则/主体类型都提交检查，未再出现的既有告警才能被解决。
    assert set(checks) == {
        (rule.code, subject_type) for rule in warning_rules() for subject_type in rule.subject_types
    }
    check = checks[("report_period_basis_conflict", "section_claim")]
    assert check.context.check_id == (
        "publication:run-1:2:report_period_basis_conflict:section_claim"
    )
    assert check.check_scope.covered_subject_prefix == "run-1:"
    [finding] = check.findings
    assert finding.subject_id == "run-1:claim-1"
    assert finding.details["subjectLocalId"] == "claim-1"
    assert finding.details["sourcePhases"] == ["publication"]
    assert all(not item.findings for key, item in checks.items() if key != check_key(check))


def check_key(check) -> tuple[str, str]:
    return check.check_scope.rule_code, check.check_scope.subject_type


@pytest.mark.anyio
async def test_collector_without_findings_still_records_full_check() -> None:
    calls = []

    class Service:
        async def record_successful_checks(self, *, tenant, checks):
            calls.append(checks)

    collector = QualityAuditCollector(report_run_id="run-1", revision=3)
    result = await collector.flush(
        service=Service(),
        tenant=TenantScope(database_name="db", company_id="42"),
    )

    assert result.flush_status == "committed"
    assert calls and all(not check.findings for check in calls[0])


def test_run_subject_ids_are_bounded_and_report_subject_is_stable() -> None:
    from smart_reporting.quality_warnings.audit import _run_subject_id, _run_subject_prefix

    prefix = _run_subject_prefix("0b0e8f5e-1d2c-4f7a-9a51-2f7a3d9d5c11")
    assert _run_subject_id(prefix, subject_type="report", subject_id="whatever") == (
        f"{prefix}report"
    )
    long_id = _run_subject_id(prefix, subject_type="section_claim", subject_id="c" * 128)
    assert long_id.startswith(f"{prefix}sha256:") and len(long_id) <= 128
    long_run = _run_subject_prefix("r" * 200)
    assert long_run.startswith("run-sha256-") and len(long_run) <= 49
