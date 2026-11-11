from io import BytesIO
import re
from zipfile import ZipFile, ZIP_DEFLATED

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference

from smart_reporting.report_editor.native_office import patch_office


def _source(namespace='default', formula="'Source'!$A$1:$A$5"):
    book = Workbook()
    book.active.title = 'Source'
    other = book.create_sheet('Other')
    for row in range(1, 6):
        book['Source'].cell(row, 1, row)
        other.cell(row, 2, row)
    chart = BarChart()
    chart.add_data(Reference(book['Source'], min_col=1, min_row=1, max_row=5))
    other.add_chart(chart, 'D2')
    stream = BytesIO()
    book.save(stream)
    result = BytesIO()
    with ZipFile(BytesIO(stream.getvalue())) as before, ZipFile(result, 'w', ZIP_DEFLATED) as after:
        for entry in before.infolist():
            data = before.read(entry.filename)
            if entry.filename == 'xl/charts/chart1.xml':
                xml = data.decode().replace("'Source'!$A$1:$A$5", formula)
                if namespace != 'default':
                    uri = 'urn:foreign' if namespace == 'foreign' else 'http://schemas.openxmlformats.org/drawingml/2006/chart'
                    prefix = 'c' if namespace == 'foreign' else 'q'
                    xml = xml.replace('xmlns="http://schemas.openxmlformats.org/drawingml/2006/chart"', f'xmlns:{prefix}="{uri}"')
                    xml = re.sub(r'<(/?)([A-Za-z][\w]*)(?=[\s/>])', rf'<\1{prefix}:\2', xml)
                data = xml.encode()
            after.writestr(entry, data)
    return result.getvalue()


def _removal():
    return {'kind': 'applySheetEdits', 'plan': {
        'renames': [], 'additions': [], 'removals': ['Source'], 'order': ['Other'],
    }}


@pytest.mark.parametrize('namespace', ['default', 'alias'])
@pytest.mark.parametrize('formula', ["'Source'!$A$1:$A$5", 'source!a1:a5'])
def test_native_chart_namespace_reference_refuses_sheet_removal(namespace, formula):
    with pytest.raises(ValueError, match='native_office_operations_invalid'):
        patch_office('xlsx', _source(namespace, formula), [_removal()])


@pytest.mark.parametrize('namespace,formula', [
    ('default', 'Other!$B$1:$B$5'),
    ('default', '&quot;Source!A1&quot;'),
    ('default', '[book.xlsx]Source!A1:A5'),
    ('alias', "'[book.xlsx]Source'!A1:A5"),
    ('foreign', 'Source!A1:A5'),
])
def test_native_chart_safe_formula_or_foreign_namespace_preserves_chart_xml(namespace, formula):
    source = _source(namespace, formula)
    changed = patch_office('xlsx', source, [_removal()])
    # foreign chart deliberately is not an Excel chart; inspect package identity directly.
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(changed)) as after:
        assert b'name="Source"' not in after.read('xl/workbook.xml')
        for path in ['xl/charts/chart1.xml', 'xl/styles.xml', 'xl/worksheets/sheet2.xml',
                     'xl/drawings/drawing1.xml', 'xl/drawings/_rels/drawing1.xml.rels']:
            assert after.read(path) == before.read(path)
    if namespace != 'foreign':
        book = load_workbook(BytesIO(changed))
        assert book.sheetnames == ['Other']
        assert book['Other']['B3'].value == 3
