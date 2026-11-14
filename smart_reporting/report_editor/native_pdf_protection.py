"""创建独立密码保护下载；凭据不进入操作历史、修订或日志。"""
from __future__ import annotations

import hashlib
import subprocess

from loguru import logger

from ..office.artifacts import ArtifactFile
from ..reporting.delivery.office_engine import run_office_engine
from ..reporting.delivery.pdf_native import protect_pdf as protect_pdf_bytes
from ..reporting.models import ReportingError
from ._file_identity import read_verified_file
from .native_models import (
    NativeArtifacts,
    NativeEditorContext,
    NativeIssue,
    NativeValidation,
    native_digest,
)


async def protect_pdf(editor,context,*,request_id,expected_sha256,user_password,owner_password,permissions):
    from .native import bind_native_workspace

    editor.require_enabled('pdf')
    if context.format != 'pdf':
        raise ReportingError('native_format_invalid','只有 PDF 可以创建密码保护下载。')
    if expected_sha256 != context.source_file.sha256:
        raise ReportingError('native_source_changed','PDF 来源已变化，请重新打开。')
    if (not isinstance(request_id,str) or not request_id.strip() or len(request_id)>256
        or any(not isinstance(value,str) or not 1<=len(value.encode('utf8'))<=127 for value in (user_password,owner_password))
        or not isinstance(permissions,dict) or set(permissions)!={'printing','modifying','annotating','copying'}
        or any(type(value) is not bool for value in permissions.values())):
        raise ReportingError('native_operations_invalid','请提供有效请求身份、1–127 UTF-8 字节密码和四项权限。')
    if editor.publication is None:
        raise ReportingError('native_engine_unavailable','原生文件发布服务尚未部署。')
    source=await editor.read_file(context)
    if hashlib.sha256(source).hexdigest()!=expected_sha256:
        raise ReportingError('native_source_changed','PDF 实际文件身份已变化。')
    try:
        receipt=await run_office_engine(protect_pdf_bytes,source,user_password=user_password,owner_password=owner_password,permissions=permissions)
    except ValueError:
        raise ReportingError('native_operations_invalid','无法创建保护文件；当前仅支持未加密且不含表单或签名保护结构的 PDF。') from None
    except (OSError,subprocess.SubprocessError):
        raise ReportingError('native_engine_unavailable','PDF 保护引擎暂不可用。') from None
    content=receipt['content']
    if not isinstance(content,bytes) or not content:
        raise ReportingError('native_protection_output_unavailable','没有生成可读取的保护 PDF。')
    digest=hashlib.sha256(content).hexdigest()
    identity_key=native_digest({'source':context.digest(),'requestId':request_id,'outputSha256':digest})
    key=bind_native_workspace(editor.workspace,context.scope)
    path='native/protected/'+identity_key+'/protected.pdf'
    identity=ArtifactFile(path=path,size=len(content),sha256=digest,mediaType='application/pdf')
    issues=[NativeIssue(code='native_protected_pdf_download_only',message='已生成密码保护 PDF；当前仅提供独立下载，不登记可在线编辑的修订。尚未执行业务和版式验收。')]
    try:
        await editor.workspace.awrite_bytes(key,path,content)
    except Exception:
        issues.append(NativeIssue(code='native_pdf_protection_postwrite_warning',message='保护 PDF 写入回执异常；继续核验实际文件并保留可用下载。'))
        logger.warning('native_pdf_protection_write_receipt_failed')
    try:
        await read_verified_file(editor.workspace,{'threadId':key},path,size=identity.size,sha256=identity.sha256,error_code='native_protection_output_unavailable',format_name='PDF')
    except Exception:
        try:
            actual,_=await editor.workspace.afile_bytes(key,path)
            if len(actual)!=identity.size or hashlib.sha256(actual).hexdigest()!=identity.sha256:
                raise ValueError('actual identity mismatch')
        except Exception:
            raise ReportingError('native_protection_output_unavailable','保护 PDF 实际文件无法读取或身份不匹配，暂无法签发下载。') from None
        issues.append(NativeIssue(code='native_pdf_protection_review_failed',message='保护 PDF 后置复核异常，但实际文件身份已重新核验，下载仍可用。'))
    child=NativeEditorContext(documentId=identity_key,revision=1,format='pdf',scope=context.scope,sourceFile=identity,origin='derived')
    if receipt.get('reviewIssues'):
        messages={
            'pdf_protection_receipt_failed_actual_output_retained':'转换引擎回执读取失败',
            'pdf_protection_receipt_identity_failed_actual_output_retained':'转换回执身份不一致，已丢弃其元数据并重新核验实际字节身份',
            'pdf_protection_output_review_mismatch':'页面几何或权限复核不一致',
            'pdf_protection_owner_review_failed':'所有者身份复核未通过',
            'pdf_protection_output_review_failed':'输出解密或结构复核失败',
        }
        details='；'.join(dict.fromkeys(messages[code] for code in receipt['reviewIssues'] if isinstance(code,str) and code in messages))
        issues.append(NativeIssue(code='native_pdf_protection_review_failed',message=(details or '保护输出复核出现告警')+'；已保留实际生成文件，请下载后核对密码、权限及内容。'))
    result=await editor.publication._publish_artifacts(child,NativeArtifacts(pdf=identity),NativeValidation(ok=False,issues=tuple(issues)),False,key)
    return {**result,'source':{'documentId':context.document_id,'revision':context.revision,'sha256':context.source_file.sha256},'protection':{'algorithm':'AES-256','revision':6,'permissions':permissions}}
