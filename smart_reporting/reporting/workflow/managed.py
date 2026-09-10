"""在 Agno 官方 Workflow 执行边界上附加 Reporting 资源生命周期。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Mapping
from copy import copy, deepcopy
from inspect import isawaitable
from typing import Any, Protocol, cast
from uuid import uuid4

import anyio
from agno.run import RunStatus
from agno.run.workflow import (
    WorkflowCancelledEvent,
    WorkflowCompletedEvent,
    WorkflowPausedEvent,
    WorkflowRunOutput,
    WorkflowRunOutputEvent,
)
from agno.workflow import Workflow
from loguru import logger


class ReportingWorkflowLifecycle(Protocol):
    def prepare_run(
        self,
        *,
        run_id: str,
        session_id: str,
        user_id: str | None,
        dependencies: dict[str, Any] | None,
    ) -> dict[str, Any]: ...

    async def start_run(self, run_id: str, session_state: dict[str, Any]) -> None: ...

    async def assert_resumable(self, run_id: str) -> None: ...

    async def settle_run(self, run_id: str, status: str) -> None: ...


def _terminal_status(status: RunStatus | str | None) -> str:
    value = status.value if isinstance(status, RunStatus) else str(status or "").upper()
    if value == RunStatus.completed.value:
        return "completed"
    if value == RunStatus.paused.value:
        return "paused"
    if value == RunStatus.cancelled.value:
        return "cancelled"
    return "failed"


class ManagedReportingWorkflow(Workflow):
    """执行仍由 Agno 负责，只在 Run 前后管理 Reporting 独占资源。"""

    def __init__(self, *, lifecycle: ReportingWorkflowLifecycle, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.lifecycle = lifecycle

    def deep_copy(self, *, update: dict[str, Any] | None = None) -> ManagedReportingWorkflow:
        copied = copy(self)
        copied.steps = self._deep_copy_steps(self.steps)
        agent = self.agent
        copied.agent = cast(
            Any,
            agent.deep_copy() if agent is not None and hasattr(agent, "deep_copy") else agent,
        )
        for name in ("session_state", "metadata", "dependencies", "events_to_skip"):
            setattr(copied, name, deepcopy(getattr(self, name)))
        copied._workflow_session = None
        copied._cached_session_db = None
        for name, value in (update or {}).items():
            setattr(copied, name, value)
        return copied

    def arun(self, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("background"):
            raise ValueError("Reporting Workflow 只允许 background=false")
        run_id = str(kwargs.get("run_id") or uuid4())
        session_id = str(kwargs.get("session_id") or uuid4())
        user_id = kwargs.get("user_id") or self.user_id
        dependencies_value = kwargs.get("dependencies")
        dependencies = (
            dict(dependencies_value) if isinstance(dependencies_value, Mapping) else None
        )
        kwargs["run_id"] = run_id
        kwargs["session_id"] = session_id
        session_state = self.lifecycle.prepare_run(
            run_id=run_id,
            session_id=session_id,
            user_id=str(user_id) if user_id is not None else None,
            dependencies=dependencies,
        )
        kwargs["session_state"] = session_state
        execution = super().arun(*args, **kwargs)
        if hasattr(execution, "__aiter__"):
            return self._stream_initial(
                cast(AsyncIterator[WorkflowRunOutputEvent], execution), run_id, session_state
            )
        if not isawaitable(execution):
            raise TypeError("Agno async Workflow 未返回 awaitable 或 async iterator")
        return self._run_initial(
            cast(Awaitable[WorkflowRunOutput], execution), run_id, session_state
        )

    async def acontinue_run(self, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("background"):
            raise ValueError("Reporting Workflow 只允许 background=false")
        run_response = kwargs.get("run_response")
        run_id = str(
            kwargs.get("run_id")
            or getattr(run_response, "run_id", None)
            or ""
        )
        if not run_id:
            raise ValueError("继续 Reporting Workflow 必须提供 run_id")
        await self.lifecycle.assert_resumable(run_id)
        execution = await super().acontinue_run(*args, **kwargs)
        if hasattr(execution, "__aiter__"):
            return self._stream_continued(
                cast(AsyncIterator[WorkflowRunOutputEvent], execution), run_id
            )
        output = cast(WorkflowRunOutput, execution)
        await self.lifecycle.settle_run(run_id, _terminal_status(output.status))
        return output

    async def _run_initial(
        self,
        execution: Awaitable[WorkflowRunOutput],
        run_id: str,
        session_state: dict[str, Any],
    ) -> WorkflowRunOutput:
        try:
            await self.lifecycle.start_run(run_id, session_state)
        except BaseException:
            close = getattr(execution, "close", None)
            if callable(close):
                close()
            raise
        try:
            output = await execution
        except asyncio.CancelledError:
            await self._settle_cancelled(run_id)
            raise
        except BaseException:
            await self._settle_after_error(run_id)
            raise
        await self.lifecycle.settle_run(run_id, _terminal_status(output.status))
        return output

    async def _stream_initial(
        self,
        execution: AsyncIterator[WorkflowRunOutputEvent],
        run_id: str,
        session_state: dict[str, Any],
    ) -> AsyncIterator[WorkflowRunOutputEvent]:
        try:
            await self.lifecycle.start_run(run_id, session_state)
        except BaseException:
            await execution.aclose()
            raise
        async for event in self._stream(execution, run_id):
            yield event

    async def _stream_continued(
        self, execution: AsyncIterator[WorkflowRunOutputEvent], run_id: str
    ) -> AsyncIterator[WorkflowRunOutputEvent]:
        async for event in self._stream(execution, run_id):
            yield event

    async def _stream(
        self, execution: AsyncIterator[WorkflowRunOutputEvent], run_id: str
    ) -> AsyncIterator[WorkflowRunOutputEvent]:
        status = "failed"
        try:
            async for event in execution:
                if isinstance(event, WorkflowPausedEvent):
                    status = "paused"
                elif isinstance(event, WorkflowCancelledEvent):
                    status = "cancelled"
                elif isinstance(event, WorkflowCompletedEvent) and status != "cancelled":
                    status = "completed"
                yield event
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except BaseException:
            raise
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    await self.lifecycle.settle_run(run_id, status)
                except Exception:
                    if status == "failed":
                        logger.exception(
                            "report_workflow_terminal_cleanup_failed run_id={} status={}",
                            run_id,
                            status,
                        )
                    else:
                        raise

    async def _settle_cancelled(self, run_id: str) -> None:
        with anyio.CancelScope(shield=True):
            await self.lifecycle.settle_run(run_id, "cancelled")

    async def _settle_after_error(self, run_id: str) -> None:
        with anyio.CancelScope(shield=True):
            try:
                await self.lifecycle.settle_run(run_id, "failed")
            except Exception:
                logger.exception(
                    "report_workflow_terminal_cleanup_failed run_id={} status=failed",
                    run_id,
                )


__all__ = ["ManagedReportingWorkflow", "ReportingWorkflowLifecycle"]
