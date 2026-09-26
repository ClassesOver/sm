from __future__ import annotations

import asyncio
import contextlib
from typing import Any
from uuid import uuid4

from dingyi_agno.process import ProcessJournal, ProcessPublisher, create_process_router
from dingyi_agno.process.core import now
from fastapi import APIRouter, HTTPException
from loguru import logger
from starlette.concurrency import run_in_threadpool

OWNER = "smart-reporting"
COMPONENT = {"type": "agent", "id": "smart-reporting"}
OPERATION_TITLE = "生成报告"
_MAX_TITLE_LENGTH = 80
_MAX_SUMMARY_LENGTH = 500
_OPERATION_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_ACTIVITY_TERMINAL = frozenset({"completed", "failed", "cancelled", "skipped"})
_STEP_TITLES = {
    "normalize-report-request": ("确认报告需求", "已确认报告需求"),
    "confirm-source": ("确认数据来源", "已确认数据来源"),
    "prepare-data-profile": ("准备数据画像", "已完成数据画像"),
    "propose-measure-semantics": ("确认指标语义", "已生成指标语义候选"),
    "commit-measure-semantics": ("提交指标语义", "已提交指标语义"),
    "generate-analysis-plan": ("制定分析计划", "已生成分析计划"),
    "generate-query-candidates": ("审核取数方案", "已确认取数方案"),
    "materialize-datasets": ("准备分析数据", "已完成数据集物化"),
    "prepare-analysis-context": ("准备分析上下文", "分析上下文已就绪"),
    "generate-detailed-analysis-plan": ("细化分析计划", "已细化分析计划"),
    "generate-outline": ("生成报告提纲", "报告提纲已生成"),
    "run-coding-analysis": ("分析并编写报告", "已完成报告分析与编写"),
    "assemble-report": ("汇编报告", "报告汇编完成"),
    "validate-report": ("检查报告结果", "报告格式验收通过"),
    "finalize-publication": ("发布报告", "报告已发布"),
}


def _bounded(value: str | None, maximum: int) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split())[:maximum] or None


@contextlib.asynccontextmanager
async def _best_effort(action: str, operation_id: str):
    try:
        yield
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.warning(
            "dingyi_process_action_failed action={} operation={} error_type={}",
            action,
            operation_id,
            type(error).__name__,
        )


