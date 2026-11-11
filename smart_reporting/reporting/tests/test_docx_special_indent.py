"""特殊缩进：真实 DOCX 原生属性和非目标内容保全。"""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import json
import subprocess
from zipfile import ZipFile

import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source_docx(characters=False):
    doc = Document()
    style = doc.styles.add_style('SpecialSource', WD_STYLE_TYPE.PARAGRAPH)
    inherited = OxmlElement('w:ind')
    inherited.set(qn('w:hangingChars'), '100')
    style.element.get_or_add_pPr().append(inherited)
    target = doc.add_paragraph(style=style)
    target.add_run('首行与悬挂').bold = True
    target.add_run('保持斜体').italic = True
    target.paragraph_format.space_after = Pt(6)
    target.paragraph_format.keep_with_next = True
    ind = OxmlElement('w:ind')
    attrs = {'left': '720', 'leftChars': '300', 'right': '360', 'rightChars': '0', 'firstLine': '180'}
    if characters:
        attrs['firstLineChars'] = '200'
    for key, value in attrs.items():
        ind.set(qn('w:' + key), value)
    target._p.pPr.append(ind)
    doc.add_paragraph('其它段落保留')
    doc.add_table(rows=1, cols=1).cell(0, 0).text = '表格保留'
    doc.sections[0].header.paragraphs[0].text = '页眉保留'
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


def operation(source, twips):
    target = inspect_docx(source)['blocks'][0]
    return {'kind': 'setParagraphSpecialIndent', 'blockId': target['blockId'],
            'expectedObjectSha256': target['expectedObjectSha256'], 'twips': twips}


@pytest.mark.parametrize('characters', [False, True])
@pytest.mark.parametrize('twips', [365, -480, 0, 14400, -14400])
def test_docx_special_indent_roundtrip_preserves_unrelated_xml(characters, twips):
    source = source_docx(characters)
    result = patch_docx(source, [operation(source, twips)])
    original, reopened = Document(BytesIO(source)), Document(BytesIO(result))
    ind = reopened.paragraphs[0]._p.pPr.find(qn('w:ind'))
    expected = {'left': '720', 'leftChars': '300', 'right': '360', 'rightChars': '0',
                'firstLineChars': '0', 'hangingChars': '0'}
    expected['hanging' if twips < 0 else 'firstLine'] = str(abs(twips))
    assert dict(ind.attrib) == {qn('w:' + key): value for key, value in expected.items()}
    assert reopened.paragraphs[0].paragraph_format.first_line_indent.twips == twips
    assert reopened.paragraphs[0].text == original.paragraphs[0].text
    def normalized_runs(doc):
        return [run._r.xml.replace(' xml:space="preserve"', '') for run in doc.paragraphs[0].runs]
    assert normalized_runs(original) == normalized_runs(reopened)
    properties = []
    for doc in (original, reopened):
        props = deepcopy(doc.paragraphs[0]._p.pPr)
        props.remove(props.find(qn('w:ind')))
        properties.append(props.xml)
    assert properties[0] == properties[1]
    assert [node.xml for node in list(original._element.body)[1:]] == [node.xml for node in list(reopened._element.body)[1:]]
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(result)) as after:
        assert {name for name in before.namelist() if not name.endswith('/')} == {name for name in after.namelist() if not name.endswith('/')}
        for name in before.namelist():
            if name not in {'word/document.xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name


@pytest.mark.parametrize('twips', [-14401, 14401, 1.5, None, True, '365'])
def test_docx_special_indent_rejects_invalid_values(twips):
    source = source_docx()
    with pytest.raises(ValueError, match='special_indent_invalid'):
        patch_docx(source, [operation(source, twips)])


@pytest.mark.parametrize('characters', [False, True])
@pytest.mark.parametrize(('hundredths', 'twips'), [(1, 2), (235, 564), (6000, 14400)])
def test_docx_first_line_characters_roundtrip_preserves_units_and_unrelated_parts(characters, hundredths, twips):
    doc = Document(BytesIO(source_docx(characters)))
    doc.paragraphs[0].runs[0].font.size = Pt(12)
    doc.paragraphs[0].runs[1].font.size = Pt(20)
    stream = BytesIO()
    doc.save(stream)
    source = stream.getvalue()
    op = {**operation(source, twips), 'firstLineChars': hundredths}
    result = patch_docx(source, [op])
    reopened = Document(BytesIO(result))
    ind = reopened.paragraphs[0]._p.pPr.find(qn('w:ind'))
    assert dict(ind.attrib) == {qn('w:' + k): v for k, v in {
        'left': '720', 'leftChars': '300', 'right': '360', 'rightChars': '0',
        'firstLine': str(twips), 'firstLineChars': str(hundredths), 'hangingChars': '0',
    }.items()}
    assert reopened.paragraphs[0].text == doc.paragraphs[0].text
    assert [node.xml for node in list(doc._element.body)[1:]] == [node.xml for node in list(reopened._element.body)[1:]]
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(result)) as after:
        for name in before.namelist():
            if name not in {'word/document.xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name
    reverted = patch_docx(result, [operation(result, 0)])
    cleared = Document(BytesIO(reverted)).paragraphs[0]._p.pPr.find(qn('w:ind'))
    assert cleared.get(qn('w:firstLineChars')) == '0'
    assert cleared.get(qn('w:hangingChars')) == '0'
    assert cleared.get(qn('w:firstLine')) == '0'


def test_docx_first_line_characters_reparse_after_first_run_font_change(tmp_path):
    doc = Document(BytesIO(source_docx(True)))
    doc.paragraphs[0].runs[0].font.size = Pt(12)
    stream = BytesIO()
    doc.save(stream)
    source = stream.getvalue()
    result = patch_docx(source, [{**operation(source, 564), 'firstLineChars': 235}])
    before = tmp_path / 'before.docx'
    before.write_bytes(result)
    reopened = Document(BytesIO(result))
    reopened.paragraphs[0].runs[0].font.size = Pt(18)
    after = tmp_path / 'after.docx'
    reopened.save(after)
    # 真实引擎重解析：同一firstLineChars随段首字号从12pt到18pt重新换算。
    engine = Path(__file__).resolve().parents[1] / 'doc_engine'
    probe = subprocess.run(['node', '--import', 'tsx', '--input-type=module', '-e', '''
import { readFile } from 'node:fs/promises';
import { parseDocx } from './packages/docx-engine/src/index.ts';
const values = [];
for (const path of process.argv.slice(1)) {
  const doc = await parseDocx(new Uint8Array(await readFile(path)));
  values.push(doc.blocks[0].format.indentFirstLine);
}
process.stdout.write(JSON.stringify(values));
''', str(before), str(after)], cwd=engine, capture_output=True, text=True, timeout=60, check=True)
    assert json.loads(probe.stdout) == [564, 846]


@pytest.mark.parametrize('hundredths', [0, -1, 10001, 1.5, None, True, '235'])
def test_docx_first_line_characters_reject_invalid_values(hundredths):
    source = source_docx()
    with pytest.raises(ValueError, match='special_indent_invalid'):
        patch_docx(source, [{**operation(source, 564), 'firstLineChars': hundredths}])


def test_docx_first_line_characters_reject_hanging_twips():
    source = source_docx()
    with pytest.raises(ValueError, match='special_indent_invalid'):
        patch_docx(source, [{**operation(source, -480), 'firstLineChars': 200}])
