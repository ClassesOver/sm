from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import secrets
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from loguru import logger

from ..reporting.delivery.publishing import (
    ReportArtifactSpec,
    ReportDownloadScope,
    publication_result,
)
from ..reporting.delivery.slides_editing import edit_pptx, inspect_pptx
from ..reporting.models import ReportingError
from ..reporting.workflow.scope import resolve_reporting_workflow_scope
from ..reporting.workflow.state import ReportingCommand, ReportingStateConflict
from .service import ReportEditorContext, ReportEditorSession

_MAX_PPTX_BYTES = 64 * 1024 * 1024
_RECHECKED_LAYOUT_ISSUES = {
    "pptx_layout_audit", "pptx_layout_warning", "pptx_audit_failed", "report_slides_validation_failed",
}


class ReportSlidesEditorService:
    """核验发布身份，在独立草稿中编辑并签发不可变 PPTX 副本。"""

    def __init__(
        self, *, state_repository: Any, workspace_registry: Any, workspace: Any,
        artifact_persistence: Any = None, download_grants: Any = None,
        draft_lock: Callable[[ReportEditorContext], AbstractAsyncContextManager[None]] | None = None,
    ) -> None:
        self.state_repository = state_repository
        self.workspace_registry = workspace_registry
        self.workspace = workspace
        self.artifact_persistence = artifact_persistence
        self.download_grants = download_grants
        self.draft_lock = draft_lock

    async def context_for_session(self, session: ReportEditorSession) -> ReportEditorContext:
        capabilities = session.capabilities
        if not isinstance(capabilities, dict) or capabilities.get("pptx_editor") is not True:
            raise ReportingError("report_slides_permission_denied", "该会话没有幻灯片编辑权限。")
        durable = await self.state_repository.get(session.workflow_run_id)
        contexts = durable.payload.get("reportEditorContexts") if durable is not None else None
        raw = contexts.get(str(session.revision)) if isinstance(contexts, dict) else None
        try:
            context = ReportEditorContext.model_validate(raw)
        except Exception as error:
            raise ReportingError(
                "report_slides_context_missing", "幻灯片编辑上下文不存在。"
            ) from error
        if (
            context.delivery_format != "pptx"
            or context.report_id != session.report_id
            or context.revision != session.revision
            or context.workflow_run_id != session.workflow_run_id
            or not secrets.compare_digest(context.digest(), session.context_sha256)
        ):
            raise ReportingError("report_slides_scope_mismatch", "幻灯片编辑作用域不一致。")
        scope = resolve_reporting_workflow_scope(
            run_id=context.workflow_run_id,
            session_id=context.scope.get("sessionId", ""),
            user_id=context.scope.get("userId"),
            stored_scope=context.scope,
        )
        if scope.workspace_key != context.scope.get("threadId"):
            raise ReportingError("report_slides_scope_mismatch", "幻灯片工作区作用域不一致。")
        self.workspace_registry.resolve(scope)
        current = await self.workspace.ahash_file(scope.workspace_key, context.pptx_path)
        if (
            current.get("missing")
            or current.get("size") != context.pptx_size
            or current.get("sha256") != context.pptx_sha256
        ):
            raise ReportingError("report_slides_identity_changed", "PPTX 文件身份已变化。")
        return context

    async def document_for_session(self, session: ReportEditorSession) -> dict:
        context = await self.context_for_session(session)
        content, digest, validation, _ = await self._current_document(context)
        return await self._document_model(context, content, digest, validation)

    async def save_draft_for_session(
        self, session: ReportEditorSession, *, expected_sha256: str, operations: list[dict],
    ) -> dict:
        context = await self.context_for_session(session)
        async with self._lock(context):
            context = await self.context_for_session(session)
            content, digest, previous_validation, is_draft = await self._current_document(context)
            self._check_expected(expected_sha256, digest)
            try:
                edited, validation = await asyncio.to_thread(edit_pptx, content, operations)
            except ValueError as error:
                raise ReportingError(
                    "report_slides_operation_invalid", "幻灯片编辑操作无效，请重新载入后重试。",
                    details={"reason": str(error)},
                ) from error
            except Exception as error:
                raise ReportingError(
                    "report_slides_engine_unavailable", "幻灯片编辑引擎暂不可用，请稍后重试。",
                ) from error
            validation = self._merge_validation(previous_validation, self._validation(validation))
            new_digest = hashlib.sha256(edited).hexdigest()
            result = await self._document_model(context, edited, new_digest, validation)
            path = self._draft_path(context)
            await self.workspace.awrite_bytes(
                context.scope["threadId"], path, edited, overwrite=is_draft,
                expected_sha256=digest if is_draft else None,
            )
            # 验收记录绑定草稿哈希；记录失败不丢弃已经原子保存的草稿。
            try:
                await self.workspace.awrite_bytes(
                    context.scope["threadId"], path + ".validation.json",
                    json.dumps({"sha256": new_digest, "validation": validation},
                               ensure_ascii=False).encode(), overwrite=True,
                )
            except Exception:
                result["validation"] = self._with_issue(
                    validation, "report_slides_validation_record_failed", "草稿已保存，但验收记录保存失败。",
                )
                logger.opt(exception=True).warning("report_slides_draft_validation_record_failed")
            return result

    async def export_for_session(
        self, session: ReportEditorSession, *, expected_sha256: str, base_url: str,
    ) -> dict:
        context = await self.context_for_session(session)
        if self.artifact_persistence is None or self.download_grants is None:
            raise ReportingError("report_slides_dependency_missing", "幻灯片下载服务尚未配置。")
        async with self._lock(context):
            context = await self.context_for_session(session)
            content, digest, validation, _ = await self._current_document(context)
            self._check_expected(expected_sha256, digest)
            try:
                # 导出不再次改写正文，只使用原生引擎的验收回执。
                _, receipt = await asyncio.to_thread(edit_pptx, content, [])
                validation = self._merge_validation(validation, self._validation(receipt))
            except Exception:
                validation = self._with_issue(
                    validation, "report_slides_validation_failed", "幻灯片验收未完成，已保留可下载的 PPTX。",
                )
                logger.opt(exception=True).warning("report_slides_export_validation_failed")
            path = str(PurePosixPath(context.markdown_path).parent / "slides-exports" / f"{uuid4().hex}.pptx")
            await self.workspace.awrite_bytes(context.scope["threadId"], path, content)
            await self._read_verified_file(context, path, len(content), digest)
            spec = ReportArtifactSpec(artifact="pptx", path=path, size=len(content), sha256=digest)
            revision, validation = await self._register_export(context, spec, validation)
            scope = ReportDownloadScope(
                database=context.scope["database"], user_id=context.scope["userId"],
                company_id=context.scope["companyId"], session_id=context.scope["sessionId"],
                thread_id=context.scope["threadId"], workflow_run_id=context.workflow_run_id,
            )
            try:
                persisted = await self.artifact_persistence.persist_available(
                    scope=scope, report_id=context.report_id, revision=revision, artifacts=(spec,),
                )
                if spec not in persisted:
                    raise ValueError("PPTX 下载副本未保存")
            except Exception as error:
                raise ReportingError(
                    "report_artifact_persistence_failed", "PPTX 已生成并保留，但下载副本保存失败；请重试导出。",
                ) from error
            raw_grant, grant = await self.download_grants.issue(
                scope=scope, report_id=context.report_id, revision=revision,
                pptx_path=spec.path, pptx_size=spec.size, pptx_sha256=spec.sha256,
            )
        logger.info("report_slides_exported report_id={} revision={} validation_ok={}",
                    context.report_id, revision, validation["ok"])
        return {
            **publication_result(
                report_id=context.report_id, revision=revision, raw_grant=raw_grant, grant=grant,
                base_url=base_url.rstrip("/"), editor_raw_grant=None, editor_expires_at=None,
            ),
            "validation": validation,
            **({"publicationGate": copy.deepcopy(context.job["publicationGate"])}
               if "publicationGate" in context.job else {}),
        }

    async def _register_export(
        self, context: ReportEditorContext, spec: ReportArtifactSpec, validation: dict,
    ) -> tuple[int, dict]:
        revision = context.revision + 1
        for attempt in range(3):
            try:
                durable = await self.state_repository.get(context.workflow_run_id)
                contexts = durable.payload["reportEditorContexts"]
                revision = max(context.revision, *(
                    ReportEditorContext.model_validate(raw).revision
                    for raw in contexts.values() if raw.get("reportId") == context.report_id
                )) + 1
                job = copy.deepcopy(context.job)
                job["render"] = {"pptx": {"path": spec.path, "size": spec.size, "sha256": spec.sha256}}
                job["validation"] = copy.deepcopy(validation)
                exported = context.model_copy(update={
                    "revision": revision, "pptx_path": spec.path, "pptx_size": spec.size,
                    "pptx_sha256": spec.sha256, "job": job, "source": "manual",
                    "created_at": datetime.now(UTC),
                })
                await self.state_repository.apply(
                    context.workflow_run_id,
                    ReportingCommand(
                        name="set_report_editor_context",
                        commandId=f"slides-editor-context:{revision}:{exported.digest()}",
                        payload={"context": exported.model_dump(mode="json", by_alias=True)},
                    ),
                    expected_version=durable.state_version,
                )
                return revision, validation
            except ReportingStateConflict:
                if attempt < 2:
                    continue
            except Exception:
                logger.opt(exception=True).warning("report_slides_export_registration_failed")
            break
        return revision, self._with_issue(
            validation, "report_slides_registration_failed", "PPTX 已生成，但新修订登记失败；下载链接仍可使用。",
        )

    def _lock(self, context: ReportEditorContext) -> AbstractAsyncContextManager[None]:
        if self.draft_lock is None:
            raise ReportingError("report_slides_dependency_missing", "幻灯片草稿锁尚未配置。")
        return self.draft_lock(context)

    @staticmethod
    def _draft_path(context: ReportEditorContext) -> str:
        name = hashlib.sha256(str(context.pptx_path).encode()).hexdigest()[:16]
        return str(PurePosixPath(context.markdown_path).parent / f".slides-draft-{name}.pptx")

    async def _read_verified_file(
        self, context: ReportEditorContext, path: str, size: int, digest: str,
    ) -> bytes:
        try:
            content = await self.workspace.read_limited_regular_file(
                context.scope["threadId"], path, max_bytes=min(size, _MAX_PPTX_BYTES),
            )
            if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("PPTX 文件身份已变化")
        except Exception as error:
            raise ReportingError("report_slides_identity_changed", "PPTX 文件身份已变化。") from error
        return content

    async def _current_document(self, context: ReportEditorContext) -> tuple[bytes, str, dict, bool]:
        source = await self._read_verified_file(
            context, context.pptx_path, context.pptx_size, context.pptx_sha256,
        )
        path = self._draft_path(context)
        thread = context.scope["threadId"]
        source_validation = self._validation(context.job.get("validation"))
        if not source_validation["ok"] and not source_validation["issues"]:
            source_validation = self._with_issue(
                source_validation, "report_slides_source_validation_unknown",
                "原发布验收未通过，但未提供具体原因；本次版式验收不能代替原发布验收。",
            )
        if not await self.workspace.apath_exists(thread, path):
            return source, context.pptx_sha256, source_validation, False
        content = await self.workspace.read_limited_regular_file(thread, path, max_bytes=_MAX_PPTX_BYTES)
        digest = hashlib.sha256(content).hexdigest()
        try:
            record = json.loads(await self.workspace.read_limited_regular_file(
                thread, path + ".validation.json", max_bytes=1024 * 1024,
            ))
            if record["sha256"] != digest or not isinstance(record["validation"], dict):
                raise ValueError("草稿验收身份已变化")
            validation = self._validation(record["validation"])
        except Exception:
            validation = self._with_issue(
                {"ok": True, "issues": []}, "report_slides_validation_unavailable", "草稿验收记录不可用，导出时将重新验收。",
            )
        return content, digest, self._merge_validation(source_validation, validation), True

    async def _document_model(
        self, context: ReportEditorContext, content: bytes, digest: str, validation: dict,
    ) -> dict:
        try:
            model = await asyncio.to_thread(inspect_pptx, content)
        except Exception as error:
            raise ReportingError("report_slides_engine_unavailable", "无法读取幻灯片，请稍后重试。") from error
        return {**model, "reportId": context.report_id, "revision": context.revision,
                "sha256": digest, "validation": validation,
                **({"publicationGate": copy.deepcopy(context.job["publicationGate"])}
                   if "publicationGate" in context.job else {})}

    @staticmethod
    def _check_expected(expected: str, current: str) -> None:
        if not isinstance(expected, str) or not secrets.compare_digest(expected.encode(), current.encode()):
            raise ReportingError("report_slides_conflict", "幻灯片草稿已变化，请重新载入后重试。")

    @staticmethod
    def _validation(value: Any) -> dict:
        if (isinstance(value, dict) and isinstance(value.get("ok"), bool)
                and isinstance(value.get("issues"), list)
                and all(isinstance(issue, dict) and isinstance(issue.get("code"), str)
                        for issue in value["issues"])):
            return {"ok": value["ok"], "issues": copy.deepcopy(value["issues"])}
        return {"ok": False, "issues": [{
            "code": "report_slides_validation_unavailable", "message": "幻灯片验收记录不可用。",
        }]}

    @staticmethod
    def _merge_validation(previous: dict, current: dict) -> dict:
        # 原生引擎只重新评估版式；来源、业务及未知失败必须继续保留。
        issues = [issue for issue in previous["issues"]
                  if issue["code"] not in _RECHECKED_LAYOUT_ISSUES]
        if not previous["ok"] and not previous["issues"]:
            issues.append({
                "code": "report_slides_source_validation_unknown",
                "message": "原发布验收未通过，但未提供具体原因；本次版式验收不能代替原发布验收。",
            })
        for issue in current["issues"]:
            if issue not in issues:
                issues.append(issue)
        return {"ok": current["ok"] is True and not issues, "issues": issues}

    @staticmethod
    def _with_issue(validation: dict, code: str, message: str) -> dict:
        issues = list(validation.get("issues", []))
        issue = {"code": code, "message": message}
        if issue not in issues:
            issues.append(issue)
        return {"ok": False, "issues": issues}
