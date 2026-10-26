from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from ..reporting.contract import ReportPeriod, SchemaInput
from ..reporting.hospital_operation.domains import DomainCode
from ..reporting.models import ReportReviewSnapshot


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, populate_by_name=True, serialize_by_alias=True
    )


class ReportingUrlAttachment(StrictModel):
    url: HttpUrl
    filename: str | None = Field(default=None, min_length=1, max_length=255)
    sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$"
    )


class ReportingReportRequest(StrictModel):
    """MCP 可提交的报表请求；fileInputs 只能由服务端 URL 物化后注入。"""

    version: Literal["1"] = "1"
    report_goal: str = Field(alias="reportGoal", min_length=1, max_length=20_000)
    report_type: Literal["comprehensive", "topic"] | None = Field(default=None, alias="reportType")
    domains: tuple[DomainCode, ...] | None = Field(default=None, max_length=6)
    period: ReportPeriod
    source_ids: tuple[str, ...] | None = Field(default=None, alias="sourceIds", max_length=20)
    schema_input: SchemaInput | None = Field(default=None, alias="schemaInput")
    comparison_roles: tuple[Literal["yoy", "mom"], ...] = Field(
        default=("yoy",), alias="comparisonRoles", max_length=2
    )


class ReportingStartInput(StrictModel):
    client_request_id: str = Field(alias="clientRequestId", min_length=1, max_length=256)
    thread_id: str = Field(alias="threadId", min_length=1, max_length=256)
    report_request: ReportingReportRequest = Field(alias="reportRequest")
    attachments: tuple[ReportingUrlAttachment, ...] = Field(default=(), max_length=4)


class ReportingGetInput(StrictModel):
    operation_id: str = Field(alias="operationId", min_length=1, max_length=256)
    thread_id: str = Field(alias="threadId", min_length=1, max_length=256)


class ReportingReviewInput(ReportingGetInput):
    action: Literal["approve", "reject"]
    feedback: str = Field(default="", max_length=4000)


class ReportingArtifactLink(StrictModel):
    path: str | None = None
    download_url: HttpUrl = Field(alias="downloadUrl")
    expires_at: datetime = Field(alias="expiresAt")
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReportingEditorLink(StrictModel):
    open_url: HttpUrl = Field(alias="openUrl")
    expires_at: datetime = Field(alias="expiresAt")


class ReportingPublishedReport(StrictModel):
    report_id: str = Field(alias="reportId", min_length=1, max_length=128)
    report_title: str | None = Field(default=None, alias="reportTitle")
    revision: int = Field(ge=0)
    pdf: ReportingArtifactLink | None = None
    word: ReportingArtifactLink | None = None
    editor: ReportingEditorLink | None = None
    publication_gate: dict[str, Any] | None = Field(default=None, alias="publicationGate")

    @model_validator(mode="after")
    def require_downloadable_artifact(self) -> ReportingPublishedReport:
        if self.pdf is None and self.word is None:
            raise ValueError("已发布报告必须至少包含一个可下载格式。")
        return self


class ReportingOperationError(StrictModel):
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(max_length=1000)
    retryable: bool
    stage: str | None = Field(default=None, max_length=128)
    status_code: int | None = Field(default=None, alias="statusCode")


class ReportingOperationResult(StrictModel):
    ok: bool
    operation_id: str = Field(alias="operationId", min_length=1, max_length=256)
    status: Literal["running", "paused", "completed", "cancelled", "failed"]
    review: ReportReviewSnapshot | None = None
    report: ReportingPublishedReport | None = None
    error: ReportingOperationError | None = None

    @model_validator(mode="after")
    def require_failure_details(self) -> ReportingOperationResult:
        if self.status == "failed" and self.error is None:
            raise ValueError("失败的报表操作必须包含错误详情。")
        if self.status != "failed" and self.error is not None:
            raise ValueError("非失败报表操作不得包含错误详情。")
        return self
