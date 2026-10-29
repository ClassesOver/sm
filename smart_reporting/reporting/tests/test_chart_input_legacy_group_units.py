import json

import pytest

from smart_reporting.reporting.workflow.runtime.chart_inputs import chart_input_matches_rebuild


def encode(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


@pytest.mark.parametrize('path', [
    'breakdowns',
    'breakdowns[0].periodValues', 'breakdowns[0].topGroups', 'breakdowns[0].bottomGroups',
    'breakdowns[0].groupPopulation', 'metrics[0].topGroups', 'metrics[0].bottomGroups',
    'metrics[0].groupPopulation',
])
def test_only_absent_new_parent_units_can_use_exact_legacy_bytes(path):
    measure = 'total' if path == 'breakdowns' else 'value'
    old = {'schema': 'chart-input/v1', 'source': {'dataPath': path, 'sha256': 'a' * 64},
           'columns': ['group', measure], 'rows': [['甲', 42]], 'rowCount': 1}
    new = {**old, 'columnMeta': {measure: {'unit': '万元', 'isPercent': False}}}
    assert chart_input_matches_rebuild(encode(old), encode(new))
    assert chart_input_matches_rebuild(encode(new), encode(new))
    for actual in ({**old, 'rows': [['甲', 43]]}, {**old, 'rowCount': 2},
                   {**old, 'source': {**old['source'], 'sha256': 'b' * 64}},
                   {**old, 'columnMeta': {measure: {'unit': '亿元'}}}):
        assert not chart_input_matches_rebuild(encode(actual), encode(new))


@pytest.mark.parametrize('path', ['metrics[0].periodValues', 'findings[0].rows', 'foreign[0].topGroups'])
def test_old_unit_omission_exception_does_not_extend_to_other_sources(path):
    old = {'source': {'dataPath': path}, 'rows': [['甲', 42]]}
    assert not chart_input_matches_rebuild(encode(old), encode({**old, 'columnMeta': {'value': {'unit': '元'}}}))


def test_unrelated_metadata_and_invalid_bytes_do_not_qualify():
    old = {'source': {'dataPath': 'breakdowns[0].periodValues'}, 'rows': [['甲', 42]]}
    for metadata in ({'value': {'unit': '元', 'periods': ['2025-09']}}, {'value': {'isPercent': True}}, {'other': {'unit': '元'}}):
        assert not chart_input_matches_rebuild(encode(old), encode({**old, 'columnMeta': metadata}))
    assert not chart_input_matches_rebuild(b'{}', b'bad json')
