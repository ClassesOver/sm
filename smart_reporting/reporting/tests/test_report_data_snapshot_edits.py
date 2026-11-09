"""冻结表编辑按来源传播，受影响图旧回执失效，原快照保持原样。"""
import hashlib
import importlib
from copy import deepcopy

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.contracts_v1 import canonical_json_bytes


def case():
    tables, contents = {}, {}
    for key, analysis in [('table_a', 'analysis_001'), ('table_b', 'analysis_001'), ('table_c', 'analysis_002')]:
        raw = canonical_json_bytes({'schema': 'chart-input/v1', 'chartId': key, 'role': 'measure',
            'source': {'analysisId': analysis, 'path': f'facts/{analysis}.json', 'dataPath': 'metrics[0].periodValues'},
            'columns': ['period', 'value'], 'rows': [['2026-09', 120], ['2026-10', 150]], 'rowCount': 2,
            'columnMeta': {'value': {'unit': '万元'}}})
        contents[key] = raw
        tables[key] = {'file': {'path': f'inputs/{key}.json', 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}}
    charts = {key: {'tableIds': [table], 'chartRevision': 'chart-old',
        'image': {'path': f'charts/{key}.png', 'size': 10, 'sha256': 'c' * 64},
        'executionReceipt': {'runId': 'old'}, 'visualReceipts': [{'runId': 'old'}],
        'standardRenderProof': {'runId': 'old'}, 'status': 'ready'}
        for key, table in [('chart_a', 'table_a'), ('chart_b', 'table_b'), ('chart_c', 'table_c')]}
    return {'reportId': 'report-1', 'snapshotId': 'snapshot-old', 'tables': tables, 'charts': charts}, contents


def prepare(snapshot, contents, **updates):
    module = importlib.import_module('smart_reporting.report_editor.data_revisions')
    request = {'expectedSnapshotId': 'snapshot-old', 'edits': [
        {'tableId': 'table_a', 'row': 1, 'column': 'value', 'expectedValue': 150, 'value': 180},
    ], **updates}
    return module.prepare_data_revision(snapshot, contents, request,
        snapshot_id='snapshot-new', output_root='reports/data/snapshot-new')


def test_frozen_edit_updates_all_same_source_charts_and_invalidates_only_their_receipts():
    snapshot, contents = case()
    before = deepcopy(snapshot), dict(contents)
    candidate, changed = prepare(snapshot, contents)
    assert snapshot == before[0] and contents == before[1]
    assert candidate['snapshotId'] == 'snapshot-new' and candidate['parentSnapshotId'] == 'snapshot-old'
    assert set(changed) == {'table_a', 'table_b'}
    import json
    for key, raw in changed.items():
        document = json.loads(raw)
        assert document['rows'] == [['2026-09', 120], ['2026-10', 180]]
        assert document['columnMeta']['value']['unit'] == '万元'
        assert document['source']['origin'] == 'user_edited'
        assert document['source']['parentFile'] == snapshot['tables'][key]['file']
        assert candidate['tables'][key]['file']['sha256'] == hashlib.sha256(raw).hexdigest()
    for key in ['chart_a', 'chart_b']:
        chart = candidate['charts'][key]
        assert chart['status'] == 'invalidated'
        assert chart['executionReceipt'] is None and chart['visualReceipts'] == []
        assert chart['standardRenderProof'] is None
        assert chart['chartRevision'] is None
        assert chart['image'] is None and chart['previousImage'] == snapshot['charts'][key]['image']
    assert candidate['charts']['chart_c'] == snapshot['charts']['chart_c']
    assert candidate['tables']['table_c'] == snapshot['tables']['table_c']


@pytest.mark.parametrize('fault', ['stale_snapshot', 'stale_cell', 'foreign_table', 'changed_bytes', 'duplicate_edit', 'nonfinite'])
def test_invalid_edits_do_not_return_candidate_or_modify_parent(fault):
    snapshot, contents = case()
    before = deepcopy(snapshot)
    updates = {}
    if fault == 'stale_snapshot':
        updates['expectedSnapshotId'] = 'snapshot-stale'
    if fault in {'stale_cell', 'foreign_table', 'nonfinite'}:
        edit = {'tableId': 'table_a', 'row': 1, 'column': 'value', 'expectedValue': 150, 'value': 180}
        edit[{'stale_cell': 'expectedValue', 'foreign_table': 'tableId', 'nonfinite': 'value'}[fault]] = {
            'stale_cell': 140, 'foreign_table': 'outside', 'nonfinite': float('nan'),
        }[fault]
        updates['edits'] = [edit]
    if fault == 'changed_bytes':
        contents['table_a'] = contents['table_a'] + b' '
    if fault == 'duplicate_edit':
        updates['edits'] = [{'tableId': 'table_a', 'row': 1, 'column': 'value', 'expectedValue': 150, 'value': v} for v in [180, 190]]
    with pytest.raises((ReportingError, ValueError)):
        prepare(snapshot, contents, **updates)
    assert snapshot == before


@pytest.mark.parametrize('ambiguous', [False, True])
def test_projected_same_source_rows_align_by_frozen_values_or_reject_ambiguity(ambiguous):
    import json
    snapshot, contents = case()
    projected = json.loads(contents['table_b'])
    projected.update(columns=['value'] if ambiguous else ['value', 'period'],
        rows=[[150], [150]] if ambiguous else [[150, '2026-10'], [120, '2026-09']])
    raw = canonical_json_bytes(projected)
    contents['table_b'] = raw
    snapshot['tables']['table_b']['file'].update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    before = deepcopy(snapshot)
    if ambiguous:
        with pytest.raises(ReportingError) as caught:
            prepare(snapshot, contents)
        assert caught.value.code == 'report_data_dependency_ambiguous'
        assert snapshot == before
    else:
        candidate, changed = prepare(snapshot, contents)
        assert json.loads(changed['table_b'])['rows'] == [[180, '2026-10'], [120, '2026-09']]
        assert candidate['charts']['chart_b']['status'] == 'invalidated'


@pytest.mark.parametrize(('old', 'new'), [(150, None), (None, 180)])
def test_null_edits_refresh_nullable_column_metadata_in_both_directions(old, new):
    import json
    snapshot, contents = case()
    for key in ['table_a', 'table_b']:
        document = json.loads(contents[key])
        document['rows'][1][1] = old
        document['nullableColumns'] = ['value'] if old is None else []
        raw = canonical_json_bytes(document)
        contents[key] = raw
        snapshot['tables'][key]['file'].update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    _candidate, changed = prepare(snapshot, contents, edits=[
        {'tableId': 'table_a', 'row': 1, 'column': 'value', 'expectedValue': old, 'value': new},
    ])
    for raw in changed.values():
        document = json.loads(raw)
        assert document['rows'][1][1] == new
        assert document['nullableColumns'] == (['value'] if new is None else [])
