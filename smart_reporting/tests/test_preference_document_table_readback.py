"""表题回读核全部原生身份和相邻表格，PDF文字只作抽样。"""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from smart_reporting.management import preference_document_table_readback as module


def _name(table_id):
    return 'tblcap_' + sha256(table_id.encode()).hexdigest()[:24]


def _document(numbered=True):
    doc = Document()
    expected = []
    for index, table_id in enumerate(('first-table', 'last-table'), 1):
        text = (f'表 {index}：' if numbered else '') + '同名表题 1234.5600'
        expected.append({'tableId': table_id, 'text': text})
        paragraph = doc.add_paragraph(text, style='Caption')
        start, end = OxmlElement('w:bookmarkStart'), OxmlElement('w:bookmarkEnd')
        start.set(qn('w:id'), str(index))
        start.set(qn('w:name'), _name(table_id))
        end.set(qn('w:id'), str(index))
        paragraph._p.insert(1, start)
        paragraph._p.append(end)
        table = doc.add_table(rows=2, cols=1)
        table.cell(0, 0).text = '指标'
        table.cell(1, 0).text = '1234.5600'
    return doc, expected


def _checks(doc, expected):
    checks = []

    def check(path, actual, wanted, **kwargs):
        checks.append({'path': path, 'actual': actual, 'expected': wanted,
            'passed': actual == wanted, **kwargs})

    status = module.check_word_table_captions(doc, expected, check)
    return checks, status


def _reader_fonts(doc):
    # 本专项夹具补齐既有字号reader的前置，不用它验证其他字体配置。
    for name in ('Normal', 'Heading 1', 'Heading 2', 'Heading 3', 'Caption'):
        doc.styles[name].font.size = Pt(11)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = Pt(11)


@pytest.mark.parametrize('numbered', [True, False])
def test_all_native_caption_identities_require_order_style_and_adjacent_tables(numbered):
    doc, expected = _document(numbered)
    # 相同普通正文不能被改Caption样式，也不能被算进受控表题数量。
    ordinary = doc.add_paragraph(expected[-1]['text'])
    checks, status = _checks(doc, expected)
    assert checks and all(item['passed'] and item['coverage'] == 'complete' for item in checks)
    assert status['status'] == 'passed' and status['expectedCount'] == 2
    assert ordinary.style.name == 'Normal'


@pytest.mark.parametrize('fault', [
    'last_text', 'last_missing_marker', 'last_missing_table', 'duplicate_marker',
    'extra_marker', 'wrong_order', 'wrong_style', 'dynamic_field', 'hidden_text', 'hidden_base_style',
])
def test_late_native_caption_damage_cannot_be_covered_by_first_success(fault):
    doc, expected = _document()
    last = doc.paragraphs[-1]
    if fault == 'last_text':
        last.runs[0].text += '伪造后缀'
    elif fault == 'last_missing_marker':
        last._p.remove(last._p.find(qn('w:bookmarkStart')))
    elif fault == 'last_missing_table':
        doc.tables[-1]._tbl.getparent().remove(doc.tables[-1]._tbl)
    elif fault == 'duplicate_marker':
        last._p.insert(1, deepcopy(last._p.find(qn('w:bookmarkStart'))))
    elif fault == 'extra_marker':
        extra = doc.add_paragraph('额外表题', style='Caption')
        start = OxmlElement('w:bookmarkStart')
        start.set(qn('w:id'), '99')
        start.set(qn('w:name'), _name('foreign'))
        extra._p.append(start)
        doc.add_table(rows=1, cols=1)
    elif fault == 'wrong_order':
        first = doc.paragraphs[0]._p.find(qn('w:bookmarkStart'))
        second = last._p.find(qn('w:bookmarkStart'))
        first.set(qn('w:name'), _name('last-table'))
        second.set(qn('w:name'), _name('first-table'))
    elif fault == 'wrong_style':
        last.style = 'Normal'
    elif fault == 'dynamic_field':
        field = OxmlElement('w:instrText')
        field.text = ' DOCPROPERTY cachedCaption '
        last.runs[0]._r.append(field)
    elif fault == 'hidden_base_style':
        doc.styles['Normal'].font.hidden = True
    else:
        last.runs[0].font.hidden = True
    checks, status = _checks(doc, expected)
    assert checks and any(not item['passed'] for item in checks)
    assert status['status'] == 'failed'


def test_native_caption_without_expected_registered_source_is_not_vacuously_complete():
    doc, _ = _document()
    checks, status = _checks(doc, [])
    assert checks == []
    assert status['status'] == 'unverified'


