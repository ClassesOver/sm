"""Common request identity, cancellation and receipts for native candidate editors."""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ..task_execution.models import TaskExecutionScope
from ..task_execution.repository import TaskExecutionRepositoryError
from .native import bind_native_workspace
from .native_ai import NativeAIService, _invalid
from .native_models import native_digest


class DurableNativeCandidateService(NativeAIService):
    def __init__(self, *args, task_repository=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.task_repository = task_repository
        self._requests: dict[tuple[str, str], str] = {}

    @staticmethod
    def _request_id(value):
        if not isinstance(value, str) or re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", value) is None:
            raise _invalid("native_ai_request_invalid", "AI 请求身份无效。")
        return value

    def _prune(self):
        cutoff = datetime.now(UTC) - timedelta(hours=1)
        for key, job in tuple(self._jobs.items()):
            if job.created_at < cutoff and (job.task is None or job.task.done()):
                self._jobs.pop(key, None)
        self._requests = {key: value for key, value in self._requests.items() if value in self._jobs}

    def _reserve(self, *, cancelled=False):
        if self._closed and not cancelled:
            raise _invalid("native_ai_closed", "AI 候选服务已关闭。")
        self._prune()
        # 提前取消的墓碑同样保留一小时，不能为腾容量而重启迟到请求。
        if len(self._jobs) >= 128 or not cancelled and sum(job.status == "running" for job in self._jobs.values()) >= 32:
            raise _invalid("native_ai_busy", "AI 候选任务繁忙，请稍后重试。")

    @staticmethod
    def _serialize(job):
        return {**NativeAIService._serialize(job), "clientRequestId": job.client_request_id}

    async def cancel_request(self, session, client_request_id):
        context = await self._context(session)
        request_id = self._request_id(client_request_id)
        if self.task_repository is not None:
            edit_id = self._durable_edit_id(context, request_id)
            if await self.task_repository.cancel_native_workbook_task(
                self._durable_scope(context, edit_id), create_tombstone=True,
            ):
                return self._serialize(await self._cancelled_projection(context, edit_id, request_id))
            return await self.wait_edit_status(session, edit_id, wait_ms=0)
        self._prune()
        key = (context.digest(), request_id)
        edit_id = self._requests.get(key)
        if edit_id is not None:
            return await self.cancel_edit(session, edit_id)
        self._reserve(cancelled=True)
        job = self.job_type(uuid4().hex, context.digest(), "", context.scope.user_id, datetime.now(UTC),
            status="cancelled", client_request_id=request_id)
        self._jobs[job.edit_id] = job
        self._requests[key] = job.edit_id
        await job.event_log.finish(job.status)
        return self._serialize(job)

    async def _register_durable_request(self, scope, instruction, fingerprint, resume_edit_id):
        repository = self.task_repository
        if await repository.is_native_workbook_task_cancelled(scope):
            return False
        if resume_edit_id is not None:
            if not await repository.has_native_workbook_task_input(scope, fingerprint):
                raise _invalid("native_ai_job_missing", f"原 {self.format_name} 任务不存在或已过期。")
        else:
            try:
                await self._create_durable_task(scope, instruction, fingerprint)
            except TaskExecutionRepositoryError as error:
                if error.code not in {"native_workbook_input_conflict", "task_initial_instruction_conflict"}:
                    raise
                if await repository.is_native_workbook_task_cancelled(scope):
                    return False
                raise _invalid("native_ai_snapshot_changed", "相同 AI 请求的内容已变化，请重新发起。") from None
        return True

    @staticmethod
    def _durable_edit_id(context, request_id):
        return native_digest({"context": context.digest(), "request": request_id})

    async def _cancelled_projection(self, context, edit_id, request_id=""):
        job = self._jobs.get(edit_id)
        if job is None:
            job = self.job_type(
                edit_id, context.digest(), "", context.scope.user_id, datetime.now(UTC),
                client_request_id=request_id,
            )
        job.status = "cancelled"
        job.proposal = job.error = None
        if job.task and not job.task.done():
            job.task.cancel()
        await job.event_log.finish(job.status)
        return job

    async def cancel_edit(self, session, edit_id):
        if self.task_repository is None or re.fullmatch(r"[0-9a-f]{64}", edit_id) is None:
            return await super().cancel_edit(session, edit_id)
        context = await self._context(session)
        try:
            cancelled = await self.task_repository.cancel_native_workbook_task(self._durable_scope(context, edit_id))
        except TaskExecutionRepositoryError as error:
            if error.code in {"task_not_found", "task_scope_mismatch"}:
                raise _invalid("native_ai_job_missing", f"{self.format_name} 任务不存在或已过期。") from None
            raise
        if cancelled:
            return self._serialize(await self._cancelled_projection(context, edit_id))
        return await self.wait_edit_status(session, edit_id, wait_ms=0)

    def _durable_scope(self, context, edit_id):
        return TaskExecutionScope(
            self.executor_id + ":" + edit_id, context.scope.user_id, context.scope.thread_id,
            bind_native_workspace(self.editor.workspace, context.scope) + ":" + context.digest(), self.executor_id,
        )

    async def _read_durable_candidate(self, scope, context):
        return await self.task_repository.get_completed_native_workbook_candidate(scope, context.digest())

    @staticmethod
    def _durable_candidate(job, proposal):
        return {"contextSha256": job.context_sha256, "snapshotSha256": job.snapshot_sha256,
                "clientRequestId": job.client_request_id, "proposal": proposal}

    async def _persist_acceptance(self, job, context, proposal):
        if self.task_repository is not None and re.fullmatch(r"[0-9a-f]{64}", job.edit_id):
            marked = await self.task_repository.accept_native_workbook_candidate(
                self._durable_scope(context, job.edit_id), self._durable_candidate(job, proposal),
            )
            if not marked:
                raise _invalid("native_ai_not_ready", f"{self.format_name} 候选已失效。")
            return True
        return False

    async def _job(self, session, edit_id):
        if self.task_repository is not None and re.fullmatch(r"[0-9a-f]{64}", edit_id):
            context = await self._context(session)
            scope = self._durable_scope(context, edit_id)
            if await self.task_repository.is_native_workbook_task_cancelled(scope):
                return await self._cancelled_projection(context, edit_id), context
            job = self._jobs.get(edit_id)
            if job is None or job.status == "succeeded":
                receipt = await self._read_durable_candidate(scope, context)
                if receipt is not None:
                    if job is None:
                        job = self.job_type(
                            edit_id, context.digest(), receipt["snapshotSha256"], context.scope.user_id,
                            datetime.now(UTC), status="succeeded", client_request_id=receipt["clientRequestId"],
                            proposal=receipt["proposal"], accepted=receipt["accepted"],
                        )
                        await job.event_log.finish(job.status)
                        return job, context
                    job.accepted = receipt["accepted"]
        return await super()._job(session, edit_id)
