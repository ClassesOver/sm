from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

_IDENTITY_MAX_LENGTH = 128
_TENANT_MAX_LENGTH = 256
_MESSAGE_MAX_LENGTH = 2_000
_DETAILS_MAX_BYTES = 16 * 1024
_SENSITIVE_DETAIL_KEYWORDS = frozenset(
    {"token", "capability", "password", "cookie", "secret", "authorization"}
)
_FINGERPRINT_DETAIL_KEYS = frozenset(
    {
        "chartId",
        "conflictingFields",
        "field",
        "missingFields",
        "metricCode",
        "reasonCode",
        "referenceType",
        "sectionCode",
        "blockId",
    }
)

NonEmptyIdentity = Annotated[str, Field(min_length=1, max_length=_IDENTITY_MAX_LENGTH)]
WarningDisposition = Literal["informational", "quality_warning", "review_required"]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class TenantScope(_FrozenModel):
    """由已验证身份构造的租户边界，绝不从告警查询参数接收。"""

    database_name: Annotated[str, Field(min_length=1, max_length=_TENANT_MAX_LENGTH)]
    company_id: Annotated[str, Field(min_length=1, max_length=_TENANT_MAX_LENGTH)]


class CheckScope(_FrozenModel):
    domain: NonEmptyIdentity
    rule_code: NonEmptyIdentity
    subject_type: NonEmptyIdentity
    covered_subject_ids: tuple[NonEmptyIdentity, ...] = Field(min_length=1, max_length=1_000)

    @field_validator("covered_subject_ids")
    @classmethod
    def _covered_subject_ids_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("covered_subject_ids 不能重复。")
        return value


class WarningFinding(_FrozenModel):
    rule_code: NonEmptyIdentity
    subject_type: NonEmptyIdentity
    subject_id: NonEmptyIdentity
    severity: Literal["warning"] = "warning"
    disposition: WarningDisposition = "quality_warning"
    source_phase: NonEmptyIdentity = Field(default="legacy", alias="sourcePhase")
    source_phases: tuple[NonEmptyIdentity, ...] = Field(default=(), alias="sourcePhases")
    message: Annotated[str, Field(min_length=1, max_length=_MESSAGE_MAX_LENGTH)]
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("details")
    @classmethod
    def _details_are_safe_json(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _assert_safe_detail_keys(value)
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > _DETAILS_MAX_BYTES:
            raise ValueError("details 超过大小限制。")
        return value

    @field_validator("source_phases")
    @classmethod
    def _source_phases_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("sourcePhases 不能重复。")
        return value


class WarningQuery(_FrozenModel):
    domain: NonEmptyIdentity | None = None
    status: Literal["open", "resolved"] = "open"
    rule_code: NonEmptyIdentity | None = None
    subject_type: NonEmptyIdentity | None = None
    subject_id: NonEmptyIdentity | None = None
    disposition: WarningDisposition | None = None
    first_observed_after: datetime | None = None
    last_observed_before: datetime | None = None
    cursor: Annotated[str, Field(min_length=1, max_length=1_024)] | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 50


class QualityWarningRecord(_FrozenModel):
    warning_id: UUID
    tenant: TenantScope
    domain: str
    rule_code: str
    subject_type: str
    subject_id: str
    fingerprint: str
    status: Literal["open", "resolved"]
    severity: Literal["warning"]
    message: str
    details: dict[str, JsonValue]
    first_observed_at: datetime
    last_observed_at: datetime
    resolved_at: datetime | None
    occurrence_count: int
    last_check_id: str
    version: int
    disposition: WarningDisposition = "quality_warning"
    source_phase: str = Field(default="legacy", alias="sourcePhase")


class QualityWarningEvent(_FrozenModel):
    event_id: UUID
    warning_id: UUID
    tenant: TenantScope
    event_type: Literal["detected", "rechecked_open", "resolved"]
    check_id: str
    occurred_at: datetime
    details: dict[str, JsonValue]


class WarningNotice(_FrozenModel):
    """阶段内产生的不可变告警通知，不包含租户或持久化状态。"""

    rule_code: NonEmptyIdentity = Field(alias="ruleCode")
    subject_type: NonEmptyIdentity = Field(alias="subjectType")
    subject_id: NonEmptyIdentity = Field(alias="subjectId")
    message: Annotated[str, Field(min_length=1, max_length=_MESSAGE_MAX_LENGTH)]
    details: dict[str, JsonValue] = Field(default_factory=dict)
    source_phase: NonEmptyIdentity = Field(alias="sourcePhase")

    @field_validator("details")
    @classmethod
    def _details_are_safe_json(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _assert_safe_detail_keys(value)
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > _DETAILS_MAX_BYTES:
            raise ValueError("details 超过大小限制。")
        return value


class QualityWarningPage(_FrozenModel):
    records: tuple[QualityWarningRecord, ...]
    next_cursor: str | None = None


class CheckContext(_FrozenModel):
    """可信运行上下文，仅在事件历史中保留定位所需的稳定标识。"""

    check_id: Annotated[str, Field(min_length=1, max_length=256)]
    report_run_id: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    revision: Annotated[int, Field(ge=0)] | None = None
    thread_id: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    user_id: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    session_id: Annotated[str, Field(min_length=1, max_length=256)] | None = None


class WarningCheck(_FrozenModel):
    """一次可原子提交的规则检查及其完整覆盖范围。"""

    check_scope: CheckScope = Field(alias="checkScope")
    findings: tuple[WarningFinding, ...] = Field(default=(), max_length=2_000)
    context: CheckContext


def warning_fingerprint(finding: WarningFinding) -> str:
    """以稳定根因聚合同一主体的重复发现，忽略运行时数值和运行身份。"""

    stable_details = {
        key: value for key, value in finding.details.items() if key in _FINGERPRINT_DETAIL_KEYS
    }
    canonical = json.dumps(
        {
            "ruleCode": finding.rule_code,
            "subjectType": finding.subject_type,
            "subjectId": finding.subject_id,
            "details": stable_details,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _assert_safe_detail_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("_", "").replace("-", "")
            if any(keyword in normalized for keyword in _SENSITIVE_DETAIL_KEYWORDS):
                raise ValueError("details 包含敏感字段。")
            _assert_safe_detail_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_safe_detail_keys(nested)
