"""写作时同步发布后的引用句核对：同一检查、同一参数，附所在语句交回模型。"""

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
    import json

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

