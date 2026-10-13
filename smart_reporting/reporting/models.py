from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from agno.exceptions import ModelProviderError, redact_secrets
from pydantic import BaseModel, ConfigDict, Field


class ReportingError(ValueError):
    def __init__(self, code: str, message: str, *, details: Any | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details


def reporting_failure(error: BaseException) -> dict[str, Any]:
    """保留报表失败阶段及供应商原因，不暴露请求头或完整响应。"""
    failure: dict[str, Any] = {
        "code": error.code if isinstance(error, ReportingError) else "report_workflow_failed",
        "message": redact_secrets(str(error))[:1000],
        "retryable": False,
    }
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        stage = getattr(current, "_reporting_failed_step", None)
        if stage and "stage" not in failure:
            failure["stage"] = stage
        if isinstance(current, ModelProviderError):
            failure.update(
                code="report_model_provider_unavailable",
                statusCode=current.status_code,
                retryable=current.status_code in {408, 429, 500, 502, 503, 504, 529},
                message=str(current)[:1000],
            )
        # Agno 的 OpenAI adapter 忽略兼容网关返回的顶层 detail，原异常 body
        # 仍在 cause 链上；只提取文字原因，绝不序列化请求或鉴权对象。
        body = getattr(current, "body", None)
        if failure["message"] == "Unknown model error" and isinstance(body, dict):
            detail = body.get("detail")
            if isinstance(detail, str) and detail.strip():
                failure["message"] = redact_secrets(detail)[:1000]
        current = current.__cause__ or current.__context__
    return failure


class ReportReviewSnapshot(BaseModel):
    """可放入外层 Agent session 的有限审核预览。"""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    stage: Literal["request", "outline", "recovery"]
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
    error: dict[str, Any] | None = None
    # 终态清理失败时保留该事实；下一次恢复只重试清理，不得重复执行 Workflow。
    finalization_pending: bool | None = Field(default=None, alias="finalizationPending")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="updatedAt")

    def public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)
