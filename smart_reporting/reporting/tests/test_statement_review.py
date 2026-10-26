"""写作时同步发布后的引用句核对：同一检查、同一参数，附所在语句交回模型。"""

import json

from smart_reporting.reporting.tests.test_number_selection import source
from smart_reporting.reporting.trace.statement_review import (
    STATEMENT_REVIEW_PREFIX,
    statement_review_warnings,
)


def test_reference_period_contradicting_the_sentence_is_reported_with_the_sentence():
    warnings = statement_review_warnings('2024年1—2月合计{{value:fact-bbbbbbbbbbbbbbbb:total:元}}。', source())
    assert warnings and all(item.startswith(STATEMENT_REVIEW_PREFIX) for item in warnings)
    # 期间按读者习惯写成“2025年1—2月”；期间已写错时不再重复报统计窗口。
    [warning] = warnings
    assert '期间文本与生成时不一致（生成时 2025年1—2月）' in warning
    assert '所在语句：2024年1—2月合计100元' in warning
    # 指明是哪个数，并给出同一指标在句中所写期间的登记引用，由模型决定是否改用。
    assert '“100元”的登记期间与句中所写不同' in warning
    assert '若要写2024年1—2月，同一指标该期间已登记为 {{value:fact-aaaaaaaaaaaaaaaa:total:元}}（20元）' in warning


def test_period_alternative_is_offered_only_when_unambiguous():
    # 同一字段在该期间有两个取值不同的登记事实时不猜测，只指明数值。
    [document] = [json.loads(item) for item in source()]
    twin = {**document['metrics'][0], 'factId': 'fact-' + 'e' * 16, 'datasetId': 'ds-2024-copy', 'total': 21,
            'periodValues': [{'period': '2024-01', 'value': 10}, {'period': '2024-02', 'value': 11}]}
    document['metrics'].append(twin)
    [warning] = statement_review_warnings('2024年1—2月合计{{value:fact-bbbbbbbbbbbbbbbb:total:元}}。',
                                          [json.dumps(document)])
    assert '“100元”的登记期间与句中所写不同' in warning and '若要写' not in warning
    # 句中写了多个期间时同样不给候选。
    [warning] = statement_review_warnings(
        '2024年1月至2025年2月合计{{value:fact-bbbbbbbbbbbbbbbb:total:元}}。', source())
    assert '若要写' not in warning


def test_period_alternative_requires_one_fact_identity_even_when_values_are_equal():
    [document] = [json.loads(item) for item in source()]
    twin = {
        **document['metrics'][0],
        'factId': 'fact-' + 'e' * 16,
        'datasetId': 'ds-2024-copy',
    }
    document['metrics'].append(twin)

    [warning] = statement_review_warnings(
        '2024年1—2月合计{{value:fact-bbbbbbbbbbbbbbbb:total:元}}。',
        [json.dumps(document)],
    )

    assert '“100元”的登记期间与句中所写不同' in warning
    assert '若要写' not in warning


def test_period_alternative_never_flattens_sparse_or_independent_windows():
    [document] = [json.loads(item) for item in source()]
    sparse = document['metrics'][0]
    sparse['periodEnd'] = '2024-03'
    sparse['periodValues'] = [
        {'period': '2024-01', 'value': 9},
        {'period': '2024-03', 'value': 11},
    ]
    cross_year = {
        **sparse,
        'factId': 'fact-' + 'e' * 16,
        'datasetId': 'ds-cross-year',
        'periodStart': '2024-01',
        'periodEnd': '2025-02',
        'periodValues': [
            {'period': f'{year}-{month:02d}', 'value': 1}
            for year, months in ((2024, range(1, 13)), (2025, range(1, 3)))
            for month in months
        ],
        'total': 14,
    }
    document['metrics'].append(cross_year)
    contents = [json.dumps(document)]

    [sparse_warning] = statement_review_warnings(
        '2024年1—3月合计{{value:fact-bbbbbbbbbbbbbbbb:total:元}}。', contents,
    )
    [windows_warning] = statement_review_warnings(
        '2024年1—2月与2025年1—2月合计{{value:fact-bbbbbbbbbbbbbbbb:total:元}}。',
        contents,
    )

    assert '若要写' not in sparse_warning
    assert '若要写' not in windows_warning


def test_period_alternative_requires_the_same_metric_time_semantics():
    [document] = [json.loads(item) for item in source()]
    selected = document['metrics'][1]
    selected.update({
        'periodAggregation': 'last',
        'periodField': 'closed_month',
        'cumulativePolicy': {
            'version': '1',
            'reset': 'calendar_year_zero',
            'observation': 'closed_month_end',
            'changes': 'signed_snapshot_delta',
        },
    })

    [warning] = statement_review_warnings(
        '2024年1—2月累计快照为{{value:fact-bbbbbbbbbbbbbbbb:total:元}}。',
        [json.dumps(document)],
    )

    assert '“100元”的登记期间与句中所写不同' in warning
    assert '若要写' not in warning


def test_period_alternative_never_substitutes_a_different_comparison_type():
    from smart_reporting.reporting.tests.test_reader_formulas import _yoy_bundle

    content, fact_id = _yoy_bundle()
    document = json.loads(content)
    mom = {
        **document['comparisons'][0],
        'factId': 'fact-' + 'e' * 16,
        'comparisonType': 'mom',
        'periodStart': '2024-01',
        'periodEnd': '2024-02',
        'currentTotal': 999,
    }
    document['comparisons'].append(mom)

    [warning] = statement_review_warnings(
        f'2024年1—2月合计{{{{value:{fact_id}:currentTotal:元}}}}。',
        [json.dumps(document)],
    )

    assert '“270元”的登记期间与句中所写不同' in warning
    assert '若要写' not in warning


