from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.enum.section import WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source_document():
    doc = Document()
    doc.add_paragraph('First section stays literal').runs[0].bold = True
    doc.add_section(WD_SECTION.NEW_PAGE)
    doc.add_paragraph('Second section stays literal')
    doc.add_table(rows=1, cols=1).cell(0, 0).text = 'Untouched table'
    for section in doc.sections:
        border = OxmlElement('w:pgBorders')
        border.set(qn('w:offsetFrom'), 'text')
        top = OxmlElement('w:top')
        for key, value in {'val': 'double', 'sz': '16', 'space': '8', 'color': '123456'}.items():
            top.set(qn(f'w:{key}'), value)
        border.append(top)
        section._sectPr.append(border)
    output = BytesIO(); doc.save(output)
    return output.getvalue()


@pytest.mark.parametrize('target_index', [0, 1])
def test_default_page_box_and_none_only_change_selected_section(target_index):
    source = source_document()
    for enabled in [True, False]:
        model = inspect_docx(source); target = model['sections'][target_index]
        op = {'kind': 'setSectionLayout', 'sectionId': target['sectionId'], 'expectedSectionSha256': target['expectedSectionSha256'], 'values': {'pageBorder': enabled}}
        output = patch_docx(source, [op])
        actual = Document(BytesIO(output))
        borders = actual.sections[target_index]._sectPr.findall(qn('w:pgBorders'))
        if enabled:
            assert len(borders) == 1 and borders[0].get(qn('w:offsetFrom')) == 'page'
            assert [etree.QName(side).localname for side in borders[0]] == ['top', 'left', 'bottom', 'right']
            assert all(side.get(qn('w:val')) == 'single' and side.get(qn('w:sz')) == '4' and side.get(qn('w:space')) == '24' for side in borders[0])
        else:
            assert not borders
        assert inspect_docx(output)['sections'][target_index]['settings']['pageBorder'] is enabled
        with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(output)) as after:
            for name in before.namelist():
                if name != 'word/document.xml': assert before.read(name) == after.read(name), name
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            a = etree.fromstring(before.read('word/document.xml')); b = etree.fromstring(after.read('word/document.xml'))
            assert etree.tostring(a.xpath('//w:sectPr', namespaces=ns)[1-target_index], method='c14n') == etree.tostring(b.xpath('//w:sectPr', namespaces=ns)[1-target_index], method='c14n')
        assert [p.text for p in actual.paragraphs] == [p.text for p in Document(BytesIO(source)).paragraphs]
        assert actual.paragraphs[0].runs[0].bold
        assert actual.tables[0].cell(0, 0).text == 'Untouched table'
        source = output


@pytest.mark.parametrize('values', [{'pageBorder': 'yes'}, {'pageBorder': 1}, {'pageBorder': None}, {'pageBorder': True, 'pageBorderProps': {}}])
def test_page_border_only_accepts_the_source_boolean_shortcuts(values):
    source = source_document(); target = inspect_docx(source)['sections'][0]
    with pytest.raises(ValueError):
        patch_docx(source, [{'kind': 'setSectionLayout', 'sectionId': target['sectionId'], 'expectedSectionSha256': target['expectedSectionSha256'], 'values': values}])


def test_page_border_rejects_protected_document_and_stale_section_identity():
    source = source_document(); target = inspect_docx(source)['sections'][0]
    op = {'kind': 'setSectionLayout', 'sectionId': target['sectionId'], 'expectedSectionSha256': '0'*64, 'values': {'pageBorder': True}}
    with pytest.raises(ValueError, match='section_anchor_invalid'):
        patch_docx(source, [op])
    doc = Document(BytesIO(source)); protection = OxmlElement('w:documentProtection')
    protection.set(qn('w:edit'), 'readOnly'); protection.set(qn('w:enforcement'), '1'); doc.settings.element.append(protection)
    stream = BytesIO(); doc.save(stream); source = stream.getvalue(); target = inspect_docx(source)['sections'][0]
    with pytest.raises(ValueError, match='section_page_border_unsupported'):
        patch_docx(source, [{**op, 'sectionId': target['sectionId'], 'expectedSectionSha256': target['expectedSectionSha256']}])
