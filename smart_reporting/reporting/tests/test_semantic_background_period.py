"""精确期间解释区分当前基期金额与同句中的本期背景。"""

import pytest

from smart_reporting.reporting.trace.claim_semantics import freeze_interpretation, semantic_warnings
from smart_reporting.reporting.trace.comparison_proofs import period_list_text

PERIODS = tuple(f'2024-{month:02d}' for month in range(1, 12))
MARKDOWN = (
    '2025年1—11月，开单收入累计111.24亿元，较2024年1—11月同窗口基期'
    '104.75亿元（10,475,201,732元[[claim:baseline]]）增加6.48亿元。'
)
PERIOD_WARNING = f'期间文本与生成时不一致（生成时 {period_list_text(PERIODS)}）'


def _receipt(periods=PERIODS, evidence=('2024年1—11月同窗口基期',)):
    return freeze_interpretation(MARKDOWN, 'baseline', {
        'claimId': 'baseline', 'scope': [], 'periods': periods, 'periodEvidence': evidence,
    })


def test_grounded_exact_baseline_period_removes_only_its_background_period_warning():
    other = ['单位文本与生成时不一致（生成时 元）', '期间角色与生成时不一致（基期窗口）']

    assert semantic_warnings(
        MARKDOWN, 'baseline', _receipt(), {}, PERIODS, [PERIOD_WARNING, *other],
    ) == other


@pytest.mark.parametrize('evidence', [(), ('不存在的基期声明',)])
def test_absent_or_ungrounded_period_evidence_cannot_clear_warning(evidence):
    assert PERIOD_WARNING in semantic_warnings(
        MARKDOWN, 'baseline', _receipt(evidence=evidence), {}, PERIODS, [PERIOD_WARNING],
    )


def test_different_interpreted_period_keeps_warning_and_reports_conflict():
    result = semantic_warnings(
        MARKDOWN, 'baseline', _receipt(periods=('2025-01',), evidence=('2025年1—11月',)),
        {}, PERIODS, [PERIOD_WARNING],
    )
    assert PERIOD_WARNING in result
    assert any('语义期间' in warning for warning in result)


def test_edited_period_invalidates_receipt_and_keeps_warning():
    result = semantic_warnings(
        MARKDOWN.replace('2024年1—11月同窗口基期', '2024年8月单月'),
        'baseline', _receipt(), {}, PERIODS, [PERIOD_WARNING],
    )
    assert PERIOD_WARNING in result
    assert any('失效' in warning for warning in result)


def test_matching_model_period_does_not_override_explicitly_different_evidence():
    # 模型即便填对期间，原文明确写出的相反年月仍不能被覆盖。
    assert PERIOD_WARNING in semantic_warnings(
        MARKDOWN, 'baseline', _receipt(evidence=('2025年1—11月',)), {}, PERIODS, [PERIOD_WARNING],
    )


def test_context_resolved_relative_period_does_not_require_repeating_dates():
    assert semantic_warnings(
        MARKDOWN, 'baseline', _receipt(evidence=('同窗口基期',)), {}, PERIODS, [PERIOD_WARNING],
    ) == []


@pytest.mark.parametrize('evidence', [
    '以1—10月同窗口对照，2025年月均收入为10.59亿元，2024年同窗口月均收入为9.42亿元',
    '2025年较2024年同窗口月均增加1.16亿元',
])
def test_same_window_cross_year_difference_accepts_grounded_comparison_periods(evidence):
    markdown = (
        '以1—10月同窗口对照，2025年月均收入为10.59亿元，'
        '2024年同窗口月均收入为9.42亿元，'
        '2025年较2024年同窗口月均增加1.16亿元[[claim:difference]]。'
    )
    periods = tuple(f'{year}-{month:02d}' for year in (2025, 2024) for month in range(1, 11))
    receipt = freeze_interpretation(markdown, 'difference', {
        'claimId': 'difference', 'scope': [], 'periods': list(reversed(periods)),
        'periodEvidence': [evidence],
    })
    warning = '期间文本与生成时不一致（生成时 2025年1—10月、2024年1—10月）'

    assert semantic_warnings(markdown, 'difference', receipt, {}, periods, [warning]) == []


def test_multiple_explicit_periods_cannot_hide_a_conflicting_month():
    markdown = '2024年1—11月基期与2025年8月背景：104.75亿元[[claim:baseline]]。'
    receipt = freeze_interpretation(markdown, 'baseline', {
        'claimId': 'baseline', 'scope': [], 'periods': PERIODS,
        'periodEvidence': ['2024年1—11月基期与2025年8月背景'],
    })

    assert PERIOD_WARNING in semantic_warnings(
        markdown, 'baseline', receipt, {}, PERIODS, [PERIOD_WARNING],
    )


def test_explicit_range_cannot_hide_an_unregistered_middle_month():
    markdown = '2025年1—3月合计100元[[claim:c]]。'
    receipt = freeze_interpretation(markdown, 'c', {
        'claimId': 'c', 'scope': [], 'periods': ['2025-01', '2025-03'],
        'periodEvidence': ['2025年1—3月'],
    })
    warning = '期间文本与生成时不一致（生成时 2025年1月、2025年3月）'

    assert warning in semantic_warnings(
        markdown, 'c', receipt, {}, ('2025-01', '2025-03'), [warning],
    )
