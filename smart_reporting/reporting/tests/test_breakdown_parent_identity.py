"""分组事实的父关系也是冻结身份，不能只按相同金额合并。"""

from smart_reporting.reporting.tests.test_dimension_breakdowns import _bundle
from smart_reporting.reporting.trace.fact_index import (
    assign_fact_ids,
    fact_binding_records,
    merge_binding_records,
)


def test_breakdown_ids_include_the_actual_frozen_parent_identity():
    first = _bundle()
    parent, = first.metrics
    assert len(parent.top_groups) > 1
    other_parent = parent.model_copy(update={'top_groups': tuple(reversed(parent.top_groups))})
    second = assign_fact_ids(first.model_copy(update={'metrics': (other_parent,)}))
    assert first.metrics[0].fact_id != second.metrics[0].fact_id
    first_groups = {(g.breakdown_field, tuple(sorted(g.scope.items()))): g for g in first.breakdowns}
    for group in second.breakdowns:
        old = first_groups[group.breakdown_field, tuple(sorted(group.scope.items()))]
        assert group.total == old.total and group.period_values == old.period_values
        assert group.parent_fact_id != old.parent_fact_id
        assert group.fact_id != old.fact_id
    assert assign_fact_ids(second) == second


def test_legacy_same_id_with_different_parent_remains_a_binding_conflict():
    bundle = _bundle()
    records = fact_binding_records(bundle)
    group = bundle.breakdowns[0]
    original = records[group.fact_id]
    changed = {**original, 'entry': {**original['entry'], 'parentFactId': 'fact-' + 'f' * 16}}
    assert merge_binding_records(original, changed) is None
