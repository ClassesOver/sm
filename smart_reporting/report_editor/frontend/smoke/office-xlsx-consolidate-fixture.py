"""合并计算真实保存夹具；以独立 XML/openpyxl 检查目标公式和非目标保真。"""
import json
import sys
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from openpyxl.workbook.defined_name import DefinedName


def expected_cells():
    formulas, values = {}, {}
    for index, (function, results) in enumerate([
        ('SUM', [12, 24, 6]), ('COUNTA', [2, 2, 1]),
        ('AVERAGE', [6, 12, 6]), ('MAX', [10, 20, 6]), ('MIN', [2, 4, 6]),
    ]):
        for offset, result in enumerate(results):
            address = f'E{index * 5 + offset + 1}'
            refs = [f"'West Side'!B{offset + 1}"]
            if offset < 2:
                refs.append(f"'O''Brien'!B{offset + 1}")
            formulas[address] = f'={function}({",".join(refs)})'
            values[address] = result
    for index, results in enumerate([[8, 14, 20], [2, 2, 1], [4, 7, 20]]):
        for offset, (label, result) in enumerate(zip(['Ada', 'Bob', 'Cara'], results)):
            row = index * 5 + offset + 1
            formulas[f'H{row}'] = values[f'H{row}'] = label
            sources = []
            if label != 'Cara':
                sources.append(("'West Side'", 3))
            if label != 'Ada':
                sources.append(("'O''Brien'", 2))
            sums = '+'.join(f'SUMIF({sheet}!$A$1:$A${end},$H{row},{sheet}!B1:B{end})' for sheet, end in sources)
            counts = '+'.join(f'COUNTIF({sheet}!$A$1:$A${end},$H{row})' for sheet, end in sources)
            formulas[f'I{row}'] = '=' + (sums if index == 0 else counts if index == 1 else f'({sums})/({counts})')
            values[f'I{row}'] = result
    assert len(formulas) == 33
    return formulas, values


def run(payload):
    directory = Path(payload['directory'])
    source = directory / 'source.xlsx'
    if payload['mode'] == 'create':
        assert not source.exists(), '禁止覆盖已有来源夹具'
        book = Workbook()
        summary = book.active
        summary.title = 'Summary'
        for address in expected_cells()[0]:
            summary[address] = f'old-{address}'
        summary['H1'] = '=99'
        summary['E1'].number_format = '0.00'
        summary['E1'].font = Font(name='Calibri', size=12, bold=True, color='17365D')
        summary['E1'].fill = PatternFill('solid', fgColor='DCE6F1')
        summary['K26'] = '保留 & <来源> 😀'
        summary['K26'].comment = Comment('合并计算范围外批注', 'Fixture')
        summary['K26'].hyperlink = 'https://example.invalid/preserved'
        summary['K25'] = '=1+2'
        summary.merge_cells('A20:C20')
        summary['A20'] = '范围外合并区'
        summary.row_dimensions[26].height = 27
        summary.column_dimensions['K'].width = 29
        summary.column_dimensions['E'].width = 19
        summary.freeze_panes = 'B2'
        book.defined_names.add(DefinedName('PreservedCell', attr_text="'Summary'!$K$26"))
        for name, rows in [('West Side', [('Ada', 2), ('Bob', 4), ('Ada', 6)]), ("O'Brien", [('Bob', 10), ('Cara', 20)])]:
            sheet = book.create_sheet(name)
            for row in rows:
                sheet.append(row)
        book.save(source)
        return {'sha256': sha256(source.read_bytes()).hexdigest()}
    if payload['mode'] == 'patch':
        from smart_reporting.report_editor.native_office import patch_office
        output = directory / 'revision-2.xlsx'
        assert not output.exists(), '禁止覆盖已保存产物'
        output.write_bytes(patch_office('xlsx', source.read_bytes(), payload['operations']))
        return {'sha256': sha256(output.read_bytes()).hexdigest(), 'size': output.stat().st_size}
    output = Path(payload.get('file', directory / 'downloaded.xlsx'))
    expected, cached = expected_cells()
    before, after = load_workbook(source), load_workbook(output)
    actual_cached = load_workbook(output, data_only=True)
    missing_caches = []
    assert before.sheetnames == after.sheetnames == ['Summary', 'West Side', "O'Brien"]
    for address, value in expected.items():
        assert after['Summary'][address].value == value, (address, after['Summary'][address].value, value)
        value = actual_cached['Summary'][address].value
        if value is None and isinstance(expected[address], str) and expected[address].startswith('='):
            missing_caches.append(address)
        else:
            assert type(value) is type(cached[address]) and value == cached[address], (address, 'cache', value, cached[address])
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(source) as original, ZipFile(output) as result:
        assert original.testzip() is None and result.testzip() is None
        names = {name for name in original.namelist() if not name.endswith('/')}
        assert names == {name for name in result.namelist() if not name.endswith('/')}
        for name in names:
            if name.endswith(('.xml', '.rels')):
                etree.fromstring(result.read(name))
        calculation = etree.fromstring(result.read('xl/workbook.xml')).find('m:calcPr', ns)
        if missing_caches:
            assert calculation is not None and calculation.get('fullCalcOnLoad') in ('1', 'true'), '缺失公式缓存时必须标记打开后重算'
            assert calculation.get('calcMode') != 'manual', '缺失公式缓存不能依赖手动计算'
        changed = sorted(name for name in names if original.read(name) != result.read(name))
        assert changed == ['xl/worksheets/sheet1.xml'], changed
        old = etree.fromstring(original.read(changed[0]))
        new = etree.fromstring(result.read(changed[0]))
        for address in expected:
            a, b = [root.xpath(f'.//m:c[@r="{address}"]', namespaces=ns) for root in [old, new]]
            assert len(a) == len(b) == 1
            assert {k: v for k, v in a[0].attrib.items() if k != 't'} == {k: v for k, v in b[0].attrib.items() if k != 't'}, (address, 'cell style/identity')
            b[0].getparent().replace(b[0], deepcopy(a[0]))
        assert etree.tostring(old, method='c14n') == etree.tostring(new, method='c14n'), '33个目标单元格外XML发生变化'
    return {'ok': True, 'formulas': expected, 'expectedValues': cached, 'targetCells': 33,
            'missingFormulaCaches': missing_caches, 'recalculateOnOpen': bool(missing_caches),
            'cachePolicy': '非空缓存必须正确；缺失缓存要求fullCalcOnLoad且非manual，实际重算另由浏览器新修订逐项验证',
            'changedParts': changed, 'sourceSha256': sha256(source.read_bytes()).hexdigest(),
            'outputSha256': sha256(output.read_bytes()).hexdigest(),
            'sourceSheetsByteIdentical': True, 'nonTargetXmlByteEquivalent': True,
            'targetStylesPreserved': True, 'zipCrcAndXmlHealthy': True}


if __name__ == '__main__':
    print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False))
