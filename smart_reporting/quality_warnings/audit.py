from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .models import (
    CheckContext,
    CheckScope,
    TenantScope,
    WarningCheck,
    WarningFinding,
    WarningNotice,
    warning_fingerprint,
)
from .policy import QualityWarningContractError, get_warning_rule, warning_rules

_SUBJECT_ID_MAX_LENGTH = 128


_RUN_KEY_MAX_LENGTH = 48


def _run_subject_prefix(report_run_id: str) -> str:
    """报告内主体（claim/block/chart 等）只在单次报告运行内唯一，台账身份需带运行前缀。"""

    run_key = (
        report_run_id
        if len(report_run_id) <= _RUN_KEY_MAX_LENGTH and ":" not in report_run_id
        else f"run-sha256-{hashlib.sha256(report_run_id.encode()).hexdigest()[:32]}"
    )
    return f"{run_key}:"


def _run_subject_id(prefix: str, *, subject_type: str, subject_id: str) -> str:
    local = "report" if subject_type == "report" else subject_id
    qualified = prefix + local
    if len(qualified) <= _SUBJECT_ID_MAX_LENGTH:
        return qualified
    return f"{prefix}sha256:{hashlib.sha256(local.encode()).hexdigest()}"


def _group_subject_id(prefix: str, ids: tuple[str, ...]) -> str:
    """多主体组合身份超过存储上限时退化为稳定摘要，完整 id 仍保留在 details。"""

    joined = ",".join(sorted(ids))
    if len(prefix) + len(joined) <= _SUBJECT_ID_MAX_LENGTH:
        return prefix + joined
    return f"{prefix}sha256:{hashlib.sha256(joined.encode()).hexdigest()}"


@dataclass(slots=True)
class WarningAuditResult:
    findings: tuple[WarningFinding, ...]
    total: int
    by_disposition: dict[str, int]
    by_source_phase: dict[str, int]
    requires_review: bool
    flush_status: str = "pending"

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "byDisposition": dict(self.by_disposition),
            "bySourcePhase": dict(self.by_source_phase),
            "requiresReview": self.requires_review,
            "flushStatus": self.flush_status,
        }


