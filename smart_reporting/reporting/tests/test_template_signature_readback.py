"""准备件由实际模板绑定生成，reader独立发现选区和包内容漂移。"""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.shared import Pt
from lxml import etree

from smart_reporting.reporting.delivery.template_signature_semantics import (
    bind_semantic_signature_slot,
    inspect_signature_candidates,
)

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}


def _parts(raw):
    with ZipFile(BytesIO(raw)) as archive:
        return {item.filename: archive.read(item) for item in archive.infolist()}


def _repack(raw, change):
    parts = _parts(raw)
    change(parts)
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return output.getvalue()


def _edit_document(raw, change):
    def update(parts):
        root = etree.fromstring(parts['word/document.xml'])
        change(root)
        parts['word/document.xml'] = etree.tostring(root)
    return _repack(raw, update)


def _record(raw, indexes):
    view = inspect_signature_candidates(raw)
    blocks = [view['blocks'][index] for index in indexes]
    return {'version': 1, 'status': 'resolved', 'templateSha256': sha256(raw).hexdigest(),
        'blockIds': [block['blockId'] for block in blocks],
        'evidence': [{key: block[key] for key in ('blockId', 'text')} for block in blocks]}


def _case():
    document = Document()
    document.add_paragraph('真实业务引用：清川分析室在2001-02-03确认收入，必须保留。')
    document.add_paragraph('{{report_content}}')
    signer = document.add_paragraph()
    signer.add_run('清川分析室').font.size = Pt(14)
    document.add_paragraph('2001-02-03')
    document.add_table(rows=1, cols=1).cell(0, 0).text = '原生资源保持'
    stream = BytesIO()
    document.save(stream)
    raw = stream.getvalue()
    record = _record(raw, [2, 3])
    prepared, receipt = bind_semantic_signature_slot(raw, record)
    return raw, prepared, record, receipt


def _read(*args):
    from smart_reporting.reporting.delivery.template_signature_readback import (
        read_semantic_preparation,
    )
    return read_semantic_preparation(*args)


def test_real_docx_readback_independently_preserves_selected_properties_and_business_reference(monkeypatch):
    raw, prepared, record, receipt = _case()
    from smart_reporting.reporting.delivery import template_signature_semantics

    def forbidden(*_args, **_kwargs):
        raise AssertionError('独立reader不得调用生成器')
    monkeypatch.setattr(template_signature_semantics, 'bind_semantic_signature_slot', forbidden)
    result = _read(raw, prepared, record, receipt)
    assert result == {'status': 'passed', 'coverage': 'complete',
        'templateSha256': sha256(raw).hexdigest(), 'preparedTemplateSha256': sha256(prepared).hexdigest(),
        'selectedBlockIds': record['blockIds'], 'issues': []}
    reopened = Document(BytesIO(prepared))
    assert reopened.paragraphs[0].text == '真实业务引用：清川分析室在2001-02-03确认收入，必须保留。'
    assert reopened.tables[0].cell(0, 0).text == '原生资源保持'


@pytest.mark.parametrize('fault', ['outside_text', 'outside_attribute', 'selected_text', 'selected_attribute',
    'extra_part', 'resource', 'double_slot', 'wrong_location', 'wrapper_attribute'])
def test_matching_hash_receipt_never_hides_native_or_package_drift(fault):
    raw, prepared, record, receipt = _case()

    def change(root):
        body = root.find('w:body', NS)
        slot = body.find('w:sdt', NS)
        if fault == 'outside_text':
            body.find('w:p/w:r/w:t', NS).text = '伪造的业务引用'
        elif fault == 'outside_attribute':
            body[0].set(f'{{{W}}}rsidR', '11111111')
        elif fault == 'selected_text':
            slot.find('w:sdtContent/w:p/w:r/w:t', NS).text = '替换样例原文'
        elif fault == 'selected_attribute':
            slot.find('w:sdtContent/w:p/w:r/w:rPr/w:sz', NS).set(f'{{{W}}}val', '48')
        elif fault == 'double_slot':
            body.insert(0, deepcopy(slot))
        elif fault == 'wrong_location':
            body.remove(slot)
            body.insert(0, slot)
        else:
            slot.set(f'{{{W}}}rsidR', '11111111')

    if fault == 'extra_part':
        prepared = _repack(prepared, lambda parts: parts.update({'custom/foreign.bin': b'foreign'}))
    elif fault == 'resource':
        prepared = _repack(prepared, lambda parts: parts.update({'word/styles.xml': parts['word/styles.xml'] + b'\n'}))
    else:
        prepared = _edit_document(prepared, change)
    receipt['preparedTemplateSha256'] = sha256(prepared).hexdigest()
    result = _read(raw, prepared, record, receipt)
    assert result['status'] == 'failed' and result['coverage'] == 'unverified'
    assert result['issues'] and result['issues'][0]['code'] == 'report_template_signature_preparation_readback_failed'


