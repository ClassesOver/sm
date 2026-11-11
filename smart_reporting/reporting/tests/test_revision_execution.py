"""刷新执行和手动编辑共用编号，恢复不再次消耗编号。"""

import pytest

from smart_reporting.reporting.tests.test_reporting_state import initial_state
from smart_reporting.reporting.workflow.state import (
    ReportingCommand,
    ReportingStateError,
    ReportingStateReducer,
)


def reserve(state, command_id, *, key=None, minimum=1):
    payload = {'minimumRevision': minimum}
    if key is not None:
        payload['reservationKey'] = key
    return ReportingStateReducer.apply(state, ReportingCommand(name='reserve_report_editor_revision',
        commandId=command_id, payload=payload), state.state_version).state


def test_execution_reservation_survives_different_replay_command_and_manual_edits():
    state = reserve(initial_state(), 'execution-1', key='execution-a')
    state = reserve(state, 'manual-1')
    state = reserve(state, 'reconstructed-execution-1', key='execution-a')
    assert state.payload['reportEditorRevisionCounter'] == 3
    assert state.payload['reportEditorRevisionReservations'] == {'execution-a': 2}
    state = reserve(state, 'execution-2', key='execution-b')
    assert state.payload['reportEditorRevisionReservations']['execution-b'] == 4


@pytest.mark.parametrize('key', ['', 7, 'x' * 129])
def test_invalid_reservation_identity_is_rejected(key):
    with pytest.raises(ReportingStateError):
        reserve(initial_state(), 'invalid-reservation', key=key)


def test_approved_outline_is_frozen_and_cannot_rebind_or_reference_unknown_analysis():
    outline = {'reportType': 'topic', 'title': '预算核对', 'sections': [
        {'code': 'section_001', 'sectionNumber': '1', 'title': '预算', 'analysisIds': ['analysis_001']}]}
    state = ReportingStateReducer.apply(initial_state(), ReportingCommand(name='set_analysis_plan',
        commandId='outline-plan', payload={'analysisIds': ['analysis_001']}), 0).state
    command = ReportingCommand(name='freeze_report_outline', commandId='original-outline', payload={'outline': outline})
    frozen = ReportingStateReducer.apply(state, command, state.state_version).state
    assert frozen.payload['approvedOutline']['title'] == '预算核对'
    changed = {**outline, 'title': '替换标题'}
    with pytest.raises(ReportingStateError) as conflict:
        ReportingStateReducer.apply(frozen, ReportingCommand(name='freeze_report_outline',
            commandId='replace-outline', payload={'outline': changed}), frozen.state_version)
    assert conflict.value.code == 'report_outline_conflict'
    foreign = {**outline, 'sections': [{**outline['sections'][0], 'analysisIds': ['analysis_unknown']}]}
    with pytest.raises(ReportingStateError) as invalid:
        ReportingStateReducer.apply(state, ReportingCommand(name='freeze_report_outline',
            commandId='foreign-outline', payload={'outline': foreign}), state.state_version)
    assert invalid.value.code == 'report_outline_invalid'
