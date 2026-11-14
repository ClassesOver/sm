"""母版文字沿 editSlides 协议传递包内身份，不接受任意路径或 XML。"""
import copy

import pytest

from smart_reporting.report_editor.native_office import _pptx_arguments


def test_master_text_protocol_forwards_plain_text_and_preserves_input():
    item = {'partPath': 'ppt/slideMasters/slideMaster1.xml', 'spid': 7, 'text': '甲<&>😀\r\n乙\n'}
    operation = {'kind': 'editSlides', 'masterTextEdits': [item]}
    before = copy.deepcopy(operation)
    assert _pptx_arguments(operation)['master_text_edits'] == [{**item, 'text': '甲<&>😀\n乙\n'}]
    assert operation == before
    assert _pptx_arguments({'kind': 'editSlides'})['master_text_edits'] == []


@pytest.mark.parametrize('patch', [
    {'partPath': '../slideMaster1.xml'}, {'partPath': 'ppt/slides/slide1.xml'},
    {'partPath': 'ppt/slideMasters/../../etc.xml'}, {'partPath': 'ppt/slideMasters/slideMaster1.xml:evil'},
    {'spid': True}, {'spid': -1}, {'spid': 0}, {'spid': 1.5},
    {'text': 1}, {'text': '\0'}, {'text': '\ud800'}, {'text': '\uffff'},
    {'text': 'a' * 20001}, {'xml': '<p:sp/>'}, {'paragraphs': []},
])
def test_master_text_protocol_rejects_invalid_identity_or_payload(patch):
    with pytest.raises(ValueError):
        _pptx_arguments({'kind': 'editSlides', 'masterTextEdits': [
            {'partPath': 'ppt/slideLayouts/slideLayout1.xml', 'spid': 2, 'text': '甲'} | patch,
        ]})


def test_master_text_protocol_rejects_duplicate_and_total_budget():
    item = {'partPath': 'ppt/slideMasters/slideMaster1.xml', 'spid': 7, 'text': 'a'}
    for items in [[item, item], [{**item, 'spid': i + 1} for i in range(201)],
                  [{**item, 'spid': i + 1, 'text': 'a' * 20000} for i in range(11)]]:
        with pytest.raises(ValueError):
            _pptx_arguments({'kind': 'editSlides', 'masterTextEdits': items})
