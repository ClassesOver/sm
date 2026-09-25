"""报表工作区工具。"""

import asyncio
import copy
import hashlib
import io
import json
import sys
import uuid
import zipfile
from collections.abc import MutableMapping
from pathlib import Path, PurePosixPath
from typing import Any

from agno.run import RunContext
from loguru import logger as loguru_logger
from PIL import Image, UnidentifiedImageError

from ..async_utils import complete_cleanup
from ..workspace import (
    MAX_TOOL_OUTPUT_BYTES,
    WorkspaceError,
    WorkspacePathConflict,
    WorkspaceService,
    _thread,
)
from .models import ReportingError

REPORT_JOBS_STATE_KEY = "report_jobs"
MAX_REPORT_JOBS = 10
MAX_REPORT_JOB_STATE_BYTES = 48 * 1024
REPORT_RUNTIME_TIMEOUT_SECONDS = 600
MAX_REPORT_CHART_BYTES = 10 * 1024 * 1024
MAX_REPORT_PLOTLY_BYTES = 2 * 1024 * 1024
MAX_REPORT_PLOTLY_TRACES = 100
MAX_REPORT_PLOTLY_DEPTH = 20
MAX_REPORT_PLOTLY_NODES = 200_000
_PLOTLY_TRACE_TYPES = frozenset(
    {
        "bar",
        "box",
        "funnel",
        "heatmap",
        "histogram",
        "indicator",
        "pie",
        "scatter",
        "scattergl",
        "violin",
        "waterfall",
    }
)
_PLOTLY_FORBIDDEN_KEYS = frozenset({"src", "source", "mapboxaccesstoken"})
_PLOTLY_FORBIDDEN_STRING_MARKERS = ("http://", "https://", "javascript:", "data:")


def _report_runtime_package() -> tuple[bytes, str]:
    from .delivery.report_runtime import runtime as report_runtime

    package_root = Path(report_runtime.__file__).parent
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(package_root.glob("*.py")):
            info = zipfile.ZipInfo(f"report_runtime/{path.name}")
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    content = buffer.getvalue()
    return content, hashlib.sha256(content).hexdigest()


def _report_runtime_digest() -> str:
    return _report_runtime_package()[1]


async def inspect_report_chart_file(
    service: Any,
    *,
    thread_id: str,
    path: str,
) -> dict[str, Any]:
    """对报表图表文件执行确定性身份和图片内容检查。"""
    source_path = service.normalize_path(path, allow_root=False)[0]
    try:
        content = await service.read_limited_regular_file(
            thread_id, source_path, max_bytes=MAX_REPORT_CHART_BYTES
        )
    except WorkspaceError as error:
        raise ReportingError(
            "report_chart_file_missing",
            "图表源文件不存在;未生成的图表不得提交登记。",
            details={"sourcePath": source_path},
        ) from error
    if not 0 < len(content) <= MAX_REPORT_CHART_BYTES:
        raise ReportingError(
            "report_chart_source_invalid", "单张图表必须大于 0 且不超过 10 MiB。"
        )
    digest = hashlib.sha256(content).hexdigest()
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            image_format = str(image.format or "").upper()
            width, height = image.size
            colors = image.convert("RGBA").getcolors(maxcolors=2)
    except (UnidentifiedImageError, OSError) as error:
        raise ReportingError(
            "report_chart_source_invalid", "图表源文件无法解码或图片签名无效。"
        ) from error
    suffix = PurePosixPath(source_path).suffix.lower()
    if image_format == "PNG" and suffix == ".png":
        media_type, extension = "image/png", ".png"
    elif image_format == "JPEG" and suffix in {".jpg", ".jpeg"}:
        media_type, extension = "image/jpeg", ".jpg"
    else:
        raise ReportingError(
            "report_chart_source_invalid", "图表仅允许签名与扩展名一致的 PNG 或 JPEG。"
        )
    if width < 1 or height < 1 or (colors is not None and len(colors) <= 1):
        raise ReportingError("report_chart_blank", "图表图片完全空白，不能登记。")
    return {
        "sourcePath": source_path,
        "size": len(content),
        "sha256": digest,
        "format": image_format,
        "mediaType": media_type,
        "extension": extension,
        "width": width,
        "height": height,
    }


