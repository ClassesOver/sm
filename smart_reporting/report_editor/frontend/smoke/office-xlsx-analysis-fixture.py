"""模拟分析：真实XLSX保存，独立回读公式、静态结果及未修改格式。"""
import json
import sys
from copy import copy, deepcopy
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.workbook.defined_name import DefinedName
from smart_reporting.report_editor.native_office import patch_office


def run(payload):
    directory = Path(payload['directory'])
    if payload['mode'] == 'create':
        book = Workbook()
        sheet = book.active
        sheet.title = 'Analysis'
        sheet['A1'], sheet['B1'] = 5, '=A1*2'
        sheet['A1'].font = Font(name='Calibri', size=13, bold=True, color='17365D')
        sheet['A1'].fill = PatternFill('solid', fgColor='DCE6F1')
        sheet['A1'].number_format = '0.00'
        sheet['B1'].number_format = '0.00'
        sheet['D2'], sheet['E2'] = '候选值', '=A1*2'
        for row, value in enumerate([10, 20, 30], 3):
            sheet.cell(row, 4, value)
            cell = sheet.cell(row, 5)
            cell.font = Font(name='Calibri', size=12, color='0070C0')
            cell.alignment = Alignment(horizontal='right')
            cell.border = Border(bottom=Side(style='thin', color='D9E2F3'))
            cell.number_format = '#,##0.00'
        sheet['G1'] = '保留 & <保真> 😀'
        sheet['G1'].hyperlink = 'https://example.invalid/preserved'
        sheet['G1'].comment = Comment('不属于本次求解或模拟运算', 'Fixture')
        sheet.column_dimensions['A'].width = 17
        sheet.column_dimensions['D'].width = 18
        sheet.column_dimensions['G'].width = 28
        sheet.row_dimensions[1].height = 24
        sheet.freeze_panes = 'B2'
        book.defined_names.add(DefinedName('BaseInput', attr_text="'Analysis'!$A$1"))
        locked = book.create_sheet('Locked')
        locked['A1'] = '来源保留'
        locked['C2'] = '=1+2'
        locked.protection.sheet = True
        book.save(directory / 'source.xlsx')
        return {'sha256': sha256((directory / 'source.xlsx').read_bytes()).hexdigest()}
    if payload['mode'] == 'patch':
        content = patch_office('xlsx', (directory / 'source.xlsx').read_bytes(), payload['operations'])
        (directory / 'revision-2.xlsx').write_bytes(content)
        return {'sha256': sha256(content).hexdigest(), 'size': len(content)}
    before = load_workbook(directory / 'source.xlsx')
    after = load_workbook(directory / 'downloaded.xlsx')
    expected = {'A1': 15, 'E3': 20, 'E4': 40, 'E5': 60}
    assert before.sheetnames == after.sheetnames == ['Analysis', 'Locked']
    cells = []
    for name in before.sheetnames:
        a, b = before[name], after[name]
        assert (a.max_row, a.max_column) == (b.max_row, b.max_column)
        assert a.protection == b.protection and a.freeze_panes == b.freeze_panes
        assert dict(a.defined_names) == dict(b.defined_names)
        assert list(a.column_dimensions) == list(b.column_dimensions)
        assert list(a.row_dimensions) == list(b.row_dimensions)
        for key in a.column_dimensions:
            assert dict(a.column_dimensions[key]) == dict(b.column_dimensions[key])
            assert a.column_dimensions[key]._style == b.column_dimensions[key]._style
        for key in a.row_dimensions:
            assert dict(a.row_dimensions[key]) == dict(b.row_dimensions[key])
            assert a.row_dimensions[key]._style == b.row_dimensions[key]._style
        for row in a:
            for old in row:
                new = b[old.coordinate]
                value = expected.get(old.coordinate, old.value) if name == 'Analysis' else old.value
                assert new.value == value, (name, old.coordinate, new.value, value)
                for attribute in ['font', 'fill', 'border', 'alignment', 'protection']:
                    assert copy(getattr(old, attribute)) == copy(getattr(new, attribute)), (name, old.coordinate, attribute)
                assert old.number_format == new.number_format
                assert old.hyperlink == new.hyperlink and old.comment == new.comment
                cells.append([name, old.coordinate])
    assert before.defined_names == after.defined_names
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(directory / 'source.xlsx') as a, ZipFile(directory / 'downloaded.xlsx') as b:
        assert a.testzip() is None and b.testzip() is None
        assert set(a.namelist()) == set(b.namelist())
        changed = [name for name in a.namelist() if a.read(name) != b.read(name)]
        assert changed == ['xl/worksheets/sheet1.xml'], changed
        original = etree.fromstring(a.read(changed[0]))
        actual = etree.fromstring(b.read(changed[0]))
        for address in expected:
            old = original.xpath(f'.//s:c[@r="{address}"]', namespaces=ns)
            new = actual.xpath(f'.//s:c[@r="{address}"]', namespaces=ns)
            assert len(old) == len(new) == 1
            new[0].getparent().replace(new[0], deepcopy(old[0]))
        assert etree.tostring(original, method='c14n') == etree.tostring(actual, method='c14n'), 'XML changed outside four requested result cells'
    result = {'ok': True, 'sourceSha256': sha256((directory / 'source.xlsx').read_bytes()).hexdigest(),
              'outputSha256': sha256((directory / 'downloaded.xlsx').read_bytes()).hexdigest(),
              'sourceBytes': (directory / 'source.xlsx').stat().st_size, 'outputBytes': (directory / 'downloaded.xlsx').stat().st_size,
              'expectedValues': expected, 'formulaB1': after['Analysis']['B1'].value, 'formulaE2': after['Analysis']['E2'].value,
              'cellsChecked': cells, 'changedParts': changed, 'onlyFourResultCellsChanged': True,
              'stylesLinksCommentsNamesDimensionsProtectionPreserved': True}
    (directory / 'independent-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


if __name__ == '__main__':
    print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False))