@pytest.mark.parametrize('fault', [
    'character_style', 'character_base', 'defaults', 'spec_vanish',
    'missing_character_style', 'cyclic_character_style', 'duplicate_character_style',
])
def test_hidden_or_unresolved_last_caption_styles_cannot_pass_native_readback(fault):
    from docx.enum.style import WD_STYLE_TYPE

    doc, expected = _document()
    last = doc.paragraphs[-1]
    if fault == 'defaults':
        defaults = doc.styles.element.find(qn('w:docDefaults')).find(qn('w:rPrDefault')).find(qn('w:rPr'))
        defaults.append(OxmlElement('w:vanish'))
    elif fault == 'spec_vanish':
        last.runs[0]._r.get_or_add_rPr().append(OxmlElement('w:specVanish'))
    else:
        style = doc.styles.add_style('Caption character test', WD_STYLE_TYPE.CHARACTER)
        last.runs[0].style = style
        if fault == 'character_style':
            style.font.hidden = True
        elif fault == 'character_base':
            base = doc.styles.add_style('Caption hidden base', WD_STYLE_TYPE.CHARACTER)
            base.font.hidden = True
            style.base_style = base
        elif fault == 'missing_character_style':
            style.element.getparent().remove(style.element)
        elif fault == 'cyclic_character_style':
            style.base_style = style
        else:
            style.element.getparent().append(deepcopy(style.element))
    # 保存后重新打开，检查实际包中的样式关系，而非内存对象缓存。
    data = BytesIO()
    doc.save(data)
    checks, status = _checks(Document(BytesIO(data.getvalue())), expected)
    assert status['status'] == 'failed'
    assert checks and not checks[0]['passed']


@pytest.mark.parametrize('fault', [
    'missing_id', 'empty_id', 'foreign_end', 'shared_id', 'paragraph_deletion',
    'paragraph_revision', 'run_revision', 'protected_document', 'permission_range',
    'duplicate_run_properties', 'nameless_default_style',
])
def test_ambiguous_bookmarks_revisions_and_protection_cannot_certify_captions(fault):
    from docx.enum.style import WD_STYLE_TYPE

    doc, expected = _document()
    last = doc.paragraphs[-1]
    start, end = last._p.find(qn('w:bookmarkStart')), last._p.find(qn('w:bookmarkEnd'))
    if fault in ('missing_id', 'empty_id'):
        for item in (start, end):
            item.attrib.pop(qn('w:id'))
            if fault == 'empty_id':
                item.set(qn('w:id'), '')
    elif fault == 'foreign_end':
        doc.add_paragraph('其他正文')._p.append(deepcopy(end))
    elif fault == 'shared_id':
        start.set(qn('w:id'), '1')
        end.set(qn('w:id'), '1')
    elif fault == 'paragraph_deletion':
        properties = OxmlElement('w:rPr')
        properties.append(OxmlElement('w:del'))
        last._p.get_or_add_pPr().append(properties)
    elif fault == 'paragraph_revision':
        last._p.get_or_add_pPr().append(OxmlElement('w:pPrChange'))
    elif fault == 'run_revision':
        last.runs[0]._r.get_or_add_rPr().append(OxmlElement('w:rPrChange'))
    elif fault == 'protected_document':
        protection = OxmlElement('w:documentProtection')
        protection.set(qn('w:edit'), 'readOnly')
        protection.set(qn('w:enforcement'), '1')
        doc.settings.element.append(protection)
    elif fault == 'permission_range':
        permission = OxmlElement('w:permStart')
        permission.set(qn('w:id'), '17')
        last._p.insert(1, permission)
    else:
        style = doc.styles.add_style('Hidden caption character', WD_STYLE_TYPE.CHARACTER)
        style.font.hidden = True
        if fault == 'duplicate_run_properties':
            last.runs[0].style = style
            last.runs[0]._r.insert(0, OxmlElement('w:rPr'))
        else:
            default = doc.styles['Default Paragraph Font'].element
            default.attrib.pop(qn('w:default'), None)
            style.element.set(qn('w:default'), '1')
            style.element.attrib.pop(qn('w:styleId'))
    data = BytesIO()
    doc.save(data)
    checks, status = _checks(Document(BytesIO(data.getvalue())), expected)
    assert status['status'] == 'failed'
    assert checks and not checks[0]['passed']


@pytest.mark.parametrize('fault', ['valid', 'last_missing', 'duplicate_first', 'extra_suffix'])
def test_pdf_caption_text_never_becomes_complete_evidence(fault):
    _, expected = _document()
    text = '\n'.join(item['text'] for item in expected)
    if fault == 'last_missing':
        text = expected[0]['text']
    elif fault == 'duplicate_first':
        text = '\n'.join([expected[0]['text']] * 2)
    elif fault == 'extra_suffix':
        text += '伪造后缀'
    checks = []

    def check(path, actual, wanted, **kwargs):
        checks.append({'passed': actual == wanted, **kwargs})

    result = module.check_pdf_table_captions(text, expected, check)
    assert checks and all(item['coverage'] == 'sample' for item in checks)
    assert result['coverage'] == 'sample'
    assert result['status'] != 'passed'
    assert all(item['passed'] for item in checks) is (fault == 'valid')


