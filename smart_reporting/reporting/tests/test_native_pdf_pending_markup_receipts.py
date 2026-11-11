"""新增标注回执不能调换原草稿归属或借用其它实际对象身份。"""

from copy import deepcopy

import pytest

from smart_reporting.report_editor.native_pdf_review_ai import NativePDFReviewReader
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_review_ai_tasks import (
    pdf_sample as pdf_sample,
)
from smart_reporting.reporting.tests.test_native_pdf_review_ai_tasks import (
    review_sample as review_sample,
)


@pytest.mark.anyio
async def test_pending_markup_receipt_rejects_wrong_identity_and_swapped_operation(review_sample):
    editor, context, _, _, source = review_sample
    page_id = inspect_pdf(source)['pages'][0]['pageId']
    base = [{'kind': 'addMarkup', 'pageId': page_id, 'markupType': 'highlight',
             'quads': [[30, top, 140, top, 30, top - 15, 140, top - 15]], 'color': [1, 0.87, 0.35]}
            for top in [240, 190]]
    receipt = await editor.preview_file(context, expected_sha256=context.source_file.sha256, operations=base)
    reader = await NativePDFReviewReader.from_bytes(context, source, operations=base, draft_receipt=receipt)
    assert len(reader.projection['pendingMarkupMapping']) == 2
    for fault in ['index', 'duplicate', 'hash', 'reference', 'page', 'swapped']:
        forged = deepcopy(receipt)
        mapping = forged['pendingMarkupMapping'][0]
        if fault == 'index':
            mapping['operationIndex'] = 99
        elif fault == 'duplicate':
            forged['pendingMarkupMapping'][1] = deepcopy(mapping)
        elif fault == 'hash':
            mapping['expectedAnnotationSha256'] = '0' * 64
        elif fault == 'reference':
            mapping['sourceRef'] = '999 0 R'
        elif fault == 'page':
            mapping['effectivePageId'] = 'foreign-page'
        else:
            forged['pendingMarkupMapping'][0]['operationIndex'] = 1
            forged['pendingMarkupMapping'][1]['operationIndex'] = 0
        with pytest.raises(ReportingError):
            reader._bind_projection(forged)


@pytest.mark.anyio
async def test_identical_pending_markup_cannot_claim_another_append_slot(review_sample):
    editor, context, _, _, source = review_sample
    page_id = inspect_pdf(source)['pages'][0]['pageId']
    mark = {'kind': 'addMarkup', 'pageId': page_id, 'markupType': 'highlight',
            'quads': [[30, 240, 140, 240, 30, 225, 140, 225]], 'color': [1, 0.87, 0.35]}
    receipt = await editor.preview_file(context, expected_sha256=context.source_file.sha256,
                                        operations=[mark, deepcopy(mark)])
    reader = await NativePDFReviewReader.from_bytes(context, source, operations=[mark, deepcopy(mark)], draft_receipt=receipt)
    forged = deepcopy(receipt)
    # 仅保留第二个真实标注，却声称它来自第一个草稿操作；内容/坐标完全相同。
    forged['pendingMarkupMapping'] = [deepcopy(receipt['pendingMarkupMapping'][1])]
    forged['pendingMarkupMapping'][0]['operationIndex'] = 0
    with pytest.raises(ReportingError):
        reader._bind_projection(forged)
