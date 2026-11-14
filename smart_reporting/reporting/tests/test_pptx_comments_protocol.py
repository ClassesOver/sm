"""经典批注协议：来源身份与作者由宿主控制，复用原生编辑链。"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.native_office import _pptx_arguments
from smart_reporting.report_editor.pptx_engine import PptxEngine

ADD = {'slideIndex': 0, 'kind': 'add', 'clientId': 'comment-1', 'text': ' 保留中文😀 & <文字>\n '}
DELETE = {'slideIndex': 1, 'kind': 'delete', 'authorId': 0, 'idx': 1}


def test_comment_edits_forward_exact_records_without_changing_input():
    records = [deepcopy(ADD), deepcopy(DELETE)]
    original = deepcopy(records)
    arguments = _pptx_arguments({'kind': 'editSlides', 'commentEdits': records})
    assert arguments['comment_edits'] == original
    assert records == original


@pytest.mark.parametrize('records', [None, {}, [True], [{**ADD, 'slideIndex': True}],
    [{**ADD, 'text': ' \n '}], [{**ADD, 'text': '\x00'}], [{**ADD, 'text': '\ud800'}],
    [{**ADD, 'text': '😀' * 5001}], [{**ADD, 'clientId': 'bad.id'}], [{**ADD, 'author': '冒认作者'}],
    [{**ADD, 'kind': 'reply'}], [{**DELETE, 'authorId': True}], [{**DELETE, 'idx': -1}],
    [{**DELETE, 'idx': 2**53}], [{**DELETE, 'text': '额外字段'}], [ADD, ADD], [DELETE, DELETE],
    [ADD] * 501])
def test_invalid_comment_records_are_rejected_before_bridge(records):
    with pytest.raises(ValueError, match='native_office_operations_invalid'):
        _pptx_arguments({'kind': 'editSlides', 'commentEdits': records})


def test_comment_delete_must_identify_author_and_index_and_source_slide():
    records = [DELETE, {**DELETE, 'authorId': 1}, {**DELETE, 'slideIndex': 2}]
    assert _pptx_arguments({'kind': 'editSlides', 'commentEdits': records})['comment_edits'] == records


def test_comment_changes_cannot_reference_a_deleted_source_slide():
    base = {'kind': 'editSlides', 'deletedSlides': [0], 'order': [1]}
    assert _pptx_arguments(base)['deleted_slides'] == [0]
    with pytest.raises(ValueError, match='native_office_operations_invalid'):
        _pptx_arguments({**base, 'commentEdits': [ADD]})


def test_external_client_cannot_set_host_comment_author():
    with pytest.raises(ValueError, match='native_office_operations_invalid'):
        _pptx_arguments({'kind': 'editSlides', 'commentEdits': [ADD], 'commentAuthor': '管理员'})


def test_python_transport_injects_fixed_host_author_for_adds(monkeypatch):
    captured = []

    def bridge(engine, name, request_path):
        request = json.loads(Path(request_path).read_text())
        captured.append((engine, name, request))
        Path(request['output']).write_bytes(b'protocol-test-output')
        return SimpleNamespace(returncode=0, stderr='', stdout='{"issues":[]}')

    monkeypatch.setattr('smart_reporting.report_editor.pptx_engine.run_bridge', bridge)
    result = PptxEngine._run_engine(b'protocol-test-source', 'edit', comment_edits=[ADD])
    assert result['bytes'] == b'protocol-test-output'
    engine, name, request = captured[0]
    assert (engine, name) == ('slides', 'edit-pptx')
    assert request['commentEdits'] == [ADD]
    assert request['commentAuthor'] == '用户'


def test_ai_candidate_keeps_manual_comment_edits_and_original_base():
    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
    base = [{'kind': 'editSlides', 'commentEdits': [ADD, DELETE], 'order': [1, 0]}]
    original = deepcopy(base)
    candidate = [{'kind': 'editSlides', 'edits': [{'slideIndex': 1, 'elementId': 'title', 'text': 'AI标题'}]}]
    combined = NativeSlidesAIService._combined_operations(None, base, candidate)
    assert combined[0]['commentEdits'] == original[0]['commentEdits']
    assert combined[0]['order'] == original[0]['order']
    assert base == original


def test_comment_text_uses_ecma_whitespace_like_bridge_and_frontend():
    with pytest.raises(ValueError, match='native_office_operations_invalid'):
        _pptx_arguments({'kind': 'editSlides', 'commentEdits': [{**ADD, 'text': '\ufeff'}]})
    # U+0085 是合法 XML 字符，不属于 JavaScript trim 的空白集合。
    records = [{**ADD, 'text': '\x85'}]
    assert _pptx_arguments({'kind': 'editSlides', 'commentEdits': records})['comment_edits'] == records