def _frozen():
    from smart_reporting.reporting.tests.test_document_table_caption_numbering import (
        caption_input,
        table,
    )

    captions = {'first-table': '同名表题 1234.5600', 'last-table': '同名表题 1234.5600'}
    markdown = '\n\n'.join(title + '\n\n' + table(key) for key, title in captions.items())
    return {'markdown': markdown, 'markdownPath': 'report.md', 'tableCaptionInput': caption_input(markdown, captions)}


@pytest.mark.parametrize('numbered', [True, False])
def test_complete_word_caption_evidence_requires_verified_source_and_positive_object_counts(numbered):
    doc, _ = _document(numbered)
    checks = []
    result = module.read_table_captions(doc, 'word', numbered, _frozen(),
        lambda *args, **kwargs: checks.append(kwargs))
    assert result['sourceStatus'] == 'verified'
    assert checks[0]['evidence_kind'] == 'word_native_table_captions_v1'
    assert checks[0]['evidence_objects'] == {'sourceStatus': 'verified',
        'expectedCaptions': 2, 'nativeCaptions': 2, 'checkedCaptions': 2}


@pytest.mark.parametrize('numbered', [True, False])
def test_expected_table_captions_independently_use_raw_source_identity_and_all_markers(numbered):
    frozen = _frozen()
    before = deepcopy(frozen)
    result = module.expected_table_captions(frozen, numbered)
    assert result['status'] == 'verified'
    assert result['expected'] == _document(numbered)[1]
    assert frozen == before


@pytest.mark.parametrize('fault', ['absent', 'changed_source', 'changed_index', 'normalized_mismatch', 'modified_title', 'duplicate_id'])
def test_unknown_or_changed_table_caption_sources_never_produce_complete_expectations(fault):
    from smart_reporting.reporting.tests.test_document_table_caption_numbering import caption_input

    frozen = _frozen()
    if fault == 'absent':
        frozen.pop('tableCaptionInput')
    elif fault == 'changed_source':
        frozen['tableCaptionInput']['markdownText'] += 'changed'
    elif fault == 'changed_index':
        frozen['tableCaptionInput']['traceIndexText'] += ' '
    elif fault == 'normalized_mismatch':
        frozen['markdown'] += 'changed'
    elif fault == 'duplicate_id':
        tables = frozen['tableCaptionInput']['manifest']['tables']
        tables.append(deepcopy(tables[0]))
    else:
        captions = {'first-table': '同名表题 1234.5600', 'last-table': '同名表题 1234.5600'}
        frozen['markdown'] = frozen['markdown'].replace('同名表题', '改过的表题', 1)
        # 新清单核的是实际当前字节；登记origin题仍旧，不能凭身份相符猜新题。
        frozen['tableCaptionInput'] = caption_input(frozen['markdown'], captions)
    result = module.expected_table_captions(frozen, True)
    assert result['status'] == 'unverified'
    assert result['issues']


def test_crlf_identity_uses_original_bytes_while_comparing_normalized_frozen_markdown():
    from smart_reporting.reporting.tests.test_document_table_caption_numbering import caption_input

    frozen = _frozen()
    raw = frozen['markdown'].replace('\n', '\r\n')
    frozen['tableCaptionInput'] = caption_input(raw, {'first-table': '同名表题 1234.5600', 'last-table': '同名表题 1234.5600'})
    result = module.expected_table_captions(frozen, True)
    assert result['status'] == 'verified'
    assert result['expected'] == _document()[1]


@pytest.mark.parametrize('available', [True, False])
def test_actual_word_preflight_connects_table_metadata_without_guessing_old_source(available):
    from smart_reporting.management.preference_preflight_readback import readback
    from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences

    frozen = _frozen()
    frozen['state'] = {'_documentContext': {'generatedDate': '2026-11-13'}}
    if not available:
        frozen.pop('tableCaptionInput')
    doc, _ = _document()
    _reader_fonts(doc)
    stream = BytesIO()
    doc.save(stream)
    preferences = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': 'reader'}}), 'word')
    result = readback(stream.getvalue(), 'word', preferences, frozen)
    metadata = result['tableCaptionReadback']
    checks = [item for item in result['checks'] if item['path'] == 'word.tables.captionNumbering']
    if available:
        assert metadata['status'] == 'passed'
        assert len(checks) == 1 and checks[0]['passed'] and checks[0]['coverage'] == 'complete'
    else:
        assert metadata['status'] == 'unverified' and metadata['issues']
        assert not checks


