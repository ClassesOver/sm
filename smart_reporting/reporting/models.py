from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ReportingError(ValueError):
    def __init__(self, code: str, message: str, *, details: Any | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details


class ReportReviewSnapshot(BaseModel):
    """可放入外层 Agent session 的有限审核预览。"""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    stage: Literal["request", "outline"]
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
    # 终态清理失败时保留该事实；下一次恢复只重试清理，不得重复执行 Workflow。
    finalization_pending: bool | None = Field(default=None, alias="finalizationPending")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="updatedAt")

    def public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class VisualizationSkillCacheEntry(BaseModel):
    """可视化阶段只读 Skill 缓存条目，绑定到单次 run 的身份和工具。"""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    run_id: str = Field(alias="runId", min_length=1, max_length=256)
    session_id: str = Field(alias="sessionId", min_length=1, max_length=256)
    user_id: str = Field(alias="userId", min_length=1, max_length=256)
    external_run_id: str = Field(alias="externalRunId", min_length=1, max_length=256)
    tool_name: Literal["get_skill_instructions", "get_skill_reference"] = Field(alias="toolName")
    result: Any
