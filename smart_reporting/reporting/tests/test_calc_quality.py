"""计算引用在质量包中按重算结果与引用句核对，不再一律记为未自动核对。"""

import pytest

from smart_reporting.reporting.tests.test_trace_subject_validate import _make_editor_with_subject
from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle

_SUM = '{{calc:sum(fact-aaaaaaaaaaaaaaaa:periodValues.0,fact-aaaaaaaaaaaaaaaa:periodValues.1):万元}}'
_GROWTH = '{{calc:growth(fact-aaaaaaaaaaaaaaaa:periodValues.1,fact-aaaaaaaaaaaaaaaa:periodValues.0):%}}'


async def _subject_issue(tmp_path, statement):
    editor, _, context = await _make_editor_with_subject(
        tmp_path, include_table=False, number_reference=True, period_table=True,
        metric_scope={'院区': '北院'}, number_statement=statement,
    )
    index = await editor.trace.require_index(context)
    markdown_file = next(file for file in index.files if file.resource_id == index.markdown_file_resource_id)
    markdown = (await editor.trace._read_registered_file(context, markdown_file, max_bytes=1 << 24)).decode()
    sources = {file.resource_id: await editor.trace._read_registered_file(context, file, max_bytes=1 << 24)
               for file in index.files if file.media_type == 'application/json'}
    bundle = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='c' * 64)
    subject_id = index.subject_bindings[0].subject_id
    return next((issue for issue in bundle.issues if issue.subject_id == subject_id), None)


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('statement', [
    f'2025年9—10月北院收入合计{_SUM}。',
    f'2025年10月北院收入较9月增长{_GROWTH}。',
])
async def test_recomputed_calc_with_matching_statement_is_checked(tmp_path, statement):
    assert await _subject_issue(tmp_path, statement) is None


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_calc_sum_whose_window_contradicts_the_statement_needs_review(tmp_path):
    issue = await _subject_issue(tmp_path, f'2025年10月北院收入合计{_SUM}。')
    assert issue is not None and 'statement_not_supported' in issue.reasons
    assert 'operation_semantics_not_evaluated' not in issue.reasons
    assert any('统计期间需复核' in warning for warning in issue.statement_review.warnings)


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_editor_source_card_lists_calc_dataset_and_readable_formula(tmp_path):
    import hashlib

    editor, _, context = await _make_editor_with_subject(
        tmp_path, include_table=False, number_reference=True, period_table=True,
        metric_scope={'院区': '北院'}, number_statement=f'2025年9—10月北院收入合计{_SUM}。',
    )
    index = await editor.trace.require_index(context)
    markdown_file = next(file for file in index.files if file.resource_id == index.markdown_file_resource_id)
    markdown = (await editor.trace._read_registered_file(context, markdown_file, max_bytes=1 << 24)).decode()
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    [subject] = result['subjects']
    # 导出附录据 datasetIds 列出源文件；计算口径写出各操作数的期间与原值，不显示内部选择器。
    assert subject['datasetIds'] == ['dataset-url-abc0001']
    assert subject['formulaText'] == '收入（2025年9月）1,200万元 + 收入（2025年10月）2,400万元 = 3,600.00万元'
