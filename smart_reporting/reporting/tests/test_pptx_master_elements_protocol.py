"""母版文字框结构改动沿既有 editSlides 传递，身份由实际包再次核验。"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.native_office import _pptx_arguments
from smart_reporting.report_editor.slides import ReportSlidesEditorService

ADD = {'kind': 'addTextBox', 'partPath': 'ppt/slideMasters/slideMaster1.xml', 'clientId': 'box-1',
       'text': '新品牌 <&>😀\r\n第二行', 'box': {'x': 48, 'y': 500, 'width': 480, 'height': 96}}
DELETE = {'kind': 'delete', 'partPath': 'ppt/slideLayouts/slideLayout1.xml', 'spid': 7}
TRANSFORM = {'kind': 'setTransform', 'partPath': 'ppt/slideMasters/slideMaster1.xml', 'spid': 8,
             'box': {'x': 96, 'y': 120, 'width': 400, 'height': 88, 'rotationDeg': 12.5}}
STROKE = {'kind': 'setStroke', 'partPath': 'ppt/slideMasters/slideMaster1.xml', 'spid': 9,
          'stroke': {'color': '#12AB34', 'widthPt': 1}}


def test_master_elements_forward_without_mutating_the_original_draft():
    operation = {'kind': 'editSlides', 'masterElementEdits': [ADD, DELETE, TRANSFORM, STROKE]}
    original = copy.deepcopy(operation)
    assert _pptx_arguments(operation)['master_element_edits'] == [{**ADD, 'text': ADD['text'].replace('\r\n', '\n')}, DELETE, TRANSFORM, STROKE]
    assert operation == original
    assert _pptx_arguments({'kind': 'editSlides'})['master_element_edits'] == []


def test_python_transport_forwards_master_elements_to_existing_bridge(monkeypatch):
    captured = []

    def bridge(engine, name, request_path):
        request = json.loads(Path(request_path).read_text())
        captured.append((engine, name, request))
        Path(request['output']).write_bytes(b'protocol-test-output')
        return SimpleNamespace(returncode=0, stderr='', stdout='{"issues":[]}')

    monkeypatch.setattr('smart_reporting.report_editor.pptx_engine.run_bridge', bridge)
    result = ReportSlidesEditorService._run_engine(b'protocol-test-source', 'edit', master_element_edits=[ADD, DELETE])
    assert result['bytes'] == b'protocol-test-output'
    engine, name, request = captured[0]
    assert (engine, name) == ('slides', 'edit-pptx')
    assert request['masterElementEdits'] == [ADD, DELETE]


@pytest.mark.parametrize('patch', [
    {'kind': 'addMaster'}, {'partPath': 'ppt/slides/slide1.xml'}, {'partPath': '../slideMaster1.xml'},
    {'clientId': ''}, {'clientId': 'a/b'}, {'text': '\ud800'}, {'text': '\0'}, {'text': 'x' * 20001},
    {'box': {'x': -1, 'y': 0, 'width': 10, 'height': 10}},
    {'box': {'x': 0, 'y': True, 'width': 10, 'height': 10}},
    {'box': {'x': 0, 'y': 0, 'width': 0, 'height': 10}},
    {'box': {'x': 0, 'y': 0, 'width': float('nan'), 'height': 10}}, {'xml': '<p:sp/>'},
    {'box': {'x': 0, 'y': 0, 'width': 10**500, 'height': 10}},
    {'kind': 'setTransform', 'spid': 8, 'box': {'x': 0, 'y': 0, 'width': 10, 'height': 10, 'rotationDeg': 361}},
    {'kind': 'setTransform', 'spid': 8, 'box': {'x': 0, 'y': 0, 'width': 0, 'height': 10, 'rotationDeg': 0}},
    {'kind': 'setTransform', 'spid': 8, 'box': {'x': 0, 'y': 0, 'width': 10, 'height': 10, 'rotationDeg': True}},
    {'kind': 'setStroke', 'spid': 9, 'stroke': {'color': 'red', 'widthPt': 1}},
    {'kind': 'setStroke', 'spid': 9, 'stroke': {'color': '#112233', 'widthPt': 2}},
    {'kind': 'setStroke', 'spid': 9, 'stroke': {'color': '#112233', 'widthPt': True}},
])
def test_master_add_rejects_bad_shape_and_client_xml(patch):
    with pytest.raises(ValueError):
        _pptx_arguments({'kind': 'editSlides', 'masterElementEdits': [{**ADD, **patch}]})


@pytest.mark.parametrize('records', [[DELETE, DELETE], [ADD, ADD], [{**DELETE, 'spid': True}],
                                   [{**DELETE, 'spid': 4294967296}], [DELETE] * 201,
                                   [{**ADD, 'clientId': f'b-{i}', 'text': 'x' * 20000} for i in range(11)]])
def test_master_structure_duplicates_and_budgets_are_rejected(records):
    with pytest.raises(ValueError):
        _pptx_arguments({'kind': 'editSlides', 'masterElementEdits': records})
