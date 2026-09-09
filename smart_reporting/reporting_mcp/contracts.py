from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from ..reporting.contract import ReportPeriod, SchemaInput
from ..reporting.hospital_operation.domains import DomainCode
from ..reporting.models import ReportReviewSnapshot


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


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
    download_url: HttpUrl = Field(alias="downloadUrl")
    expires_at: datetime = Field(alias="expiresAt")
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReportingHtmlPreview(StrictModel):
    preview_url: HttpUrl = Field(alias="previewUrl")
    expires_at: datetime = Field(alias="expiresAt")


class ReportingPublishedReport(StrictModel):
    report_id: str = Field(alias="reportId", min_length=1, max_length=128)
    revision: int = Field(ge=0)
    pdf: ReportingArtifactLink
    word: ReportingArtifactLink
    html: ReportingHtmlPreview


class ReportingOperationResult(StrictModel):
    ok: bool
    operation_id: str = Field(alias="operationId", min_length=1, max_length=256)
    status: Literal["running", "paused", "completed", "cancelled", "failed"]
    review: ReportReviewSnapshot | None = None
    report: ReportingPublishedReport | None = None
