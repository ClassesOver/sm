"""演讲者备注只接受来源页与纯文本，不接受原始包数据。"""
import copy

import pytest

from smart_reporting.report_editor.native_office import _pptx_arguments


@pytest.mark.parametrize(('text', 'expected'), [('甲\r\n乙\r\n\r\n', '甲\n乙'), ('  甲\n\n乙  ', '  甲\n\n乙  '), ('', ''), ('\n\n', ''), ('中文😀\t& $& < > &#10;', '中文😀\t& $& < > &#10;')])
def test_notes_protocol_forwards_canonical_plain_text(text, expected):
    operation = {'kind': 'editSlides', 'notesEdits': [{'slideIndex': 0, 'text': text}]}
    snapshot = copy.deepcopy(operation)
    assert _pptx_arguments(operation)['notes_edits'] == [{'slideIndex': 0, 'text': expected}]
    assert operation == snapshot


@pytest.mark.parametrize('patch', [{'slideIndex': True}, {'slideIndex': -1}, {'text': 1}, {'text': '\0'}, {'text': '\x0b'}, {'text': '\ud800'}, {'text': '\udfff'}, {'text': '\ufffe'}, {'text': '\uffff'}, {'xml': '<a:p/>'}, {'parts': {}}, {'text': '😀' * 10001}, {'text': '\n' * 20001}])
def test_notes_protocol_rejects_invalid_fields_or_raw_limits(patch):
    with pytest.raises(ValueError):
        _pptx_arguments({'kind': 'editSlides', 'notesEdits': [{'slideIndex': 0, 'text': '甲'} | patch]})


@pytest.mark.parametrize('records', [[{'slideIndex': 0, 'text': '甲'}, {'slideIndex': 0, 'text': '乙'}], [{'slideIndex': i, 'text': ''} for i in range(201)], [{'slideIndex': i, 'text': '😀' * 10000} for i in range(11)]])
def test_notes_protocol_limits_raw_total_unique_sources_and_records(records):
    with pytest.raises(ValueError):
        _pptx_arguments({'kind': 'editSlides', 'notesEdits': records})


def test_notes_protocol_rejects_deleted_or_duplicated_source():
    for extra in [{'deletedSlides': [0]}, {'newSlides': [{'duplicateOf': 0}], 'order': [0, 1]}]:
        with pytest.raises(ValueError):
            _pptx_arguments({'kind': 'editSlides', 'notesEdits': [{'slideIndex': 0, 'text': '甲'}]} | extra)
