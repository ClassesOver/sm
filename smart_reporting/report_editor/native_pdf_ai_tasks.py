"""PDF 只读 AI 任务：绑定原生会话与来源，不创建编辑候选或保存产物。"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from time import monotonic
from typing import Any
from uuid import uuid4

from loguru import logger

from ..reporting.models import ReportingError
from .agent_event_streams import AgentEventLog, bind_agent_event_log, event_stream_response
from .native_ai import _copy_operations
from .native_models import native_digest
from .native_pdf_ai import NativePDFTaskReader

_READ_INSTRUCTIONS = {
    "ask": "根据实际读取的 PDF 证据回答用户问题，引用工具页码并按投影映射说明原始页号；依据不足时澄清。",
    "summarize": "读取授权范围内全部正文，概括文档主题、结论与重要数据，标明未覆盖的页面。",
    "keyPoints": "读取授权范围全部正文，提炼关键要点、数值、日期及行动项，引用页码，不补造事实。",
    "reviewSummary": "只读总结全部批注和标注，按实际工具页号、投影映射及可读作者/状态归纳审阅意见，不执行意见或删除批注。",
}
_ACTIONS = set(_READ_INSTRUCTIONS)


@dataclass
class _ReadJob:
    task_id: str
    client_request_id: str
    context_sha256: str
    created_at: float
    snapshot_sha256: str | None = None
    status: str = "running"
    task: asyncio.Task | None = None
    result: dict | None = None
    error: dict | None = None
    event_log: AgentEventLog = field(default_factory=AgentEventLog)


class NativePDFReadService:
    def __init__(
        self,
        editor: Any,
        *,
        planner: Any,
        enabled: bool = False,
        timeout_seconds: float = 120,
    ):
        self.editor, self.planner, self.enabled = editor, planner, enabled
        self.timeout_seconds = timeout_seconds
        self._jobs: dict[tuple[str, str], _ReadJob] = {}
        self._closed = False

    async def _context(self, session):
        context = await self.editor.context_for_session(session)
        if not self.enabled:
            raise ReportingError("native_ai_disabled", "原生 AI 尚未开放。")
        if context.format != "pdf":
            raise ReportingError(
                "native_ai_format_unsupported", "此阅读任务仅支持 PDF。"
            )
        return context

    @staticmethod
    def _request_id(value):
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", value) is None
        ):
            raise ReportingError("native_ai_request_invalid", "AI 请求身份无效。")
        return value

    def _prune(self):
        for key, job in tuple(self._jobs.items()):
            if monotonic() - job.created_at > 3600 and (
                not job.task or job.task.done()
            ):
                del self._jobs[key]

    def _reserve(self, *, cancelled=False):
        if self._closed and not cancelled:
            raise ReportingError("native_ai_closed", "AI 任务服务已关闭。")
        self._prune()
        # 提前取消的回执也保留一小时，避免迟到 start 重新调用模型。
        if len(self._jobs) >= 128 or (
            not cancelled
            and sum(j.status == "running" for j in self._jobs.values()) >= 32
        ):
            raise ReportingError("native_ai_busy", "PDF AI 任务繁忙，请稍后重试。")

    async def start(
        self,
        session,
        *,
        client_request_id: str,
        expected_sha256: str,
        operations: list,
        selection: list,
        action: str,
        instruction: str,
    ):
        context = await self._context(session)
        request_id = self._request_id(client_request_id)
        if expected_sha256 != context.source_file.sha256:
            raise ReportingError(
                "native_ai_snapshot_changed", "PDF 来源已变化，请重新打开。"
            )
        if (
            action not in _ACTIONS
            or not isinstance(instruction, str)
            or len(instruction) > 2000
        ):
            raise ReportingError(
                "native_ai_instruction_invalid", "PDF AI 任务要求无效。"
            )
        if action == "ask" and not instruction.strip():
            raise ReportingError("native_ai_instruction_invalid", "请输入 PDF 问题。")
        base = _copy_operations(operations)
        if (
            not isinstance(selection, list)
            or len(selection) > 100
            or any(
                not isinstance(item, dict)
                or set(item) != {"pageId", "objectId"}
                or any(
                    not isinstance(value, str) or not value or len(value) > 256
                    for value in item.values()
                )
                for item in selection
            )
        ):
            raise ReportingError("native_ai_selection_invalid", "PDF 选区身份无效。")
        selected = [dict(item) for item in selection]
        snapshot = native_digest(
            {
                "context": context.digest(),
                "operations": base,
                "selection": selected,
                "action": action,
                "instruction": instruction,
            }
        )
        self._prune()
        key = (context.digest(), request_id)
        previous = self._jobs.get(key)
        if previous:
            if (
                previous.snapshot_sha256 is not None
                and previous.snapshot_sha256 != snapshot
            ):
                raise ReportingError(
                    "native_ai_snapshot_changed",
                    "相同 AI 请求的内容已变化，请重新发起请求。",
                )
            return self._serialize(previous)
        self._reserve()
        job = _ReadJob(uuid4().hex, request_id, context.digest(), monotonic(), snapshot)
        self._jobs[key] = job
        job.task = asyncio.create_task(
            self._run(job, session, context, base, selected, action, instruction)
        )
        return self._serialize(job)

    async def _run(self, job, session, context, base, selected, action, instruction):
        try:
            await job.event_log.emit("phase", label="正在读取 PDF")
            async with asyncio.timeout(self.timeout_seconds):
                # 读取真实授权来源；读取型问答不依赖原位改字/编辑配置。
                content = await self.editor.read_file(context)
                projection = None
                if base:
                    if any(op["kind"] in {"mergePages", "splitPages"} for op in base):
                        self.editor.require_enabled(context.format)
                        raise ReportingError(
                            "native_pdf_ai_draft_mapping_unsupported",
                            "合并或拆分页面草稿尚不能可靠映射，请先保存重开。",
                        )
                    receipt = await self.editor.preview_file(
                        context,
                        expected_sha256=context.source_file.sha256,
                        operations=base,
                    )
                    if job.status != "running":
                        return
                    projection = await NativePDFTaskReader.from_bytes(
                        context, content, operations=base, draft_receipt=receipt
                    )
                if job.status != "running":
                    return
                await job.event_log.emit("phase", label="正在整理回答")
                async with bind_agent_event_log(job.event_log):
                    result = await self.planner(
                        context=context,
                        content=content,
                        operations=base,
                        action=action,
                        instruction=_READ_INSTRUCTIONS[action]
                        + "\n用户要求："
                        + instruction,
                        selection=selected,
                        session_id=f"native-pdf-read:{job.task_id}",
                        user_id=context.scope.user_id,
                        **(
                            {"draft_projection": projection}
                            if projection is not None
                            else {}
                        ),
                    )
                current = await self.editor.context_for_session(session)
                if current.digest() != job.context_sha256:
                    raise ReportingError(
                        "native_ai_snapshot_changed", "PDF 会话来源已变化。"
                    )
                if (
                    not isinstance(result, dict)
                    or not isinstance(result.get("answer"), str)
                    or not result["answer"].strip()
                ):
                    raise ReportingError(
                        "native_ai_output_empty", "AI 未返回有效回答。"
                    )
                if "operations" in result or "proposal" in result:
                    raise ReportingError(
                        "native_ai_schema_invalid", "只读任务不能返回可采纳编辑。"
                    )
                if projection is not None:
                    # 身份与执行清单来自授权真实预览，不接受模型自报。
                    result["projection"] = projection.projection
                    result["issues"] = list(result.get("issues", []))
                    for issue in projection.issues:
                        if issue not in result["issues"]:
                            result["issues"].append(issue)
                if job.status == "running":
                    job.result = result
                    job.status = "completed"
        except asyncio.CancelledError:
            job.status, job.result = "cancelled", None
            raise
        except Exception as error:
            if job.status == "cancelled":
                return
            if isinstance(error, ReportingError):
                code, message = error.code, error.message
            elif isinstance(error, TimeoutError):
                code, message = "native_ai_timeout", "PDF AI 阅读超时，请重试。"
            else:
                code, message = (
                    "native_ai_read_failed",
                    "PDF AI 阅读失败，文档与草稿保持原样。",
                )
            logger.warning(
                "native_pdf_ai_read_failed task_id={} error_type={}",
                job.task_id,
                type(error).__name__,
            )
            job.status, job.error = "failed", {"code": code, "message": message}
        finally:
            await job.event_log.finish(job.status)

    async def status(self, session, task_id: str, *, wait_ms: int = 20000):
        context = await self._context(session)
        self._prune()
        job = next(
            (
                job
                for (digest, _), job in self._jobs.items()
                if digest == context.digest() and job.task_id == task_id
            ),
            None,
        )
        if job is None:
            raise ReportingError("native_ai_job_missing", "PDF AI 任务不存在或已过期。")
        if job.task and not job.task.done() and wait_ms > 0:
            try:
                await asyncio.wait_for(
                    asyncio.shield(job.task), min(wait_ms, 20000) / 1000
                )
            except TimeoutError:
                pass
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if (current and current.cancelling()) or not job.task.cancelled():
                    raise
        return self._serialize(job)

    async def event_stream(self, session, task_id: str, after: int = 0):
        context = await self._context(session)
        self._prune()
        job = next((job for (digest, _), job in self._jobs.items()
                    if digest == context.digest() and job.task_id == task_id), None)
        if job is None:
            raise ReportingError("native_ai_job_missing", "PDF AI 任务不存在或已过期。")
        return event_stream_response(job.event_log, after)

    async def cancel_request(self, session, client_request_id: str):
        context = await self._context(session)
        request_id = self._request_id(client_request_id)
        self._prune()
        key = (context.digest(), request_id)
        job = self._jobs.get(key)
        if job is None:
            self._reserve(cancelled=True)
            job = _ReadJob(uuid4().hex, request_id, context.digest(), monotonic())
            self._jobs[key] = job
        job.status, job.result = "cancelled", None
        if job.task and not job.task.done():
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
        await job.event_log.finish(job.status)
        return self._serialize(job)

    @staticmethod
    def _serialize(job):
        return {
            "taskId": job.task_id,
            "clientRequestId": job.client_request_id,
            "status": job.status,
            "snapshotSha256": job.snapshot_sha256,
            **({"result": job.result} if job.result is not None else {}),
            **({"error": job.error} if job.error else {}),
        }

    async def aclose(self):
        self._closed = True
        jobs = list(self._jobs.values())
        tasks = [
            job.task for job in jobs if job.task and not job.task.done()
        ]
        for job in jobs:
            if job.status == "running":
                job.status, job.result = "cancelled", None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for job in jobs:
            if job.status == "cancelled":
                await job.event_log.finish(job.status)
