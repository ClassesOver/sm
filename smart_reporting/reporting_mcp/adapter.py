from __future__ import annotations

import hashlib
import json
from typing import Any

from ..reporting.contract import ReportRequestEnvelope
from ..reporting.workflow.controller import (
    ReportWorkflowController,
    reporting_external_operation_id,
)
from .contracts import ReportingReviewInput, ReportingStartInput
from .identity import McpRequestIdentity
from .url_materializer import UrlMaterializer


class ReportingMcpAdapter:
    def __init__(
        self,
        controller: ReportWorkflowController,
        workspace: Any,
    ) -> None:
        self.controller = controller
        self.materializer = UrlMaterializer(workspace)

    async def start(
        self, request: ReportingStartInput, *, identity: McpRequestIdentity
    ) -> dict[str, Any]:
        identity.require_thread(request.thread_id)
        operation_id = reporting_external_operation_id(
            database=identity.database,
            company_id=identity.company_id,
            user_id=identity.user_id,
            thread_id=request.thread_id,
            client_request_id=request.client_request_id,
        )
        request_payload = request.model_dump(mode="json", by_alias=True, exclude_none=True)
        fingerprint = hashlib.sha256(
            json.dumps(
                request_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        payload = ReportRequestEnvelope.from_untrusted(
            request.report_request.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
        materialization_completed = False
        cleanup_attempted = False

        async def prepare() -> ReportRequestEnvelope:
            nonlocal materialization_completed
            files = await self.materializer.materialize_all(
                thread_id=request.thread_id,
                operation_id=operation_id,
                attachments=request.attachments,
            )
            materialization_completed = bool(files)
            return payload.model_copy(update={"file_inputs": tuple(files)}) if files else payload

        async def cleanup_prepared_inputs() -> None:
            nonlocal cleanup_attempted
            cleanup_attempted = True
            await self.materializer.cleanup_operation(request.thread_id, operation_id)

        try:
            result = await self.controller.start_external_background(
                payload,
                external_run_id=operation_id,
                thread_id=request.thread_id,
                user_id=identity.user_id,
                database=identity.database,
                company_id=identity.company_id,
                request_fingerprint=fingerprint,
                prepare=prepare,
                prepared_input_cleanup=(cleanup_prepared_inputs if request.attachments else None),
            )
        except BaseException:
            # 控制器通常接管 prepare 之后的失败补偿；若异常发生在回调接管前，
            # Adapter 仍负责删除已完成物化的输入，同时避免重复访问已销毁的 workspace。
            if materialization_completed and not cleanup_attempted:
                await cleanup_prepared_inputs()
            raise
        return {**result, "operationId": operation_id}

    async def get(
        self,
        *,
        operation_id: str,
        thread_id: str,
        identity: McpRequestIdentity,
    ) -> dict[str, Any]:
        identity.require_thread(thread_id)
        result = await self.controller.get_external(
            external_run_id=operation_id,
            thread_id=thread_id,
            user_id=identity.user_id,
            database=identity.database,
            company_id=identity.company_id,
        )
        return {**result, "operationId": operation_id}

    async def review(
        self, request: ReportingReviewInput, *, identity: McpRequestIdentity
    ) -> dict[str, Any]:
        identity.require_thread(request.thread_id)
        context = await self.controller.external_context(
            external_run_id=request.operation_id,
            thread_id=request.thread_id,
            user_id=identity.user_id,
            database=identity.database,
            company_id=identity.company_id,
        )
        if request.action == "approve":
            result = await self.controller.approve(context)
        else:
            result = await self.controller.reject(request.feedback, context)
        return {**result, "operationId": request.operation_id}

    async def cancel(
        self,
        *,
        operation_id: str,
        thread_id: str,
        identity: McpRequestIdentity,
    ) -> dict[str, Any]:
        identity.require_thread(thread_id)
        result = await self.controller.cancel_external(
            external_run_id=operation_id,
            thread_id=thread_id,
            user_id=identity.user_id,
            database=identity.database,
            company_id=identity.company_id,
        )
        if result.get("status") == "cancelled":
            await self.materializer.cleanup_operation(thread_id, operation_id)
        return {**result, "operationId": operation_id}