def test_table_caption_immediately_after_picture_is_not_misread_as_figure_caption():
    import base64

    from smart_reporting.management.configuration_preview import MD_SAMPLE_PNG
    from smart_reporting.management.preference_preflight_readback import readback
    from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences

    frozen = _frozen()
    frozen['state'] = {'_documentContext': {'generatedDate': '2026-11-13'}}
    doc, _ = _document()
    _reader_fonts(doc)
    image = doc.add_paragraph()
    image.add_run().add_picture(BytesIO(base64.b64decode(MD_SAMPLE_PNG)))
    doc.paragraphs[0]._p.addprevious(image._p)
    stream = BytesIO()
    doc.save(stream)
    result = readback(stream.getvalue(), 'word', resolve_format_preferences(
        FormatPreferences.model_validate({'common': {'signer': 'reader'}}), 'word'), frozen)
    assert not [item for item in result['checks'] if item['path'] == 'word.charts.keepWithCaption']
    assert result['tableCaptionReadback']['status'] == 'passed'


def test_partial_registered_source_only_produces_sample_even_for_matching_known_objects():
    from smart_reporting.reporting.tests.test_document_table_caption_numbering import caption_input

    frozen = _frozen()
    frozen['markdown'] = frozen['markdown'].replace('同名表题', '改过的表题', 1)
    frozen['tableCaptionInput'] = caption_input(frozen['markdown'], {
        'first-table': '同名表题 1234.5600', 'last-table': '同名表题 1234.5600'})
    doc, _ = _document()
    doc.paragraphs[0]._p.getparent().remove(doc.paragraphs[0]._p)
    doc.tables[0]._tbl.getparent().remove(doc.tables[0]._tbl)
    doc.paragraphs[0].runs[0].text = '表 1：同名表题 1234.5600'
    checks = []

    def check(path, actual, expected, **kwargs):
        checks.append({'passed': actual == expected, **kwargs})

    result = module.read_table_captions(doc, 'word', True, frozen, check)
    assert result['status'] == 'unverified' and result['issues']
    assert checks and all(item['passed'] and item['coverage'] == 'sample' for item in checks)
    assert all('evidence_kind' not in item and 'evidence_objects' not in item for item in checks)


def test_code_only_table_markers_are_not_treated_as_exercised_caption_objects():
    frozen = {'markdown': '```text\n任意表题\n\n[[table:x]]\n| a |\n| --- |\n| b |\n\n[[/table:x]]\n```'}
    result = module.expected_table_captions(frozen, True)
    assert result == {'status': 'not_exercised', 'expected': [], 'issues': []}


@pytest.mark.parametrize('suffix', ['', '伪造后缀'])
def test_pdf_wrapped_caption_is_only_a_sample_and_suffix_is_detected(suffix):
    expected = [{'tableId': 'first', 'text': '表 1：非常长的受控表题原文 1234.5600'}]
    text = '表 1：非常长的\n受控表题原文 1234.5600' + suffix
    checks = []

    def check(path, actual, wanted, **kwargs):
        checks.append({'passed': actual == wanted, **kwargs})

    result = module.check_pdf_table_captions(text, expected, check)
    assert all(item['coverage'] == 'sample' for item in checks)
    assert all(item['passed'] for item in checks) is (not suffix)
    assert result['status'] != 'passed'


def test_identical_pdf_prose_and_unnumbered_titles_are_unverified_not_falsely_failed():
    expected = [{'tableId': name, 'text': '同名表题 1234.5600'} for name in ('first', 'last')]
    checks = []

    def check(*args, **kwargs):
        checks.append((args, kwargs))

    result = module.check_pdf_table_captions('\n'.join([item['text'] for item in expected] + [expected[0]['text']]), expected, check)
    assert result['status'] == 'unverified'
    assert result['issues'][0]['code'] == 'management_preference_pdf_table_caption_ambiguous'
    assert not checks  # 文字无法判定多出来的是正文还是重复表题，不能冒充确定的字段失败或通过。


def test_untitled_registered_table_is_not_assigned_a_guessed_number():
    from smart_reporting.reporting.tests.test_document_table_caption_numbering import (
        caption_input,
        table,
    )

    markdown = table('untitled')
    frozen = {'markdown': markdown, 'tableCaptionInput': caption_input(markdown, {'untitled': ''})}
    result = module.expected_table_captions(frozen, True)
    assert result['expected'] == []
    assert result['status'] != 'verified'
