from io import BytesIO
from pathlib import Path
import subprocess
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook

from smart_reporting.report_editor.native_office import patch_office
from smart_reporting.reporting.delivery import xlsx
from smart_reporting.reporting.tests.test_workbook_chart_sheet_removal import _source


@pytest.fixture(autouse=True)
def _source_bridge(monkeypatch):
    # 直接校验本轮源码，避免读取 root 尚未统一重建的 dist。
    root = Path(__file__).resolve().parents[1] / 'workbook_engine'
    def run(_engine, script, request_path, **_kwargs):
        return subprocess.run([str(root / 'node_modules/.bin/tsx'),
                               str(root / 'bridge' / f'{script}.ts'), str(request_path)],
                              cwd=root, capture_output=True, text=True, timeout=120)
    monkeypatch.setattr(xlsx, 'run_bridge', run)


def _rename():
    return {'kind': 'applySheetEdits', 'plan': {
        'renames': [{'sheetName': 'Source', 'newName': "New & O'Brien"}],
        'additions': [], 'removals': [], 'order': ["New & O'Brien", 'Other'],
    }}


@pytest.mark.parametrize('namespace', ['default', 'alias'])
@pytest.mark.parametrize('formula', ["'Source'!$A$1:$A$5", '<![CDATA[Source!$A$1:$A$5]]>'])
def test_native_chart_sheet_rename_updates_namespace_formula_and_preserves_package(namespace, formula):
    source = _source(namespace, formula)
    changed = patch_office('xlsx', source, [_rename()])
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(changed)) as after:
        old_xml = before.read('xl/charts/chart1.xml').decode()
        new_xml = after.read('xl/charts/chart1.xml').decode()
        assert new_xml == old_xml.replace(formula, "'New &amp; O''Brien'!$A$1:$A$5")
        parsed = ET.fromstring(new_xml)
        assert [node.text for node in parsed.iter('{http://schemas.openxmlformats.org/drawingml/2006/chart}f')] == ["'New & O''Brien'!$A$1:$A$5"]
        for path in ['xl/styles.xml', 'xl/worksheets/sheet2.xml', 'xl/drawings/drawing1.xml', 'xl/drawings/_rels/drawing1.xml.rels']:
            assert after.read(path) == before.read(path)
    book = load_workbook(BytesIO(changed))
    assert book.sheetnames == ["New & O'Brien", 'Other']
    assert book['Other']._charts[0].series[0].val.numRef.f == "'New & O''Brien'!$A$1:$A$5"


def test_native_chart_sheet_rename_preserves_foreign_c_prefix():
    source = _source('foreign', 'Source!A1:A5')
    changed = patch_office('xlsx', source, [_rename()])
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(changed)) as after:
        assert after.read('xl/charts/chart1.xml') == before.read('xl/charts/chart1.xml')
