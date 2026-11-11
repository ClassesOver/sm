"""真实 OOXML 批注读取、源身份增删与既有非批注内容保全。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from pptx import Presentation

from smart_reporting.report_editor.native_office import inspect_office, patch_office
from smart_reporting.reporting.tests.pptx_comments_fixture import COMMENTS, TEXTS, create, readback, verify


def test_inspect_classic_comments_matches_independent_xml_readback():
    source = create()
    model, independent = inspect_office('pptx', source), readback(source)
    for slide, actual in zip(model['slides'], independent['slides'], strict=True):
        assert slide['comments']['readOnlyReason'] is None
        assert [{key: item[key] for key in ('authorId', 'idx', 'author', 'text')} for item in slide['comments']['items']] == actual['comments']


def test_add_and_exact_delete_preserve_body_other_author_and_unknown_parts(tmp_path):
    source = create()
    text = '未失焦新批注😀 <&> "引号"\n保留末尾 '
    updated = patch_office('pptx', source, [{'kind': 'editSlides', 'commentEdits': [
        {'slideIndex': 0, 'kind': 'delete', 'authorId': 0, 'idx': 1},
        {'slideIndex': 1, 'kind': 'delete', 'authorId': 0, 'idx': 2},
        {'slideIndex': 0, 'kind': 'add', 'clientId': 'persist-1', 'text': text},
    ]}])
    result = verify(source, updated, [text])
    assert result['sameIdxOtherAuthorPreserved'] and result['lastCommentPartRelationshipOverrideRemoved']
    assert result['unrelatedPartsByteExact'] and result['pythonPptxBodyUnchanged']
    (tmp_path / 'source.pptx').write_bytes(source)
    (tmp_path / 'comments.pptx').write_bytes(updated)
    assert [item['text'] for item in inspect_office('pptx', updated)['slides'][0]['comments']['items']] == [COMMENTS[0][1][2], text]
    assert inspect_office('pptx', updated)['slides'][1]['comments']['items'] == []


def test_comment_edits_follow_original_page_identity_through_reorder():
    source = create()
    updated = patch_office('pptx', source, [{'kind': 'editSlides', 'order': [1, 0], 'commentEdits': [
        {'slideIndex': 0, 'kind': 'delete', 'authorId': 0, 'idx': 1},
        {'slideIndex': 1, 'kind': 'add', 'clientId': 'reordered-1', 'text': '精确第二来源页'},
    ]}])
    model = inspect_office('pptx', updated)
    assert [item['text'] for item in model['slides'][0]['comments']['items']] == [COMMENTS[1][0][2], '精确第二来源页']
    assert [item['text'] for item in model['slides'][1]['comments']['items']] == [COMMENTS[0][1][2]]
    assert [[shape.text for shape in slide.shapes if shape.has_text_frame] for slide in Presentation(BytesIO(updated)).slides] == [[TEXTS[1]], [TEXTS[0]]]


@pytest.mark.parametrize('variant', ['modern', 'broken'])
def test_unverifiable_comments_only_disable_comment_writes(variant):
    source = create(variant)
    state = inspect_office('pptx', source)['slides'][0]['comments']
    assert state['readOnlyReason']
    with pytest.raises(ValueError):
        patch_office('pptx', source, [{'kind': 'editSlides', 'commentEdits': [
            {'slideIndex': 0, 'kind': 'add', 'clientId': 'refused-1', 'text': '不可写入歧义来源'},
        ]}])
    # 评论来源不足不能禁用其它已授权编辑，也不能遗失原有部件。
    updated = patch_office('pptx', source, [{'kind': 'editSlides', 'hiddenSlides': [{'slideIndex': 1, 'hidden': True}]}])
    assert inspect_office('pptx', updated)['slides'][1]['hidden'] is True
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(updated)) as after:
        assert before.read('custom/preserved.xml') == after.read('custom/preserved.xml')
        for part in before.namelist():
            if part.startswith('ppt/comments/'):
                assert before.read(part) == after.read(part), part


@pytest.mark.parametrize('record', [
    {'slideIndex': 0, 'kind': 'delete', 'authorId': 0, 'idx': 999},
    {'slideIndex': 2, 'kind': 'add', 'clientId': 'new-slide', 'text': '不是原来源'},
])
def test_native_bridge_refuses_missing_source_identity(record):
    with pytest.raises(ValueError):
        patch_office('pptx', create(), [{'kind': 'editSlides', 'commentEdits': [record]}])
