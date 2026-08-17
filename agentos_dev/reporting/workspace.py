"""报表工作区工具。"""

import copy
import hashlib
import json
import shlex
import uuid
from collections.abc import MutableMapping
from pathlib import PurePosixPath
from typing import Any

from agno.run import RunContext
from daytona.common.errors import DaytonaNotFoundError

from ..async_utils import complete_cleanup
from ..observability import suppress_expected_probe_tracing
from ..workspace import (
    MAX_TOOL_OUTPUT_BYTES,
    WORKSPACE_ROOT,
    WorkspaceError,
    WorkspaceService,
    _thread,
)

REPORT_JOBS_STATE_KEY = "report_jobs"
MAX_REPORT_JOBS = 10
MAX_REPORT_JOB_STATE_BYTES = 48 * 1024
REPORT_RUNTIME_TIMEOUT_SECONDS = 600


class WorkspaceReportService:
    def __init__(self, service: WorkspaceService, data_sources: Any | None = None):
        self.service = service
        self.data_sources = data_sources

    @staticmethod
    def _session_state(run_context: RunContext | None) -> MutableMapping[str, Any]:
        if run_context is None:
            raise WorkspaceError("当前报表操作没有绑定对话，请刷新页面后重试。")
        if run_context.session_state is None:
            run_context.session_state = {}
        if not isinstance(run_context.session_state, MutableMapping):
            raise WorkspaceError("当前报表任务状态无效，请重新准备数据集。")
        return run_context.session_state

    @staticmethod
    def _thread_binding(thread: str) -> str:
        return hashlib.sha256(thread.encode()).hexdigest()

    def _load_job(
        self,
        job_id: str,
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        try:
            normalized_job_id = str(uuid.UUID(job_id))
        except (AttributeError, TypeError, ValueError) as error:
            raise WorkspaceError("job_id 无效，请重新准备数据集。") from error
        stored = self._session_state(run_context).get(REPORT_JOBS_STATE_KEY, {})
        raw = stored.get(normalized_job_id) if isinstance(stored, dict) else None
        if not isinstance(raw, dict):
            raise WorkspaceError("分析任务不存在，请重新准备数据集。")
        if raw.get("jobId") != normalized_job_id:
            raise WorkspaceError("分析任务状态无效，请重新准备数据集。")
        if raw.get("_threadBinding") != self._thread_binding(_thread(run_context)):
            raise WorkspaceError("分析任务不属于当前对话，请重新准备数据集。")
        return copy.deepcopy(raw)

    def _store_job(
        self,
        job: dict[str, Any],
        run_context: RunContext | None,
    ) -> None:
        if len(json.dumps(job, ensure_ascii=False).encode("utf-8")) > MAX_REPORT_JOB_STATE_BYTES:
            raise WorkspaceError("报表任务状态超过服务端边界，请减少报表页数后重试。")
        state = self._session_state(run_context)
        current = state.get(REPORT_JOBS_STATE_KEY, {})
        jobs = dict(current) if isinstance(current, dict) else {}
        job_id = str(job["jobId"])
        jobs[job_id] = copy.deepcopy(job)
        while len(jobs) > MAX_REPORT_JOBS:
            jobs.pop(next(iter(jobs)))
        state[REPORT_JOBS_STATE_KEY] = jobs

    async def _current_artifact(
        self,
        recorded: Any,
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        if not isinstance(recorded, dict) or not isinstance(recorded.get("path"), str):
            raise WorkspaceError("报表任务产物状态无效，请重新生成报表。")
        current = await self.service.ahash_file(_thread(run_context), recorded["path"])
        current["changed"] = current.get("sha256") != recorded.get("sha256") or current.get(
            "size"
        ) != recorded.get("size")
        return current

    async def _job_status(
        self,
        job: dict[str, Any],
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        sources = job.get("sources")
        if not isinstance(sources, list) or not sources:
            raise WorkspaceError("分析任务缺少数据集状态，请重新准备数据集。")
        current_sources = [await self._current_artifact(source, run_context) for source in sources]
        if any(source["changed"] for source in current_sources):
            raise WorkspaceError("源文件发生变化，分析任务已失效，请重新准备数据集。")
        validation = job.get("validation")
        render = job.get("render")
        status = (
            "validated"
            if isinstance(validation, dict) and validation.get("ok") is True
            else "validation_failed"
            if isinstance(validation, dict)
            else "rendered"
            if isinstance(render, dict)
            else "prepared"
        )
        result: dict[str, Any] = {
            "jobId": job["jobId"],
            "status": status,
            "sources": current_sources,
        }
        if isinstance(render, dict):
            markdown_artifact = await self._current_artifact(render.get("markdown"), run_context)
            pdf_artifact = await self._current_artifact(render.get("pdf"), run_context)
            word_artifact = await self._current_artifact(render.get("word"), run_context)
            image_artifacts = [
                await self._current_artifact(item, run_context) for item in render.get("images", [])
            ]
            artifacts: dict[str, Any] = {
                "markdown": markdown_artifact,
                "pdf": pdf_artifact,
                "word": word_artifact,
                "images": image_artifacts,
            }
            result["artifacts"] = artifacts
            if (
                markdown_artifact["changed"]
                or pdf_artifact["changed"]
                or word_artifact["changed"]
                or any(item["changed"] for item in image_artifacts)
            ):
                result["status"] = "artifact_changed"
        if isinstance(validation, dict):
            result["validation"] = validation
        if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_TOOL_OUTPUT_BYTES:
            raise WorkspaceError("报表任务状态超过返回边界，请重新生成较短的报表。")
        return result

    async def _run_report_runtime(
        self,
        action: str,
        payload: dict[str, Any],
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        from .delivery import report_runtime

        with open(report_runtime.__file__, "rb") as runtime_file:
            content = runtime_file.read()
        digest = hashlib.sha256(content).hexdigest()
        remote = f"/tmp/workspace-report-runtime-{digest}.py"
        async with self.service._async_client() as client:
            sandbox = await self.service._asandbox_for(client, _thread(run_context))
            await sandbox.fs.upload_file(content, remote)
            command = (
                f"python {shlex.quote(remote)} {shlex.quote(action)} "
                f"{shlex.quote(json.dumps(payload, ensure_ascii=False))}"
            )
            value = await sandbox.process.exec(
                command,
                cwd=WORKSPACE_ROOT,
                timeout=REPORT_RUNTIME_TIMEOUT_SECONDS,
            )
        result = self.service._bounded_output(value)
        if result["exitCode"] != 0:
            try:
                failure = json.loads(
                    next(line for line in reversed(result["output"].splitlines()) if line.strip())
                )
            except (StopIteration, json.JSONDecodeError):
                failure = None
            message = failure.get("error") if isinstance(failure, dict) else None
            raise WorkspaceError(str(message or "报表运行失败。"))
        try:
            output = next(line for line in reversed(result["output"].splitlines()) if line.strip())
            parsed = json.loads(output)
        except (StopIteration, json.JSONDecodeError) as error:
            raise WorkspaceError("报表运行时返回无效结果。") from error
        if not isinstance(parsed, dict):
            raise WorkspaceError("报表运行时返回无效结果。")
        return parsed

    async def _delete_report_path(
        self,
        remote: str,
        run_context: RunContext | None,
        *,
        recursive: bool,
    ) -> None:
        try:
            async with self.service._async_client() as client:
                sandbox = await self.service._asandbox_for(client, _thread(run_context))
                with suppress_expected_probe_tracing():
                    await sandbox.fs.delete_file(remote, recursive=recursive)
        except Exception:
            pass

    async def report_prepare_dataset(
        self,
        dataset_ids: list[str],
        run_context: RunContext | None = None,
    ):
        """通过一至二十个不可变 dataset_id 创建服务端报表任务。"""
        if self.data_sources is None:
            raise WorkspaceError("当前报表工具未配置数据集解析器，请重新进入智能报表。")
        if not isinstance(dataset_ids, list) or len(set(dataset_ids)) != len(dataset_ids):
            raise WorkspaceError("dataset_ids 必须是不重复的数据集标识数组。")
        paths = await self.data_sources.resolve_dataset_paths(
            dataset_ids,
            run_context=run_context,
        )
        sources = [await self.service.ahash_file(_thread(run_context), path) for path in paths]
        job_id = str(uuid.uuid4())
        job = {
            "jobId": job_id,
            "_threadBinding": self._thread_binding(_thread(run_context)),
            "sources": sources,
        }
        self._store_job(job, run_context)
        return {"status": "prepared", "jobId": job_id, "sources": sources}

    async def bind_page_layout(
        self,
        job_id: str,
        page_layout: dict[str, str],
        run_context: RunContext | None = None,
    ) -> None:
        """由 Workflow 绑定服务端页面版式；该方法不注册为 Agent 工具。"""
        if not isinstance(page_layout, dict):
            raise WorkspaceError("PDF 页面格式无效。")
        job = self._load_job(job_id, run_context)
        if "_pageLayout" in job:
            raise WorkspaceError("PDF 页面格式已经绑定。")
        job["_pageLayout"] = dict(page_layout)
        self._store_job(job, run_context)

    async def bind_document_context(
        self,
        job_id: str,
        document_context: dict[str, Any],
        run_context: RunContext | None = None,
    ) -> None:
        """绑定服务端封面、品牌、章节和落款事实；该方法不注册为 Agent 工具。"""
        if not isinstance(document_context, dict):
            raise WorkspaceError("报告文档展示契约无效。")
        encoded = json.dumps(
            document_context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > 32 * 1024:
            raise WorkspaceError("报告文档展示契约超过状态边界。")
        job = self._load_job(job_id, run_context)
        existing = job.get("_documentContext")
        if existing is not None and existing != document_context:
            raise WorkspaceError("报告文档展示契约已经绑定且内容不同。")
        job["_documentContext"] = copy.deepcopy(document_context)
        self._store_job(job, run_context)

    async def bind_citation_presentations(
        self,
        job_id: str,
        presentations: list[dict[str, Any]],
        run_context: RunContext | None = None,
    ) -> None:
        """由 Workflow 绑定 PDF 可读引用；该内部方法不注册为 Agent 工具。"""
        if not isinstance(presentations, list) or not presentations:
            raise WorkspaceError("PDF 实际引用展示信息无效。")
        encoded = json.dumps(
            presentations,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > MAX_REPORT_JOB_STATE_BYTES // 2:
            raise WorkspaceError("PDF 实际引用展示信息超过状态边界。")
        job = self._load_job(job_id, run_context)
        existing = job.get("_citationPresentations")
        if existing is not None and existing != presentations:
            raise WorkspaceError("PDF 实际引用展示信息已经绑定且内容不同。")
        job["_citationPresentations"] = copy.deepcopy(presentations)
        self._store_job(job, run_context)

    async def _render_report_pair(
        self,
        job_id: str,
        markdown_path: str,
        output_path: str,
        *,
        artifact_manifest: dict[str, Any] | None,
        run_context: RunContext | None = None,
    ):
        """从同一 Markdown 生成并验收 PDF/Word，再原子发布整个 revision。"""
        job = self._load_job(job_id, run_context)
        await self._job_status(job, run_context)
        relative_output, _remote_output = self.service.normalize_path(output_path, allow_root=False)
        output = PurePosixPath(relative_output)
        requested_word = str(output.with_suffix(".docx"))
        relative_word, _remote_word = self.service.normalize_path(requested_word, allow_root=False)
        word_output = PurePosixPath(relative_word)
        if (
            output.suffix.lower() != ".pdf"
            or word_output.suffix.lower() != ".docx"
            or output.parent != word_output.parent
            or output.stem != word_output.stem
            or output.parent == PurePosixPath(".")
        ):
            raise WorkspaceError("PDF 和 Word 必须使用同一 revision 目录和文件名主体。")
        invocation = uuid.uuid4().hex
        temporary_root = f"/tmp/workspace-report-{invocation}-render"
        temporary_pdf = f"{temporary_root}/render.pdf"
        temporary_word = f"{temporary_root}/render.docx"
        staging_directory = output.parent.with_name(f".{output.parent.name}.{invocation}.tmp")
        staging_relative = staging_directory.as_posix()
        _normalized_staging, remote_staging = self.service.normalize_path(
            staging_relative, allow_root=False
        )
        staged_pdf_relative = str(staging_directory / output.name)
        staged_word_relative = str(staging_directory / word_output.name)
        _staged_pdf, remote_staged_pdf = self.service.normalize_path(
            staged_pdf_relative, allow_root=False
        )
        _staged_word, remote_staged_word = self.service.normalize_path(
            staged_word_relative, allow_root=False
        )
        final_directory_relative = output.parent.as_posix()
        _normalized_final, remote_final_directory = self.service.normalize_path(
            final_directory_relative, allow_root=False
        )
        validation_directory = f"/tmp/workspace-report-{uuid.uuid4().hex}-validate"
        published = False
        try:
            async with self.service._async_client() as client:
                sandbox = await self.service._asandbox_for(client, _thread(run_context))
                await self.service._aensure_directory(
                    sandbox, remote_final_directory.rsplit("/", 1)[0]
                )
                for candidate in (remote_final_directory, remote_staging):
                    try:
                        await self.service._ainfo(sandbox, candidate)
                    except DaytonaNotFoundError:
                        continue
                    raise WorkspaceError("报告 revision 输出目录已经存在，请使用新的 revision。")
            result = await self._run_report_runtime(
                "render_markdown",
                {
                    "job": job,
                    "markdown_path": markdown_path,
                    "output_path": output_path,
                    "temporary_path": temporary_pdf,
                    "page_layout": job.get("_pageLayout"),
                    "word_output_path": relative_word,
                },
                run_context,
            )
            render = result.pop("render", None)
            if (
                not isinstance(render, dict)
                or render.get("pdf", {}).get("path") != relative_output
                or render.get("word", {}).get("path") != relative_word
            ):
                raise WorkspaceError("报表运行时返回无效产物。")
            async with self.service._async_client() as client:
                sandbox = await self.service._asandbox_for(client, _thread(run_context))
                created = await sandbox.process.exec(
                    self.service._shell_command(f"mkdir -- {shlex.quote(remote_staging)}"),
                    cwd=WORKSPACE_ROOT,
                    timeout=30,
                )
                if getattr(created, "exit_code", None) != 0:
                    raise WorkspaceError("双格式报告暂存目录创建失败。")
                for source, target in (
                    (temporary_pdf, remote_staged_pdf),
                    (temporary_word, remote_staged_word),
                ):
                    copied = await sandbox.process.exec(
                        self.service._shell_command(
                            f"cp --no-clobber -- {shlex.quote(source)} {shlex.quote(target)}"
                        ),
                        cwd=WORKSPACE_ROOT,
                        timeout=30,
                    )
                    if getattr(copied, "exit_code", None) != 0:
                        raise WorkspaceError("双格式报告暂存失败。")
            staged_pdf = await self.service.ahash_file(_thread(run_context), staged_pdf_relative)
            staged_word = await self.service.ahash_file(_thread(run_context), staged_word_relative)
            if any(
                staged.get("sha256") != render[key].get("sha256")
                or staged.get("size") != render[key].get("size")
                for key, staged in (("pdf", staged_pdf), ("word", staged_word))
            ):
                raise WorkspaceError("双格式报告暂存身份校验失败。")

            staged_render = copy.deepcopy(render)
            staged_render["pdf"]["path"] = staged_pdf_relative
            staged_render["word"]["path"] = staged_word_relative
            staged_job = copy.deepcopy(job)
            staged_job["render"] = staged_render
            validation = await self._run_report_runtime(
                "validate_pdf",
                {
                    "job": staged_job,
                    "pdf_path": staged_pdf_relative,
                    "word_path": staged_word_relative,
                    "temporary_directory": validation_directory,
                    "artifact_manifest": artifact_manifest,
                },
                run_context,
            )
            if validation.get("ok") is not True:
                raise WorkspaceError("PDF/Word 联合验收未通过。")
            async with self.service._async_client() as client:
                sandbox = await self.service._asandbox_for(client, _thread(run_context))
                publish_result = await sandbox.process.exec(
                    self.service._shell_command(
                        f"mv -T -- {shlex.quote(remote_staging)} "
                        f"{shlex.quote(remote_final_directory)}"
                    ),
                    cwd=WORKSPACE_ROOT,
                    timeout=30,
                )
            if getattr(publish_result, "exit_code", None) != 0:
                raise WorkspaceError("双格式报告 revision 原子发布失败。")
            published = True
            current_pdf = await self.service.ahash_file(_thread(run_context), relative_output)
            current_word = await self.service.ahash_file(_thread(run_context), relative_word)
            if any(
                current.get("sha256") != render[key].get("sha256")
                or current.get("size") != render[key].get("size")
                for key, current in (("pdf", current_pdf), ("word", current_word))
            ):
                raise WorkspaceError("双格式报告发布身份校验失败。")
            validation["pdfPath"] = relative_output
            validation["wordPath"] = relative_word
            render["pdf"]["path"] = relative_output
            render["word"]["path"] = relative_word
            job["render"] = render
            job["validation"] = validation
            self._store_job(job, run_context)
            result.update(
                {
                    "status": "validated",
                    "pdfPath": relative_output,
                    "wordPath": relative_word,
                    "validation": validation,
                }
            )
            return result
        except BaseException:
            if published:
                await complete_cleanup(
                    self._delete_report_path(remote_final_directory, run_context, recursive=True)
                )
            raise
        finally:
            await complete_cleanup(
                self._delete_report_path(remote_staging, run_context, recursive=True)
            )
            await complete_cleanup(
                self._delete_report_path(temporary_root, run_context, recursive=True)
            )
            await complete_cleanup(
                self._delete_report_path(validation_directory, run_context, recursive=True)
            )

    async def discard_report_revision(
        self,
        job_id: str,
        pdf_path: str,
        word_path: str,
        run_context: RunContext | None = None,
    ) -> None:
        """联合门禁失败后删除本轮整个 revision，并清除对应 job 产物状态。"""
        pdf_relative, _pdf_remote = self.service.normalize_path(pdf_path, allow_root=False)
        word_relative, _word_remote = self.service.normalize_path(word_path, allow_root=False)
        pdf = PurePosixPath(pdf_relative)
        word = PurePosixPath(word_relative)
        if (
            pdf.suffix.lower() != ".pdf"
            or word.suffix.lower() != ".docx"
            or pdf.parent != word.parent
            or pdf.stem != word.stem
        ):
            raise WorkspaceError("待清理的 PDF/Word revision 身份不一致。")
        job = self._load_job(job_id, run_context)
        render = job.get("render")
        if (
            not isinstance(render, dict)
            or render.get("pdf", {}).get("path") != pdf_relative
            or render.get("word", {}).get("path") != word_relative
        ):
            raise WorkspaceError("待清理的 revision 不属于当前报表 job。")
        _revision_relative, revision_remote = self.service.normalize_path(
            pdf.parent.as_posix(), allow_root=False
        )
        async with self.service._async_client() as client:
            sandbox = await self.service._asandbox_for(client, _thread(run_context))
            with suppress_expected_probe_tracing():
                await sandbox.fs.delete_file(revision_remote, recursive=True)
        job.pop("render", None)
        job.pop("validation", None)
        self._store_job(job, run_context)
