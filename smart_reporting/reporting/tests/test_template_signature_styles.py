"""模板落款显式样式解析：只接受可完整解释的安全继承与关联。"""

from io import BytesIO
from types import SimpleNamespace

import pytest
from lxml import etree

from smart_reporting.reporting.delivery.template_signature_readback import read_semantic_preparation
from smart_reporting.reporting.delivery.template_signature_semantics import (
    bind_semantic_signature_slot,
    inspect_signature_candidates,
)
from smart_reporting.reporting.tests.test_template_signature_semantics import (
    NS,
    W,
    package,
    parts,
    selection,
)


def styled_template(styles, *, paragraph_style='Signature', run_style='SignatureText'):
    p_style = f'<w:pStyle w:val="{paragraph_style}"/>' if paragraph_style else ''
    r_style = f'<w:rStyle w:val="{run_style}"/>' if run_style else ''
    body = ('<w:p><w:r><w:t>业务引用中的旧编制人和历史日期必须保留</w:t></w:r></w:p>'
        f'<w:p><w:pPr>{p_style}<w:jc w:val="right"/></w:pPr>'
        f'<w:r><w:rPr>{r_style}<w:b/></w:rPr><w:t>旧编制人</w:t></w:r></w:p>'
        f'<w:p><w:pPr>{p_style}</w:pPr><w:r><w:t>2001-02-03</w:t></w:r></w:p>')
    return package(body, {'word/styles.xml': f'<w:styles xmlns:w="{W}">{styles}</w:styles>'.encode()})


def style(identity, kind='paragraph', content=''):
    return f'<w:style w:type="{kind}" w:styleId="{identity}">{content}</w:style>'


@pytest.mark.parametrize('linked', [False, True])
def test_safe_explicit_styles_inherit_and_preserve_all_original_parts(linked):
    styles = (style('Base', content='<w:pPr><w:spacing w:after="120"/></w:pPr>')
        + style('Signature', content='<w:name w:val="编制落款"/><w:basedOn w:val="Base"/>'
            + ('<w:link w:val="SignatureText"/>' if linked else ''))
        + style('TextBase', 'character', '<w:rPr><w:sz w:val="24"/></w:rPr>')
        + style('SignatureText', 'character', '<w:basedOn w:val="TextBase"/>'
            + ('<w:link w:val="Signature"/>' if linked else '')))
    raw = styled_template(styles)
    assert all(block['eligible'] for block in inspect_signature_candidates(raw)['blocks'][1:3])
    record = selection(raw, [1, 2])
    prepared, receipt = bind_semantic_signature_slot(raw, record)
    before, after = parts(raw), parts(prepared)
    assert all(before[key] == after[key] for key in before if key != 'word/document.xml')
    original = etree.fromstring(before['word/document.xml'])
    wrapped = etree.fromstring(after['word/document.xml'])
    selected = wrapped.find('w:body/w:sdt/w:sdtContent', NS)
    assert [etree.tostring(node, method='c14n') for node in selected] == [
        etree.tostring(node, method='c14n') for node in original.find('w:body', NS)[1:3]]
    independent = read_semantic_preparation(raw, prepared, record, receipt)
    assert independent['status'] == 'passed' and independent['coverage'] == 'complete'


@pytest.mark.parametrize('hazard', ['vanish', 'webHidden', 'specVanish', 'numPr', 'sectPr', 'pageBreakBefore'])
@pytest.mark.parametrize('branch', ['paragraph_parent', 'character_parent', 'linked_character'])
def test_protected_inherited_or_linked_properties_remain_context_only(hazard, branch):
    properties = f'<w:rPr><w:{hazard}/></w:rPr>' if hazard in {'vanish', 'webHidden', 'specVanish'} else f'<w:pPr><w:{hazard}/></w:pPr>'
    styles = style('Base', content=properties if branch == 'paragraph_parent' else '')
    styles += style('Signature', content='<w:basedOn w:val="Base"/>'
        + ('<w:link w:val="Linked"/>' if branch == 'linked_character' else ''))
    styles += style('TextBase', 'character', properties if branch == 'character_parent' else '')
    styles += style('SignatureText', 'character', '<w:basedOn w:val="TextBase"/>')
    if branch == 'linked_character':
        styles += style('Linked', 'character', properties)
    raw = styled_template(styles)
    assert inspect_signature_candidates(raw)['blocks'][1]['eligible'] is False
    with pytest.raises(ValueError):
        bind_semantic_signature_slot(raw, selection(raw, [1]))


