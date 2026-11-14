"""编辑预览和人工修订共用的模板消费者；文件签发仍走既有编辑器。"""

import hashlib
from copy import deepcopy
from pathlib import PurePosixPath

from loguru import logger

from ..management.preference_template_readback import read_template_document
from ..preferences.document_adapter import document_design
from ..preferences.markdown_adapter import strip_signature
from ..preferences.workbook_adapter import displayed_date
from ..reporting.delivery.artifacts_v1 import ReportArtifactManifest
from ..reporting.delivery.office_engine import libreoffice_to_pdf, run_office_engine
from ..reporting.delivery.template_body_readback import read_template_body
from ..reporting.delivery.template_body_resources import bind_template_images, resource_issue
from ..reporting.delivery.templates import fill_report_template
from ..reporting.workspace import REPORT_JOBS_STATE_KEY
from ..workspace import WorkspacePathConflict
from ._file_identity import read_verified_file
from .template_provenance import build_template_provenance, unavailable_issue


async def render_editor_document(editor, *, context, source_context, document, snapshot_path,
        output_path, formats, render_manifest, management_overview, run_context, preview=False):
    """预览和导出共享路由；只有确认未绑定模板才调用通用生成器。"""
    from .template_source import resolve_editor_template

    template = await resolve_editor_template(editor, context=context, source_context=source_context)
    if template is not None:
        result = await render_editor_template(editor, template_source=template, context=context,
            source_context=source_context, document=document, snapshot_path=snapshot_path,
            output_path=output_path, formats=('word',) if preview and context.delivery_format == 'docx' else formats,
            render_manifest=render_manifest, run_context=run_context)
        if preview and context.delivery_format == 'docx' and result.get('wordPath'):
            identity = {key: result['word' + field] for key, field in (('path', 'Path'), ('size', 'Size'), ('sha256', 'Sha256'))}
            stored = await read_verified_file(editor.workspace, context.scope, identity['path'], size=identity['size'],
                sha256=identity['sha256'], error_code='report_editor_template_preview_changed', format_name='文字文档预览源')
            pdf = await run_office_engine(libreoffice_to_pdf, stored, suffix='.docx', timeout=120)
            await editor.workspace.awrite_bytes(context.scope['threadId'], output_path, pdf)
            result.update(pdfPath=output_path, pdfSize=len(pdf), pdfSha256=hashlib.sha256(pdf).hexdigest())
            result['validation']['previewSourceFormat'] = 'word'
        return result
    return await editor.report_tools._render_report_pair(context.job_id, snapshot_path, output_path,
        artifact_manifest=render_manifest, management_overview=management_overview, run_context=run_context)


def _format_content(job, configuration, format):
    """只读取本次冻结快照；不读取当前默认或当前日期。"""
    preferences = job.get('_formatPreferences') or (configuration or {}).get('resolvedFormats', {})
    resolved = deepcopy(preferences.get(format))
    context = job.get('_documentContext', {})
    generated = context.get('generatedDate') or (configuration or {}).get('generatedDate')
    title = context.get('title', '')
    if not resolved or not generated:
        return title, None, None, generated
    design = document_design(resolved, overrides=job.get('_reportDesign'))
    resolved['common']['dateFormat'] = design.signature.date_format if design.signature else 'iso'
    resolved['signature']['description'] = design.signature.description if design.signature else ''
    signature = {'signer': resolved['common']['signer'],
        'date': displayed_date(generated, resolved['common']['dateFormat']),
        'description': resolved['signature']['description']}
    return title, signature, resolved, generated


