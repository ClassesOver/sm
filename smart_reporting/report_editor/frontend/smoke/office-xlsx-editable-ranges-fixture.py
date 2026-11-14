"""允许编辑区域：真实保存桥与独立 ZIP/XML/openpyxl 保真检查。"""
import json
import sys
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from lxml import etree
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from openpyxl.workbook.defined_name import DefinedName

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
EXPECTED = [
    {'name': 'Sales_Input', 'sqref': 'B2:C4 E2:E4'},
    {'name': 'Keep', 'sqref': 'D8'},
    {'name': 'Extra', 'sqref': 'F2:F4'},
]


def create(source):
    assert not source.exists(), '禁止覆盖已有来源'
    book = Workbook()
    sheet = book.active
    sheet.title = 'Inputs'
    for row in [['Locked', 'Amount', 'Quantity', 'Other', 'Formula', 'Extra'],
                ['locked', 10, 3, 'preserve', 5, 6], ['row3', 20, 4, '', 8, 9], ['row4', 30, 5, '', 10, 11]]:
        sheet.append(row)
    sheet['B3'].font = Font(name='Calibri', size=12, bold=True, color='17365D')
    sheet['B3'].fill = PatternFill('solid', fgColor='DCE6F1')
    sheet['B3'].number_format = '0.00'
    sheet['B3'].comment = Comment('保留批注 & <原内容>', 'Fixture')
    sheet['B3'].hyperlink = 'https://example.invalid/preserved'
    sheet['D8'] = 'Keep region'
    sheet['J10'] = '=1+2'
    sheet.merge_cells('H12:J12'); sheet['H12'] = '非目标合并区域'
    sheet.column_dimensions['B'].width = 24
    sheet.row_dimensions[3].height = 28
    sheet.freeze_panes = 'B2'
    book.defined_names.add(DefinedName('PreservedCell', attr_text="'Inputs'!$B$3"))
    chart = BarChart(); chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=4), titles_from_data=True)
    sheet.add_chart(chart, 'L2')
    locked = book.create_sheet('Locked'); locked['A1'] = 'password-protected'; locked.protection.set_password('fixture'); locked.protection.sheet = True
    restricted = book.create_sheet('Restricted'); restricted['A1'] = '密码范围只读'
    buffer = BytesIO(); book.save(buffer)
    with ZipFile(BytesIO(buffer.getvalue())) as original, ZipFile(source, 'w', ZIP_DEFLATED) as output:
        for info in original.infolist():
            raw = original.read(info.filename)
            if info.filename in ('xl/worksheets/sheet1.xml', 'xl/worksheets/sheet3.xml'):
                root = etree.fromstring(raw)
                ranges = etree.Element(f'{{{NS["m"]}}}protectedRanges')
                definitions = [{'name':'Entry','sqref':'B2:C4'}, {'name':'Remove','sqref':'H2:H3'}, {'name':'Keep','sqref':'D8'}] if info.filename.endswith('sheet1.xml') else [{'name':'Secret','sqref':'A1','password':'ABCD'}]
                for definition in definitions:
                    etree.SubElement(ranges, f'{{{NS["m"]}}}protectedRange', **definition)
                root.insert(list(root).index(root.find('m:sheetData', NS)) + 1, ranges)
                raw = etree.tostring(root)
            output.writestr(info, raw)
    return {'sourceSha256': sha256(source.read_bytes()).hexdigest()}


def inspect(source, output):
    before, after = load_workbook(source), load_workbook(output)
    assert after.sheetnames == before.sheetnames == ['Inputs', 'Locked', 'Restricted']
    assert after['Inputs']['B2'].value == 42
    assert after['Inputs']['E2'].value == '=SUM(B2:C2)'
    assert after['Inputs'].protection.sheet is True
    assert after['Inputs'].protection.password is None
    assert after['Locked'].protection.password == before['Locked'].protection.password
    with ZipFile(source) as a, ZipFile(output) as b:
        assert a.testzip() is None and b.testzip() is None
        names = {n for n in a.namelist() if not n.endswith('/')}
        assert names == {n for n in b.namelist() if not n.endswith('/')}
        for name in names:
            if name.endswith(('.xml', '.rels')):
                etree.fromstring(b.read(name))
        changed = sorted(n for n in names if a.read(n) != b.read(n))
        assert changed == ['xl/worksheets/sheet1.xml'], changed
        old, new = [etree.fromstring(z.read(changed[0])) for z in [a, b]]
        actual = new.find('m:protectedRanges', NS)
        assert actual is not None
        assert [dict(n.attrib) for n in actual] == EXPECTED, [dict(n.attrib) for n in actual]
        protection = new.find('m:sheetProtection', NS)
        assert protection is not None and dict(protection.attrib) == {'sheet':'1','objects':'1','scenarios':'1'}, '工作表保护权限不符合默认设置'
        children = list(new)
        assert children.index(new.find('m:sheetData', NS)) < children.index(protection) < children.index(actual) < children.index(new.find('m:mergeCells', NS)), '保护及区域定义的OOXML顺序无效'
        # 比较范围外XML；目标节点单独核对内容及规范顺序，不把旧夹具的错误节点位置当作保真契约。
        old.remove(old.find('m:protectedRanges', NS)); new.remove(actual)
        new.remove(protection)
        for address in ['B2', 'E2']:
            old_cell, new_cell = [root.xpath(f'.//m:c[@r="{address}"]', namespaces=NS)[0] for root in [old, new]]
            assert {k:v for k,v in old_cell.attrib.items() if k != 't'} == {k:v for k,v in new_cell.attrib.items() if k != 't'}, '目标单元格样式改变'
            new_cell.getparent().replace(new_cell, deepcopy(old_cell))
        assert etree.tostring(old, method='c14n') == etree.tostring(new, method='c14n'), '目标区域定义、保护和两处值之外的XML变化'
        unchanged = sorted(names - set(changed))
    return {'ok':True, 'sourceSha256':sha256(source.read_bytes()).hexdigest(), 'outputSha256':sha256(output.read_bytes()).hexdigest(),
            'ranges':EXPECTED, 'allowedValue':42, 'allowedFormula':'=SUM(B2:C2)', 'protected':True,
            'changedParts':changed, 'unchangedParts':unchanged, 'nonTargetXmlEquivalent':True,
            'stylesCommentsLinksChartNamesDimensionsAndOtherProtectionPreserved':True, 'zipAndXmlHealthy':True}


def run(payload):
    directory = Path(payload['directory']); source = directory / 'source.xlsx'
    if payload['mode'] == 'create':
        return create(source)
    if payload['mode'] == 'patch':
        from smart_reporting.report_editor.native_office import patch_office
        output = directory / 'revision-2.xlsx'
        assert not output.exists(), '禁止重复保存'
        output.write_bytes(patch_office('xlsx', source.read_bytes(), payload['operations']))
        return {'sha256':sha256(output.read_bytes()).hexdigest(), 'size':output.stat().st_size}
    return inspect(source, Path(payload.get('file', directory / 'downloaded.xlsx')))


if __name__ == '__main__':
    print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False))
