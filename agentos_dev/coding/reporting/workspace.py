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
from agno.tools import Toolkit
from daytona.common.errors import DaytonaNotFoundError

from ...async_utils import complete_cleanup
from ...observability import suppress_expected_probe_tracing
from ...workspace import (
    MAX_TOOL_OUTPUT_BYTES,
    WORKSPACE_ROOT,
    WorkspaceError,
    WorkspaceService,
    _thread,
)

REPORT_JOBS_STATE_KEY = "report_jobs"
REPORT_DELIVERY_STATE_KEY = "report_delivery"
REPORT_DELIVERY_INCOMPLETE_MESSAGE = (
    "报表未完成：服务端未找到本轮已验收且当前仍存在的 Markdown/PDF/Word 产物，"
    "已阻止发送生成成功结论。"
)
MAX_REPORT_JOBS = 10
MAX_REPORT_JOB_STATE_BYTES = 48 * 1024
REPORT_RUNTIME_TIMEOUT_SECONDS = 600

WORKSPACE_REPORT_TOOLKIT_INSTRUCTIONS = """
智能报表工具规则：
- 本工具集只负责绑定报表输入，以及从同一 Markdown 生成并验收 PDF/Word；文件检查、Python 编码、分析和长进程统一使用 Coding 工具。
- 先通过 report_materialize_dataset 获得一至二十个 datasetId，再用 report_prepare_dataset 绑定这些不可变数据集句柄，并在后续各轮原样复用返回的 jobId。
- 复杂分析先用 terminal 检查文件，再用 patch 的 replace 或 patch 模式在工作区创建或修改 Python 脚本；不得用 Shell 绕过补丁边界。
- 用 terminal 执行当前依赖和权限允许的分析命令；返回 session_id 时用 process 轮询、输入或终止，不另加 Report 层命令限制。
- 分析失败时读取 output 和 exit_code，修正脚本或命令后继续；由模型根据证据充分性决定分析方式和轮次。
- 分析充分后，基于真实工具结果生成 Markdown 文件；结论、数字、表格和图片不得脱离分析结果，图片使用相对 Markdown 文件的路径。
- 使用新的输出路径调用 report_render_markdown，再调用兼容入口 report_validate_pdf 联合验收 PDF/Word；必要时用 view_image 检查生成的图表。report_job_status 为 validated 后仍须调用 finish_task，只有门禁 accepted 才能声称报表完成。
""".strip()


def report_delivery_content(content: Any, evidence: dict[str, Any] | None) -> str:
    if evidence is None:
        return REPORT_DELIVERY_INCOMPLETE_MESSAGE
    markdown_path = str(evidence["markdownPath"])
    pdf_path = str(evidence["pdfPath"])
    word_path = str(evidence["wordPath"])
    text = content.strip() if isinstance(content, str) else ""
    if markdown_path in text and pdf_path in text and word_path in text:
        return text
    prefix = text or "报表已生成并通过服务端验收。"
    return (
        f"{prefix}\n\n已验证产物：\n- Markdown：`{markdown_path}`"
        f"\n- PDF：`{pdf_path}`\n- Word：`{word_path}`"
    )


