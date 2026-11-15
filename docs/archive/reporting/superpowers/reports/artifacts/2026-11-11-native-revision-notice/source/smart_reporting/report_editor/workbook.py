from __future__ import annotations

import hashlib
import json
import secrets
from copy import deepcopy
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from zipfile import ZipFile

from loguru import logger

from ..reporting.delivery.office_engine import run_office_engine
from ..reporting.delivery.publishing import ReportArtifactSpec, ReportDownloadScope
from ..reporting.delivery.xlsx import inspect_workbook, patch_workbook
from ..reporting.models import ReportingError
from ..reporting.workflow.scope import resolve_reporting_workflow_scope
from ..reporting.workflow.state import ReportingCommand
from ._file_identity import read_verified_file
from .revision_notice import add_workbook_revision_notice
from .revisions import apply_editor_command, next_manual_revision, revision_file_path
from .service import ReportEditorContext, ReportEditorSession


class ReportWorkbookEditorService:
    """Identity-bound workbook drafts; saving always creates a separate revision."""

    def __init__(
        self, *, state_repository: Any, workspace_registry: Any, workspace: Any,
        editor_grants: Any = None, artifact_persistence: Any = None,
        download_grants: Any = None, public_base_url: str = "",
    ) -> None:
        self.state_repository = state_repository
        self.workspace_registry = workspace_registry
        self.workspace = workspace
        self.editor_grants = editor_grants
        self.artifact_persistence = artifact_persistence
        self.download_grants = download_grants
        self.public_base_url = public_base_url.rstrip("/")

    async def context_for_session(self, session: ReportEditorSession) -> ReportEditorContext:
        return await self._context_for_capability(session, "xlsx_editor")

    async def download_for_session(self, session: ReportEditorSession) -> tuple[ReportEditorContext, bytes]:
        context = await self._context_for_capability(session, "xlsx_download", verify_file=False)
        return context, await self._read_verified(context)

    async def file_for_session(self, session: ReportEditorSession) -> tuple[ReportEditorContext, bytes]:
        context = await self._context_for_capability(session, "xlsx_editor", verify_file=False)
        return context, await self._read_verified(context)

    async def _context_for_capability(
        self, session: ReportEditorSession, capability: str, *, verify_file: bool = True,
    ) -> ReportEditorContext:
        if not isinstance(session.capabilities, dict) or session.capabilities.get(capability) is not True:
            raise ReportingError("report_workbook_permission_denied", "该会话没有工作簿编辑权限。")
        state = await self.state_repository.get(session.workflow_run_id)
        contexts = state.payload.get("reportEditorContexts", {}) if state is not None else {}
        try:
            context = ReportEditorContext.model_validate(contexts.get(str(session.revision)))
        except Exception as error:
            raise ReportingError("report_workbook_context_missing", "工作簿编辑上下文不存在。") from error
        if (context.delivery_format != "xlsx" or context.report_id != session.report_id
            or context.revision != session.revision or context.workflow_run_id != session.workflow_run_id
            or not secrets.compare_digest(context.digest(), session.context_sha256)):
            raise ReportingError("report_workbook_scope_mismatch", "工作簿编辑作用域不一致。")
        scope = resolve_reporting_workflow_scope(
            run_id=context.workflow_run_id, session_id=context.scope.get("sessionId", ""),
            user_id=context.scope.get("userId"), stored_scope=context.scope,
        )
        if scope.workspace_key != context.scope.get("threadId"):
            raise ReportingError("report_workbook_scope_mismatch", "工作簿工作区作用域不一致。")
        self.workspace_registry.resolve(scope)
        if verify_file:
            await self._read_verified(context)
        return context

    async def _read_verified(self, context: ReportEditorContext) -> bytes:
        return await read_verified_file(
            self.workspace, context.scope, context.xlsx_path or "",
            size=context.xlsx_size, sha256=context.xlsx_sha256,
            error_code="report_workbook_identity_changed", format_name="XLSX",
        )

    @staticmethod
    def _operations(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list) or len(value) > 500 or any(not isinstance(op, dict) for op in value):
            raise ReportingError("report_workbook_edit_invalid", "工作簿修改内容无效。")
        return value

    async def snapshot_for_session(self, session: ReportEditorSession, operations: Any = None) -> dict[str, Any]:
        context = await self.context_for_session(session)
        source = await self._read_verified(context)
        ops = self._operations(operations if operations is not None else [])
        try:
            snapshot = await run_office_engine(patch_workbook, source, ops) if ops else source
            model = await run_office_engine(inspect_workbook, snapshot)
        except Exception as error:
            raise ReportingError("report_workbook_edit_invalid", "工作簿修改无法应用，未保存草稿已保留。") from error
        return {"reportId": context.report_id, "revision": context.revision,
                "sha256": context.xlsx_sha256,
                "snapshotSha256": hashlib.sha256(json.dumps(
                    {"sourceSha256": context.xlsx_sha256, "operations": ops},
                    sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
                ).encode()).hexdigest(),
                "snapshotFileSha256": hashlib.sha256(snapshot).hexdigest(),
                "workbook": model, "sources": context.job.get("workbookSources", [])}

    async def preview_operations(self, session: ReportEditorSession, operations: Any, proposed: Any) -> dict[str, Any]:
        return await self.snapshot_for_session(session, [*self._operations(operations), *self._operations(proposed)])

    async def save_revision(self, session: ReportEditorSession, payload: Any) -> dict[str, Any]:
        context = await self.context_for_session(session)
        if not isinstance(payload, dict) or payload.get("expectedSha256") != context.xlsx_sha256:
            raise ReportingError("report_workbook_conflict", "XLSX 已发生变化，请重新载入。")
        operations = self._operations(payload.get("operations", []))
        source = await self._read_verified(context)
        try:
            revised = await run_office_engine(patch_workbook, source, operations)
        except Exception as error:
            raise ReportingError("report_workbook_edit_invalid", "工作簿修改无法应用，未保存草稿已保留。") from error
        lineage_issues: list[dict[str, str]] = []
        embedded_sources = None
        try:
            embedded_sources = self._source_mapping(source)
            if embedded_sources is not None:
                revised = self._mark_sources_unverified(revised, embedded_sources, context.xlsx_sha256)
        except Exception:
            lineage_issues.append({"code": "workbook_source_mapping_failed", "message": "工作簿来源映射读取或更新失败，追溯信息待核验。"})
            try:
                revised = self._drop_source_mapping(revised)
            except Exception:
                lineage_issues.append({"code": "workbook_source_mapping_unavailable",
                    "message": "新文件中的旧来源标记无法移除，不代表当前支持结论；文件仍可下载，请勿据此认定已核验。"})
        revision, revision_issues = await next_manual_revision(self.state_repository, context)
        lineage_issues.extend(revision_issues)
        try:
            revised = await run_office_engine(add_workbook_revision_notice, revised,
                revision=revision, parent_revision=context.revision)
        except Exception:
            lineage_issues.append({"code": "workbook_revision_notice_unavailable",
                "message": "XLSX 已保存，但文件内修订核验说明未能更新；本修订仍待核验，文件可下载。"})
        revised_path = revision_file_path(context.xlsx_path or "report.xlsx", revision, suffix=".xlsx")
        await self.workspace.awrite_bytes(context.scope["threadId"], revised_path, revised, overwrite=False)
        actual = await self.workspace.ahash_file(context.scope["threadId"], revised_path)
        digest = hashlib.sha256(revised).hexdigest()
        if actual.get("size") != len(revised) or actual.get("sha256") != digest:
            raise ReportingError("report_workbook_identity_unavailable", "新修订 XLSX 身份无法核验。")
        issues: list[dict[str, str]] = [
            *lineage_issues,
            {"code": "workbook_semantic_verification_pending", "message": "新修订尚未重新进行业务语义验收，不继承旧版本验收结论。"},
        ]
        try:
            model = await run_office_engine(inspect_workbook, revised)
            if not model.get("sheets"):
                raise ValueError("no_sheets")
        except Exception as error:
            logger.warning("report_workbook_validation_failed error_type={}", type(error).__name__)
            issues.append({"code": "workbook_read_validation_failed", "message": "XLSX 已保存，工作簿可读性验收失败。"})
        job = deepcopy(context.job)
        sources = deepcopy(job.get("workbookSources", embedded_sources.get("sources", {}) if isinstance(embedded_sources, dict) else []))
        if operations:
            issues.append({"code": "workbook_sources_need_verification", "message": "编辑值与原始证据分开保留，来源关联需重新核验。"})
            if isinstance(sources, list):
                for item in sources:
                    if isinstance(item, dict):
                        item["verificationStatus"] = "needs_verification"
            elif isinstance(sources, dict):
                sources["verificationStatus"] = "needs_verification"
                for item in sources.get("cells", []):
                    if isinstance(item, dict):
                        item["verificationStatus"] = "needs_verification"
        job.update({"revision": revision, "xlsxPath": revised_path, "xlsxSize": len(revised),
                    "xlsxSha256": digest, "workbookSources": sources,
                    "validation": {"ok": not issues, "issues": list(issues)}})
        scope = self._download_scope(context)
        if self.artifact_persistence is not None:
            try:
                stored = await self.artifact_persistence.persist_available(
                    scope=scope, report_id=context.report_id, revision=revision,
                    artifacts=(ReportArtifactSpec(artifact="xlsx", path=revised_path, size=len(revised), sha256=digest),),
                )
                if not stored:
                    raise RuntimeError("artifact_not_persisted")
            except Exception:
                issues.append({"code": "report_workbook_persistence_failed", "message": "XLSX 已保存，持久化下载副本暂不可用。"})
        download_url = editor_url = ""
        if self.download_grants is not None:
            try:
                raw, _ = await self.download_grants.issue(
                    scope=scope, report_id=context.report_id, revision=revision,
                    xlsx_path=revised_path, xlsx_size=len(revised), xlsx_sha256=digest,
                )
                download_url = f"{self.public_base_url}/reports/v1/download/{raw}/xlsx"
            except Exception:
                issues.append({"code": "report_workbook_download_grant_failed", "message": "XLSX 已保存，下载授权暂未签发。"})
        job["validation"] = {"ok": not issues, "issues": list(issues)}
        next_context = ReportEditorContext(
            reportId=context.report_id, revision=revision, jobId=context.job_id,
            analysisContextFile=context.analysis_context_file,
            workflowRunId=context.workflow_run_id, markdownPath=context.markdown_path,
            job=job, scope=context.scope, source="manual", createdAt=datetime.now(UTC),
            note="工作簿编辑", deliveryFormat="xlsx", xlsxPath=revised_path,
            xlsxSize=len(revised), xlsxSha256=digest,
        )
        context_registered = False
        try:
            await apply_editor_command(self.state_repository, context.workflow_run_id, ReportingCommand(
                name="set_report_editor_context", payload={"context": next_context.model_dump(mode="json", by_alias=True)},
                commandId=f"workbook-context:{revision}:{digest}",
            ))
            context_registered = True
        except Exception:
            issues.append({"code": "report_workbook_context_failed", "message": "XLSX 已保存，新修订编辑上下文登记失败。"})
        if self.editor_grants is not None and context_registered:
            if not download_url:
                try:
                    raw, _ = await self.editor_grants.issue(next_context, capabilities={"xlsx_download": True})
                    download_url = f"{self.public_base_url}/reports/v1/workbooks/download/{raw}"
                except Exception:
                    issues.append({"code": "report_workbook_download_grant_failed", "message": "XLSX 已保存，备用下载授权暂未签发。"})
            try:
                raw, _ = await self.editor_grants.issue(next_context, capabilities={"xlsx_editor": True})
                editor_url = f"{self.public_base_url}/reports/v1/workbooks/open/{raw}"
            except Exception:
                issues.append({"code": "report_workbook_editor_grant_failed", "message": "XLSX 已保存，新修订编辑入口暂不可用。"})
        return {"reportId": context.report_id, "revision": revision, "revisionRegistered": context_registered,
                "xlsx": {"path": revised_path, "size": len(revised), "sha256": digest,
                         **({"downloadUrl": download_url} if download_url else {})},
                **({"editor": {"openUrl": editor_url}} if editor_url else {}),
                "validation": {"ok": not issues, "issues": issues}}

    @staticmethod
    def _source_mapping(content: bytes) -> dict[str, Any] | None:
        with ZipFile(BytesIO(content)) as package:
            try:
                encoded = package.read("smart-reporting/source-mapping.json")
            except KeyError:
                return None
        mapping = json.loads(encoded)
        if not isinstance(mapping, dict):
            raise ReportingError("report_workbook_sources_invalid", "工作簿来源映射无效。")
        return mapping

    @staticmethod
    def _mark_sources_unverified(content: bytes, mapping: dict[str, Any], parent_sha256: str | None) -> bytes:
        updated = deepcopy(mapping)
        updated["verificationStatus"] = "needs_verification"
        updated["sourceWorkbookSha256"] = parent_sha256
        # Original evidence values remain intact, distinct from revised cell values.
        sources = updated.get("sources")
        if isinstance(sources, dict):
            sources["verificationStatus"] = "needs_verification"
            for cell in sources.get("cells", []):
                if isinstance(cell, dict):
                    cell["verificationStatus"] = "needs_verification"
            for claim in sources.get("claims", []):
                if isinstance(claim, dict) and isinstance(claim.get("support"), dict):
                    claim["support"].update({
                        "supportStatus": "unverified", "evidenceRefs": [],
                        "reason": "manual_revision_requires_verification",
                    })
        result = BytesIO()
        with ZipFile(BytesIO(content)) as original, ZipFile(result, "w") as target:
            for info in original.infolist():
                if info.filename != "smart-reporting/source-mapping.json":
                    target.writestr(info, original.read(info.filename))
            target.writestr("smart-reporting/source-mapping.json", json.dumps(updated, ensure_ascii=False, allow_nan=False))
        return result.getvalue()

    @staticmethod
    def _drop_source_mapping(content: bytes) -> bytes:
        result = BytesIO()
        with ZipFile(BytesIO(content)) as original, ZipFile(result, "w") as target:
            for info in original.infolist():
                if info.filename != "smart-reporting/source-mapping.json":
                    target.writestr(info, original.read(info.filename))
        return result.getvalue()

    @staticmethod
    def _download_scope(context: ReportEditorContext) -> ReportDownloadScope:
        return ReportDownloadScope(
            database=context.scope["database"], user_id=context.scope["userId"],
            company_id=context.scope["companyId"], session_id=context.scope["sessionId"],
            thread_id=context.scope["threadId"], workflow_run_id=context.workflow_run_id,
        )
