from __future__ import annotations

import asyncio
import base64
import copy
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import stat
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.parse import quote, urlencode
from uuid import uuid4

from agno.run import RunContext
from cryptography.fernet import Fernet, InvalidToken
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..async_utils import complete_cleanup
from ..reporting.delivery.artifacts_v1 import ArtifactFile
from ..reporting.delivery.publishing import (
    ReportArtifactSpec,
    ReportDownloadScope,
    publication_result,
)
from ..reporting.host_workspace import ReportingWorkspaceRegistry, ReportingWorkspaceRouter
from ..reporting.models import ReportingError
from ..reporting.workflow.scope import resolve_reporting_workflow_scope
from ..reporting.workflow.state import ReportingCommand
from ..reporting.workspace import REPORT_JOBS_STATE_KEY
from ..workspace import WorkspaceError, WorkspacePathConflict
from .trace_retention import source_lifecycle, source_lifecycle_lock
from .trace_revisions import rebuild_edited_manifest, snapshot_revision_lineage
from .trace_sources import ReportEditorTraceService

_SOURCE_STATUS_PRIORITY = {"valid": 0, "stale": 1, "unbound": 2, "missing": 3}


def _export_citation_presentations(
    presentations: Any,
    validation: Mapping[str, Any],
    trace_index: Any,
    *,
    public_base_url: str,
    report_id: str,
    revision: int,
    citations: Any = (),
) -> Any:
    """把当前草稿的 subject 状态与新 revision 定位链接投影到来源附录。"""

    if not isinstance(presentations, list):
        return presentations
    status_by_subject = {
        item["subjectId"]: "stale" if item.get("warnings") else item["status"]
        for item in validation.get("subjects", ())
        if isinstance(item, Mapping)
        and isinstance(item.get("subjectId"), str)
        and item.get("status") in _SOURCE_STATUS_PRIORITY
    }
    table_statuses: dict[str, str] = {}
    for item in validation.get("tables", ()):
        if not isinstance(item, Mapping) or not isinstance(item.get("tableId"), str):
            continue
        counts = item.get("cells")
        if not isinstance(counts, Mapping):
            continue
        status = "valid"
        if int(counts.get("unbound", 0) or 0):
            status = "unbound"
        elif int(counts.get("stale", 0) or 0):
            status = "stale"
        if (item.get("copiedCells") or item.get("insertedRows")) and status == "valid":
            status = "stale"
        table_statuses[item["tableId"]] = status
    for subject in trace_index.subject_bindings:
        table_id = subject.locator.table_id
        if subject.subject_kind == "table_cell" and table_id in table_statuses:
            status_by_subject[subject.subject_id] = table_statuses[table_id]

    statuses_by_dataset: dict[str, list[str]] = {}
    for kind in ("subjects", "tables", "charts"):
        for item in validation.get(kind, ()):
            if not isinstance(item, Mapping):
                continue
            status = (
                table_statuses.get(item.get("tableId")) if kind == "tables"
                else "stale" if item.get("warnings") else item.get("status")
            )
            if status not in _SOURCE_STATUS_PRIORITY:
                continue
            for dataset_id in item.get("datasetIds", ()):
                statuses_by_dataset.setdefault(dataset_id, []).append(status)
    datasets_by_citation = {item.citation_id: item.dataset_id for item in citations}

    base_path = (
        f"/reports/v1/editor/{quote(report_id, safe='')}/{revision}"
    )
    rebound: list[dict[str, Any]] = []
    for presentation in presentations:
        if not isinstance(presentation, Mapping):
            rebound.append(presentation)
            continue
        updated = copy.deepcopy(dict(presentation))
        links = updated.get("links")
        statuses = list(statuses_by_dataset.get(
            datasets_by_citation.get(updated.get("citationId")), ()
        ))
        if isinstance(links, list):
            for link in links:
                if not isinstance(link, dict) or not isinstance(link.get("subjectId"), str):
                    continue
                subject_id = link["subjectId"]
                status = status_by_subject.get(subject_id)
                if status is not None:
                    statuses.append(status)
                link["url"] = (
                    f"{public_base_url.rstrip('/')}{base_path}?"
                    f"{urlencode({'subject': subject_id})}"
                )
        if statuses:
            updated["status"] = max(
                statuses, key=lambda item: _SOURCE_STATUS_PRIORITY[item]
            )
        rebound.append(updated)
    return rebound


# job 状态经 _store_job 有 48 KiB 硬上限（引用展示已占 24 KiB 预算）；
# 数据来源附录载荷超预算时显式失败，不静默截断来源。
_MAX_EXPORT_TRACE_SOURCE_BYTES = 16 * 1024


def _build_export_trace_sources(
    trace_index: Any,
    validation: Mapping[str, Any],
    *,
    public_base_url: str,
    report_id: str,
    revision: int,
) -> dict[str, Any]:
    """把冻结追溯索引与草稿校验结果装配成 PDF/Word 数据来源附录载荷。

    编号由渲染器按正文首次出现顺序分配；这里只提供摘要与在线定位，
    claim 按首个 factRef 身份聚合，同一事实被多次引用复用同一来源。
    状态来自当前草稿校验（软语义），不隐藏失效。
    """
    base_path = f"/reports/v1/editor/{quote(report_id, safe='')}/{revision}"

    def summarize(entry: dict[str, Any]) -> dict[str, Any]:
        omitted = dict(entry.get("omittedCounts", {}))
        for field, limit in (("datasetIds", 10), ("methods", 5), ("transformNotes", 10), ("subjectIds", 10), ("links", 10)):
            values = entry.get(field)
            if isinstance(values, list) and len(values) > limit:
                omitted[field] = len(values) - limit
                entry[field] = values[:limit]
        if omitted:
            entry["omittedCounts"] = omitted
        return entry

    def link_of(subject_id: str) -> dict[str, str]:
        return {
            "subjectId": subject_id,
            "url": (
                f"{public_base_url.rstrip('/')}{base_path}?"
                f"{urlencode({'subject': subject_id})}"
            ),
        }

    datasets_payload = {
        dataset.dataset_id: {
            "filename": dataset.filename,
            "businessLabel": dataset.business_label,
            "periodRoles": list(dataset.period_roles),
        }
        for dataset in trace_index.datasets
    }
    subjects_by_claim: dict[str, Mapping[str, Any]] = {
        item["claimId"]: item
        for item in validation.get("subjects", ())
        if isinstance(item, Mapping) and isinstance(item.get("claimId"), str)
    }
    claims_payload: dict[tuple[str, str], dict[str, Any]] = {}
    fact_dataset_ids: dict[tuple[str, str], list[str]] = {}
    for binding in trace_index.subject_bindings:
        if not binding.claim_id or not binding.fact_refs:
            continue
        state = subjects_by_claim.get(binding.claim_id)
        if state is None:
            continue
        reference = binding.fact_refs[0]
        key = (reference.file_resource_id, reference.json_pointer)
        entry = claims_payload.get(key)
        if entry is None:
            entry = {
                "claimId": binding.claim_id,
                "subjectIds": [],
                "links": [],
                "status": "stale" if state.get("warnings") else state.get("status", "unbound"),
                "factValue": state.get("factValue"),
                "unit": state.get("unit"),
                "periods": list(state.get("periods") or ()),
                "formula": state.get("formula"),
                "scope": dict(state.get("scope") or {}),
                "datasetIds": list(state.get("datasetIds") or ()),
            }
            claims_payload[key] = entry
            fact_dataset_ids[key] = entry["datasetIds"]
        else:
            claim_ids = entry.setdefault("claimIds", [entry["claimId"]])
            if binding.claim_id not in claim_ids:
                claim_ids.append(binding.claim_id)
            entry["status"] = max(
                (entry["status"], "stale" if state.get("warnings") else state.get("status", "unbound")),
                key=lambda item: _SOURCE_STATUS_PRIORITY.get(item, 3),
            )
        if (
            binding.subject_id not in entry["subjectIds"]
        ):
            entry["subjectIds"].append(binding.subject_id)
            entry["links"].append(link_of(binding.subject_id))

    table_statuses: dict[str, str] = {}
    table_details: dict[str, Mapping[str, Any]] = {}
    for item in validation.get("tables", ()):
        if not isinstance(item, Mapping) or not isinstance(item.get("tableId"), str):
            continue
        counts = item.get("cells")
        if not isinstance(counts, Mapping):
            continue
        table_details[item["tableId"]] = item
        status = "valid"
        if int(counts.get("unbound", 0) or 0):
            status = "unbound"
        elif int(counts.get("stale", 0) or 0):
            status = "stale"
        if (item.get("copiedCells") or item.get("insertedRows")) and status == "valid":
            status = "stale"
        table_statuses[item["tableId"]] = status
    chart_statuses: dict[str, str] = {}
    for item in validation.get("charts", ()):
        if not isinstance(item, Mapping) or not isinstance(item.get("chartId"), str):
            continue
        if item.get("status") in _SOURCE_STATUS_PRIORITY:
            chart_statuses[item["chartId"]] = item["status"]
    computations = {item.computation_id: item for item in trace_index.computations}
    subjects_by_table: dict[str, list[str]] = {}
    for binding in trace_index.subject_bindings:
        if binding.subject_kind == "table_cell" and binding.locator.table_id:
            subjects_by_table.setdefault(binding.locator.table_id, []).append(
                binding.subject_id
            )
    tables_payload: list[dict[str, Any]] = []
    for table in trace_index.tables:
        detail = table_details.get(table.table_id, {})
        dataset_ids: list[str] = list(detail.get("datasetIds") or ())
        methods: list[str] = list(detail.get("methods") or ())
        for cell in table.cells:
            # 生产表格单元格主要绑 factRefs；数据集身份从同一冻结事实解析，
            # 显式 dataset_ids 与之取并集，附录不因绑定形态丢失源文件。
            for ref in cell.fact_refs:
                for dataset_id in fact_dataset_ids.get(
                    (ref.file_resource_id, ref.json_pointer), ()
                ):
                    if dataset_id not in dataset_ids:
                        dataset_ids.append(dataset_id)
            for dataset_id in cell.dataset_ids:
                if dataset_id not in dataset_ids:
                    dataset_ids.append(dataset_id)
            computation = (
                computations.get(cell.computation_id)
                if cell.computation_id
                else None
            )
            if computation is not None and computation.method not in methods:
                methods.append(computation.method)
        table_subjects = list(dict.fromkeys(subjects_by_table.get(table.table_id, [])))
        tables_payload.append(
            {
                "tableId": table.table_id,
                "subjectIds": table_subjects,
                "status": table_statuses.get(table.table_id, "unbound"),
                "datasetIds": dataset_ids,
                "methods": methods,
                "links": [link_of(subject_id) for subject_id in table_subjects],
            }
        )

    files = {item.resource_id: item for item in trace_index.files}
    subjects_by_chart: dict[str, list[str]] = {}
    for binding in trace_index.subject_bindings:
        if binding.subject_kind in ("chart", "chart_caption") and binding.locator.chart_id:
            subjects_by_chart.setdefault(binding.locator.chart_id, []).append(
                binding.subject_id
            )
    charts_payload: list[dict[str, Any]] = []
    for chart in trace_index.chart_traces:
        chart_subjects = list(dict.fromkeys(subjects_by_chart.get(chart.chart_id, [])))
        image = files.get(chart.image_file_resource_id)
        methods: list[str] = []
        if chart.computation_id:
            computation = computations.get(chart.computation_id)
            if computation is not None:
                methods.append(computation.method)
        charts_payload.append(
            {
                "chartId": chart.chart_id,
                "subjectIds": chart_subjects,
                "status": chart_statuses.get(chart.chart_id, "valid"),
                "imagePath": image.path if image is not None else "",
                "datasetIds": list(chart.dataset_ids),
                "methods": methods,
                "transformNotes": list(chart.transform_notes),
                "unit": chart.axis_unit,
                "links": [link_of(subject_id) for subject_id in chart_subjects],
            }
        )
    payload = {
        "claims": [summarize(item) for item in claims_payload.values()],
        "tables": [summarize(item) for item in tables_payload],
        "charts": [summarize(item) for item in charts_payload],
        "datasets": datasets_payload,
    }
    encoded_size = len(
        json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    )
    if encoded_size > _MAX_EXPORT_TRACE_SOURCE_BYTES:
        raise ReportingError(
            "report_editor_trace_sources_too_large",
            "数据来源附录超出渲染状态边界，请减少正文事实、表格或图表数量后重试。",
        )
    logger.info(
        "report_editor_trace_sources_built claims={} tables={} charts={} "
        "datasets={} bytes={}",
        len(payload["claims"]),
        len(payload["tables"]),
        len(payload["charts"]),
        len(payload["datasets"]),
        encoded_size,
    )
    return payload

