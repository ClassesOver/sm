"""PPTX链接与内部对象剪贴板的宿主协议，不接受XML或外部文件身份。"""
import copy

import pytest

from smart_reporting.report_editor.native_office import _pptx_arguments


@pytest.mark.parametrize('target', [{'kind': 'url', 'url': 'https://example.test/a?x=1&y=2'}, {'kind': 'url', 'url': 'mailto:team@example.test'}, {'kind': 'slide', 'slideIndex': 1}, None])
def test_link_protocol_forwards_only_supported_targets(target):
    records = [{'slideIndex': 0, 'elementId': 'a', 'target': target}]
    assert _pptx_arguments({'kind': 'editSlides', 'linkEdits': records})['link_edits'] == records


@pytest.mark.parametrize('target', [{'kind': 'url', 'url': 'javascript:alert(1)'}, {'kind': 'url', 'url': 'data:text/plain,no'}, {'kind': 'url', 'url': 'file:///tmp/a'}, {'kind': 'url', 'url': 'https://example.test/\nq'}, {'kind': 'url', 'url': ''}, {'kind': 'slide', 'slideIndex': True}, {'kind': 'slide', 'slideIndex': -1}, {'kind': 'action', 'action': 'next'}, {'kind': 'url', 'url': 'https://example.test', 'xml': '<a/>'}])
def test_link_protocol_rejects_invalid_targets(target):
    with pytest.raises(ValueError):
        _pptx_arguments({'kind': 'editSlides', 'linkEdits': [{'slideIndex': 0, 'elementId': 'a', 'target': target}]})


def test_clipboard_protocol_forwards_saved_source_references():
    records = [{'sourceSlideIndex': 0, 'elementIds': ['a', 'b'], 'slideIndex': 1, 'dx': 20, 'dy': 20}]
    assert _pptx_arguments({'kind': 'editSlides', 'clipboardPastes': records})['clipboard_pastes'] == records


@pytest.mark.parametrize('patch', [{'sourceSlideIndex': True}, {'elementIds': []}, {'elementIds': ['a', 'a']}, {'elementIds': ['']}, {'elementIds': [1]}, {'dx': float('nan')}, {'dy': True}, {'dx': 100001}, {'xml': '<p:sp/>'}, {'rels': []}, {'parts': {}}, {'documentId': 'other'}])
def test_clipboard_protocol_rejects_invalid_or_raw_payloads(patch):
    item = {'sourceSlideIndex': 0, 'elementIds': ['a'], 'slideIndex': 1, 'dx': 20, 'dy': 20} | patch
    with pytest.raises(ValueError):
        _pptx_arguments({'kind': 'editSlides', 'clipboardPastes': [item]})


@pytest.mark.parametrize('field,item', [('linkEdits', {'slideIndex': 0, 'elementId': 'a', 'target': None}), ('clipboardPastes', {'sourceSlideIndex': 0, 'elementIds': ['a'], 'slideIndex': 1, 'dx': 0, 'dy': 0})])
def test_new_operations_are_bounded_and_do_not_mutate_request(field, item):
    records = [copy.deepcopy(item) for _ in range(51)]
    operation = {'kind': 'editSlides', field: records}
    snapshot = copy.deepcopy(operation)
    with pytest.raises(ValueError):
        _pptx_arguments(operation)
    assert operation == snapshot
