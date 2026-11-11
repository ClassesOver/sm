"""原生文件分支：沿用可信报告会话，独立保存文件和授权身份。"""

from __future__ import annotations

import hashlib
import secrets
import subprocess
from time import perf_counter
from typing import Any, Literal

from loguru import logger
from pydantic import ValidationError
from .native_pdf_contract import PDF_CONFIRMATION_KINDS, pdf_review_issues

from ..reporting.delivery.artifacts_v1 import ArtifactFile
from ..reporting.delivery.docx_native import inspect_docx, patch_docx
from ..reporting.delivery.office_engine import engine_dir, run_office_engine
from ..reporting.delivery.pdf_native import inspect_pdf, patch_pdf, patch_pdf_with_receipt
from ..reporting.models import ReportingError
from ..reporting.workflow.scope import ReportingWorkflowScope
from ..workspace import WorkspacePathConflict
from ._file_identity import read_verified_file
from .capabilities import EditorCapabilities
from .native_models import (
    NATIVE_ARTIFACT_MEDIA,
    NATIVE_MEDIA,
    NativeEditorContext,
    NativeFormat,
    NativeScope,
    NativeSource,
    native_digest,
)
from .service import ReportEditorGrantService, ReportEditorSession

_MAX_FILE_BYTES = 24 * 1024 * 1024
_MEDIA = NATIVE_MEDIA


def bind_native_workspace(workspace: Any, scope: NativeScope) -> str:
    """根据已签名四维身份重建专属 registry 绑定；不借用原报告 workspace。"""
    digest = native_digest(scope.model_dump(mode="json", by_alias=True))
    key = f"native-workspace-{digest}"
    workspace.registry.resolve(
        ReportingWorkflowScope(
            run_id=f"native:{digest}",
            external_run_id=f"native:{digest}",
            session_id=f"native:{digest}",
            caller_thread_id=scope.thread_id,
            user_id=scope.user_id,
            database=scope.database,
            company_id=scope.company_id,
            thread_lease_key=f"native-thread-{digest}",
            workspace_key=key,
        )
    )
    return key


