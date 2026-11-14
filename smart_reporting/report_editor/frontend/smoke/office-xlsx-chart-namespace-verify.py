"""XLSX图表浏览器下载：独立ZIP/URI回读，不导入产品读写器。"""
import argparse
import hashlib
import json
import re
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.styles import Font

CHART = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
MAIN = 'http://schemas.openxmlformats.org/drawingml/2006/main'
NS = {'c': CHART, 'a': MAIN}
PART = 'xl/charts/chart1.xml'
TITLE = 'Browser saved & 图表'
VENDOR = '<v:keep xmlns:v="urn:namespace-smoke" marker="unchanged">opaque &amp; untouched</v:keep>'


def digest(content):
    return hashlib.sha256(content).hexdigest()


def create_sources(directory, selected_cases=('default', 'arbitrary', 'mixed')):
    assert selected_cases and len(set(selected_cases)) == len(selected_cases) and all(case in ('default', 'arbitrary', 'mixed') for case in selected_cases)
    book = Workbook(); sheet = book.active; sheet.title = 'Summary'
    for row in [('Quarter', 'Sales'), ('Q1', 10), ('Q2', 20)]: sheet.append(row)
    sheet['B2'].font = Font(name='Calibri', bold=True, color='17365D')
    sheet['B2'].number_format = '0.00'
    sheet['D4'] = '=SUM(B2:B3)'; sheet['D4'].comment = Comment('Preserve source comment', 'Fixture')
    sheet['E5'] = 'Preserved hyperlink'; sheet['E5'].hyperlink = 'https://example.invalid/source'
    sheet.merge_cells('D7:F7'); sheet['D7'] = 'Preserve merged data'
    chart = BarChart(); chart.title = 'Original'; chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=3), titles_from_data=True)
    chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=3)); chart.series[0].graphicalProperties.solidFill = '17365D'
    sheet.add_chart(chart, 'D2'); other = book.create_sheet('Keep'); other['A1'] = 'Untouched sheet'
    stream = BytesIO(); book.save(stream)
    cases = {}
    for case in selected_cases:
        target = directory / case; target.mkdir(parents=True, exist_ok=True)
        source = target / 'source.xlsx'; assert not source.exists(), '禁止覆盖来源'
        with ZipFile(BytesIO(stream.getvalue())) as original, ZipFile(source, 'w', ZIP_DEFLATED) as saved:
            for info in original.infolist():
                raw = original.read(info.filename)
                if info.filename == PART:
                    xml = raw.decode()
                    xml = xml.replace('</chart>', f'<extLst><ext uri="namespace-smoke">{VENDOR}</ext></extLst></chart>')
                    if case == 'arbitrary':
                        xml = re.sub(r'<(/?)([A-Za-z_][\w.-]*)(?=[\s/>])', r'<\1chart:\2', xml)
                        xml = xml.replace(f'xmlns="{CHART}"', f'xmlns:chart="{CHART}"', 1)
                    elif case == 'mixed':
                        for tag in ['title', 'barChart', 'ser']:
                            xml = xml.replace(f'<{tag}>', f'<alt:{tag} xmlns:alt="{CHART}" xmlns:unused="urn:unused">', 1).replace(f'</{tag}>', f'</alt:{tag}>', 1)
                    raw = xml.encode()
                    etree.fromstring(raw)
                saved.writestr(info, raw)
        cases[case] = {'source': str(source), 'sha256': digest(source.read_bytes()), 'size': source.stat().st_size}
    return cases


def semantic(node):
    return (node.tag, sorted(node.attrib.items()), node.text or '', [semantic(child) for child in node if isinstance(child.tag, str)])


def verify_case(directory, output=None):
    source, output = directory / 'source.xlsx', output or directory / 'downloaded.xlsx'
    source_bytes, saved_bytes = source.read_bytes(), output.read_bytes()
    with ZipFile(source) as before, ZipFile(output) as after:
        assert before.testzip() is None and after.testzip() is None
        names = sorted(name for name in before.namelist() if not name.endswith('/'))
        assert names == sorted(name for name in after.namelist() if not name.endswith('/'))
        changed = [name for name in names if before.read(name) != after.read(name)]
        assert changed == [PART], changed
        for name in names:
            if name.endswith(('.xml', '.rels')): etree.fromstring(after.read(name))
        original, saved = [etree.fromstring(z.read(PART)) for z in [before, after]]
        assert len(saved.xpath('./c:chart/c:title', namespaces=NS)) == 1, '标题重复'
        assert saved.xpath('./c:chart/c:title//a:t/text()', namespaces=NS) == [TITLE], '标题未落盘'
        assert len(saved.xpath('.//c:barChart/c:ser', namespaces=NS)) == 1, '系列重复'
        colors = saved.xpath('.//c:barChart/c:ser/c:spPr//a:srgbClr/@val', namespaces=NS)
        assert colors == ['2F9E6E', '2F9E6E'], colors
        assert saved.xpath('.//c:barChart/c:dLbls/c:showVal/@val', namespaces=NS) == ['1'], '标签未落盘'
        assert len(saved.xpath('.//c:barChart/c:dLbls', namespaces=NS)) == 1, '标签重复'
        assert VENDOR.encode() in after.read(PART), '外来扩展词法变化'
        for root in [original, saved]:
            for node in root.xpath('./c:chart/c:title | .//c:barChart/c:ser/c:spPr | .//c:barChart/c:dLbls', namespaces=NS): node.getparent().remove(node)
        assert semantic(original) == semantic(saved), '非目标图表语义变化'
        expected_prefix = 'chart' if directory.name == 'arbitrary' else None
        assert saved.prefix == expected_prefix, '来源主前缀身份变化'
        preserved = [{'part': name, 'sha256': digest(after.read(name))} for name in names if name != PART]
    book = load_workbook(output, data_only=False)
    assert book['Summary']['D4'].value == '=SUM(B2:B3)' and book['Keep']['A1'].value == 'Untouched sheet'
    assert book['Summary']['B2'].number_format == '0.00'
    assert book['Summary']['B2'].value == 10 and book['Summary']['B2'].data_type == 'n'
    return {'ok': True, 'sourceSha256': digest(source_bytes), 'downloadedSha256': digest(saved_bytes), 'size': len(saved_bytes), 'changedParts': changed, 'preservedParts': preserved, 'singleTitle': TITLE, 'seriesColors': colors, 'dataLabels': True, 'numericSource': {'cell': 'Summary!B2', 'raw': 10, 'numberFormat': '0.00'}, 'nonTargetChartSemanticsPreserved': True, 'namespaceUriCorrect': True, 'mainChartPrefix': expected_prefix}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--directory', type=Path, required=True); parser.add_argument('--create', action='store_true')
    parser.add_argument('--cases', default='default,arbitrary,mixed')
    args = parser.parse_args()
    selected_cases = args.cases.split(',')
    assert selected_cases and len(set(selected_cases)) == len(selected_cases) and all(case in ('default', 'arbitrary', 'mixed') for case in selected_cases)
    result = create_sources(args.directory, selected_cases) if args.create else {case: verify_case(args.directory / case) for case in selected_cases}
    print(json.dumps(result, ensure_ascii=False))
