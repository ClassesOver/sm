"""从已核验的 PDF 修订派生独立文档，登记失败也保留可读取的实际产物。"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import PurePosixPath

from loguru import logger

from ..office.artifacts import ArtifactFile
from ..reporting.delivery.office_engine import run_office_engine
from ..reporting.delivery.pdf_native import extract_pdf_pages, inspect_pdf
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


async def split_pdf(editor, context, *, chunk_size, request_id):
    """按保存后的连续页序派生多份 PDF；单份失败不丢其它实际文件。"""
    editor.require_enabled("pdf")
    if context.format != "pdf":
        raise ReportingError("native_format_invalid", "只有 PDF 可以拆分文件。")
    if (type(chunk_size) is not int or not 1 <= chunk_size <= 10000
        or not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 256):
        raise ReportingError("native_operations_invalid", "每份页数须为有效整数，并提供请求身份。")
    source = await editor.read_file(context)
    model = await run_office_engine(inspect_pdf, source)
    total = model.get("pageCount")
    if (type(total) is not int or not 2 <= total <= 10000
        or total != len(model.get("pages", [])) or chunk_size >= total):
        raise ReportingError("native_operations_invalid", "每份页数须大于0且小于来源总页数，至少生成两份 PDF。")
    stem = re.sub(r'[/\\:*?"<>|\x00-\x1f]', '_', PurePosixPath(context.source_file.path).stem) or "split"
    parts, issues = [], []
    for index, start in enumerate(range(1, total + 1, chunk_size), 1):
        pages = list(range(start, min(start + chunk_size, total + 1)))
        part = {"index": index, "pages": pages, "filename": f"{stem}-{index}.pdf"}
        try:
            part["result"] = await extract_pages(editor, context, pages=pages,
                request_id=native_digest({"action": "splitPdf", "requestId": request_id,
                    "source": context.digest(), "chunkSize": chunk_size, "part": index}))
        except Exception as error:
            code = error.code if isinstance(error, ReportingError) else "native_pdf_split_part_failed"
            message = error.message if isinstance(error, ReportingError) else "本份 PDF 未能生成或核验身份，其它分份继续处理。"
            part["error"] = {"code": code, "message": message}
            issues.append({"code": code, "message": f"第 {index} 份（第 {pages[0]}–{pages[-1]} 页）：{message}"})
            logger.bind(documentId=context.document_id, revision=context.revision,
                part=index, code=code).warning("native_pdf_split_part_failed")
        parts.append(part)
    return {"source": {"documentId": context.document_id, "revision": context.revision,
        "sha256": context.source_file.sha256}, "chunkSize": chunk_size, "parts": parts,
        "validation": {"ok": False, "issues": [*issues, {
            "code": "native_validation_pending", "message": "拆分文件尚未重新执行业务和版式验收，请逐份核对；可读取的实际文件下载不受影响。"}]}}


async def extract_pages(editor, context, *, pages, request_id):
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
    result = await _publish_derived_pdf(editor, context, receipt=receipt, request_id=request_id,
        identity_key=native_digest({"context": context.digest(), "requestId": request_id, "pages": pages}))
    return {
        **result,
        "source": {
            "documentId": context.document_id,
            "revision": context.revision,
            "sha256": context.source_file.sha256,
            "pages": pages,
        },
    }


async def _publish_derived_pdf(editor, context, *, receipt, request_id, identity_key,
    filename="extracted.pdf", label="提取", issue_prefix="native_pdf_extract",
    output_error="native_extract_output_unavailable", extra_issues=()):
    """原提取派生登记与非阻断下载链；合并仅替换产物身份和提示。"""
    from .native import bind_native_workspace

    key = bind_native_workspace(editor.workspace, context.scope)
    content = receipt["content"]
    path = f"native/derived/{identity_key}/{filename}"
    identity = ArtifactFile(
        path=path,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        mediaType="application/pdf",
    )
    recovery_issues = []
    if receipt.get("reviewIssues"):
        recovery_issues.append(NativeIssue(
            code=f"{issue_prefix}_receipt_warning",
            message=f"{label}引擎回执读取或身份复核异常，已丢弃不可信元数据；实际生成文件已保留，请下载后核对内容。",
        ))
    try:
        await editor.workspace.awrite_bytes(key, path, content)
    except WorkspacePathConflict:
        pass
    except Exception:
        recovery_issues.append(NativeIssue(
            code=f"{issue_prefix}_postwrite_warning",
            message=f"{label} PDF 写入回执异常；继续核验实际文件并保留可用下载。",
        ))
        logger.warning(f"{issue_prefix}_write_receipt_failed")
    try:
        await read_verified_file(
            editor.workspace, {"threadId": key}, path, size=identity.size,
            sha256=identity.sha256, error_code=output_error, format_name="PDF",
        )
    except Exception:
        try:
            actual, _ = await editor.workspace.afile_bytes(key, path)
            if len(actual) != identity.size or hashlib.sha256(actual).hexdigest() != identity.sha256:
                raise ValueError("actual identity mismatch")
        except Exception:
            raise ReportingError(
                output_error, f"{label} PDF 实际文件无法读取或身份不匹配，暂无法签发下载。"
            ) from None
        recovery_issues.append(NativeIssue(
            code=f"{issue_prefix}_review_failed",
            message=f"{label} PDF 后置复核异常，但实际文件身份已重新核验，下载仍可用。",
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
    issues = [*recovery_issues, *extra_issues,
        NativeIssue(
            code="native_validation_pending",
            message=f"{label} PDF 已生成并核验文件身份，尚未重新执行业务和版式验收。",
        )
    ]
    registered = False
    if len(content) > 24 * 1024 * 1024:
        issues.append(
            NativeIssue(
                code="native_file_too_large",
                message=f"{label}文件超过 24 MiB 在线编辑上限，保留下载但不开放在线编辑。",
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
            ).warning(f"{issue_prefix}_registration_failed")
    result = await editor.publication._publish_artifacts(
        child_context,
        NativeArtifacts(pdf=identity),
        NativeValidation(ok=False, issues=tuple(issues)),
        registered,
        key,
    )
    return result
