"""真实SQL/HTTP授权，固定生成器；仅验证运行阶段身份故障，不是Office验收。"""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from smart_reporting.management import preference_verification
from smart_reporting.management.repository import preference_verification_results
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_evidence_persistence import with_artifact_storage
from smart_reporting.tests.test_preference_verification_handoff import ROOT, begin
from smart_reporting.tests.test_preference_verification_handoff import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('fault,code', [
    ('before_read', 'management_preference_executor_identity_unavailable'),
    ('after_read', 'management_preference_executor_identity_unavailable'),
    ('changed', 'management_preference_executor_changed'),
])
async def test_run_identity_fault_preserves_artifact_without_misclassifying_storage(case, monkeypatch, fault, code):
    calls = []

    def manifest():
        calls.append(True)
        if fault == 'before_read' or fault == 'after_read' and len(calls) == 2:
            raise ValueError('/private/executor/fixture-sensitive-path')
        return {'fixtureExecutor': 'changed' if fault == 'changed' and len(calls) == 2 else 'stable'}

    monkeypatch.setattr(preference_verification, 'executor_manifest', manifest)
    record = AsyncMock(side_effect=AssertionError('身份不完整时不能留证'))
    monkeypatch.setattr(case[0].evidence, 'record_result', record)
    token = await begin(case)
    response = await case[1].post(ROOT + '/run', json={**case[2], 'handoffToken': token}, headers=case[3])

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['formats']['md']['artifact']['base64'] == 'dGVzdA=='
    assert payload['formats']['md']['artifact']['size'] == 4
    assert payload['status'] == 'failed' and payload['canApply'] is False
    assert code in {issue['code'] for issue in payload['issues']}
    assert 'management_preference_evidence_persistence_failed' not in {issue['code'] for issue in payload['issues']}
    assert 'verificationReceipt' not in payload
    assert len(case[10]) == 1
    record.assert_not_called()
    assert all(secret not in response.text for secret in (
        '/private/executor', 'fixtureExecutor', case[5], case[6], token, 'authBinding'))


@pytest.mark.parametrize('fault', ['changed', 'after_read'])
async def test_identity_fault_still_rechecks_expired_authority_before_returning_bytes(case, monkeypatch, fault):
    calls = []

    def manifest():
        calls.append(True)
        if len(calls) == 2:
            case[9][0] += timedelta(minutes=31)
            if fault == 'after_read':
                raise RuntimeError('fixture-after-expiry')
        return {'fixtureExecutor': len(calls)}

    monkeypatch.setattr(preference_verification, 'executor_manifest', manifest)
    record = AsyncMock(side_effect=AssertionError('变化期间不能留证'))
    monkeypatch.setattr(case[0].evidence, 'record_result', record)
    token = await begin(case)
    response = await case[1].post(ROOT + '/run', json={**case[2], 'handoffToken': token}, headers=case[3])

    assert response.status_code in {401, 403}, response.text
    assert 'dGVzdA==' not in response.text
    assert len(case[10]) == 1
    record.assert_not_called()


async def test_stable_readable_incomplete_runtime_identity_still_records_coverage_gaps(case, monkeypatch):
    manifest = {**preference_verification.executor_manifest(), 'runtimeIdentityComplete': False}
    monkeypatch.setattr(preference_verification, 'executor_manifest', lambda: manifest)
    with_artifact_storage(case)
    record = AsyncMock(wraps=case[0].evidence.record_result)
    monkeypatch.setattr(case[0].evidence, 'record_result', record)
    token = await begin(case)
    response = await case[1].post(ROOT + '/run', json={**case[2], 'handoffToken': token}, headers=case[3])

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['verificationReceipt']['id']
    assert payload['canApply'] is False
    assert payload['formats']['md']['artifact']['base64'] == 'dGVzdA=='
    record.assert_awaited_once()
    assert 'management_preference_executor_identity_unavailable' not in {issue['code'] for issue in payload.get('issues', [])}
    async with case[7].engine.connect() as connection:
        document = await connection.scalar(select(preference_verification_results.c.document).where(
            preference_verification_results.c.id == payload['verificationReceipt']['id']))
    assert document['assessment']['canApply'] is False
    assert any(gap['reason'] == 'executor_identity_unavailable'
        for gap in document['assessment']['missingRequirements'])


async def test_executor_change_keeps_existing_material_failure_and_full_artifact_identity(case, monkeypatch):
    calls = []
    original = case[0].bound.run
    observed = {}

    async def material_failure(*args, **kwargs):
        result = await original(*args, **kwargs)
        observed.update(result['formats']['md']['artifact'])
        result.setdefault('issues', []).append({'code': 'management_preference_materials_changed',
            'message': '夹具：生成后材料变化。'})
        result['binding']['valid'] = False
        result['status'], result['canApply'] = 'failed', False
        return result

    def manifest():
        calls.append(True)
        return {'fixtureExecutor': len(calls)}

    monkeypatch.setattr(case[0].bound, 'run', material_failure)
    monkeypatch.setattr(preference_verification, 'executor_manifest', manifest)
    token = await begin(case)
    response = await case[1].post(ROOT + '/run', json={**case[2], 'handoffToken': token}, headers=case[3])

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['formats']['md']['artifact'] == observed
    assert {'management_preference_materials_changed', 'management_preference_executor_changed'} <= {
        issue['code'] for issue in payload['issues']}
    assert payload['bindingValid'] is False and payload['canApply'] is False
    assert 'verificationReceipt' not in payload
