from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from .models import (
    CheckContext,
    CheckScope,
    QualityWarningEvent,
    QualityWarningPage,
    QualityWarningRecord,
    TenantScope,
    WarningFinding,
    WarningQuery,
)
from .repository import QualityWarningRepository


class QualityWarningService:
    """全局告警写入门面，阻止业务阶段用错误范围关闭历史问题。"""

    def __init__(self, repository: QualityWarningRepository):
        self.repository = repository

    async def create_schema(self) -> None:
        await self.repository.create_schema()

    async def record_successful_check(
        self,
        *,
        tenant: TenantScope,
        check_scope: CheckScope,
        findings: Sequence[WarningFinding],
        context: CheckContext,
    ) -> tuple[QualityWarningRecord, ...]:
        for finding in findings:
            if (
                finding.rule_code != check_scope.rule_code
                or finding.subject_type != check_scope.subject_type
            ):
                raise ValueError("finding 必须与成功检查的规则和主体类型一致。")
            if finding.subject_id not in check_scope.covered_subject_ids:
                raise ValueError("finding 主体不在成功检查声明的覆盖范围内。")
        return await self.repository.record_successful_check(
            tenant=tenant,
            check_scope=check_scope,
            findings=findings,
            context=context,
        )

    async def list_warnings(
        self, *, tenant: TenantScope, query: WarningQuery
    ) -> tuple[QualityWarningRecord, ...]:
        return await self.repository.list_warnings(tenant=tenant, query=query)

    async def list_warning_page(
        self, *, tenant: TenantScope, query: WarningQuery
    ) -> QualityWarningPage:
        return await self.repository.list_warning_page(tenant=tenant, query=query)

    async def get_warning(
        self, *, tenant: TenantScope, warning_id: UUID
    ) -> QualityWarningRecord | None:
        return await self.repository.get_warning(tenant=tenant, warning_id=warning_id)

    async def list_events(
        self, *, tenant: TenantScope, warning_id: UUID
    ) -> tuple[QualityWarningEvent, ...]:
        return await self.repository.list_events(tenant=tenant, warning_id=warning_id)
