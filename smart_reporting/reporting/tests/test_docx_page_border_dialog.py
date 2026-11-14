from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.tests.test_docx_page_borders import source_document


def test_dialog_props_use_native_writer_and_preserve_other_sections_and_parts():
    source = source_document(); model = inspect_docx(source); target = model['sections'][0]
    props = {'display': 'firstPage', 'offsetFrom': 'text', 'zOrder': 'back', 'widthPt': 2.25, 'spacePt': 7, 'color': '123456',
             'sides': {'top': {'val': 'double', 'widthPt': 2.25, 'spacePt': 7, 'color': '123456', 'shadow': True},
                       'right': {'val': 'single', 'widthPt': .5, 'spacePt': 4}}}
    op = {'kind': 'setSectionLayout', 'sectionId': target['sectionId'], 'expectedSectionSha256': target['expectedSectionSha256'],
          'values': {'pageBorder': True, 'pageBorderProps': props}}
    output = patch_docx(source, [op]); actual = Document(BytesIO(output))
    border = actual.sections[0]._sectPr.find(qn('w:pgBorders'))
    assert border.get(qn('w:display')) == 'firstPage' and border.get(qn('w:zOrder')) == 'back'
    assert border.find(qn('w:top')).get(qn('w:sz')) == '18'
    assert border.find(qn('w:top')).get(qn('w:shadow')) == '1'
    assert border.find(qn('w:right')).get(qn('w:color')) == 'auto'
    assert border.find(qn('w:left')) is None
    assert inspect_docx(output)['sections'][0]['settings']['pageBorderProps'] == props
    assert actual.sections[1]._sectPr.xml == Document(BytesIO(source)).sections[1]._sectPr.xml
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(output)) as after:
        for name in before.namelist():
            if name != 'word/document.xml': assert before.read(name) == after.read(name), name


def test_all_sections_art_native_width_shadow_and_display():
    source = source_document(); model = inspect_docx(source)
    props = {'display': 'notFirstPage', 'offsetFrom': 'page', 'spacePt': 24, 'widthPt': 19,
             'sides': {side: {'val': 'apples', 'art': True, 'widthPt': 19, 'spacePt': 24, 'frame': True} for side in ['top', 'bottom', 'left', 'right']}}
    ops = [{'kind': 'setSectionLayout', 'sectionId': target['sectionId'], 'expectedSectionSha256': target['expectedSectionSha256'],
            'values': {'pageBorder': True, 'pageBorderProps': props}} for target in model['sections']]
    output = patch_docx(source, ops)
    for section in Document(BytesIO(output)).sections:
        border = section._sectPr.find(qn('w:pgBorders'))
        assert border.get(qn('w:display')) == 'notFirstPage'
        assert all(side.get(qn('w:sz')) == '19' and side.get(qn('w:val')) == 'apples' and side.get(qn('w:frame')) == '1' for side in border)
    assert all(target['settings']['pageBorderProps'] == props for target in inspect_docx(output)['sections'])


def test_explicit_none_clears_custom_border_properties():
    source = source_document(); target = inspect_docx(source)['sections'][0]
    output = patch_docx(source, [{'kind': 'setSectionLayout', 'sectionId': target['sectionId'],
        'expectedSectionSha256': target['expectedSectionSha256'], 'values': {'pageBorder': False, 'pageBorderProps': None}}])
    actual = Document(BytesIO(output))
    assert actual.sections[0]._sectPr.find(qn('w:pgBorders')) is None
    settings = inspect_docx(output)['sections'][0]['settings']
    assert settings['pageBorder'] is False
    assert 'pageBorderProps' not in settings


@pytest.mark.parametrize('props', [
    {'display': 'oddPage', 'spacePt': 1, 'widthPt': 1, 'sides': {'top': {'val': 'single', 'widthPt': 1, 'spacePt': 1}}},
    {'display': 'all', 'offsetFrom': 'page', 'spacePt': 1, 'widthPt': 1, 'sides': {'top': {'val': 'single', 'widthPt': 1, 'spacePt': 1}}},
    {'offsetFrom': 'page', 'spacePt': 1, 'widthPt': 1, 'xml': '<w:pgBorders/>', 'sides': {'top': {'val': 'single', 'widthPt': 1, 'spacePt': 1}}},
    {'offsetFrom': 'page', 'spacePt': 1, 'widthPt': 1, 'sides': {'top': {'val': 'single', 'widthPt': 1, 'spacePt': 1, 'shadow': False}}},
    {'offsetFrom': 'page', 'spacePt': 1, 'widthPt': 1, 'sides': {'top': {'val': 'not-a-border', 'widthPt': 1, 'spacePt': 1}}},
])
def test_page_border_dialog_rejects_unknown_or_invalid_properties(props):
    source = source_document(); target = inspect_docx(source)['sections'][0]
    operation = {'kind': 'setSectionLayout', 'sectionId': target['sectionId'], 'expectedSectionSha256': target['expectedSectionSha256'],
        'values': {'pageBorder': True, 'pageBorderProps': props}}
    with pytest.raises(ValueError, match='section_page_border_props_invalid'):
        patch_docx(source, [operation])


def test_page_border_dialog_rejects_props_without_enabled_border_or_on_protected_document():
    source = source_document(); target = inspect_docx(source)['sections'][0]
    props = {'offsetFrom': 'text', 'spacePt': 4, 'widthPt': 1, 'sides': {'top': {'val': 'single', 'widthPt': 1, 'spacePt': 4}}}
    base = {'kind': 'setSectionLayout', 'sectionId': target['sectionId'], 'expectedSectionSha256': target['expectedSectionSha256']}
    with pytest.raises(ValueError, match='section_layout_invalid'):
        patch_docx(source, [{**base, 'values': {'pageBorder': False, 'pageBorderProps': props}}])
    doc = Document(BytesIO(source)); protection = OxmlElement('w:documentProtection')
    protection.set(qn('w:edit'), 'readOnly'); protection.set(qn('w:enforcement'), '1'); doc.settings.element.append(protection)
    stream = BytesIO(); doc.save(stream); protected = stream.getvalue(); target = inspect_docx(protected)['sections'][0]
    with pytest.raises(ValueError, match='section_page_border_unsupported'):
        patch_docx(protected, [{**base, 'sectionId': target['sectionId'], 'expectedSectionSha256': target['expectedSectionSha256'],
            'values': {'pageBorder': True, 'pageBorderProps': props}}])
