from __future__ import annotations

import asyncio
import hashlib
import io
import secrets
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

import anyio
import polars as pl
from agno.run import RunContext

from ..async_utils import complete_cleanup
from ..workspace import WorkspaceHashResultError, WorkspaceService, _thread
from .contract import ReportFileInput
from .data_source import DataSourceAdapter
from .models import ReportingError
from .workflow.query_pipeline import (
    ApprovedQuery,
    DatasetLineage,
    require_approved_sql,
    validate_lineage,
)

REPORT_DATASET_HANDLES_STATE_KEY = "report_dataset_handles"
MAX_REPORT_INPUTS = 100
MAX_DATASET_FILE_BYTES = 200 * 1024 * 1024
_DATASET_HASH_ATTEMPTS = 3
_DATASET_HASH_RETRY_DELAY_SECONDS = 0.2


@dataclass(frozen=True)
class DatasetHandle:
    dataset_id: str
    source_id: str
    path: str
    row_count: int
    size: int
    sha256: str
    requirement_id: str
    sql_hash: str
    source_type: Literal["starrocks_materialized", "url_csv"] = "starrocks_materialized"
    filename: str | None = None
    period_roles: tuple[Literal["current", "yoy", "mom"], ...] = ("current",)
    query_window_id: str = "current"

    def __post_init__(self) -> None:
        if (
            self.source_type not in {"starrocks_materialized", "url_csv"}
            or (self.source_type == "url_csv" and not self.filename)
            or (self.source_type == "starrocks_materialized" and self.filename is not None)
            or not self.period_roles
            or len(self.period_roles) != len(set(self.period_roles))
            or any(role not in {"current", "yoy", "mom"} for role in self.period_roles)
        ):
            raise ValueError("数据集句柄来源或 periodRoles 无效")
        if not self.query_window_id:
            raise ValueError("数据集句柄 queryWindowId 无效")

    def public_dict(self) -> dict[str, Any]:
        return {
            "datasetId": self.dataset_id,
            "sourceId": self.source_id,
            "sourceType": self.source_type,
            "path": self.path,
            "format": "csv",
            "rowCount": self.row_count,
            "size": self.size,
            "sha256": self.sha256,
            "provenance": {
                "requirementId": self.requirement_id,
                "sqlHash": self.sql_hash,
                "periodRoles": list(self.period_roles),
                "queryWindowId": self.query_window_id,
                **({"filename": self.filename} if self.filename is not None else {}),
            },
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> DatasetHandle:
        try:
            provenance = value["provenance"]
            if not isinstance(provenance, Mapping):
                raise TypeError
            raw_period_roles = provenance.get("periodRoles") or ("current",)
            if not isinstance(raw_period_roles, (list, tuple)):
                raise TypeError
            return cls(
                dataset_id=str(value["datasetId"]),
                source_id=str(value["sourceId"]),
                source_type=cast(
                    Literal["starrocks_materialized", "url_csv"],
                    str(value.get("sourceType") or "starrocks_materialized"),
                ),
                path=str(value["path"]),
                row_count=int(value["rowCount"]),
                size=int(value["size"]),
                sha256=str(value["sha256"]),
                requirement_id=str(provenance["requirementId"]),
                sql_hash=str(provenance["sqlHash"]),
                period_roles=cast(
                    tuple[Literal["current", "yoy", "mom"], ...],
                    tuple(raw_period_roles),
                ),
                query_window_id=str(provenance.get("queryWindowId") or "current"),
                filename=(
                    str(provenance["filename"]) if provenance.get("filename") is not None else None
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ReportingError("dataset_invalid", "数据集句柄无效，请重新准备。") from error


class _BatchItemError(Exception):
    def __init__(self, index: int, error: Exception):
        super().__init__(str(error))
        self.index = index
        self.error = error


class ReportDatasetStore:
    """执行已审核 SQL，并在全部查询成功后登记不可变数据集。"""

    def __init__(self, service: WorkspaceService):
        self.service = service

    async def register_external_csv(
        self,
        files: tuple[ReportFileInput, ...],
        *,
        run_context: RunContext,
    ) -> tuple[tuple[DatasetHandle, ...], tuple[DatasetLineage, ...]]:
        """校验 URL 物化文件并登记为同一批不可变补充数据集。"""

        if not files:
            return (), ()
        if len(files) > MAX_REPORT_INPUTS:
            raise ReportingError("report_attachment_count_invalid", "CSV 附件数量无效。")
        handles: list[DatasetHandle] = []
        lineages: list[DatasetLineage] = []
        thread_id = _thread(run_context)
        for index, file in enumerate(files):
            if not file.filename.lower().endswith(".csv") or file.media_type not in {
                None,
                "text/csv",
            }:
                raise ReportingError(
                    "report_attachment_type_unsupported", "Reporting URL 附件仅支持 CSV。"
                )
            current = await self.service.ahash_file(thread_id, file.path)
            if (
                current.get("missing")
                or current.get("size") != file.size
                or current.get("sha256") != file.sha256
            ):
                raise ReportingError("report_attachment_changed", "URL CSV 附件在登记前发生变化。")
            content, _media_type = await self.service.afile_bytes(thread_id, file.path)
            try:
                row_count = pl.read_csv(io.BytesIO(content)).height
            except (UnicodeDecodeError, pl.exceptions.PolarsError) as error:
                raise ReportingError(
                    "report_attachment_csv_invalid", "CSV 附件格式无效。"
                ) from error
            requirement_id = f"attachment-{index + 1:03d}"
            sql_hash = hashlib.sha256(f"url_csv:{file.sha256}".encode()).hexdigest()
            dataset_id = (
                "dataset-url-"
                + hashlib.sha256(f"{index}:{file.filename}:{file.sha256}".encode()).hexdigest()[:28]
            )
            handle = DatasetHandle(
                dataset_id=dataset_id,
                source_id="mcp-url",
                source_type="url_csv",
                path=file.path,
                row_count=row_count,
                size=file.size,
                sha256=file.sha256,
                requirement_id=requirement_id,
                sql_hash=sql_hash,
                filename=file.filename,
            )
            handles.append(handle)
            lineages.append(
                DatasetLineage(
                    datasetId=dataset_id,
                    sourceId=handle.source_id,
                    sourceType=handle.source_type,
                    requirementId=requirement_id,
                    sqlHash=sql_hash,
                    rowCount=row_count,
                    size=file.size,
                    sha256=file.sha256,
                )
            )
        completed = tuple(handles)
        self._store_handles(completed, run_context)
        return completed, tuple(lineages)

    async def materialize_batch(
        self,
        approved: tuple[ApprovedQuery, ...],
        adapters: Mapping[str, DataSourceAdapter],
        *,
        run_context: RunContext,
    ) -> tuple[tuple[DatasetHandle, ...], tuple[DatasetLineage, ...]]:
        if not approved or len(approved) > MAX_REPORT_INPUTS:
            raise ReportingError("report_query_batch_invalid", "审核 SQL 批次数量无效。")

        validated: list[tuple[ApprovedQuery, DataSourceAdapter, str]] = []
        seen_query_keys: set[tuple[str, str, str]] = set()
        for query in approved:
            query_key = (query.source_id, query.requirement_id, query.query_window_id)
            if query_key in seen_query_keys:
                raise ReportingError(
                    "report_query_duplicate_window",
                    "同一 sourceId、requirementId、queryWindowId 只能执行一次查询。",
                )
            seen_query_keys.add(query_key)
            adapter = adapters.get(query.source_id)
            if adapter is None:
                raise ReportingError("report_source_not_found", "审核 SQL 的数据源不存在。")
            sql = require_approved_sql(query, query.sql)
            validated.append((query, adapter, sql))

        workflow_run_id = str(run_context.run_id or "report")
        root = f"报表/数据集/{hashlib.sha256(workflow_run_id.encode()).hexdigest()[:24]}"
        handles: list[DatasetHandle | None] = [None] * len(validated)
        staging_paths: list[str | None] = [None] * len(validated)
        batch_id = secrets.token_hex(16)
        final_root = f"{root}/batch-{batch_id}"
        staging_root = f"{root}/.staging-{batch_id}"
        _session_state(run_context)
        thread_id = _thread(run_context)
        await self.service.aensure_directory(thread_id, root)
        try:
            await self.service.aensure_directory(thread_id, staging_root)
        except BaseException:
            await complete_cleanup(
                _best_effort_delete(self.service, thread_id, staging_root, recursive=True)
            )
            await complete_cleanup(
                _best_effort_delete(self.service, thread_id, final_root, recursive=True)
            )
            raise
        global_limiter = anyio.CapacityLimiter(
            min(item[1].config.limits.query_concurrency for item in validated)
        )
        source_limiters = {
            source_id: anyio.CapacityLimiter(adapter.config.limits.query_concurrency)
            for source_id, adapter in adapters.items()
        }

        async def materialize_one(
            index: int,
            query: ApprovedQuery,
            adapter: DataSourceAdapter,
            sql: str,
        ) -> None:
            try:
                async with global_limiter:
                    async with source_limiters[query.source_id]:
                        result = await adapter.materialize(
                            sql,
                            max_bytes=MAX_DATASET_FILE_BYTES,
                        )
                        content = result.content
                        if result.size > min(
                            MAX_DATASET_FILE_BYTES,
                            adapter.config.limits.max_bytes,
                        ):
                            raise ReportingError(
                                "query_result_too_large", "查询结果超过单文件限制。"
                            )
                        digest = hashlib.sha256(content).hexdigest()
                        dataset_id = (
                            "dataset-"
                            + hashlib.sha256(
                                f"{query.source_id}:{query.requirement_id}:"
                                f"{query.query_window_id}:{query.sql_hash}:{digest}".encode()
                            ).hexdigest()[:32]
                        )
                        path = f"{final_root}/{dataset_id}.csv"
                        staging_path = f"{staging_root}/{dataset_id}.csv"
                        await self.service.awrite_bytes(thread_id, staging_path, content)
                        handles[index] = DatasetHandle(
                            dataset_id=dataset_id,
                            path=path,
                            source_id=query.source_id,
                            requirement_id=query.requirement_id,
                            sql_hash=query.sql_hash,
                            period_roles=query.period_roles,
                            query_window_id=query.query_window_id,
                            row_count=result.row_count,
                            size=len(content),
                            sha256=digest,
                        )
                        staging_paths[index] = staging_path
            except Exception as error:
                raise _BatchItemError(index, error) from error

        try:
            async with anyio.create_task_group() as task_group:
                for index, (query, adapter, sql) in enumerate(validated):
                    task_group.start_soon(materialize_one, index, query, adapter, sql)

            completed = tuple(item for item in handles if item is not None)
            completed_staging_paths = tuple(path for path in staging_paths if path is not None)
            if len(completed) != len(validated) or len(completed_staging_paths) != len(validated):
                raise ReportingError(
                    "report_dataset_commit_failed", "数据集 staging 结果不完整。"
                )

            # 上传可以并发，但身份校验必须在所有文件落盘后串行执行。
            for item, staging_path in zip(completed, completed_staging_paths, strict=True):
                current: dict[str, Any] | None = None
                for attempt in range(_DATASET_HASH_ATTEMPTS):
                    try:
                        current = await self.service.ahash_file(thread_id, staging_path)
                    except WorkspaceHashResultError:
                        if attempt + 1 >= _DATASET_HASH_ATTEMPTS:
                            raise
                        await anyio.sleep(_DATASET_HASH_RETRY_DELAY_SECONDS * (2**attempt))
                        continue
                    break
                if current is None:
                    raise ReportingError(
                        "report_dataset_commit_failed", "数据集提交校验未返回结果。"
                    )
                if (
                    current.get("sha256") != item.sha256
                    or int(current.get("size", -1)) != item.size
                ):
                    raise ReportingError("report_dataset_commit_failed", "数据集提交校验失败。")

            lineage = tuple(
                DatasetLineage(
                    datasetId=item.dataset_id,
                    sourceId=item.source_id,
                    requirementId=item.requirement_id,
                    sqlHash=item.sql_hash,
                    rowCount=item.row_count,
                    size=item.size,
                    sha256=item.sha256,
                    periodRoles=item.period_roles,
                    queryWindowId=item.query_window_id,
                )
                for item in completed
            )
            validate_lineage(approved, lineage)
            await self.service.amove_files(thread_id, staging_root, final_root)
        # 取消也必须删除 staging/final 目录；清理完成后再保留原始取消语义。
        except BaseException as error:
            await complete_cleanup(
                _best_effort_delete(self.service, thread_id, staging_root, recursive=True)
            )
            await complete_cleanup(
                _best_effort_delete(self.service, thread_id, final_root, recursive=True)
            )
            if isinstance(error, asyncio.CancelledError):
                raise
            if not isinstance(error, Exception):
                raise
            failure = _first_batch_error(error)
            if isinstance(failure, ReportingError):
                raise failure
            raise ReportingError(
                "report_dataset_commit_failed", "数据集原子提交失败。"
            ) from failure
        await complete_cleanup(
            _best_effort_delete(self.service, thread_id, staging_root, recursive=True)
        )

        self._store_handles(completed, run_context)
        return completed, lineage

    async def resolve_dataset_paths(
        self,
        dataset_ids: Sequence[str],
        *,
        run_context: RunContext | None = None,
    ) -> list[str]:
        if isinstance(dataset_ids, (str, bytes)) or not 1 <= len(dataset_ids) <= MAX_REPORT_INPUTS:
            raise ReportingError("invalid_dataset_count", "数据集数量无效。")
        stored = _session_state(run_context).get(REPORT_DATASET_HANDLES_STATE_KEY)
        if not isinstance(stored, dict):
            raise ReportingError("dataset_not_found", "数据集状态不存在。")
        paths: list[str] = []
        binding = _thread_binding(_thread(run_context))
        for dataset_id in dataset_ids:
            raw = stored.get(dataset_id)
            if not isinstance(raw, dict) or raw.get("_threadBinding") != binding:
                raise ReportingError("dataset_not_found", "数据集不存在或不属于当前对话。")
            path = raw.get("path")
            if not isinstance(path, str):
                raise ReportingError("dataset_invalid", "数据集状态无效。")
            current = await self.service.ahash_file(_thread(run_context), path)
            if current.get("sha256") != raw.get("sha256") or current.get("size") != raw.get("size"):
                raise ReportingError("stale_dataset", "不可变数据集文件已变化。")
            paths.append(path)
        return paths

    @staticmethod
    def _store_handles(handles: tuple[DatasetHandle, ...], run_context: RunContext) -> None:
        state = _session_state(run_context)
        stored = dict(state.get(REPORT_DATASET_HANDLES_STATE_KEY) or {})
        binding = _thread_binding(_thread(run_context))
        for handle in handles:
            stored[handle.dataset_id] = {**handle.public_dict(), "_threadBinding": binding}
        state[REPORT_DATASET_HANDLES_STATE_KEY] = stored


async def _best_effort_delete(
    service: Any, thread_id: str, path: str, *, recursive: bool
) -> None:
    try:
        await service.adelete_file(thread_id, path, recursive=recursive)
    except Exception:
        pass


def _first_batch_error(error: Exception) -> Exception:
    failures: list[_BatchItemError] = []

    def collect(current: BaseException) -> None:
        if isinstance(current, _BatchItemError):
            failures.append(current)
        elif isinstance(current, BaseExceptionGroup):
            for nested in current.exceptions:
                collect(nested)

    collect(error)
    if failures:
        return min(failures, key=lambda item: item.index).error
    return error


def _session_state(run_context: RunContext | None) -> MutableMapping[str, Any]:
    if run_context is None:
        raise ReportingError("report_workflow_context_missing", "报表工作流缺少运行上下文。")
    if run_context.session_state is None:
        run_context.session_state = {}
    if not isinstance(run_context.session_state, MutableMapping):
        raise ReportingError("report_workflow_state_invalid", "报表工作流状态无效。")
    return run_context.session_state


def _thread_binding(thread_id: str) -> str:
    return hashlib.sha256(thread_id.encode()).hexdigest()