class NativeEditorService:
    def __init__(
        self,
        workspace: Any,
        repository: Any,
        grants: ReportEditorGrantService,
        *,
        report_editor: Any,
        docx_enabled: bool = False,
        pdf_enabled: bool = False,
        office_enabled: bool = False,
        pdf_text_enabled: bool = False,
        publication: Any = None,
    ):
        self.workspace, self.repository, self.grants = workspace, repository, grants
        self.report_editor, self.publication = report_editor, publication
        self.docx_enabled, self.pdf_enabled = docx_enabled, pdf_enabled
        self.office_enabled = office_enabled
        self.pdf_text_enabled = pdf_text_enabled

    def is_enabled(self, format: NativeFormat) -> bool:
        return {"docx": self.docx_enabled, "pdf": self.pdf_enabled,
                "xlsx": self.office_enabled, "pptx": self.office_enabled}[format]

    def require_enabled(self, format: NativeFormat) -> None:
        if not self.is_enabled(format):
            raise ReportingError("native_feature_disabled", "该格式的原生编辑尚未开放。")

    @staticmethod
    def capabilities(context: NativeEditorContext) -> dict[str, Any]:
        return {
            "native_editor": True,
            "native_download": True,
            "format": context.format,
            "scope": context.scope.model_dump(mode="json", by_alias=True),
        }

    async def open_report(
        self, session: ReportEditorSession, *, format: NativeFormat, request_id: str
    ) -> dict[str, Any]:
        started = perf_counter()
        self.require_enabled(format)
        if format not in {"docx", "pdf"}:
            raise ReportingError("native_format_invalid", "工作簿和幻灯片报告沿用现有编辑入口。")
        if not EditorCapabilities.of(
            session.capabilities
        ).full or session.workflow_run_id.startswith("native:"):
            raise ReportingError("native_permission_denied", "分享会话不能创建独立原生编辑分支。")
        context = await self.report_editor.context_for_session(session)
        if context.delivery_format != "document":
            raise ReportingError("native_format_invalid", "仅文档报告可以派生 Word/PDF 分支。")
        try:
            scope = NativeScope.model_validate(
                {key: context.scope[key] for key in ("database", "companyId", "userId", "threadId")}
            )
            label = "word" if format == "docx" else "pdf"
            raw = context.job["render"][label]
            identity = ArtifactFile.model_validate({**raw, "mediaType": _MEDIA[format]})
        except (KeyError, TypeError, ValidationError) as error:
            raise ReportingError(
                "native_source_missing", "当前报告修订没有该格式的已登记产物。"
            ) from error
        if identity.size > _MAX_FILE_BYTES:
            raise ReportingError(
                "native_file_too_large", "文件超过 24 MiB 在线编辑上限，请使用原下载链接。"
            )
        content = await read_verified_file(
            self.report_editor.workspace,
            context.scope,
            identity.path,
            size=identity.size,
            sha256=identity.sha256,
            error_code="native_source_changed",
            format_name=format.upper(),
        )
        key = bind_native_workspace(self.workspace, scope)
        # 稳定来源身份与requestId绑定副本路径，重试读取相同字节而非覆盖原件。
        copy_id = native_digest(
            {
                "scope": scope.model_dump(),
                "reportId": context.report_id,
                "revision": context.revision,
                "workflowRunId": context.workflow_run_id,
                "source": identity.model_dump(mode="json"),
                "requestId": request_id,
            }
        )
        path = f"native/sources/{copy_id}/original.{format}"
        try:
            await self.workspace.awrite_bytes(key, path, content)
        except WorkspacePathConflict:
            pass
        copied = identity.model_copy(update={"path": path})
        await read_verified_file(
            self.workspace,
            {"threadId": key},
            copied.path,
            size=copied.size,
            sha256=copied.sha256,
            error_code="native_source_changed",
            format_name=format.upper(),
        )
        source = NativeSource(
            format=format,
            origin="report",
            sourceFile=copied,
            reportId=context.report_id,
            workflowRunId=context.workflow_run_id,
            revision=context.revision,
        )
        document = await self.repository.create_from_source(
            source, scope=scope, request_id=request_id
        )
        revision = await self.repository.get_revision(document.document_id, 1, scope=scope)
        if revision is None or revision.context is None:
            raise ReportingError("native_document_not_found", "原生修订尚未登记。")
        grant, expires = await self.grants.issue(
            revision.context, capabilities=self.capabilities(revision.context)
        )
        logger.bind(
            format=format, document_id=document.document_id, revision=revision.context.revision,
            elapsed_ms=round((perf_counter() - started) * 1000, 1), outcome="success",
        ).info("native_report_open")
        return {
            "documentId": document.document_id,
            "revision": 1,
            "parentRevision": None,
            "editor": {"url": f"/reports/v1/native/open/{grant}", "expiresAt": expires.isoformat()},
        }

    async def context_for_session(self, session: ReportEditorSession) -> NativeEditorContext:
        caps = session.capabilities or {}
        if (
            caps.get("native_editor") is not True
            or session.workflow_run_id != f"native:{session.report_id}"
        ):
            raise ReportingError("native_permission_denied", "该会话没有原生编辑权限。")
        try:
            scope = NativeScope.model_validate(caps.get("scope"))
        except ValidationError as error:
            raise ReportingError("native_permission_denied", "原生会话作用域无效。") from error
        revision = await self.repository.get_revision(
            session.report_id, session.revision, scope=scope
        )
        if revision is None or revision.status != "saved" or revision.context is None:
            raise ReportingError("native_document_not_found", "原生文档修订不存在。")
        context = revision.context
        if (
            context.document_id != session.report_id
            or context.revision != session.revision
            or context.scope != scope
            or caps.get("format") != context.format
            or not secrets.compare_digest(context.digest(), session.context_sha256)
        ):
            raise ReportingError("native_permission_denied", "原生会话与文档身份不一致。")
        bind_native_workspace(self.workspace, context.scope)
        return context

    async def read_file(self, context: NativeEditorContext) -> bytes:
        key = bind_native_workspace(self.workspace, context.scope)
        identity = context.source_file
        if identity.size > _MAX_FILE_BYTES:
            raise ReportingError("native_file_too_large", "文件超过 24 MiB 在线编辑上限。")
        return await read_verified_file(
            self.workspace,
            {"threadId": key},
            identity.path,
            size=identity.size,
            sha256=identity.sha256,
            error_code="native_source_changed",
            format_name=context.format.upper(),
        )

    async def preview(
        self,
        context: NativeEditorContext,
        *,
        expected_sha256: str,
        operations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        started = perf_counter()
        self.require_enabled(context.format)
        text_edits = context.format == "pdf" and any(op.get("kind") in {"replaceText", "insertText"} for op in operations)
        if text_edits and not self.pdf_text_enabled:
            raise ReportingError("native_pdf_text_disabled", "PDF 原位文字编辑尚未开放。")
        content = await self.read_file(context)
        if not secrets.compare_digest(context.source_file.sha256, expected_sha256):
            raise ReportingError("native_source_changed", "原生草稿来源已变化，请刷新后重试。")
        engines: dict[NativeFormat, Literal["slides", "workbook", "pdf"]] = {
            "docx": "slides", "pdf": "pdf", "xlsx": "workbook", "pptx": "slides",
        }
        script = {"docx": "edit-docx", "pdf": "cli", "xlsx": "cli", "pptx": "edit-pptx"}[context.format]
        root = engine_dir(engines[context.format])
        if not (
            (root / "dist" / f"{script}.mjs").is_file()
            or (root / "node_modules/.bin/tsx").is_file()
        ):
            raise ReportingError("native_engine_unavailable", "原生编辑引擎尚未部署。")
        inspect = inspect_docx if context.format == "docx" else inspect_pdf
        patch = patch_docx if context.format == "docx" else patch_pdf
        if context.format in {"xlsx", "pptx"}:
            from functools import partial

            from .native_office import inspect_office, patch_office
            inspect = partial(inspect_office, context.format)
            patch = partial(patch_office, context.format)
        try:
            receipt = None
            # PDF 预览一律走回执路径：每种修改（含绘图、图章、空白页、涂黑、合并/拆分页面）都返回绑定实际输出的确认摘要。
            if text_edits or (context.format == "pdf" and operations):
                receipt = await run_office_engine(patch_pdf_with_receipt, content, operations)
                edited = receipt["content"]
            else:
                edited = await run_office_engine(patch, content, operations) if operations else content
            if context.format == "pdf":
                model = await run_office_engine(inspect_pdf, edited, include_text=self.pdf_text_enabled)
            else:
                model = await run_office_engine(inspect, edited)
        except ReportingError:
            raise
        except ValueError as error:
            raise ReportingError("native_operations_invalid", str(error)) from error
        except (OSError, subprocess.SubprocessError) as error:
            raise ReportingError(
                "native_engine_unavailable", "原生编辑引擎无法执行，请稍后重试。"
            ) from error
        result = {
            "sourceSha256": context.source_file.sha256,
            "draftSha256": hashlib.sha256(edited).hexdigest(),
            "model": model,
            **({key: receipt[key] for key in ("previewDigest", "skippedOperations", "appliedOperationIndices", "pendingNoteMapping") if key in receipt} if receipt is not None else {}),
            **({"reviewIssues": pdf_review_issues(receipt)} if receipt is not None and context.format == 'pdf' else {}),
        }
        logger.bind(
            format=context.format, document_id=context.document_id, revision=context.revision,
            operation_count=len(operations),
            skipped_count=len(result.get("skippedOperations", ())),
            elapsed_ms=round((perf_counter() - started) * 1000, 1), outcome="success",
        ).info("native_preview")
        return result

    async def render_tree(
        self, context: NativeEditorContext, *, expected_sha256: str,
        operations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if context.format != "pptx":
            raise ReportingError("native_format_invalid", "只有幻灯片支持画布预览。")
        self.require_enabled(context.format)
        if expected_sha256 != context.source_file.sha256:
            raise ReportingError("native_source_changed", "幻灯片来源已变化，请重新打开。")
        from .native_office import patch_office
        from .slides_render import render_pptx_tree
        content = await self.read_file(context)
        try:
            if operations:
                content = await run_office_engine(patch_office, context.format, content, operations)
            tree = await run_office_engine(render_pptx_tree, content)
            return {**tree, "revision": context.revision, "sha256": context.source_file.sha256}
        except ValueError:
            raise ReportingError("native_operations_invalid", "幻灯片画布无法应用当前修改。") from None
        except (OSError, subprocess.SubprocessError):
            raise ReportingError("native_engine_unavailable", "幻灯片预览引擎暂不可用。") from None

    async def preview_file(
        self, context: NativeEditorContext, *, expected_sha256: str,
        operations: list[dict[str, Any]], expected_preview_digest: str | None = None,
    ) -> dict[str, Any]:
        """实际预览字节与确认清单使用同一引擎判定，绝不覆盖源文件。"""
        self.require_enabled(context.format)
        if expected_sha256 != context.source_file.sha256:
            raise ReportingError("native_source_changed", "原生草稿来源已变化，请刷新后重试。")
        content = await self.read_file(context)
        try:
            if context.format == "pdf":
                if any(op.get("kind") in {"replaceText", "insertText"} for op in operations) and not self.pdf_text_enabled:
                    raise ReportingError("native_pdf_text_disabled", "PDF 原位文字编辑尚未开放。")
                receipt = await run_office_engine(patch_pdf_with_receipt, content, operations)
                if expected_preview_digest is not None and receipt["previewDigest"] != expected_preview_digest:
                    raise ReportingError("native_pdf_text_preview_changed", "PDF 预览或字体资源已变化，请重新校验修改。")
                return receipt
            if context.format == "pptx":
                from ..reporting.delivery.office_engine import libreoffice_to_pdf
                from .native_office import patch_office
                edited = await run_office_engine(patch_office, context.format, content, operations) if operations else content
                pdf = await run_office_engine(libreoffice_to_pdf, edited, suffix=".pptx", timeout=90)
                return {"content": pdf}
            raise ReportingError("native_format_invalid", "该格式没有 PDF 字节预览入口。")
        except ReportingError:
            raise
        except ValueError:
            raise ReportingError("native_operations_invalid", "预览无法应用当前修改，草稿仍保留。") from None
        except (OSError, subprocess.SubprocessError):
            raise ReportingError("native_engine_unavailable", "预览引擎暂不可用。") from None

    async def extract_pages(self, context: NativeEditorContext, *, pages: list[int], request_id: str) -> dict[str, Any]:
        from .native_pdf_extract import extract_pages

        return await extract_pages(self, context, pages=pages, request_id=request_id)

    async def save(
        self,
        context: NativeEditorContext,
        *,
        request_id: str,
        expected_sha256: str,
        operations: list[dict[str, Any]],
        export_pdf: bool = False,
        note: str = "",
        confirmed_preview_digest: str | None = None,
    ) -> dict[str, Any]:
        self.require_enabled(context.format)
        if context.format == "pdf" and any(op.get("kind") in {"replaceText", "insertText"} for op in operations):
            if not self.pdf_text_enabled:
                raise ReportingError("native_pdf_text_disabled", "PDF 原位文字编辑尚未开放。")
        if context.format == 'pdf' and any(op.get('kind') in PDF_CONFIRMATION_KINDS for op in operations) and not confirmed_preview_digest:
            raise ReportingError('native_pdf_text_confirmation_required','请先核对实际 PDF 预览，并确认执行结果和告警。')
        if self.publication is None:
            raise ReportingError("native_engine_unavailable", "原生保存服务尚未部署。")
        try:
            return await self.publication.save_revision(
                context,
                request_id=request_id,
                expected_sha256=expected_sha256,
                operations=operations,
                export_pdf=export_pdf,
                note=note,
                **({"confirmed_preview_digest": confirmed_preview_digest} if confirmed_preview_digest is not None else {}),
            )
        except ReportingError:
            raise
        except ValueError as error:
            raise ReportingError("native_operations_invalid", str(error)) from error
        except (OSError, subprocess.SubprocessError) as error:
            raise ReportingError(
                "native_engine_unavailable", "原生编辑引擎无法执行，请稍后重试。"
            ) from error

    async def download(self, session: ReportEditorSession, artifact: str) -> tuple[bytes, str]:
        caps = session.capabilities or {}
        if (
            caps.get("native_download") is not True
            or session.workflow_run_id != f"native:{session.report_id}"
        ):
            raise ReportingError("native_permission_denied", "该会话没有原生下载权限。")
        if artifact not in NATIVE_ARTIFACT_MEDIA:
            raise ReportingError("native_document_not_found", "下载格式不存在。")
        try:
            scope = NativeScope.model_validate(caps.get("scope"))
            context = NativeEditorContext.model_validate(caps.get("context"))
            identity = ArtifactFile.model_validate(caps["artifacts"][artifact])
        except (KeyError, TypeError, ValidationError) as error:
            raise ReportingError("native_permission_denied", "原生下载文件身份无效。") from error
        if (
            context.document_id != session.report_id
            or context.revision != session.revision
            or context.scope != scope
            or context.format != caps.get("format")
            or not secrets.compare_digest(context.digest(), session.context_sha256)
        ):
            raise ReportingError("native_permission_denied", "下载授权与原生修订身份不一致。")
        expected_media = NATIVE_ARTIFACT_MEDIA[artifact]
        if identity.media_type != expected_media:
            raise ReportingError("native_permission_denied", "原生下载文件类型不一致。")
        key = bind_native_workspace(self.workspace, scope)
        content = await read_verified_file(
            self.workspace,
            {"threadId": key},
            identity.path,
            size=identity.size,
            sha256=identity.sha256,
            error_code="native_source_changed",
            format_name=artifact,
        )
        return content, expected_media