# 签发链接默认长期有效（10 年，等价永久；存储列不允许 NULL，用远端日期表达）。
EDITOR_GRANT_TTL = timedelta(days=3650)
EDITOR_SHARE_TTL = timedelta(days=30)
EDITOR_SESSION_TTL = timedelta(hours=8)


class ReportEditorContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    report_id: str = Field(alias="reportId", min_length=1, max_length=256)
    revision: int = Field(ge=1)
    job_id: str = Field(alias="jobId", min_length=1, max_length=256)
    job: dict[str, Any]
    workflow_run_id: str = Field(alias="workflowRunId", min_length=1, max_length=256)
    markdown_path: str = Field(alias="markdownPath", min_length=1, max_length=1024)
    artifact_manifest: ArtifactFile | None = Field(default=None, alias="artifactManifest")
    scope: dict[str, str]
    source: str = Field(default="published", pattern=r"^(published|manual)$")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    note: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def validate_job_identity(self) -> ReportEditorContext:
        if self.job.get("jobId") != self.job_id:
            raise ValueError("报告编辑 job 身份不一致")
        return self

    def digest(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json", by_alias=True, exclude_defaults=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ReportEditorSession:
    report_id: str
    revision: int
    workflow_run_id: str
    context_sha256: str
    expires_at: datetime
    # None 表示完整 editor 会话（兼容旧授权）；分享链接签发时写入受限能力，
    # 例如 {"download_original": False}。B0 权限矩阵按此执行。
    capabilities: dict[str, Any] | None = None


@dataclass(frozen=True)
class ReportEditorDocument:
    path: str
    markdown: str
    sha256: str
    source_revision: int | None = None


class ReportEditorRepository(Protocol):
    async def put_grant(self, jti: str, *, expires_at: datetime) -> None: ...

    async def grant_active(self, jti: str, *, now: datetime) -> bool: ...

    async def put_session(self, session_hash: str, session: ReportEditorSession) -> None: ...

    async def get_session(self, session_hash: str) -> ReportEditorSession | None: ...


class InMemoryReportEditorRepository:
    def __init__(self) -> None:
        self.grants: dict[str, datetime] = {}
        self.sessions: dict[str, ReportEditorSession] = {}

    async def put_grant(self, jti: str, *, expires_at: datetime) -> None:
        self.grants[jti] = expires_at

    async def grant_active(self, jti: str, *, now: datetime) -> bool:
        expires_at = self.grants.get(jti)
        return expires_at is not None and expires_at > now

    async def put_session(self, session_hash: str, session: ReportEditorSession) -> None:
        self.sessions[session_hash] = session

    async def get_session(self, session_hash: str) -> ReportEditorSession | None:
        return self.sessions.get(session_hash)


class ReportEditorGrantService:
    def __init__(
        self,
        repository: ReportEditorRepository,
        *,
        secret: str,
        grant_ttl: timedelta = EDITOR_GRANT_TTL,
        session_ttl: timedelta = EDITOR_SESSION_TTL,
    ) -> None:
        if len(secret.encode()) < 32:
            raise ValueError("报告编辑授权密钥至少需要 32 字节。")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        self._fernet = Fernet(key)
        self._csrf_key = hashlib.sha256(f"report-editor-csrf:{secret}".encode()).digest()
        self.repository = repository
        self.grant_ttl = grant_ttl
        self.session_ttl = session_ttl

    async def issue(
        self, context: ReportEditorContext, *, now: datetime | None = None,
        ttl: timedelta | None = None,
        capabilities: Mapping[str, Any] | None = None,
    ) -> tuple[str, datetime]:
        issued_at = _utc(now or datetime.now(UTC))
        expires_at = issued_at + (ttl if ttl is not None else self.grant_ttl)
        jti = secrets.token_urlsafe(24)
        payload = {
            "contextSha256": context.digest(),
            "expiresAt": int(expires_at.timestamp()),
            "jti": jti,
            "reportId": context.report_id,
            "revision": context.revision,
            "workflowRunId": context.workflow_run_id,
        }
        if capabilities is not None:
            payload["capabilities"] = dict(capabilities)
        raw = self._fernet.encrypt(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).decode()
        await self.repository.put_grant(jti, expires_at=expires_at)
        return raw, expires_at

    async def exchange(
        self, raw_grant: str, *, now: datetime | None = None
    ) -> tuple[str, ReportEditorSession]:
        current = _utc(now or datetime.now(UTC))
        try:
            payload = json.loads(self._fernet.decrypt(raw_grant.encode()))
            expires_at = datetime.fromtimestamp(int(payload["expiresAt"]), tz=UTC)
            jti = str(payload["jti"])
            raw_capabilities = payload.get("capabilities")
            session = ReportEditorSession(
                report_id=str(payload["reportId"]),
                revision=int(payload["revision"]),
                workflow_run_id=str(payload["workflowRunId"]),
                context_sha256=str(payload["contextSha256"]),
                expires_at=current + self.session_ttl,
                capabilities=(
                    dict(raw_capabilities)
                    if isinstance(raw_capabilities, dict)
                    else None
                ),
            )
        except (InvalidToken, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ReportingError("report_editor_grant_invalid", "报告编辑授权无效。") from error
        if expires_at <= current:
            raise ReportingError("report_editor_grant_expired", "报告编辑授权已过期。")
        # 编辑链接是长期入口，可重复打开；每次兑换签发独立的短期会话，服务端只核验
        # 授权仍登记且未过期，不做一次性消费。
        if not await self.repository.grant_active(jti, now=current):
            raise ReportingError("report_editor_grant_invalid", "报告编辑授权无效。")
        raw_session = secrets.token_urlsafe(32)
        await self.repository.put_session(_token_hash(raw_session), session)
        return raw_session, session

    async def lookup_session(
        self, raw_session: str, *, now: datetime | None = None
    ) -> ReportEditorSession:
        current = _utc(now or datetime.now(UTC))
        session = await self.repository.get_session(_token_hash(raw_session))
        if session is None:
            raise ReportingError("report_editor_session_invalid", "报告编辑会话无效。")
        if session.expires_at <= current:
            raise ReportingError("report_editor_session_expired", "报告编辑会话已过期。")
        return session

    def csrf_token(self, raw_session: str) -> str:
        return hmac.new(self._csrf_key, raw_session.encode(), hashlib.sha256).hexdigest()


_MAX_EXPORT_JOBS = 64
_EXPORT_JOB_RETENTION_SECONDS = 3600


@dataclass
class _ExportJob:
    report_id: str
    revision: int
    task: asyncio.Task[dict[str, object]]
    started_at: float
    finished_at: float | None = None


class ReportEditorService:
    def __init__(
        self,
        *,
        state_repository: Any,
        workspace_registry: ReportingWorkspaceRegistry,
        workspace: ReportingWorkspaceRouter,
        report_tools: Any | None = None,
        artifact_persistence: Any | None = None,
        download_grants: Any | None = None,
        editor_grants: ReportEditorGrantService | None = None,
        public_base_url: str | None = None,
        export_timeout_seconds: float = 1200.0,
        trace_cursor_secret: bytes | None = None,
        lineage_panel_enabled: bool = True,
        lineage_download_enabled: bool = True,
        lineage_drilldown_enabled: bool = True,
        lineage_export_sources_enabled: bool = True,
    ) -> None:
        self.state_repository = state_repository
        self.workspace_registry = workspace_registry
        self.workspace = workspace
        self.report_tools = report_tools
        self.artifact_persistence = artifact_persistence
        self.download_grants = download_grants
        self.editor_grants = editor_grants
        self.public_base_url = public_base_url
        self._lineage_features = {
            "panel": bool(lineage_panel_enabled),
            "download": bool(lineage_download_enabled),
            "drilldown": bool(lineage_drilldown_enabled),
            "exportSources": bool(lineage_export_sources_enabled),
        }
        if export_timeout_seconds <= 0:
            raise ValueError("报告编辑导出超时必须大于 0 秒")
        self.export_timeout_seconds = export_timeout_seconds
        self._export_jobs: dict[str, _ExportJob] = {}
        self._draft_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._source_lifecycle_locks: dict[tuple[Any, Any], bool] = {}
        # 预览游标签名密钥：未显式配置时按进程随机生成（重启后旧游标失效，
        # 客户端重新拉取首页即可，不影响数据正确性）。
        self.trace = ReportEditorTraceService(
            workspace,
            cursor_secret=trace_cursor_secret or secrets.token_bytes(32),
        )
        self.trace.exports.source_guard = self._derived_source_guard

    def lineage_features(self) -> dict[str, bool]:
        """返回前端可见的发布开关；关闭展示不修改或删除冻结来源。"""

        return dict(self._lineage_features)

    def _require_lineage_feature(self, name: str) -> None:
        if self._lineage_features[name]:
            return
        code = "drilldown_unavailable" if name == "drilldown" else "source_missing"
        raise ReportingError(code, "该数据追溯能力当前未开放。")

    @asynccontextmanager
    async def _derived_source_guard(self, context):
        async with source_lifecycle_lock(self, context):
            await self._ensure_sources_retained(context)
            yield

    async def context_for_session(self, session: ReportEditorSession) -> ReportEditorContext:
        state = await self.state_repository.get(session.workflow_run_id)
        contexts = state.payload.get("reportEditorContexts") if state is not None else None
        raw = contexts.get(str(session.revision)) if isinstance(contexts, dict) else None
        try:
            context = ReportEditorContext.model_validate(raw)
        except Exception as error:
            raise ReportingError(
                "report_editor_context_missing", "报告编辑上下文不存在。"
            ) from error
        if (
            context.report_id != session.report_id
            or context.workflow_run_id != session.workflow_run_id
            or not secrets.compare_digest(context.digest(), session.context_sha256)
        ):
            raise ReportingError("report_editor_scope_mismatch", "报告编辑上下文作用域不一致。")
        return await self._restore(context)

    @source_lifecycle
    async def read_document(self, expected: ReportEditorContext) -> ReportEditorDocument:
        context = await self._restore(expected)
        async with self._draft_lock(context):
            path, markdown, sha256 = await self._read_revision_markdown(context)
            source = await self._draft_source(context, sha256)
            return ReportEditorDocument(path, markdown, sha256, source.revision)

    async def set_revision_retention(
        self, expected: ReportEditorContext, *, expires_at: datetime | None
    ) -> None:
        async with source_lifecycle_lock(self, expected, exclusive=True):
            await self._set_revision_retention(expected, expires_at=expires_at)

    async def _set_revision_retention(
        self, expected: ReportEditorContext, *, expires_at: datetime | None
    ) -> None:
        """服务端维护入口：缺省永久保留，不使用下载授权过期时间。"""
        if expires_at is not None and expires_at.utcoffset() is None:
            raise ReportingError("report_editor_retention_invalid", "保留截止时间必须包含时区。")
        context = await self._restore(expected)
        state = await self.state_repository.get(context.workflow_run_id)
        if state is None:
            raise ReportingError("report_editor_context_missing", "报告编辑上下文不存在。")
        deadline = expires_at.astimezone(UTC).isoformat() if expires_at is not None else None
        await self.state_repository.apply(
            context.workflow_run_id,
            ReportingCommand(
                name="set_report_editor_retention",
                payload={"context": context.model_dump(mode="json", by_alias=True), "expiresAt": deadline},
                commandId=f"editor-retention:{uuid4().hex}",
            ),
            expected_version=state.state_version,
        )

    async def preview_revision_source_cleanup(
        self, expected: ReportEditorContext, *, now: datetime
    ) -> dict[str, Any]:
        """只读维护预检；结果不能作为稍后删除的授权，执行时必须重新校验。"""
        if now.utcoffset() is None:
            raise ReportingError("report_editor_retention_invalid", "预检时间必须包含时区。")
        context = await self._restore(expected)
        state = await self.state_repository.get(context.workflow_run_id)
        if state is None:
            raise ReportingError("report_editor_context_missing", "报告编辑上下文不存在。")
        try:
            raw_contexts = state.payload["reportEditorContexts"]
            retention = state.payload.get("reportEditorRetention", {})
            if not isinstance(raw_contexts, dict) or not isinstance(retention, dict):
                raise ValueError("登记损坏")
            contexts = {key: ReportEditorContext.model_validate(raw) for key, raw in raw_contexts.items()}
            if not contexts or set(retention) - set(contexts):
                raise ValueError("保留策略缺少版本登记")
            if len({item.markdown_path for item in contexts.values()}) != len(contexts):
                raise ValueError("多个版本共享正文路径")
            expired = set()
            for key, candidate in contexts.items():
                if (
                    key != str(candidate.revision)
                    or candidate.workflow_run_id != context.workflow_run_id
                    or candidate.scope != context.scope
                    or candidate.report_id != context.report_id
                ):
                    raise ValueError("版本作用域不一致")
                policy = retention.get(key)
                if policy is None and key not in retention:
                    continue
                if (
                    not isinstance(policy, dict)
                    or set(policy) != {"contextSha256", "expiresAt"}
                    or policy["contextSha256"] != candidate.digest()
                ):
                    raise ValueError("保留策略身份不一致")
                if policy["expiresAt"] is not None:
                    deadline = datetime.fromisoformat(policy["expiresAt"])
                    if deadline.utcoffset() is None:
                        raise ValueError("保留截止时间缺少时区")
                    if deadline <= now:
                        expired.add(key)
        except (KeyError, ValueError, TypeError) as error:
            raise ReportingError("report_editor_retention_invalid", "来源清理预检登记无效，停止清理。") from error

        protected = set(contexts) - expired
        record_paths = {item.markdown_path for item in contexts.values()}
        record_paths.update(item.artifact_manifest.path for item in contexts.values() if item.artifact_manifest)
        files: dict[str, Any] = {}
        references: dict[str, set[str]] = {}
        # 按固定顺序锁住草稿及来源 sidecar；pending 也保护，避免恢复中途丢失证据。
        async with AsyncExitStack() as locks:
            for candidate in sorted(contexts.values(), key=lambda item: item.markdown_path):
                await locks.enter_async_context(self._draft_lock(candidate))
            for candidate in contexts.values():
                manifest = await self.trace.load_manifest(candidate)
                if manifest is not None and manifest.trace_index is not None:
                    record_paths.add(manifest.trace_index.path)
            for key, candidate in contexts.items():
                origin_path = _draft_origin_path(candidate.markdown_path)
                if await self.workspace.apath_exists(candidate.scope["threadId"], origin_path):
                    try:
                        origin = json.loads(await self.workspace.aread_text(candidate.scope["threadId"], origin_path))
                        if origin["contextSha256"] != candidate.digest():
                            raise ValueError("草稿身份不一致")
                        entries = [origin[name] for name in ("active", "pending") if name in origin]
                        if not entries:
                            raise ValueError("草稿来源未登记")
                        for entry in entries:
                            source_key = str(entry["sourceRevision"])
                            if contexts[source_key].digest() != entry["sourceContextSha256"]:
                                raise ValueError("草稿来源身份不一致")
                            protected.add(source_key)
                    except (KeyError, ValueError, TypeError) as error:
                        raise ReportingError("snapshot_integrity_failed", "草稿来源登记无效，停止清理。") from error
                index = await self.trace.load_index(candidate)
                if index is None:
                    raise ReportingError("report_editor_retention_invalid", "版本缺少权威来源索引，停止清理。")
                for file in index.files:
                    if file.path in record_paths:
                        continue
                    existing = files.get(file.path)
                    if existing is not None and existing != file:
                        raise ReportingError("snapshot_integrity_failed", "共享来源登记身份冲突，停止清理。")
                    files[file.path] = file
                    references.setdefault(file.path, set()).add(key)
            current = await self.state_repository.get(context.workflow_run_id)
            if current is None or current.state_version != state.state_version:
                raise ReportingError("report_editor_conflict", "预检期间报告状态已变化，请重新预检。")
        cleaned = state.payload.get("reportEditorCleanedSourceFiles", {})
        if not isinstance(cleaned, dict):
            raise ReportingError("snapshot_integrity_failed", "已回收文件登记损坏。")
        for path, identity in cleaned.items():
            if path not in files or files[path].model_dump(mode="json", by_alias=True) != identity or references[path] & protected:
                raise ReportingError("snapshot_integrity_failed", "已回收文件出现新引用或身份变化。")
        eligible = [path for path, keys in references.items() if not keys & protected and path not in cleaned]
        return {
            "stateVersion": state.state_version,
            "expiredRevisions": sorted(int(key) for key in expired),
            "protectedRevisions": sorted(int(key) for key in protected),
            "candidateFiles": [files[path].model_dump(mode="json", by_alias=True) for path in sorted(eligible)],
            "protectedPaths": sorted(path for path, keys in references.items() if keys & protected),
            "dryRun": True,
        }

    async def cleanup_revision_sources(
        self, expected: ReportEditorContext, *, now: datetime
    ) -> dict[str, Any]:
        """服务端维护入口：先登记回收意图，再删除精确文件；失败可重启重试。"""
        async with source_lifecycle_lock(self, expected, exclusive=True):
            context = await self._restore(expected)
            state = await self.state_repository.get(context.workflow_run_id)
            if state is None or state.phase != "completed":
                raise ReportingError("report_editor_retention_invalid", "工作流未完成，不能回收来源。")
            plan = await self.preview_revision_source_cleanup(context, now=now)
            pending = state.payload.get("reportEditorSourceCleanup")
            if pending is not None and not isinstance(pending, dict):
                raise ReportingError("snapshot_integrity_failed", "来源回收记录损坏。")
            if isinstance(pending, dict) and pending.get("status") not in {"pending", "completed"}:
                raise ReportingError("snapshot_integrity_failed", "来源回收任务状态损坏。")
            if pending is None or pending.get("status") == "completed":
                revisions = set(plan["expiredRevisions"]) - set(plan["protectedRevisions"])
                retired = state.payload.get("reportEditorRetiredSources", {})
                if not revisions - {int(key) for key in retired} and not plan["candidateFiles"]:
                    return {"status": "completed", "deletedPaths": [], "dryRun": False}
                if not revisions:
                    return {"status": "completed", "deletedPaths": [], "dryRun": False}
                for item in plan["candidateFiles"]:
                    await self.trace._read_registered_file(
                        context, ArtifactFile.model_validate({key: value for key, value in item.items() if key != "resourceId"}),
                        max_bytes=item["size"],
                    )
                contexts = state.payload["reportEditorContexts"]
                cleanup_id = uuid4().hex
                await self.state_repository.apply(context.workflow_run_id, ReportingCommand(
                    name="begin_report_editor_source_cleanup", commandId=f"editor-cleanup:{cleanup_id}",
                    payload={"cleanupId": cleanup_id, "now": now.isoformat(),
                        "contexts": {str(revision): ReportEditorContext.model_validate(contexts[str(revision)]).digest()
                            for revision in revisions}, "files": plan["candidateFiles"]},
                ), expected_version=plan["stateVersion"])
                state = await self.state_repository.get(context.workflow_run_id)
                pending = state.payload["reportEditorSourceCleanup"]
            eligible = {item["path"]: item for item in plan["candidateFiles"]}
            try:
                if not isinstance(pending["files"], list) or not isinstance(pending["contexts"], dict):
                    raise ValueError("回收内容损坏")
                for key, digest in pending["contexts"].items():
                    candidate = ReportEditorContext.model_validate(state.payload["reportEditorContexts"][key])
                    if candidate.digest() != digest or state.payload["reportEditorRetiredSources"][key] != digest:
                        raise ValueError("回收身份变化")
                if any(not isinstance(item, dict) or "path" not in item for item in pending["files"]):
                    raise ValueError("回收文件登记损坏")
            except (KeyError, ValueError, TypeError) as error:
                raise ReportingError("snapshot_integrity_failed", "来源回收意图登记损坏，停止清理。") from error
            if any(eligible.get(item["path"]) != item for item in pending["files"]):
                raise ReportingError("report_editor_conflict", "回收文件出现新引用或身份变化，停止清理。")
            deleted = []
            try:
                for item in pending["files"]:
                    await self.workspace.adelete_registered_file(
                        context.scope["threadId"], item["path"], size=item["size"], sha256=item["sha256"]
                    )
                    deleted.append(item["path"])
            except (OSError, WorkspaceError) as error:
                raise ReportingError("snapshot_integrity_failed", "来源回收未完成，文件身份异常；保留回收记录供重试。") from error
            current = await self.state_repository.get(context.workflow_run_id)
            await self.state_repository.apply(context.workflow_run_id, ReportingCommand(
                name="finish_report_editor_source_cleanup", commandId=f"editor-cleanup-finish:{pending['cleanupId']}",
                payload={"cleanupId": pending["cleanupId"]},
            ), expected_version=current.state_version)
            logger.info("report_editor_sources_cleaned workflow_run_id={} cleanup_id={} files={}",
                context.workflow_run_id, pending["cleanupId"], len(deleted))
            return {"status": "completed", "cleanupId": pending["cleanupId"], "deletedPaths": deleted, "dryRun": False}

    @asynccontextmanager
    async def _draft_lock(self, context: ReportEditorContext) -> AsyncIterator[None]:
        key = (context.scope["threadId"], context.markdown_path)
        lock = self._draft_locks.setdefault(key, asyncio.Lock())
        async with lock:
            identity = self.workspace_registry.get(key[0])
            if identity is None:
                raise ReportingError("report_host_workspace_missing", "报告工作区尚未恢复。")
            # 锁文件不可删除：各 worker 必须始终锁定同一 inode，覆盖正文与来源的联合提交。
            lock_name = ".editor-draft-" + hashlib.sha256(key[1].encode()).hexdigest() + ".lock"
            descriptor = os.open(identity.root / lock_name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise ReportingError("snapshot_integrity_failed", "草稿锁文件不是普通文件。")
                while True:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        await asyncio.sleep(0.05)
                yield
            finally:
                os.close(descriptor)

    async def _draft_source(
        self, context: ReportEditorContext, sha256: str
    ) -> ReportEditorContext:
        path = _draft_origin_path(context.markdown_path)
        thread_id = context.scope["threadId"]
        if not await self.workspace.apath_exists(thread_id, path):
            return context
        try:
            record = json.loads(await self.workspace.aread_text(thread_id, path))
            if record["contextSha256"] != context.digest():
                raise ValueError("draft context changed")
            selected = next(
                entry for entry in (record.get("pending"), record.get("active"))
                if isinstance(entry, dict) and entry.get("sha256") == sha256
            )
            revision = selected["sourceRevision"]
            candidates = await self._candidate_revisions(context)
            source = next(item for item in candidates if item.revision == revision)
            if source.digest() != selected["sourceContextSha256"]:
                raise ValueError("source context changed")
            return source
        except (ValueError, KeyError, TypeError, StopIteration) as error:
            raise ReportingError(
                "snapshot_integrity_failed", "Draft provenance does not match the saved document."
            ) from error

    async def _ensure_sources_retained(self, context: ReportEditorContext) -> None:
        state = await self.state_repository.get(context.workflow_run_id)
        retired = state.payload.get("reportEditorRetiredSources", {}) if state else {}
        if not isinstance(retired, dict):
            raise ReportingError("snapshot_integrity_failed", "来源回收登记损坏。")
        if str(context.revision) in retired:
            if retired[str(context.revision)] != context.digest():
                raise ReportingError("snapshot_integrity_failed", "来源回收登记身份不一致。")
            raise ReportingError("snapshot_expired", "该版本的数据来源已结束保留期，明细不可用。")

    async def _source_context(
        self, expected: ReportEditorContext, *, allow_retired: bool = False
    ) -> ReportEditorContext:
        context = await self._restore(expected)
        async with self._draft_lock(context):
            if await self.workspace.apath_exists(
                context.scope["threadId"], _draft_origin_path(context.markdown_path)
            ):
                _, _, sha256 = await self._read_revision_markdown(context)
                context = await self._draft_source(context, sha256)
            if not allow_retired:
                await self._ensure_sources_retained(context)
            return context

    async def _read_frozen_markdown(self, context: ReportEditorContext) -> tuple[str, str, str]:
        try:
            markdown = await self.workspace.aread_text(context.scope["threadId"], context.markdown_path)
        except WorkspaceError as error:
            raise ReportingError("report_editor_revision_missing", "Historical report is missing.") from error
        sha256 = hashlib.sha256(markdown.encode()).hexdigest()
        manifest = await self.trace.load_manifest(context)
        if manifest is not None:
            identity = manifest.markdown
            if identity.size != len(markdown.encode()) or identity.sha256 != sha256:
                raise ReportingError("snapshot_integrity_failed", "Historical Markdown identity changed.")
        else:
            registered = _registered_markdown_sha(context.job)
            if registered and registered != sha256:
                raise ReportingError("snapshot_integrity_failed", "Historical Markdown identity changed.")
        return context.markdown_path, markdown, sha256

    @source_lifecycle
    async def restore_history(
        self, expected: ReportEditorContext, revision: int, *, expected_sha256: str
    ) -> ReportEditorDocument:
        context = await self._restore(expected)
        source = next(
            (item for item in await self._candidate_revisions(context) if item.revision == revision),
            None,
        )
        if source is None:
            raise ReportingError("report_editor_history_missing", "Historical revision does not exist.")
        await self._ensure_sources_retained(source)
        _, markdown, _ = await self._read_frozen_markdown(source)
        # Verify the registered index before publishing provenance, when available.
        await self.trace.load_index(source)
        async with self._draft_lock(context):
            return await self._save_draft(
                context, markdown=markdown, expected_sha256=expected_sha256, source=source
            )

    async def list_history(
        self,
        expected: ReportEditorContext,
        *,
        limit: int = 20,
        offset: int = 0,
        include_markdown: bool = True,
    ) -> list[dict[str, object]]:
        candidates = await self._candidate_revisions(expected)
        history: list[dict[str, object]] = []
        for candidate in candidates[offset : offset + limit]:
            item = self._history_metadata(candidate)
            if include_markdown:
                try:
                    _path, markdown, sha256 = await self._read_frozen_markdown(candidate)
                except ReportingError as error:
                    # 单个历史修订的工作区文件缺失不应拖垮整个历史列表。
                    logger.warning(
                        "report_editor_history_revision_unreadable report_id={} revision={} "
                        "code={}",
                        candidate.report_id,
                        candidate.revision,
                        error.code,
                    )
                    continue
                item["markdown"] = markdown
                item["sha256"] = sha256
            history.append(item)
        return history

    async def history_page(
        self,
        expected: ReportEditorContext,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, object]:
        candidates = await self._candidate_revisions(expected)
        total = len(candidates)
        page = candidates[offset : offset + limit]
        items = [self._history_metadata(candidate) for candidate in page]
        return {
            "items": items,
            "total": total,
            "hasMore": offset + len(items) < total,
        }

    async def read_history_revision(
        self, expected: ReportEditorContext, revision: int
    ) -> dict[str, object]:
        candidates = await self._candidate_revisions(expected)
        for candidate in candidates:
            if candidate.revision == revision:
                candidate = await self._restore(candidate)
                _path, markdown, sha256 = await self._read_frozen_markdown(candidate)
                sources = await self.trace.sources(candidate)
                return {
                    "revision": candidate.revision,
                    "markdown": markdown,
                    "sha256": sha256,
                    "sources": sources,
                }
        raise ReportingError("report_editor_history_missing", "历史版本不存在。")

    @source_lifecycle
    async def read_asset(self, expected: ReportEditorContext, path: str) -> tuple[bytes, str]:
        context = await self._source_context(expected)
        if "/" not in path and path not in {".", ".."}:
            path = str(PurePosixPath(context.markdown_path).parent / path)
        render = context.job.get("render")
        images = render.get("images") if isinstance(render, dict) else None
        interactive = context.job.get("interactiveCharts")
        registered = (
            next(
                (item for item in images if isinstance(item, dict) and item.get("path") == path),
                None,
            )
            if isinstance(images, list)
            else None
        )
        if registered is None and isinstance(interactive, dict) and path.endswith(".plotly.json"):
            registered = next(
                (
                    item
                    for item in interactive.values()
                    if isinstance(item, dict) and item.get("path") == path
                ),
                None,
            )
        if not isinstance(registered, dict):
            raise ReportingError("report_editor_asset_missing", "报告资源不存在。")
        content, media_type = await self.workspace.afile_bytes(context.scope["threadId"], path)
        if media_type not in {"image/png", "image/jpeg"} and not (
            path.endswith(".plotly.json") and media_type == "application/json"
        ):
            raise ReportingError("report_editor_asset_invalid", "报告资源格式无效。")
        if len(content) != registered.get("size") or hashlib.sha256(
            content
        ).hexdigest() != registered.get("sha256"):
            raise ReportingError("report_editor_asset_changed", "报告资源已变化。")
        return content, media_type

    @source_lifecycle
    async def interactive_charts(self, expected: ReportEditorContext) -> dict[str, str]:
        context = await self._source_context(expected)
        interactive = context.job.get("interactiveCharts")
        if not isinstance(interactive, dict):
            return {}
        return {
            image_path: item["path"]
            for image_path, item in interactive.items()
            if isinstance(image_path, str)
            and isinstance(item, dict)
            and isinstance(item.get("path"), str)
        }

    @source_lifecycle
    async def trace_sources(
        self, expected: ReportEditorContext, session: ReportEditorSession
    ) -> dict[str, Any]:
        if not self._lineage_features["panel"]:
            return {
                "available": False,
                "reason": "feature_disabled",
                "datasets": [],
                "subjects": [],
                "drilldown": {"enabled": False, "metrics": [], "subjects": []},
            }
        context = await self._source_context(expected, allow_retired=True)
        state = await self.state_repository.get(context.workflow_run_id)
        checkpoint = state.payload.get("workflowCheckpoint", {}) if state else {}
        files = checkpoint.get("files", ()) if isinstance(checkpoint, Mapping) else ()
        analysis_context_file = next((item for item in files if isinstance(item, Mapping)
            and str(item.get("path", "")).endswith("/detailed-analysis-context.json")), None)
        result = await self.trace.sources(context, session.capabilities, analysis_context_file=analysis_context_file)
        # 历史事实文件没有名称时，用同一工作流中登记的分析计划补充展示名称。
        plans = state.payload.get("analysisPlans", {}) if state else {}
        if not isinstance(plans, Mapping):
            plans = {}
        datasets_by_analysis: dict[str, set[str]] = {}
        for fact in result.get("facts", ()):
            datasets_by_analysis.setdefault(fact["analysisId"], set()).update(fact.get("datasetIds", ()))
        for fact in result.get("facts", ()):
            plan = plans.get(fact["analysisId"], {})
            if not isinstance(plan, Mapping):
                continue
            dataset_ids = datasets_by_analysis[fact["analysisId"]]
            if not fact.get("analysisName") and dataset_ids and dataset_ids.issubset(plan.get("datasetIds", ())):
                fact["analysisName"] = plan.get("analysisName") or plan.get("step")
        if not self._lineage_features["drilldown"]:
            result["drilldown"] = {"enabled": False, "metrics": [], "subjects": []}
        try:
            await self._ensure_sources_retained(context)
        except ReportingError as error:
            if error.code != "snapshot_expired":
                raise
            result.update(available=False, reason="snapshot_expired")
        return result

    @source_lifecycle
    async def trace_drilldown(
        self,
        expected: ReportEditorContext,
        session: ReportEditorSession,
        subject_id: str,
        *,
        metric_code: str,
        dataset_id: str,
        dimension_code: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._require_lineage_feature("drilldown")
        context = await self._source_context(expected)
        return await self.trace.drilldown(
            context,
            session.capabilities,
            subject_id,
            metric_code=metric_code,
            dataset_id=dataset_id,
            dimension_code=dimension_code,
            limit=limit,
            cursor=cursor,
        )

    @source_lifecycle
    async def trace_drilldown_metric(
        self,
        expected: ReportEditorContext,
        session: ReportEditorSession,
        metric_code: str,
        *,
        dataset_id: str,
        dimension_code: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._require_lineage_feature("drilldown")
        context = await self._source_context(expected)
        return await self.trace.drilldown_metric(
            context,
            session.capabilities,
            metric_code,
            dataset_id=dataset_id,
            dimension_code=dimension_code,
            limit=limit,
            cursor=cursor,
        )

    @source_lifecycle
    async def trace_dataset_preview(
        self,
        expected: ReportEditorContext,
        session: ReportEditorSession,
        dataset_id: str,
        *,
        columns: Sequence[str] | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._require_lineage_feature("panel")
        context = await self._source_context(expected)
        page = await self.trace.preview(
            context,
            session.capabilities,
            dataset_id,
            columns=columns,
            limit=limit,
            cursor=cursor,
        )
        return page.to_payload()

    @source_lifecycle
    async def trace_dataset_columns(
        self,
        expected: ReportEditorContext,
        session: ReportEditorSession,
        dataset_id: str,
    ) -> dict[str, Any]:
        self._require_lineage_feature("panel")
        context = await self._source_context(expected)
        return await self.trace.columns(context, session.capabilities, dataset_id)

    @source_lifecycle
    async def trace_dataset_download(
        self,
        expected: ReportEditorContext,
        session: ReportEditorSession,
        dataset_id: str,
    ) -> tuple[str, str, int]:
        """返回 (本地路径, 安全文件名, 大小)；HTTP 层负责流式响应。"""

        self._require_lineage_feature("download")
        context = await self._source_context(expected)
        path, filename, size = await self.trace.download(
            context, session.capabilities, dataset_id
        )
        return str(path), filename, size

    @source_lifecycle
    async def trace_create_derived_export(
        self,
        expected: ReportEditorContext,
        session: ReportEditorSession,
        dataset_id: str,
        *,
        policy: str,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_lineage_feature("download")
        context = await self._source_context(expected)
        return await self.trace.create_derived_export(
            context,
            session.capabilities,
            dataset_id,
            policy,
            params or {},
        )

    @source_lifecycle
    async def trace_derived_export_status(
        self,
        expected: ReportEditorContext,
        session: ReportEditorSession,
        export_id: str,
    ) -> dict[str, Any]:
        context = await self._source_context(expected)
        return await self.trace.derived_export_status(context, export_id)

    @source_lifecycle
    async def trace_derived_export_download(
        self,
        expected: ReportEditorContext,
        session: ReportEditorSession,
        export_id: str,
    ) -> tuple[str, str, int]:
        self._require_lineage_feature("download")
        context = await self._source_context(expected)
        path, filename, size = await self.trace.derived_export_download(
            context, session.capabilities, export_id
        )
        return str(path), filename, size

    @source_lifecycle
    async def trace_facts(
        self, expected: ReportEditorContext, session: ReportEditorSession
    ) -> dict[str, Any]:
        self._require_lineage_feature("panel")
        context = await self._source_context(expected)
        return await self.trace.facts(context)

    @source_lifecycle
    async def trace_fact_detail(
        self,
        expected: ReportEditorContext,
        session: ReportEditorSession,
        analysis_id: str,
        fact_id: str,
    ) -> dict[str, Any]:
        self._require_lineage_feature("panel")
        context = await self._source_context(expected)
        return await self.trace.fact_detail(context, analysis_id, fact_id)

    @source_lifecycle
    async def trace_charts(
        self, expected: ReportEditorContext, session: ReportEditorSession
    ) -> dict[str, Any]:
        self._require_lineage_feature("panel")
        context = await self._source_context(expected)
        return await self.trace.charts(context)

    @source_lifecycle
    async def trace_chart_source(
        self,
        expected: ReportEditorContext,
        session: ReportEditorSession,
        chart_id: str,
        *,
        preview_limit: int = 20,
        preview_offset: int = 0,
    ) -> dict[str, Any]:
        self._require_lineage_feature("panel")
        context = await self._source_context(expected)
        return await self.trace.chart_source(
            context,
            chart_id,
            preview_limit=preview_limit,
            preview_offset=preview_offset,
        )

    @source_lifecycle
    async def trace_computations(
        self, expected: ReportEditorContext, session: ReportEditorSession
    ) -> dict[str, Any]:
        self._require_lineage_feature("panel")
        context = await self._source_context(expected)
        return await self.trace.computations(context)

    @source_lifecycle
    async def trace_computation_detail(
        self,
        expected: ReportEditorContext,
        session: ReportEditorSession,
        computation_id: str,
        *,
        depth: int = 2,
    ) -> dict[str, Any]:
        self._require_lineage_feature("panel")
        context = await self._source_context(expected)
        return await self.trace.computation_detail(context, computation_id, depth=depth)

    @source_lifecycle
    async def trace_validate(
        self,
        expected: ReportEditorContext,
        session: ReportEditorSession,
        markdown: str,
        draft_sha256: str,
    ) -> dict[str, Any]:
        self._require_lineage_feature("panel")
        context = await self._source_context(expected)
        return await self.trace.validate(context, markdown, draft_sha256)

    @source_lifecycle
    async def save_draft(
        self,
        expected: ReportEditorContext,
        *,
        markdown: str,
        expected_sha256: str,
    ) -> ReportEditorDocument:
        context = await self._restore(expected)
        async with self._draft_lock(context):
            return await self._save_draft(
                context, markdown=markdown, expected_sha256=expected_sha256
            )

    async def _save_draft(
        self,
        context: ReportEditorContext,
        *,
        markdown: str,
        expected_sha256: str,
        source: ReportEditorContext | None = None,
    ) -> ReportEditorDocument:
        thread_id = context.scope["threadId"]
        _, _, current_sha = await self._read_revision_markdown(context)
        if not secrets.compare_digest(current_sha, expected_sha256):
            raise ReportingError("report_editor_conflict", "报告草稿保存冲突，请重新载入。")
        active_source = await self._draft_source(context, current_sha)
        selected = source or active_source
        target_sha = hashlib.sha256(markdown.encode()).hexdigest()
        if target_sha == current_sha and selected != active_source:
            # A hash-only CAS cannot distinguish a lineage-only commit after a crash.
            raise ReportingError("report_editor_conflict", "Identical Markdown has different provenance.")
        origin_path = _draft_origin_path(context.markdown_path)
        has_origin = await self.workspace.apath_exists(thread_id, origin_path)
        if has_origin or source is not None:
            def entry(origin: ReportEditorContext, sha: str) -> dict[str, object]:
                return {"sha256": sha, "sourceRevision": origin.revision,
                        "sourceContextSha256": origin.digest()}

            record = {"contextSha256": context.digest(),
                      "active": entry(active_source, current_sha),
                      "pending": entry(selected, target_sha)}
            await self.workspace.awrite_text(
                thread_id, origin_path, json.dumps(record, sort_keys=True), overwrite=has_origin
            )
        draft_path = _draft_path(context.markdown_path)
        exists = await self.workspace.apath_exists(thread_id, draft_path)
        try:
            if exists:
                await self.workspace.awrite_text(
                    thread_id,
                    draft_path,
                    markdown,
                    overwrite=True,
                    expected_sha256=expected_sha256,
                )
            else:
                source = await self.workspace.ahash_file(thread_id, context.markdown_path)
                if not secrets.compare_digest(str(source.get("sha256")), expected_sha256):
                    raise WorkspacePathConflict("报告源 Markdown 已变化。")
                await self.workspace.awrite_text(thread_id, draft_path, markdown)
        except WorkspacePathConflict as error:
            raise ReportingError(
                "report_editor_conflict", "报告草稿保存冲突，请重新载入。"
            ) from error
        document = ReportEditorDocument(
            draft_path, markdown, hashlib.sha256(markdown.encode()).hexdigest(), selected.revision
        )
        if not secrets.compare_digest(document.sha256, expected_sha256):
            logger.warning(
                "report_editor_manual_save report_id={} revision={} user_id={} "
                "base_markdown_sha256={} edited_markdown_sha256={}",
                context.report_id,
                context.revision,
                context.scope["userId"],
                expected_sha256,
                document.sha256,
            )
        return document

    async def export_revision(
        self,
        expected: ReportEditorContext,
        *,
        expected_sha256: str,
        settings: dict[str, bool] | None = None,
        note: str = "",
        request_id: str | None = None,
    ) -> dict[str, object]:
        correlation_id = request_id or str(uuid4())
        started = time.monotonic()
        logger.info(
            "report_editor_export_started request_id={} report_id={} base_revision={} "
            "target_revision={} user_id={}",
            correlation_id,
            expected.report_id,
            expected.revision,
            expected.revision + 1,
            expected.scope.get("userId", ""),
        )
        try:
            result = await asyncio.wait_for(
                self._export_revision(
                    expected,
                    expected_sha256=expected_sha256,
                    settings=settings,
                    note=note,
                ),
                timeout=self.export_timeout_seconds,
            )
        except TimeoutError as error:
            self._log_export_failure(
                correlation_id, expected, started, "report_editor_export_timeout"
            )
            raise ReportingError(
                "report_editor_export_timeout",
                "报告导出超时，请稍后重试。",
            ) from error
        except ReportingError as error:
            self._log_export_failure(correlation_id, expected, started, error.code)
            raise
        except BaseException as error:
            self._log_export_failure(
                correlation_id,
                expected,
                started,
                type(error).__name__,
                level="ERROR",
                exc_info=True,
            )
            raise
        elapsed_ms = round((time.monotonic() - started) * 1000)
        logger.info(
            "report_editor_export_succeeded request_id={} report_id={} base_revision={} "
            "target_revision={} user_id={} elapsed_ms={}",
            correlation_id,
            expected.report_id,
            expected.revision,
            expected.revision + 1,
            expected.scope.get("userId", ""),
            elapsed_ms,
        )
        return {**result, "requestId": correlation_id}

    async def start_export(
        self,
        expected: ReportEditorContext,
        *,
        expected_sha256: str,
        settings: dict[str, bool] | None = None,
        note: str = "",
        request_id: str | None = None,
    ) -> dict[str, object]:
        """在后台启动导出并立即返回任务标识。

        渲染与验收可能持续数分钟，同步 HTTP 请求会先被网关读超时切断；导出改为服务端
        后台任务，由编辑器轮询 ``export_status``。服务以单 worker 运行，任务状态保存在
        进程内；同一 revision 同时只允许一个导出，避免两个任务争抢 revision N+1。
        """

        self._prune_export_jobs()
        key = (expected.report_id, expected.revision)
        if any(
            (job.report_id, job.revision) == key and not job.task.done()
            for job in self._export_jobs.values()
        ):
            raise ReportingError(
                "report_editor_export_running", "当前版本正在导出，请等待完成后再试。"
            )
        if len(self._export_jobs) >= _MAX_EXPORT_JOBS:
            raise ReportingError("report_editor_export_busy", "导出任务过多，请稍后再试。")
        export_id = request_id or str(uuid4())
        if export_id in self._export_jobs:
            export_id = str(uuid4())
        task = asyncio.create_task(
            self.export_revision(
                expected,
                expected_sha256=expected_sha256,
                settings=settings,
                note=note,
                request_id=export_id,
            ),
            name=f"report-editor-export:{export_id}",
        )
        # 结果由轮询读取；预先取走异常，避免任务结束后无人等待时产生未处理异常告警。
        task.add_done_callback(lambda done: done.cancelled() or done.exception())
        self._export_jobs[export_id] = _ExportJob(
            report_id=expected.report_id,
            revision=expected.revision,
            task=task,
            started_at=time.monotonic(),
        )
        return {"exportId": export_id, "status": "running", "requestId": export_id}

    def export_status(self, expected: ReportEditorContext, export_id: str) -> dict[str, object]:
        job = self._export_jobs.get(export_id)
        if job is None or (job.report_id, job.revision) != (
            expected.report_id,
            expected.revision,
        ):
            raise ReportingError("report_editor_export_missing", "导出任务不存在或已过期。")
        if not job.task.done():
            return {"exportId": export_id, "status": "running", "requestId": export_id}
        if job.finished_at is None:
            job.finished_at = time.monotonic()
        error = (
            ReportingError("report_editor_export_failed", "报告导出失败。")
            if job.task.cancelled()
            else job.task.exception()
        )
        if error is None:
            return {
                "exportId": export_id,
                "status": "succeeded",
                "requestId": export_id,
                "result": job.task.result(),
            }
        if not isinstance(error, ReportingError):
            error = ReportingError("report_editor_export_failed", "报告导出失败。")
        return {
            "exportId": export_id,
            "status": "failed",
            "requestId": export_id,
            "error": {"code": error.code, "message": error.message},
        }

    def _prune_export_jobs(self) -> None:
        now = time.monotonic()
        for export_id, job in list(self._export_jobs.items()):
            if job.task.done():
                if job.finished_at is None:
                    job.finished_at = now
                if now - job.finished_at > _EXPORT_JOB_RETENTION_SECONDS:
                    del self._export_jobs[export_id]

    async def aclose(self) -> None:
        """应用关闭时取消仍在运行的导出，由取消链路终止渲染进程组并清理临时 revision。"""

        running = [job.task for job in self._export_jobs.values() if not job.task.done()]
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)

    @staticmethod
    def _log_export_failure(
        correlation_id: str,
        expected: ReportEditorContext,
        started: float,
        code: str,
        *,
        level: str = "WARNING",
        exc_info: bool = False,
    ) -> None:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        logger.opt(exception=exc_info).log(
            level,
            "report_editor_export_failed request_id={} report_id={} base_revision={} "
            "target_revision={} user_id={} elapsed_ms={} error_code={}",
            correlation_id,
            expected.report_id,
            expected.revision,
            expected.revision + 1,
            expected.scope.get("userId", ""),
            elapsed_ms,
            code,
        )

    @source_lifecycle
    async def _export_revision(
        self,
        expected: ReportEditorContext,
        *,
        expected_sha256: str,
        settings: dict[str, bool] | None = None,
        note: str = "",
    ) -> dict[str, object]:
        context = await self._restore(expected)
        async with self._draft_lock(context):
            path, markdown, sha256 = await self._read_revision_markdown(context)
            source_context = await self._draft_source(context, sha256)
            document = ReportEditorDocument(path, markdown, sha256, source_context.revision)
        await self._ensure_sources_retained(source_context)
        if not secrets.compare_digest(document.sha256, expected_sha256):
            raise ReportingError("report_editor_conflict", "报告草稿已变化，请重新载入。")
        if self.report_tools is None:
            raise RuntimeError("报告编辑导出依赖配置不完整")
        if self.artifact_persistence is None:
            raise RuntimeError("报告编辑导出依赖配置不完整")
        if self.download_grants is None:
            raise RuntimeError("报告编辑导出依赖配置不完整")
        if self.editor_grants is None:
            raise RuntimeError("报告编辑导出依赖配置不完整")
        if self.public_base_url is None:
            raise RuntimeError("报告编辑导出依赖配置不完整")
        report_tools = self.report_tools
        artifact_persistence = self.artifact_persistence
        download_grants = self.download_grants
        editor_grants = self.editor_grants
        public_base_url = self.public_base_url

        scope = resolve_reporting_workflow_scope(
            run_id=context.workflow_run_id,
            session_id=context.scope["sessionId"],
            user_id=context.scope["userId"],
            stored_scope=context.scope,
        )
        session_state: dict[str, Any] = {
            "report_workflow_scope": scope.as_state(),
            REPORT_JOBS_STATE_KEY: {context.job_id: copy.deepcopy(context.job)},
        }
        run_context = RunContext(
            run_id=context.workflow_run_id,
            session_id=scope.workspace_key,
            user_id=scope.user_id,
            session_state=session_state,
        )
        export_settings = {
            key: bool(settings[key])
            for key in ("cover", "toc", "headerFooter", "pageNumbers", "sources")
            if settings and key in settings
        }
        if not self._lineage_features["exportSources"]:
            export_settings["sources"] = False
        if export_settings:
            session_state[REPORT_JOBS_STATE_KEY][context.job_id]["_editorExportSettings"] = {
                **export_settings,
            }
        # 编辑链接长期有效，用户可能从旧修订的链接进入。导出过一次会产生更新的
        # revision；若最新 revision 的 Markdown 与当前草稿一致（用户未再改动），
        # 自动以最新 revision 为基准再次导出，实现重复导出的幂等。只有内容确实
        # 落后于更新版本时才拒绝，必须明确提示改用最新修订继续编辑。
        # 最新 revision 的工作区文件缺失（如历史部署未持久化工作区目录）时无法比对
        # 内容，允许以当前修订为基准继续导出，否则编辑链接会变成打不开、也无法
        # 再导出的死锁。
        candidates = await self._candidate_revisions(context)
        latest_revision = max((candidate.revision for candidate in candidates), default=context.revision)
        if latest_revision > context.revision:
            latest = max(candidates, key=lambda item: item.revision)
            try:
                _, _, latest_sha256 = await self._read_revision_markdown(latest)
            except Exception:
                latest_sha256 = None
            if latest_sha256 is None:
                logger.warning(
                    "report_editor_latest_revision_unreadable report_id={} missing_revision={} "
                    "base_revision={}",
                    context.report_id,
                    latest_revision,
                    context.revision,
                )
            elif secrets.compare_digest(latest_sha256, document.sha256):
                # 后续渲染/登记都按 context.job_id 从 run_context 取 job 状态，
                # 重定基后必须同步换成最新 revision 的 job，否则索引错位。
                context = latest
                session_state[REPORT_JOBS_STATE_KEY][context.job_id] = copy.deepcopy(
                    context.job
                )
            else:
                raise ReportingError(
                    "report_editor_revision_stale",
                    f"当前编辑的是第 {context.revision} 版，已有更新的第 {latest_revision} 版，"
                    "请打开最新版本的编辑链接后再导出。",
                )
        output_path = _next_pdf_path(context)
        revision_path = PurePosixPath(output_path).parent.as_posix()
        if await self.workspace.apath_exists(scope.workspace_key, revision_path):
            raise ReportingError(
                "report_editor_revision_conflict", "新的报告 revision 已存在，请重新载入。"
            )
        cleanup_revision = True
        # 导出在后台运行期间编辑器仍会自动保存草稿；渲染必须基于已校验 SHA 的内容快照，
        # 否则 PDF 可能来自更新后的草稿，而新 revision 保存的仍是导出开始时的 Markdown。
        # 快照与草稿同目录，保证图片等相对资源的解析不变。
        if source_context.revision != context.revision:
            target_job = session_state[REPORT_JOBS_STATE_KEY][context.job_id]
            target_job.setdefault("render", {})["images"] = copy.deepcopy(
                source_context.job.get("render", {}).get("images", [])
            )
            target_job["interactiveCharts"] = copy.deepcopy(
                source_context.job.get("interactiveCharts", {})
            )
        snapshot_path = str(PurePosixPath(source_context.markdown_path).with_name(f".export-{uuid4().hex}.md"))
        await self.workspace.awrite_text(scope.workspace_key, snapshot_path, document.markdown)
        try:
            artifact_manifest = await self.trace.load_manifest(source_context)
            trace_index = None
            render_manifest = None
            if artifact_manifest is not None:
                trace_index = await self.trace.load_index(source_context)
                rebuilt = await rebuild_edited_manifest(
                    self.workspace,
                    scope.workspace_key,
                    manifest=artifact_manifest,
                    index=trace_index,
                    markdown_path=snapshot_path,
                    markdown=document.markdown,
                    target_revision=context.revision + 1,
                )
                render_manifest = rebuilt.model_dump(mode="json", by_alias=True)
            if trace_index is not None:
                validation = await self.trace.validate(
                    source_context, document.markdown, document.sha256
                )
                target_job = session_state[REPORT_JOBS_STATE_KEY][context.job_id]
                if isinstance(target_job.get("_citationPresentations"), list):
                    target_job["_citationPresentations"] = _export_citation_presentations(
                        target_job["_citationPresentations"],
                        validation,
                        trace_index,
                        public_base_url=public_base_url,
                        report_id=context.report_id,
                        revision=context.revision + 1,
                        citations=artifact_manifest.citations,
                    )
                # B8：数据来源附录与引用展示同一次快照联合渲染，编号由渲染器
                # 按正文首次出现顺序分配；无追溯索引的旧报告保持无附录导出。
                target_job["_traceSourcePresentations"] = _build_export_trace_sources(
                    trace_index,
                    validation,
                    public_base_url=public_base_url,
                    report_id=context.report_id,
                    revision=context.revision + 1,
                )
            try:
                rendered = await report_tools._render_report_pair(
                    context.job_id,
                    snapshot_path,
                    output_path,
                    artifact_manifest=render_manifest,
                    run_context=run_context,
                )
            except WorkspacePathConflict as error:
                raise ReportingError(
                    "report_editor_revision_conflict", "新的报告 revision 已存在，请重新载入。"
                ) from error
            finally:
                await self._delete_export_snapshot(scope.workspace_key, snapshot_path)
            if (
                not isinstance(rendered, dict)
                or rendered.get("validation", {}).get("ok") is not True
            ):
                raise ReportingError(
                    "report_artifact_validation_failed", "PDF/Word 联合验收未通过。"
                )
            next_revision = context.revision + 1
            word_path = str(PurePosixPath(output_path).with_suffix(".docx"))
            pdf_identity = await self.workspace.ahash_file(scope.workspace_key, output_path)
            word_identity = await self.workspace.ahash_file(scope.workspace_key, word_path)
            markdown_path = str(
                PurePosixPath(output_path).with_name(PurePosixPath(context.markdown_path).name)
            )
            try:
                await self.workspace.awrite_text(
                    scope.workspace_key, markdown_path, document.markdown
                )
            except WorkspacePathConflict as error:
                cleanup_revision = False
                raise ReportingError(
                    "report_editor_revision_conflict", "新的报告 revision 已存在，请重新载入。"
                ) from error

            download_scope = ReportDownloadScope(
                database=scope.database,
                user_id=scope.user_id,
                company_id=scope.company_id,
                session_id=scope.session_id,
                thread_id=scope.workspace_key,
                workflow_run_id=scope.run_id,
            )
            artifacts = (
                ReportArtifactSpec(
                    artifact="pdf",
                    path=output_path,
                    size=int(pdf_identity["size"]),
                    sha256=str(pdf_identity["sha256"]),
                ),
                ReportArtifactSpec(
                    artifact="word",
                    path=word_path,
                    size=int(word_identity["size"]),
                    sha256=str(word_identity["sha256"]),
                ),
            )
            await artifact_persistence.persist(
                scope=download_scope,
                report_id=context.report_id,
                revision=next_revision,
                artifacts=artifacts,
            )
            stored_jobs = (run_context.session_state or {}).get(REPORT_JOBS_STATE_KEY, {})
            next_job = stored_jobs.get(context.job_id) if isinstance(stored_jobs, dict) else None
            if not isinstance(next_job, dict):
                raise ReportingError("report_editor_job_invalid", "报告编辑 job 状态无效。")
            render_record = next_job.get("render")
            rendered_markdown = (
                render_record.get("markdown") if isinstance(render_record, dict) else None
            )
            if (
                not isinstance(render_record, dict)
                or not isinstance(rendered_markdown, dict)
                or rendered_markdown.get("sha256") != document.sha256
            ):
                raise ReportingError(
                    "report_editor_conflict", "导出渲染内容与已校验草稿不一致，请重新导出。"
                )
            # 渲染快照随后即被删除；新 revision 的权威 Markdown 是刚写入的 markdown_path。
            render_record["markdown"] = {**rendered_markdown, "path": markdown_path}
            copied = await self._copy_revision_assets(
                scope.workspace_key,
                next_job,
                source_root=PurePosixPath(source_context.markdown_path).parent,
                target_root=PurePosixPath(markdown_path).parent,
            )
            next_manifest_identity = None
            if artifact_manifest is not None:
                path_map = dict(copied)
                if trace_index is not None:
                    source_root = PurePosixPath(source_context.markdown_path).parent
                    target_root = PurePosixPath(markdown_path).parent
                    for file in trace_index.files:
                        if file.resource_id == trace_index.markdown_file_resource_id:
                            continue
                        try:
                            relative = PurePosixPath(file.path).relative_to(source_root)
                            target = target_root / relative
                        except ValueError:
                            target = target_root / "trace-resources" / file.path
                        path_map[file.path] = target.as_posix()
                awaitable_manifest = rebuilt
                next_markdown = ArtifactFile(
                    path=markdown_path, mediaType="text/markdown",
                    size=len(document.markdown.encode()), sha256=document.sha256,
                )
                _, next_manifest_identity = await snapshot_revision_lineage(
                    self.workspace, scope.workspace_key,
                    manifest=awaitable_manifest, index=trace_index,
                    markdown_file=next_markdown, target_revision=next_revision,
                    path_map=path_map,
                    manifest_path=str(PurePosixPath(markdown_path).with_name("artifact-manifest.json")),
                )
            next_context = ReportEditorContext(
                reportId=context.report_id,
                revision=next_revision,
                jobId=context.job_id,
                workflowRunId=context.workflow_run_id,
                markdownPath=markdown_path,
                artifactManifest=next_manifest_identity,
                job=next_job,
                scope=scope.as_state(),
                source="manual",
                createdAt=datetime.now(UTC),
                note=note,
            )
            durable = await self.state_repository.get(context.workflow_run_id)
            if durable is None:
                raise ReportingError("report_editor_context_missing", "报告编辑上下文不存在。")
            await self.state_repository.apply(
                context.workflow_run_id,
                ReportingCommand(
                    name="set_report_editor_context",
                    payload={"context": next_context.model_dump(mode="json", by_alias=True)},
                    commandId=f"editor-context:{next_revision}:{next_context.digest()}",
                ),
                expected_version=durable.state_version,
            )
            # durable 编辑上下文已提交：之后签发授权失败不得再删除 revision 文件，
            # 否则历史里会留下一个已提交却没有 Markdown/图片的版本。
            cleanup_revision = False
            raw_download, download_grant = await download_grants.issue(
                scope=download_scope,
                report_id=context.report_id,
                revision=next_revision,
                pdf_path=output_path,
                pdf_size=int(pdf_identity["size"]),
                pdf_sha256=str(pdf_identity["sha256"]),
                word_path=word_path,
                word_size=int(word_identity["size"]),
                word_sha256=str(word_identity["sha256"]),
            )
            raw_editor, editor_expires_at = await editor_grants.issue(next_context)
        except BaseException:
            await self._delete_export_snapshot(scope.workspace_key, snapshot_path)
            if cleanup_revision:
                await self._cleanup_export_revision(
                    self.workspace, scope.workspace_key, revision_path
                )
            raise
        logger.warning(
            "report_editor_manual_exported report_id={} base_revision={} revision={} "
            "user_id={} markdown_sha256={}",
            context.report_id,
            context.revision,
            next_revision,
            scope.user_id,
            document.sha256,
        )
        return publication_result(
            report_id=context.report_id,
            revision=next_revision,
            raw_grant=raw_download,
            grant=download_grant,
            base_url=public_base_url,
            editor_raw_grant=raw_editor,
            editor_expires_at=editor_expires_at,
        )

    async def _copy_revision_assets(
        self,
        thread_id: str,
        job: dict[str, Any],
        *,
        source_root: PurePosixPath,
        target_root: PurePosixPath,
    ) -> dict[str, str]:
        copied: dict[str, str] = {}

        async def copy_identity(identity: dict[str, Any]) -> None:
            source = identity.get("path")
            if not isinstance(source, str):
                return
            try:
                relative = PurePosixPath(source).relative_to(source_root)
            except ValueError:
                return
            target = (target_root / relative).as_posix()
            if source not in copied:
                content, _media_type = await self.workspace.afile_bytes(thread_id, source)
                if len(content) != identity.get("size") or not secrets.compare_digest(
                    hashlib.sha256(content).hexdigest(), str(identity.get("sha256", ""))
                ):
                    raise ReportingError("report_editor_asset_changed", "报告资源已变化。")
                await self.workspace.awrite_bytes(thread_id, target, content)
                copied[source] = target
            identity["path"] = copied[source]

        render = job.get("render")
        images = render.get("images") if isinstance(render, dict) else None
        if isinstance(images, list):
            for image in images:
                if isinstance(image, dict):
                    await copy_identity(image)

        interactive = job.get("interactiveCharts")
        if isinstance(interactive, dict):
            migrated: dict[str, Any] = {}
            for image_path, identity in interactive.items():
                if not isinstance(image_path, str):
                    continue
                if isinstance(identity, dict):
                    await copy_identity(identity)
                migrated[copied.get(image_path, image_path)] = identity
            job["interactiveCharts"] = migrated
        return copied

    async def _delete_export_snapshot(self, thread_id: str, path: str) -> None:
        try:
            await complete_cleanup(self.workspace.adelete_file(thread_id, path))
        except Exception as error:
            logger.warning(
                "report_editor_export_snapshot_cleanup_failed path={} error_type={}",
                path,
                type(error).__name__,
            )

    @staticmethod
    async def _cleanup_export_revision(
        workspace: ReportingWorkspaceRouter, thread_id: str, revision_path: str
    ) -> None:
        try:
            await workspace.adelete_file(thread_id, revision_path, recursive=True)
        except BaseException as error:
            logger.warning(
                "report_editor_revision_cleanup_failed path={} error_type={}",
                revision_path,
                type(error).__name__,
            )

    async def _candidate_revisions(
        self, expected: ReportEditorContext
    ) -> list[ReportEditorContext]:
        context = await self._restore(expected)
        state = await self.state_repository.get(context.workflow_run_id)
        contexts = state.payload.get("reportEditorContexts") if state is not None else None
        candidates: list[ReportEditorContext] = []
        if isinstance(contexts, dict):
            for raw in contexts.values():
                try:
                    candidate = ReportEditorContext.model_validate(raw)
                except Exception:
                    continue
                if (
                    candidate.report_id == context.report_id
                    and candidate.workflow_run_id == context.workflow_run_id
                    and candidate.scope == context.scope
                ):
                    candidates.append(candidate)
        return sorted(candidates, key=lambda item: item.revision)

    async def _read_revision_markdown(self, candidate: ReportEditorContext) -> tuple[str, str, str]:
        draft_path = _draft_path(candidate.markdown_path)
        path = (
            draft_path
            if await self.workspace.apath_exists(candidate.scope["threadId"], draft_path)
            else candidate.markdown_path
        )
        try:
            markdown = await self.workspace.aread_text(candidate.scope["threadId"], path)
        except WorkspaceError as error:
            # 工作区文件丢失（例如历史部署未持久化工作区目录）时给出可读的 404，
            # 避免 WorkspaceError 冒泡成 500。
            raise ReportingError(
                "report_editor_revision_missing",
                f"第 {candidate.revision} 版报告内容已不存在，请改用最新版本的编辑链接。",
            ) from error
        return path, markdown, hashlib.sha256(markdown.encode()).hexdigest()

    @staticmethod
    def _history_metadata(candidate: ReportEditorContext) -> dict[str, object]:
        return {
            "revision": candidate.revision,
            "source": candidate.source,
            "createdAt": candidate.created_at.isoformat() if candidate.created_at else None,
            "note": candidate.note,
            "sha256": _registered_markdown_sha(candidate.job),
        }

    async def _restore(self, expected: ReportEditorContext) -> ReportEditorContext:
        state = await self.state_repository.get(expected.workflow_run_id)
        contexts = state.payload.get("reportEditorContexts") if state is not None else None
        raw = contexts.get(str(expected.revision)) if isinstance(contexts, dict) else None
        try:
            context = ReportEditorContext.model_validate(raw)
        except Exception as error:
            raise ReportingError(
                "report_editor_context_missing", "报告编辑上下文不存在。"
            ) from error
        if context != expected:
            raise ReportingError("report_editor_scope_mismatch", "报告编辑上下文作用域不一致。")
        scope = resolve_reporting_workflow_scope(
            run_id=context.workflow_run_id,
            session_id=context.scope.get("sessionId", ""),
            user_id=context.scope.get("userId"),
            stored_scope=context.scope,
        )
        self.workspace_registry.resolve(scope)
        return context


def _draft_path(markdown_path: str) -> str:
    source = PurePosixPath(markdown_path)
    return str(source.parent / "draft" / source.name)


def _draft_origin_path(markdown_path: str) -> str:
    source = PurePosixPath(markdown_path)
    return str(source.parent / "draft" / f".{source.name}.origin.json")


def _registered_markdown_sha(job: dict[str, Any]) -> str:
    render = job.get("render")
    markdown = render.get("markdown") if isinstance(render, dict) else None
    if isinstance(markdown, dict):
        return str(markdown.get("sha256", ""))
    return ""


def _next_pdf_path(context: ReportEditorContext) -> str:
    render = context.job.get("render")
    pdf = render.get("pdf") if isinstance(render, dict) else None
    if not isinstance(pdf, dict) or "path" not in pdf:
        raise ReportingError("report_editor_job_invalid", "报告编辑 job 缺少当前 PDF revision。")
    path = PurePosixPath(str(pdf["path"]))
    if path.suffix.lower() != ".pdf" or path.parent.name != f"revision-{context.revision}":
        raise ReportingError("report_editor_job_invalid", "报告编辑 job 缺少当前 PDF revision。")
    return str(path.parent.with_name(f"revision-{context.revision + 1}") / path.name)


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
