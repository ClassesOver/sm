from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from loguru import logger

from smart_reporting.quality_warnings import (
    CheckContext,
    CheckScope,
    QualityWarningService,
    TenantScope,
    WarningFinding,
    WarningQuery,
)
from smart_reporting.quality_warnings.repository import SqlAlchemyQualityWarningRepository
from smart_reporting.runtime.database import create_agent_database


def test_sql_quality_warning_repository_requires_postgresql() -> None:
    engine = SimpleNamespace(dialect=SimpleNamespace(name="mysql"))

    with pytest.raises(ValueError, match="只支持 PostgreSQL"):
        SqlAlchemyQualityWarningRepository(engine)  # type: ignore[arg-type]


def _integration_database_url() -> str:
    value = os.getenv("REPORTING_TEST_DB_URL", "").strip()
    if not value:
        pytest.skip("未设置 REPORTING_TEST_DB_URL，跳过 PostgreSQL 质量告警集成测试。")
    return value


@pytest.fixture
async def quality_warning_service():
    database = create_agent_database(_integration_database_url())
    repository = SqlAlchemyQualityWarningRepository(database.async_engine)
    await repository.create_schema()
    service = QualityWarningService(repository)
    tenant = TenantScope(
        database_name=f"integration-quality-warning-{uuid4().hex}", company_id="42"
    )
    try:
        yield service, tenant
    finally:
        await database.async_engine.dispose()
        database.sync_engine.dispose()


def _scope(*covered_subject_ids: str) -> CheckScope:
    return CheckScope(
        domain="reporting",
        rule_code="report_metric_definition_incomplete",
        subject_type="metric",
        covered_subject_ids=covered_subject_ids,
    )


def _finding(subject_id: str = "income_summary_total") -> WarningFinding:
    return WarningFinding(
        rule_code="report_metric_definition_incomplete",
        subject_type="metric",
        subject_id=subject_id,
        message="指标定义不完整。",
        details={"missingFields": ["unit"], "value": 1},
    )


@pytest.mark.anyio
async def test_quality_warning_persistence_cancellation_is_not_logged_as_error() -> None:
    class CancelledTransaction:
        async def __aenter__(self):
            raise asyncio.CancelledError

        async def __aexit__(self, *_args):
            return False

    engine = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        begin=lambda: CancelledTransaction(),
    )
    repository = SqlAlchemyQualityWarningRepository(engine)  # type: ignore[arg-type]
    records: list[str] = []
    sink_id = logger.add(records.append, level="ERROR", format="{message}")
    try:
        with pytest.raises(asyncio.CancelledError):
            await repository.record_successful_check(
                tenant=TenantScope(database_name="cancelled", company_id="42"),
                check_scope=_scope("metric-1"),
                findings=(_finding("metric-1"),),
                context=CheckContext(check_id="cancelled-check"),
            )
    finally:
        logger.remove(sink_id)

    assert "quality_warning_batch_persist_failed" not in "".join(records)


@pytest.mark.anyio
@pytest.mark.integration
async def test_successful_rechecks_are_idempotent_and_resolve_only_covered_subjects(
    quality_warning_service,
) -> None:
    service, tenant = quality_warning_service
    scope = _scope("income_summary_total")
    finding = _finding()

    first = await service.record_successful_check(
        tenant=tenant,
        check_scope=scope,
        findings=(finding,),
        context=CheckContext(check_id="analysis-1"),
    )
    repeated = await service.record_successful_check(
        tenant=tenant,
        check_scope=scope,
        findings=(finding,),
        context=CheckContext(check_id="analysis-1"),
    )
    rechecked = await service.record_successful_check(
        tenant=tenant,
        check_scope=scope,
        findings=(finding,),
        context=CheckContext(check_id="analysis-2"),
    )
    await service.record_successful_check(
        tenant=tenant,
        check_scope=scope,
        findings=(),
        context=CheckContext(check_id="analysis-3"),
    )

    assert first[0].warning_id == repeated[0].warning_id == rechecked[0].warning_id
    resolved = await service.list_warnings(tenant=tenant, query=WarningQuery(status="resolved"))
    events = await service.list_events(tenant=tenant, warning_id=first[0].warning_id)
    assert resolved[0].occurrence_count == 2
    assert [event.event_type for event in events] == ["detected", "rechecked_open", "resolved"]


