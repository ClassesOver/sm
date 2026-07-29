from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from agno.run import RunContext
from agno.run.base import RunStatus
from agno.tools import Toolkit
from agno.workflow import OnReject
from pydantic import BaseModel

from .contract import ReportRequestEnvelope
from .entrypoints import current_server_envelope
from .models import (
    ReportingError,
    ReportReviewSnapshot,
    ReportWorkflowControl,
)

REPORT_WORKFLOW_CONTROL_STATE_KEY = "report_workflow_control"
REPORT_WORKFLOW_SCOPE_DEPENDENCY = "AgentOS 报表工作流"
_WORKFLOW_ID = "enterprise-reporting-workflow-v1"
_ACTIVE_STATUSES = frozenset({"running", "paused"})
ReportWorkflowStatus = Literal["running", "paused", "completed", "cancelled", "failed"]
ReviewStage = Literal["agent", "source", "outline", "query", "publication"]


class ReviewableWorkflow(Protocol):
    id: str | None

    async def arun(self, *args: Any, **kwargs: Any) -> Any: ...

    async def aget_run(self, run_id: str, session_id: str | None = None) -> Any: ...

    async def acontinue_run(self, *args: Any, **kwargs: Any) -> Any: ...

    async def acancel_run(self, run_id: str) -> bool: ...


WorkflowFactory = Callable[[], ReviewableWorkflow]
CancelCleanup = Callable[[dict[str, str], str, str], Awaitable[None]]
DeliveryValidator = Callable[[dict[str, str], str, str], Awaitable[dict[str, Any] | None]]
PublicationIssuer = Callable[[dict[str, str], str, str, Any], Awaitable[dict[str, Any]]]