def _inspect_plotly_value(value: Any, *, depth: int = 0) -> int:
    if depth > MAX_REPORT_PLOTLY_DEPTH:
        raise ReportingError("report_plotly_source_invalid", "Plotly JSON 嵌套层级过深。")
    if isinstance(value, dict):
        nodes = 1
        for raw_key, child in value.items():
            normalized = str(raw_key).lower()
            if (
                not isinstance(raw_key, str)
                or normalized in _PLOTLY_FORBIDDEN_KEYS
                or normalized.startswith("on")
            ):
                raise ReportingError("report_plotly_source_invalid", "Plotly JSON 包含禁止字段。")
            nodes += _inspect_plotly_value(child, depth=depth + 1)
        return nodes
    if isinstance(value, list):
        return 1 + sum(
            _inspect_plotly_value(item, depth=depth + 1) for item in value
        )
    if isinstance(value, str):
        normalized_value = value.lower()
        if (
            any(marker in normalized_value for marker in _PLOTLY_FORBIDDEN_STRING_MARKERS)
            or normalized_value.startswith("//")
            or "<" in value
            or ">" in value
        ):
            raise ReportingError("report_plotly_source_invalid", "Plotly JSON 包含外部或可执行内容。")
    return 1


def _reject_plotly_nonfinite(value: str) -> None:
    raise ValueError(f"Plotly JSON 不允许 {value}")


async def inspect_report_plotly_file(
    service: Any,
    *,
    thread_id: str,
    path: str,
) -> dict[str, Any]:
    source_path = service.normalize_path(path, allow_root=False)[0]
    if not source_path.endswith(".plotly.json"):
        raise ReportingError("report_plotly_source_invalid", "Plotly 规格必须使用 .plotly.json 扩展名。")
    try:
        content = await service.read_limited_regular_file(
            thread_id, source_path, max_bytes=MAX_REPORT_PLOTLY_BYTES
        )
    except WorkspaceError as error:
        raise ReportingError(
            "report_plotly_file_missing",
            "Plotly JSON 不存在或超过 2 MiB。",
            details={"sourcePath": source_path},
        ) from error
    try:
        payload = json.loads(content, parse_constant=_reject_plotly_nonfinite)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        raise ReportingError("report_plotly_source_invalid", "Plotly JSON 无法解析。") from error
    if not isinstance(payload, dict) or set(payload) - {"data", "layout", "config"}:
        raise ReportingError("report_plotly_source_invalid", "Plotly JSON 顶层结构无效。")
    data = payload.get("data")
    if not isinstance(data, list) or not 1 <= len(data) <= MAX_REPORT_PLOTLY_TRACES:
        raise ReportingError("report_plotly_source_invalid", "Plotly JSON trace 数量无效。")
    if any(
        not isinstance(trace, dict) or trace.get("type") not in _PLOTLY_TRACE_TYPES
        for trace in data
    ):
        raise ReportingError("report_plotly_source_invalid", "Plotly JSON 包含不支持的 trace。")
    if "layout" in payload and not isinstance(payload["layout"], dict):
        raise ReportingError("report_plotly_source_invalid", "Plotly layout 必须是对象。")
    if "config" in payload and not isinstance(payload["config"], dict):
        raise ReportingError("report_plotly_source_invalid", "Plotly config 必须是对象。")
    if _inspect_plotly_value(payload) > MAX_REPORT_PLOTLY_NODES:
        raise ReportingError("report_plotly_source_invalid", "Plotly JSON 复杂度超过上限。")
    return {
        "sourcePath": source_path,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "mediaType": "application/vnd.plotly.v1+json",
        "traceCount": len(data),
    }