@pytest.mark.anyio
@pytest.mark.integration
async def test_warning_history_is_tenant_isolated_and_parallel_rechecks_aggregate(
    quality_warning_service,
) -> None:
    service, tenant = quality_warning_service
    scope = _scope("income_summary_total")

    await asyncio.gather(
        *(
            service.record_successful_check(
                tenant=tenant,
                check_scope=scope,
                findings=(_finding(),),
                context=CheckContext(check_id=f"analysis-{index}"),
            )
            for index in range(2)
        )
    )

    own_warnings = await service.list_warnings(tenant=tenant, query=WarningQuery())
    other_warnings = await service.list_warnings(
        tenant=TenantScope(database_name=tenant.database_name, company_id="other"),
        query=WarningQuery(),
    )
    events = await service.list_events(tenant=tenant, warning_id=own_warnings[0].warning_id)
    assert own_warnings[0].occurrence_count == 2
    assert len(events) == 2
    assert other_warnings == ()


@pytest.mark.anyio
@pytest.mark.integration
async def test_publication_audit_resolves_fixed_warnings_without_touching_other_reports(
    quality_warning_service,
) -> None:
    from smart_reporting.quality_warnings import QualityAuditCollector, WarningEmitter

    service, tenant = quality_warning_service

    def claim_conflict(details: dict[str, str]):
        return WarningEmitter(source_phase="publication").emit(
            code="report_period_basis_conflict",
            subject_type="section_claim",
            subject_id="claim_001",
            message="期间口径冲突",
            details=details,
        )

    async def publish(run_id: str, revision: int, *notices) -> None:
        collector = QualityAuditCollector(report_run_id=run_id, revision=revision)
        collector.extend(notices)
        await collector.flush(service=service, tenant=tenant)

    # 两份报告的 claim id 都由模型生成为 claim_001，但属于不同主体。
    await publish("run-a", 1, claim_conflict({"sectionCode": "income"}))
    await publish("run-b", 1, claim_conflict({"sectionCode": "cost"}))
    open_records = await service.list_warnings(tenant=tenant, query=WarningQuery())
    assert sorted(item.subject_id for item in open_records) == [
        "run-a:claim_001",
        "run-b:claim_001",
    ]

    # 报告 A 修正后重新发布：其告警被解决，报告 B 的告警保持打开。
    await publish("run-a", 2)
    open_records = await service.list_warnings(tenant=tenant, query=WarningQuery())
    resolved = await service.list_warnings(tenant=tenant, query=WarningQuery(status="resolved"))
    assert [item.subject_id for item in open_records] == ["run-b:claim_001"]
    assert [item.subject_id for item in resolved] == ["run-a:claim_001"]


@pytest.mark.anyio
@pytest.mark.integration
async def test_incomplete_publication_audit_keeps_existing_warnings_open(
    quality_warning_service,
) -> None:
    from smart_reporting.quality_warnings import QualityAuditCollector, WarningEmitter

    service, tenant = quality_warning_service
    first = QualityAuditCollector(report_run_id="run-a", revision=1)
    first.add(
        WarningEmitter(source_phase="publication").emit(
            code="report_period_basis_conflict",
            subject_type="section_claim",
            subject_id="claim_001",
            message="期间口径冲突",
            details={"sectionCode": "income"},
        )
    )
    await first.flush(service=service, tenant=tenant)

    # 发布门禁未能读取冻结分析产物时，告警收集不完整，不能据此关闭既有告警。
    await QualityAuditCollector(report_run_id="run-a", revision=2).flush(
        service=service, tenant=tenant, complete=False
    )

    open_records = await service.list_warnings(tenant=tenant, query=WarningQuery())
    assert [item.subject_id for item in open_records] == ["run-a:claim_001"]
