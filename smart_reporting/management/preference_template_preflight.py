"""已绑定DOCX模板的临时草稿生成；复用正式填充器，不写业务修订。"""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZipFile

from loguru import logger
from lxml import etree

from ..preferences.markdown_adapter import strip_signature
from ..preferences.models import resolve_format_preferences
from ..preferences.workbook_adapter import displayed_date
from ..reporting.contract import ReportFileInput
from ..reporting.delivery.report_runtime.validation import _input_path
from ..reporting.delivery.template_body_resources import bind_template_images, resource_issue
from ..reporting.delivery.templates import fill_report_template
from .models import ManagementError


def verify_docx_template(content):
    """后缀不是格式证据；实际包必须声明普通DOCX正文。"""
    with ZipFile(BytesIO(content)) as package:
        members = package.infolist()
        if (len(members) > 10000 or len({item.filename for item in members}) != len(members)
            or sum(item.file_size for item in members) > 200 * 1024 * 1024):
            raise ValueError('template package exceeds limits')
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        types = etree.fromstring(package.read('[Content_Types].xml'), parser)
        main = [node for node in types if node.get('PartName') == '/word/document.xml'
            and node.get('ContentType') == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml']
        root = etree.fromstring(package.read('word/document.xml'), parser)
        namespace = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        if len(main) != 1 or root.tag != namespace + 'document' or root.find(namespace + 'body') is None:
            raise ValueError('template is not a DOCX document')


def verify_template_source(source, identities, markdown_path):
    """来源只来自服务端快照；类型路由与实际复制身份同时冻结。"""
    try:
        template = ReportFileInput.model_validate(source['identity'])
        actual = {key: template.model_dump()[key] for key in ('path', 'size', 'sha256')}
        if (source['templateFormat'] != 'docx' or PurePosixPath(template.filename).suffix.lower() != '.docx'
            or identities.get(template.path) != actual
            or source['sourceContent'] != identities.get(markdown_path)):
            raise ValueError('template identity or route mismatch')
    except (KeyError, TypeError, ValueError) as error:
        raise ManagementError('management_preference_materials_invalid',
            '模板与本修订冻结成稿的实际身份或格式路由不一致，请重新关联。', 409) from error
    return deepcopy(source)


def template_signature(resolved, frozen):
    return {'signer': resolved['common']['signer'],
        'date': displayed_date(frozen['state']['_documentContext']['generatedDate'], resolved['common']['dateFormat']),
        'description': resolved['signature']['description']}


def template_body_resources(source_root, frozen):
    """只读取验收已复制、登记且仍核得实际身份的图片。"""
    identities = [*frozen['state']['sources'], *frozen.get('templateSource', {}).get('images', ())]
    bindings, issues = bind_template_images(frozen['markdown'], frozen['markdownPath'], identities)
    resources = {}
    for source, identity in bindings.items():
        try:
            path = _input_path(source_root, identity['path'], PurePosixPath(identity['path']).suffix)
            raw = path.read_bytes()
            if len(raw) != identity['size'] or sha256(raw).hexdigest() != identity['sha256']:
                raise ValueError('template resource identity changed')
            resources[source] = raw
        except (OSError, ValueError):
            issues.append(resource_issue())
    return resources, issues


def generate_template_documents(root, preferences, frozen):
    """各格式独立取草稿签名；写出文件后任何回执异常不能抹去文件。"""
    raw = (root / 'inputs' / frozen['templateSource']['identity']['path']).read_bytes()
    prepared, semantic_receipt, semantic_issues = raw, None, []
    from ..reporting.delivery.template_signature_readback import read_semantic_preparation
    from ..reporting.template_semantic_review import semantic_issue
    from ..reporting.workflow.runtime.template_semantics import (
        prepare_semantic_template,
        semantic_review_reference,
    )

    try:
        source = frozen['templateSource']
        semantic_issues.extend(deepcopy(source.get('semanticIssues', [])))
        record = source.get('semanticReview')
        if record is not None and source.get('semanticSource', {}).get('review') != semantic_review_reference(record):
            raise ValueError('语义记录与已授权来源摘要不匹配')
        prepared, semantic_receipt, preparation_issues = prepare_semantic_template(raw, record)
        semantic_issues.extend(issue for issue in preparation_issues if issue not in semantic_issues)
        if semantic_receipt is not None:
            semantic_receipt['review'] = semantic_review_reference(record)
        if semantic_receipt is not None and semantic_receipt['status'] == 'resolved':
            independent = read_semantic_preparation(raw, prepared, record, semantic_receipt)
            semantic_receipt['preparationReadback'] = independent
            if independent['status'] != 'passed' or independent['coverage'] != 'complete':
                semantic_issues.extend(independent['issues'])
                semantic_issues.append(semantic_issue('unavailable'))
                prepared, semantic_receipt['status'] = raw, 'unavailable'
    except Exception as error:
        logger.warning('preference_template_semantic_preparation_unavailable error_type={}', type(error).__name__)
        prepared, semantic_receipt = raw, None
        semantic_issues.append(semantic_issue('unavailable'))
    values = {'report_title': frozen['state']['_documentContext']['title'],
        'report_content': strip_signature(frozen['markdown'])}
    resources, resource_issues = template_body_resources(root / 'inputs', frozen)
    generated = {}
    for format in ('pdf', 'word'):
        if format not in frozen['formats']:
            continue
        entry = generated[format] = {'issues': [*resource_issues, *semantic_issues],
            'signatureBinding': None, 'bodyBinding': None, 'readbackTemplate': prepared,
            'semanticPreparation': deepcopy(semantic_receipt)}
        try:
            delivery = 'docx' if format == 'word' else 'pdf'
            filled = fill_report_template(prepared, template_format='docx', delivery_format=delivery,
                values=values, signature=template_signature(resolve_format_preferences(preferences, format), frozen),
                body_resources=resources)
            (root / ('report.' + delivery)).write_bytes(filled.content)
            entry['issues'].extend(filled.issues)
            entry['signatureBinding'] = deepcopy(filled.signature_binding)
            if (entry['signatureBinding'] is not None and semantic_receipt is not None
                    and semantic_receipt['status'] == 'resolved'
                    and entry['signatureBinding']['placement'] == 'declared_template_slot'):
                entry['signatureBinding']['placement'] = 'semantic_template_slot'
            entry['bodyBinding'] = deepcopy(filled.body_binding)
        except Exception:
            logger.warning('preference_template_generation_failed format={}', format)
            entry['issues'].append({'code': 'management_preference_template_generation_failed',
                'message': '正式模板填充或回执未能完成；未使用通用布局替代，实际已生成文件仍保留。'})
    return generated


def template_provenance(frozen, resolved, signature_binding, readback):
    source = frozen['templateSource']
    template = source['identity']
    content = source['sourceContent']
    # 定位回执仅说明实际执行分支，独立reader另行说明可核验范围。
    binding = signature_binding or {}
    body = readback.get('templateReadback', {}).get('body', {})
    native = body.get('status') == 'passed' and body.get('coverage') == 'complete'
    sample = body.get('status') == 'sampled' and body.get('coverage') == 'sample'
    return {'layoutSource': 'uploaded_template', 'contentSource': 'frozen_report_markdown',
        'signatureSource': 'current_draft',
        'bodyRepresentation': 'native_docx_blocks' if native else 'pdf_text_sample' if sample else 'frozen_markdown_text',
        'richDocumentProjection': 'structure_verified' if native else 'sample_only' if sample else 'unverified',
        'generatedDate': frozen['state']['_documentContext']['generatedDate'],
        'template': {key: template[key] for key in ('filename', 'size', 'sha256')},
        'sourceContent': {key: content[key] for key in ('size', 'sha256')},
        'signature': template_signature(resolved, frozen),
        'placement': binding.get('placement', 'unverified'),
        'signatureLayoutSource': binding.get('layoutSource', 'unverified'),
        'templateSampleStatus': binding.get('templateSampleStatus', 'not_assessed'),
        'undeclaredSamples': 'not_assessed', 'layoutValidation': 'unverified',
        'signatureReadback': readback.get('templateReadback', {}).get('signature', {}).get('status', 'unverified')}