class ReportWorkflowController:
    """在 Agent 工具边界内启动和恢复 Agno Workflow。"""

    def __init__(
        self,
        workflow_factory: WorkflowFactory,
        *,
        cancel_cleanup: CancelCleanup | None = None,
        delivery_validator: DeliveryValidator | None = None,
        publication_issuer: PublicationIssuer | None = None,
    ):
        self._workflow_factory = workflow_factory
        self._cancel_cleanup = cancel_cleanup
        self._delivery_validator = delivery_validator
        self._publication_issuer = publication_issuer
        self._active_external: set[tuple[str, str, str]] = set()

    async def start(
        self,
        envelope: ReportRequestEnvelope | dict[str, Any],
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        request = (
            envelope
            if isinstance(envelope, ReportRequestEnvelope)
            else ReportRequestEnvelope.from_untrusted(envelope)
        )
        scope = self._scope(run_context)
        state = self._state(run_context)
        assert run_context is not None
        existing = self._control(state, required=False)
        if existing is not None and existing.status in _ACTIVE_STATUSES:
            self._assert_scope(existing, scope)
            raise ReportingError("report_workflow_active", "当前运行已有未完成的报表工作流。")

        workflow = self._workflow()
        workflow_session_id, workflow_run_id = self._workflow_ids(scope)
        payload = request.model_dump(mode="json", by_alias=True, exclude_none=True)
        scope_key = self._external_scope_key(scope)
        self._active_external.add(scope_key)
        try:
            output = await workflow.arun(
                payload,
                run_id=workflow_run_id,
                session_id=workflow_session_id,
                user_id=scope["user_id"],
                dependencies={
                    REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
                        "externalRunId": scope["external_run_id"],
                        "threadId": scope["thread_id"],
                        "userId": scope["user_id"],
                    }
                },
                stream=False,
            )
            control = self._control_from_output(output, scope, workflow_session_id, workflow_run_id)
        except BaseException:
            self._active_external.discard(scope_key)
            raise
        if control.status not in _ACTIVE_STATUSES:
            self._active_external.discard(scope_key)
        state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = control.public_dict()
        return self._result(control, output)

    async def approve(self, run_context: RunContext | None) -> dict[str, Any]:
        return await self._continue(run_context, approve=True)

    async def reject(self, feedback: str, run_context: RunContext | None) -> dict[str, Any]:
        normalized = str(feedback or "").strip()
        if not normalized or len(normalized) > 4000:
            raise ReportingError(
                "review_feedback_invalid", "拒绝时必须提供 1 至 4000 个字符的意见。"
            )
        state = self._state(run_context)
        control = self._control(state)
        if control is not None and control.review is not None:
            if control.review.stage == "agent":
                raise ReportingError(
                    "report_agent_selection_required", "当前审核项必须明确选择报表 Agent。"
                )
            if control.review.stage == "source":
                return await self.cancel(run_context)
        return await self._continue(run_context, approve=False, feedback=normalized)

    async def select_agent(self, agent_id: str, run_context: RunContext | None) -> dict[str, Any]:
        normalized = str(agent_id or "").strip()
        if not normalized or len(normalized) > 128:
            raise ReportingError("report_agent_invalid", "所选报表 Agent 无效。")
        scope = self._scope(run_context)
        state = self._state(run_context)
        control = self._control(state)
        assert control is not None
        self._assert_scope(control, scope)
        if control.review is None or control.review.stage != "agent":
            raise ReportingError("report_agent_selection_not_pending", "当前不等待选择报表 Agent。")
        agents = control.review.preview.get("agents")
        allowed = (
            {
                item.get("code")
                for item in agents
                if isinstance(item, dict) and isinstance(item.get("code"), str)
            }
            if isinstance(agents, list)
            else set()
        )
        if normalized not in allowed:
            raise ReportingError("report_agent_invalid", "所选报表 Agent 不存在或未启用。")
        output = await self._load(control)
        requirement = self._active_requirement(output)
        requirement.reject(feedback=f"agentId:{normalized}")
        output = await self._workflow().acontinue_run(
            run_response=output,
            step_requirements=list(getattr(output, "step_requirements", None) or []),
            stream=False,
        )
        updated = self._control_from_output(
            output,
            scope,
            control.workflow_session_id,
            control.workflow_run_id,
        )
        state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = updated.public_dict()
        return self._result(updated, output)

    async def cancel(self, run_context: RunContext | None) -> dict[str, Any]:
        scope = self._scope(run_context)
        state = self._state(run_context)
        control = self._control(state)
        assert control is not None
        self._assert_scope(control, scope)
        output = await self._load(control)
        status = self._status(getattr(output, "status", None))
        workflow = self._workflow()
        if status == "paused":
            requirement = self._active_requirement(output)
            requirement.on_reject = OnReject.cancel
            requirement.reject(feedback="用户取消报表工作流。")
            output = await workflow.acontinue_run(
                run_response=output,
                step_requirements=list(getattr(output, "step_requirements", None) or []),
                stream=False,
            )
        elif status == "running":
            await workflow.acancel_run(control.workflow_run_id)
            output = await workflow.aget_run(
                control.workflow_run_id, session_id=control.workflow_session_id
            )
        updated = self._control_from_output(
            output,
            scope,
            control.workflow_session_id,
            control.workflow_run_id,
        )
        if updated.status in _ACTIVE_STATUSES:
            raise ReportingError("report_workflow_cancel_failed", "报表工作流未进入取消终态。")
        await self._cleanup_cancelled(updated, scope)
        self._active_external.discard(self._external_scope_key(scope))
        state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = updated.public_dict()
        return self._result(updated, output)

    async def cancel_external(
        self,
        *,
        external_run_id: str,
        thread_id: str,
        user_id: str,
        probe_storage: bool = False,
    ) -> dict[str, Any] | None:
        scope = {
            "external_run_id": external_run_id,
            "thread_id": thread_id,
            "user_id": user_id,
        }
        scope_key = self._external_scope_key(scope)
        if scope_key not in self._active_external and not probe_storage:
            return None
        workflow_session_id, workflow_run_id = self._workflow_ids(scope)
        workflow = self._workflow()
        output = await workflow.aget_run(workflow_run_id, session_id=workflow_session_id)
        if output is None:
            self._active_external.discard(scope_key)
            return None
        stored_user = getattr(output, "user_id", None)
        if stored_user is not None and str(stored_user) != user_id:
            return None
        status = self._status(getattr(output, "status", None))
        if status == "paused":
            requirement = self._active_requirement(output)
            requirement.on_reject = OnReject.cancel
            requirement.reject(feedback="用户取消报表工作流。")
            output = await workflow.acontinue_run(
                run_response=output,
                step_requirements=list(getattr(output, "step_requirements", None) or []),
                stream=False,
            )
        elif status == "running":
            await workflow.acancel_run(workflow_run_id)
            output = await workflow.aget_run(workflow_run_id, session_id=workflow_session_id)
        status = self._status(getattr(output, "status", None))
        if status in _ACTIVE_STATUSES:
            raise ReportingError("report_workflow_cancel_failed", "报表工作流未进入取消终态。")
        self._active_external.discard(scope_key)
        if status == "cancelled" and self._cancel_cleanup is not None:
            await self._cancel_cleanup(scope, workflow_session_id, workflow_run_id)
        return {"ok": True, "status": status}

    async def validated_external_delivery(
        self, *, external_run_id: str, thread_id: str, user_id: str
    ) -> dict[str, Any] | None:
        if self._delivery_validator is None:
            return None
        scope = {
            "external_run_id": external_run_id,
            "thread_id": thread_id,
            "user_id": user_id,
        }
        workflow_session_id, workflow_run_id = self._workflow_ids(scope)
        output = await self._workflow().aget_run(workflow_run_id, session_id=workflow_session_id)
        if output is None or self._status(getattr(output, "status", None)) != "completed":
            return None
        stored_user = getattr(output, "user_id", None)
        if stored_user is not None and str(stored_user) != user_id:
            return None
        return await self._delivery_validator(scope, workflow_session_id, workflow_run_id)

    async def _continue(
        self,
        run_context: RunContext | None,
        *,
        approve: bool,
        feedback: str | None = None,
    ) -> dict[str, Any]:
        scope = self._scope(run_context)
        state = self._state(run_context)
        control = self._control(state)
        assert control is not None
        self._assert_scope(control, scope)
        output = await self._load(control)
        if self._status(getattr(output, "status", None)) != "paused":
            raise ReportingError("report_workflow_not_paused", "报表工作流当前不等待审核。")
        requirement = self._active_requirement(output)
        review_stage = control.review.stage if control.review is not None else None
        if approve:
            requirement.confirm()
        else:
            requirement.reject(feedback=feedback)
        workflow = self._workflow()
        output = await workflow.acontinue_run(
            run_response=output,
            step_requirements=list(getattr(output, "step_requirements", None) or []),
            stream=False,
        )
        updated = self._control_from_output(
            output,
            scope,
            control.workflow_session_id,
            control.workflow_run_id,
        )
        if review_stage == "publication" and updated.status == "completed":
            if self._publication_issuer is None:
                raise ReportingError("report_publication_unavailable", "报表发布服务未配置。")
            output.content = await self._publication_issuer(
                scope,
                control.workflow_session_id,
                control.workflow_run_id,
                output,
            )
        await self._cleanup_cancelled(updated, scope)
        if updated.status not in _ACTIVE_STATUSES:
            self._active_external.discard(self._external_scope_key(scope))
        state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = updated.public_dict()
        return self._result(updated, output)

    async def _load(self, control: ReportWorkflowControl) -> Any:
        output = await self._workflow().aget_run(
            control.workflow_run_id, session_id=control.workflow_session_id
        )
        if output is None:
            raise ReportingError("report_workflow_not_found", "报表工作流不存在或已经失效。")
        stored_user = getattr(output, "user_id", None)
        if stored_user is not None and str(stored_user) != control.user_id:
            raise ReportingError("report_workflow_scope_mismatch", "报表工作流不属于当前用户。")
        return output

    async def _cleanup_cancelled(
        self, control: ReportWorkflowControl, scope: dict[str, str]
    ) -> None:
        if control.status == "cancelled" and self._cancel_cleanup is not None:
            await self._cancel_cleanup(scope, control.workflow_session_id, control.workflow_run_id)

    def _workflow(self) -> ReviewableWorkflow:
        workflow = self._workflow_factory()
        if workflow is None or str(getattr(workflow, "id", "") or "") != _WORKFLOW_ID:
            raise ReportingError("report_workflow_unavailable", "报表工作流配置不可用。")
        return workflow

    @staticmethod
    def _source_ids(value: list[str] | None) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or not 1 <= len(value) <= 20:
            raise ReportingError("report_source_ids_invalid", "source_ids 必须包含 1 至 20 项。")
        normalized = [str(item).strip() for item in value]
        if any(not item or len(item) > 256 for item in normalized) or len(set(normalized)) != len(
            normalized
        ):
            raise ReportingError(
                "report_source_ids_invalid", "source_ids 包含空值、重复项或超长值。"
            )
        return normalized

    @staticmethod
    def _state(run_context: RunContext | None) -> dict[str, Any]:
        if run_context is None:
            raise ReportingError("report_workflow_context_missing", "报表工作流缺少运行上下文。")
        if run_context.session_state is None:
            run_context.session_state = {}
        if not isinstance(run_context.session_state, dict):
            raise ReportingError("report_workflow_state_invalid", "报表工作流状态无效。")
        return run_context.session_state

    @staticmethod
    def _scope(run_context: RunContext | None) -> dict[str, str]:
        if run_context is None:
            raise ReportingError("report_workflow_context_missing", "报表工作流缺少运行上下文。")
        dependency = (run_context.dependencies or {}).get(REPORT_WORKFLOW_SCOPE_DEPENDENCY)
        external_run_id = (
            dependency.get("externalRunId") if isinstance(dependency, dict) else run_context.run_id
        )
        values = {
            "external_run_id": str(external_run_id or ""),
            "thread_id": str(run_context.session_id or ""),
            "user_id": str(run_context.user_id or ""),
        }
        if any(not value or len(value) > 256 for value in values.values()):
            raise ReportingError("report_workflow_context_missing", "报表工作流作用域不完整。")
        return values

    @staticmethod
    def _workflow_ids(scope: dict[str, str]) -> tuple[str, str]:
        session_digest = hashlib.sha256(
            f"{scope['user_id']}:{scope['thread_id']}".encode()
        ).hexdigest()[:32]
        run_digest = hashlib.sha256(
            f"{scope['user_id']}:{scope['thread_id']}:{scope['external_run_id']}".encode()
        ).hexdigest()[:32]
        return f"report-session-{session_digest}", f"report-run-{run_digest}"

    @staticmethod
    def _external_scope_key(scope: dict[str, str]) -> tuple[str, str, str]:
        return scope["external_run_id"], scope["thread_id"], scope["user_id"]

    @staticmethod
    def _control(state: dict[str, Any], *, required: bool = True) -> ReportWorkflowControl | None:
        raw = state.get(REPORT_WORKFLOW_CONTROL_STATE_KEY)
        if raw is None and not required:
            return None
        try:
            return ReportWorkflowControl.model_validate(raw)
        except Exception as error:
            raise ReportingError(
                "report_workflow_control_invalid", "报表工作流控制状态无效。"
            ) from error

    @staticmethod
    def _assert_scope(control: ReportWorkflowControl, scope: dict[str, str]) -> None:
        if (
            control.external_run_id,
            control.thread_id,
            control.user_id,
        ) != (
            scope["external_run_id"],
            scope["thread_id"],
            scope["user_id"],
        ):
            raise ReportingError("report_workflow_scope_mismatch", "报表工作流不属于当前运行。")

    def _control_from_output(
        self,
        output: Any,
        scope: dict[str, str],
        workflow_session_id: str,
        workflow_run_id: str,
    ) -> ReportWorkflowControl:
        status = self._status(getattr(output, "status", None))
        review = self._review(output) if status == "paused" else None
        return ReportWorkflowControl(
            workflowId=_WORKFLOW_ID,
            workflowRunId=workflow_run_id,
            workflowSessionId=workflow_session_id,
            externalRunId=scope["external_run_id"],
            threadId=scope["thread_id"],
            userId=scope["user_id"],
            status=status,
            review=review,
            updatedAt=datetime.now(UTC),
        )

    @staticmethod
    def _status(value: Any) -> ReportWorkflowStatus:
        normalized = value.value if isinstance(value, RunStatus) else str(value or "").upper()
        statuses: dict[str, ReportWorkflowStatus] = {
            "PENDING": "running",
            "RUNNING": "running",
            "PAUSED": "paused",
            "COMPLETED": "completed",
            "CANCELLED": "cancelled",
            "ERROR": "failed",
            "FAILED": "failed",
        }
        return statuses.get(normalized, "failed")

    @staticmethod
    def _active_requirement(output: Any) -> Any:
        active = list(getattr(output, "active_step_requirements", None) or [])
        if not active:
            requirements = list(getattr(output, "step_requirements", None) or [])
            active = [
                item for item in requirements if not bool(getattr(item, "is_resolved", False))
            ]
        if len(active) != 1:
            raise ReportingError("report_workflow_review_invalid", "报表工作流审核状态无效。")
        return active[0]

    def _review(self, output: Any) -> ReportReviewSnapshot:
        requirement = self._active_requirement(output)
        name = str(getattr(requirement, "step_name", "") or "")
        stage: ReviewStage
        content = getattr(getattr(requirement, "step_output", None), "content", None)
        if isinstance(content, BaseModel):
            content = content.model_dump(mode="json", by_alias=True)
        if "来源" in name and isinstance(content, dict) and isinstance(content.get("agents"), list):
            stage = "agent"
            title = "选择报表 Agent"
            allowed = {"agents"}
        elif "来源" in name:
            stage = "source"
            title = "确认数据来源"
            allowed = {"sources"}
        elif "提纲" in name:
            stage = "outline"
            title = "审核报告提纲"
            allowed = {"title", "sections", "assumptions"}
        elif "取数" in name or "查询" in name:
            stage = "query"
            title = "审核取数方案"
            allowed = {"queries"}
        elif "发布" in name:
            stage = "publication"
            title = "审核最终报告"
            allowed = {"status", "jobId", "revision", "validation"}
        else:
            raise ReportingError("report_workflow_review_invalid", "报表工作流出现未知审核阶段。")
        preview = (
            {key: content[key] for key in allowed if key in content}
            if isinstance(content, dict)
            else {}
        )
        message = str(
            getattr(requirement, "confirmation_message", None)
            or getattr(requirement, "output_review_message", None)
            or title
        )[:1000]
        return ReportReviewSnapshot(stage=stage, title=title, message=message, preview=preview)

    @staticmethod
    def _result(control: ReportWorkflowControl, output: Any) -> dict[str, Any]:
        result: dict[str, Any] = {"ok": control.status != "failed", "status": control.status}
        if control.review is not None:
            result["review"] = control.review.model_dump(mode="json", by_alias=True)
        if control.status == "completed":
            content = getattr(output, "content", None)
            if isinstance(content, BaseModel):
                content = content.model_dump(mode="json", by_alias=True)
            if isinstance(content, dict):
                allowed = {"reportId", "revision", "pdf", "path", "size", "sha256"}
                report = {key: content[key] for key in allowed if key in content}
                if report:
                    result["report"] = report
        return result


