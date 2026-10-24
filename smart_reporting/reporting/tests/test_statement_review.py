"""写作时同步发布后的引用句核对：同一检查、同一参数，附所在语句交回模型。"""

from smart_reporting.reporting.tests.test_number_selection import source
from smart_reporting.reporting.trace.statement_review import (
    STATEMENT_REVIEW_PREFIX,
    statement_review_warnings,
)


def test_reference_period_contradicting_the_sentence_is_reported_with_the_sentence():
    warnings = statement_review_warnings('2024年1—2月合计{{value:fact-bbbbbbbbbbbbbbbb:total:元}}。', source())
    assert warnings and all(item.startswith(STATEMENT_REVIEW_PREFIX) for item in warnings)
    assert any('2025-01、2025-02' in item for item in warnings)
    assert all('所在语句：2024年1—2月合计100元' in item for item in warnings)


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