class WorkspaceReportToolkit(Toolkit):
    def __init__(self, service: WorkspaceService, data_sources: Any | None = None):
        self.service = service
        self.data_sources = data_sources
        super().__init__(
            name="workspace_report",
            tools=[
                self.report_prepare_dataset,
                self.report_job_status,
                self.report_render_markdown,
                self.report_validate_pdf,
            ],
            instructions=WORKSPACE_REPORT_TOOLKIT_INSTRUCTIONS,
            add_instructions=True,
        )

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

    def _touch_job(self, job_id: str, run_context: RunContext | None) -> None:
        state = self._session_state(run_context)
        delivery = state.get(REPORT_DELIVERY_STATE_KEY)
        if not isinstance(delivery, dict) or not isinstance(delivery.get("deliveryId"), str):
            return
        state[REPORT_DELIVERY_STATE_KEY] = {
            "deliveryId": delivery["deliveryId"],
            "jobId": job_id,
        }

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

    async def validated_delivery(
        self,
        delivery_id: str,
        run_context: RunContext | None,
    ) -> dict[str, Any] | None:
        state = self._session_state(run_context)
        delivery = state.get(REPORT_DELIVERY_STATE_KEY)
        if (
            not isinstance(delivery, dict)
            or delivery.get("deliveryId") != delivery_id
            or not isinstance(delivery.get("jobId"), str)
        ):
            return None
        try:
            job = self._load_job(delivery["jobId"], run_context)
            status = await self._job_status(job, run_context)
        except Exception:
            return None
        if status.get("status") != "validated":
            return None
        artifacts = status.get("artifacts")
        validation = status.get("validation")
        if not isinstance(artifacts, dict) or not isinstance(validation, dict):
            return None
        markdown = artifacts.get("markdown")
        pdf = artifacts.get("pdf")
        word = artifacts.get("word")
        if (
            not isinstance(markdown, dict)
            or not isinstance(pdf, dict)
            or not isinstance(word, dict)
            or markdown.get("changed") is not False
            or pdf.get("changed") is not False
            or word.get("changed") is not False
            or not isinstance(markdown.get("path"), str)
            or not isinstance(pdf.get("path"), str)
            or not isinstance(word.get("path"), str)
            or validation.get("ok") is not True
            or validation.get("pdfPath") != pdf["path"]
            or validation.get("wordPath") != word["path"]
        ):
            return None
        return {
            "jobId": job["jobId"],
            "status": "validated",
            "markdownPath": markdown["path"],
            "pdfPath": pdf["path"],
            "wordPath": word["path"],
            "markdownSha256": markdown.get("sha256"),
            "pdfSha256": pdf.get("sha256"),
            "wordSha256": word.get("sha256"),
        }

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
        self._touch_job(job_id, run_context)
        return {"status": "prepared", "jobId": job_id, "sources": sources}

    async def report_job_status(
        self,
        job_id: str,
        run_context: RunContext | None = None,
    ):
        """返回 job 的输入哈希、已登记产物哈希和最近双格式验收状态。"""
        job = self._load_job(job_id, run_context)
        self._touch_job(job["jobId"], run_context)
        return await self._job_status(job, run_context)

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

    async def report_render_markdown(
        self,
        job_id: str,
        markdown_path: str,
        output_path: str,
        run_context: RunContext | None = None,
    ):
        """按服务端版式生成双格式草稿；无需用户确认，正式 Workflow 会额外绑定 manifest。"""
        return await self._render_report_pair(
            job_id,
            markdown_path,
            output_path,
            artifact_manifest=None,
            run_context=run_context,
        )

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
        self._touch_job(job["jobId"], run_context)
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

    async def report_validate_pdf(
        self,
        job_id: str,
        pdf_path: str,
        artifact_manifest: dict[str, Any] | None = None,
        run_context: RunContext | None = None,
    ):
        """重新检查当前 job 已登记的 PDF 与 Word；无需用户确认。"""
        job = self._load_job(job_id, run_context)
        self._touch_job(job["jobId"], run_context)
        status = await self._job_status(job, run_context)
        if status["status"] == "artifact_changed":
            raise WorkspaceError("报表产物发生变化，请重新渲染后验收。")
        temporary_directory = f"/tmp/workspace-report-{uuid.uuid4().hex}-validate"
        render = job.get("render")
        word_path = render.get("word", {}).get("path") if isinstance(render, dict) else None
        if not isinstance(word_path, str):
            raise WorkspaceError("Word 未登记为当前报表产物。")
        try:
            validation = await self._run_report_runtime(
                "validate_pdf",
                {
                    "job": job,
                    "pdf_path": pdf_path,
                    "word_path": word_path,
                    "temporary_directory": temporary_directory,
                    "artifact_manifest": artifact_manifest,
                },
                run_context,
            )
            if (
                validation.get("pdfPath") != pdf_path
                or validation.get("wordPath") != word_path
                or not isinstance(validation.get("ok"), bool)
            ):
                raise WorkspaceError("PDF/Word 验收返回无效结果。")
            current_status = await self._job_status(job, run_context)
            if current_status["status"] == "artifact_changed":
                raise WorkspaceError("报表产物在验收期间发生变化，请重新渲染后验收。")
            job["validation"] = validation
            self._store_job(job, run_context)
            return validation
        finally:
            await complete_cleanup(
                self._delete_report_path(temporary_directory, run_context, recursive=True)
            )