class DingyiProcessAdapter:
    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self._journal: ProcessJournal | None = None
        self._router: APIRouter | None = None
        self._operation_ids: dict[str, str] = {}

    def _ensure_journal(self) -> ProcessJournal:
        if self._journal is None:
            self._journal = ProcessJournal(engine=self._engine)
        return self._journal

    @property
    def router(self) -> APIRouter:
        if self._router is None:
            self._router = create_process_router(self._ensure_journal(), authorize=self._authorize)
        return self._router

    @staticmethod
    async def _authorize(request: Any, resource: dict[str, Any] | None) -> None:
        """只接受中间件已验签的 Odoo capability，并把访问限定在其 thread 内。

        过程 operation 的 sessionId 即报告 thread；未携带 capability 的请求不能按
        猜测或泄露的会话/operation id 读取报告标题、步骤摘要和事件流。
        """

        capability = getattr(getattr(request, "state", None), "capability", None)
        thread = getattr(capability, "thread", None)
        if not isinstance(thread, str) or not thread:
            raise HTTPException(status_code=401)
        if resource is not None and resource.get("sessionId") not in (None, thread):
            raise HTTPException(status_code=404)
        return None

    async def _snapshot(self, operation_id: str) -> dict[str, Any] | None:
        try:
            return await run_in_threadpool(self._ensure_journal().snapshot, operation_id)
        except Exception:
            return None

    async def start_operation(
        self, *, operation_id: str, session_id: str, run_id: str, title: str, execution: str
    ) -> None:
        async with _best_effort("start_operation", operation_id):
            publisher = ProcessPublisher(
                self._ensure_journal(),
                owner=OWNER,
                session_id=session_id,
                run_id=run_id,
                component=COMPONENT,
                title=_bounded(title, _MAX_TITLE_LENGTH) or OPERATION_TITLE,
                operation_id=operation_id,
                execution=execution,
            )
            await publisher.astart()
            self._operation_ids[operation_id] = operation_id

    async def update_operation(
        self, *, operation_id: str, session_id: str, status: str, summary: str | None = None
    ) -> None:
        async with _best_effort("update_operation", operation_id):
            target = self._operation_ids.get(operation_id, operation_id)
            snapshot = await self._snapshot(target)
            if snapshot is None or str(snapshot["operation"]["status"]) in _OPERATION_TERMINAL:
                return
            if status in _OPERATION_TERMINAL:
                await self._close_activities(snapshot, status)
            publisher = ProcessPublisher(
                self._ensure_journal(),
                owner=OWNER,
                session_id=session_id,
                run_id=str(snapshot["operation"]["runId"]),
                component=COMPONENT,
                title=str(snapshot["operation"]["title"]),
                operation_id=target,
                execution=str(snapshot["operation"]["execution"]),
            )
            await publisher.aupdate(status=status, summary=_bounded(summary, _MAX_SUMMARY_LENGTH))
            if status in _OPERATION_TERMINAL:
                self._operation_ids.pop(operation_id, None)

    async def _close_activities(self, snapshot: dict[str, Any], terminal_status: str) -> None:
        operation = snapshot["operation"]
        activity_status = "completed" if terminal_status == "completed" else "failed"
        for activity in snapshot.get("activities", []):
            if str(activity.get("status")) in _ACTIVITY_TERMINAL:
                continue
            publisher = ProcessPublisher(
                self._ensure_journal(),
                owner=OWNER,
                session_id=str(operation["sessionId"]),
                run_id=str(operation["runId"]),
                component=COMPONENT,
                title=str(operation["title"]),
                operation_id=str(operation["operationId"]),
                execution=str(operation["execution"]),
            )
            await publisher.aactivity(
                id=str(activity["id"]),
                title=str(activity.get("title") or "步骤"),
                kind=str(activity.get("kind") or "step"),
                status=activity_status,
                endedAt=now(),
                summary="已随任务完成" if activity_status == "completed" else "步骤执行失败",
            )

    async def start_activity(
        self, *, operation_id: str, session_id: str, run_id: str, step_id: str
    ) -> str | None:
        async with _best_effort("start_activity", operation_id):
            if await self._snapshot(self._operation_ids.get(operation_id, operation_id)) is None:
                return None
            title, _ = _STEP_TITLES.get(step_id, (step_id, "步骤执行完成"))
            operation = (await self._snapshot(self._operation_ids.get(operation_id, operation_id)))[
                "operation"
            ]
            publisher = ProcessPublisher(
                self._ensure_journal(),
                owner=OWNER,
                session_id=session_id,
                run_id=run_id,
                component=COMPONENT,
                title=str(operation["title"]),
                operation_id=str(operation["operationId"]),
                execution=str(operation["execution"]),
            )
            activity_id = str(uuid4())
            await publisher.aactivity(
                id=activity_id,
                title=title,
                status="running",
                startedAt=now(),
                source={"runId": run_id, "stepId": step_id},
            )
            return activity_id

    async def finish_activity(
        self,
        *,
        operation_id: str,
        session_id: str,
        activity_id: str,
        step_id: str,
        status: str,
        summary: str | None = None,
    ) -> None:
        async with _best_effort("finish_activity", operation_id):
            operation = await self._snapshot(self._operation_ids.get(operation_id, operation_id))
            if operation is None:
                return
            data = operation["operation"]
            title, default = _STEP_TITLES.get(step_id, (step_id, "步骤执行完成"))
            publisher = ProcessPublisher(
                self._ensure_journal(),
                owner=OWNER,
                session_id=session_id,
                run_id=str(data["runId"]),
                component=COMPONENT,
                title=str(data["title"]),
                operation_id=str(data["operationId"]),
                execution=str(data["execution"]),
            )
            await publisher.aactivity(
                id=activity_id,
                title=title,
                status=status,
                endedAt=now(),
                summary=_bounded(
                    summary or (default if status == "completed" else None), _MAX_SUMMARY_LENGTH
                ),
            )
