"""共同数据修订必须通过持久状态 CAS，冲突不能覆盖旧修订。"""
from copy import deepcopy

import pytest

from smart_reporting.reporting.tests.test_reporting_state import initial_state
from smart_reporting.reporting.workflow.state import ReportingStateError, ReportingStateReducer


def state_with_report():
    state = initial_state()
    state.payload['reportEditorContexts'] = {'1': {
        'reportId': 'report-1', 'revision': 1, 'jobId': 'job-1', 'job': {'jobId': 'job-1'},
        'workflowRunId': state.report_run_id, 'markdownPath': 'reports/report.md',
        'scope': {'threadId': 'thread-1', 'userId': 'user-1'},
    }}
    return state


def commit(state, snapshot='snapshot-1', parent=None, *, report='report-1', digest='a' * 64, base_revision=1):
    return ReportingStateReducer.apply(state, {
        'name': 'record_report_data_revision', 'commandId': f'{snapshot}-{digest}',
        'payload': {
            'expectedSnapshotId': parent,
            'revision': {
                'reportId': report, 'baseRevision': base_revision, 'snapshotId': snapshot,
                'parentSnapshotId': parent,
                'manifest': {'path': f'reports/data/{snapshot}/manifest.json', 'size': 100, 'sha256': digest},
            },
        },
    }, state.state_version).state


def test_data_revision_preserves_parent_and_immutable_history():
    baseline = state_with_report()
    first = commit(baseline)
    frozen = deepcopy(first.payload['reportDataRevisions']['report-1']['1']['revisions']['snapshot-1'])
    second = commit(first, 'snapshot-2', 'snapshot-1')
    history = second.payload['reportDataRevisions']['report-1']['1']
    assert history['latestSnapshotId'] == 'snapshot-2'
    assert history['revisions']['snapshot-1'] == frozen
    assert history['revisions']['snapshot-2']['parentSnapshotId'] == 'snapshot-1'
    assert 'reportDataRevisions' not in baseline.payload


def test_data_revision_rejects_stale_parent_even_after_state_version_retry():
    first = commit(state_with_report())
    second = commit(first, 'snapshot-2', 'snapshot-1')
    before = second.model_dump(mode='json')
    with pytest.raises(ReportingStateError) as caught:
        commit(second, 'snapshot-3', 'snapshot-1')
    assert caught.value.code == 'report_data_revision_conflict'
    assert second.model_dump(mode='json') == before


def test_editor_revisions_have_independent_snapshot_cas_and_export_history():
    state = state_with_report()
    state.payload['reportEditorContexts']['2'] = {
        **state.payload['reportEditorContexts']['1'], 'revision': 2, 'markdownPath': 'reports/revision-2/report.md',
    }
    first = record_export(commit(state))
    second = commit(first, 'revision-2-baseline', base_revision=2)
    third = commit(second, 'snapshot-2', 'snapshot-1')
    fourth = record_export(third, export_id='revision-2-export', baseRevision=2,
        snapshotId='revision-2-baseline', revision=4)
    histories = fourth.payload['reportDataRevisions']['report-1']
    assert histories['1']['latestSnapshotId'] == 'snapshot-2'
    assert histories['2']['latestSnapshotId'] == 'revision-2-baseline'
    assert set(histories['1']['exports']) == {'export-1'}
    assert set(histories['2']['exports']) == {'revision-2-export'}
    assert histories['1']['revisions']['snapshot-1'] == first.payload['reportDataRevisions']['report-1']['1']['revisions']['snapshot-1']
    with pytest.raises(ReportingStateError):
        commit(fourth, 'wrong-parent', 'snapshot-2', base_revision=2)
    with pytest.raises(ReportingStateError):
        record_export(fourth, export_id='wrong-snapshot', baseRevision=2)


@pytest.mark.parametrize('fault', ['foreign_report', 'overwrite_id', 'bad_identity', 'bad_parent'])
def test_invalid_data_revision_never_changes_latest_or_history(fault):
    state = commit(state_with_report())
    before = state.model_dump(mode='json')
    kwargs = {
        'foreign_report': {'snapshot': 'snapshot-2', 'parent': 'snapshot-1', 'report': 'foreign'},
        'overwrite_id': {'snapshot': 'snapshot-1', 'parent': 'snapshot-1', 'digest': 'b' * 64},
        'bad_identity': {'snapshot': 'snapshot-2', 'parent': 'snapshot-1', 'digest': 'invalid'},
        'bad_parent': {'snapshot': 'snapshot-2', 'parent': None},
    }[fault]
    with pytest.raises(ReportingStateError):
        commit(state, **kwargs)
    assert state.model_dump(mode='json') == before


@pytest.mark.parametrize('identity', ['workflowRunId', 'threadId', 'userId'])
def test_data_revision_rejects_foreign_run_thread_or_user(identity):
    state = state_with_report()
    context = state.payload['reportEditorContexts']['1']
    if identity == 'workflowRunId':
        context[identity] = 'foreign'
    else:
        context['scope'][identity] = 'foreign'
    with pytest.raises(ReportingStateError) as caught:
        commit(state)
    assert caught.value.code == 'report_data_revision_invalid'
    assert 'reportDataRevisions' not in state.payload


def record_export(state, export_id='export-1', **overrides):
    record = {
        'reportId': 'report-1', 'baseRevision': 1, 'snapshotId': 'snapshot-1',
        'exportId': export_id, 'revision': 2,
        'manifest': {'path': f'reports/exports/{export_id}/manifest.json',
            'size': 200, 'sha256': 'b' * 64},
        **overrides,
    }
    return ReportingStateReducer.apply(state, {
        'name': 'record_report_data_export', 'commandId': f'export:{export_id}:{record["revision"]}',
        'payload': {'export': record},
    }, state.state_version).state


def test_data_export_records_reexports_without_changing_snapshot_history():
    state = commit(state_with_report())
    first = record_export(state)
    second = record_export(first, 'export-2', revision=3)
    history = second.payload['reportDataRevisions']['report-1']['1']
    assert history['revisions'] == state.payload['reportDataRevisions']['report-1']['1']['revisions']
    assert history['latestSnapshotId'] == 'snapshot-1'
    assert set(history['exports']) == {'export-1', 'export-2'}
    assert history['exports']['export-1'] == first.payload['reportDataRevisions']['report-1']['1']['exports']['export-1']
    assert history['exports']['export-2']['snapshotId'] == 'snapshot-1'


@pytest.mark.parametrize('fault', ['snapshot', 'report', 'identity', 'overwrite', 'scope'])
def test_data_export_rejects_unregistered_or_foreign_records_without_mutation(fault):
    state = record_export(commit(state_with_report()))
    if fault == 'scope':
        state.payload['reportEditorContexts']['1']['scope']['userId'] = 'foreign'
    before = deepcopy(state)
    kwargs = {
        'snapshot': {'snapshotId': 'missing'},
        'report': {'reportId': 'foreign'},
        'identity': {'manifest': {'path': '../escape', 'size': 1, 'sha256': 'x'}},
        'overwrite': {'export_id': 'export-1', 'revision': 3},
        'scope': {},
    }[fault]
    with pytest.raises(ReportingStateError):
        record_export(state, **({'export_id': 'export-2'} | kwargs))
    assert state == before