@pytest.mark.parametrize('styles', [
    '',
    style('Signature', content='<w:basedOn w:val="Missing"/>'),
    style('Signature', content='<w:basedOn w:val="Base"/>') + style('Base', content='<w:basedOn w:val="Signature"/>'),
    style('Signature') + style('Signature'),
    style('Signature', 'character'),
    style('Signature', content='<w:link w:val="Missing"/>'),
    style('Signature', content='<w:link w:val="Signature"/>'),
    style('Signature', content='<w:pPr><w:futureProperty/></w:pPr>'),
    style('Signature', content='<w:basedOn w:val="Base"/><w:basedOn w:val="Other"/>') + style('Base') + style('Other'),
])
def test_unresolved_or_ambiguous_style_graph_cannot_authorize_removal(styles):
    raw = styled_template(styles, run_style=None)
    assert inspect_signature_candidates(raw)['blocks'][1]['eligible'] is False
    with pytest.raises(ValueError):
        bind_semantic_signature_slot(raw, selection(raw, [1]))


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def actual_styled_template():
    from docx import Document
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    from smart_reporting.reporting.tests.test_template_semantic_review import template_bytes

    document = Document(BytesIO(template_bytes()))
    paragraph_style = document.styles.add_style('SignatureLayout', WD_STYLE_TYPE.PARAGRAPH)
    paragraph_style.base_style = document.styles['Normal']
    paragraph_style.paragraph_format.space_after = Pt(6)
    character_style = document.styles.add_style('SignatureLetters', WD_STYLE_TYPE.CHARACTER)
    character_style.font.size = Pt(12)
    for owner, other in ((paragraph_style, character_style), (character_style, paragraph_style)):
        linked = OxmlElement('w:link')
        linked.set(qn('w:val'), other.style_id)
        owner.element.append(linked)
    for paragraph in document.paragraphs[2:4]:
        paragraph.style = paragraph_style
        for run in paragraph.runs:
            run.style = character_style
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def assert_actual_styled_output(raw, signer):
    from docx import Document

    document = Document(BytesIO(raw))
    paragraphs = document._element.body.xpath('.//w:p')
    signed = [paragraph for paragraph in paragraphs if ''.join(paragraph.xpath('.//w:t/text()')) == signer]
    assert len(signed) == 1
    assert signed[0].find('w:pPr/w:pStyle', NS).get(f'{{{W}}}val') == 'SignatureLayout'
    assert signed[0].find('w:r/w:rPr/w:rStyle', NS).get(f'{{{W}}}val') == 'SignatureLetters'
    assert document.styles['SignatureLetters'].font.size.pt == 12
    text = '\n'.join(document._element.body.xpath('.//w:t/text()'))
    assert text.count('清川分析室') == text.count('2001-02-03') == 1
    return text


@pytest.mark.anyio
async def test_workflow_renders_styled_semantic_signature_in_actual_word_and_pdf(tmp_path):
    from pypdf import PdfReader

    from smart_reporting.reporting.tests.test_template_semantic_delivery import runtime_case
    from smart_reporting.reporting.workflow.runtime.template_delivery import (
        render_template_delivery,
    )

    original = actual_styled_template()
    (tmp_path / 'original.docx').write_bytes(original)
    runtime, context, _ = runtime_case(original)
    for format, label, extension in [('docx', 'word', 'docx'), ('pdf', 'pdf', 'pdf')]:
        result = await render_template_delivery(runtime, context, runtime.result, SimpleNamespace(title='冻结标题'), format)
        content = runtime.files[result[label + 'Path']]
        (tmp_path / ('workflow.' + extension)).write_bytes(content)
        assert result['validation']['readback']['signature']['placement'] == 'semantic_template_slot'
        independent = result['validation']['readback']['semanticSignature']['preparationReadback']
        assert independent['status'] == 'passed' and independent['coverage'] == 'complete'
        if format == 'docx':
            assert '2026年9月16日' in assert_actual_styled_output(content, '冻结编制人')
        else:
            text = ''.join(''.join(page.extract_text().split()) for page in PdfReader(BytesIO(content)).pages)
            assert text.count('清川分析室') == text.count('2001-02-03') == 1
            assert text.count('冻结编制人') == 1 and '2026年9月16日' in text
    assert runtime.files['inputs/template.docx'] == original
    assert len(runtime.template_signature_reviewer.executor.requests) == 2


