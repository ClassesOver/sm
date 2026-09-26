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
    WarningCheck,
    WarningFinding,
    WarningQuery,
)
from .policy import QualityWarningContractError, get_warning_rule
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
        return await self.record_successful_checks(
            tenant=tenant,
            checks=(
                WarningCheck(
                    checkScope=check_scope,
                    findings=tuple(findings),
                    context=context,
                ),
            ),
        )

    async def record_successful_checks(
        self,
        *,
        tenant: TenantScope,
        checks: Sequence[WarningCheck],
    ) -> tuple[QualityWarningRecord, ...]:
        if not checks:
            raise ValueError("成功检查批次不能为空。")
        check_ids = [check.context.check_id for check in checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("成功检查批次不能包含重复 check_id。")
        scopes = [
            (
                check.check_scope.domain,
                check.check_scope.rule_code,
                check.check_scope.subject_type,
            )
            for check in checks
        ]
        if len(scopes) != len(set(scopes)):
            raise ValueError("成功检查批次不能包含重复检查范围。")
        for check in checks:
            scope = check.check_scope
            for finding in check.findings:
                rule = get_warning_rule(finding.rule_code)
                if (
                    finding.rule_code != scope.rule_code
                    or finding.subject_type != scope.subject_type
                ):
                    raise ValueError("finding 必须与成功检查的规则和主体类型一致。")
                if not scope.covers(finding.subject_id):
                    raise ValueError("finding 主体不在成功检查声明的覆盖范围内。")
                if finding.subject_type not in rule.subject_types:
                    raise QualityWarningContractError(
                        f"规则 {finding.rule_code} 不允许主体类型 {finding.subject_type}。"
                    )
                if finding.disposition != rule.disposition:
                    raise QualityWarningContractError(
                        f"规则 {finding.rule_code} 的 disposition 不匹配。"
                    )
        return await self.repository.record_successful_checks(tenant=tenant, checks=checks)

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
