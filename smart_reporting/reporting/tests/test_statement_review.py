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
