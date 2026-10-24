"""数值引用书写规范化只改写法不改身份；无法登记时给出原因与同一指标的可选引用。"""

import pytest

from smart_reporting.reporting.trace.value_references import (
    canonical_value_references,
    value_reference_failure,
)

_SHARE = '{{value:fact-0123456789abcdef:metricShare.fact-fedcba9876543210.2025-01..2025-09:%}}'
CATALOG = {
    '{{value:fact-0123456789abcdef:total:元}}': '2,713,908,213元',
    '{{value:fact-0123456789abcdef:total:亿元}}': '27.14亿元',
    '{{value:fact-0123456789abcdef:periodValues.0:亿元}}': '3.02亿元',
    _SHARE: '27.47%',
}


@pytest.mark.parametrize('written,expected', [
    ('{{value:0123456789ABCDEF:total:亿}}', '{{value:fact-0123456789abcdef:total:亿元}}'),
    ('{{ value: fact-0123456789abcdef : total : 亿元 }}', '{{value:fact-0123456789abcdef:total:亿元}}'),
    ('{{value:fact-0123456789abcdef:metricShare.fedcba9876543210.2025-1—2025-9:百分比}}', _SHARE),
    ('{{value:fact-0123456789abcdef:metricShare.fact-fedcba9876543210.2025-01~2025-09:亿元}}', _SHARE),
])
def test_spelling_variants_resolve_to_the_registered_reference(written, expected):
    assert canonical_value_references(f'收入{written}。', CATALOG) == f'收入{expected}。'


@pytest.mark.parametrize('written', [
    '{{value:fact-0123456789abcdef:periodTotals.0-8:亿元}}',   # 未登记的选择器不猜
    '{{value:fact-0123456789abcdef:total:人次}}',              # 多个显示单位时不替模型选
    '{{value:fact-ffffffffffffffff:total:亿元}}',
])
def test_identity_changes_are_never_guessed(written):
    assert canonical_value_references(written, CATALOG) == written


def test_failure_reason_lists_same_fact_alternatives_without_ids_in_reason():
    reason, shown, suggestions = value_reference_failure(
        '{{value:fact-0123456789abcdef:periodTotals.0-8:亿元}}', CATALOG)
    assert '取值方式' in reason and 'fact-' not in reason and shown is None
    assert suggestions[0] == '{{value:fact-0123456789abcdef:total:亿元}}'
    reason, _shown, suggestions = value_reference_failure('{{value:fact-ffffffffffffffff:total:亿元}}', CATALOG)
    assert '不在' in reason and suggestions == []


def test_revoked_reference_reports_its_original_value():
    reason, shown, _ = value_reference_failure(
        '{{value:fact-0123456789abcdef:unverified.periodValues.0:亿元}}', CATALOG)
    assert shown == '3.02亿元' and '撤销' in reason
