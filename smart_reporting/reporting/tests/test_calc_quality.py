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


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize(('reference', 'computation', 'formula_text'), [
    (_SUM, 'calc', '收入（2025年9月）1,200万元 + 收入（2025年10月）2,400万元 = 3,600.00万元'),
    ('{{value:fact-aaaaaaaaaaaaaaaa:total:万元}}', 'registered', 'revenue 求和'),
    # 服务端派生的数写出按登记原值的可验算算式，而不是原始的核对公式。
    ('{{value:fact-aaaaaaaaaaaaaaaa:periodTotals.0-1:万元}}', 'derived', '9月 1,200万元 + 10月 2,400万元 = 3,600万元'),
])
async def test_editor_reports_how_each_number_was_obtained(tmp_path, reference, computation, formula_text):
    import hashlib

    editor, _, context = await _make_editor_with_subject(
        tmp_path, include_table=False, number_reference=True, period_table=True,
        metric_scope={'院区': '北院'}, number_statement=f'2025年9—10月北院收入合计{reference}。',
    )
    index = await editor.trace.require_index(context)
    markdown_file = next(file for file in index.files if file.resource_id == index.markdown_file_resource_id)
    markdown = (await editor.trace._read_registered_file(context, markdown_file, max_bytes=1 << 24)).decode()
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    [subject] = result['subjects']
    # 编辑器据此向读者区分直接登记值与服务端计算的数。
    assert subject['status'] == 'valid' and subject['computation'] == computation
    assert subject['formulaText'] == formula_text


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_editor_formula_text_names_fields_by_their_column_description(tmp_path):
    import hashlib
    import json

    editor, _, context = await _make_editor_with_subject(
        tmp_path, include_table=False, number_reference=True, period_table=True,
        metric_scope={'院区': '北院'},
        number_statement='2025年9—10月北院收入合计{{value:fact-aaaaaaaaaaaaaaaa:total:万元}}。',
    )
    index = await editor.trace.require_index(context)
    files = {file.resource_id: file for file in index.files}
    [dataset] = index.datasets
    document = {'datasetContexts': [{
        'datasetId': dataset.dataset_id, 'sha256': files[dataset.file_resource_id].sha256,
        'schema': {'tables': [{'name': 'income', 'columns': [{'name': 'revenue', 'description': '医疗收入'}]}]},
    }]}
    content = json.dumps(document, ensure_ascii=False).encode()
    path = 'reports/detailed-analysis-context.json'
    await editor.workspace.awrite_bytes(context.scope['threadId'], path, content)
    identity = {'path': path, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
    markdown_file = files[index.markdown_file_resource_id]
    markdown = (await editor.trace._read_registered_file(context, markdown_file, max_bytes=1 << 24)).decode()
    sha = hashlib.sha256(markdown.encode()).hexdigest()
    [subject] = (await editor.trace.validate(context, markdown, sha, analysis_context_file=identity))['subjects']
    # 卡片口径与“指标”同源：所属数据集的列说明，不显示内部字段名。
    assert subject['formula'] == 'sum(revenue)' and subject['formulaText'] == '医疗收入 求和'
    # 上下文缺失时退回原口径，校验照常完成。
    [fallback] = (await editor.trace.validate(context, markdown, sha))['subjects']
    assert fallback['status'] == 'valid' and fallback['formulaText'] == 'revenue 求和'


def test_formula_labels_prefer_column_descriptions_and_skip_conflicting_columns():
    from smart_reporting.report_editor.trace_sources import _formula_labels

    definitions = {'d1': {'revenue': '医疗收入', 'campus': '院区'}, 'd2': {'revenue': '药品收入'}, 'd3': {'cost': '成本'}}
    entry = {'field': 'visits', 'displayName': '门诊人次'}
    # 同名列在所属数据集间说明不一致时保留原名；不属于该事实的数据集不参与；字段缺列说明时用登记的指标名。
    assert _formula_labels(entry, ['d1', 'd2'], definitions) == {'campus': '院区', 'visits': '门诊人次'}
    assert _formula_labels({'field': 'revenue', 'displayName': '收入金额'}, ['d1'], definitions)['revenue'] == '医疗收入'
    assert _formula_labels(None, [], definitions) == {}
    # 带别名的名称只取首个名称。
    assert _formula_labels({'field': 'income', 'displayName': '收入金额，也称医疗收入金额'}, [], {}) == {'income': '收入金额'}