def test_period_alternative_uses_the_period_nearest_a_reference_in_a_long_sentence():
    [document] = [json.loads(item) for item in source()]
    candidate = {
        **document['metrics'][0],
        'factId': 'fact-' + 'e' * 16,
        'datasetId': 'ds-2023',
        'periodStart': '2023-01',
        'periodEnd': '2023-02',
        'periodValues': [
            {'period': '2023-01', 'value': 14},
            {'period': '2023-02', 'value': 16},
        ],
        'total': 30,
    }
    document['metrics'].append(candidate)
    markdown = (
        '2024年1—2月是历史背景，' + '背景说明' * 60
        + '，2023年1—2月合计{{value:fact-bbbbbbbbbbbbbbbb:total:元}}。'
    )

    [warning] = statement_review_warnings(markdown, [json.dumps(document)])

    assert '若要写2023年1—2月' in warning
    assert '{{value:fact-eeeeeeeeeeeeeeee:total:元}}（30元）' in warning
    assert '若要写2024年1—2月' not in warning
    assert '所在语句：' in warning and '2023年1—2月合计100元' in warning


def test_consistent_sentences_and_unbound_text_pass():
    assert statement_review_warnings('2025年1—2月合计{{value:fact-bbbbbbbbbbbbbbbb:total:元}}。', source()) == []
    assert statement_review_warnings('本章不含数值。', source()) == []


SUM = '{{calc:sum(fact-bbbbbbbbbbbbbbbb:periodValues.0,fact-bbbbbbbbbbbbbbbb:periodValues.1):元}}'
GROWTH = '{{calc:growth(fact-bbbbbbbbbbbbbbbb:periodValues.1,fact-bbbbbbbbbbbbbbbb:periodValues.0):%}}'


def test_calc_references_get_the_same_sentence_check_as_the_quality_bundle():
    # 质量包按重算结果核对计算引用所在语句；写作时同样交回模型，不等发布后才暴露。
    [window] = statement_review_warnings(f'2025年2月合计{SUM}。', source())
    assert '统计期间需复核' in window and '所在语句：2025年2月合计100元' in window
    [period] = statement_review_warnings(f'2024年2月较1月增长{GROWTH}。', source())
    assert '期间文本与生成时不一致' in period
    assert statement_review_warnings(f'2025年1—2月合计{SUM}；2025年2月较1月增长{GROWTH}。', source()) == []


def test_period_lists_read_as_calendar_spans():
    from smart_reporting.reporting.trace.comparison_proofs import period_list_text

    assert period_list_text([f'2024-{month:02d}' for month in range(1, 10)]) == '2024年1—9月'
    assert period_list_text(['2024-11', '2024-12', '2025-01']) == '2024年11月—2025年1月'
    assert period_list_text(['2025-09']) == '2025年9月'
    # 不连续的各段分别书写（同比的本期与基期）；非逐月期间保持原样。
    assert period_list_text(['2025-01', '2025-03']) == '2025年1月、2025年3月'
    assert period_list_text(['2025-01', '2025-02', '2024-01', '2024-02']) == '2025年1—2月、2024年1—2月'
    assert period_list_text(['2025-09-01', '2025-09-02']) == '2025-09-01、2025-09-02'
    assert period_list_text(['2025-13']) == '2025-13'



B_MIN = '{{value:fact-bbbbbbbbbbbbbbbb:monthlyMinimum:元}}'
B_MAX = '{{value:fact-bbbbbbbbbbbbbbbb:monthlyMaximum:元}}'


def test_server_derived_values_get_the_same_sentence_check():
    # 月度极值、期间累计等由服务端派生的数，写作时同样核对所在语句的期间。
    warnings = statement_review_warnings('2025年1月累计{{value:fact-bbbbbbbbbbbbbbbb:periodTotals.0-1:元}}。', source())
    assert any('当前引用覆盖 2025年1—2月' in warning for warning in warnings)
    assert statement_review_warnings('2025年1—2月累计{{value:fact-bbbbbbbbbbbbbbbb:periodTotals.0-1:元}}。', source()) == []
    # “各月介于最低至最高”写的是区间两端，不是“各月均为同一数值”。
    assert statement_review_warnings(f'2025年1—2月各月收入介于{B_MIN}至{B_MAX}之间。', source()) == []
    [uniform] = statement_review_warnings(f'2025年1—2月各月收入均为{B_MAX}。', source())
    assert '不能表述为各月均为同一数值' in uniform


def test_relative_yoy_baseline_is_checked_against_previous_year_window():
    from smart_reporting.reporting.trace.content_review import review_content_result

    markdown = ('2025年1—2月收入较上年同期的 {{value:fact-aaaaaaaaaaaaaaaa:total:元}} '
                '增长至 {{value:fact-bbbbbbbbbbbbbbbb:total:元}}。')
    for wording in ('上年同期', '去年同期'):
        text = markdown.replace('上年同期', wording)
        assert statement_review_warnings(text, source()) == []
        review = review_content_result(text, source())
        assert not any('统计期间需复核' in warning for warning in review.warnings)


def test_relative_yoy_does_not_excuse_wrong_baseline_months_or_year():
    for label in ('2025年1—3月', '2026年1—2月'):
        markdown = f'{label}收入较上年同期的 {{{{value:fact-aaaaaaaaaaaaaaaa:total:元}}}} 增长。'
        assert statement_review_warnings(markdown, source())


def test_yoy_label_does_not_allow_a_current_fact_as_the_baseline():
    markdown = ('2025年1—2月收入较上年同期的 {{value:fact-bbbbbbbbbbbbbbbb:total:元}} 增长。')
    assert statement_review_warnings(markdown, source())
