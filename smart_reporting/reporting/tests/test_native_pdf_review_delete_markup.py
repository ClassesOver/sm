"""批注删除候选只能来自完整读过的可信标注身份。"""

from copy import deepcopy

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_review_ai import review_tools


def tools_with_markups():
    tools = review_tools()
    page = tools.reader.pages[1]
    page['markupReadSafe'] = True
    page['markups'] = [{
        'annotationId': char * 64, 'expectedAnnotationSha256': char * 64,
        'sourceRef': f'{index}R', 'contents': '请删除过期标记', 'markupType': kind,
        'removable': True, 'quads': [[10, 40, 90, 40, 10, 20, 90, 20]],
    } for index, (char, kind) in enumerate([('d', 'highlight'), ('e', 'underline')], 10)]
    from smart_reporting.report_editor.native_pdf_review_ai import NativePDFReviewTools

    return NativePDFReviewTools(tools.reader)


def test_delete_markup_requires_complete_read_and_registers_source_bound_operation():
    tools = tools_with_markups()
    with pytest.raises(ReportingError, match='批注'):
        tools.delete_markup('a' * 64, 2, '删除过期标注', ['d' * 64])
    tools.read_annotations(limit=1)
    with pytest.raises(ReportingError, match='标注'):
        tools.delete_markup('a' * 64, 2, '删除过期标注', ['d' * 64])
    assert tools.operations == []
    tools.read_annotations()
    result = tools.delete_markup('a' * 64, 2, '删除过期标注', ['d' * 64])
    assert result['operationIndices'] == [0]
    assert tools.operations == [{
        'kind': 'removeMarkup', 'pageId': tools.reader.pages[1]['pageId'],
        'annotationId': 'd' * 64, 'expectedAnnotationSha256': 'd' * 64,
    }]
    tools.propose_reply('a' * 64, '已提出删除过期标注候选。')
    assert tools.result('待采纳')['notes'][0]['operationIndices'] == [0]


def test_markup_read_exposes_trusted_location_to_distinguish_same_type_targets():
    tools = tools_with_markups()
    page = tools.reader.pages[1]
    page['markups'][1].update(markupType='highlight', quads=[[20, 80, 100, 80, 20, 60, 100, 60]], color=[0, 1, 0])
    page['textObjects'][0]['rect'] = [10, 20, 90, 40]
    result = tools.read_annotations()
    markups = [item for item in result['annotations'] if item['kind'] == 'markup']
    assert markups[0]['quads'] == page['markups'][0]['quads']
    assert markups[1]['quads'] == page['markups'][1]['quads']
    assert markups[1]['color'] == [0, 1, 0]
    body = tools.read_pages(start_page=2)
    assert body['pages'][0]['textObjects'][0]['rect'] == [10, 20, 90, 40]
    tools.delete_markup('a' * 64, 2, '仅删除第二处高亮', [markups[1]['annotationId']])
    assert tools.operations[0]['annotationId'] == 'e' * 64


@pytest.mark.parametrize('kwargs', [
    {'page_number': 1}, {'markup_ids': ['x' * 64]}, {'markup_ids': []},
    {'markup_ids': ['d' * 64, 'd' * 64]}, {'markup_type': 'unknown'}, {'reason': ''},
])
def test_invalid_markup_deletion_never_registers_partial_operations(kwargs):
    tools = tools_with_markups()
    tools.read_annotations()
    arguments = dict(annotation_id='a' * 64, page_number=2, reason='移除过期标记', markup_ids=['d' * 64])
    arguments.update(kwargs)
    with pytest.raises(ReportingError):
        tools.delete_markup(**arguments)
    assert tools.operations == []


def test_delete_markup_filters_type_and_rejects_repeated_candidate():
    tools = tools_with_markups()
    tools.read_annotations()
    tools.delete_markup('a' * 64, 2, '删除高亮', markup_type='highlight')
    assert [op['annotationId'] for op in tools.operations] == ['d' * 64]
    with pytest.raises(ReportingError):
        tools.delete_markup('a' * 64, 2, '重复删除', ['d' * 64])
    assert len(tools.operations) == 1


def test_delete_markup_can_be_combined_with_text_replacement_in_same_note():
    tools = tools_with_markups()
    tools.read_annotations()
    tools.read_pages(start_page=2)
    tools.delete_markup('a' * 64, 2, '删除过期高亮', ['d' * 64])
    tools.propose_replace_text('a' * 64, 2, 'Revenue is 42.', 'Revenue is 43.', '更正')
    assert [op['kind'] for op in tools.operations] == ['removeMarkup', 'replaceText']
    assert tools.result('组合候选')['notes'][0]['operationIndices'] == [0, 1]


def test_long_markup_contents_must_be_completely_read_before_deletion():
    tools = tools_with_markups()
    tools.reader.pages[1]['markups'][0]['contents'] = '说明' * 3500
    first = tools.read_annotations()
    assert first['next'] is not None
    with pytest.raises(ReportingError, match='完整读取'):
        tools.delete_markup('a' * 64, 2, '移除', ['d' * 64])
    tools.read_annotations(**first['next'])
    tools.delete_markup('a' * 64, 2, '移除', ['d' * 64])
    assert len(tools.operations) == 1


def test_delete_all_is_atomic_when_one_markup_is_readonly():
    tools = tools_with_markups()
    tools.reader.pages[1]['markups'][1]['removable'] = False
    tools.read_annotations()
    with pytest.raises(ReportingError):
        tools.delete_markup('a' * 64, 2, '删除标注')
    assert tools.operations == []


def test_projected_saved_markup_rebinds_only_exact_original_identity():
    tools = tools_with_markups()
    reader = tools.reader
    reader._original_pages = deepcopy(reader.pages)
    original = reader._original_pages[1]
    original['pageId'] = 'source-page'
    reader.projection = {'pageMapping': [
        {'originalPageId': page['pageId'], 'effectivePageId': page['pageId']}
        for page in reader.pages
    ]}
    reader.projection['pageMapping'][1]['originalPageId'] = 'source-page'
    reader.pages[1]['markups'][0]['annotationId'] = 'f' * 64
    tools.read_annotations()
    tools.delete_markup('a' * 64, 2, '移除', ['f' * 64])
    assert tools.operations[0]['pageId'] == 'source-page'
    assert tools.operations[0]['annotationId'] == 'd' * 64
    reader.pages[1]['markups'][1]['sourceRef'] = 'new-ref'
    with pytest.raises(ReportingError, match='来源'):
        tools.delete_markup('a' * 64, 2, '移除', ['e' * 64])
    assert len(tools.operations) == 1
