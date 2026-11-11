"""独立原生宿主与迷你图桥共享严格顶层协议。"""
from unittest.mock import Mock
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree

import pytest

from smart_reporting.report_editor import native_office


def test_native_sparkline_operation_reaches_shared_engine(monkeypatch):
    operation = {
        'kind': 'appendSheetSparklines', 'sheetName': '中文 Sheet',
        'groups': [{'type': 'line', 'cells': [{'cell': 'D2', 'sourceRef': "'中文 Sheet'!$A$2:$C$2"}]}],
    }
    patch = Mock(return_value=b'edited')
    monkeypatch.setattr(native_office, 'patch_workbook', patch)
    assert native_office.patch_office('xlsx', b'source', [operation]) == b'edited'
    patch.assert_called_once_with(b'source', [operation])


@pytest.mark.parametrize('extra', [{'unexpected': True}, {'sourcePath': '/tmp/other.xlsx'}])
def test_native_sparkline_rejects_unknown_outer_fields(monkeypatch, extra):
    patch = Mock()
    monkeypatch.setattr(native_office, 'patch_workbook', patch)
    with pytest.raises(ValueError):
        native_office.patch_office('xlsx', b'source', [{
            'kind': 'appendSheetSparklines', 'sheetName': 'Sheet', 'groups': [], **extra,
        }])
    patch.assert_not_called()


def test_real_native_sparkline_save_preserves_cells_and_writes_extension():
    from openpyxl import Workbook
    workbook = Workbook()
    workbook.active.title = '中文 Sheet'
    workbook.active.append([1, -2, 3])
    stream = BytesIO()
    workbook.save(stream)
    source = stream.getvalue()
    edited = native_office.patch_office('xlsx', source, [{
        'kind': 'appendSheetSparklines', 'sheetName': '中文 Sheet',
        'groups': [{'type': 'column', 'cells': [{'cell': 'D1', 'sourceRef': "'中文 Sheet'!$A$1:$C$1"}]}],
    }])
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(edited)) as after:
        changed = [name for name in before.namelist() if before.read(name) != after.read(name)]
        assert changed == ['xl/worksheets/sheet1.xml']
        root = ElementTree.fromstring(after.read(changed[0]))
    namespaces = {
        's': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
        'x': 'http://schemas.microsoft.com/office/spreadsheetml/2009/9/main',
        'm': 'http://schemas.microsoft.com/office/excel/2006/main',
    }
    group = root.find('s:extLst/s:ext/x:sparklineGroups/x:sparklineGroup', namespaces)
    assert group is not None and group.attrib['type'] == 'column'
    assert group.find('.//m:f', namespaces).text == "'中文 Sheet'!$A$1:$C$1"
    assert group.find('.//m:sqref', namespaces).text == 'D1'
