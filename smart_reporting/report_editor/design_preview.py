"""短期 PDF 成品预览；只使用独立运行状态，不提交修订或签发发布授权。"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import secrets
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from agno.run import RunContext
from loguru import logger

from ..reporting.models import ReportingError
from ..reporting.workflow.scope import resolve_reporting_workflow_scope
from ..reporting.workspace import REPORT_JOBS_STATE_KEY
from .render_preparation import prepare_editor_render
from .trace_retention import source_lifecycle_lock


@dataclass
class PreviewJob:
    context: Any
    task: asyncio.Task
    directory: str
    started: float
    finished: float | None = None
    expiry: asyncio.Task | None = None


class ReportDesignPreviewService:
    def __init__(self, editor):
        self.editor = editor
        self.jobs: dict[str, PreviewJob] = {}
        self._start_lock = asyncio.Lock()

    async def _cleanup(self, job):
        try:
            if await self.editor.workspace.apath_exists(job.context.scope["threadId"], job.directory):
                await self.editor.workspace.adelete_file(job.context.scope["threadId"], job.directory, recursive=True)
        except Exception:
            logger.opt(exception=True).warning("report_design_preview_cleanup_failed report_id={}", job.context.report_id)

    async def _prune(self):
        for key, job in list(self.jobs.items()):
            if job.task.done() and job.finished is not None and time.monotonic() - job.finished > 1800:
                await self._cleanup(job)
                self.jobs.pop(key, None)

    async def start(self, expected, expected_sha: str, expected_design_sha: str):
        async with self._start_lock:
            return await self._start(expected, expected_sha, expected_design_sha)

    async def _expire(self, preview_id, job):
        await asyncio.sleep(1800)
        if self.jobs.get(preview_id) is job:
            self.jobs.pop(preview_id, None)
            await self._cleanup(job)

    async def _start(self, expected, expected_sha: str, expected_design_sha: str):
        await self._prune()
        running = [job for job in self.jobs.values() if not job.task.done()]
        if len(running) >= 2 or any(job.context.digest() == expected.digest() for job in running):
            raise ReportingError("report_editor_export_busy", "预览任务正在进行，请稍后再试。")
        context = await self.editor._restore(expected)
        async with self.editor._draft_lock(context):
            _, markdown, sha = await self.editor._read_revision_markdown(context)
            if not secrets.compare_digest(sha, expected_sha):
                raise ReportingError("report_editor_conflict", "正文已变化，请保存后重新预览。")
            design = await self.editor.design._read(context, sha)
            self.editor.design.check(design, expected_design_sha)
            source = await self.editor._draft_source(context, sha)
        preview_id = uuid4().hex
        directory = f".reporting-tmp/editor-preview-{preview_id}"
        snapshot = str(PurePosixPath(source.markdown_path).with_name(f".preview-{preview_id}.md"))
        job_state = copy.deepcopy(context.job)
        job_state["_reportDesign"] = design.compact()
        job_state["_editorExportSettings"] = design.options.model_dump(by_alias=True)
        if not self.editor._lineage_features["exportSources"]:
            job_state["_editorExportSettings"]["sources"] = False
        if source.revision != context.revision:
            job_state.setdefault("render", {})["images"] = copy.deepcopy(source.job.get("render", {}).get("images", []))
        run_context = RunContext(run_id=context.workflow_run_id, session_id=context.scope["threadId"], user_id=context.scope["userId"], session_state={"report_workflow_scope": context.scope, REPORT_JOBS_STATE_KEY: {context.job_id: job_state}})
        task = asyncio.create_task(asyncio.wait_for(self._render(context, source, markdown, snapshot, directory, run_context), timeout=self.editor.export_timeout_seconds), name=f"report-design-preview:{preview_id}")
        job = PreviewJob(context, task, directory, time.monotonic())
        self.jobs[preview_id] = job
        def finished(done):
            job.finished = time.monotonic()
            if self.jobs.get(preview_id) is job:
                job.expiry = asyncio.create_task(self._expire(preview_id, job))
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
        return {"previewId": preview_id, "status": "running", "documentSha256": sha, "designSha256": design.digest()}

    async def _render(self, context, source, markdown, snapshot, directory, run_context):
        async with source_lifecycle_lock(self.editor, context):
            await self.editor._ensure_sources_retained(source)
            return await self._render_guarded(context, source, markdown, snapshot, directory, run_context)

    async def _render_guarded(self, context, source, markdown, snapshot, directory, run_context):
        if self.editor.report_tools is None:
            raise ReportingError("report_editor_export_failed", "预览渲染服务未配置。")
        try:
            await self.editor.workspace.awrite_text(context.scope["threadId"], snapshot, markdown)
            # 快照 Markdown 与来源已固定，不读取后台运行期间的新草稿。
            sha = hashlib.sha256(markdown.encode()).hexdigest()
            scope = resolve_reporting_workflow_scope(run_id=context.workflow_run_id, session_id=context.scope["sessionId"], user_id=context.scope["userId"], stored_scope=context.scope)
            prepared = await prepare_editor_render(
                self.editor, context=context, source_context=source,
                document=SimpleNamespace(markdown=markdown, sha256=sha), snapshot_path=snapshot,
                scope=scope, session_state=run_context.session_state, next_revision=source.revision,
                export_settings=run_context.session_state[REPORT_JOBS_STATE_KEY][context.job_id]["_editorExportSettings"],
                public_base_url=self.editor.public_base_url or "",
            )
            result = await asyncio.wait_for(self.editor.report_tools._render_report_pair(
                context.job_id, snapshot, f"{directory}/report.pdf", artifact_manifest=prepared[2],
                management_overview=prepared[5], run_context=run_context,
            ), timeout=self.editor.export_timeout_seconds)
            preparation_issues = prepared[4]
            if preparation_issues:
                validation = result.setdefault("validation", {})
                validation["ok"] = False
                validation["issues"] = [*(validation.get("issues") or []), *preparation_issues]
            path = result.get("pdfPath") or f"{directory}/report.pdf"
            identity = await self.editor.workspace.ahash_file(context.scope["threadId"], path)
            if identity.get("missing") or not identity.get("sha256"):
                raise ReportingError("report_editor_preview_missing", "PDF 预览未生成，已保留具体渲染告警。")
            return {"pdfPath": path, "identity": identity, "validation": result.get("validation")}
        finally:
            await self.editor._delete_export_snapshot(context.scope["threadId"], snapshot)

    async def _job(self, context, preview_id):
        await self._prune()
        job = self.jobs.get(preview_id)
        if job is None or job.context.digest() != context.digest():
            raise ReportingError("report_editor_preview_missing", "预览不存在或已过期，请重新生成。")
        return job

    async def status(self, context, preview_id):
        job = await self._job(context, preview_id)
        if not job.task.done():
            return {"previewId": preview_id, "status": "running"}
        if job.task.cancelled() or job.task.exception():
            error = None if job.task.cancelled() else job.task.exception()
            return {"previewId": preview_id, "status": "failed", "error": {"code": getattr(error, "code", "report_editor_preview_failed"), "message": getattr(error, "message", "PDF 预览失败，请重试。")}}
        return {"previewId": preview_id, "status": "succeeded", **job.task.result()}

    async def pdf(self, context, preview_id):
        job = await self._job(context, preview_id)
        if not job.task.done() or job.task.cancelled() or job.task.exception():
            raise ReportingError("report_editor_preview_missing", "PDF 预览尚不可用。")
        result = job.task.result()
        content, _ = await self.editor.workspace.afile_bytes(context.scope["threadId"], result["pdfPath"])
        if len(content) != result["identity"]["size"] or hashlib.sha256(content).hexdigest() != result["identity"]["sha256"]:
            raise ReportingError("snapshot_integrity_failed", "PDF 预览文件身份已变化，请重新生成。")
        return content

    async def aclose(self):
        jobs = list(self.jobs.values())
        self.jobs.clear()
        for job in jobs:
            if not job.task.done():
                job.task.cancel()
            if job.expiry is not None:
                job.expiry.cancel()
        await asyncio.gather(*(job.task for job in jobs), *(job.expiry for job in jobs if job.expiry is not None), return_exceptions=True)
        for job in jobs:
            await self._cleanup(job)
