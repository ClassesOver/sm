"""未知时间口径不得被确定性合计或补证覆盖判断升级。"""
import hashlib

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.tests.test_deterministic_analysis import analysis, context, semantic
from smart_reporting.reporting.workflow.runtime.evidence_coverage import facts_cover_analysis


@pytest.mark.parametrize('periods', [
    ('2025-01', '2025-02'), ('2025-01', None), ('2025-01', 'unknown'),
])
def test_unknown_time_additivity_does_not_freeze_an_unproven_total(periods):
    csv = ('month,department,budget,actual\n' + ''.join(
        f'{period or ""},A,100,10\n' for period in periods
    )).encode()
    ctx = context('current', fields=('month', 'department', 'budget', 'actual'), semantics=(
        {**semantic('budget', unit='元'), 'additiveAcross': []},
        semantic('actual', unit='元'),
    ), sha256=hashlib.sha256(csv).hexdigest())
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=('budget', 'actual')).model_copy(update={'dataset_ids': ('current',)}),
        (('current', csv, ctx, ('current',)),),
    )
    assert [(fact.field, fact.total) for fact in bundle.metrics] == [('actual', 20)]
    assert not any(fact.field == 'budget' for fact in bundle.breakdowns)
    assert any('budget' in warning and '时间可加性未确认' in warning for warning in bundle.warnings)
    assert facts_cover_analysis(bundle, {'step': '全年规模合计', 'actions': ['汇总']}, {}) is None


def test_unknown_time_additivity_keeps_single_period_grouping_available():
    csv = b'month,department,budget\n2025-01,A,100\n2025-01,B,50\n'
    ctx = context('current', fields=('month', 'department', 'budget'), semantics=(
        {**semantic('budget', unit='元'), 'additiveAcross': []},
    ), sha256=hashlib.sha256(csv).hexdigest())
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=('budget',)).model_copy(update={'dataset_ids': ('current',), 'periods': ('2025-01',)}),
        (('current', csv, ctx, ('current',)),),
    )
    fact, = bundle.metrics
    assert fact.total == 150
    assert fact.period_aggregation is None
    assert [(period.period, period.value) for period in fact.period_values] == [('2025-01', 150)]
