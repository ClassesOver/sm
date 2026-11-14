"""独立回读语义准备件；不调用绑定生成器，不将模型判断提升为布局验收。"""

from hashlib import sha256

from loguru import logger
from lxml import etree

from .template_body_readback import _package
from .template_signature_semantics import _xml, inspect_signature_candidates

_W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
_NS = {'w': _W}
_WQ = '{' + _W + '}'


def _shape(node, ignored_prefixes=(), *, tail=True):
    """展开QName比较原生结构及属性，忽略新增包装的无业务命名空间别名。"""
    suffix = node.tail if tail else None
    if isinstance(node, etree._Comment):
        return ('comment', node.text, suffix)
    if isinstance(node, etree._ProcessingInstruction):
        return ('pi', node.target, node.text, suffix)
    namespaces = tuple(sorted((prefix or '', uri) for prefix, uri in node.nsmap.items()
        if prefix not in ignored_prefixes))
    return (node.tag, tuple(sorted(node.attrib.items())), namespaces, node.text, suffix,
        tuple(_shape(child, ignored_prefixes) for child in node))


def _selected(view, record, receipt):
    if (not isinstance(record, dict) or not isinstance(receipt, dict)
            or type(record.get('version')) is not int or record['version'] != 1
            or record.get('status') != 'resolved' or receipt.get('status') != 'resolved'
            or record.get('templateSha256') != view['templateSha256']
            or receipt.get('templateSha256') != view['templateSha256'] or view['declared']):
        raise ValueError('源模板或冻结语义记录身份不匹配')
    ids, evidence = record.get('blockIds'), record.get('evidence')
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 12
            or not all(isinstance(item, str) for item in ids) or len(set(ids)) != len(ids)
            or not isinstance(evidence, list) or len(evidence) != len(ids)
            or receipt.get('selectedBlockIds') != ids):
        raise ValueError('冻结选区及证据不完整')
    positions = {block['blockId']: index for index, block in enumerate(view['blocks'])}
    indexes = [positions.get(identity, -1) for identity in ids]
    if indexes[0] < 0 or indexes != list(range(indexes[0], indexes[0] + len(ids))):
        raise ValueError('冻结选区不是源模板连续段落')
    for identity, index, proof in zip(ids, indexes, evidence, strict=True):
        block = view['blocks'][index]
        if (not block['eligible'] or not isinstance(proof, dict)
                or proof.get('blockId') != identity or proof.get('text') != block['text']):
            raise ValueError('源选区受保护或逐字证据不匹配')
    return ids, indexes


def _check_document(original, prepared, indexes):
    source, target = _xml(original), _xml(prepared)
    source_body = source.find('w:body', _NS)
    bodies = target.findall('w:body', _NS)
    declarations = target.xpath('.//w:tag[@w:val="report_signature"]', namespaces=_NS)
    slots = target.xpath('./w:body/w:sdt[w:sdtPr/w:tag[@w:val="report_signature"]]', namespaces=_NS)
    if target.tag != _WQ + 'document' or len(bodies) != 1 or len(declarations) != 1 or len(slots) != 1:
        raise ValueError('准备件必须包含唯一正文级落款声明')
    slot, body = slots[0], bodies[0]
    if body.index(slot) != indexes[0] or slot.attrib or len(slot) != 2:
        raise ValueError('准备件落款包装或位置发生变化')
    properties, content = slot
    if (properties.tag != _WQ + 'sdtPr' or properties.attrib or len(properties) != 1
            or properties[0].tag != _WQ + 'tag'
            or dict(properties[0].attrib) != {_WQ + 'val': 'report_signature'}
            or len(properties[0]) or content.tag != _WQ + 'sdtContent' or content.attrib
            or any((node.text or '').strip() for node in (slot, properties, properties[0], content))
            or any((node.tail or '').strip() for node in (properties, properties[0], content))
            or len(content) != len(indexes)):
        raise ValueError('准备件声明包含额外原生内容')
    source_prefixes = {prefix for node in source.iter() if isinstance(node.tag, str) for prefix in node.nsmap}
    added = {prefix: uri for prefix, uri in slot.nsmap.items() if body.nsmap.get(prefix) != uri}
    if any(prefix in source_prefixes or uri != _W for prefix, uri in added.items()):
        raise ValueError('落款包装修改现有命名空间')
    for paragraph, index in zip(content, indexes, strict=True):
        if paragraph.tag != _WQ + 'p' or _shape(paragraph, added, tail=False) != _shape(source_body[index], tail=False):
            raise ValueError('准备件选中段落的原文或属性变化')
    paragraphs = list(content)
    last_tail = paragraphs[-1].tail
    paragraphs[-1].tail = (last_tail or '') + (slot.tail or '') if last_tail is not None or slot.tail is not None else None
    position = body.index(slot)
    body.remove(slot)
    for offset, paragraph in enumerate(paragraphs):
        body.insert(position + offset, paragraph)
    if _shape(source) != _shape(target, added):
        raise ValueError('移除包装后原模板正文或选区外内容变化')


def read_semantic_preparation(original: bytes, prepared: bytes, record: dict, receipt: dict) -> dict:
    """独立核对真实准备件；坏身份、坏包及原生漂移一律软失败。"""
    result = {'status': 'failed', 'coverage': 'unverified', 'templateSha256': None,
        'preparedTemplateSha256': None, 'selectedBlockIds': [], 'issues': []}
    try:
        result['templateSha256'] = sha256(original).hexdigest()
        result['preparedTemplateSha256'] = sha256(prepared).hexdigest()
        source_parts, target_parts = _package(original), _package(prepared)
        view = inspect_signature_candidates(original)
        ids, indexes = _selected(view, record, receipt)
        if receipt.get('preparedTemplateSha256') != result['preparedTemplateSha256']:
            raise ValueError('准备件实际身份与生成回执不匹配')
        if (source_parts.keys() != target_parts.keys()
                or any(source_parts[name] != target_parts[name] for name in source_parts if name != 'word/document.xml')):
            raise ValueError('准备件添加、删除或更改其他包资源')
        _check_document(source_parts['word/document.xml'], target_parts['word/document.xml'], indexes)
        result.update(status='passed', coverage='complete', selectedBlockIds=list(ids))
    except Exception as error:
        logger.warning('template_signature_preparation_readback_failed error_type={}', type(error).__name__)
        result['issues'].append({'code': 'report_template_signature_preparation_readback_failed',
            'message': '模板语义准备件独立回读未通过；未据此确认样例替换，原模板及实际产物保留。'})
    return result
