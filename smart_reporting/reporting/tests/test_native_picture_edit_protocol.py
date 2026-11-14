from copy import deepcopy

import pytest

from smart_reporting.report_editor import native_office


def operation(geometry):
    return dict(kind='editPicture', sheetName='Report', sourceIdentity='a' * 64,
                drawingPart='xl/drawings/drawing1.xml', pictureId='2', mediaSha256='b' * 64,
                before=dict(row=1, column=2, rowOffsetPx=3, columnOffsetPx=4, widthPx=120, heightPx=80),
                geometry=geometry)


@pytest.mark.parametrize('geometry', [None, dict(row=3, column=4, rowOffsetPx=5, columnOffsetPx=6, widthPx=240, heightPx=160)])
def test_native_picture_edit_shapes_reach_existing_engine_without_rewriting_input(monkeypatch, geometry):
    request = operation(geometry)
    before = deepcopy(request)
    received = []

    def engine(content, operations):
        received.append((content, deepcopy(operations)))
        return b'engine-result'

    monkeypatch.setattr(native_office, 'patch_workbook', engine)
    assert native_office.patch_office('xlsx', b'source', [request]) == b'engine-result'
    assert request == before
    assert received == [(b'source', [before])]


@pytest.mark.parametrize('change', ['missing_geometry', 'extra_path'])
def test_native_picture_edit_gateway_rejects_incomplete_or_extra_fields_before_engine(monkeypatch, change):
    request = operation(None)
    if change == 'missing_geometry':
        del request['geometry']
    else:
        request['path'] = '/tmp/foreign.png'
    received = []
    monkeypatch.setattr(native_office, 'patch_workbook', lambda *args: received.append(args))
    with pytest.raises(ValueError, match='native_office_operations_invalid'):
        native_office.patch_office('xlsx', b'source', [request])
    assert received == []


@pytest.mark.parametrize('geometry', [None, dict(row=3, column=4, rowOffsetPx=5, columnOffsetPx=6, widthPx=240, heightPx=160)])
def test_native_picture_edit_crosses_both_python_protocol_boundaries(monkeypatch, geometry):
    from pathlib import Path
    from smart_reporting.reporting.delivery import xlsx

    request = operation(geometry)
    received = []

    def invoke(payload):
        received.append(deepcopy(payload['operations']))
        Path(payload['output']).write_bytes(b'bridge-result')
        return {}

    monkeypatch.setattr(xlsx, '_invoke', invoke)
    assert native_office.patch_office('xlsx', b'source', [request]) == b'bridge-result'
    assert received == [[request]]
