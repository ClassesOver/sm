from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from smart_reporting.database import create_agent_database
from smart_reporting.quality_warnings import (
    CheckContext,
    CheckScope,
    QualityWarningService,
    TenantScope,
    WarningFinding,
    WarningQuery,
)
from smart_reporting.quality_warnings.repository import SqlAlchemyQualityWarningRepository


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
