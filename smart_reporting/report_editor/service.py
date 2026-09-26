from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Protocol
from uuid import uuid4

from agno.run import RunContext
from cryptography.fernet import Fernet, InvalidToken
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, model_validator

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
from ..workspace import WorkspacePathConflict

# 签发链接默认长期有效（10 年，等价永久；存储列不允许 NULL，用远端日期表达）。
EDITOR_GRANT_TTL = timedelta(days=3650)
EDITOR_SESSION_TTL = timedelta(hours=8)


class ReportEditorContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    report_id: str = Field(alias="reportId", min_length=1, max_length=256)
    revision: int = Field(ge=1)
    job_id: str = Field(alias="jobId", min_length=1, max_length=256)
    job: dict[str, Any]
    workflow_run_id: str = Field(alias="workflowRunId", min_length=1, max_length=256)
    markdown_path: str = Field(alias="markdownPath", min_length=1, max_length=1024)
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


@dataclass(frozen=True)
class ReportEditorDocument:
    path: str
    markdown: str
    sha256: str


class ReportEditorRepository(Protocol):
    async def put_grant(self, jti: str, *, expires_at: datetime) -> None: ...

    async def consume_grant(self, jti: str, *, now: datetime) -> bool: ...

    async def put_session(self, session_hash: str, session: ReportEditorSession) -> None: ...

    async def get_session(self, session_hash: str) -> ReportEditorSession | None: ...


class InMemoryReportEditorRepository:
    def __init__(self) -> None:
        self.grants: dict[str, tuple[datetime, bool]] = {}
        self.sessions: dict[str, ReportEditorSession] = {}

    async def put_grant(self, jti: str, *, expires_at: datetime) -> None:
        self.grants[jti] = (expires_at, False)

    async def consume_grant(self, jti: str, *, now: datetime) -> bool:
        record = self.grants.get(jti)
        if record is None or record[1] or record[0] <= now:
            return False
        self.grants[jti] = (record[0], True)
        return True

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
        self, context: ReportEditorContext, *, now: datetime | None = None
    ) -> tuple[str, datetime]:
        issued_at = _utc(now or datetime.now(UTC))
        expires_at = issued_at + self.grant_ttl
        jti = secrets.token_urlsafe(24)
        payload = {
            "contextSha256": context.digest(),
            "expiresAt": int(expires_at.timestamp()),
            "jti": jti,
            "reportId": context.report_id,
            "revision": context.revision,
            "workflowRunId": context.workflow_run_id,
        }
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
            session = ReportEditorSession(
                report_id=str(payload["reportId"]),
                revision=int(payload["revision"]),
                workflow_run_id=str(payload["workflowRunId"]),
                context_sha256=str(payload["contextSha256"]),
                expires_at=current + self.session_ttl,
            )
        except (InvalidToken, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ReportingError("report_editor_grant_invalid", "报告编辑授权无效。") from error
        if expires_at <= current:
            raise ReportingError("report_editor_grant_expired", "报告编辑授权已过期。")
        if not await self.repository.consume_grant(jti, now=current):
            raise ReportingError("report_editor_grant_used", "报告编辑授权已使用。")
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
        export_timeout_seconds: float = 120.0,
    ) -> None:
        self.state_repository = state_repository
        self.workspace_registry = workspace_registry
        self.workspace = workspace
        self.report_tools = report_tools
        self.artifact_persistence = artifact_persistence
        self.download_grants = download_grants
        self.editor_grants = editor_grants
        self.public_base_url = public_base_url
        if export_timeout_seconds <= 0:
            raise ValueError("报告编辑导出超时必须大于 0 秒")
        self.export_timeout_seconds = export_timeout_seconds

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

    async def read_document(self, expected: ReportEditorContext) -> ReportEditorDocument:
        context = await self._restore(expected)
        path, markdown, sha256 = await self._read_revision_markdown(context)
        return ReportEditorDocument(path, markdown, sha256)

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
                _path, markdown, sha256 = await self._read_revision_markdown(candidate)
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
                _path, markdown, sha256 = await self._read_revision_markdown(candidate)
                return {
                    "revision": candidate.revision,
                    "markdown": markdown,
                    "sha256": sha256,
                }
        raise ReportingError("report_editor_history_missing", "历史版本不存在。")

    async def read_asset(self, expected: ReportEditorContext, path: str) -> tuple[bytes, str]:
        context = await self._restore(expected)
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

    async def interactive_charts(self, expected: ReportEditorContext) -> dict[str, str]:
        context = await self._restore(expected)
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

    async def save_draft(
        self,
        expected: ReportEditorContext,
        *,
        markdown: str,
        expected_sha256: str,
    ) -> ReportEditorDocument:
        context = await self._restore(expected)
        thread_id = context.scope["threadId"]
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
            draft_path, markdown, hashlib.sha256(markdown.encode()).hexdigest()
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
            self._log_export_failure(correlation_id, expected, started, "report_editor_export_timeout")
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

    async def _export_revision(
        self,
        expected: ReportEditorContext,
        *,
        expected_sha256: str,
        settings: dict[str, bool] | None = None,
        note: str = "",
    ) -> dict[str, object]:
        context = await self._restore(expected)
        document = await self.read_document(context)
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
        run_context = RunContext(
            run_id=context.workflow_run_id,
            session_id=scope.workspace_key,
            user_id=scope.user_id,
            session_state={
                "report_workflow_scope": scope.as_state(),
                REPORT_JOBS_STATE_KEY: {context.job_id: copy.deepcopy(context.job)},
            },
        )
        if settings:
            run_context.session_state[REPORT_JOBS_STATE_KEY][context.job_id]["_editorExportSettings"] = {
                key: bool(settings[key])
                for key in ("cover", "toc", "headerFooter", "pageNumbers")
                if key in settings
            }
        output_path = _next_pdf_path(context)
        revision_path = PurePosixPath(output_path).parent.as_posix()
        if await self.workspace.apath_exists(scope.workspace_key, revision_path):
            raise ReportingError(
                "report_editor_revision_conflict", "新的报告 revision 已存在，请重新载入。"
            )
        cleanup_revision = True
        try:
            try:
                rendered = await report_tools._render_report_pair(
                    context.job_id,
                    document.path,
                    output_path,
                    artifact_manifest=None,
                    run_context=run_context,
                )
            except WorkspacePathConflict as error:
                raise ReportingError(
                    "report_editor_revision_conflict", "新的报告 revision 已存在，请重新载入。"
                ) from error
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
            stored_jobs = run_context.session_state.get(REPORT_JOBS_STATE_KEY, {})
            next_job = stored_jobs.get(context.job_id) if isinstance(stored_jobs, dict) else None
            if not isinstance(next_job, dict):
                raise ReportingError("report_editor_job_invalid", "报告编辑 job 状态无效。")
            await self._copy_revision_assets(
                scope.workspace_key,
                next_job,
                source_root=PurePosixPath(context.markdown_path).parent,
                target_root=PurePosixPath(markdown_path).parent,
            )
            next_context = ReportEditorContext(
                reportId=context.report_id,
                revision=next_revision,
                jobId=context.job_id,
                workflowRunId=context.workflow_run_id,
                markdownPath=markdown_path,
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
    ) -> None:
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

    async def _read_revision_markdown(
        self, candidate: ReportEditorContext
    ) -> tuple[str, str, str]:
        draft_path = _draft_path(candidate.markdown_path)
        path = (
            draft_path
            if await self.workspace.apath_exists(candidate.scope["threadId"], draft_path)
            else candidate.markdown_path
        )
        markdown = await self.workspace.aread_text(candidate.scope["threadId"], path)
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
