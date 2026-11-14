"""正式Word生成后的执行器漂移告警；漂移注入不是当前执行器批准证明。"""

import base64
import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from docx import Document
from sqlalchemy import func, select

from smart_reporting.management import preference_report_preflight, preference_verification
from smart_reporting.management.repository import preference_verification_results
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_verification_handoff import ROOT, begin
from smart_reporting.tests.test_preference_verification_handoff import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]
OUTPUT = Path('output/system-config-preferences/executor-diagnostics')


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_real_word_survives_injected_executor_drift_without_receipt_or_storage_failure(case, monkeypatch):
    manifest = preference_verification.executor_manifest()
    calls = []

    def changed_manifest():
        calls.append(True)
        # 显式测试接缝，不冒充自然发生的源码/资源漂移。
        return manifest if len(calls) == 1 else {**manifest, 'fixtureInjectedDrift': True}

    async def actual_word(function, *args, **kwargs):
        return function(*args, **{**kwargs, 'formats': ('word',)})

    record = AsyncMock(side_effect=AssertionError('漂移后不得留证'))
    monkeypatch.setattr(preference_verification, 'executor_manifest', changed_manifest)
    monkeypatch.setattr(preference_report_preflight, 'run_office_engine', actual_word)
    monkeypatch.setattr(case[0].evidence, 'record_result', record)
    token = await begin(case)
    response = await case[1].post(ROOT + '/run', json={**case[2], 'handoffToken': token}, headers=case[3])

    assert response.status_code == 200, response.text
    payload = response.json()
    artifact = payload['formats']['word']['artifact']
    content = base64.b64decode(artifact['base64'], validate=True)
    assert artifact['size'] == len(content) > 0
    assert artifact['sha256'] == sha256(content).hexdigest()
    native = Document(BytesIO(content))
    assert native.tables and native.paragraphs
    assert payload['status'] == 'failed' and payload['canApply'] is False
    assert payload['bindingValid'] is True
    codes = {item['code'] for item in payload['issues']}
    assert 'management_preference_executor_changed' in codes
    assert 'management_preference_evidence_persistence_failed' not in codes
    assert 'verificationReceipt' not in payload
    assert len(calls) == 2
    record.assert_not_called()
    async with case[7].engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(preference_verification_results)) == 0
    assert all(value not in response.text for value in (case[5], case[6], token, 'fixtureInjectedDrift'))
    (OUTPUT / 'drift-actual.docx').write_bytes(content)
    (OUTPUT / 'word-readback.json').write_text(json.dumps({
        'scope': 'real_word_http_sql_authority_with_explicit_manifest_drift_injection',
        'artifact': {'sizeBytes': len(content), 'sha256': sha256(content).hexdigest()},
        'nativeTables': len(native.tables), 'nativeParagraphs': len(native.paragraphs),
        'status': payload['status'], 'canApply': payload['canApply'],
        'bindingValid': payload['bindingValid'], 'issues': payload['issues'],
        'receiptAbsent': True, 'recordResultCalled': False, 'sqlRecordCount': 0,
        'boundary': '合成业务/工作流；正式Word引擎；执行器漂移为固定注入，无完整视觉/批准证据。',
    }, ensure_ascii=False, indent=2))
