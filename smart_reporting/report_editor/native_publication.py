"""原生修订保存与交付；身份可读的文件不受验收/登记附加故障阻断。"""

from __future__ import annotations
from .native_pdf_contract import PDF_CONFIRMATION_KINDS,PDF_RECEIPT_KINDS,pdf_review_issues

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from time import monotonic
from typing import Any, Literal, cast
from urllib.parse import quote

from loguru import logger
from pydantic import Field

from ..reporting.delivery.artifacts_v1 import ArtifactFile
from ..reporting.delivery.docx_native import patch_docx
from ..reporting.delivery.office_engine import libreoffice_to_pdf, run_office_engine
from ..reporting.delivery.pdf_native import patch_pdf, patch_pdf_with_receipt
from ..reporting.delivery.publishing import ReportArtifactSpec, ReportDownloadScope
from ..reporting.models import ReportingError
from ..workspace import WorkspacePathConflict
from ._file_identity import read_verified_file
from .native_models import (
    NATIVE_ARTIFACT_KEYS,
    NATIVE_MEDIA,
    NativeArtifacts,
    NativeEditorContext,
    NativeIssue,
    NativeModel,
    NativeRevision,
    NativeValidation,
    native_digest,
)


class _SavedReceipt(NativeModel):
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    context: NativeEditorContext
    artifacts: NativeArtifacts
    issues: tuple[NativeIssue, ...] = ()


