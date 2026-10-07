"""Editor 来源读取服务（B1）：从 revision 追溯索引解析数据集并委托预览。

定位规则：索引文件 ``trace-index-v1.json`` 与 ``context.markdown_path`` 同目录
（发布链路 manifest 与正文同目录，Host 快照复制保持相对位置）。旧报告没有
索引时如实返回不可用，不猜测（计划 6.3）。

文件访问沿用 read_asset 的"登记-校验-哈希"模式：先在索引内解析
resourceId → 工作区相对路径；预览与列清单流式复制并校验 size/sha256，
再从请求内临时快照读取表头和数据，避免校验后原路径变更导致读取不一致。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

import anyio
from loguru import logger

from ..reporting.delivery.artifacts_v1 import ReportArtifactManifest
from ..reporting.workflow.checkpoint import FileIdentity
from ..reporting.models import ReportingError
from ..reporting.trace.contracts_v1 import (
    TRACE_BUDGETS_V1,
    RevisionTraceIndexV1,
    TraceFileRefV1,
    derive_resource_id,
)
from ..reporting.trace.dataset_service import (
    TraceCsvPreviewService,
    TraceDatasetFile,
    TracePreviewPage,
    TracePreviewPermissions,
    verified_dataset_snapshot,
)
from ..reporting.trace.drilldown_service import TraceDrilldownService
from ..reporting.trace.fact_service import fact_display_value
from ..reporting.trace.index_builder import TRACE_INDEX_FILENAME
from ..workspace import WorkspaceError
from .trace_exports import TraceDerivedExportService

_MAX_INDEX_BYTES = 4 * 1024 * 1024
_DRILLDOWN_TIMEOUT_SECONDS = 10.0
_DRILLDOWN_LARGE_FILE_BYTES = 64 * 1024 * 1024


class _RegisteredFile(Protocol):
    """已登记文件身份：清单产物与追溯索引文件引用都满足。"""

    @property
    def path(self) -> str: ...

    @property
    def size(self) -> int: ...

    @property
    def sha256(self) -> str: ...


def trace_index_path_for_context(markdown_path: str) -> str:
    parent = PurePosixPath(markdown_path).parent
    return parent.joinpath(TRACE_INDEX_FILENAME).as_posix()


class ReportEditorTraceService:
    def __init__(self, workspace: Any, *, cursor_secret: bytes) -> None:
        self._workspace = workspace
        self._preview = TraceCsvPreviewService(secret=cursor_secret)
        self._drilldown = TraceDrilldownService(secret=cursor_secret)
        self._drilldown_limiter = anyio.CapacityLimiter(4)
        self._drilldown_large_limiter = anyio.CapacityLimiter(1)
        self.exports = TraceDerivedExportService(workspace)

    # ------------------------------------------------------------------
    # 索引加载
    # ------------------------------------------------------------------

    async def _read_registered_file(self, context: Any, identity: _RegisteredFile, *, max_bytes: int) -> bytes:
        try:
            content = await self._workspace.read_limited_regular_file(
                context.scope["threadId"], identity.path, max_bytes=max_bytes
            )
        except (OSError, WorkspaceError) as exc:
            raise ReportingError("snapshot_integrity_failed", "登记的来源文件无法读取。") from exc
        if len(content) != identity.size or hashlib.sha256(content).hexdigest() != identity.sha256:
            raise ReportingError("snapshot_integrity_failed", "来源文件与登记身份不一致。")
        return content

    async def load_manifest(self, context: Any) -> ReportArtifactManifest | None:
        identity = getattr(context, "artifact_manifest", None)
        if identity is None:
            return None
        content = await self._read_registered_file(context, identity, max_bytes=_MAX_INDEX_BYTES)
        try:
            manifest = ReportArtifactManifest.model_validate_json(content)
        except ValueError as exc:
            raise ReportingError("snapshot_integrity_failed", "修订产物清单无法解析。") from exc
        if (
            manifest.report_id != str(context.report_id)
            or manifest.revision != int(context.revision)
            or manifest.markdown.path != context.markdown_path
        ):
            raise ReportingError("snapshot_integrity_failed", "修订产物清单与当前报告不匹配。")
        return manifest

    async def load_index(self, context: Any) -> RevisionTraceIndexV1 | None:
        manifest = await self.load_manifest(context)
        if manifest is None or manifest.trace_index is None:
            return None
        content = await self._read_registered_file(
            context, manifest.trace_index, max_bytes=_MAX_INDEX_BYTES
        )
        try:
            index = RevisionTraceIndexV1.model_validate_json(content)
        except ValueError:
            raise ReportingError(
                "snapshot_integrity_failed", "修订追溯索引无法解析。"
            ) from None
        markdown_id = derive_resource_id(context.markdown_path)
        markdown_file = next((file for file in index.files if file.resource_id == markdown_id), None)
        if (
            markdown_file is None
            or markdown_file.size != manifest.markdown.size
            or markdown_file.sha256 != manifest.markdown.sha256
            or index.report_id != str(context.report_id)
            or index.revision != int(context.revision)
            or index.workflow_run_id != str(context.workflow_run_id)
            or index.markdown_file_resource_id != markdown_id
        ):
            raise ReportingError(
                "snapshot_integrity_failed", "修订追溯索引与当前报告不匹配。"
            )
        return index

    # ------------------------------------------------------------------
    # 来源概览
    # ------------------------------------------------------------------

    async def sources(
        self,
        context: Any,
        session_capabilities: Mapping[str, Any] | None = None,
        *,
        analysis_context_file: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        index = await self.load_index(context)
        if index is None:
            return {
                "available": False,
                "reason": "source_index_missing",
                "datasets": [],
            }
        files = {item.resource_id: item for item in index.files}
        field_labels: dict[tuple[str, str], str] = {}
        if analysis_context_file is not None:
            try:
                raw_context = await self._read_registered_file(
                    context, FileIdentity.model_validate(analysis_context_file), max_bytes=_MAX_INDEX_BYTES
                )
                analysis_context = json.loads(raw_context)
                for dataset_context in analysis_context.get("datasetContexts", ()):
                    dataset_id = dataset_context.get("datasetId")
                    dataset = next((item for item in index.datasets if item.dataset_id == dataset_id), None)
                    # 字段说明只用于相同字节身份的已登记快照，不能拿新数据的口径给旧事实命名。
                    if dataset is None or dataset_context.get("sha256") != files[dataset.file_resource_id].sha256:
                        continue
                    schema = dataset_context.get("schema", {})
                    for table in schema.get("tables", ()):
                        for column in table.get("columns", ()):
                            description = column.get("description")
                            if not isinstance(description, str) or not description.strip():
                                continue
                            ref = ".".join(str(value) for value in (
                                table.get("sourceId") or schema.get("sourceId"), table.get("database"), table.get("name"), column.get("name")
                            ))
                            field_labels[(dataset_id, ref)] = description.strip()
            except (ReportingError, ValueError, TypeError, AttributeError):
                logger.warning("facts_display_context_unavailable report={} revision={}", context.report_id, context.revision)
        datasets = []
        for dataset in index.datasets:
            file_ref = files[dataset.file_resource_id]
            datasets.append(
                {
                    "datasetId": dataset.dataset_id,
                    "sourceType": dataset.source_type,
                    "requirementId": dataset.requirement_id,
                    "filename": dataset.filename,
                    "businessLabel": dataset.business_label,
                    "sqlHash": dataset.sql_hash,
                    "querySql": dataset.query_sql,
                    "rowCount": dataset.row_count,
                    "size": file_ref.size,
                    "materializedAt": dataset.materialized_at,
                    "periodRoles": list(dataset.period_roles),
                    "queryWindowId": dataset.query_window_id,
                }
            )
        facts = []
        registered_dataset_ids = {item.dataset_id for item in index.datasets}
        for entry in index.fact_files:
            if entry.content_kind != "deterministic_bundle":
                continue
            raw = await self._read_registered_file(
                context, files[entry.file_resource_id], max_bytes=16 * 1024 * 1024
            )
            document = json.loads(raw)
            for kind, key in (
                ("metric", "metrics"), ("comparison", "comparisons"),
                ("derived", "derivedMetrics"), ("reconciliation", "reconciliations"),
                ("correlation", "correlationDetails"),
            ):
                for fact in document.get(key, ()):
                    if not fact.get("factId"):
                        continue
                    dataset_ids = list(dict.fromkeys(
                        dataset_id for dataset_id in (
                            *(fact.get(field) for field in ("datasetId", "currentDatasetId", "baselineDatasetId")),
                            *fact.get("datasetIds", ()),
                        ) if dataset_id in registered_dataset_ids
                    ))
                    name = fact.get("field") or fact.get("code") or (
                        f'{fact["leftField"]} / {fact["rightField"]}' if kind == "correlation" else None
                    ) or fact.get("fieldRef") or fact["factId"]
                    descriptions = {field_labels[(dataset_id, fact.get("fieldRef"))] for dataset_id in dataset_ids
                        if (dataset_id, fact.get("fieldRef")) in field_labels}
                    if len(descriptions) == 1:
                        name = descriptions.pop()
                    roles = fact.get("periodRoles") or ([fact["periodRole"]] if fact.get("periodRole") else [])
                    facts.append({
                        "analysisId": entry.analysis_id,
                        "factId": fact["factId"],
                        "factKind": kind,
                        "label": " · ".join(str(value) for value in (
                            {"metric": "指标", "comparison": "对比", "derived": "派生指标",
                             "reconciliation": "核对", "correlation": "相关性"}[kind],
                            name,
                            {"yoy": "同比", "mom": "环比"}.get(fact.get("comparisonType"), fact.get("comparisonType")),
                            " / ".join({"current": "本期", "yoy": "同比基期", "mom": "环比基期"}.get(role, role) for role in roles),
                            " — ".join(dict.fromkeys(value for value in (fact.get("periodStart"), fact.get("periodEnd")) if value)),
                        ) if value),
                        "name": name,
                        "periodStart": fact.get("periodStart"),
                        "periodEnd": fact.get("periodEnd"),
                        "periodRoles": roles,
                        "comparisonType": fact.get("comparisonType"),
                        "displayValue": fact_display_value(fact),
                        "unit": fact.get("unit"),
                        "datasetIds": dataset_ids,
                    })
        drilldown_enabled = self._drilldown_enabled(session_capabilities)
        allowed_declarations = (
            tuple(
                item
                for item in index.drilldown_metrics
                if self._drilldown_declaration_allowed(item, session_capabilities)
            )
            if drilldown_enabled
            else ()
        )
        drilldowns_by_fact: dict[str, list[Any]] = {}
        for declaration in allowed_declarations:
            for fact_key in declaration.fact_keys:
                drilldowns_by_fact.setdefault(fact_key, []).append(declaration)
        subject_drilldowns = []
        for subject in index.subject_bindings:
            declarations = {
                (item.metric_code, item.dataset_id): item
                for ref in subject.fact_refs
                for item in drilldowns_by_fact.get(ref.fact_key or "", ())
            }
            if declarations:
                subject_drilldowns.append(
                    {
                        "subjectId": subject.subject_id,
                        "metrics": [
                            self._drilldown_declaration_payload(item)
                            for item in declarations.values()
                        ],
                    }
                )
        return {
            "available": True,
            "reason": None,
            "version": index.version,
            "reportId": index.report_id,
            "revision": index.revision,
            "datasets": datasets,
            "facts": facts,
            "subjects": [
                {
                    "subjectId": subject.subject_id,
                    "subjectKind": subject.subject_kind,
                    "locator": subject.locator.model_dump(mode="json", by_alias=True),
                    "factRefs": [
                        {
                            "analysisId": ref.analysis_id,
                            "factId": ref.fact_key,
                        }
                        for ref in subject.fact_refs
                    ],
                    "computationId": subject.computation_id,
                }
                for subject in index.subject_bindings
            ],
            "drilldown": {
                "enabled": drilldown_enabled,
                "metrics": [
                    self._drilldown_declaration_payload(item)
                    for item in allowed_declarations
                ],
                "subjects": subject_drilldowns,
            },
        }

    async def drilldown_metric(
        self,
        context: Any,
        session_capabilities: Mapping[str, Any] | None,
        metric_code: str,
        *,
        dataset_id: str,
        dimension_code: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not self._drilldown_enabled(session_capabilities):
            raise ReportingError(
                "dataset_access_denied", "当前会话无权执行快照下钻。"
            )
        index = await self.require_index(context)
        declaration = next(
            (
                item
                for item in index.drilldown_metrics
                if item.metric_code == metric_code and item.dataset_id == dataset_id
            ),
            None,
        )
        if declaration is None:
            raise ReportingError(
                "drilldown_unavailable", "当前修订没有登记所选指标的下钻能力。"
            )
        return await self._execute_drilldown(
            context,
            index,
            declaration,
            session_capabilities,
            dimension_code=dimension_code,
            limit=limit,
            cursor=cursor,
        )

    async def drilldown(
        self,
        context: Any,
        session_capabilities: Mapping[str, Any] | None,
        subject_id: str,
        *,
        metric_code: str,
        dataset_id: str,
        dimension_code: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not self._drilldown_enabled(session_capabilities):
            raise ReportingError(
                "dataset_access_denied", "当前会话无权执行快照下钻。"
            )
        index = await self.require_index(context)
        subject = next(
            (item for item in index.subject_bindings if item.subject_id == subject_id),
            None,
        )
        if subject is None:
            raise ReportingError("source_missing", "对象不在当前修订的来源索引中。")
        fact_keys = {ref.fact_key for ref in subject.fact_refs if ref.fact_key}
        declaration = next(
            (
                item
                for item in index.drilldown_metrics
                if item.metric_code == metric_code
                and item.dataset_id == dataset_id
                and fact_keys.intersection(item.fact_keys)
            ),
            None,
        )
        if declaration is None:
            raise ReportingError(
                "drilldown_unavailable", "该对象没有登记所选指标的下钻能力。"
            )
        return await self._execute_drilldown(
            context,
            index,
            declaration,
            session_capabilities,
            dimension_code=dimension_code,
            limit=limit,
            cursor=cursor,
        )

    async def _execute_drilldown(
        self,
        context: Any,
        index: RevisionTraceIndexV1,
        declaration: Any,
        session_capabilities: Mapping[str, Any] | None,
        *,
        dimension_code: str,
        limit: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        if not self._drilldown_declaration_allowed(declaration, session_capabilities):
            raise ReportingError(
                "dataset_access_denied", "当前会话无权读取该下钻所需字段。"
            )
        file = await self._resolve_dataset_file(
            context, index, declaration.dataset_id
        )
        limiter = (
            self._drilldown_large_limiter
            if file.size >= _DRILLDOWN_LARGE_FILE_BYTES
            else self._drilldown_limiter
        )
        try:
            with anyio.fail_after(_DRILLDOWN_TIMEOUT_SECONDS):
                page = await anyio.to_thread.run_sync(
                    lambda: self._drilldown.drilldown(
                        file,
                        declaration,
                        dimension_code=dimension_code,
                        report_id=str(context.report_id),
                        revision=int(context.revision),
                        limit=limit,
                        cursor=cursor,
                    ),
                    abandon_on_cancel=True,
                    limiter=limiter,
                )
        except TimeoutError as error:
            raise ReportingError(
                "resource_limit_exceeded", "下钻计算超时，请稍后重试。"
            ) from error
        return page.to_payload()

    # ------------------------------------------------------------------
    # 预览与下载
    # ------------------------------------------------------------------

    async def preview(
        self,
        context: Any,
        session_capabilities: Mapping[str, Any] | None,
        dataset_id: str,
        *,
        columns: Sequence[str] | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> TracePreviewPage:
        index = await self.require_index(context)
        file = await self._resolve_dataset_file(context, index, dataset_id, verify=False)

        def read_preview() -> TracePreviewPage:
            with verified_dataset_snapshot(file) as snapshot:
                return self._preview.preview(
                    snapshot,
                    self._permissions(session_capabilities),
                    columns=columns,
                    limit=limit,
                    cursor=cursor,
                    report_id=str(context.report_id),
                    revision=int(context.revision),
                )

        return await anyio.to_thread.run_sync(read_preview)

    async def columns(
        self,
        context: Any,
        session_capabilities: Mapping[str, Any] | None,
        dataset_id: str,
    ) -> dict[str, Any]:
        index = await self.require_index(context)
        file = await self._resolve_dataset_file(context, index, dataset_id, verify=False)

        def read_columns() -> tuple[list[str], bool]:
            with verified_dataset_snapshot(file) as snapshot:
                return self._preview.visible_columns(
                    snapshot, self._permissions(session_capabilities)
                )

        visible, restricted = await anyio.to_thread.run_sync(read_columns)
        return {
            "datasetId": file.dataset_id,
            "columns": visible,
            "restricted": restricted,
            "maxColumnsPerPage": TRACE_BUDGETS_V1["preview_max_columns"],
        }

    async def download(
        self,
        context: Any,
        session_capabilities: Mapping[str, Any] | None,
        dataset_id: str,
    ) -> tuple[Path, str, int]:
        index = await self.require_index(context)
        file = await self._resolve_dataset_file(context, index, dataset_id)
        path, filename = self._preview.download_target(
            file, self._permissions(session_capabilities)
        )
        return path, filename, file.size

    async def create_derived_export(
        self,
        context: Any,
        session_capabilities: Mapping[str, Any] | None,
        dataset_id: str,
        policy: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        permissions = self._permissions(session_capabilities)
        if not permissions.can_download_derived:
            raise ReportingError(
                "dataset_access_denied", "当前会话无权创建派生导出。"
            )
        index = await self.require_index(context)
        file = await self._resolve_dataset_file(context, index, dataset_id)
        return await self.exports.create(
            context=context,
            file=file,
            policy=policy,
            params=params,
            blocked_columns=permissions.blocked_columns,
        )

    async def derived_export_status(
        self, context: Any, export_id: str
    ) -> dict[str, Any]:
        return await self.exports.status(context, export_id)

    async def derived_export_download(
        self,
        context: Any,
        session_capabilities: Mapping[str, Any] | None,
        export_id: str,
    ) -> tuple[Path, str, int]:
        if not self._permissions(session_capabilities).can_download_derived:
            raise ReportingError(
                "dataset_access_denied", "当前会话无权下载派生导出。"
            )
        path, filename, size, _sha256 = await self.exports.download(context, export_id)
        return path, filename, size

    async def require_index(self, context: Any) -> RevisionTraceIndexV1:
        index = await self.load_index(context)
        if index is None:
            raise ReportingError(
                "source_missing", "当前修订没有可用的来源索引。"
            )
        return index

    # ------------------------------------------------------------------
    # 事实查询（B2）
    # ------------------------------------------------------------------

    async def facts(self, context: Any) -> dict[str, Any]:
        """当前 revision 登记的事实文件与分析清单（不展开条目内容）。"""

        index = await self.require_index(context)
        files = {item.resource_id: item for item in index.files}
        return {
            "available": True,
            "analyses": [
                {
                    "analysisId": entry.analysis_id,
                    "contentKind": entry.content_kind,
                    "fileSize": files[entry.file_resource_id].size,
                }
                for entry in index.fact_files
            ],
        }

    async def fact_detail(
        self,
        context: Any,
        analysis_id: str,
        fact_id: str,
    ) -> dict[str, Any]:
        """按 (analysisId, factId) 解析具体事实与一层输入（计划 5.1）。

        bundle 从索引登记的冻结文件读取并复核身份；factId 在四类数组中
        唯一定位，未知即 fact_binding_unavailable。
        """

        from ..reporting.trace.contracts_v1 import FactRefV1, derive_resource_id
        from ..reporting.trace.fact_service import resolve_fact

        index = await self.require_index(context)
        entry = next(
            (item for item in index.fact_files if item.analysis_id == analysis_id),
            None,
        )
        if entry is None:
            raise ReportingError("source_missing", "分析不在当前修订的事实索引中。")
        file_ref = next(
            (item for item in index.files if item.resource_id == entry.file_resource_id),
            None,
        )
        if file_ref is None:
            raise ReportingError(
                "snapshot_integrity_failed", "事实文件登记不完整。"
            )
        # 校验与解析必须针对同一份字节：先哈希再另读会留下文件被替换的窗口。
        bundle_bytes = await self._read_registered_file(
            context, file_ref, max_bytes=16 * 1024 * 1024
        )
        pointer = self._locate_fact_pointer(bundle_bytes, fact_id)
        fact_ref = FactRefV1(
            analysisId=analysis_id,
            fileResourceId=derive_resource_id(file_ref.path),
            jsonPointer=pointer,
            factKind=self._pointer_kind(pointer),
            factKey=fact_id,
        )
        return resolve_fact(bundle_bytes, fact_ref, with_inputs=True)

    @staticmethod
    def _locate_fact_pointer(bundle_bytes: bytes, fact_id: str) -> str:
        try:
            import json as _json

            document = _json.loads(bundle_bytes)
        except (ValueError, UnicodeDecodeError):
            raise ReportingError(
                "snapshot_integrity_failed", "事实文件无法解析。"
            ) from None
        # 与 fact_index 的 factId 分配范围一致：相关性事实同样进入正文引用的事实目录。
        for array_name, prefix in (
            ("metrics", "/metrics/"),
            ("comparisons", "/comparisons/"),
            ("derivedMetrics", "/derivedMetrics/"),
            ("reconciliations", "/reconciliations/"),
            ("correlationDetails", "/correlationDetails/"),
        ):
            for index, item in enumerate(document.get(array_name, ()) or ()):
                if isinstance(item, dict) and item.get("factId") == fact_id:
                    return f"{prefix}{index}"
        raise ReportingError("fact_binding_unavailable", "事实 ID 不在该分析中。")

    # ------------------------------------------------------------------
    # 正文 subject 校验（B6）
    # ------------------------------------------------------------------

    async def validate(
        self,
        context: Any,
        markdown: str,
        draft_sha256: str,
    ) -> dict[str, Any]:
        """按 ``[[claim:id]]`` 协议标记判定正文 subject 状态（计划 6.1）。

        标记被删 → unbound；标记附近找不到生成时事实值 → stale（软语义，
        提示复核，不拒绝保存）；命中 → valid。响应绑定请求的草稿 sha，
        前端据此丢弃过期响应。
        """

        import hashlib
        import json as _json

        from ..reporting.delivery.artifacts_v1 import _TABLE_BLOCK
        from ..reporting.trace.subject_builder import (
            claim_status,
            value_matches,
        )

        actual_draft_sha256 = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        if actual_draft_sha256 != draft_sha256:
            raise ReportingError(
                "request_invalid", "草稿摘要与正文内容不一致，已拒绝校验。"
            )

        index = await self.require_index(context)
        files = {item.resource_id: item for item in index.files}
        thread_id = context.scope["threadId"]
        bundle_cache: dict[str, Any] = {}

        async def _fact_entry_of(ref: Any) -> dict[str, Any] | None:
            file_ref = files.get(ref.file_resource_id)
            if file_ref is None:
                raise ReportingError("snapshot_integrity_failed", "事实文件登记不完整。")
            if file_ref.path not in bundle_cache:
                try:
                    content = await self._workspace.read_limited_regular_file(
                        thread_id, file_ref.path, max_bytes=16 * 1024 * 1024
                    )
                except (OSError, WorkspaceError) as exc:
                    raise ReportingError("snapshot_integrity_failed", "事实文件无法读取。") from exc
                if len(content) != file_ref.size or hashlib.sha256(content).hexdigest() != file_ref.sha256:
                    raise ReportingError("snapshot_integrity_failed", "事实文件与登记身份不一致。")
                try:
                    bundle_cache[file_ref.path] = _json.loads(content)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ReportingError("snapshot_integrity_failed", "事实文件无法解析。") from exc
            document = bundle_cache[file_ref.path]
            if not isinstance(document, dict):
                return None
            try:
                prefix, index_token = ref.json_pointer.rsplit("/", 1)
                array_name = {
                    "/metrics": "metrics",
                    "/comparisons": "comparisons",
                    "/derivedMetrics": "derivedMetrics",
                    "/reconciliations": "reconciliations",
                    "/correlationDetails": "correlationDetails",
                }.get(prefix)
                if array_name is None or not index_token.isdigit():
                    return None
                array = document.get(array_name)
                position = int(index_token)
                if not isinstance(array, list) or position >= len(array):
                    return None
                entry = array[position]
                return entry if isinstance(entry, dict) else None
            except (ValueError, TypeError):
                return None

        def _entry_value(entry: dict[str, Any] | None) -> Any:
            if not entry:
                return None
            for key in ("total", "percentage", "value", "change", "difference"):
                if entry.get(key) is not None:
                    return entry[key]
            return None

        def _entry_formula(entry: dict[str, Any] | None) -> str | None:
            value = entry.get("formula") if entry else None
            return value if isinstance(value, str) and value else None

        def _entry_scope(entry: dict[str, Any] | None) -> dict[str, str]:
            scope = entry.get("scope") if entry else None
            if not isinstance(scope, dict):
                return {}
            return {
                str(key): str(value)
                for key, value in scope.items()
                if isinstance(key, str) and isinstance(value, str)
            }

        def _entry_dataset_ids(entry: dict[str, Any] | None) -> list[str]:
            if not entry:
                return []
            dataset_ids: list[str] = []
            for key in ("datasetId", "currentDatasetId", "baselineDatasetId"):
                value = entry.get(key)
                if isinstance(value, str) and value not in dataset_ids:
                    dataset_ids.append(value)
            values = entry.get("datasetIds")
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, str) and value not in dataset_ids:
                        dataset_ids.append(value)
            return dataset_ids

        async def _fact_value_of(ref: Any) -> Any:
            return _entry_value(await _fact_entry_of(ref))

        subjects: list[dict[str, Any]] = []
        summary = {"valid": 0, "stale": 0, "unbound": 0}
        for binding in index.subject_bindings:
            if not binding.claim_id or not binding.fact_refs:
                continue
            entry: dict[str, Any] | None = None
            for ref in binding.fact_refs:
                entry = await _fact_entry_of(ref)
                if _entry_value(entry) is not None:
                    break
            fact_value = _entry_value(entry)
            expected_unit = (
                str(entry["unit"])
                if entry and isinstance(entry.get("unit"), str) and entry.get("unit")
                else None
            )
            expected_periods = tuple(
                str(item["period"])
                for item in (entry.get("periodValues") or ()) if isinstance(item, dict) and item.get("period")
            ) if entry else ()
            detail = claim_status(
                markdown,
                binding.claim_id,
                fact_value,
                expected_unit=expected_unit,
                expected_periods=expected_periods,
                expected_scope=_entry_scope(entry),
            )
            status = detail["status"]
            summary[status] += 1
            subjects.append(
                {
                    "subjectId": binding.subject_id,
                    "claimId": binding.claim_id,
                    "sectionId": binding.locator.section_id,
                    "status": status,
                    "factValue": fact_value,
                    "warnings": detail["warnings"],
                    "draftValue": detail.get("draftValue"),
                    "draftUnit": detail.get("draftUnit"),
                    "draftPeriods": detail.get("draftPeriods"),
                    "comparable": detail.get("comparable", False),
                    # B8 导出来源附录的冻结摘要字段：单位、期间、公式、范围与
                    # 数据集身份都取自事实登记，不从草稿反推。
                    "unit": expected_unit,
                    "periods": list(expected_periods),
                    "formula": _entry_formula(entry),
                    "scope": _entry_scope(entry),
                    "datasetIds": _entry_dataset_ids(entry),
                }
            )

        tables_payload, table_summary = await self._evaluate_tables(
            index, context, markdown, _fact_value_of, _TABLE_BLOCK, value_matches
        )
        for table, payload in zip(index.tables, tables_payload, strict=True):
            dataset_ids: list[str] = []
            methods: list[str] = []
            for cell in table.cells:
                for dataset_id in cell.dataset_ids:
                    if dataset_id not in dataset_ids:
                        dataset_ids.append(dataset_id)
                for ref in cell.fact_refs:
                    entry = await _fact_entry_of(ref)
                    for dataset_id in _entry_dataset_ids(entry):
                        if dataset_id not in dataset_ids:
                            dataset_ids.append(dataset_id)
                    formula = _entry_formula(entry)
                    if formula and formula not in methods:
                        methods.append(formula)
            payload.update(datasetIds=dataset_ids, methods=methods)
        if any(chart.presentation_sha256 is None for chart in index.chart_traces):
            from ..reporting.trace.chart_subjects import freeze_chart_presentations

            file = files[index.markdown_file_resource_id]
            committed = await self._read_registered_file(context, file, max_bytes=16 * 1024 * 1024)
            index = freeze_chart_presentations(index, committed.decode("utf-8"))
        charts_payload = self._evaluate_charts(index, markdown)
        return {
            "draftSha256": draft_sha256,
            "subjects": subjects,
            "summary": summary,
            "tables": tables_payload,
            "tableSummary": table_summary,
            "charts": charts_payload,
        }

    @staticmethod
    def _evaluate_charts(index: Any, draft_markdown: str) -> list[dict[str, Any]]:
        """图表唯一定位；图题/紧邻图注变化给出软语义 stale。"""
        from ..reporting.trace.chart_subjects import chart_fingerprints, chart_presentations

        charts: list[dict[str, Any]] = []
        files = {item.resource_id: item for item in index.files}
        presentations = chart_presentations(draft_markdown)
        for trace in index.chart_traces:
            image = files.get(trace.image_file_resource_id)
            unique_name = image is not None and sum(
                PurePosixPath(files[item.image_file_resource_id].path).name == PurePosixPath(image.path).name
                for item in index.chart_traces
            ) == 1
            fingerprints = chart_fingerprints(presentations, image.path, allow_filename=unique_name) if image else []
            status = "unbound" if len(fingerprints) != 1 else (
                "valid" if fingerprints[0] == trace.presentation_sha256 else "stale"
            )
            location_source = None
            if image is not None and len(fingerprints) == 1:
                allowed_paths = {image.path, PurePosixPath(image.path).name} if unique_name else {image.path}
                location_source = next(path for path in presentations if path in allowed_paths)
            charts.append(
                {
                    "chartId": trace.chart_id,
                    "imagePath": image.path if image is not None else None,
                    "status": status,
                    "locationSource": location_source,
                }
            )
        return charts

    async def _evaluate_tables(
        self,
        index: Any,
        context: Any,
        draft_markdown: str,
        fact_value_of: Any,
        table_block_pattern: Any,
        value_matches: Any,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """表格身份重判（计划 6.1）：排序不失效，改值 stale，插删行/删块 unbound。

        行标签→rowKey 的映射来自当前 revision 已提交正文（与 TableTraceV1
        同源生成的表格块）；列按草稿表头文本 == columnKey 定位，表头被改
        即无法定位 → stale。全部为软语义，不阻断保存。
        """

        committed = None
        try:
            committed_bytes = await self._workspace.read_limited_regular_file(
                context.scope["threadId"],
                context.markdown_path,
                max_bytes=16 * 1024 * 1024,
            )
            committed = committed_bytes.decode("utf-8")
        except (OSError, WorkspaceError, UnicodeDecodeError):
            committed = None

        def _blocks(source: str | None) -> dict[str, str]:
            if not source:
                return {}
            return {
                match.group(1): match.group(2)
                for match in table_block_pattern.finditer(source)
            }

        def _rows(body: str) -> tuple[list[str], list[list[str]]]:
            from markdown_it import MarkdownIt

            parser = MarkdownIt()

            def cell_text(value: str) -> str:
                # 编辑器的转义与强调只改变 Markdown 表达，不改变冻结行列标签。
                tokens = parser.parseInline(value.strip())
                return "".join(
                    child.content for token in tokens for child in (token.children or ())
                    if child.type in {"text", "code_inline"}
                ).strip()

            lines = [line for line in body.split("\n") if line.startswith("|")]
            if len(lines) < 3:
                return [], []
            header = [cell_text(cell) for cell in lines[0].strip().strip("|").split("|")]
            data = [
                [cell_text(cell) for cell in line.strip().strip("|").split("|")]
                for line in lines[2:]
            ]
            return header[1:], data

        committed_blocks = _blocks(committed)
        draft_blocks = _blocks(draft_markdown)
        results: list[dict[str, Any]] = []
        summary = {
            "valid": 0,
            "stale": 0,
            "unbound": 0,
            "insertedRows": 0,
            "copiedCells": 0,
        }
        for trace in index.tables:
            counts = {"valid": 0, "stale": 0, "unbound": 0}
            locations: list[dict[str, Any]] = []
            inserted_rows = 0
            copied_cells: list[dict[str, Any]] = []
            origin_body = committed_blocks.get(trace.table_id)
            draft_body = draft_blocks.get(trace.table_id)
            if draft_body is None:
                counts["unbound"] = len(trace.cells)
            else:
                _header, origin_rows = _rows(origin_body or "")
                if len(origin_rows) == len(trace.row_keys):
                    label_to_key = {
                        row[0]: key for row, key in zip(origin_rows, trace.row_keys)
                    }
                else:
                    label_to_key = {}
                draft_header, draft_rows = _rows(draft_body)
                # 定位比软校验更保守：重复标签/列名不能选择首个匹配冒充唯一身份。
                # 已提交正文读取失败（committed 为 None）时视为非唯一，只做软校验、不给定位。
                unique_block = all(
                    sum(match.group(1) == trace.table_id for match in table_block_pattern.finditer(markdown)) == 1
                    for markdown in (committed or "", draft_markdown)
                )
                origin_labels = [row[0] for row in origin_rows if row]
                draft_labels = [row[0] for row in draft_rows if row]
                column_index = {
                    name: position + 1 for position, name in enumerate(draft_header)
                }
                row_by_key: dict[str, list[str]] = {}
                copy_rows: list[list[str]] = []
                for row in draft_rows:
                    key = label_to_key.get(row[0]) if row else None
                    # 已知标签的首个出现按冻结行键映射；未知标签或重复标签
                    # （复制行）进入复制候选，逐格细分提示，不静默覆盖首行。
                    if key is None or key in row_by_key:
                        copy_rows.append(row)
                        if key is None:
                            summary["insertedRows"] += 1
                            inserted_rows += 1
                    else:
                        row_by_key[key] = row
                frozen_values: list[tuple[Any, Any]] = []
                for cell in trace.cells:
                    value: Any = None
                    for ref in cell.fact_refs:
                        value = await fact_value_of(ref)
                        if value is not None:
                            break
                    frozen_values.append((cell, value))
                for cell in trace.cells:
                    row = row_by_key.get(cell.row_key)
                    if row is None:
                        counts["unbound"] += 1
                        continue
                    column = column_index.get(cell.column_key)
                    if column is None or column >= len(row):
                        counts["stale"] += 1
                        continue
                    fact_value: Any = None
                    for frozen_cell, frozen_value in frozen_values:
                        if frozen_cell is cell:
                            fact_value = frozen_value
                            break
                    cell_status = (
                        "valid" if fact_value is not None and value_matches(row[column], fact_value) else "stale"
                    )
                    if (unique_block and origin_labels.count(row[0]) == 1
                            and draft_labels.count(row[0]) == 1
                            and draft_header.count(cell.column_key) == 1
                            and len(row) == len(draft_header) + 1):
                        locations.append({
                            "rowKey": cell.row_key, "columnKey": cell.column_key,
                            "rowIndex": draft_rows.index(row), "columnIndex": column,
                            "rowLabel": row[0], "text": row[column], "status": cell_status,
                        })
                    counts[cell_status] += 1
                # 复制单元格细分：新格文本与某冻结单元格事实值一致时给出
                # 候选绑定提示（软语义提示，不自动赋绑定身份）。
                for row in copy_rows:
                    for column in range(1, len(row)):
                        cell_text = row[column]
                        if not cell_text or cell_text == "—":
                            continue
                        matches = [
                            {
                                "rowKey": frozen_cell.row_key,
                                "columnKey": frozen_cell.column_key,
                                "factKey": (
                                    frozen_cell.fact_refs[0].fact_key
                                    if frozen_cell.fact_refs
                                    else None
                                ),
                            }
                            for frozen_cell, frozen_value in frozen_values
                            if frozen_value is not None
                            and value_matches(cell_text, frozen_value)
                        ]
                        if not matches:
                            continue
                        summary["copiedCells"] += 1
                        copied_cells.append(
                            {
                                "rowLabel": row[0],
                                "columnKey": (
                                    draft_header[column - 1]
                                    if column - 1 < len(draft_header)
                                    else None
                                ),
                                "text": cell_text,
                                "matches": matches[:5],
                            }
                        )
            for key in ("valid", "stale", "unbound"):
                summary[key] += counts[key]
            results.append(
                {
                    "tableId": trace.table_id,
                    "cells": counts,
                    "copiedCells": copied_cells,
                    "insertedRows": inserted_rows,
                    "locations": locations,
                }
            )
        return results, summary

    # ------------------------------------------------------------------
    # 计算链（B4 第二增量）
    # ------------------------------------------------------------------

    async def computations(self, context: Any) -> dict[str, Any]:
        """当前 revision 登记的补充分析计算记录清单（轻量元数据）。"""

        index = await self.require_index(context)
        files = {item.resource_id: item for item in index.files}
        return {
            "available": True,
            "computations": [
                {
                    "computationId": record.computation_id,
                    "method": record.method,
                    "methodVersion": record.method_version,
                    "executionId": record.execution_id,
                    "verification": record.verification,
                    "reproducibility": record.reproducibility,
                    "inputDatasetCount": len(record.input_dataset_ids),
                    "outputFactCount": len(record.output_fact_refs),
                    "scriptSize": (
                        files[record.script_file_resource_id].size
                        if record.script_file_resource_id in files
                        else None
                    ),
                    "limitations": list(record.limitations),
                }
                for record in index.computations
            ],
        }

    async def computation_detail(
        self,
        context: Any,
        computation_id: str,
        *,
        depth: int = 2,
    ) -> dict[str, Any]:
        """计算记录详情 + 依赖链展开（计划 4.3/B4-5：查看不触发执行或重查）。"""

        from ..reporting.trace.computation_service import expand_computation_chain

        index = await self.require_index(context)
        record = next(
            (item for item in index.computations if item.computation_id == computation_id),
            None,
        )
        if record is None:
            raise ReportingError("source_missing", "计算记录不在当前修订的来源索引中。")
        files = {item.resource_id: item for item in index.files}
        chain = expand_computation_chain(index.computations, computation_id, depth=depth)
        environment = (
            dict(record.environment) if isinstance(record.environment, Mapping) else None
        )
        return {
            "available": True,
            "computationId": record.computation_id,
            "method": record.method,
            "methodVersion": record.method_version,
            "parameters": dict(record.parameters),
            "preprocessing": list(record.preprocessing),
            "executionId": record.execution_id,
            "environment": environment,
            "verification": record.verification,
            "reproducibility": record.reproducibility,
            "limitations": list(record.limitations),
            "inputDatasetIds": list(record.input_dataset_ids),
            "inputFactRefs": [
                {
                    "analysisId": ref.analysis_id,
                    "factKey": ref.fact_key,
                    "factKind": ref.fact_kind,
                }
                for ref in record.input_fact_refs
            ],
            "outputFactRefs": [
                {
                    "analysisId": ref.analysis_id,
                    "factKey": ref.fact_key,
                    "factKind": ref.fact_kind,
                    "jsonPointer": ref.json_pointer,
                }
                for ref in record.output_fact_refs
            ],
            "scriptFile": (
                {"size": files[record.script_file_resource_id].size, "sha256": files[record.script_file_resource_id].sha256}
                if record.script_file_resource_id in files
                else None
            ),
            "chain": chain,
        }

    # ------------------------------------------------------------------
    # 图表来源（B3 第二增量）
    # ------------------------------------------------------------------

    async def charts(self, context: Any) -> dict[str, Any]:
        """当前 revision 登记了来源的图表清单（有 ChartTraceV1 的图）。"""

        index = await self.require_index(context)
        files = {item.resource_id: item for item in index.files}
        datasets = {item.dataset_id for item in index.datasets}
        return {
            "available": True,
            "charts": [
                {
                    "chartId": trace.chart_id,
                    "datasetIds": list(trace.dataset_ids),
                    "datasetIdsRegistered": all(
                        did in datasets for did in trace.dataset_ids
                    ),
                    "plotDataFileCount": len(trace.plot_data_file_resource_ids),
                    "plotDataKind": "chart_input",
                    "transformNotes": list(trace.transform_notes),
                    "imageSize": files[trace.image_file_resource_id].size,
                }
                for trace in index.chart_traces
            ],
        }

    async def chart_source(
        self,
        context: Any,
        chart_id: str,
        *,
        preview_limit: int = 20,
        preview_offset: int = 0,
    ) -> dict[str, Any]:
        """图表来源详情：图片/作图数据身份 + 作图表有界预览（计划 5.1）。

        chart_id 不在当前修订的索引中一律 `source_missing`（不泄露其他
        图表存在性）；作图数据文件逐个复核登记身份后解析为
        chart-input/v1 预览（columns + 分页 rows，不返回文件路径）。
        """

        index = await self.require_index(context)
        trace = next(
            (item for item in index.chart_traces if item.chart_id == chart_id),
            None,
        )
        if trace is None:
            raise ReportingError("source_missing", "图表不在当前修订的来源索引中。")
        files = {item.resource_id: item for item in index.files}
        image_ref = files[trace.image_file_resource_id]
        if not 1 <= preview_limit <= TRACE_BUDGETS_V1["preview_max_rows_per_page"]:
            raise ReportingError(
                "request_invalid",
                f"预览行数必须在 1~{TRACE_BUDGETS_V1['preview_max_rows_per_page']} 之间。",
            )
        # 负偏移在 Python 切片中会从尾部取行，返回与请求不符的预览。
        if preview_offset < 0:
            raise ReportingError("request_invalid", "预览起始行不能为负数。")
        plot_tables: list[dict[str, Any]] = []
        for resource_id in trace.plot_data_file_resource_ids:
            file_ref = files[resource_id]
            content = await self._read_registered_file(
                context, file_ref, max_bytes=8 * 1024 * 1024
            )
            plot_tables.append(
                self._chart_input_payload(
                    content,
                    file_ref=file_ref,
                    limit=preview_limit,
                    offset=preview_offset,
                )
            )
        return {
            "available": True,
            "chartId": trace.chart_id,
            "datasetIds": list(trace.dataset_ids),
            "transformNotes": list(trace.transform_notes),
            "computationId": trace.computation_id,
            "image": {"size": image_ref.size, "sha256": image_ref.sha256},
            "plotData": plot_tables,
        }

    @staticmethod
    def _chart_input_payload(
        content: bytes,
        *,
        file_ref: Any,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        """chart-input/v1 JSON → 有界预览（不暴露工作区路径）。"""

        import json as _json

        try:
            document = _json.loads(content)
        except ValueError:
            raise ReportingError(
                "snapshot_integrity_failed", "作图数据文件无法解析。"
            ) from None
        rows = document.get("rows")
        columns = document.get("columns")
        if not isinstance(rows, list) or not isinstance(columns, list):
            raise ReportingError(
                "snapshot_integrity_failed", "作图数据文件结构无效。"
            )
        window = rows[offset : offset + limit]
        return {
            "fileResourceId": file_ref.resource_id,
            "sha256": file_ref.sha256,
            "size": file_ref.size,
            "role": document.get("role"),
            "source": document.get("source"),
            "columns": columns,
            "rowCount": document.get("rowCount", len(rows)),
            "offset": offset,
            "limit": limit,
            "rows": window,
            "truncated": offset + len(window) < len(rows),
        }

    @staticmethod
    def _pointer_kind(pointer: str) -> str:
        if pointer.startswith("/metrics/"):
            return "metric"
        if pointer.startswith("/comparisons/"):
            return "comparison"
        if pointer.startswith("/derivedMetrics/"):
            return "derived"
        if pointer.startswith("/reconciliations/"):
            return "reconciliation"
        if pointer.startswith("/correlationDetails/"):
            return "correlation"
        return "metric"

    def _permissions(
        self, capabilities: Mapping[str, Any] | None
    ) -> TracePreviewPermissions:
        # capabilities 为 None 表示完整 editor 会话（向后兼容旧会话结构）；
        # 分享会话在签发时写入受限能力字典。
        if capabilities is None:
            return TracePreviewPermissions(
                can_download_original=True, can_download_derived=True
            )
        blocked = capabilities.get("blocked_columns") or ()
        return TracePreviewPermissions(
            blocked_columns=frozenset(str(item) for item in blocked),
            can_download_original=bool(capabilities.get("download_original", False)),
            can_download_derived=bool(capabilities.get("download_derived", False)),
        )

    @staticmethod
    def _drilldown_enabled(capabilities: Mapping[str, Any] | None) -> bool:
        return capabilities is None or bool(capabilities.get("drilldown", False))

    @staticmethod
    def _drilldown_declaration_allowed(
        declaration: Any, capabilities: Mapping[str, Any] | None
    ) -> bool:
        if capabilities is None:
            return True
        blocked = {str(item) for item in capabilities.get("blocked_columns") or ()}
        required = {
            *(item.field for item in declaration.dimensions),
            *declaration.fixed_scope,
        }
        required.update(
            item
            for item in (
                declaration.value_field,
                declaration.numerator_field,
                declaration.denominator_field,
                declaration.period_field,
            )
            if item is not None
        )
        return not bool(required & blocked)

    @staticmethod
    def _drilldown_declaration_payload(declaration: Any) -> dict[str, Any]:
        return {
            "metricCode": declaration.metric_code,
            "datasetId": declaration.dataset_id,
            "aggregation": declaration.aggregation,
            "unit": declaration.unit,
            "dimensions": [
                {"code": item.code, "label": item.label or item.code}
                for item in declaration.dimensions
            ],
        }

    async def _resolve_dataset_file(
        self,
        context: Any,
        index: RevisionTraceIndexV1,
        dataset_id: str,
        *,
        verify: bool = True,
    ) -> TraceDatasetFile:
        dataset = next(
            (item for item in index.datasets if item.dataset_id == dataset_id), None
        )
        if dataset is None:
            raise ReportingError(
                "source_missing", "数据集不在当前修订的来源索引中。"
            )
        file_ref = next(
            (item for item in index.files if item.resource_id == dataset.file_resource_id),
            None,
        )
        if not isinstance(file_ref, TraceFileRefV1):
            raise ReportingError(
                "snapshot_integrity_failed", "来源索引文件登记不完整。"
            )
        thread_id = context.scope["threadId"]
        # 预览与列清单在复制到请求内快照时校验，避免重复全文件哈希。
        if verify:
            current = await self._workspace.ahash_file(thread_id, file_ref.path)
            if (
                current.get("missing")
                or current.get("size") != file_ref.size
                or current.get("sha256") != file_ref.sha256
            ):
                raise ReportingError(
                    "snapshot_integrity_failed", "数据集快照与登记身份不一致。"
                )
        workspace = self._workspace.workspace(thread_id)
        relative = workspace.paths.normalize(file_ref.path, allow_root=False)
        host_path = workspace.paths.to_host_path(relative, allow_root=False)
        return TraceDatasetFile(
            dataset_id=dataset.dataset_id,
            local_path=host_path,
            size=file_ref.size,
            sha256=file_ref.sha256,
            row_count=dataset.row_count,
            filename=dataset.filename,
            source_type=dataset.source_type,
        )
