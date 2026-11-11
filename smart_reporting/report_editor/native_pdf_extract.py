"""从已核验的 PDF 修订派生独立文档，登记失败也保留可读取的实际产物。"""

from __future__ import annotations

import hashlib
import subprocess

from loguru import logger

from ..reporting.delivery.artifacts_v1 import ArtifactFile
from ..reporting.delivery.office_engine import run_office_engine
from ..reporting.delivery.pdf_native import extract_pdf_pages
from ..reporting.models import ReportingError
from ..workspace import WorkspacePathConflict
from ._file_identity import read_verified_file
from .native_models import (
    NativeArtifacts,
    NativeEditorContext,
    NativeIssue,
    NativeSource,
    NativeValidation,
    native_digest,
)


async def extract_pages(editor, context, *, pages, request_id):
    from .native import bind_native_workspace

    editor.require_enabled("pdf")
    if context.format != "pdf":
        raise ReportingError("native_format_invalid", "只有 PDF 可以提取页面。")
    if (
        not isinstance(pages, list)
        or not 1 <= len(pages) <= 10000
        or any(type(page) is not int or page < 1 for page in pages)
        or len(set(pages)) != len(pages)
        or not isinstance(request_id, str)
        or not request_id.strip()
        or len(request_id) > 256
    ):
        raise ReportingError(
            "native_operations_invalid", "请选择不重复的有效页码，并提供请求身份。"
        )
    if editor.publication is None:
        raise ReportingError("native_engine_unavailable", "原生文件发布服务尚未部署。")
    source = await editor.read_file(context)
    try:
        receipt = await run_office_engine(
            extract_pdf_pages, source, [page - 1 for page in pages]
        )
    except ValueError:
        raise ReportingError(
            "native_operations_invalid",
            "无法提取所选页面，请检查页码范围；含表单、批注或保护信息的 PDF 暂不支持提取。",
        ) from None
    except (OSError, subprocess.SubprocessError):
        raise ReportingError(
            "native_engine_unavailable", "PDF 提取引擎暂不可用。"
        ) from None
    content = receipt["content"]
    key = bind_native_workspace(editor.workspace, context.scope)
    identity_key = native_digest(
        {"context": context.digest(), "requestId": request_id, "pages": pages}
    )
    path = f"native/derived/{identity_key}/extracted.pdf"
    identity = ArtifactFile(
        path=path,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        mediaType="application/pdf",
    )
    recovery_issues = []
    if receipt.get("reviewIssues"):
        recovery_issues.append(NativeIssue(
            code="native_pdf_extract_receipt_warning",
            message="提取引擎回执读取或身份复核异常，已丢弃不可信元数据；实际生成文件已保留，请下载后核对内容。",
        ))
    try:
        await editor.workspace.awrite_bytes(key, path, content)
    except WorkspacePathConflict:
        pass
    except Exception:
        recovery_issues.append(NativeIssue(
            code="native_pdf_extract_postwrite_warning",
            message="提取 PDF 写入回执异常；继续核验实际文件并保留可用下载。",
        ))
        logger.warning("native_pdf_extract_write_receipt_failed")
    try:
        await read_verified_file(
            editor.workspace, {"threadId": key}, path, size=identity.size,
            sha256=identity.sha256, error_code="native_extract_output_unavailable", format_name="PDF",
        )
    except Exception:
        try:
            actual, _ = await editor.workspace.afile_bytes(key, path)
            if len(actual) != identity.size or hashlib.sha256(actual).hexdigest() != identity.sha256:
                raise ValueError("actual identity mismatch")
        except Exception:
            raise ReportingError(
                "native_extract_output_unavailable", "提取 PDF 实际文件无法读取或身份不匹配，暂无法签发下载。"
            ) from None
        recovery_issues.append(NativeIssue(
            code="native_pdf_extract_review_failed",
            message="提取 PDF 后置复核异常，但实际文件身份已重新核验，下载仍可用。",
        ))
    derived = NativeSource(
        format="pdf",
        origin="derived",
        sourceFile=identity,
        parentDocumentId=context.document_id,
        parentRevision=context.revision,
        parentSha256=context.source_file.sha256,
    )
    child_context = NativeEditorContext(
        documentId=identity_key,
        revision=1,
        format="pdf",
        scope=context.scope,
        sourceFile=identity,
        origin="derived",
    )
    issues = [*recovery_issues,
        NativeIssue(
            code="native_validation_pending",
            message="提取 PDF 已生成并核验文件身份，尚未重新执行业务和版式验收。",
        )
    ]
    registered = False
    if len(content) > 24 * 1024 * 1024:
        issues.append(
            NativeIssue(
                code="native_file_too_large",
                message="提取文件超过 24 MiB 在线编辑上限，保留下载但不开放在线编辑。",
            )
        )
    else:
        try:
            child = await editor.repository.create_from_source(
                derived, scope=context.scope, request_id=request_id
            )
            revision = await editor.repository.get_revision(
                child.document_id, 1, scope=context.scope
            )
            if (
                revision is None
                or revision.context is None
                or revision.status != "saved"
                or revision.context.source_file != identity
                or revision.context.scope != context.scope
                or revision.context.document_id != child.document_id
                or revision.context.revision != 1
                or revision.context.format != "pdf"
                or revision.context.origin != "derived"
            ):
                raise ValueError("派生修订登记身份不一致")
            child_context = revision.context
            registered = True
        except Exception:
            issues.append(
                NativeIssue(
                    code="native_derived_registration_failed",
                    message="派生文档登记失败，已生成 PDF 的下载仍可用。",
                )
            )
            logger.bind(
                documentId=context.document_id, revision=context.revision
            ).warning("native_pdf_extract_registration_failed")
    result = await editor.publication._publish_artifacts(
        child_context,
        NativeArtifacts(pdf=identity),
        NativeValidation(ok=False, issues=tuple(issues)),
        registered,
        key,
    )
    return {
        **result,
        "source": {
            "documentId": context.document_id,
            "revision": context.revision,
            "sha256": context.source_file.sha256,
            "pages": pages,
        },
    }
