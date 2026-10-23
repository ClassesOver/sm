"""Dimension defects retain totals but cannot certify business comparisons."""

import hashlib
import json

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.top_sets import registered_top_sets

from .test_deterministic_analysis import analysis, context, semantic
from .test_group_rank_assertions import compile_rank
from .test_group_share_assertions import compile_share, group_bundle


@pytest.mark.parametrize('missing', ['', '   '])
def test_missing_middle_group_restricts_all_group_proofs(missing):
    raw = ('month,campus,department,amount\n' + ''.join(
        f'2025-01,北院,{missing if value == 15 else "科室" + str(value)},{value}\n'
        for value in range(1, 31)
    )).encode()
    ctx = context(
        'current', fields=('month', 'campus', 'department', 'amount'),
        semantics=(semantic('amount', scope={'campus': '北院'}, unit='元'),),
        sha256=hashlib.sha256(raw).hexdigest(),
    ).model_copy(update={'period_granularities': {'month': 'month'}})
    bundle = build_deterministic_analysis_bundle(
        analysis(), (('current', raw, ctx, ('current',)),), profile_hash='a' * 64,
    )
    metric = bundle.metrics[0]
    assert metric.total == 465 and not metric.warnings
    assert '归属缺失' in metric.group_warnings['department'][0]
    assert all(group.group_values['department'] not in (None, '   ')
               for group in (*metric.top_groups, *metric.bottom_groups))
    document = json.loads(bundle.model_dump_json(by_alias=True))
    rank, _, _ = compile_rank(document)
    share, _, _ = compile_share(document)
    assert rank.status != 'supported'
    assert 'ranking_dimension_review_required' in rank.reasons
    assert share.status != 'supported'
    assert 'population_dimension_review_required' in share.reasons
    assert registered_top_sets(document['metrics'][0])[1] == ('ranking_dimension_review_required',)


def test_share_retains_concentration_restriction_but_ignores_other_dimensions():
    document = json.loads(group_bundle(weights=(10000, 1)).model_dump_json(by_alias=True))
    result, _, _ = compile_share(document)
    assert result.status != 'supported'
    assert 'population_dimension_review_required' in result.reasons
    document['metrics'][0]['groupWarnings'] = {'another_dimension': ['待确认']}
    result, _, _ = compile_share(document)
    assert result.status == 'supported', result.reasons