async def render_editor_template(editor, *, template_source, context, source_context, document,
        snapshot_path, output_path, formats, render_manifest, run_context):
    """只写服务端指定的新目录；验收失败不撤销已生成的可核验文件。"""
    issues, readbacks, result, bindings = [], {}, {}, {}
    job = run_context.session_state[REPORT_JOBS_STATE_KEY][context.job_id]
    scope = context.scope
    try:
        if not formats or any(format not in ('word', 'pdf') for format in formats):
            raise ValueError('unsupported template editor target')
        if PurePosixPath(template_source.identity.filename).suffix.lower() != '.docx':
            raise ValueError('template editor requires registered DOCX source')
        if (len(template_source.content) != template_source.identity.size
                or hashlib.sha256(template_source.content).hexdigest() != template_source.identity.sha256):
            raise ValueError('template source bytes changed')
        await read_verified_file(editor.workspace, scope, snapshot_path,
            size=len(document.markdown.encode()), sha256=document.sha256,
            error_code='report_editor_template_snapshot_changed', format_name='正文快照')
        if hashlib.sha256(document.markdown.encode()).hexdigest() != document.sha256:
            raise ValueError('document snapshot does not match selected SHA')
        from ..reporting.workflow.runtime.template_semantics import (
            prepare_semantic_template,
            semantic_review_reference,
        )

        issues.extend(getattr(template_source, 'semantic_issues', ()))
        semantic_record = getattr(template_source, 'semantic_review', None)
        prepared_template, semantic_receipt, semantic_issues = prepare_semantic_template(
            template_source.content, semantic_record)
        issues.extend(issue for issue in semantic_issues if issue not in issues)
        if semantic_receipt is not None:
            semantic_receipt['review'] = semantic_review_reference(semantic_record)
        if semantic_receipt is not None and semantic_receipt['status'] == 'resolved':
            from ..reporting.delivery.template_signature_readback import read_semantic_preparation

            try:
                independent = await run_office_engine(read_semantic_preparation,
                    template_source.content, prepared_template, semantic_record, semantic_receipt)
                semantic_receipt['preparationReadback'] = independent
                if independent['status'] != 'passed' or independent['coverage'] != 'complete':
                    from ..reporting.template_semantic_review import semantic_issue

                    issues.extend(independent['issues'])
                    issues.append(semantic_issue('unavailable'))
                    prepared_template = template_source.content
                    semantic_receipt['status'] = 'unavailable'
            except Exception as error:
                from ..reporting.template_semantic_review import semantic_issue

                logger.warning('editor_semantic_preparation_unavailable error_type={}', type(error).__name__)
                issues.append(semantic_issue('unavailable'))
                prepared_template, semantic_receipt = template_source.content, None
        if not job.get('_documentContext') and getattr(template_source, 'document_context', None):
            job['_documentContext'] = deepcopy(template_source.document_context)
        if not job.get('_formatPreferences') and template_source.configuration is not None:
            job['_formatPreferences'] = deepcopy(template_source.configuration['resolvedFormats'])
            job['_formatDesigns'] = {format: document_design(job['_formatPreferences'][format]).compact()
                for format in ('pdf', 'word')}
        candidates = list(source_context.job.get('render', {}).get('images', ()))
        if render_manifest is not None:
            manifest = ReportArtifactManifest.model_validate(render_manifest)
            if (manifest.report_id != context.report_id or manifest.markdown.path != snapshot_path
                    or manifest.markdown.sha256 != document.sha256
                    or manifest.markdown.size != len(document.markdown.encode())):
                raise ValueError('template image manifest differs from frozen editor document')
            candidates = [item.model_dump() for item in manifest.charts]
        bindings, resource_issues = bind_template_images(document.markdown, snapshot_path, candidates)
        issues.extend(resource_issues)
        resources, images = {}, []
        for source, identity in bindings.items():
            try:
                resources[source] = await read_verified_file(editor.workspace, scope, identity['path'],
                    size=identity['size'], sha256=identity['sha256'],
                    error_code='report_editor_template_image_changed', format_name='正文图片')
                images.append({key: identity[key] for key in ('path', 'size', 'sha256')})
            except Exception as error:
                logger.warning('editor_template_image_unavailable error_type={}', type(error).__name__)
                issues.append(resource_issue())
        job['_templateSource'] = deepcopy(template_source.binding)
        job.pop('_templateSemanticReview', None)
        if (semantic_receipt is not None and semantic_receipt['status'] == 'resolved'
                and semantic_receipt.get('preparationReadback', {}).get('status') == 'passed'
                and semantic_receipt.get('preparationReadback', {}).get('coverage') == 'complete'):
            job['_templateSemanticReview'] = deepcopy(semantic_receipt['review'])
        job['render'] = {'markdown': {'path': snapshot_path, 'size': len(document.markdown.encode()),
            'sha256': document.sha256}, 'images': images}
        for format in formats:
            path = str(PurePosixPath(output_path).with_suffix('.docx' if format == 'word' else '.pdf'))
            generated = None
            try:
                title, signature, resolved, generated_date = _format_content(job, template_source.configuration, format)
                if signature is None:
                    issues.append({'code': 'report_editor_template_signature_unavailable',
                        'message': '本修订缺少已冻结的落款或日期，未采用当前默认；请核对实际文件。'})
                if not title:
                    raise ValueError('frozen template title unavailable')
                filled = await run_office_engine(fill_report_template, prepared_template,
                    template_format='docx', delivery_format='docx' if format == 'word' else 'pdf',
                    values={'report_title': title, 'report_content': strip_signature(document.markdown)},
                    body_resources=resources, **({'signature': signature} if signature is not None else {}))
                issues.extend(filled.issues)
                generated = filled.content
                bindings[format] = filled.signature_binding
                if (bindings[format] is not None and semantic_receipt is not None
                        and semantic_receipt['status'] == 'resolved'
                        and bindings[format].get('placement') == 'declared_template_slot'):
                    bindings[format] = {**bindings[format], 'placement': 'semantic_template_slot'}
                await editor.workspace.awrite_bytes(scope['threadId'], path, generated)
            except WorkspacePathConflict:
                if not result:
                    raise
                issues.append({'code': 'report_editor_template_target_conflict',
                    'message': '另一格式目标已存在，未使用或覆盖该文件；本次已生成的其他格式仍可下载。'})
                continue
            except Exception as error:
                logger.warning('editor_template_generation_failed format={} error_type={}', format, type(error).__name__)
                issues.append({'code': 'report_editor_template_generation_failed',
                    'message': f'{"文字文档" if format == "word" else "PDF"} 模板生成或保存未完成，已生成文件仍保留。'})
            if generated is None:
                continue
            identity = {'path': path, 'size': len(generated), 'sha256': hashlib.sha256(generated).hexdigest()}
            try:
                stored = await read_verified_file(editor.workspace, scope, path, size=identity['size'],
                    sha256=identity['sha256'], error_code='report_editor_template_output_changed', format_name='模板成品')
            except Exception as error:
                logger.warning('editor_template_output_unreadable format={} error_type={}', format, type(error).__name__)
                issues.append({'code': 'report_editor_template_output_unavailable',
                    'message': f'{"文字文档" if format == "word" else "PDF"} 成品实际身份不可读取，不能签发此文件。'})
                continue
            job['render'][format] = identity
            result.update({format + 'Path': path, format + 'Size': identity['size'], format + 'Sha256': identity['sha256']})
            try:
                if signature is not None:
                    frozen = {'markdown': document.markdown,
                        'state': {'_documentContext': {'title': title, 'generatedDate': generated_date}}}
                    receipt = await run_office_engine(read_template_document, stored, format, resolved,
                        frozen, prepared_template, body_resources=resources)
                    if semantic_receipt is not None:
                        detail = receipt.get('templateReadback', {})
                        detail['semanticPreparation'] = deepcopy(semantic_receipt)
                        if semantic_receipt['status'] == 'resolved':
                            if detail.get('signature', {}).get('declaration') == 'report_signature_sdt':
                                detail['signature']['declaration'] = 'semantic_signature_sdt'
                            if detail.get('outsideDeclaredTargets', {}).get('scope'):
                                detail['outsideDeclaredTargets']['scope'] = 'package_parts_outside_semantic_and_declared_targets'
                    issues.extend(receipt.get('issues', ()))
                    issues.extend({'code': 'report_editor_template_content_mismatch',
                        'message': item.get('message', '模板实际内容与冻结来源不一致。')}
                        for item in receipt.get('checks', ()) if item.get('passed') is False)
                    readbacks[format] = receipt
                elif format == 'word':
                    body = await run_office_engine(read_template_body, stored, document.markdown, resources,
                        original=prepared_template, report_title=title)
                    issues.extend(body['issues'])
                    readbacks[format] = {'status': 'incomplete', 'templateReadback': {'body': body}}
            except Exception as error:
                logger.warning('editor_template_readback_failed format={} error_type={}', format, type(error).__name__)
                issues.append({'code': 'report_editor_template_readback_failed',
                    'message': '模板成品独立回读未完成，实际文件仍可下载，请核对内容与版式。'})
        if job.get('_reportDesign') or job.get('_editorExportSettings'):
            issues.append({'code': 'report_editor_template_layout_precedence',
                'message': '页面和文字样式沿用上传模板；本次排版设置未覆盖模板，落款内容按本次修订处理。'})
    except WorkspacePathConflict:
        raise
    except Exception as error:
        logger.warning('editor_template_render_unavailable error_type={}', type(error).__name__)
        issues.append({'code': 'report_editor_template_render_unavailable',
            'message': '当前修订模板或冻结材料无法核验，未替换为通用版式；已生成文件仍保留。'})
    issues.append({'code': 'report_editor_template_layout_unverified',
        'message': '模板正文按冻结内容填入，完整页面布局仍需独立复核，未标记验收通过。'})
    result.update(status='validation_failed', validation={'ok': False, 'issues': issues, 'readback': readbacks,
        'template': deepcopy(template_source.binding), 'sourceContentSha256': document.sha256})
    try:
        result['validation']['layoutProvenance'] = build_template_provenance(job=job,
            configuration=template_source.configuration, template=template_source.identity.model_dump(),
            content_sha256=document.sha256, bindings=bindings, readbacks=readbacks,
            identities={format: {'size': result[format + 'Size'], 'sha256': result[format + 'Sha256']}
                for format in ('word', 'pdf') if result.get(format + 'Path')})
    except Exception as error:
        logger.warning('editor_template_provenance_failed error_type={}', type(error).__name__)
        issues.append(unavailable_issue())
    return result
