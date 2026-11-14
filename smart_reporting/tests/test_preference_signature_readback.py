"""末尾落款的原生结构证据；正文引用不得冒充或重复计算为落款。"""
import hashlib
import json
import shutil
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace

import pytest
from docx import Document
from pptx import Presentation

from smart_reporting.management.preference_preflight import _generate, _verify_materials
from smart_reporting.management.preference_preflight_readback import readback
from smart_reporting.preferences.markdown_adapter import END, START, append_signature
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.pptx import build_editable_pptx

from .test_preference_preflight import _inputs

SIGNER = 'ReadbackSigner'
DATE = '2026-11-13'
DESCRIPTION = 'First complete explanation\nSecond complete explanation'
CONTENT_PATHS = ('common.signer', 'common.dateFormat', 'signature.description')


@pytest.fixture(scope='module')
def signature_case(tmp_path_factory):
    cases = {}

    def build(format):
        if format in cases:
            return cases[format]
        root = tmp_path_factory.mktemp('signature-readback-' + format)
        source = root / 'source'
        source.mkdir()
        _, materials = _inputs(source)
        # 同姓名、同日期和全部说明的真实正文引用，不能满足末尾落款或算作重复落款。
        quote = '\n\n'.join([SIGNER, DATE.replace('-', '\\-'), *DESCRIPTION.splitlines()])
        markdown = (source / 'report.md').read_text() + '\n\n正文引用（保留）：\n\n' + quote + '\n'
        (source / 'report.md').write_text(markdown)
        for identity in materials.state['sources']:
            if identity['path'] == 'report.md':
                raw = markdown.encode()
                identity.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        preferences = FormatPreferences.model_validate({'common': {'signer': SIGNER, 'dateFormat': 'iso'},
            'md': {'toc': False, 'signature': {'description': DESCRIPTION}},
            'word': {'cover': True, 'toc': False, 'sources': True, 'signature': {'description': DESCRIPTION}},
            'pdf': {'cover': False, 'toc': False, 'bookmarks': False, 'signature': {'description': DESCRIPTION}},
            'pptx': {'signature': {'description': DESCRIPTION}, 'footer': {'right': '{slide}/{slides}'}}})
        _, frozen, _ = _verify_materials(materials, formats=(format,))
        frozen['slides'] = ({'title': 'Business citation',
            'bullets': [SIGNER, DATE, *DESCRIPTION.splitlines()]},)
        resolved = resolve_format_preferences(preferences, format)
        if format == 'md':
            content = append_signature(markdown, resolved, DATE,
                citation_presentations=frozen['state']['_citationPresentations'],
                heading_numbers=frozen['state']['_documentContext']['headingNumbers']).encode()
        else:
            for identity in materials.state['sources']:
                target = root / 'inputs' / identity['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / identity['path'], target)
            _generate(root, preferences, frozen)
            content = (root / ('inputs/revision/report.docx' if format == 'word' else 'report.pptx')).read_bytes()
        cases[format] = SimpleNamespace(content=content, prefs=resolved, frozen=frozen, root=root)
        return cases[format]

    return build


def content_checks(case, format, content):
    result = readback(content, format, case.prefs, case.frozen)
    return [item for item in result['checks'] if item['path'] in [format + '.' + path for path in CONTENT_PATHS]]


@pytest.mark.parametrize('format', ['md', 'word', 'pptx'])
def test_real_terminal_signature_is_complete_despite_identical_body_citations(signature_case, format):
    case = signature_case(format)
    result = readback(case.content, format, case.prefs, case.frozen)
    assert result['status'] == 'passed', result
    checks = content_checks(case, format, case.content)
    assert len(checks) == 3
    assert all(item['passed'] and item['coverage'] == 'complete' for item in checks)
    record = {'format': format, 'fixtureOnly': True, 'realGenerator': True,
        'size': len(case.content), 'sha256': hashlib.sha256(case.content).hexdigest(),
        'readbackStatus': result['status'], 'signatureChecks': checks}
    suffix = 'docx' if format == 'word' else format
    (case.root / ('verified.' + suffix)).write_bytes(case.content)
    (case.root / 'readback-evidence.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
    print(json.dumps(record, ensure_ascii=False))


@pytest.mark.parametrize('fault', ['missing', 'unmarked', 'inline', 'wrong_order', 'missing_description', 'duplicate', 'after_body', 'code_only'])
def test_markdown_signature_requires_one_independent_marked_tail(signature_case, fault):
    case = signature_case('md')
    text = case.content.decode()
    body, block = text.split(START)
    signed = START + block
    if fault == 'missing':
        text = body
    elif fault == 'unmarked':
        text = body + block.replace(END, '')
    elif fault == 'inline':
        text = body + START + '\n\n' + ' '.join([SIGNER, DATE, *DESCRIPTION.splitlines()]) + '\n\n' + END
    elif fault == 'wrong_order':
        escaped_date = DATE.replace('-', '\\-')
        text = body + signed.replace(SIGNER + '\n\n' + escaped_date, escaped_date + '\n\n' + SIGNER)
    elif fault == 'missing_description':
        text = body + signed.replace('Second complete explanation', '')
    elif fault == 'duplicate':
        text = body + signed + '\n' + signed
    elif fault == 'after_body':
        text += '\n后续业务正文不能出现在落款之后。\n'
    else:
        text = body + '\n```text\n' + signed + '\n```\n'
    checks = content_checks(case, 'md', text.encode())
    assert checks and not all(item['passed'] for item in checks)


def test_markdown_literal_marker_in_code_does_not_duplicate_real_signature(signature_case):
    case = signature_case('md')
    text = case.content.decode()
    body, block = text.split(START)
    quoted = '\n```text\n' + START + '\n' + END + '\n```\n\n'
    checks = content_checks(case, 'md', (body + quoted + START + block).encode())
    assert all(item['passed'] and item['coverage'] == 'complete' for item in checks)


@pytest.mark.parametrize('fault', ['missing', 'unmarked', 'wrong_order', 'missing_description', 'duplicate', 'after_body', 'after_table', 'hidden'])
def test_word_signature_requires_unique_native_tail_before_sources(signature_case, fault):
    case = signature_case('word')
    document = Document(BytesIO(case.content))
    signature = [paragraph for paragraph in document.paragraphs if paragraph.style.name == 'Report Signature']
    assert [paragraph.text for paragraph in signature] == [SIGNER, DATE, *DESCRIPTION.splitlines()]
    if fault == 'missing':
        for paragraph in signature:
            paragraph._p.getparent().remove(paragraph._p)
    elif fault == 'unmarked':
        for paragraph in signature:
            paragraph.style = document.styles['Normal']
    elif fault == 'wrong_order':
        signature[0].text, signature[1].text = DATE, SIGNER
    elif fault == 'missing_description':
        signature[-1]._p.getparent().remove(signature[-1]._p)
    elif fault == 'duplicate':
        for paragraph in signature:
            signature[0]._p.addprevious(deepcopy(paragraph._p))
    elif fault == 'after_body':
        paragraph = document.add_paragraph('后续业务正文')
        signature[-1]._p.addnext(paragraph._p)
    elif fault == 'hidden':
        document.styles['Report Signature'].font.hidden = True
    else:
        table = document.add_table(rows=1, cols=1)
        table.cell(0, 0).text = '后续业务表格'
        signature[-1]._p.addnext(table._tbl)
    output = BytesIO()
    document.save(output)
    checks = content_checks(case, 'word', output.getvalue())
    assert checks and not all(item['passed'] for item in checks)


@pytest.fixture(scope='module')
def word_toc_case(tmp_path_factory):
    root = tmp_path_factory.mktemp('signature-word-toc')
    source = root / 'source'
    source.mkdir()
    document, materials = _inputs(source)
    document['document']['common'].update(signer=SIGNER, dateFormat='iso')
    document['document']['word'].update(toc=True, cover=False, sources=False,
        signature={'description': DESCRIPTION})
    preferences = FormatPreferences.model_validate(document['document'])
    _, frozen, _ = _verify_materials(materials, formats=('word',))
    for identity in materials.state['sources']:
        target = root / 'inputs' / identity['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / identity['path'], target)
    _generate(root, preferences, frozen)
    content = (root / 'inputs/revision/report.docx').read_bytes()
    return SimpleNamespace(content=content, prefs=resolve_format_preferences(preferences, 'word'),
        frozen=frozen, root=root)


@pytest.mark.parametrize('boundary', ['generated_tail', 'between_signature'])
def test_word_signature_accepts_bookmark_boundaries_with_real_toc(word_toc_case, boundary):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    case = word_toc_case
    document = Document(BytesIO(case.content))
    signature = [paragraph for paragraph in document.paragraphs if paragraph.style.name == 'Report Signature']
    tail = list(document.element.body)[list(document.element.body).index(signature[-1]._p) + 1:]
    assert any(element.tag == qn('w:bookmarkEnd') for element in tail)
    if boundary == 'between_signature':
        start, end = OxmlElement('w:bookmarkStart'), OxmlElement('w:bookmarkEnd')
        start.set(qn('w:id'), '9001')
        start.set(qn('w:name'), 'signature_boundary')
        end.set(qn('w:id'), '9001')
        signature[1]._p.addprevious(start)
        signature[1]._p.addprevious(end)
    output = BytesIO()
    document.save(output)
    checks = content_checks(case, 'word', output.getvalue())
    assert all(item['passed'] and item['coverage'] == 'complete' for item in checks), checks
    if boundary == 'generated_tail':
        (case.root / 'verified-toc.docx').write_bytes(case.content)
        print(json.dumps({'artifact': str(case.root / 'verified-toc.docx'), 'size': len(case.content),
            'sha256': hashlib.sha256(case.content).hexdigest(), 'signatureChecks': checks}, ensure_ascii=False))


@pytest.mark.parametrize('fault', ['body', 'table', 'drawing'])
def test_word_signature_toc_bookmarks_do_not_allow_following_content(word_toc_case, fault):
    case = word_toc_case
    document = Document(BytesIO(case.content))
    signature = [paragraph for paragraph in document.paragraphs if paragraph.style.name == 'Report Signature']
    if fault == 'table':
        table = document.add_table(rows=1, cols=1)
        table.cell(0, 0).text = '后续业务表格'
        element = table._tbl
    else:
        paragraph = document.add_paragraph('后续业务正文' if fault == 'body' else '')
        if fault == 'drawing':
            paragraph.add_run().add_picture(str(case.root / 'inputs/chart.png'))
        element = paragraph._p
    signature[-1]._p.addnext(element)
    output = BytesIO()
    document.save(output)
    checks = content_checks(case, 'word', output.getvalue())
    assert checks and not all(item['passed'] for item in checks)


@pytest.mark.parametrize('fault', ['missing', 'wrong_order', 'missing_description', 'duplicate', 'after_body', 'off_canvas', 'hidden'])
def test_pptx_signature_requires_final_editable_native_region(signature_case, fault):
    case = signature_case('pptx')
    deck = Presentation(BytesIO(case.content))
    signature_slide = deck.slides[-1]
    identity = next(shape for shape in signature_slide.shapes if shape.has_text_frame and shape.text.startswith(SIGNER))
    if fault == 'missing':
        slide_id = deck.slides._sldIdLst[-1]
        deck.part.drop_rel(slide_id.rId)
        deck.slides._sldIdLst.remove(slide_id)
    elif fault == 'wrong_order':
        identity.text_frame.paragraphs[0].text, identity.text_frame.paragraphs[1].text = DATE, SIGNER
    elif fault == 'missing_description':
        shape = next(shape for shape in signature_slide.shapes if shape.has_text_frame and shape.text == DESCRIPTION.splitlines()[-1])
        shape._element.getparent().remove(shape._element)
    elif fault == 'duplicate':
        slide = deck.slides.add_slide(signature_slide.slide_layout)
        for shape in signature_slide.shapes:
            slide.shapes._spTree.insert_element_before(deepcopy(shape._element), 'p:extLst')
    elif fault == 'after_body':
        slide = deck.slides.add_slide(signature_slide.slide_layout)
        from pptx.util import Inches

        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = 'Later business body'
    elif fault == 'hidden':
        identity._element.xpath('.//p:cNvPr')[0].set('hidden', '1')
    else:
        identity.left = -deck.slide_width
    output = BytesIO()
    deck.save(output)
    checks = content_checks(case, 'pptx', output.getvalue())
    assert checks and not all(item['passed'] for item in checks)


def test_pdf_text_occurrence_remains_sample_even_when_all_signature_words_exist(signature_case):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas

    case = signature_case('md')
    preferences = FormatPreferences.model_validate({'common': {'signer': SIGNER, 'dateFormat': 'iso'},
        'pdf': {'bookmarks': False, 'signature': {'description': DESCRIPTION}}})
    resolved = resolve_format_preferences(preferences, 'pdf')
    output = BytesIO()
    canvas = Canvas(output, pagesize=A4)
    canvas.drawString(30, 700, 'BODY CITATION ' + ' '.join([SIGNER, DATE, *DESCRIPTION.splitlines()]))
    canvas.save()
    frozen = {**case.frozen, 'markdown': '', 'state': {**case.frozen['state'],
        '_documentContext': {**case.frozen['state']['_documentContext'], 'headingNumbers': []}}}
    result = readback(output.getvalue(), 'pdf', resolved, frozen)
    checks = [item for item in result['checks'] if item['path'] in ['pdf.' + path for path in CONTENT_PATHS]]
    assert len(checks) == 3
    assert all(item['coverage'] == 'sample' for item in checks)
    from smart_reporting.management.preference_preflight import _capabilities

    capabilities = _capabilities('pdf', resolved, result, frozen)
    assert all(item['status'] == 'not_verified' for item in capabilities
        if item['path'] in ['pdf.' + path for path in CONTENT_PATHS])


@pytest.mark.parametrize('format', ['md', 'word', 'pptx'])
@pytest.mark.parametrize('leftover', [False, True])
def test_empty_description_requires_no_old_terminal_description(signature_case, format, leftover):
    case = deepcopy(signature_case(format))
    case.prefs['signature']['description'] = ''
    if format == 'md':
        content = case.content if leftover else append_signature(case.frozen['markdown'], case.prefs, DATE).encode()
    elif format == 'word':
        doc = Document(BytesIO(case.content))
        if not leftover:
            signature = [paragraph for paragraph in doc.paragraphs if paragraph.style.name == 'Report Signature']
            for paragraph in signature[2:]:
                paragraph._p.getparent().remove(paragraph._p)
        output = BytesIO()
        doc.save(output)
        content = output.getvalue()
    else:
        deck = Presentation(BytesIO(case.content))
        if not leftover:
            for shape in list(deck.slides[-1].shapes):
                if shape.has_text_frame and shape.text in DESCRIPTION.splitlines():
                    shape._element.getparent().remove(shape._element)
        output = BytesIO()
        deck.save(output)
        content = output.getvalue()
    checks = content_checks(case, format, content)
    assert all(item['passed'] for item in checks) is (not leftover)
    assert all(item['coverage'] == 'complete' for item in checks)


def test_markdown_literal_punctuation_and_blank_description_paragraph_are_complete(signature_case):
    case = deepcopy(signature_case('md'))
    case.prefs['common']['signer'] = 'Lab * [R&D]'
    case.prefs['signature']['description'] = 'First * literal\n\nLast [text](url)'
    content = append_signature(case.frozen['markdown'], case.prefs, DATE).encode()
    checks = content_checks(case, 'md', content)
    assert all(item['passed'] and item['coverage'] == 'complete' for item in checks)


def test_pptx_complete_description_spans_native_chunks_and_final_continuation_pages(signature_case, tmp_path):
    case = deepcopy(signature_case('pptx'))
    case.prefs['signature'].update(size=36, description='说明abcdef12345' * 40 + '\nEND complete')
    path = tmp_path / 'continued-signature.pptx'
    build_editable_pptx(output_path=path, title=case.frozen['state']['_documentContext']['title'],
        period=case.frozen['state']['_documentContext']['periodLabel'], theme='executive',
        slides=case.frozen['slides'], preferences=case.prefs, generated_date=DATE)
    deck = Presentation(path)
    assert len(deck.slides) > len(case.frozen['slides']) + 2
    checks = content_checks(case, 'pptx', path.read_bytes())
    assert all(item['passed'] and item['coverage'] == 'complete' for item in checks)