class WarningEmitter:
    def __init__(self, *, source_phase: str):
        if not source_phase:
            raise QualityWarningContractError("source_phase 不能为空。")
        self.source_phase = source_phase

    def emit(
        self,
        *,
        code: str,
        subject_type: str,
        subject_id: str,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> WarningNotice:
        rule = get_warning_rule(code)
        if not subject_type or not subject_id:
            raise QualityWarningContractError("告警必须显式提供主体。")
        if subject_type not in rule.subject_types:
            raise QualityWarningContractError(f"规则 {code} 不允许主体类型 {subject_type}。")
        try:
            return WarningNotice(
                ruleCode=code,
                subjectType=subject_type,
                subjectId=subject_id,
                message=message,
                details=dict(details or {}),
                sourcePhase=self.source_phase,
            )
        except ValidationError as error:
            # 字段超限等结构问题属于审计契约违例，交由发布门禁记为 issue，而不是
            # 以未分类异常中断整个质量审计。
            raise QualityWarningContractError(f"规则 {code} 的告警结构无效。") from error


class WarningAdapter:
    @staticmethod
    def from_notice(notice: WarningNotice) -> WarningNotice:
        """在跨阶段边界重新校验 notice，防止绕过规则目录构造对象。"""

        return WarningEmitter(source_phase=notice.source_phase).emit(
            code=notice.rule_code,
            subject_type=notice.subject_type,
            subject_id=notice.subject_id,
            message=notice.message,
            details=notice.details,
        )

    @staticmethod
    def from_source_warning(source_warning: Any, *, source_phase: str) -> WarningNotice:
        if hasattr(source_warning, "model_dump"):
            value = source_warning.model_dump(mode="json", by_alias=True)
        elif isinstance(source_warning, Mapping):
            value = dict(source_warning)
        else:
            raise QualityWarningContractError("来源告警格式无效。")
        code = value.get("code")
        message = value.get("message")
        dataset_ids = tuple(str(item) for item in value.get("datasetIds", ()) or ())
        query_ids = tuple(str(item) for item in value.get("queryIds", ()) or ())
        if len(dataset_ids) == 1 and not query_ids:
            subject_type, subject_id = "dataset", dataset_ids[0]
        elif len(query_ids) == 1 and not dataset_ids:
            subject_type, subject_id = "query", query_ids[0]
        elif dataset_ids:
            subject_type, subject_id = "dataset", _group_subject_id("datasets:", dataset_ids)
        elif query_ids:
            subject_type, subject_id = "query", _group_subject_id("queries:", query_ids)
        else:
            raise QualityWarningContractError("来源告警缺少明确数据主体。")
        details = dict(value.get("details", {}) or {})
        if dataset_ids:
            details["datasetIds"] = list(dataset_ids)
        if query_ids:
            details["queryIds"] = list(query_ids)
        return WarningEmitter(source_phase=source_phase).emit(
            code=str(code),
            subject_type=subject_type,
            subject_id=subject_id,
            message=str(message),
            details=details,
        )

    @staticmethod
    def from_mapping(
        value: Mapping[str, Any], *, source_phase: str, subject_type: str, subject_id: str
    ) -> WarningNotice:
        code = value.get("code")
        message = value.get("message") or str(code or "")
        details = value.get("details", {})
        if not isinstance(code, str) or not isinstance(details, Mapping):
            raise QualityWarningContractError("告警映射格式无效。")
        return WarningEmitter(source_phase=source_phase).emit(
            code=code,
            subject_type=subject_type,
            subject_id=subject_id,
            message=str(message),
            details=dict(details),
        )


class QualityAuditCollector:
    def __init__(self, *, report_run_id: str, revision: int):
        if not report_run_id or revision < 0:
            raise QualityWarningContractError("审计运行身份无效。")
        self.report_run_id = report_run_id
        self.revision = revision
        self._notices: list[WarningNotice] = []

    def add(self, notice: WarningNotice) -> None:
        if len(self._notices) >= 2_000:
            raise QualityWarningContractError("单次审计告警数量超过限制。")
        if not isinstance(notice, WarningNotice):
            raise QualityWarningContractError("审计只能接收 WarningNotice。")
        self._notices.append(notice)

    def extend(self, notices: Sequence[WarningNotice]) -> None:
        for notice in notices:
            self.add(notice)

    def build(self) -> WarningAuditResult:
        merged: dict[tuple[str, str, str, str], WarningFinding] = {}
        phases: dict[tuple[str, str, str, str], set[str]] = {}
        for notice in self._notices:
            rule = get_warning_rule(notice.rule_code)
            finding = WarningFinding(
                rule_code=notice.rule_code,
                subject_type=notice.subject_type,
                subject_id=notice.subject_id,
                disposition=rule.disposition,
                message=notice.message,
                details=notice.details,
                sourcePhase=notice.source_phase,
            )
            key = (
                finding.rule_code,
                finding.subject_type,
                finding.subject_id,
                warning_fingerprint(finding),
            )
            phases.setdefault(key, set()).add(notice.source_phase)
            merged.setdefault(key, finding)
        findings = tuple(
            WarningFinding(
                rule_code=item.rule_code,
                subject_type=item.subject_type,
                subject_id=item.subject_id,
                severity=item.severity,
                disposition=item.disposition,
                sourcePhase=item.source_phase,
                sourcePhases=tuple(sorted(phases[key])),
                message=item.message,
                details=item.details,
            )
            for key, item in sorted(merged.items())
        )
        by_disposition = dict(Counter(item.disposition for item in findings))
        by_phase = Counter(phase for values in phases.values() for phase in sorted(values))
        return WarningAuditResult(
            findings=findings,
            total=len(findings),
            by_disposition=dict(sorted(by_disposition.items())),
            by_source_phase=dict(sorted(by_phase.items())),
            requires_review=any(item.disposition == "review_required" for item in findings),
        )

    async def flush(
        self, *, service: Any, tenant: TenantScope, complete: bool = True
    ) -> WarningAuditResult:
        """提交一次完整发布检查。

        发布门禁每次都会重算全部规则，因此对每个已登记的规则/主体类型都声明一次检查，
        覆盖范围为本次报告运行的全部主体：本次未再出现的既有告警即被判定为已解决，
        其他报告运行的告警不受影响。``complete=False`` 表示本次只收集到部分告警：
        仍记录发现，但不关闭任何既有告警。
        """

        result = self.build()
        prefix = _run_subject_prefix(self.report_run_id)
        grouped: dict[tuple[str, str], list[WarningFinding]] = {}
        for finding in result.findings:
            grouped.setdefault((finding.rule_code, finding.subject_type), []).append(
                WarningFinding(
                    rule_code=finding.rule_code,
                    subject_type=finding.subject_type,
                    subject_id=_run_subject_id(
                        prefix, subject_type=finding.subject_type, subject_id=finding.subject_id
                    ),
                    severity=finding.severity,
                    disposition=finding.disposition,
                    sourcePhase=finding.source_phase,
                    sourcePhases=finding.source_phases,
                    message=finding.message,
                    details={
                        **finding.details,
                        "subjectLocalId": finding.subject_id,
                        "sourcePhases": list(finding.source_phases),
                    },
                )
            )
        checks = []
        for rule in warning_rules():
            for subject_type in sorted(rule.subject_types):
                findings = grouped.pop((rule.code, subject_type), [])
                checks.append(
                    WarningCheck(
                        checkScope=CheckScope(
                            domain="reporting",
                            rule_code=rule.code,
                            subject_type=subject_type,
                            covered_subject_prefix=prefix,
                        ),
                        findings=tuple(findings),
                        reconcile=complete,
                        context=CheckContext(
                            check_id=(
                                f"publication:{self.report_run_id}:{self.revision}:"
                                f"{rule.code}:{subject_type}"
                            ),
                            report_run_id=self.report_run_id,
                            revision=self.revision,
                        ),
                    )
                )
        if grouped:
            raise QualityWarningContractError("存在未登记规则或主体类型的告警。")
        try:
            await service.record_successful_checks(tenant=tenant, checks=tuple(checks))
        except Exception:
            result.flush_status = "failed"
            raise
        result.flush_status = "committed"
        return result


__all__ = [
    "QualityAuditCollector",
    "WarningAdapter",
    "WarningAuditResult",
    "WarningEmitter",
]
