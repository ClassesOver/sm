"""服务端绑定真实报告材料的只读草稿验收；不发布版本、不签发业务链接。

材料对象只能由服务端任务工作区构造，不能直接从 HTTP 请求反序列化。
生成成功、独立回读成功和所有偏好均已验收是三个不同结论。
"""
from __future__ import annotations

import shutil
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from loguru import logger

from ..preferences.capabilities import unsupported_preference_reason as _unsupported
from ..preferences.document_adapter import document_design
from ..preferences.markdown_adapter import append_signature
from ..preferences.models import FORMATS, FormatPreferences, resolve_format_preferences
from ..reporting.delivery.office_engine import libreoffice_to_pdf
from ..reporting.delivery.pptx import build_editable_pptx
from ..reporting.delivery.report_runtime.runtime import ReportRuntime
from ..reporting.delivery.report_runtime.validation import (
    _input_path,
    _reject_symlinks,
    _relative_path,
)
from ..reporting.delivery.xlsx import build_workbook
from .configuration_preview import MEDIA, _artifact
from .configuration_store import configuration_hash
from .models import ManagementError
from .preference_preflight_readback import readback as _readback


@dataclass(frozen=True)
class PreferencePreflightMaterials:
    """复用任务原生输入；workspace 必须由服务端已绑定的任务解析。"""

    workspace: Path
    markdown_path: str
    state: dict[str, Any]
    sheets: tuple[dict[str, Any], ...]
    slides: tuple[dict[str, Any], ...]
    template_source: dict[str, Any] | None = None


def _issue(code, message):
    return {'code': code, 'message': message}


def _verify_materials(materials, *, formats=None):
    workspace = materials.workspace.resolve()
    state = deepcopy(materials.state)
    try:
        ReportRuntime(workspace)._validate_datasets(state)
        source = _input_path(workspace, materials.markdown_path, '.md')
        identities = {item['path']: item for item in state['sources']}
        if len(identities) != len(state['sources']) or materials.markdown_path not in identities:
            raise ValueError('源身份缺失或重复')
        slides = deepcopy(materials.slides)
        for slide in slides:
            if 'chartPath' not in slide:
                continue
            relative = slide['chartPath']
            _relative_path(relative)
            if relative not in identities:
                raise ValueError('图像未登记')
            image = workspace / relative
            _reject_symlinks(workspace, image)
            if image.suffix.lower() not in {'.png', '.jpg', '.jpeg'}:
                raise ValueError('仅接受静态图像')
        if formats is None and materials.template_source is None and (not materials.sheets or not slides):
            raise ValueError('缺少正式工作簿或演示文稿材料')
        context = state['_documentContext']
        for key in ('title', 'periodLabel', 'generatedDate'):
            if not context[key]:
                raise ValueError('缺少文档上下文')
        # 确认源文件可读；正式渲染器负责其余原生文档契约校验。
        source.read_text(encoding='utf-8')
    except Exception as error:
        raise ManagementError('management_preference_materials_invalid',
            '验收材料身份无效或未完整绑定当前服务端工作区，请重新读取任务材料。', 409) from error
    frozen = {'markdownPath': materials.markdown_path, 'markdown': source.read_text(encoding='utf-8'), 'state': state,
        'sheets': deepcopy(materials.sheets), 'slides': slides}
    if state.get('_tableCaptionManifest') is not None:
        try:
            manifest = state['_tableCaptionManifest']
            identity = manifest['traceIndex']
            if type(identity['size']) is not int or not 0 <= identity['size'] <= 32 * 1024 * 1024:
                raise ValueError('表题索引大小无效')
            index = _input_path(workspace, identity['path'], '.json')
            if index.stat().st_size != identity['size']:
                raise ValueError('表题索引大小改变')
            raw = index.read_bytes()
            if sha256(raw).hexdigest() != identity['sha256']:
                raise ValueError('表题索引身份改变')
            frozen['tableCaptionInput'] = {'manifest': deepcopy(manifest),
                'traceIndexText': raw.decode('utf-8'), 'markdownText': source.read_bytes().decode('utf-8'),
                'workflowRunId': state.get('_tableCaptionWorkflowRunId')}
        except Exception as error:
            logger.warning('preference_table_caption_material_unavailable error_type={}', type(error).__name__)
    if materials.template_source is not None:
        from .preference_template_preflight import verify_docx_template, verify_template_source

        try:
            # 模板图片单独冻结，不能挤占业务源文件的20项限制。
            for identity in materials.template_source.get('images', ()):
                from pathlib import PurePosixPath

                path = _input_path(workspace, identity['path'], PurePosixPath(identity['path']).suffix)
                raw = path.read_bytes()
                if (len(raw) != identity['size'] or sha256(raw).hexdigest() != identity['sha256']
                        or identity['path'] in identities and identities[identity['path']] != identity):
                    raise ValueError('template image identity mismatch')
                identities[identity['path']] = deepcopy(identity)
            frozen['templateSource'] = verify_template_source(materials.template_source, identities, materials.markdown_path)
            verify_docx_template((workspace / frozen['templateSource']['identity']['path']).read_bytes())
        except Exception as error:
            raise ManagementError('management_preference_materials_invalid',
                '模板实际文件不是可核验的DOCX包，未使用通用生成替代。', 409) from error
        frozen['formats'] = tuple(format for format in FORMATS if format in (formats or FORMATS)
            and format in ('md', 'pdf', 'word'))
    elif formats is not None:
        frozen['formats'] = tuple(format for format in FORMATS if format in formats
            and (format != 'xlsx' or frozen['sheets']) and (format != 'pptx' or slides))
    return workspace, frozen, configuration_hash(frozen)