@pytest.mark.anyio
async def test_editor_reuses_styled_frozen_review_for_actual_word_and_pdf(tmp_path):
    import json
    from hashlib import sha256

    from pypdf import PdfReader

    from smart_reporting.report_editor.template_render import render_editor_template
    from smart_reporting.reporting.contract import ReportFileInput
    from smart_reporting.reporting.tests.test_editor_semantic_template import review
    from smart_reporting.reporting.tests.test_editor_template_render import render_case

    case = await render_case(tmp_path)
    original = actual_styled_template()
    identity = ReportFileInput(filename='样式模板.docx', path='inputs/styled-template.docx',
        size=len(original), sha256=sha256(original).hexdigest())
    await case.editor.workspace.awrite_bytes(case.context.scope['threadId'], identity.path, original)
    case.source.identity = identity
    case.source.content = original
    case.source.semantic_review = await review(original)
    assert case.source.semantic_review['status'] == 'resolved'
    case.source.binding['identity'] = identity.model_dump(mode='json', by_alias=True)
    result = await render_editor_template(case.editor, template_source=case.source,
        context=case.context, source_context=case.context, document=case.document,
        snapshot_path=case.snapshot, output_path='reports/revision-2/report.pdf',
        formats=('word', 'pdf'), render_manifest=None, run_context=case.run)
    (tmp_path / 'editor-receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    for format, extension in [('word', 'docx'), ('pdf', 'pdf')]:
        content, _ = await case.editor.workspace.afile_bytes(case.context.scope['threadId'], result[format + 'Path'])
        (tmp_path / ('editor.' + extension)).write_bytes(content)
        detail = result['validation']['readback'][format]['templateReadback']
        assert detail['semanticPreparation']['preparationReadback']['status'] == 'passed'
        assert detail['semanticPreparation']['preparationReadback']['coverage'] == 'complete'
        if format == 'word':
            assert detail['outsideDeclaredTargets']['status'] == 'passed'
            assert_actual_styled_output(content, '文字编制')
        else:
            assert detail['outsideDeclaredTargets']['status'] == 'unverified'
            assert detail['signature']['status'] == 'unverified'
            text = ''.join(''.join(page.extract_text().split()) for page in PdfReader(BytesIO(content)).pages)
            assert text.count('清川分析室') == text.count('2001-02-03') == 1
            assert text.count('版式编制') == 1 and '2026年9月16日' in text
    assert (await case.editor.workspace.afile_bytes(case.context.scope['threadId'], identity.path))[0] == original


def test_management_preflight_consumes_styled_review_in_actual_word_and_pdf(tmp_path, monkeypatch):
    import base64
    import json
    from copy import deepcopy

    from pypdf import PdfReader

    from smart_reporting.reporting.template_semantic_review import _record
    from smart_reporting.reporting.tests.test_template_semantic_review import opinion
    from smart_reporting.tests import test_preference_template_semantics as fixtures
    from smart_reporting.tests.test_preference_preflight import _run

    def review(raw):
        judged = opinion(raw)
        return _record(raw, 'resolved', (judged, deepcopy(judged)))

    monkeypatch.setattr(fixtures, '_template', actual_styled_template)
    monkeypatch.setattr(fixtures, '_review', review)
    draft, materials, original = fixtures._materials(tmp_path)
    fixtures._no_preview(monkeypatch)
    result = _run(draft, materials, formats=('word', 'pdf'))
    (tmp_path / 'management-readback.json').write_text(json.dumps({format: result['formats'][format]['templateReadback']
        for format in ('word', 'pdf')}, ensure_ascii=False, indent=2))
    for format, extension in [('word', 'docx'), ('pdf', 'pdf')]:
        content = base64.b64decode(result['formats'][format]['artifact']['base64'])
        (tmp_path / ('management.' + extension)).write_bytes(content)
        detail = result['formats'][format]['templateReadback']
        assert detail['semanticPreparation']['preparationReadback']['status'] == 'passed'
        assert detail['semanticPreparation']['preparationReadback']['coverage'] == 'complete'
        if format == 'word':
            assert detail['signature']['declaration'] == 'semantic_signature_sdt'
            assert detail['outsideDeclaredTargets']['status'] == 'passed'
            assert_actual_styled_output(content, '草稿验收编制')
        else:
            assert detail['signature']['status'] == 'unverified'
            assert detail['outsideDeclaredTargets']['status'] == 'unverified'
            text = ''.join(''.join(page.extract_text().split()) for page in PdfReader(BytesIO(content)).pages)
            assert text.count('清川分析室') == text.count('2001-02-03') == 1
            assert text.count('草稿验收编制') == 1
    assert (tmp_path / 'template.docx').read_bytes() == original