@pytest.mark.parametrize('fault', ['prepared_hash', 'source_hash', 'receipt_group', 'record_group',
    'evidence', 'noncontiguous', 'duplicate', 'version', 'status'])
def test_frozen_identity_selection_and_exact_evidence_are_rechecked(fault):
    raw, prepared, record, receipt = _case()
    if fault == 'prepared_hash':
        receipt['preparedTemplateSha256'] = '0' * 64
    elif fault == 'source_hash':
        record['templateSha256'] = '0' * 64
    elif fault == 'receipt_group':
        receipt['selectedBlockIds'] = [record['blockIds'][0]]
    elif fault == 'record_group':
        record = _record(raw, [0])
        receipt['selectedBlockIds'] = record['blockIds']
    elif fault == 'evidence':
        record['evidence'][0]['text'] += ' '
    elif fault == 'noncontiguous':
        record = _record(raw, [0, 3])
        receipt['selectedBlockIds'] = record['blockIds']
    elif fault == 'duplicate':
        record['blockIds'] *= 2
        record['evidence'] *= 2
        receipt['selectedBlockIds'] = record['blockIds']
    elif fault == 'version':
        record['version'] = True
    else:
        record['status'] = 'unavailable'
    assert _read(raw, prepared, record, receipt)['status'] == 'failed'


@pytest.mark.parametrize('fault', ['declared_source', 'protected_placeholder', 'protected_bookmark'])
def test_declared_or_native_protected_sources_cannot_be_certified(fault):
    raw, prepared, record, receipt = _case()
    if fault == 'declared_source':
        raw = prepared
    elif fault == 'protected_placeholder':
        record = _record(raw, [1, 2, 3])
    else:
        def protect(root):
            body = root.find('w:body', NS)
            marker = etree.Element(f'{{{W}}}bookmarkStart', {f'{{{W}}}id': '1', f'{{{W}}}name': 'business'})
            body.insert(2, marker)
        raw = _edit_document(raw, protect)
        record = _record(raw, [3, 4])
    record['templateSha256'] = receipt['templateSha256'] = sha256(raw).hexdigest()
    receipt['selectedBlockIds'] = record['blockIds']
    assert _read(raw, prepared, record, receipt)['status'] == 'failed'


@pytest.mark.parametrize('original,prepared,record,receipt', [(b'bad', b'bad', {}, {}),
    (b'', b'', None, None)])
def test_bad_packages_and_receipts_return_soft_failure(original, prepared, record, receipt):
    result = _read(original, prepared, record, receipt)
    assert result['status'] == 'failed' and result['coverage'] == 'unverified'
    assert result['issues'] and 'Traceback' not in str(result)


@pytest.mark.parametrize('path', ['w:sdtPr', 'w:sdtPr/w:tag', 'w:sdtContent'])
def test_wrapper_cannot_hide_unselected_literal_text(path):
    raw, prepared, record, receipt = _case()
    def inject(root):
        root.find('w:body/w:sdt/' + path, NS).tail = '新增游离正文'
    prepared = _edit_document(prepared, inject)
    receipt['preparedTemplateSha256'] = sha256(prepared).hexdigest()
    assert _read(raw, prepared, record, receipt)['status'] == 'failed'


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16-le', 'utf-16-be'])
def test_independent_readback_preserves_comments_instructions_and_encoded_paragraph_tails(encoding):
    raw, _, _, _ = _case()
    def update(parts):
        root = etree.fromstring(parts['word/document.xml'])
        body = root.find('w:body', NS)
        body.insert(0, etree.Comment('未选注释'))
        body.insert(1, etree.ProcessingInstruction('business', 'keep'))
        for child in body:
            child.tail = '\n'
        parts['word/document.xml'] = (f'<?xml version="1.0" encoding="{encoding}"?>'
            + etree.tostring(root, encoding='unicode')).encode(encoding)
    raw = _repack(raw, update)
    record = _record(raw, [4, 5])
    prepared, receipt = bind_semantic_signature_slot(raw, record)
    assert _read(raw, prepared, record, receipt)['status'] == 'passed'
