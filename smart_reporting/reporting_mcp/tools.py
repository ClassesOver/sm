from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from .adapter import ReportingMcpAdapter
from .contracts import (
    ReportingOperationResult,
    ReportingReportRequest,
    ReportingReviewInput,
    ReportingStartInput,
    ReportingUrlAttachment,
)
from .identity import require_mcp_identity


def create_reporting_mcp_tools(adapter: ReportingMcpAdapter) -> list[Any]:
    async def reporting_start(
        clientRequestId: Annotated[str, Field(min_length=1, max_length=256)],
        threadId: Annotated[str, Field(min_length=1, max_length=256)],
        reportRequest: ReportingReportRequest,
        attachments: Annotated[list[ReportingUrlAttachment] | None, Field(max_length=4)] = None,
    ) -> ReportingOperationResult:
        """启动 Reporting 报表工作流，可选附件通过 HTTPS URL 提供。"""
        request = ReportingStartInput.model_validate(
            {
                "clientRequestId": clientRequestId,
                "threadId": threadId,
                "reportRequest": reportRequest,
                "attachments": attachments or [],
            }
        )
        result = await adapter.start(request, identity=require_mcp_identity(threadId))
        return ReportingOperationResult.model_validate(result)

    async def reporting_get(
        operationId: Annotated[str, Field(min_length=1, max_length=256)],
        threadId: Annotated[str, Field(min_length=1, max_length=256)],
    ) -> ReportingOperationResult:
        """查询 Reporting 工作流的有限状态投影。"""
        result = await adapter.get(
            operation_id=operationId,
            thread_id=threadId,
            identity=require_mcp_identity(threadId),
        )
        return ReportingOperationResult.model_validate(result)

    async def reporting_review(
        operationId: Annotated[str, Field(min_length=1, max_length=256)],
        threadId: Annotated[str, Field(min_length=1, max_length=256)],
        action: Literal["approve", "reject"],
        feedback: Annotated[str, Field(max_length=4000)] = "",
    ) -> ReportingOperationResult:
        """批准或拒绝暂停中的 Reporting 审核项。"""
        request = ReportingReviewInput(
            operationId=operationId,
            threadId=threadId,
            action=action,
            feedback=feedback,
        )
        result = await adapter.review(request, identity=require_mcp_identity(threadId))
        return ReportingOperationResult.model_validate(result)

    async def reporting_cancel(
        operationId: Annotated[str, Field(min_length=1, max_length=256)],
        threadId: Annotated[str, Field(min_length=1, max_length=256)],
    ) -> ReportingOperationResult:
        """取消 Reporting 工作流并执行终态清理。仅暂停等待审核的工作流可取消；运行中的工作流不可取消，请改用 reporting_get 轮询等待终态。"""
        result = await adapter.cancel(
            operation_id=operationId,
            thread_id=threadId,
            identity=require_mcp_identity(threadId),
        )
        return ReportingOperationResult.model_validate(result)

    return [reporting_start, reporting_get, reporting_review, reporting_cancel]