def _generate(root, preferences, frozen):
    """复用五格式正式生成器；每一格式异常只记原因，保留实际写出的文件。"""
    issues = {format: [] for format in FORMATS}
    selected = frozen.get('formats', FORMATS)
    context = frozen['state']['_documentContext']
    source_root = root / 'inputs'
    source = source_root / frozen['markdownPath']
    for format in ('md', 'xlsx', 'pptx'):
        if format not in selected:
            continue
        try:
            resolved = resolve_format_preferences(preferences, format)
            native_context = frozen['state'].get('_nativeDocumentContexts', {}).get(format, context)
            if format == 'md':
                (root / 'report.md').write_text(append_signature(source.read_text(encoding='utf-8'),
                    resolved, context['generatedDate'],
                    heading_numbers=context['headingNumbers'],
                    citation_presentations=frozen['state'].get('_citationPresentations')),
                    encoding='utf-8')
            elif format == 'xlsx':
                result = build_workbook(output_path=root / 'report.xlsx', title=native_context['title'],
                    period=native_context['periodLabel'], sheets=frozen['sheets'], preferences=resolved,
                    source_mapping=frozen['state'].get('_workbookSourceMapping'),
                    generated_date=native_context['generatedDate'])
                issues[format].extend(result.issues)
            else:
                slides = deepcopy(frozen['slides'])
                for slide in slides:
                    if 'chartPath' in slide:
                        slide['chartPath'] = str(source_root / slide['chartPath'])
                result = build_editable_pptx(output_path=root / 'report.pptx', title=native_context['title'],
                    period=native_context['periodLabel'], theme=resolved['theme'], slides=slides,
                    preferences=resolved, generated_date=native_context['generatedDate'])
                issues[format].extend(result.issues)
        except Exception:
            logger.warning('preference_preflight_generation_failed format={}', format)
            issues[format].append(_issue('management_preference_generation_failed',
                f'{format} 正式生成或生成回执检查失败；已生成且身份可读的原生文件仍予保留。'))
    document_formats = tuple(format for format in ('pdf', 'word') if format in selected)
    if not document_formats:
        return issues
    try:
        state = deepcopy(frozen['state'])
        formats = {key: resolve_format_preferences(preferences, key) for key in ('pdf', 'word')}
        state['_formatPreferences'] = formats
        state['_formatDesigns'] = {key: document_design(value).compact() for key, value in formats.items()}
        # 草稿验收不继承旧任务上一次的可变设计覆盖。
        state.pop('_reportDesign', None)
        # 仅传入材料快照已经核验的静态图片；渲染器还会核对实际字节与正文引用范围。
        chart_images = [{'chartId': item['path'], **item} for item in state['sources']
            if Path(item['path']).suffix.lower() in {'.png', '.jpg', '.jpeg'}]
        result = ReportRuntime(source_root).render_markdown(state, frozen['markdownPath'],
            'revision/report.pdf', '.reporting-tmp/workspace-report-preflight-render/render.pdf',
            chart_images=chart_images)
        for format in document_formats:
            issues[format].extend(result.get('renderIssues', []))
    except Exception:
        logger.warning('preference_preflight_document_generation_failed')
        for format in document_formats:
            issues[format].append(_issue('management_preference_generation_failed',
                f'{format} 正式生成失败；其他已生成文件仍予保留。'))
    return issues


