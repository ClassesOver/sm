"""派生/脱敏 CSV 导出服务（B1，计划 4.1-7 与 5.1）。

派生文件是独立产物：掩码列替换、其余列保持原值，身份（sha256）与原始
快照不同，响应与文件名明确标注派生，不冒充原始 CSV。任务复用编辑器
导出的"后台任务 + 轮询"模式；下载时重验任务归属与保留期，过期即拒绝
并清理（独立短保留期，默认 24h，见 TRACE_BUDGETS_V1）。

生成走 polars lazy ``sink_csv`` 流式写，不整表入内存；策略代码只接受
本模块登记的注册表，未登记策略立即 4xx，不进入执行器。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
import polars as pl
from loguru import logger

from ..reporting.models import ReportingError
from ..reporting.trace.contracts_v1 import TRACE_BUDGETS_V1
from ..reporting.trace.dataset_service import (
    TraceDatasetFile,
    is_blocked_column,
    read_csv_header,
    safe_download_filename,
)

_MAX_DERIVED_EXPORT_JOBS = 4
_RETENTION_SECONDS = TRACE_BUDGETS_V1["export_derived_retention_seconds"]
_MAX_POLICY_COLUMNS = 200
_UNSAFE_FILENAME_PATTERN = re.compile(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+")


@dataclass
class TraceExportJob:
    export_id: str
    report_id: str
    revision: int
    dataset_id: str
    policy: str
    params: dict[str, Any]
    source_dataset_id: str
    source_sha256: str
    workspace_path: str
    thread_id: str
    created_at: float
    status: str = "running"
    size: int | None = None
    sha256: str | None = None
    error: str | None = None
    finished_at: float | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "exportId": self.export_id,
            "status": self.status,
            "policy": self.policy,
            "derived": True,
            "sourceDatasetId": self.source_dataset_id,
            "sourceSha256": self.source_sha256,
            "createdAt": self.created_at,
        }
        if self.size is not None:
            payload["size"] = self.size
        if self.sha256 is not None:
            payload["sha256"] = self.sha256
        if self.error is not None:
            payload["error"] = {"code": "report_editor_export_failed", "message": self.error}
        return payload


def _validate_masked_columns_policy(
    file: TraceDatasetFile,
    params: Mapping[str, Any],
    blocked_columns: frozenset[str] = frozenset(),
) -> tuple[list[str], str]:
    """校验掩码策略并返回最终掩码列：文件中会话受限的列一律并入（计划 5.2）。"""

    columns = params.get("columns", [])
    mask = params.get("mask", "***")
    if not isinstance(columns, (list, tuple)):
        raise ReportingError(
            "request_invalid", "masked_columns 策略必须提供非空 columns 列表。"
        )
    if len(columns) > _MAX_POLICY_COLUMNS or any(
        not isinstance(item, str) or not item for item in columns
    ):
        raise ReportingError("request_invalid", "masked_columns 策略列清单无效。")
    if not isinstance(mask, str) or not (1 <= len(mask) <= 32):
        raise ReportingError("request_invalid", "masked_columns 策略掩码文本无效。")
    header = read_csv_header(file.local_path)
    unknown = [item for item in columns if item not in header]
    if unknown:
        # 只回显请求列不存在，不泄露其余受保护字段。
        raise ReportingError(
            "request_invalid", "masked_columns 策略包含不存在的列。"
        )
    # 受限列强制掩码：派生导出不能成为读取受限列的旁路。
    forced = [name for name in header if is_blocked_column(name, blocked_columns)]
    target = list(dict.fromkeys([*columns, *forced]))
    if not target:
        raise ReportingError(
            "request_invalid", "masked_columns 策略必须提供非空 columns 列表。"
        )
    return target, mask


class TraceDerivedExportService:
    """进程内派生导出任务管理；文件落在报告 revision 的隐藏导出目录。"""

    def __init__(self, workspace: Any) -> None:
        self._workspace = workspace
        self._jobs: dict[str, TraceExportJob] = {}
        self.source_guard = None

    # ------------------------------------------------------------------
    # 任务生命周期
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        context: Any,
        file: TraceDatasetFile,
        policy: str,
        params: Mapping[str, Any],
        blocked_columns: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        self._cleanup_expired()
        if policy != "masked_columns":
            raise ReportingError(
                "request_invalid", f"未登记的导出策略代码: {policy}"
            )
        target_columns, mask = _validate_masked_columns_policy(file, params, blocked_columns)
        running = sum(1 for job in self._jobs.values() if job.status == "running")
        if running >= _MAX_DERIVED_EXPORT_JOBS:
            raise ReportingError(
                "report_editor_export_busy", "派生导出任务已达并发上限，请稍后重试。"
            )
        export_id = hashlib.sha256(
            f"{file.dataset_id}:{file.sha256}:{policy}:{time.time_ns()}".encode()
        ).hexdigest()[:24]
        job = TraceExportJob(
            export_id=export_id,
            report_id=str(context.report_id),
            revision=int(context.revision),
            dataset_id=file.dataset_id,
            policy=policy,
            params={"columns": target_columns, "mask": mask},
            source_dataset_id=file.dataset_id,
            source_sha256=file.sha256,
            workspace_path=self._export_workspace_path(context, export_id),
            thread_id=str(context.scope["threadId"]),
            created_at=time.time(),
        )
        job.task = asyncio.create_task(self._run_guarded(context, job, file, target_columns, mask))
        self._jobs[export_id] = job
        logger.info(
            "trace_derived_export_created export_id={} dataset={} policy={} columns={}",
            export_id,
            file.dataset_id,
            policy,
            len(target_columns),
        )
        return job.to_payload()

    async def status(self, context: Any, export_id: str) -> dict[str, Any]:
        job = self._owned_job(context, export_id)
        return job.to_payload()

    async def download(
        self, context: Any, export_id: str
    ) -> tuple[Path, str, int, str]:
        """返回 (本地路径, 安全文件名, 大小, sha256)；重验归属与保留期。"""

        job = self._owned_job(context, export_id)
        if job.status == "expired":
            raise ReportingError("snapshot_expired", "派生导出已超过保留期。")
        if job.status == "failed":
            raise ReportingError("report_editor_export_failed", "派生导出已失败，无法下载。")
        if job.status != "completed":
            raise ReportingError("report_editor_export_running", "派生导出尚未完成，请稍后重试。")
        workspace = self._workspace.workspace(context.scope["threadId"])
        relative = workspace.paths.normalize(job.workspace_path, allow_root=False)
        host_path = workspace.paths.to_host_path(relative, allow_root=False)
        if not host_path.is_file():
            raise ReportingError("source_missing", "派生导出文件不存在。")
        return (
            host_path,
            _derived_filename(job),
            job.size or host_path.stat().st_size,
            job.sha256 or "",
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _owned_job(self, context: Any, export_id: str) -> TraceExportJob:
        job = self._jobs.get(export_id)
        if (
            job is None
            or job.report_id != str(context.report_id)
            or job.revision != int(context.revision)
        ):
            # 不泄露其他报告的导出任务是否存在。
            raise ReportingError("source_missing", "派生导出任务不存在。")
        if job.status != "expired" and (
            (
                job.finished_at is not None
                and time.time() - job.finished_at > _RETENTION_SECONDS
            )
            or (
                job.finished_at is None
                and time.time() - job.created_at > _RETENTION_SECONDS
            )
        ):
            job.status = "expired"
            self._best_effort_delete(job)
        return job

    def _export_workspace_path(self, context: Any, export_id: str) -> str:
        from pathlib import PurePosixPath

        parent = PurePosixPath(context.markdown_path).parent
        return parent.joinpath(f".trace-exports/{export_id}.csv").as_posix()

    async def _run_guarded(self, context, job, file, target_columns, mask):
        if self.source_guard is None:
            await self._run(job, file, target_columns, mask)
            return
        try:
            async with self.source_guard(context):
                await self._run(job, file, target_columns, mask)
        except Exception as error:  # noqa: BLE001 - 守卫失败同样必须落到任务状态
            # 非 ReportingError（如状态库读取失败、锁文件打开失败）若逃出任务，状态会停在
            # running：轮询永远“生成中”、过期清理跳过 running，且持续占用并发名额。
            job.status = "failed"
            job.error = (
                error.message if isinstance(error, ReportingError) else "派生导出生成失败。"
            )
            job.finished_at = time.time()
            if not isinstance(error, ReportingError):
                logger.warning(
                    "trace_derived_export_guard_failed export_id={} error={}",
                    job.export_id,
                    error,
                )

    async def _run(
        self,
        job: TraceExportJob,
        file: TraceDatasetFile,
        target_columns: list[str],
        mask: str,
    ) -> None:
        try:
            workspace = self._workspace.workspace(job.thread_id)
            relative = workspace.paths.normalize(job.workspace_path, allow_root=False)
            host_path = workspace.paths.to_host_path(relative, allow_root=False)
            host_path.parent.mkdir(parents=True, exist_ok=True)
            await anyio.to_thread.run_sync(
                self._generate, file.local_path, host_path, target_columns, mask
            )
            content_hash = hashlib.sha256()
            size = 0
            with host_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    content_hash.update(chunk)
                    size += len(chunk)
            job.size = size
            job.sha256 = content_hash.hexdigest()
            job.status = "completed"
        except Exception as error:  # noqa: BLE001 - 任务失败必须落到状态里
            job.status = "failed"
            job.error = str(error) if isinstance(error, ReportingError) else "派生导出生成失败。"
            logger.warning(
                "trace_derived_export_failed export_id={} error={}", job.export_id, error
            )
        finally:
            job.finished_at = time.time()

    @staticmethod
    def _generate(
        source: Path, target: Path, target_columns: Sequence[str], mask: str
    ) -> None:
        # 按原文读写：类型推断会改写编码前导零、小数尾零等未掩码列。
        frame = pl.scan_csv(source, infer_schema=False).with_columns(
            [pl.lit(mask).alias(column) for column in target_columns]
        )
        frame.sink_csv(target)

    def _cleanup_expired(self) -> None:
        now = time.time()
        for job in list(self._jobs.values()):
            age = now - (job.finished_at or job.created_at)
            if job.status != "running" and age > _RETENTION_SECONDS:
                job.status = "expired"
                self._best_effort_delete(job)
                self._jobs.pop(job.export_id, None)

    def _best_effort_delete(self, job: TraceExportJob) -> None:
        async def _delete() -> None:
            try:
                await self._workspace.adelete_file(job.thread_id, job.workspace_path)
            except Exception as error:  # noqa: BLE001 - 清理失败不影响主流程
                logger.warning(
                    "trace_derived_export_cleanup_failed export_id={} error={}",
                    job.export_id,
                    error,
                )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(_delete())


def _derived_filename(job: TraceExportJob) -> str:
    base = f"{job.source_dataset_id}-derived"
    name = _UNSAFE_FILENAME_PATTERN.sub("_", base).strip("._") or job.export_id
    return f"{name[:160]}-{job.export_id[:8]}.csv"


def derived_download_filename(job: TraceExportJob) -> str:
    return _derived_filename(job)


__all__ = [
    "TraceDerivedExportService",
    "TraceExportJob",
    "safe_download_filename",
    "derived_download_filename",
]