class ReportWorkflowToolkit(Toolkit):
    def __init__(self, controller: ReportWorkflowController):
        self.controller = controller
        super().__init__(
            name="report_workflow",
            tools=[
                self.report_workflow_start,
                self.report_workflow_select_agent,
                self.report_workflow_approve,
                self.report_workflow_reject,
                self.report_workflow_cancel,
            ],
            instructions=(
                "新报表只调用 report_workflow_start。需要选择 Agent 时调用 "
                "report_workflow_select_agent；其他 paused 审核批准调用 "
                "report_workflow_approve，拒绝调用 report_workflow_reject；用户明确取消时调用 "
                "report_workflow_cancel。不得绕过 Workflow 审核或自行执行取数和 Coding 分析。"
            ),
            add_instructions=True,
            requires_confirmation_tools=["report_workflow_approve"],
        )

    async def report_workflow_start(
        self,
        envelope: dict[str, Any] | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """使用严格 ReportRequestEnvelope v1 启动企业智能运营报表 Workflow。"""
        if envelope is None:
            bound = current_server_envelope()
            envelope = (
                bound.model_dump(mode="json", by_alias=True, exclude_none=True)
                if bound is not None
                else None
            )
        if not isinstance(envelope, dict):
            raise ReportingError("report_request_invalid", "当前消息缺少报表 Envelope。")
        return await self.controller.start(envelope, run_context)

    async def report_workflow_approve(
        self, run_context: RunContext | None = None
    ) -> dict[str, Any]:
        """批准当前报表 Workflow 审核项并继续执行。"""
        return await self.controller.approve(run_context)

    async def report_workflow_select_agent(
        self,
        agent_id: str,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """选择当前 Workflow 暂停项列出的报表 Agent。"""
        return await self.controller.select_agent(agent_id, run_context)

    async def report_workflow_reject(
        self,
        feedback: str,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """拒绝当前审核项并提供修改意见。"""
        return await self.controller.reject(feedback, run_context)

    async def report_workflow_cancel(self, run_context: RunContext | None = None) -> dict[str, Any]:
        """取消当前报表 Workflow，并推进到持久化终态。"""
        return await self.controller.cancel(run_context)
