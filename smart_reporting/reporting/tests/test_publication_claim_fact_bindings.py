"""发布核对事实身份，不把未绑定选择器的计划 claim 当成事实合计。"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.workflow.runtime.publication import RuntimePublicationMixin


@pytest.mark.anyio
@pytest.mark.parametrize(('entry', 'value'), [
    ({'baselineTotal': 10475201732, 'change': 648339771}, 10475201732),
    ({'total': 11123541503}, 1011231045.73),
    ({'total': 11123541503,
      'periodValues': [{'period': '2025-11', 'value': 537347472}]}, 537347472),
])
async def test_legacy_claim_without_selector_is_not_compared_to_arbitrary_fact_field(entry, value):
    runtime = object.__new__(RuntimePublicationMixin)
    runtime._read_identity_bytes = AsyncMock(return_value=json.dumps({
        'metrics': [{'factId': 'fact-aaaaaaaaaaaaaaaa', **entry}],
    }).encode())
    checkpoint = SimpleNamespace(deterministic_fact_files={'analysis_001': object()})
    artifact = SimpleNamespace(section_code='section_001', claims=[SimpleNamespace(
        claim_id='claim_001', fact_ids=('fact-aaaaaaaaaaaaaaaa',), value=value,
    )])

    issues, warnings = await runtime._verify_claim_fact_bindings('thread', checkpoint, (artifact,))

    assert issues == []
    assert warnings == []


@pytest.mark.anyio
async def test_unknown_fact_still_reports_identity_issue():
    runtime = object.__new__(RuntimePublicationMixin)
    runtime._read_identity_bytes = AsyncMock(return_value=b'{"metrics": []}')
    checkpoint = SimpleNamespace(deterministic_fact_files={'analysis_001': object()})
    artifact = SimpleNamespace(section_code='section_001', claims=[SimpleNamespace(
        claim_id='claim_001', fact_ids=('fact-aaaaaaaaaaaaaaaa',), value=30,
    )])

    issues, warnings = await runtime._verify_claim_fact_bindings('thread', checkpoint, (artifact,))

    assert [issue['code'] for issue in issues] == ['report_claim_fact_unknown']
    assert warnings == []
