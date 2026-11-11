"""独立预期值仅由合成原始行计算，不导入生产计算器。"""

from decimal import Decimal
from pathlib import Path

import pytest

from smart_reporting.reporting.tests.semantic_fixtures.oracle import (
    execution_ratio,
    read_amounts,
    snapshot_changes,
    unique_document_total,
)

FIXTURES = Path(__file__).with_name("semantic_fixtures")


def test_total_ratio_uses_totals_instead_of_mean_of_project_ratios():
    budget = read_amounts(FIXTURES / "budget.csv")
    actual = read_amounts(FIXTURES / "actual.csv")
    assert sum(budget.values()) == Decimal("300")
    assert sum(actual.values()) == Decimal("190")
    assert execution_ratio(actual, budget) == Decimal("63.33")
    assert execution_ratio(actual, budget) != Decimal("70.00")


def test_duplicate_document_does_not_inflate_total_and_refund_keeps_sign():
    assert unique_document_total((('p1', '100'), ('p1', '100'), ('r1', '-10'))) == Decimal('90')
    with pytest.raises(ValueError, match="同一单据"):
        unique_document_total((('p1', '100'), ('p1', '90')))


def test_zero_denominator_and_missing_amount_do_not_become_zero_rate():
    assert execution_ratio({'A': Decimal('0')}, {'A': Decimal('0')}) is None
    assert execution_ratio({}, {'A': Decimal('100')}) is None


def test_snapshot_oracle_differences_and_requires_explicit_year_reset():
    assert snapshot_changes((('2026-01', '50'), ('2026-02', '80'))) == (
        Decimal('50'), Decimal('30'),
    )
    with pytest.raises(ValueError, match="跨年"):
        snapshot_changes((('2025-12', '100'), ('2026-01', '20')))
    assert snapshot_changes(
        (('2025-12', '100'), ('2026-01', '20')), calendar_year_reset=True,
    ) == (Decimal('100'), Decimal('20'))