def _leaves(value, prefix=''):
    for key, nested in value.items():
        path = prefix + '.' + key if prefix else key
        if isinstance(nested, dict):
            yield from _leaves(nested, path)
        else:
            yield path, nested


def _not_exercised(format, local, frozen):
    from markdown_it import MarkdownIt

    tokens = MarkdownIt('commonmark').enable('table').parse(frozen['markdown'])
    if format == 'md':
        feature = {'listMarker': 'bullet_list_open', 'codeFence': 'fence', 'tableStyle': 'table_open'}
        if local in feature and not any(token.type == feature[local] for token in tokens):
            return '当前真实材料未包含此偏好对应的原生内容。'
        if local == 'references' and '[[citation:' not in frozen['markdown']:
            return '当前材料没有已登记引用标记。'
    if format == 'pptx':
        if (local.startswith('typography.caption.') or local in {
            'charts.captionNumbering', 'charts.imageDpi', 'layout'}) and not any(
            slide.get('chartPath') for slide in frozen['slides']):
            return '当前演示文稿材料没有已登记静态图像。'
        if local.startswith('typography.body.') and not any(slide.get('bullets') for slide in frozen['slides']):
            return '当前演示文稿材料没有正文要点。'
    return None


def _capabilities(format, resolved, readback, frozen):
    checked = {}
    for item in readback.get('checks', []):
        if item.get('path'):
            checked.setdefault(item['path'], []).append(item)
    capabilities = []
    for local, value in _leaves(resolved):
        path = format + '.' + local
        reason = _unsupported(format, path)
        checks = checked.get(path)
        if checks and any(not item['passed'] for item in checks):
            status, reason = 'failed', '至少一处实际原生属性与冻结偏好不一致。'
        elif reason:
            status = 'unsupported'
        elif checks:
            if any(item.get('coverage') != 'complete' for item in checks):
                status, reason = 'not_verified', '仅完成局部采样或样式定义回读，不能推定该字段已在全部实际内容中验收。'
            else:
                status, reason = 'verified', checks[0]['message']
        elif reason := _not_exercised(format, local, frozen):
            status = 'not_exercised'
        else:
            status, reason = 'not_verified', '尚无针对本材料和本字段的独立产物回读证据；不能推定已验收。'
        capabilities.append({'path': path, 'value': value, 'status': status, 'reason': reason})
    return capabilities


