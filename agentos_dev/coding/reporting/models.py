from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class SourceMode(StrEnum):
    TEMPORARY_DATABASE = "temporary_database"
    MANAGED_QUERY = "managed_query"
    PROVIDED_DATASET = "provided_dataset"
    WORKSPACE_REFERENCE = "workspace_reference"
    ODOO_EXPORT = "odoo_export"
    HYBRID = "hybrid"


class ReportingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class TemporarySourceRequest(BaseModel):
    """只存在于 intake 与临时凭据仓之间，禁止进入可序列化状态。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: Literal["starrocks"] = "starrocks"
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=9030, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr
    database: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_$]*$")

    @field_validator("host", "username")
    @classmethod
    def _strip_nonempty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("不能为空")
        return normalized

    def secret_payload(self) -> dict[str, str | int]:
        return {
            "source_type": self.source_type,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password.get_secret_value(),
            "database": self.database,
        }

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise TypeError("temporary_source_request_not_serializable")

    def model_dump_json(self, *args: Any, **kwargs: Any) -> str:
        raise TypeError("temporary_source_request_not_serializable")


class ReportSourceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    binding_id: str = Field(alias="bindingId", min_length=1, max_length=128)
    source_mode: SourceMode = Field(alias="sourceMode")
    database: str | None = Field(default=None, max_length=128)
    allowed_tables: tuple[str, ...] = Field(default=(), alias="allowedTables", max_length=500)
    metadata_fingerprint: str = Field(alias="metadataFingerprint", pattern=r"^[0-9a-f]{64}$")
    thread_id: str = Field(alias="threadId", min_length=1, max_length=256)
    user_id: str = Field(alias="userId", min_length=1, max_length=256)
    session_id: str = Field(alias="sessionId", min_length=1, max_length=256)
    expires_at: datetime = Field(alias="expiresAt")

    @field_validator("expires_at")
    @classmethod
    def _timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("expiresAt 必须包含时区")
        return value.astimezone(UTC)

    def public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class ReportOutline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    outline_id: str = Field(alias="outlineId", min_length=1, max_length=128)
    binding_id: str = Field(alias="bindingId", min_length=1, max_length=128)
    metadata_fingerprint: str = Field(alias="metadataFingerprint", pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=300)
    sections: tuple[str, ...] = Field(min_length=1, max_length=30)
    assumptions: tuple[str, ...] = Field(default=(), max_length=30)
    approved: bool = False


class AnalysisMethodDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: str = Field(min_length=1, max_length=64)
    decision: Literal["execute", "not_applicable"]
    rationale: str = Field(min_length=1, max_length=1000)


REQUIRED_ANALYSIS_METHODS = frozenset(
    {"comprehensive", "year_over_year", "month_over_month", "attribution"}
)


class AnalysisPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    plan_id: str = Field(alias="planId", min_length=1, max_length=128)
    outline_id: str = Field(alias="outlineId", min_length=1, max_length=128)
    binding_id: str = Field(alias="bindingId", min_length=1, max_length=128)
    methods: tuple[AnalysisMethodDecision, ...] = Field(min_length=4, max_length=30)

    @model_validator(mode="after")
    def _required_methods_are_decided(self) -> AnalysisPlan:
        names = [item.method for item in self.methods]
        missing = REQUIRED_ANALYSIS_METHODS - set(names)
        if missing:
            raise ValueError(f"缺少必须评估的分析方法: {', '.join(sorted(missing))}")
        if len(names) != len(set(names)):
            raise ValueError("分析方法不能重复")
        return self


class DataRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    requirement_id: str = Field(alias="requirementId", min_length=1, max_length=128)
    binding_id: str = Field(alias="bindingId", min_length=1, max_length=128)
    metric: str = Field(min_length=1, max_length=300)
    dimensions: tuple[str, ...] = Field(default=(), max_length=30)
    grain: str = Field(min_length=1, max_length=200)
    period: str = Field(min_length=1, max_length=200)
    comparison_period: str | None = Field(default=None, alias="comparisonPeriod", max_length=200)
    purpose: str = Field(min_length=1, max_length=1000)


class QueryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    requirement_id: str = Field(alias="requirementId", min_length=1, max_length=128)
    binding_id: str = Field(alias="bindingId", min_length=1, max_length=128)
    sql: str = Field(min_length=1, max_length=262_144)
    generator: Literal["vanna", "agent"]
    requires_approval: bool = Field(alias="requiresApproval")


class ReportReviewState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    binding_id: str = Field(alias="bindingId", min_length=1, max_length=128)
    outline_status: Literal["draft", "pending", "approved", "rejected", "invalidated"] = "draft"
    publication_status: Literal[
        "draft", "pending", "approved", "rejected", "cancelled", "invalidated"
    ] = "draft"
    feedback: str | None = Field(default=None, max_length=4000)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="updatedAt")


class ReportReviewSnapshot(BaseModel):
    """可放入外层 Agent session 的有限审核预览。"""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    stage: Literal["source", "outline", "query", "publication"]
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=1000)
    preview: dict[str, Any] = Field(default_factory=dict)


class ReportWorkflowControl(BaseModel):
    """外层 Agent 只保存恢复 Workflow 所需的最小控制面状态。"""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    workflow_id: str = Field(alias="workflowId", min_length=1, max_length=128)
    workflow_run_id: str = Field(alias="workflowRunId", min_length=1, max_length=128)
    workflow_session_id: str = Field(alias="workflowSessionId", min_length=1, max_length=128)
    external_run_id: str = Field(alias="externalRunId", min_length=1, max_length=256)
    thread_id: str = Field(alias="threadId", min_length=1, max_length=256)
    user_id: str = Field(alias="userId", min_length=1, max_length=256)
    status: Literal["running", "paused", "completed", "cancelled", "failed"]
    review: ReportReviewSnapshot | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="updatedAt")

    def public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)
