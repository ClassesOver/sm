"""Durable PDF text candidates reuse the native preview and acceptance checks."""
from __future__ import annotations

import asyncio
from functools import partial

from .durable_native_candidate import DurableNativeCandidateService
from .native_ai import _NativeAIJob, _invalid
from .native_candidate_runner import run_native_candidate


class DurablePDFCandidateService(DurableNativeCandidateService):
    executor_id = "native-pdf-ai"
    format_name = "PDF"
    job_type = _NativeAIJob

    async def _context(self, session):
        context = await super()._context(session)
        if context.format != "pdf":
            raise _invalid("native_ai_format_unsupported", "此入口仅支持原生 PDF。")
        return context

    def _durable_pdf_enabled(self, context):
        return self.task_repository is not None

    async def _create_durable_task(self, scope, instruction, fingerprint):
        return await self.task_repository.create_native_pdf_task(scope, instruction, fingerprint)

    async def _start_durable_pdf(self, job, session, context, base, selected, prompt, instruction, resume_edit_id):
        request_id = job.client_request_id
        edit_id = self._durable_edit_id(context, request_id)
        if resume_edit_id is not None and resume_edit_id != edit_id:
            raise _invalid("native_ai_job_missing", "原 PDF 任务不存在或已过期。")
        scope = self._durable_scope(context, edit_id)
        if not await self._register_durable_request(scope, instruction, job.request_sha256, resume_edit_id):
            return self._serialize(await self._cancelled_projection(context, edit_id, request_id))
        previous = self._request_job(context, request_id, job.request_sha256)
        if previous is not None:
            return self._serialize(previous)
        self._reserve()
        job.edit_id = edit_id
        self._jobs[edit_id] = job
        self._requests[(context.digest(), request_id)] = edit_id
        prepare = partial(self._run_job, job, session, context, base, selected, prompt)
        job.task = asyncio.create_task(run_native_candidate(
            self, scope, job, context, prepare, self.task_repository.request_native_workbook_finish,
        ))
        return self._serialize(job)