def run_preference_preflight(draft: dict, materials: PreferencePreflightMaterials, *,
    expected_version: int, expected_content_hash: str, formats: tuple[str, ...] | None = None) -> dict:
    """验收服务端冻结材料；显式 formats 只运行已绑定格式，缺失格式不可据此应用。"""
    if (type(expected_version) is not int or draft.get('version') != expected_version
        or draft.get('contentHash') != expected_content_hash):
        raise ManagementError('management_version_conflict', '草稿版本或内容摘要已变化，请重新读取草稿。', 409)
    document = deepcopy(draft['document'])
    preferences = FormatPreferences.model_validate(document)
    if configuration_hash(document) != expected_content_hash or preferences.model_dump(mode='json', by_alias=True) != document:
        raise ManagementError('management_configuration_corrupt', '草稿内容身份校验失败。', 409)
    if formats is not None and (not isinstance(formats, tuple)
        or any(format not in FORMATS for format in formats) or len(set(formats)) != len(formats)):
        raise ManagementError('management_preference_formats_invalid', '服务端验收格式选择无效。', 409)
    workspace, frozen, material_hash = _verify_materials(materials, formats=formats)
    selected = frozen.get('formats', FORMATS)
    format_results = {}
    with tempfile.TemporaryDirectory(prefix='preference-preflight-') as directory:
        root = Path(directory)
        for item in frozen['state']['sources']:
            target = root / 'inputs' / item['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(workspace / item['path'], target)
        for item in frozen.get('templateSource', {}).get('images', ()):
            target = root / 'inputs' / item['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(workspace / item['path'], target)
        caption_input = frozen.get('tableCaptionInput')
        if caption_input is not None:
            # 表题索引属于展示来源，独立搬运；不能挤占业务数据集数量上限。
            target = root / 'inputs' / caption_input['manifest']['traceIndex']['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(caption_input['traceIndexText'].encode('utf-8'))
        # 拷贝后再验身份，避免来源在首次校验与读取之间改变。
        ReportRuntime(root / 'inputs')._validate_datasets(frozen['state'])
        template_generation = {}
        try:
            if frozen.get('templateSource') is not None:
                from .preference_template_preflight import generate_template_documents

                generation_issues = {format: [] for format in FORMATS}
                if 'md' in selected:
                    generation_issues = _generate(root, preferences, {**frozen, 'formats': ('md',)})
                template_generation = generate_template_documents(root, preferences, frozen)
                for format, generated in template_generation.items():
                    generation_issues[format].extend(generated['issues'])
            else:
                generation_issues = _generate(root, preferences, frozen)
        except Exception:
            logger.warning('preference_preflight_generation_receipt_failed')
            generation_issues = {format: [_issue('management_preference_generation_failed',
                '生成回执收集失败；仍独立读取已写出的各格式文件并保留其实际身份。')] for format in FORMATS}
        for format in FORMATS:
            resolved = resolve_format_preferences(preferences, format)
            if format not in selected:
                reason = '当前修订未绑定此格式的完整正式生成材料，未执行生成或独立回读。'
                format_results[format] = {'availability': 'unavailable', 'artifact': None, 'pdf': None,
                    'previewPageCount': 0, 'readback': {'status': 'unavailable', 'checks': []},
                    'capabilities': [{'path': format + '.' + path, 'value': value,
                        'status': 'unavailable', 'reason': reason} for path, value in _leaves(resolved)],
                    'issues': [_issue('management_preference_format_unavailable', reason)], 'status': 'incomplete'}
                continue
            suffix = '.docx' if format == 'word' else '.' + format
            path = root / ('report' + suffix)
            if format in {'pdf', 'word'} and not path.is_file():
                path = root / 'inputs' / 'revision' / ('report' + suffix)
            issues = list(generation_issues[format])
            artifact, pdf, preview_pages = None, None, 0
            readback = {'status': 'failed', 'checks': []}
            if path.is_file():
                try:
                    content = path.read_bytes()
                    if not content:
                        raise ValueError('empty artifact')
                    artifact = _artifact(content, format + suffix, MEDIA[format])
                except Exception:
                    issues.append(_issue('management_preference_identity_unavailable', f'{format} 文件身份不可读取。'))
            if artifact:
                try:
                    readback_frozen = frozen
                    native_context = frozen['state'].get('_nativeDocumentContexts', {}).get(format)
                    if format in {'xlsx', 'pptx'} and native_context is not None:
                        readback_frozen = {**frozen, 'state': {**frozen['state'],
                            '_documentContext': deepcopy(native_context)}}
                    if frozen.get('templateSource') is not None and format in ('pdf', 'word'):
                        from .preference_template_preflight import template_body_resources
                        from .preference_template_readback import read_template_document

                        resources, resource_issues = template_body_resources(root / 'inputs', frozen)
                        issues.extend(resource_issues)
                        generated = template_generation.get(format, {})
                        original = generated.get('readbackTemplate')
                        if original is None:
                            original = (root / 'inputs' / frozen['templateSource']['identity']['path']).read_bytes()
                        readback = read_template_document(content, format, resolved, frozen, original,
                            body_resources=resources)
                        semantic = generated.get('semanticPreparation')
                        if semantic is not None:
                            detail = readback.get('templateReadback', {})
                            detail['semanticPreparation'] = deepcopy(semantic)
                            if semantic['status'] == 'resolved':
                                if detail.get('signature', {}).get('declaration') == 'report_signature_sdt':
                                    detail['signature']['declaration'] = 'semantic_signature_sdt'
                                if detail.get('outsideDeclaredTargets', {}).get('scope'):
                                    detail['outsideDeclaredTargets']['scope'] = 'package_parts_outside_semantic_and_declared_targets'
                    else:
                        readback = _readback(content, format, resolved, readback_frozen)
                    failures = [item for item in readback['checks'] if not item['passed']]
                    if failures:
                        issues.append({**_issue('management_preference_native_mismatch',
                            f'{format} 独立回读发现原生属性或来源内容不一致，请查看具体回读项。'),
                            'paths': list(dict.fromkeys(item['path'] or 'sourceContent' for item in failures))})
                except Exception:
                    logger.warning('preference_preflight_readback_failed format={}', format)
                    issues.append(_issue('management_preference_readback_failed', f'{format} 独立原生回读失败；实际文件身份仍保留。'))
                if format != 'md':
                    try:
                        from io import BytesIO

                        from pypdf import PdfReader

                        pdf_bytes = content if format == 'pdf' else libreoffice_to_pdf(content, suffix=suffix, timeout=60)
                        preview_pages = len(PdfReader(BytesIO(pdf_bytes)).pages)
                        pdf = _artifact(pdf_bytes, format + '-preview.pdf', MEDIA['pdf'])
                    except Exception:
                        logger.warning('preference_preflight_preview_failed format={}', format)
                        issues.append(_issue('management_preference_preview_failed', f'{format} PDF 预览失败；原生文件仍保留。'))
            else:
                issues.append(_issue('management_preference_artifact_missing', f'{format} 未生成身份可读取的文件。'))
            capabilities = _capabilities(format, resolved, readback, frozen)
            format_results[format] = {'availability': 'available', 'artifact': artifact, 'pdf': pdf, 'previewPageCount': preview_pages,
                'readback': readback, 'capabilities': capabilities, 'issues': issues,
                'status': 'failed' if issues or readback['status'] != 'passed' else 'incomplete'
                    if any(item['status'] != 'verified' for item in capabilities) else 'passed'}
            if frozen.get('templateSource') is not None and format in ('pdf', 'word'):
                format_results[format]['templateReadback'] = readback.get('templateReadback', {'status': 'unavailable'})
                try:
                    from .preference_template_preflight import template_provenance

                    format_results[format]['provenance'] = template_provenance(frozen, resolved,
                        template_generation.get(format, {}).get('signatureBinding'), readback)
                except Exception:
                    logger.warning('preference_template_provenance_failed format={}', format)
                    issues.append(_issue('management_preference_template_provenance_failed',
                        '模板来源回执未能完整读取，实际生成文件仍保留，不能据此批准。'))
                    format_results[format]['status'] = 'failed'
                for issue in readback.get('issues', []):
                    issues.append(issue)
                format_results[format]['status'] = 'failed' if (issues or readback['status'] == 'failed') else 'incomplete'
        try:
            _, _, final_hash = _verify_materials(materials, formats=formats)
            if final_hash != material_hash:
                raise ValueError('材料上下文发生变化')
        except Exception:
            for result in format_results.values():
                result['issues'].append(_issue('management_preference_materials_changed',
                    '验收期间服务端来源材料发生变化，已生成文件保留但不可据此应用草稿。'))
                result['status'] = 'failed'
    can_apply = all(item['status'] == 'passed' for item in format_results.values())
    return {'schemaVersion': 1, 'draftVersion': expected_version, 'contentHash': expected_content_hash,
        'materialHash': material_hash, 'scope': 'server_bound_report_materials',
        'status': 'passed' if can_apply else 'failed' if any(item['status'] == 'failed'
            for item in format_results.values()) else 'incomplete', 'canApply': can_apply, 'formats': format_results}
