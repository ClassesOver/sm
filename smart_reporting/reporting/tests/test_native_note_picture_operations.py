from unittest.mock import Mock


def test_native_xlsx_note_picture_operation_passes_whitelist(monkeypatch):
    from smart_reporting.report_editor import native_office
    from smart_reporting.reporting.tests.test_native_office import workbook_bytes

    operation = {
        'kind': 'setNotePicture', 'sheetName': 'Sheet', 'row': 0, 'column': 0,
        'sourceIdentity': 'a' * 64,
        'picture': {
            'mediaType': 'image/png', 'bytesBase64': 'AAAA', 'size': 3,
            'sha256': 'b' * 64, 'widthPx': 1, 'heightPx': 1, 'name': 'a.png',
        },
    }
    patch = Mock(return_value=b'edited')
    monkeypatch.setattr(native_office, 'patch_workbook', patch)
    assert native_office.patch_office('xlsx', workbook_bytes(), [operation]) == b'edited'
    patch.assert_called_once()