class NativePublicationService:
    def __init__(
        self,
        repository: Any,
        workspace_service: Any,
        download_grants: Any,
        editor_grants: Any,
        *,
        artifact_persistence: Any | None = None,
        public_base_url: str = "",
        validator: Callable[[NativeEditorContext, NativeArtifacts], Awaitable[NativeValidation]]
        | None = None,
    ) -> None:
        self.repository = repository
        self.workspace = workspace_service
        self.download_grants = download_grants
        self.editor_grants = editor_grants
        self.artifact_persistence = artifact_persistence
        self.public_base_url = public_base_url.rstrip("/")
        self.validator = validator
        self._locks: dict[str, tuple[asyncio.Lock, int]] = {}

    @asynccontextmanager
    async def _save_lock(self, key: str):
        lock, count = self._locks.get(key, (asyncio.Lock(), 0))
        self._locks[key] = lock, count + 1
        try:
            async with lock:
                yield
        finally:
            _, count = self._locks[key]
            if count == 1:
                self._locks.pop(key)
            else:
                self._locks[key] = lock, count - 1

    async def save_revision(
        self,
        context: NativeEditorContext,
        *,
        operations: list[dict[str, Any]],
        request_id: str,
        expected_sha256: str,
        export_pdf: bool = False,
        note: str = "",
        confirmed_preview_digest: str | None = None,
    ) -> dict[str, Any]:
        started = monotonic()
        if not isinstance(note, str) or len(note) > 200:
            raise ReportingError("native_operations_invalid", "修订说明超过上限。")
        if expected_sha256 != context.source_file.sha256:
            raise ReportingError("native_source_changed", "原生文件快照已变化，请重新打开修订。")
        if (
            not isinstance(operations, list)
            or len(operations) > 500
            or any(not isinstance(item, dict) for item in operations)
        ):
            raise ReportingError("native_operations_invalid", "原生编辑操作无效或超过上限。")
        try:
            encoded = json.dumps(operations, ensure_ascii=False, allow_nan=False).encode()
            if len(encoded) > 12 * 1024 * 1024:
                raise ValueError("operations too large")
            request_sha256 = native_digest(
                {
                    "context": context.digest(),
                    "operations": operations,
                    "exportPdf": export_pdf,
                    "note": note,
                    **({"confirmedPreviewDigest": confirmed_preview_digest} if confirmed_preview_digest is not None else {}),
                }
            )
        except (TypeError, ValueError) as error:
            raise ReportingError("native_operations_invalid", "原生编辑操作无法序列化。") from error
        async with self._save_lock(
            native_digest([context.document_id, request_id, context.scope.model_dump()])
        ):
            reservation = await self.repository.reserve_revision(
                context.document_id,
                parent_revision=context.revision,
                request_id=request_id,
                request_sha256=request_sha256,
                scope=context.scope,
                note=note,
            )
            event = logger.bind(
                format=context.format,
                documentId=context.document_id,
                revision=reservation.revision,
                operationCount=len(operations),
            )
            try:
                result = await self._save_reserved(
                    context, reservation, operations, export_pdf, confirmed_preview_digest
                )
            except Exception as error:
                event.bind(
                    durationMs=round((monotonic() - started) * 1000),
                    result="failed",
                    errorType=type(error).__name__,
                ).warning("native_editor_save")
                raise
            event.bind(
                durationMs=round((monotonic() - started) * 1000),
                result="registered" if result["revisionRegistered"] else "unregistered",
                issueCodes=sorted({issue["code"] for issue in result["validation"]["issues"]}),
            ).info("native_editor_save")
            return {**result, "note": reservation.note}

    async def _save_reserved(
        self,
        parent: NativeEditorContext,
        reservation: NativeRevision,
        operations: list[dict[str, Any]],
        export_pdf: bool,
        confirmed_preview_digest: str | None = None,
    ) -> dict[str, Any]:
        from .native import bind_native_workspace

        key = bind_native_workspace(self.workspace, parent.scope)
        if reservation.status == "saved":
            if reservation.context is None:
                raise ReportingError("native_revision_invalid", "已保存修订缺少文件身份。")
            return await self._publish_artifacts(
                reservation.context,
                reservation.artifacts,
                reservation.validation or self._pending_validation(),
                True,
                key,
            )
        # 只有完整的服务端回执、预约摘要及磁盘文件三者一致才可恢复；reserved 本身不是成功。
        prefix = f"native/documents/{native_digest(parent.document_id)}/r{reservation.revision}"
        receipt_path = f"{prefix}/saved.json"
        recovered: _SavedReceipt | None = None
        recovery_blocked = False
        recovery_issues: list[NativeIssue] = []
        try:
            if await self.workspace.apath_exists(key, receipt_path):
                recovered = await self._read_receipt(key, receipt_path, parent, reservation)
        except Exception:
            recovery_blocked = True
            recovery_issues.append(
                self._issue(
                    "native_recovery_record_invalid",
                    "恢复记录无法核验，已拒绝使用；本次独立核验的文件仍继续签发。",
                )
            )
        if recovered is not None:
            next_context, artifacts = recovered.context, recovered.artifacts
            issues = list(recovered.issues)
        else:
            content = await read_verified_file(
                self.workspace,
                {"threadId": key},
                parent.source_file.path,
                size=parent.source_file.size,
                sha256=parent.source_file.sha256,
                error_code="native_source_changed",
                format_name=parent.format.upper(),
            )
            try:
                text_receipt = None
                patch = patch_docx if parent.format == "docx" else patch_pdf
                if parent.format in {"xlsx", "pptx"}:
                    from functools import partial

                    from .native_office import patch_office
                    patch = partial(patch_office, parent.format)
                if parent.format == 'pdf' and any(op.get('kind') in PDF_RECEIPT_KINDS for op in operations):
                    text_receipt = await run_office_engine(patch_pdf_with_receipt, content, operations)
                    if any(op.get('kind') in PDF_CONFIRMATION_KINDS for op in operations) and (not confirmed_preview_digest or text_receipt['previewDigest'] != confirmed_preview_digest):
                        raise ReportingError('native_pdf_text_preview_changed','PDF 实际输出或资源已变化，请重新预览并确认。')
                    revised = text_receipt["content"]
                else:
                    revised = await run_office_engine(patch, content, operations)
            except Exception:
                try:
                    await self.repository.fail_revision(reservation, code="native_engine_failed")
                except Exception as error:
                    logger.bind(errorType=type(error).__name__).warning(
                        "native_failed_reservation_record_unavailable"
                    )
                raise
            primary_label = NATIVE_ARTIFACT_KEYS[parent.format]
            primary_path = f"{prefix}/{hashlib.sha256(revised).hexdigest()}.{parent.format}"
            primary = ArtifactFile(
                path=primary_path,
                size=len(revised),
                sha256=hashlib.sha256(revised).hexdigest(),
                mediaType=NATIVE_MEDIA[parent.format],
            )
            identities: dict[str, ArtifactFile] = {}
            issues = list(recovery_issues)
            if text_receipt is not None:
                for skipped in text_receipt.get("skippedOperations", []):
                    styled_text = any(op.get('kind') == 'replaceText' and (
                        any(key in op for key in ('font','fontSize','color','bold','italic','align','lineLeading','styleRuns'))
                        or chr(10) in str(op.get('newText',''))) for op in operations)
                    message = (f"第 {skipped['operationIndex'] + 1} 项 PDF 编辑执行或复核告警，已保留实际生成文件，请核对内容：{skipped['reason']}"
                        if skipped.get('kind') != 'replaceText' or styled_text else
                        f"第 {skipped['operationIndex'] + 1} 项文字修改未应用，已保留原文：{skipped['reason']}")
                    issues.append(self._issue("native_pdf_text_skipped", message))
                for review_issue in pdf_review_issues(text_receipt):
                    issues.append(self._issue(review_issue["code"], review_issue["message"]))
            try:
                identities[primary_label] = await self._write_file(
                    key, primary.path, revised, primary.media_type
                )
            except Exception:
                issues.append(
                    self._issue(
                        f"native_{primary_label}_identity_unavailable",
                        f"{primary_label} 文件保存或身份读取失败，继续交付其他已核验格式。",
                    )
                )
            if parent.format in {"xlsx", "pptx"} and primary_label in identities:
                try:
                    from .native_office import inspect_office

                    await run_office_engine(inspect_office, parent.format, revised)
                except Exception:
                    issues.append(
                        self._issue(
                            "native_office_read_validation_failed",
                            "文件已保存并核验身份，但结构回读验收失败；下载仍可用。",
                        )
                    )
            if parent.format == "docx" and export_pdf:
                try:
                    pdf = await run_office_engine(
                        libreoffice_to_pdf, revised, suffix=".docx", timeout=120
                    )
                    identities["pdf"] = await self._write_file(
                        key,
                        f"{prefix}/{hashlib.sha256(pdf).hexdigest()}.pdf",
                        pdf,
                        "application/pdf",
                    )
                except Exception:
                    issues.append(
                        self._issue("native_pdf_export_failed", "Word 已保存，但 PDF 转换失败。")
                    )
            artifacts = NativeArtifacts(**identities)
            next_context = NativeEditorContext(
                documentId=parent.document_id,
                revision=reservation.revision,
                parentRevision=parent.revision,
                scope=parent.scope,
                format=parent.format,
                origin=parent.origin,
                sourceFile=primary,
            )
            if primary_label in identities:
                receipt = _SavedReceipt(
                    request_sha256=reservation.request_sha256,
                    context=next_context,
                    artifacts=artifacts,
                    issues=tuple(issues),
                )
                try:
                    await self.workspace.awrite_bytes(
                        key, receipt_path, receipt.model_dump_json(by_alias=True).encode()
                    )
                except WorkspacePathConflict:
                    # 两个进程可能并行运行同一预约；只采用首个完整回执绑定的文件。
                    try:
                        winner = await self._read_receipt(key, receipt_path, parent, reservation)
                    except Exception:
                        recovery_blocked = True
                        issues.append(
                            self._issue(
                                "native_recovery_record_invalid",
                                "已有恢复记录无法核验，本次文件仍保留下载。",
                            )
                        )
                    else:
                        next_context, artifacts, issues = (
                            winner.context,
                            winner.artifacts,
                            list(winner.issues),
                        )
                except Exception:
                    issues.append(
                        self._issue(
                            "native_recovery_record_failed", "文件已保存，但重试恢复记录未能保存。"
                        )
                    )
        # 在任何附加验收前再次读磁盘核对；恢复回执不能替代真实文件身份。
        verified, identity_issues = await self._verified_artifacts(key, artifacts)
        issues.extend(identity_issues)
        validation = self._pending_validation()
        if self.validator is not None:
            try:
                checked = NativeValidation.model_validate(
                    await self.validator(next_context, verified)
                )
                validation = self._with_issues(validation, list(checked.issues))
            except Exception:
                issues.append(
                    self._issue(
                        "native_validation_failed", "文件已保存，但内容或版式验收执行失败。"
                    )
                )
        validation = self._with_issues(validation, issues)
        registered = False
        verified_primary = getattr(verified, NATIVE_ARTIFACT_KEYS[parent.format])
        if verified_primary == next_context.source_file and not recovery_blocked:
            try:
                await self.repository.complete_revision(
                    reservation, context=next_context, artifacts=verified, validation=validation
                )
                registered = True
            except Exception:
                validation = self._with_issues(
                    validation,
                    [
                        self._issue(
                            "native_revision_registration_failed",
                            "文件已保存，但新修订尚未登记；下载仍可用，可重试恢复登记。",
                        )
                    ],
                )
        return await self._publish_artifacts(next_context, verified, validation, registered, key)

    async def _read_receipt(
        self, key: str, path: str, parent: NativeEditorContext, reservation: NativeRevision
    ) -> _SavedReceipt:
        try:
            raw, _ = await self.workspace.afile_bytes(key, path)
            recovered = _SavedReceipt.model_validate_json(raw)
        except Exception as error:
            raise ReportingError(
                "native_revision_identity_changed", "保存回执已变化，不能覆盖已有文件。"
            ) from error
        if (
            recovered.request_sha256 != reservation.request_sha256
            or recovered.context.document_id != parent.document_id
            or recovered.context.revision != reservation.revision
            or recovered.context.parent_revision != parent.revision
            or recovered.context.scope != parent.scope
            or recovered.context.format != parent.format
            or recovered.context.origin != parent.origin
            or getattr(recovered.artifacts, NATIVE_ARTIFACT_KEYS[parent.format])
            != recovered.context.source_file
        ):
            raise ReportingError("native_revision_identity_changed", "保存回执与预约不一致。")
        prefix = f"native/documents/{native_digest(parent.document_id)}/r{reservation.revision}"
        for extension, label in NATIVE_ARTIFACT_KEYS.items():
            identity = getattr(recovered.artifacts, label)
            if identity is not None and identity.path != f"{prefix}/{identity.sha256}.{extension}":
                raise ReportingError(
                    "native_revision_identity_changed", "保存回执引用其他文档或修订的文件。"
                )
        return recovered

    async def _write_file(
        self, key: str, path: str, content: bytes, media_type: Any
    ) -> ArtifactFile:
        identity = ArtifactFile(
            path=path,
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            mediaType=media_type,
        )
        try:
            await self.workspace.awrite_bytes(
                key, path, content
            )  # 默认 overwrite=False，不能替换来源或历史文件。
        except WorkspacePathConflict:
            # 同一预约的并发/失败重试只复用相同字节，不覆盖已存在的文件。
            pass
        await read_verified_file(
            self.workspace,
            {"threadId": key},
            path,
            size=identity.size,
            sha256=identity.sha256,
            error_code="native_artifact_identity_changed",
            format_name="原生",
        )
        return identity

    async def _verified_artifacts(
        self, key: str, artifacts: NativeArtifacts
    ) -> tuple[NativeArtifacts, list[NativeIssue]]:
        verified = {}
        issues = []
        for label in NATIVE_ARTIFACT_KEYS.values():
            file = getattr(artifacts, label)
            if file is None:
                continue
            try:
                await read_verified_file(
                    self.workspace,
                    {"threadId": key},
                    file.path,
                    size=file.size,
                    sha256=file.sha256,
                    error_code="native_artifact_identity_changed",
                    format_name=label,
                )
            except Exception:
                try:
                    actual, _ = await self.workspace.afile_bytes(key, file.path)
                    if len(actual) != file.size or hashlib.sha256(actual).hexdigest() != file.sha256:
                        raise ValueError("actual identity mismatch")
                except Exception:
                    issues.append(
                        self._issue(
                            f"native_{label}_identity_unavailable",
                            f"{label} 文件身份无法核验，未签发该格式下载。",
                        )
                    )
                else:
                    verified[label] = file
                    issues.append(self._issue(
                        f"native_{label}_identity_review_failed",
                        f"{label} 后置复核异常，但已直接读取并重新核验实际文件身份，下载仍可用。",
                    ))
            else:
                verified[label] = file
        return NativeArtifacts(**verified), issues

    async def _publish_artifacts(
        self,
        context: NativeEditorContext,
        artifacts: NativeArtifacts,
        validation: NativeValidation,
        registered: bool,
        workspace_key: str,
        *,
        allow_editor: bool = True,
    ) -> dict[str, Any]:
        verified, issues = await self._verified_artifacts(workspace_key, artifacts)
        identities = {
            label: getattr(verified, label)
            for label in NATIVE_ARTIFACT_KEYS.values()
            if getattr(verified, label) is not None
        }
        download_scope = ReportDownloadScope(
            database=context.scope.database,
            company_id=context.scope.company_id,
            user_id=context.scope.user_id,
            session_id=context.scope.thread_id,
            thread_id=workspace_key,
            workflow_run_id=context.workflow_run_id,
        )
        report_id = f"native:{context.document_id}:r{context.revision}"
        if identities and self.artifact_persistence is not None:
            try:
                stored = await self.artifact_persistence.persist_available(
                    scope=download_scope,
                    report_id=report_id,
                    revision=context.revision,
                    artifacts=tuple(
                        ReportArtifactSpec(
                            artifact=cast(Literal["word", "pdf", "xlsx", "pptx"], label),
                            path=file.path,
                            size=file.size,
                            sha256=file.sha256,
                        )
                        for label, file in identities.items()
                    ),
                )
                if {spec.artifact for spec in stored} != set(identities):
                    issues.append(
                        self._issue(
                            "native_artifact_persistence_failed",
                            "部分下载副本保存失败，使用已核验工作区文件。",
                        )
                    )
            except Exception:
                issues.append(
                    self._issue(
                        "native_artifact_persistence_failed",
                        "下载副本保存失败，使用已核验工作区文件。",
                    )
                )
        links, link_issues = await self._issue_links(context, identities, download_scope, report_id)
        issues.extend(link_issues)
        editor = None
        editable_primary = getattr(verified, NATIVE_ARTIFACT_KEYS[context.format])
        if (
            registered
            and allow_editor
            and editable_primary == context.source_file
            and self.editor_grants is not None
        ):
            try:
                raw, expires = await self.editor_grants.issue(
                    context,
                    capabilities={
                        "native_editor": True,
                        "native_download": True,
                        "format": context.format,
                        "scope": context.scope.model_dump(by_alias=True),
                    },
                )
                editor = {
                    "openUrl": f"{self.public_base_url}/reports/v1/native/open/{quote(raw, safe='')}",
                    "expiresAt": expires.isoformat(),
                }
            except Exception:
                issues.append(
                    self._issue(
                        "native_editor_grant_failed", "编辑入口签发失败，文件下载不受影响。"
                    )
                )
        return {
            "documentId": context.document_id,
            "revision": context.revision,
            "parentRevision": context.parent_revision,
            "revisionRegistered": registered,
            "artifacts": {
                label: {
                    **file.model_dump(mode="json", by_alias=True),
                    **({"downloadUrl": links[label]} if label in links else {}),
                }
                for label, file in identities.items()
            },
            "validation": self._with_issues(validation, issues).model_dump(mode="json"),
            **({"editor": editor} if editor else {}),
        }

    async def _issue_links(
        self,
        context: NativeEditorContext,
        identities: dict[str, ArtifactFile],
        download_scope: ReportDownloadScope,
        report_id: str,
    ) -> tuple[dict[str, str], list[NativeIssue]]:
        if not identities:
            return {}, []
        issues: list[NativeIssue] = []
        try:
            raw, _ = await self.download_grants.issue(
                scope=download_scope,
                report_id=report_id,
                revision=context.revision,
                **{
                    f"{label}_{field}": getattr(file, field)
                    for label, file in identities.items()
                    for field in ("path", "size", "sha256")
                },
            )
            return {
                label: f"{self.public_base_url}/reports/v1/native/artifacts/{raw}/{label}"
                for label in identities
            }, issues
        except Exception:
            issues.append(
                self._issue(
                    "native_download_grant_failed", "主下载授权签发失败，尝试原生文件授权。"
                )
            )
        try:
            raw, _ = await self.editor_grants.issue(
                context,
                capabilities={
                    "native_download": True,
                    "format": context.format,
                    "scope": context.scope.model_dump(by_alias=True),
                    "context": context.model_dump(mode="json", by_alias=True),
                    "artifacts": {
                        label: file.model_dump(mode="json", by_alias=True)
                        for label, file in identities.items()
                    },
                },
            )
            return {
                label: f"{self.public_base_url}/reports/v1/native/download/{quote(raw, safe='')}/{label}"
                for label in identities
            }, issues
        except Exception:
            issues.append(
                self._issue(
                    "native_download_fallback_failed",
                    "备用下载授权签发失败，已核验文件保留，可重试签发。",
                )
            )
            return {}, issues

    @staticmethod
    def _issue(code: str, message: str) -> NativeIssue:
        logger.warning("{}", code)
        return NativeIssue(code=code, message=message)

    @staticmethod
    def _pending_validation() -> NativeValidation:
        return NativeValidation(
            ok=False,
            issues=(
                NativeIssue(
                    code="native_source_review_pending",
                    message="文件已保存；原生编辑内容尚未重新核验业务事实与完整版式。",
                ),
            ),
        )

    @staticmethod
    def _with_issues(validation: NativeValidation, issues: list[NativeIssue]) -> NativeValidation:
        return NativeValidation(
            ok=validation.ok and not issues, issues=(*validation.issues, *issues)
        )
