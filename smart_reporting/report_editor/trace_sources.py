"""Editor 来源读取服务（B1）：从 revision 追溯索引解析数据集并委托预览。

定位规则：索引文件 ``trace-index-v1.json`` 与 ``context.markdown_path`` 同目录
（发布链路 manifest 与正文同目录，Host 快照复制保持相对位置）。旧报告没有
索引时如实返回不可用，不猜测（计划 6.3）。

文件访问沿用 read_asset 的"登记-校验-哈希"模式：先在索引内解析
resourceId → 工作区相对路径；预览与列清单流式复制并校验 size/sha256，
再从请求内临时快照读取表头和数据，避免校验后原路径变更导致读取不一致。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from functools import partial
from pathlib import Path, PurePosixPath
from time import perf_counter
from typing import Any, Protocol

import anyio
from loguru import logger

from ..reporting.delivery.artifacts_v1 import ReportArtifactManifest
from ..reporting.delivery.report_runtime.markdown import readable_formula
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
    is_blocked_column,
    verified_dataset_snapshot,
)
from ..reporting.trace.drilldown_service import TraceDrilldownService
from ..reporting.trace.fact_index import FACT_ARRAYS
from ..reporting.trace.fact_service import fact_display_unit, fact_display_value, read_fact_document
from ..reporting.trace.numeric_text import PERCENT_POINT, percent_point_field, primary_display_name
from ..reporting.workflow.checkpoint import FileIdentity
from ..workspace import WorkspaceError
from .capabilities import EditorCapabilities
from .trace_exports import TraceDerivedExportService

_MAX_INDEX_BYTES = 4 * 1024 * 1024
_DRILLDOWN_TIMEOUT_SECONDS = 10.0
_DRILLDOWN_LARGE_FILE_BYTES = 64 * 1024 * 1024


CapabilitiesInput = EditorCapabilities | Mapping[str, Any] | None


def _registered_dataset_file(files: Mapping[str, Any], dataset: Any) -> Any | None:
    """数据集文件未登记时返回 None，字段说明跳过该快照而不是抛出 KeyError。"""
    if dataset is None:
        return None
    resource_id = getattr(dataset, "file_resource_id", None)
    if not isinstance(resource_id, str):
        return None
    return files.get(resource_id)


def _dataset_column_definitions(
    analysis_context: Mapping[str, Any],
    files: Mapping[str, Any],
    datasets: Sequence[Any],
) -> dict[str, dict[str, str]]:
    """每个已登记数据集的列名到中文说明；只采用与该数据集快照字节一致的分析上下文。"""
    definitions: dict[str, dict[str, str]] = {}
    for dataset_context in analysis_context.get("datasetContexts", ()):
        if not isinstance(dataset_context, Mapping):
            continue
        dataset_id = dataset_context.get("datasetId")
        dataset = next((item for item in datasets if item.dataset_id == dataset_id), None)
        file_ref = _registered_dataset_file(files, dataset)
        if file_ref is None or dataset_context.get("sha256") != file_ref.sha256:
            continue
        schema = dataset_context.get("schema") or {}
        if not isinstance(schema, Mapping):
            continue
        for table in schema.get("tables", ()):
            if not isinstance(table, Mapping):
                continue
            for column in table.get("columns", ()):
                if not isinstance(column, Mapping):
                    continue
                name = column.get("name")
                description = column.get("description")
                if (
                    isinstance(name, str) and name.strip()
                    and isinstance(description, str) and description.strip()
                ):
                    definitions.setdefault(dataset_id, {}).setdefault(name.strip(), description.strip())
    return definitions


def _merged_column_definitions(definitions: Mapping[str, Mapping[str, str]]) -> dict[str, str]:
    """跨数据集的列名到中文说明；同名列取先登记的说明。"""
    merged: dict[str, str] = {}
    for columns in definitions.values():
        for name, description in columns.items():
            merged.setdefault(name, description)
    return merged


def _formula_labels(
    entry: Mapping[str, Any] | None,
    dataset_ids: Sequence[str],
    definitions: Mapping[str, Mapping[str, str]],
) -> dict[str, str]:
    """口径里的字段写成读者看到的中文名：所属数据集的列说明优先，其次登记的指标名，均只取首个名称。

    同名列在所属数据集间说明不一致时保留原字段名，不张冠李戴。
    """
    labels: dict[str, str] = {}
    conflicts: set[str] = set()
    for dataset_id in dataset_ids:
        for name, description in definitions.get(dataset_id, {}).items():
            if labels.setdefault(name, description) != description:
                conflicts.add(name)
    for name in conflicts:
        labels.pop(name)
    field, display_name = (entry or {}).get("field"), (entry or {}).get("displayName")
    if isinstance(field, str) and isinstance(display_name, str) and display_name.strip():
        labels.setdefault(field, display_name)
    return {name: primary_display_name(label) or label for name, label in labels.items()}


def _column_field_definitions(
    analysis_context: Mapping[str, Any],
    files: Mapping[str, Any],
    datasets: Sequence[Any],
) -> dict[str, str]:
    """列名到中文说明；只采用与已登记数据集快照字节一致的分析上下文。"""
    return _merged_column_definitions(_dataset_column_definitions(analysis_context, files, datasets))


def narrative_section_projection(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return revision-bound finding assignments for the editor.

    Older manifests have no narrative mapping; expose the stable section list
    with empty optional fields rather than inferring findings from Markdown.
    """
    sections = manifest.get("sections")
    if not isinstance(sections, (list, tuple)):
        return []
    finding_ids = manifest.get("sectionFindingIds")
    grouping_reasons = manifest.get("sectionGroupingReasons")
    finding_ids = finding_ids if isinstance(finding_ids, Mapping) else {}
    grouping_reasons = grouping_reasons if isinstance(grouping_reasons, Mapping) else {}
    result: list[dict[str, Any]] = []
    for section_code in sections:
        if not isinstance(section_code, str):
            continue
        values = finding_ids.get(section_code, ())
        result.append({
            "sectionCode": section_code,
            "findingIds": list(values) if isinstance(values, (list, tuple)) else [],
            "groupingReason": (
                grouping_reasons.get(section_code)
                if isinstance(grouping_reasons.get(section_code), str)
                else None
            ),
        })
    return result



# 服务端表格大额列的表头单位（“门诊收入（万元）”）；单元格只写换算后的数字。

class _RegisteredFile(Protocol):
    """已登记文件身份：清单产物与追溯索引文件引用都满足。"""

    @property
    def path(self) -> str: ...

    @property
    def size(self) -> int: ...

    @property
    def sha256(self) -> str: ...


# 数据核对结果只有 verified/unknown（语义核对另有 conflicting）。unknown 里有一类只是“未评估”：
# 静态 PNG 不做数组比对、图表/表格未登记规格。它们不说明来源被改动，不能把未改动的图表/表格
# 降为待复核；其余 unknown（比对不一致、来源不可读、核对失败）仍按待复核处理。前端
# source-validation.ts 的 checkNeedsReview 保持同一清单。
NOT_EVALUATED_REASONS = frozenset({
    "static_image_not_evaluated", "interactive_spec_unregistered", "chart_unregistered", "table_unregistered",
    "chart_semantics_unregistered", "chart_fact_binding_unregistered",
    # 语义核对因数组未核验而未运行；数组本身不一致时 dataCheck 已判待复核。
    "chart_arrays_unverified",
})


def check_mismatched(check: Any) -> bool:
    if not isinstance(check, Mapping) or check.get("status") == "verified":
        return False
    reasons = check.get("reasons") or ((check["reason"],) if isinstance(check.get("reason"), str) else ())
    return check.get("status") == "conflicting" or not reasons or not set(reasons) <= NOT_EVALUATED_REASONS