class WorkspaceReportService:
    def __init__(self, service: WorkspaceService, data_sources: Any | None = None):
        self.service = service
        self.data_sources = data_sources

    async def _inspect_chart_file(
        self,
        *,
        thread_id: str,
        path: str,
    ) -> dict[str, Any]:
        return await inspect_report_chart_file(self.service, thread_id=thread_id, path=path)

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
        if action not in {"render_markdown", "validate_pdf"}:
            raise WorkspaceError("报表运行时 action 无效。")
        try:
            payload_text = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as error:
            raise WorkspaceError("报表运行时 payload 无效。") from error
        runtime_package, expected_runtime_digest = await asyncio.to_thread(_report_runtime_package)
        runtime_package_relative_path = (
            f".workspace-report-runtime-{uuid.uuid4().hex}-{expected_runtime_digest}.zip"
        )
        thread_id = _thread(run_context)
        # 入口代码和包内容由服务端固定；Agno Workspace 将进程 cwd 固定到会话根。
        script = (
            "import hashlib,json,sys\n"
            "from pathlib import Path\n"
            f"package=Path({runtime_package_relative_path!r})\n"
            "if not package.is_file() or "
            f"hashlib.sha256(package.read_bytes()).hexdigest()!={expected_runtime_digest!r}:\n"
            " print(json.dumps({'error':'报表运行时版本不匹配'},ensure_ascii=False));"
            "raise SystemExit(1)\n"
            "sys.path.insert(0,str(package))\n"
            "from report_runtime.cli import main\n"
            f"exit_code=main([{action!r}, {payload_text!r}])\n"
            "print(json.dumps({'__reportExitCode':exit_code},separators=(',',':')))\n"
        )
        await self.service.awrite_bytes(
            thread_id, runtime_package_relative_path, runtime_package
        )
        try:
            stdout = await self.service.arun_command(
                thread_id,
                [sys.executable, "-c", script],
                timeout=REPORT_RUNTIME_TIMEOUT_SECONDS,
                tail=200,
            )
        finally:
            await complete_cleanup(
                self.service.adelete_file(thread_id, runtime_package_relative_path)
            )
        if len(stdout.encode("utf-8")) > MAX_TOOL_OUTPUT_BYTES:
            raise WorkspaceError("报表运行时返回结果超过大小限制。")
        lines = [line for line in stdout.splitlines() if line.strip()]
        try:
            status = json.loads(lines[-1])
        except (IndexError, json.JSONDecodeError) as error:
            raise WorkspaceError("报表运行时返回无效结果。") from error
        if not isinstance(status, dict) or "__reportExitCode" not in status:
            raise WorkspaceError("报表运行时返回无效结果。")
        if status["__reportExitCode"] != 0:
            message = None
            # 受控 runtime 把规范化业务错误写入 stdout；渲染依赖可能随后在 stderr
            # 输出 warning。必须查找结构化错误对象，不能让无关尾行遮蔽失败事实。
            for line in reversed(lines[:-1]):
                try:
                    failure = json.loads(line)
                except json.JSONDecodeError:
                    continue
                candidate = failure.get("error") if isinstance(failure, dict) else None
                if isinstance(candidate, str) and candidate:
                    message = candidate
                    break
            raise WorkspaceError(str(message or "报表运行失败。"))
        try:
            result_line = lines[-2]
            parsed = json.loads(result_line)
        except (IndexError, json.JSONDecodeError) as error:
            raise WorkspaceError("报表运行时返回无效结果。") from error
        if not isinstance(parsed, dict):
            raise WorkspaceError("报表运行时返回无效结果。")
        return parsed

    async def _delete_report_path(
        self,
        path: str,
        run_context: RunContext | None,
        *,
        recursive: bool,
    ) -> None:
        try:
            await self.service.adelete_file(
                _thread(run_context), path, recursive=recursive
            )
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

    async def complete_document_heading_numbers(
        self,
        job_id: str,
        heading_numbers: list[dict[str, Any]],
        run_context: RunContext | None = None,
    ) -> None:
        """在正文装配后一次性补全标题映射；既有封面和章节事实不可改写。"""
        if not isinstance(heading_numbers, list) or not heading_numbers:
            raise WorkspaceError("报告标题编号映射无效。")
        job = self._load_job(job_id, run_context)
        context = job.get("_documentContext")
        if not isinstance(context, dict):
            raise WorkspaceError("报告文档展示契约尚未绑定。")
        existing = context.get("headingNumbers")
        if existing is not None and existing != heading_numbers:
            raise WorkspaceError("报告标题编号映射已经绑定且内容不同。")
        completed = {**context, "headingNumbers": copy.deepcopy(heading_numbers)}
        encoded = json.dumps(
            completed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > 32 * 1024:
            raise WorkspaceError("报告文档展示契约超过状态边界。")
        job["_documentContext"] = completed
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
        temporary_root = f".reporting-tmp/workspace-report-{invocation}-render"
        temporary_pdf = f"{temporary_root}/render.pdf"
        staging_directory = output.parent.with_name(f".{output.parent.name}.{invocation}.tmp")
        staging_relative = staging_directory.as_posix()
        _normalized_staging, _staging_host_path = self.service.normalize_path(
            staging_relative, allow_root=False
        )
        staged_pdf_relative = str(staging_directory / output.name)
        staged_word_relative = str(staging_directory / word_output.name)
        final_directory_relative = output.parent.as_posix()
        _normalized_final, _final_host_path = self.service.normalize_path(
            final_directory_relative, allow_root=False
        )
        validation_directory = f".reporting-tmp/workspace-report-{uuid.uuid4().hex}-validate"
        published = False
        try:
            thread_id = _thread(run_context)
            await self.service.aensure_directory(thread_id, output.parent.parent.as_posix())
            if await self.service.apath_exists(thread_id, final_directory_relative):
                raise WorkspacePathConflict(
                    "报告 revision 输出目录已经存在，请使用新的 revision。"
                )
            if await self.service.apath_exists(thread_id, staging_relative):
                raise WorkspaceError("报告 revision 暂存目录已经存在。")
            result = await self._run_report_runtime(
                "render_markdown",
                {
                    "job": job,
                    "markdown_path": markdown_path,
                    "output_path": staged_pdf_relative,
                    "temporary_path": temporary_pdf,
                    "page_layout": job.get("_pageLayout"),
                    "word_output_path": staged_word_relative,
                },
                run_context,
            )
            render = result.pop("render", None)
            if (
                not isinstance(render, dict)
                or render.get("pdf", {}).get("path") != staged_pdf_relative
                or render.get("word", {}).get("path") != staged_word_relative
            ):
                raise WorkspaceError("报表运行时返回无效产物。")
            staged_pdf = await self.service.ahash_file(_thread(run_context), staged_pdf_relative)
            staged_word = await self.service.ahash_file(_thread(run_context), staged_word_relative)
            if any(
                staged.get("sha256") != render[key].get("sha256")
                or staged.get("size") != render[key].get("size")
                for key, staged in (
                    ("pdf", staged_pdf),
                    ("word", staged_word),
                )
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
                loguru_logger.warning(
                    "report_runtime_validation_failed details={}",
                    json.dumps(validation, ensure_ascii=False, default=str)[:4000],
                )
                raise WorkspaceError("PDF/Word 联合验收未通过。")
            await self.service.amove_files(thread_id, staging_relative, final_directory_relative)
            published = True
            current_pdf = await self.service.ahash_file(_thread(run_context), relative_output)
            current_word = await self.service.ahash_file(_thread(run_context), relative_word)
            if any(
                current.get("sha256") != render[key].get("sha256")
                or current.get("size") != render[key].get("size")
                for key, current in (
                    ("pdf", current_pdf),
                    ("word", current_word),
                )
            ):
                raise WorkspaceError("双格式报告发布身份校验失败。")
            validation["pdfPath"] = relative_output
            validation["wordPath"] = relative_word
            render["pdf"]["path"] = relative_output
            render["word"]["path"] = relative_word
            # 完整 render 只在同一次受控验收中使用；durable job 已分别持有文档上下文、
            # 引用和页面布局。这里只保存后续状态查询与 revision 清理所需的产物身份，
            # 避免重复结构挤占 48 KiB 的会话状态边界。
            job["render"] = {
                key: render[key] for key in ("markdown", "pdf", "word", "images")
            }
            # 逐页验收结果由本方法返回并写入 Workflow 权威状态；job 只需记录是否通过，
            # 否则最多 200 页的 pages 数组会让 durable job 再次线性越过 48 KiB。
            job["validation"] = {"ok": True}
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
                    self._delete_report_path(
                        final_directory_relative, run_context, recursive=True
                    )
                )
            raise
        finally:
            await complete_cleanup(
                self._delete_report_path(staging_relative, run_context, recursive=True)
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
            raise WorkspaceError("待清理的 PDF 和 Word revision 身份不一致。")
        job = self._load_job(job_id, run_context)
        render = job.get("render")
        if (
            not isinstance(render, dict)
            or render.get("pdf", {}).get("path") != pdf_relative
            or render.get("word", {}).get("path") != word_relative
        ):
            raise WorkspaceError("待清理的双格式 revision 不属于当前报表 job。")
        revision_relative, _revision_host_path = self.service.normalize_path(
            pdf.parent.as_posix(), allow_root=False
        )
        await self.service.adelete_file(
            _thread(run_context), revision_relative, recursive=True
        )
        job.pop("render", None)
        job.pop("validation", None)
        self._store_job(job, run_context)
