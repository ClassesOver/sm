"""Reproduce table serializer preservation limits without enabling product commands."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import RGBColor
from lxml import etree

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / 'smart_reporting/reporting/doc_engine'
NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def element(tag, **attrs):
    node = OxmlElement(f'w:{tag}')
    for key, value in attrs.items():
        node.set(qn(f'w:{key}'), str(value))
    return node


def fixture(path):
    doc = Document()
    doc.add_paragraph('Untouched before')
    doc.sections[0].header.paragraphs[0].text = 'Untouched header'
    doc.sections[0].footer.paragraphs[0].text = 'Untouched footer'
    table = doc.add_table(rows=3, cols=3)
    table.autofit = False
    table._tbl.tblPr.find(qn('w:tblW')).set(qn('w:w'), '9000')
    table._tbl.tblPr.find(qn('w:tblW')).set(qn('w:type'), 'dxa')
    widths = [2400, 3000, 3600]
    for node, width in zip(table._tbl.tblGrid, widths, strict=True):
        node.set(qn('w:w'), str(width))
    for ri, row in enumerate(table.rows):
        props = row._tr.get_or_add_trPr()
        props.append(element('trHeight', val=300 + ri * 100, hRule='atLeast'))
        if ri == 0:
            props.append(element('tblHeader'))
        if ri == 1:
            props.append(element('cantSplit'))
        for ci, cell in enumerate(row.cells):
            cell._tc.get_or_add_tcPr().find(qn('w:tcW')).set(qn('w:w'), str(widths[ci]))
            cell._tc.get_or_add_tcPr().append(element('shd', val='clear', color='auto', fill=f'{ri + 1}{ci + 1}CCAA'))
            para = cell.paragraphs[0]
            para._p.set(qn('w:rsidR'), f'{ri + 1:04X}{ci + 1:04X}')
            para._p.get_or_add_pPr().append(element('mirrorIndents'))
            run = para.add_run(f'R{ri}C{ci}')
            run.bold = True
            run.font.color.rgb = RGBColor.from_string('194361')
    doc.add_paragraph('Untouched after')
    doc.save(path)


def read_package(path):
    with ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}
    root = etree.fromstring(members['word/document.xml'])
    table = root.find('w:body/w:tbl', NS)
    matrix = [[cell.text for cell in row.cells] for row in Document(path).tables[0].rows]
    return members, root, table, matrix


def text(node):
    return ''.join(node.xpath('.//w:t/text()', namespaces=NS))


def row_props(row):
    props = row.find('w:trPr', NS)
    height = props.find('w:trHeight', NS) if props is not None else None
    def enabled(tag):
        node = props.find(f'w:{tag}', NS) if props is not None else None
        return node is not None and node.get(qn('w:val')) not in {'0', 'false', 'off'}
    return {'height': height.get(qn('w:val')) if height is not None else None,
            'header': enabled('tblHeader'), 'cantSplit': enabled('cantSplit')}


def run(output, preserve=False):
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'source.docx'
    fixture(source)
    subprocess.run([str(ENGINE / 'node_modules/.bin/tsx'), 'probes/docx-table-structure.ts',
                    str(source), str(output / 'cases'), *(['--preserve'] if preserve else [])], cwd=ENGINE, check=True)
    original, root, table, matrix = read_package(source)
    cases = json.loads((output / 'cases/engine-cases.json').read_text())
    original_rows = table.findall('w:tr', NS)
    original_cells = {text(cell): cell for row in original_rows for cell in row.findall('w:tc', NS)}
    results = []
    for case in cases:
        operation, index = case['operation'], case['index']
        path = output / 'cases' / case['file']
        members, after_root, after_table, after_matrix = read_package(path)
        expected = [row[:] for row in matrix]
        widths = [2400, 3000, 3600]
        row_ids = [0, 1, 2]
        if operation == 'insertRow':
            expected.insert(index, ['', '', ''])
            row_ids.insert(index, None)
        elif operation == 'deleteRow':
            expected.pop(index)
            row_ids.pop(index)
        elif operation == 'insertColumn':
            for row in expected:
                row.insert(index, '')
            neighbor = min(index, 2)
            width = widths[neighbor]
            widths[neighbor:neighbor + 1] = [width // 2, width - width // 2]
        elif operation == 'deleteColumn':
            for row in expected:
                row.pop(index)
            removed = widths.pop(index)
            widths[min(index, len(widths) - 1)] += removed
        assert after_matrix == expected == case['engineMatrix'], case
        changed = sorted(name for name in original.keys() | members.keys() if original.get(name) != members.get(name))
        assert set(changed) <= {'word/document.xml', 'docProps/core.xml'}, changed
        if 'docProps/core.xml' in changed:
            before_core = etree.fromstring(original['docProps/core.xml'])
            after_core = etree.fromstring(members['docProps/core.xml'])
            cp = 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties'
            dt = 'http://purl.org/dc/terms/'
            assert before_core.find(f'{{{cp}}}revision').text == '1'
            assert after_core.find(f'{{{cp}}}revision').text == '2'
            for tag in [f'{{{cp}}}revision', f'{{{dt}}}modified']:
                before_core.remove(before_core.find(tag))
                after_core.remove(after_core.find(tag))
            assert etree.tostring(before_core, method='c14n') == etree.tostring(after_core, method='c14n')
        before_other = [etree.tostring(node, method='c14n') for node in root.find('w:body', NS) if node.tag != qn('w:tbl')]
        after_other = [etree.tostring(node, method='c14n') for node in after_root.find('w:body', NS) if node.tag != qn('w:tbl')]
        assert before_other == after_other, case
        assert [int(node.get(qn('w:w'))) for node in after_table.findall('w:tblGrid/w:gridCol', NS)] == widths, case
        assert sum(widths) == 9000
        losses = []
        for ri, row in enumerate(after_table.findall('w:tr', NS)):
            expected_props = row_props(original_rows[row_ids[ri]]) if row_ids[ri] is not None else {'height': None, 'header': False, 'cantSplit': False}
            if preserve and row_ids[ri] is None and index == 0:
                expected_props['header'] = True
            assert row_props(row) == expected_props, (case, ri, row_props(row), expected_props)
            for ci, cell in enumerate(row.findall('w:tc', NS)):
                assert int(cell.find('w:tcPr/w:tcW', NS).get(qn('w:w'))) == widths[ci], case
                value = text(cell)
                if not value:
                    continue
                source_cell = original_cells[value]
                assert cell.find('w:tcPr/w:shd', NS).get(qn('w:fill')) == source_cell.find('w:tcPr/w:shd', NS).get(qn('w:fill')), case
                assert cell.find('w:p/w:r/w:rPr/w:b', NS) is not None, case
                assert cell.find('w:p/w:r/w:rPr/w:color', NS).get(qn('w:val')) == '194361', case
                para = cell.find('w:p', NS)
                if preserve:
                    assert [etree.tostring(p, method='c14n') for p in cell.findall('w:p', NS)] == [etree.tostring(p, method='c14n') for p in source_cell.findall('w:p', NS)], (case, value)
                    before_props = etree.fromstring(etree.tostring(source_cell.find('w:tcPr', NS)))
                    after_props = etree.fromstring(etree.tostring(cell.find('w:tcPr', NS)))
                    before_props.find('w:tcW', NS).set(qn('w:w'), str(widths[ci]))
                    assert etree.tostring(before_props, method='c14n') == etree.tostring(after_props, method='c14n'), (case, value)

                for label, retained in [('w:rsidR', para.get(qn('w:rsidR')) == source_cell.find('w:p', NS).get(qn('w:rsidR'))),
                                        ('w:mirrorIndents', para.find('w:pPr/w:mirrorIndents', NS) is not None)]:
                    if not retained:
                        losses.append({'cell': value, 'property': label})
        if operation == 'original':
            assert path.read_bytes() == source.read_bytes()
            assert not losses
        results.append({**case, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'independentMatrix': after_matrix, 'changedMembers': changed,
                        'modeledChecksPassed': True, 'lostProperties': losses})
    receipt = {'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'cases': results, 'modeledChecksPassed': len(results),
               'casesWithPropertyLoss': sum(bool(case['lostProperties']) for case in results),
               'preservationAdapterVerified': preserve, 'structureReady': False, 'desktopVerified': False,
               'scope': 'local serializer and preservation adapter; product UI not enabled'}
    if preserve:
        assert all(not case['lostProperties'] for case in results)
    (output / 'evidence.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps({key: receipt[key] for key in ['sourceSha256', 'modeledChecksPassed', 'casesWithPropertyLoss', 'structureReady']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='New directory for fixtures, files and evidence')
    parser.add_argument('--preserve', action='store_true', help='Exercise the source-XML preservation adapter')
    args = parser.parse_args()
    run(args.output.resolve(), args.preserve)