class ReportEditorTraceService:
    def __init__(self, workspace: Any, *, cursor_secret: bytes) -> None:
        self._workspace = workspace
        self._preview = TraceCsvPreviewService(secret=cursor_secret)
        self._drilldown = TraceDrilldownService(secret=cursor_secret)
        self._drilldown_limiter = anyio.CapacityLimiter(4)
        self._drilldown_large_limiter = anyio.CapacityLimiter(1)
        self._drilldown_tasks: set[asyncio.Task[Any]] = set()
        self._validation_limiter = anyio.CapacityLimiter(2)
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
        return (await self.load_manifest_and_index(context))[1]

    async def load_manifest_and_index(
        self, context: Any
    ) -> tuple[ReportArtifactManifest | None, RevisionTraceIndexV1 | None]:
        """一次读取并核验修订产物清单与追溯索引，供同时需要两者的调用方复用。"""

        manifest = await self.load_manifest(context)
        return manifest, await self.index_for_manifest(context, manifest)

    async def index_for_manifest(
        self, context: Any, manifest: ReportArtifactManifest | None
    ) -> RevisionTraceIndexV1 | None:
        """按已核验的产物清单读取并核验追溯索引。"""

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
        from ..reporting.trace.subject_builder import bind_table_subjects

        return bind_table_subjects(index)

    # ------------------------------------------------------------------
    # 来源概览
    # ------------------------------------------------------------------

    async def sources(
        self,
        context: Any,
        session_capabilities: CapabilitiesInput = None,
        *,
        analysis_context_file: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        manifest, index = await self.load_manifest_and_index(context)
        if index is None:
            return {
                "available": False,
                "reason": "source_index_missing",
                "datasets": [],
                "narrativeSections": [],
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
                    file_ref = _registered_dataset_file(files, dataset)
                    if file_ref is None or dataset_context.get("sha256") != file_ref.sha256:
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
                    # 原始 SQL 含库表结构、过滤字面值与列名；分享会话（受限能力）只见哈希。
                    "querySql": (
                        dataset.query_sql
                        if EditorCapabilities.of(session_capabilities).full
                        else None
                    ),
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
            try:
                raw = await self._read_registered_file(
                    context, files[entry.file_resource_id], max_bytes=16 * 1024 * 1024
                )
                document = read_fact_document(raw)
                if document.get("analysisId") != entry.analysis_id:
                    raise ReportingError("fact_binding_unavailable", "事实文件与登记分析身份不匹配。")
            except (ReportingError, ValueError) as error:
                # 事实目录只是概览：保留期回收或文件损坏时不拖垮整个来源页，
                # 数据集元数据照常返回；事实明细接口仍按登记身份严格校验。
                logger.warning(
                    "facts_overview_unavailable report={} revision={} analysis={} error={}",
                    context.report_id, context.revision, entry.analysis_id, error,
                )
                continue
            for kind, key in FACT_ARRAYS:
                for fact in document.get(key, ()):
                    if not fact.get("factId"):
                        continue
                    dataset_ids = list(dict.fromkeys(
                        dataset_id for dataset_id in (
                            *(fact.get(field) for field in ("datasetId", "currentDatasetId", "baselineDatasetId")),
                            *fact.get("datasetIds", ()),
                        ) if dataset_id in registered_dataset_ids
                    ))
                    # 列说明缺失时先用登记的指标名，不向读者显示内部字段名。
                    name = fact.get("displayName") or fact.get("field") or fact.get("code") or (
                        f'{fact["leftField"]} / {fact["rightField"]}' if kind == "correlation" else None
                    ) or fact.get("fieldRef") or fact["factId"]
                    descriptions = {field_labels[(dataset_id, fact.get("fieldRef"))] for dataset_id in dataset_ids
                        if (dataset_id, fact.get("fieldRef")) in field_labels}
                    if len(descriptions) == 1:
                        name = descriptions.pop()
                    roles = fact.get("periodRoles") or ([fact["periodRole"]] if fact.get("periodRole") else [])
                    facts.append({
                        "analysisId": entry.analysis_id,
                        "analysisName": document.get("analysisName"),
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
                        "unit": fact_display_unit(fact),
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
            "citations": [
                {"citationId": citation.citation_id, "datasetId": citation.dataset_id}
                for citation in (manifest.citations if manifest is not None else ())
                if citation.dataset_id in registered_dataset_ids
            ],
            "facts": facts,
            "narrativeSections": narrative_section_projection(
                manifest.model_dump(mode="json", by_alias=True) if manifest is not None else {}
            ),
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
                    "sourceCell": subject.source_cell.model_dump(mode="json", by_alias=True) if subject.source_cell else None,
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
        session_capabilities: CapabilitiesInput,
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
        session_capabilities: CapabilitiesInput,
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
        session_capabilities: CapabilitiesInput,
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
            context, index, declaration.dataset_id, verify=False
        )
        limiter = (
            self._drilldown_large_limiter
            if file.size >= _DRILLDOWN_LARGE_FILE_BYTES
            else self._drilldown_limiter
        )

        def read_drilldown():
            # 复制、校验与所有聚合读取在同一线程内，临时快照存活到计算结束。
            with verified_dataset_snapshot(file) as snapshot:
                return self._drilldown.drilldown(
                    snapshot,
                    declaration,
                    dimension_code=dimension_code,
                    report_id=str(context.report_id),
                    revision=int(context.revision),
                    limit=limit,
                    cursor=cursor,
                )

        try:
            with anyio.fail_after(_DRILLDOWN_TIMEOUT_SECONDS):
                # 等待名额也计入超时；尚未取得名额的请求不能留下后台排队任务。
                borrower = object()
                await limiter.acquire_on_behalf_of(borrower)
                execution = asyncio.create_task(
                    anyio.to_thread.run_sync(read_drilldown)
                )
                self._drilldown_tasks.add(execution)

                def finished(task: asyncio.Task[Any]) -> None:
                    limiter.release_on_behalf_of(borrower)
                    self._drilldown_tasks.discard(task)
                    if not task.cancelled():
                        task.exception()

                # 超时或调用方取消都不能终止同步线程；实际完成后才释放名额。
                execution.add_done_callback(finished)
                page = await asyncio.shield(execution)
        except TimeoutError as error:
            raise ReportingError(
                "resource_limit_exceeded", "下钻计算超时，请稍后重试。"
            ) from error
        return page.to_payload()

    async def aclose(self) -> None:
        """关闭时等待已脱离请求的下钻线程及派生导出完成。"""
        await asyncio.gather(
            self.exports.aclose(), *self._drilldown_tasks, return_exceptions=True
        )

    # ------------------------------------------------------------------
    # 预览与下载
    # ------------------------------------------------------------------

    async def preview(
        self,
        context: Any,
        session_capabilities: CapabilitiesInput,
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
        session_capabilities: CapabilitiesInput,
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
        session_capabilities: CapabilitiesInput,
        dataset_id: str,
    ) -> tuple[Path, str, int, str]:
        index = await self.require_index(context)
        file = await self._resolve_dataset_file(context, index, dataset_id)
        path, filename = await anyio.to_thread.run_sync(
            self._preview.download_target,
            file, self._permissions(session_capabilities)
        )
        return path, filename, file.size, file.sha256

    async def create_derived_export(
        self,
        context: Any,
        session_capabilities: CapabilitiesInput,
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
        session_capabilities: CapabilitiesInput,
        export_id: str,
    ) -> tuple[Path, str, int, str]:
        permissions = self._permissions(session_capabilities)
        if not permissions.can_download_derived:
            raise ReportingError(
                "dataset_access_denied", "当前会话无权下载派生导出。"
            )
        return await self.exports.download(
            context, export_id, blocked_columns=permissions.blocked_columns
        )

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
        from ..reporting.trace.fact_service import resolve_fact_from_document

        index = await self.require_index(context)
        entry = next(
            (item for item in index.fact_files
             if item.analysis_id == analysis_id and item.content_kind == "deterministic_bundle"),
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
        document = read_fact_document(bundle_bytes)
        pointer = self._locate_fact_pointer(document, fact_id)
        fact_ref = FactRefV1(
            analysisId=analysis_id,
            fileResourceId=derive_resource_id(file_ref.path),
            jsonPointer=pointer,
            factKind=self._pointer_kind(pointer),
            factKey=fact_id,
        )
        result = resolve_fact_from_document(document, fact_ref, with_inputs=True)
        result["analysisName"] = document.get("analysisName")
        return result

    @staticmethod
    def _locate_fact_pointer(document: Mapping[str, Any], fact_id: str) -> str:
        # 与 fact_index 的 factId 分配范围一致：相关性事实同样进入正文引用的事实目录。
        for _, array_name in FACT_ARRAYS:
            for index, item in enumerate(document.get(array_name, ()) or ()):
                if isinstance(item, dict) and item.get("factId") == fact_id:
                    return f"/{array_name}/{index}"
        raise ReportingError("fact_binding_unavailable", "事实 ID 不在该分析中。")

    async def _column_definitions_for_review(
        self,
        context: Any,
        files: Mapping[str, Any],
        datasets: Sequence[Any],
        analysis_context_file: Mapping[str, Any] | None,
    ) -> dict[str, dict[str, str]]:
        """编辑器复核使用与生成阶段相同的列名说明（按数据集）；上下文缺失时不阻断校验。"""
        if analysis_context_file is None:
            return {}
        try:
            raw_context = await self._read_registered_file(
                context,
                FileIdentity.model_validate(analysis_context_file),
                max_bytes=_MAX_INDEX_BYTES,
            )
            analysis_context = json.loads(raw_context)
        except (ReportingError, ValueError, TypeError, AttributeError):
            logger.warning(
                "report_editor_review_context_unavailable report={} revision={}",
                context.report_id,
                context.revision,
            )
            return {}
        if not isinstance(analysis_context, dict):
            return {}
        return _dataset_column_definitions(analysis_context, files, datasets)

    # ------------------------------------------------------------------
    # 正文 subject 校验（B6）
    # ------------------------------------------------------------------

    async def validate(
        self,
        context: Any,
        markdown: str,
        draft_sha256: str,
        *,
        analysis_context_file: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """按 ``[[claim:id]]`` 协议标记判定正文 subject 状态（计划 6.1）。

        标记被删 → unbound；标记附近找不到生成时事实值 → stale（软语义，
        提示复核，不拒绝保存）；命中 → valid。响应绑定请求的草稿 sha，
        前端据此丢弃过期响应。
        """

        import hashlib
        import json as _json

        from ..reporting.delivery.artifacts_v1 import _TABLE_BLOCK
        from ..reporting.trace.semantic_bindings import (
            bound_number_display,
            reference_computation,
            reference_fact_ids,
            resolve_number_references,
            statement_fingerprints,
        )
        from ..reporting.trace.subject_builder import (
            fact_periods,
            prepare_claim_status,
            value_matches,
        )
        from ..reporting.trace.table_sources import (
            derivation_resource_ids,
            resolve_table_derivation,
        )

        started = perf_counter()
        actual_draft_sha256 = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        if actual_draft_sha256 != draft_sha256:
            raise ReportingError(
                "request_invalid", "草稿摘要与正文内容不一致，已拒绝校验。"
            )

        index = await self.require_index(context)
        files = {item.resource_id: item for item in index.files}
        thread_id = context.scope["threadId"]
        bundle_cache: dict[str, Any] = {}
        validated_source_bytes: dict[str, bytes] = {}
        table_source_cache: dict[str, bytes] = {}
        source_failures: dict[str, str] = {}

        async def _table_sources_of(derivation: Any) -> dict[str, bytes]:
            source_ids = set(derivation_resource_ids(derivation))
            result: dict[str, bytes] = {}
            for resource_id in source_ids:
                file_ref = files.get(resource_id)
                if file_ref is None or file_ref.media_type != "application/json":
                    raise ReportingError("snapshot_integrity_failed", "表格派生来源登记不完整。")
                if resource_id not in table_source_cache:
                    if resource_id in source_failures:
                        raise ReportingError(source_failures[resource_id], "表格来源无法核验。")
                    try:
                        table_source_cache[resource_id] = await self._read_registered_file(
                            context, file_ref, max_bytes=16 * 1024 * 1024
                        )
                    except Exception as error:
                        code = error.code if isinstance(error, ReportingError) else "source_read_failed"
                        source_failures[resource_id] = code
                        raise ReportingError(code, "表格来源无法核验。") from error
                result[resource_id] = table_source_cache[resource_id]
            return result

        async def _fact_entry_of(ref: Any) -> dict[str, Any] | None:
            file_ref = files.get(ref.file_resource_id)
            if file_ref is None:
                raise ReportingError("snapshot_integrity_failed", "事实文件登记不完整。")
            if file_ref.path not in bundle_cache:
                try:
                    content = await self._workspace.read_limited_regular_file(
                        thread_id, file_ref.path, max_bytes=16 * 1024 * 1024
                    )
                except Exception as error:
                    source_failures[file_ref.resource_id] = (
                        "snapshot_integrity_failed" if isinstance(error, (OSError, WorkspaceError))
                        else error.code if isinstance(error, ReportingError) else "source_read_failed"
                    )
                    bundle_cache[file_ref.path] = None
                    return None
                if len(content) != file_ref.size or hashlib.sha256(content).hexdigest() != file_ref.sha256:
                    source_failures[file_ref.resource_id] = "snapshot_integrity_failed"
                    bundle_cache[file_ref.path] = None
                    return None
                validated_source_bytes[file_ref.resource_id] = content
                try:
                    bundle_cache[file_ref.path] = read_fact_document(content)
                except ReportingError as error:
                    # 只拒绝有歧义/损坏的来源；正文与其余来源仍可进行软校验。
                    bundle_cache[file_ref.path] = None
                    source_failures[file_ref.resource_id] = error.code
                    logger.warning("source_validation_fact_unavailable resource={} error={}", file_ref.resource_id, error.code)
            document = bundle_cache[file_ref.path]
            if not isinstance(document, dict):
                return None
            from ..reporting.trace.fact_index import fact_entry_from_pointer

            if document.get("analysisId") != ref.analysis_id:
                return None
            try:
                kind, entry = fact_entry_from_pointer(document, ref.json_pointer)
            except KeyError:
                return None
            if kind != ref.fact_kind or (ref.fact_key and entry.get("factId") != ref.fact_key):
                return None
            if kind in {"comparison", "derived"} and not entry.get("periodGranularity"):
                from ..reporting.trace.fact_service import _input_fact_refs

                # 比较窗口沿用输入指标的粒度；月初日期标签不能被误当作单日窗口。
                inputs = {item["factId"] for item in _input_fact_refs(document, kind, entry) if item.get("factId")}
                grains = {metric.get("periodGranularity") for metric in document.get("metrics") or ()
                          if isinstance(metric, dict) and metric.get("factId") in inputs}
                if len(grains) == 1 and (grain := next(iter(grains))) in {"day", "month", "year"}:
                    return {**entry, "periodGranularity": grain}
            return entry

        def _entry_value(entry: dict[str, Any] | None) -> Any:
            if not entry:
                return None
            return fact_display_value(entry)

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

        async def _fact_value_of(ref: Any, row_key: str) -> Any:
            entry = await _fact_entry_of(ref)
            if entry is not None and (selection := re.fullmatch(r"periodValues\.(\d+)", row_key)):
                values = entry.get("periodValues") or ()
                position = int(selection[1])
                return values[position].get("value") if position < len(values) and isinstance(values[position], dict) else None
            if entry is not None and row_key == "total":
                return entry.get("total")
            if entry is not None and row_key in {"currentTotal", "baselineTotal", "change", "changeRate"}:
                return "—" if entry.get(row_key) is None else entry[row_key]
            if row_key.startswith("comparison:") and entry is not None:
                field = row_key.rsplit(":", 1)[-1]
                if field not in {"currentTotal", "baselineTotal", "change", "changeRate"} or field not in entry:
                    return None
                # 成功读取的空计算结果展示为“—”；解析失败仍返回 None。
                return "—" if entry[field] is None else entry[field]
            if row_key.startswith("period:") and entry is not None:
                period = row_key.removeprefix("period:")
                values = [item.get("value") for item in entry.get("periodValues") or ()
                          if isinstance(item, dict) and item.get("period") == period]
                return values[0] if len(values) == 1 else None
            return _entry_value(entry)

        async def _fact_selector_valid_of(ref: Any, row_key: str, selector: str) -> bool:
            from ..reporting.trace.table_quality import table_selector_matches

            entry = await _fact_entry_of(ref)
            return entry is not None and table_selector_matches(entry, row_key, selector)

        async def _fact_unit_of(ref: Any, row_key: str) -> str | None:
            entry = await _fact_entry_of(ref)
            if entry is None:
                return None
            if row_key.startswith("comparison:") or row_key in {"currentTotal", "baselineTotal", "change", "changeRate"}:
                field = row_key.rsplit(":", 1)[-1]
                if field == "changeRate":
                    return "%"
                return PERCENT_POINT if percent_point_field(field, entry.get("unit")) else entry.get("unit")
            return fact_display_unit(entry)

        subjects: list[dict[str, Any]] = []
        summary = {"valid": 0, "stale": 0, "unbound": 0}
        check_claim = await anyio.to_thread.run_sync(
            prepare_claim_status, markdown, limiter=self._validation_limiter
        )
        fingerprints = await anyio.to_thread.run_sync(statement_fingerprints, markdown, tuple(
            binding.claim_id for binding in index.subject_bindings
            if binding.number_reference and binding.claim_id
        ), limiter=self._validation_limiter)
        legacy_claims = tuple(
            binding.claim_id for binding in index.subject_bindings
            if binding.claim_id and binding.number_reference and binding.number_reference.display_text is None
        )
        legacy_loaded = False
        legacy_markdown: str | None = None
        legacy_fingerprints: dict[str, str | None] = {}

        async def _legacy_restore_text(number: Any, selected: dict[str, Any]) -> str | None:
            nonlocal legacy_loaded, legacy_markdown, legacy_fingerprints
            if not legacy_loaded:
                legacy_loaded = True
                try:
                    identity = files[index.markdown_file_resource_id]
                    committed = await self._read_registered_file(context, identity, max_bytes=16 * 1024 * 1024)
                    legacy_markdown = committed.decode('utf-8')
                    legacy_fingerprints = await anyio.to_thread.run_sync(
                        statement_fingerprints, legacy_markdown, legacy_claims, limiter=self._validation_limiter,
                    )
                except Exception as error:
                    legacy_markdown = None
                    logger.warning('source_validation_restore_unavailable report_id={} error={}',
                                   context.report_id, getattr(error, 'code', type(error).__name__))
            if legacy_markdown is None:
                return None
            if legacy_fingerprints.get(number.claim_id) != number.statement_sha256:
                logger.warning('source_validation_restore_fingerprint_mismatch claim_id={}', number.claim_id)
                return None
            try:
                shown = bound_number_display(legacy_markdown, number.claim_id, selected)
            except Exception as error:
                logger.warning('source_validation_restore_display_failed claim_id={} error={}',
                               number.claim_id, type(error).__name__)
                return None
            if shown is None or not shown.verified or len(shown.text) > 4096:
                logger.warning('source_validation_restore_display_unavailable claim_id={}', number.claim_id)
                return None
            return shown.text

        column_definitions = await self._column_definitions_for_review(
            context, files, index.datasets, analysis_context_file
        )
        number_tokens: dict[tuple[str, ...], set[str]] = {}
        for binding in index.subject_bindings:
            if (binding.number_reference and binding.claim_id and binding.fact_refs
                    and binding.number_reference.table_derivation is None):
                source_ids = tuple(sorted({ref.file_resource_id for ref in binding.fact_refs}))
                number_tokens.setdefault(source_ids, set()).add(binding.number_reference.token)
        def _cell_selector(cell: Any, entry: dict[str, Any] | None) -> str | None:
            """表格单元格对应的数值选择器；旧索引把选择器写在行键里（comparison:0:change、period:2025-01）。"""
            if entry is None:
                return None
            if cell.value_selector:
                return cell.value_selector
            row_key = cell.row_key
            if row_key.startswith("comparison:"):
                return row_key.rsplit(":", 1)[-1]
            if row_key.startswith("period:"):
                positions = [index for index, item in enumerate(entry.get("periodValues") or ())
                             if isinstance(item, dict) and item.get("period") == row_key.removeprefix("period:")]
                return f"periodValues.{positions[0]}" if len(positions) == 1 else None
            return row_key

        # 表格单元格只登记事实与选择器；与正文引用并入同一来源组的同一次解析，得到同样的数值视图。
        table_selectors: dict[tuple[str, ...], set[tuple[str, str]]] = {}
        table_cell_views: dict[tuple[str, str, str], tuple[tuple[str, ...], str]] = {}
        for table in index.tables:
            for cell in table.cells:
                if cell.computation_id or len(cell.fact_refs) != 1 or not cell.fact_refs[0].fact_key:
                    continue
                ref = cell.fact_refs[0]
                cell_entry = await _fact_entry_of(ref)
                selector = _cell_selector(cell, cell_entry)
                if selector is None:
                    continue
                table_selectors.setdefault((ref.file_resource_id,), set()).add((ref.fact_key, selector))
                table_cell_views[(table.table_id, cell.row_key, cell.column_key)] = (
                    (ref.file_resource_id,), f"{ref.fact_key}:{selector}",
                )
        number_results: dict[tuple[str, ...], dict[str, Any]] = {}

        async def _resolved_group(source_ids: tuple[str, ...]) -> dict[str, Any]:
            if source_ids not in number_results:
                number_results[source_ids] = await anyio.to_thread.run_sync(
                    partial(
                        resolve_number_references,
                        tuple(number_tokens.get(source_ids, ())),
                        tuple(_json.dumps(bundle_cache[files[resource_id].path]) for resource_id in source_ids),
                        selectors=tuple(sorted(table_selectors.get(source_ids, ()))),
                    ),
                    limiter=self._validation_limiter,
                )
            return number_results[source_ids]

        def _value_view(entry: dict[str, Any] | None, selected: dict[str, Any] | None) -> dict[str, Any]:
            """正文数值与表格单元格共用的冻结摘要：单位、期间、口径或可验算算式、范围与数据集。"""
            formula = _entry_formula(entry)
            return {
                "formula": formula,
                # 派生值与对比值写出可验算的算式，其余与导出附录同一转换规则。
                "formulaText": (selected or {}).get("explanation") or (readable_formula(formula, _formula_labels(
                    entry, _entry_dataset_ids(entry), column_definitions,
                )) if formula else None),
                "scope": _entry_scope(entry),
                "datasetIds": _entry_dataset_ids(entry),
            }
        for binding in index.subject_bindings:
            if not binding.claim_id or not (binding.fact_refs or (
                binding.number_reference is not None
                and binding.number_reference.table_derivation is not None
            )):
                continue
            entry: dict[str, Any] | None = None
            for ref in binding.fact_refs:
                entry = await _fact_entry_of(ref)
                if _entry_value(entry) is not None:
                    break
            fact_value = _entry_value(entry)
            expected_unit = fact_display_unit(entry) if entry else None
            expected_periods = fact_periods(entry) if entry else ()
            number = binding.number_reference
            selected = None
            if number is not None:
                derivation = number.table_derivation
                if derivation is not None:
                    # Any ordinary FactRefs remain independent prerequisites.
                    entries = [await _fact_entry_of(ref) for ref in binding.fact_refs]
                    if all(item is not None for item in entries) and number.claim_id == binding.claim_id:
                        try:
                            table_sources = await _table_sources_of(derivation)
                            selected = await anyio.to_thread.run_sync(
                                resolve_table_derivation,
                                number.token,
                                derivation,
                                table_sources,
                                limiter=self._validation_limiter,
                            )
                        except Exception as error:
                            logger.warning(
                                "source_validation_table_derivation_unavailable claim_id={} error={}",
                                binding.claim_id,
                                type(error).__name__,
                            )
                else:
                    # 每个操作数先通过文件 hash、analysis、pointer 和 factKey 校验，不能借同分析其它值。
                    entries = [await _fact_entry_of(ref) for ref in binding.fact_refs]
                    ids = reference_fact_ids(number.token)
                    if (all(item is not None for item in entries)
                            and set(ids) == {ref.fact_key for ref in binding.fact_refs}
                            and number.claim_id == binding.claim_id):
                        source_ids = tuple(sorted({ref.file_resource_id for ref in binding.fact_refs}))
                        selected = (await _resolved_group(source_ids)).get(number.token)
                fact_value = selected["value"] if selected else None
                expected_unit = selected["unit"] if selected else None
                expected_periods = selected["periods"] if selected else ()
                if selected:
                    entry = {**selected["entry"], "formula": selected["formula"], "scope": selected["scope"]}
            detail = check_claim(
                binding.claim_id,
                fact_value,
                expected_unit=expected_unit,
                expected_periods=expected_periods,
                expected_period_roles=selected['period_roles'] if selected else None,
                expected_scope=_entry_scope(entry),
                expected_reference=selected,
                semantic_receipt=number.semantic_receipt if number else None,
                section_id=binding.locator.section_id,
            )
            if number is not None:
                if selected is None:
                    detail = {"status": "unbound", "warnings": ["具体数值引用无法从登记事实重算。"]}
                elif (detail["status"] == "valid" and
                      fingerprints[binding.claim_id] != number.statement_sha256):
                    detail["status"] = "stale"
                    detail["warnings"].append("引用所在陈述已修改，请复核指标、期间和范围。")
                    detail["comparable"] = False
            dependency_ids = {ref.file_resource_id for ref in binding.fact_refs}
            if number is not None and number.table_derivation is not None:
                dependency_ids.update(derivation_resource_ids(number.table_derivation))
            failed_sources = sorted(dependency_ids & source_failures.keys())
            if failed_sources:
                detail["warnings"].append("来源身份无法核验；已拒绝使用对应数据，其余来源继续校验。")
            restore_text = number.display_text if number is not None and selected is not None else None
            if number is not None and selected is not None and restore_text is None:
                restore_text = await _legacy_restore_text(number, selected)
            status = detail["status"]
            summary[status] += 1
            from ..reporting.trace.claim_semantics import semantic_receipt_status

            receipt = number.semantic_receipt if number else None
            subjects.append(
                {
                    "subjectId": binding.subject_id,
                    "claimId": binding.claim_id,
                    "sectionId": binding.locator.section_id,
                    "status": status,
                    "sourceStatus": "integrity_failed" if failed_sources else "available",
                    "bindingStatus": {"valid": "bound", "stale": "invalidated", "unbound": "unbound"}[status],
                    "supportStatus": "supported" if status == "valid" and selected is not None
                                     and selected.get("scope") and selected.get("periods")
                                     and not detail["warnings"] else "unknown",
                    "checkStatus": "failed" if failed_sources else "completed",
                    "sourceIssues": [{"resourceId": resource_id, "code": source_failures[resource_id]}
                                     for resource_id in failed_sources],
                    "factValue": fact_value,
                    # 读者可见的可信状态：直接登记值、服务端派生或按运算式重算。
                    "computation": reference_computation(
                        number.token, selected.get("selector") if selected else None,
                        table_derivation=number.table_derivation is not None,
                        entry=selected.get("entry") if selected else None,
                    ) if number is not None else None,
                    "restoreText": restore_text,
                    "warnings": detail["warnings"],
                    "semanticCheck": {
                        "method": receipt.method,
                        "status": semantic_receipt_status(markdown, binding.claim_id, receipt),
                        "interpretation": receipt.interpretation.model_dump(mode='json', by_alias=True),
                    } if receipt and selected and not failed_sources else None,
                    "draftValue": detail.get("draftValue"),
                    "draftUnit": detail.get("draftUnit"),
                    "draftPeriods": detail.get("draftPeriods"),
                    "draftDirection": detail.get("draftDirection"),
                    "comparable": detail.get("comparable", False),
                    # B8 导出来源附录的冻结摘要字段：单位、期间、公式、范围与
                    # 数据集身份都取自事实登记，不从草稿反推。
                    "unit": expected_unit,
                    "periods": list(expected_periods),
                    **_value_view(entry, selected),
                }
            )

        direct_source_documents: dict[str, Any] = {}

        async def _source_cell_of(operand: Any) -> dict[str, Any] | None:
            from types import SimpleNamespace

            from ..reporting.trace.table_sources import _object, source_cell_view

            try:
                sources = await _table_sources_of(SimpleNamespace(operands=(operand,), denominator_fact=None))
                resource_id = operand.file_resource_id
                if resource_id not in direct_source_documents:
                    direct_source_documents[resource_id] = json.loads(sources[resource_id], object_pairs_hook=_object)
                return source_cell_view(operand, direct_source_documents[resource_id])
            except Exception as error:
                logger.warning("source_validation_table_cell_unavailable reason={}", type(error).__name__)
                return None

        tables_payload, table_summary = await self._evaluate_tables(
            index, context, markdown, _fact_value_of, _TABLE_BLOCK, value_matches,
            fact_unit_of=_fact_unit_of,
            fact_selector_valid_of=_fact_selector_valid_of, source_cell_of=_source_cell_of,
        )
        for table, payload in zip(index.tables, tables_payload, strict=True):
            # 表格单元格与正文数值同一数值视图：卡片写出登记值、期间、取得方式与可验算算式。
            direct_cells = {(cell.row_key, cell.column_key): cell for cell in table.cells
                            if cell.source_cell is not None}
            for location in payload["locations"]:
                direct = direct_cells.get((location['rowKey'], location['columnKey']))
                if direct is not None:
                    selected = await _source_cell_of(direct.source_cell)
                    if selected is not None:
                        location.update(factValue=selected['value'], unit=selected['unit'],
                                        periods=list(selected['periods']), scope=selected['scope'],
                                        datasetIds=list(direct.dataset_ids),
                                        computation={'method': 'frozen_source_cell',
                                                     'explanation': '冻结补证表原始单元格；数值身份核验不代表业务期间或分析角色已确认。'})
                    continue
                found = table_cell_views.get((table.table_id, location["rowKey"], location["columnKey"]))
                if found is None:
                    continue
                source_ids, key = found
                selected = (await _resolved_group(source_ids)).get(key)
                if selected is None:
                    continue
                location.update(
                    factValue=selected["value"],
                    unit=selected["unit"],
                    periods=list(selected["periods"]),
                    computation=reference_computation(
                        f"{{{{value:{key}:}}}}", selected.get("selector"), entry=selected.get("entry"),
                    ),
                    **_value_view(
                        {**selected["entry"], "formula": selected["formula"], "scope": selected["scope"]}, selected,
                    ),
                )
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
        from ..reporting.trace.content_review import review_content

        # 未绑定数值的趋势段也需要复核，不能只加载已有数值锚点引用的事实。
        for fact_file in index.fact_files:
            identity = files[fact_file.file_resource_id]
            if identity.path not in bundle_cache:
                try:
                    raw = await self._read_registered_file(context, identity, max_bytes=16 * 1024 * 1024)
                    validated_source_bytes[identity.resource_id] = raw
                    bundle_cache[identity.path] = read_fact_document(raw)
                except Exception as error:
                    source_failures[identity.resource_id] = error.code if isinstance(error, ReportingError) else "source_read_failed"
                    bundle_cache[identity.path] = None
        plot_contents: list[str] = []
        plot_ids = {
            resource_id
            for chart in index.chart_traces
            for resource_id in chart.plot_data_file_resource_ids
        }
        for resource_id in sorted(plot_ids):
            try:
                raw = await self._read_registered_file(context, files[resource_id], max_bytes=8 * 1024 * 1024)
                validated_source_bytes[resource_id] = raw
                plot_contents.append(raw.decode("utf-8"))
            except (ReportingError, UnicodeDecodeError) as error:
                logger.warning("report_editor_plot_validation_source_unavailable resource_id={} reason={}",
                               resource_id, type(error).__name__)

        from ..reporting.trace.markdown_body import trace_body

        review_markdown = trace_body(markdown)
        # 与生成阶段同一组输入：列中文名用于补证归因，仍留在正文中的成品图不能被说成已剔除。
        bound_chart_ids = tuple(
            chart["chartId"]
            for chart in charts_payload
            if chart.get("status") in {"valid", "stale"}
        )
        field_definitions = _merged_column_definitions(column_definitions)
        warnings = await anyio.to_thread.run_sync(
            partial(
                review_content,
                field_definitions=field_definitions,
                bound_chart_ids=bound_chart_ids,
            ),
            markdown,
            (
                *(_json.dumps(bundle, ensure_ascii=False) for bundle in bundle_cache.values()
                  if bundle is not None),
                *plot_contents,
            ),
            limiter=self._validation_limiter,
        )
        from ..reporting.trace.contracts_v1 import canonical_sha256
        from ..reporting.trace.quality_bundle import (
            QUALITY_FILENAME,
            QualityBundle,
            evaluate_quality_bundle,
        )

        try:
            questions = None
            answer_review_plan = None
            interactive_charts = {}
            try:
                manifest = await self.load_manifest(context)
                if manifest is not None:
                    for chart in manifest.charts:
                        spec = chart.interactive_spec
                        if spec is None:
                            continue
                        registered = [files.get(derive_resource_id(item.path)) for item in (chart, spec)]
                        if all(file is not None and file.path == item.path and file.size == item.size
                               and file.sha256 == item.sha256 for file, item in zip(registered, (chart, spec), strict=True)):
                            interactive_charts[chart.path] = spec.path
            except Exception:
                logger.warning("editor_chart_manifest_unavailable")
            chart_quality_ids = {chart.image_file_resource_id for chart in index.chart_traces}
            from ..reporting.trace.chart_quality import QUALITY_IMAGE_BYTE_BUDGET

            quality_image_ids = set(chart_quality_ids)
            quality_image_bytes = 0
            chart_quality_ids.update(file.resource_id for file in index.files
                                     if file.path in set(interactive_charts.values()))
            for resource_id in (file.resource_id for file in index.files if file.resource_id in chart_quality_ids):
                if resource_id in quality_image_ids:
                    if files[resource_id].size > QUALITY_IMAGE_BYTE_BUDGET - quality_image_bytes:
                        continue
                try:
                    validated_source_bytes[resource_id] = await self._read_registered_file(
                        context, files[resource_id], max_bytes=min(files[resource_id].size, QUALITY_IMAGE_BYTE_BUDGET)
                        if resource_id in quality_image_ids else 16 * 1024 * 1024,
                    )
                    if resource_id in quality_image_ids:
                        quality_image_bytes += len(validated_source_bytes[resource_id])
                except Exception:
                    logger.warning("editor_chart_quality_source_unavailable resource_id={}", resource_id)
            quality_path = PurePosixPath(context.markdown_path).with_name(QUALITY_FILENAME).as_posix()
            quality_file = next((file for file in index.files if file.path == quality_path), None)
            if quality_file is not None:
                try:
                    historical = QualityBundle.model_validate_json(await self._read_registered_file(
                        context, quality_file, max_bytes=16 * 1024 * 1024,
                    ))
                    # Only frozen requirements are carried across revisions;
                    # previous pass/coverage results are never reused.
                    if historical.report_id == index.report_id:
                        questions = historical.question_specs
                        answer_review_plan = historical.answer_review_plan
                except Exception as error:
                    logger.warning("editor_question_specs_unavailable reason={}", type(error).__name__)
            if any(table.origin_markdown is None for table in index.tables):
                original_file = files[index.markdown_file_resource_id]
                try:
                    validated_source_bytes[original_file.resource_id] = await self._read_registered_file(
                        context, original_file, max_bytes=16 * 1024 * 1024,
                    )
                except Exception:
                    logger.warning("editor_table_original_unavailable")
            quality = await anyio.to_thread.run_sync(partial(
                evaluate_quality_bundle, index, markdown, validated_source_bytes,
                authorization_scope_hash=canonical_sha256({
                    key: context.scope.get(key) for key in ("userId", "threadId")
                }),
                questions=questions,
                answer_review_plan=answer_review_plan,
                interactive_charts=interactive_charts,
            ), limiter=self._validation_limiter)
            quality_payload = {
                "status": "evaluated", "inputSha256": quality.input_sha256,
                "allKeyFactsEvaluated": quality.all_key_facts_evaluated,
                "questionCoverage": quality.question_coverage,
                "answerReview": quality.answer_review.model_dump(mode="json", by_alias=True) if quality.answer_review is not None else None,
                "managementOverview": quality.management_overview.model_dump(mode="json", by_alias=True) if quality.management_overview is not None else None,
                "issues": [issue.model_dump(mode="json", by_alias=True) for issue in quality.issues],
                "tableChecks": {key: check.model_dump(mode="json", by_alias=True) for key, check in quality.table_checks.items()},
                "semanticChecks": {key: check.model_dump(mode="json", by_alias=True) for key, check in quality.semantic_checks.items()},
                "chartChecks": {key: check.model_dump(mode="json", by_alias=True) for key, check in quality.chart_checks.items()},
            }
            try:
                from ..reporting.trace.warning_ledger import build_warning_ledger

                quality_payload["warningLedger"] = build_warning_ledger(
                    quality, index,
                ).model_dump(mode="json", by_alias=True)
            except Exception as error:
                # An optional worklist must never erase the original diagnostics.
                logger.warning("editor_warning_ledger_unavailable reason={}", type(error).__name__)
            for table in tables_payload:
                check = quality.table_checks.get(table["tableId"])
                table["dataCheck"] = check.model_dump(mode="json", by_alias=True) if check is not None else {
                    "status": "unknown", "scope": "frozen_cells", "reasons": ["table_unregistered"],
                }
            for chart in charts_payload:
                semantic_check = quality.semantic_checks.get(chart["chartId"])
                chart["semanticCheck"] = semantic_check.model_dump(mode="json", by_alias=True) if semantic_check is not None else {
                    "status": "unknown", "scope": "registered_fact_projection", "reasons": ["chart_semantics_unregistered"],
                }
                check = quality.chart_checks.get(chart["chartId"])
                chart["dataCheck"] = check.model_dump(mode="json", by_alias=True) if check is not None else {
                    "status": "unknown", "scope": "registered_arrays", "reason": "chart_unregistered",
                }
        except Exception as error:
            logger.warning("editor_quality_evaluation_unavailable reason={}", type(error).__name__)
            quality_payload = {"status": "failed", "allKeyFactsEvaluated": False,
                               "issues": [{"code": "quality_evaluation_unavailable"}]}
            for table in tables_payload:
                table["dataCheck"] = {"status": "unknown", "scope": "frozen_cells", "reasons": ["table_check_failed"]}
            for chart in charts_payload:
                chart["dataCheck"] = {"status": "unknown", "scope": "registered_arrays", "reason": "chart_check_failed"}
                chart["semanticCheck"] = {"status": "unknown", "scope": "registered_fact_projection", "reasons": ["chart_semantic_check_failed"]}
        logger.info(
            "report_source_validation_completed report_id={} revision={} subjects={} tables={} duration_ms={}",
            context.report_id, context.revision, len(subjects), len(tables_payload),
            round((perf_counter() - started) * 1000),
        )
        return {
            "draftSha256": draft_sha256,
            "quality": quality_payload,
            "sourceIssues": [{"resourceId": key, "code": value}
                             for key, value in sorted(source_failures.items())],
            "warnings": warnings,
            "subjects": subjects,
            "summary": summary,
            "tables": tables_payload,
            "tableSummary": table_summary,
            "charts": charts_payload,
            **({"reviewNotices": [
                {**notice.model_dump(mode="json", by_alias=True),
                 "occurrences": len(re.findall(r"待核实[\s*_~]*" + re.escape(f"[[claim:{notice.claim_id}]]"), review_markdown)),
                 "bound": review_markdown.count(f"[[claim:{notice.claim_id}]]") == 1}
                for notice in index.review_notices
            ]} if index.review_notices is not None else {}),
        }

    @staticmethod
    def _evaluate_charts(index: Any, draft_markdown: str) -> list[dict[str, Any]]:
        """图表唯一定位；图题/紧邻图注变化给出软语义 stale。"""
        from ..reporting.trace.chart_subjects import chart_fingerprints, chart_presentations

        charts: list[dict[str, Any]] = []
        files = {item.resource_id: item for item in index.files}
        presentations = chart_presentations(draft_markdown)
        registered_paths: set[str] = set()
        for trace in index.chart_traces:
            image = files.get(trace.image_file_resource_id)
            unique_name = image is not None and sum(
                PurePosixPath(files[item.image_file_resource_id].path).name == PurePosixPath(image.path).name
                for item in index.chart_traces
            ) == 1
            fingerprints = chart_fingerprints(presentations, image.path, allow_filename=unique_name) if image else []
            if image is not None:
                registered_paths.add(image.path)
                # 重名裸文件名已由上述未绑定记录覆盖，不能再追加为新图片。
                # 是否能绑定仍由 unique_name 控制；其他目录的路径仍须独立计数。
                registered_paths.add(PurePosixPath(image.path).name)
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
        # 正文中新出现或未登记来源的图也必须进入覆盖率分母；不赋予冻结来源身份。
        chart_ids = {chart["chartId"] for chart in charts}
        for path in presentations:
            if path in registered_paths:
                continue
            chart_id = "unbound-" + hashlib.sha256(path.encode()).hexdigest()
            while chart_id in chart_ids:
                chart_id = "unbound-" + chart_id
            chart_ids.add(chart_id)
            charts.append({"chartId": chart_id, "imagePath": path,
                           "status": "unbound", "locationSource": path})
        return charts

    async def _evaluate_tables(
        self,
        index: Any,
        context: Any,
        draft_markdown: str,
        fact_value_of: Any,
        table_block_pattern: Any,
        value_matches: Any,
        *,
        fact_unit_of: Any = None,
        fact_selector_valid_of: Any = None,
        source_cell_of: Any = None,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """表格身份重判（计划 6.1）：排序不失效，改值 stale，插删行/删块 unbound。

        行标签→rowKey 的映射来自冻结的原始表格块，旧索引回退到已提交正文；
        列按草稿表头文本 == columnKey 定位，表头被改
        即无法定位 → stale。全部为软语义，不阻断保存。
        """

        from ..reporting.trace.markdown_body import trace_body
        from ..reporting.trace.table_quality import table_value_matches as matches_fact_value

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

        # 保留表格内的行内代码标签；代码块与注释中的整块表格不参与绑定。
        draft_markdown = trace_body(draft_markdown, mask_inline_code=False)
        if committed is not None:
            committed = trace_body(committed, mask_inline_code=False)

        def _blocks(source: str | None) -> dict[str, str]:
            if not source:
                return {}
            blocks: dict[str, str] = {}
            duplicates: set[str] = set()
            for match in table_block_pattern.finditer(source):
                table_id, body = match.group(1), match.group(2)
                if table_id in blocks:
                    duplicates.add(table_id)
                    blocks.pop(table_id)
                elif table_id not in duplicates:
                    blocks[table_id] = body
            # 重复身份没有唯一来源，不能按出现顺序挑选其中一块冒充已验证。
            return blocks

        def _rows(body: str) -> tuple[list[str], list[list[str]]]:
            from markdown_it import MarkdownIt

            # 使用表格语法分列，转义的管道符属于单元格内容，不能直接 split('|')。
            tokens = MarkdownIt().enable("table").parse(body)
            rows: list[list[str]] = []
            in_table = False
            for token in tokens:
                if token.type == "table_open":
                    in_table = True
                elif token.type == "table_close":
                    break
                elif in_table and token.type == "tr_open":
                    rows.append([])
                elif in_table and token.type == "inline" and rows:
                    rows[-1].append("".join(
                        child.content for child in (token.children or ())
                        if child.type in {"text", "code_inline"}
                    ).strip())
            if len(rows) < 2:
                return [], []
            return rows[0][1:], rows[1:]

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
            origin_source = (
                trace_body(trace.origin_markdown, mask_inline_code=False)
                if trace.origin_markdown is not None else committed
            )
            origin_body = (
                _blocks(origin_source).get(trace.table_id)
                if trace.origin_markdown is not None else committed_blocks.get(trace.table_id)
            )
            draft_body = draft_blocks.get(trace.table_id)
            if draft_body is None:
                counts["unbound"] = len(trace.cells)
            else:
                origin_header, origin_rows = _rows(origin_body or "")
                # 期间并集表的缺失月份由服务端登记为空引用并展示“—”。
                # 只豁免原样保留的占位符；事实读取失败或填入数字仍须告警。
                missing_cells = {
                    (key, name)
                    for row, key in zip(origin_rows, trace.row_keys)
                    for column, name in enumerate(origin_header, 1)
                    if column < len(row) and row[column] == "—"
                } if len(origin_rows) == len(trace.row_keys) else set()
                if len(origin_rows) == len(trace.row_keys):
                    label_to_key = {
                        row[0]: key for row, key in zip(origin_rows, trace.row_keys)
                    }
                else:
                    label_to_key = {}
                draft_header, draft_rows = _rows(draft_body)
                # 定位比软校验更保守：重复标签/列名不能选择首个匹配冒充唯一身份。
                # 无冻结表格且已提交正文不可读时，无法确认原始位置，不给定位。
                unique_block = origin_body is not None
                origin_labels = Counter(row[0] for row in origin_rows if row)
                draft_labels = Counter(row[0] for row in draft_rows if row)
                header_counts = Counter(draft_header)
                column_index = {
                    name: position + 1 for position, name in enumerate(draft_header)
                }
                row_by_key: dict[str, list[str]] = {}
                row_positions: dict[str, int] = {}
                copy_rows: list[list[str]] = []
                for position, row in enumerate(draft_rows):
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
                        row_positions[key] = position
                frozen_values: list[tuple[Any, Any, str | None]] = []
                for cell in trace.cells:
                    value: Any = None
                    unit: str | None = None
                    for ref in cell.fact_refs:
                        selector = cell.value_selector or cell.row_key
                        if fact_selector_valid_of is not None and not await fact_selector_valid_of(ref, cell.row_key, selector):
                            continue
                        value = await fact_value_of(ref, selector)
                        if value is not None:
                            if fact_unit_of is not None:
                                unit = await fact_unit_of(ref, selector)
                            break
                    if cell.source_cell is not None and source_cell_of is not None:
                        selected = await source_cell_of(cell.source_cell)
                        if selected is not None:
                            from ..reporting.trace.table_sources import source_cell_text
                            value, unit = source_cell_text(selected['value']), None
                    frozen_values.append((cell, value, unit))
                for cell, fact_value, fact_unit in frozen_values:
                    row = row_by_key.get(cell.row_key)
                    if row is None:
                        counts["unbound"] += 1
                        continue
                    column = column_index.get(cell.column_key)
                    if column is None or column >= len(row):
                        counts["stale"] += 1
                        continue
                    missing_unchanged = (
                        not cell.fact_refs and (cell.row_key, cell.column_key) in missing_cells
                        and row[column] == "—"
                    )
                    cell_status = (
                        "valid" if missing_unchanged or (
                            fact_value is not None and (
                                row[column] == "—" if fact_value == "—"
                                else row[column] == fact_value if cell.source_cell is not None
                                else matches_fact_value(row[column], fact_value, fact_unit, cell.column_key)
                            )
                        ) else "stale"
                    )
                    uniquely_bound = (
                        unique_block and origin_labels[row[0]] == 1
                        and draft_labels[row[0]] == 1
                        and header_counts[cell.column_key] == 1
                        and len(row) == len(draft_header) + 1
                    )
                    if not uniquely_bound:
                        cell_status = "unbound"
                    if uniquely_bound:
                        locations.append({
                            "rowKey": cell.row_key, "columnKey": cell.column_key,
                            "rowIndex": row_positions[cell.row_key], "columnIndex": column,
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
                            for frozen_cell, frozen_value, frozen_unit in frozen_values
                            if frozen_value is not None
                            and matches_fact_value(
                                cell_text, frozen_value, frozen_unit, frozen_cell.column_key
                            )
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
        limitations = list(record.limitations)
        pending = [chain]
        while pending:
            node = pending.pop()
            limitations.extend(node.get("warnings", ()))
            pending.extend(node.get("inputs", ()))
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
            "limitations": list(dict.fromkeys(limitations)),
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

    async def _chart_edit_summaries(self, context: Any) -> dict[str, dict[str, Any]]:
        """按 chartId 聚合改图登记摘要（P3：快捷指令按图形推荐 + 改图历史展示）。

        登记不存在视为空；损坏只降级该展示数据并告警，不影响来源面板其余内容。
        """

        from .chart_edits import load_chart_edit_records

        try:
            records = await load_chart_edit_records(
                self._workspace, context.scope["threadId"], context.markdown_path
            )
        except ValueError as error:
            logger.warning(
                "chart_edit_history_unavailable report={} revision={} error={}",
                context.report_id, context.revision, error,
            )
            return {}
        summaries: dict[str, dict[str, Any]] = {}
        for record in records:
            entry = summaries.setdefault(
                record.chart_id, {"visualForm": None, "editCount": 0, "history": []}
            )
            entry["editCount"] += 1
            # 最新成功的改图决定当前图形形态；按登记追加顺序取最后一条。
            entry["visualForm"] = record.chart.visual_form
            entry["history"].append(
                {
                    "editId": record.edit_id,
                    "instruction": record.instruction[:200],
                    "level": list(record.level),
                    "createdAt": record.created_at,
                }
            )
        for entry in summaries.values():
            entry["history"] = entry["history"][-20:][::-1]
        return summaries

    async def charts(self, context: Any) -> dict[str, Any]:
        """当前 revision 登记了来源的图表清单（有 ChartTraceV1 的图）。"""

        index = await self.require_index(context)
        files = {item.resource_id: item for item in index.files}
        datasets = {item.dataset_id for item in index.datasets}
        edit_summaries = await self._chart_edit_summaries(context)
        charts_payload = []
        for trace in index.chart_traces:
            summary = edit_summaries.get(trace.chart_id, {})
            charts_payload.append(
                {
                    "chartId": trace.chart_id,
                    "datasetIds": list(trace.dataset_ids),
                    "datasetIdsRegistered": all(
                        did in datasets for did in trace.dataset_ids
                    ),
                    "plotDataFileCount": len(trace.plot_data_file_resource_ids),
                    "plotDataKind": "chart_input",
                    "transformNotes": list(trace.transform_notes),
                    # imagePath 供编辑器把正文图片定位到登记图表（AI 改图入口）。
                    "imagePath": files[trace.image_file_resource_id].path,
                    "imageSize": files[trace.image_file_resource_id].size,
                    # AI 改图摘要：visualForm 供快捷指令按图形推荐，editCount 供入口提示。
                    "visualForm": summary.get("visualForm"),
                    "editCount": summary.get("editCount", 0),
                }
            )
        return {"available": True, "charts": charts_payload}

    async def chart_source(
        self,
        context: Any,
        chart_id: str,
        *,
        session_capabilities: CapabilitiesInput = None,
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
        permissions = self._permissions(session_capabilities)
        source_cache: dict[str, Mapping[str, Any]] = {}
        plot_tables: list[dict[str, Any]] = []
        for resource_id in trace.plot_data_file_resource_ids:
            file_ref = files[resource_id]
            content = await self._read_registered_file(
                context, file_ref, max_bytes=8 * 1024 * 1024
            )
            if permissions.blocked_columns:
                source_columns = await self._chart_origin_columns(context, index, content, source_cache)
                if any(is_blocked_column(column, permissions.blocked_columns) for column in source_columns):
                    raise ReportingError("dataset_access_denied", "该图表来源使用当前会话的受限字段。")
            plot_tables.append(
                self._chart_input_payload(
                    content,
                    file_ref=file_ref,
                    limit=preview_limit,
                    offset=preview_offset,
                    blocked_columns=permissions.blocked_columns,
                )
            )
        result = {
            "available": True,
            "chartId": trace.chart_id,
            "datasetIds": list(trace.dataset_ids),
            "transformNotes": list(trace.transform_notes),
            "computationId": trace.computation_id,
            "image": {"size": image_ref.size, "sha256": image_ref.sha256},
            "plotData": plot_tables,
            # AI 改图历史（P3）：登记成功过的改图记录，最新在前；正文未引用的记录同样列出。
            "editHistory": (await self._chart_edit_summaries(context))
            .get(trace.chart_id, {})
            .get("history", []),
        }
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > TRACE_BUDGETS_V1["preview_max_response_bytes"]:
            raise ReportingError("resource_limit_exceeded", "图表来源预览超过资源预算，请缩小每页行数。")
        return result

    async def _chart_origin_columns(
        self, context: Any, index: RevisionTraceIndexV1, content: bytes,
        cache: dict[str, Mapping[str, Any]],
    ) -> frozenset[str]:
        """通用作图列名不能代替权限依据；按已登记的事实哈希追踪原始字段。"""
        from ..reporting.trace.fact_index import fact_entry_from_pointer
        from ..reporting.trace.fact_service import _input_fact_refs
        from ..reporting.workflow.runtime.chart_inputs import ChartInputError, parse_data_path

        denied = "当前会话无法确认该图表的来源字段权限。"
        try:
            plot = json.loads(content)
        except ValueError as error:
            raise ReportingError("snapshot_integrity_failed", "作图数据文件无法解析。") from error
        source = plot.get("source") if isinstance(plot, Mapping) else None
        if not isinstance(source, Mapping) or not isinstance(source.get("dataPath"), str):
            raise ReportingError("dataset_access_denied", denied)
        files = {item.resource_id: item for item in index.files}
        matches = [files[entry.file_resource_id] for entry in index.fact_files
                   if entry.analysis_id == source.get("analysisId")
                   and entry.content_kind == "deterministic_bundle"
                   and files[entry.file_resource_id].sha256 == source.get("sha256")]
        if len(matches) != 1:
            raise ReportingError("dataset_access_denied", denied)
        file_ref = matches[0]
        if file_ref.resource_id not in cache:
            raw = await self._read_registered_file(context, file_ref, max_bytes=16 * 1024 * 1024)
            cache[file_ref.resource_id] = read_fact_document(raw)
        document = cache[file_ref.resource_id]
        if document.get("analysisId") != source.get("analysisId"):
            raise ReportingError("snapshot_integrity_failed", "图表来源事实与登记分析身份不一致。")
        try:
            tokens = parse_data_path(source["dataPath"])
            if len(tokens) < 2 or not isinstance(tokens[1], int):
                raise ChartInputError("未定位到具体事实")
            # 旧事实没有冻结分组字段名，不能凭 group/value 推断原始维度权限。
            if "topGroups" in tokens or "bottomGroups" in tokens:
                raise ChartInputError("分组字段未登记")
            kind, fact = fact_entry_from_pointer(document, f"/{tokens[0]}/{tokens[1]}")
        except (ChartInputError, KeyError) as error:
            raise ReportingError("dataset_access_denied", denied) from error
        required: set[str] = set()

        def collect(entry: Mapping[str, Any]) -> None:
            for key in ("field", "periodField", "leftField", "rightField"):
                if isinstance(entry.get(key), str) and entry[key]:
                    required.add(entry[key])
            if isinstance(entry.get("fieldRef"), str):
                required.add(entry["fieldRef"].rsplit(".", 1)[-1])
            if isinstance(entry.get("scope"), Mapping):
                required.update(entry["scope"])

        collect(fact)
        inputs = _input_fact_refs(document, kind, fact)
        ids = {ref["factId"] for ref in inputs if isinstance(ref.get("factId"), str)}
        metrics = [metric for metric in document.get("metrics", ()) if metric.get("factId") in ids]
        if kind in {"derived", "comparison", "reconciliation"} and (not inputs or len(metrics) != len(inputs)):
            raise ReportingError("dataset_access_denied", denied)
        operand_keys = {
            "derived": ("numeratorMetric", "denominatorMetric"),
            "reconciliation": ("leftMetric", "rightMetric"),
        }.get(kind, ())
        if any(not isinstance(fact.get(key), str) or not any(
            fact[key] in (metric.get("metricCodes") or ()) for metric in metrics
        ) for key in operand_keys):
            raise ReportingError("dataset_access_denied", denied)
        if kind == "comparison" and any(
            not isinstance(fact.get(key), str) or not any(
                metric.get("datasetId") == fact[key] for metric in metrics
            ) for key in ("currentDatasetId", "baselineDatasetId")
        ):
            raise ReportingError("dataset_access_denied", denied)
        for metric in metrics:
            collect(metric)
        if not required:
            raise ReportingError("dataset_access_denied", denied)
        return frozenset(required)

    @staticmethod
    def _chart_input_payload(
        content: bytes,
        *,
        file_ref: Any,
        limit: int,
        offset: int,
        blocked_columns: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        """chart-input/v1 JSON → 有界预览（不暴露工作区路径）。"""

        import json as _json

        try:
            document = _json.loads(content)
        except ValueError:
            raise ReportingError(
                "snapshot_integrity_failed", "作图数据文件无法解析。"
            ) from None
        if not isinstance(document, Mapping):
            raise ReportingError(
                "snapshot_integrity_failed", "作图数据文件结构无效。"
            )
        rows = document.get("rows")
        columns = document.get("columns")
        if (
            not isinstance(rows, list)
            or not isinstance(columns, list)
            or any(not isinstance(column, str) for column in columns)
        ):
            raise ReportingError(
                "snapshot_integrity_failed", "作图数据文件结构无效。"
            )
        # 与数据集整表预览一致：包含受限列时拒绝整份预览，分页也不能绕过。
        if any(is_blocked_column(column, blocked_columns) for column in columns):
            raise ReportingError("dataset_access_denied", "该图表来源包含当前会话的受限列。")
        if len(columns) > TRACE_BUDGETS_V1["preview_max_columns"]:
            raise ReportingError("resource_limit_exceeded", "作图数据列数超过预览上限。")
        if any(len(column.encode("utf-8")) > TRACE_BUDGETS_V1["preview_max_cell_bytes"] for column in columns):
            raise ReportingError("resource_limit_exceeded", "作图数据列名超过预览上限。")
        window = rows[offset : offset + limit]
        for row in window:
            if not isinstance(row, list) or len(row) != len(columns):
                raise ReportingError("snapshot_integrity_failed", "作图数据行与列结构不一致。")
            for value in row:
                if not (value is None or isinstance(value, (str, int, float, bool))) or (
                    isinstance(value, float) and not math.isfinite(value)
                ):
                    raise ReportingError("snapshot_integrity_failed", "作图数据包含无效单元格。")
                if isinstance(value, str) and len(value.encode("utf-8")) > TRACE_BUDGETS_V1["preview_max_cell_bytes"]:
                    raise ReportingError("resource_limit_exceeded", "作图数据单元格超过预览上限。")
        source = document.get("source")
        public_source = {
            key: source[key] for key in ("analysisId", "sha256", "dataPath")
            if isinstance(source.get(key), str)
        } if isinstance(source, Mapping) else None
        result = {
            "fileResourceId": file_ref.resource_id,
            "sha256": file_ref.sha256,
            "size": file_ref.size,
            "role": document.get("role") if isinstance(document.get("role"), str) else None,
            "source": public_source,
            "columns": columns,
            "rowCount": len(rows),
            "offset": offset,
            "limit": limit,
            "rows": window,
            "truncated": offset + len(window) < len(rows),
        }
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > TRACE_BUDGETS_V1["preview_max_response_bytes"]:
            raise ReportingError("resource_limit_exceeded", "作图数据预览超过资源预算，请缩小每页行数。")
        return result

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

    def _permissions(self, capabilities: CapabilitiesInput) -> TracePreviewPermissions:
        resolved = EditorCapabilities.of(capabilities)
        return TracePreviewPermissions(
            blocked_columns=resolved.blocked_columns,
            can_download_original=resolved.download_original,
            can_download_derived=resolved.download_derived,
        )

    @staticmethod
    def _drilldown_enabled(capabilities: CapabilitiesInput) -> bool:
        return EditorCapabilities.of(capabilities).drilldown

    @staticmethod
    def _drilldown_declaration_allowed(declaration: Any, capabilities: CapabilitiesInput) -> bool:
        resolved = EditorCapabilities.of(capabilities)
        if resolved.full:
            return True
        blocked = resolved.blocked_columns
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
        return not any(is_blocked_column(field, blocked) for field in required)

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
