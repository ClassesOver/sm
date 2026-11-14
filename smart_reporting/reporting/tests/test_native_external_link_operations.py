from unittest.mock import Mock

import pytest


@pytest.mark.parametrize('operation', [
    {'kind': 'retargetExternalLink', 'index': 1, 'expectedTarget': 'old.xlsx', 'target': 'new.xlsx'},
    {'kind': 'breakExternalLink', 'index': 1, 'expectedTarget': 'old.xlsx'},
    {'kind': 'updateExternalLinkCaches', 'updates': []},
    {'kind': 'bindExternalLinkSource', 'index': 1, 'expectedTarget': 'old.xlsx', 'name': 'old.xlsx', 'mediaType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'size': 1, 'sha256': 'a' * 64, 'bytesBase64': 'AAAA'},
])
def test_native_xlsx_external_operations_delegate_to_shared_engine(operation, monkeypatch):
    from smart_reporting.report_editor import native_office
    from smart_reporting.reporting.tests.test_native_office import workbook_bytes
    content = workbook_bytes()
    patch = Mock(return_value=b'edited')
    monkeypatch.setattr(native_office, 'patch_workbook', patch)
    assert native_office.patch_office('xlsx', content, [operation]) == b'edited'
    patch.assert_called_once()


def test_native_xlsx_external_operations_cross_real_delivery_bridge():
    """独立 XLSX 夹具经真实 Python/CLI 链路覆盖四种操作，不 mock 桥接。"""
    import base64
    import hashlib
    from io import BytesIO
    from zipfile import ZIP_DEFLATED, ZipFile

    from lxml import etree
    from openpyxl import Workbook, load_workbook

    from smart_reporting.report_editor.native_office import patch_office

    spreadsheet = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    relationship = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    package = 'http://schemas.openxmlformats.org/package/2006/relationships'
    book = Workbook()
    book.active.title = 'Report'
    book.active['A1'] = 6
    book.create_sheet('Unrelated')['A1'] = '保持不变'
    stream = BytesIO()
    book.save(stream)
    with ZipFile(BytesIO(stream.getvalue())) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    root = etree.fromstring(parts['xl/workbook.xml'])
    references = etree.SubElement(root, f'{{{spreadsheet}}}externalReferences')
    etree.SubElement(references, f'{{{spreadsheet}}}externalReference', {f'{{{relationship}}}id': 'ext1'})
    parts['xl/workbook.xml'] = etree.tostring(root)
    root = etree.fromstring(parts['xl/_rels/workbook.xml.rels'])
    etree.SubElement(root, f'{{{package}}}Relationship', Id='ext1', Type=f'{relationship}/externalLink', Target='externalLinks/externalLink1.xml')
    parts['xl/_rels/workbook.xml.rels'] = etree.tostring(root)
    parts['xl/externalLinks/externalLink1.xml'] = (f'<externalLink xmlns="{spreadsheet}" xmlns:r="{relationship}"><externalBook r:id="rId1"><sheetNames><sheetName val="Data"/></sheetNames></externalBook></externalLink>').encode()
    parts['xl/externalLinks/_rels/externalLink1.xml.rels'] = (f'<Relationships xmlns="{package}"><Relationship Id="rId1" Type="{relationship}/externalLinkPath" Target="old.xlsx" TargetMode="External"/></Relationships>').encode()
    parts['xl/worksheets/sheet1.xml'] = (f'<worksheet xmlns="{spreadsheet}"><sheetData><row r="1"><c r="A1"><f>[1]Data!A1*2</f><v>6</v></c></row></sheetData></worksheet>').encode()
    stream = BytesIO()
    with ZipFile(stream, 'w', ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    source = Workbook()
    source.active.title = 'Data'
    source.active['A1'] = 12
    source_stream = BytesIO()
    source.save(source_stream)
    source_bytes = source_stream.getvalue()
    result = patch_office('xlsx', stream.getvalue(), [
        {'kind': 'retargetExternalLink', 'index': 1, 'expectedTarget': 'old.xlsx', 'target': 'new.xlsx'},
        {'kind': 'bindExternalLinkSource', 'index': 1, 'expectedTarget': 'new.xlsx', 'name': 'new.xlsx', 'mediaType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'size': len(source_bytes), 'sha256': hashlib.sha256(source_bytes).hexdigest(), 'bytesBase64': base64.b64encode(source_bytes).decode()},
        {'kind': 'updateExternalLinkCaches', 'updates': [{'sheetName': 'Report', 'address': 'A1', 'formula': '[1]Data!A1*2', 'value': 24}]},
        {'kind': 'breakExternalLink', 'index': 1, 'expectedTarget': 'new.xlsx'},
    ])
    with ZipFile(BytesIO(result)) as archive:
        assert 'xl/externalLinks/externalLink1.xml' not in archive.namelist()
        assert archive.read('xl/worksheets/sheet2.xml') == parts['xl/worksheets/sheet2.xml']
        cell = etree.fromstring(archive.read('xl/worksheets/sheet1.xml')).find(f'.//{{{spreadsheet}}}c')
        assert cell.find(f'{{{spreadsheet}}}f') is None
        assert cell.findtext(f'{{{spreadsheet}}}v') == '24'
    reopened = load_workbook(BytesIO(result), data_only=True)
    assert reopened['Report']['A1'].value == 24
    assert reopened['Unrelated']['A1'].value == '保持不变'
