"""表题材料桥只搬运当前服务端登记，不把索引算作业务数据集。"""
import hashlib
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.management.preference_preflight import _verify_materials
from smart_reporting.reporting.tests.test_reporting_integration import (
    _report_pair_identities,
    _ReportPairService,
)
from smart_reporting.reporting.workspace import WorkspaceReportService
from smart_reporting.tests.test_preference_preflight import _inputs
from smart_reporting.tests.test_preference_report_preflight import bound_case


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
@pytest.mark.parametrize('manifest', [None, {'current': 'registered-manifest'}])
async def test_pair_uses_current_manifest_without_persisting_private_payload(monkeypatch, manifest):
    import uuid

    service = _ReportPairService(_report_pair_identities())
    report = WorkspaceReportService(service)
    context = RunContext(run_id='actual-run', session_id='thread', session_state={})
    job = {'jobId': 'job-1', 'sources': [], '_tableCaptionManifest': {'stale': True},
        '_tableCaptionWorkflowRunId': 'old-run'}
    captured, stored = [], []
    monkeypatch.setattr(uuid, 'uuid4', lambda: SimpleNamespace(hex='test'))
    monkeypatch.setattr(report, '_load_job', lambda *_: deepcopy(job))
    monkeypatch.setattr(report, '_job_status', AsyncMock(return_value={}))
    monkeypatch.setattr(report, '_delete_report_path', AsyncMock())
    monkeypatch.setattr(report, '_store_job', lambda value, *_: stored.append(deepcopy(value)))
    async def render(_operation, payload, _context):
        captured.append(deepcopy(payload['job']))
        return {'render': {'markdown': {'path': 'report.md', 'size': 1, 'sha256': 'markdown'},
            'images': [], 'pdf': {**service.identities['reports/.revision-1.test.tmp/report.pdf'],
                'path': 'reports/.revision-1.test.tmp/report.pdf'}}}
    report._run_report_runtime = render
    await report._render_report_pair('job-1', 'report.md', 'reports/revision-1/report.pdf',
        artifact_manifest=manifest, run_context=context)
    if manifest is None:
        assert '_tableCaptionManifest' not in captured[0]
        assert '_tableCaptionWorkflowRunId' not in captured[0]
    else:
        assert captured[0]['_tableCaptionManifest'] == manifest
        assert captured[0]['_tableCaptionWorkflowRunId'] == 'actual-run'
    assert stored and all('_tableCaptionManifest' not in item and
        '_tableCaptionWorkflowRunId' not in item for item in stored)
    assert job['_tableCaptionManifest'] == {'stale': True}


def test_frozen_caption_input_preserves_exact_crlf_and_hashes_index(tmp_path):
    _, materials = _inputs(tmp_path)
    source = tmp_path / 'report.md'
    source.write_bytes(source.read_bytes().replace(b'\n', b'\r\n'))
    identity = next(item for item in materials.state['sources'] if item['path'] == 'report.md')
    identity.update(size=source.stat().st_size, sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    raw = b'{"registered":"index"}\r\n'
    (tmp_path / 'trace-index.json').write_bytes(raw)
    manifest = {'traceIndex': {'path': 'trace-index.json', 'size': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest()}}
    materials.state.update(_tableCaptionManifest=manifest, _tableCaptionWorkflowRunId='actual-run')
    _, frozen, digest = _verify_materials(materials, formats=('word', 'pdf'))
    assert frozen['tableCaptionInput'] == {'manifest': manifest, 'traceIndexText': raw.decode(),
        'markdownText': source.read_bytes().decode(), 'workflowRunId': 'actual-run'}
    assert '\r\n' in frozen['tableCaptionInput']['markdownText']
    (tmp_path / 'trace-index.json').write_bytes(b'changed')
    _, changed, changed_digest = _verify_materials(materials, formats=('word', 'pdf'))
    assert changed.get('tableCaptionInput') is None
    assert changed_digest != digest


@pytest.mark.anyio
async def test_bound_snapshot_copies_registered_index_separately_from_datasets(tmp_path, monkeypatch):
    service, _, _, repository, context, root, _ = await bound_case(tmp_path)
    raw = b'{"transport":"only"}\r\n'
    (root / 'trace-index.json').write_bytes(raw)
    index_identity = {'path': 'trace-index.json', 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    md = context.job['render']['markdown']
    manifest_dict = {'markdown': md, 'traceIndex': index_identity}
    manifest = SimpleNamespace(markdown=SimpleNamespace(model_dump=lambda **_: deepcopy(md)),
        trace_index=SimpleNamespace(model_dump=lambda **_: deepcopy(index_identity)),
        model_dump=lambda **_: deepcopy(manifest_dict))
    monkeypatch.setattr(service.editor.trace, 'load_manifest', AsyncMock(return_value=manifest))
    check = AsyncMock(return_value=object())
    monkeypatch.setattr(service.editor.trace, 'index_for_manifest', check)
    destination = tmp_path / 'frozen'
    materials, _, binding = await service._snapshot(context, repository.state, destination)
    check.assert_awaited_once_with(context, manifest)
    assert materials.state['_tableCaptionManifest'] == manifest_dict
    assert materials.state['_tableCaptionWorkflowRunId'] == context.workflow_run_id
    assert (destination / 'trace-index.json').read_bytes() == raw
    assert index_identity in binding['identities']
    assert all(item['path'] != 'trace-index.json' for item in materials.state['sources'])


def test_preflight_stages_frozen_caption_index_without_dataset_registration(tmp_path, monkeypatch):
    from smart_reporting.management import preference_preflight as module
    from smart_reporting.reporting.tests.test_document_table_caption_numbering import (
        caption_input,
        sample_markdown,
    )

    draft, materials = _inputs(tmp_path)
    text = sample_markdown()
    value = caption_input(text)
    (tmp_path / 'report.md').write_bytes(text.encode())
    (tmp_path / 'trace-index.json').write_bytes(value['traceIndexText'].encode())
    materials.state['sources'][0] = {key: value['manifest']['markdown'][key] for key in ('path', 'size', 'sha256')}
    materials.state.update(_tableCaptionManifest=value['manifest'], _tableCaptionWorkflowRunId=value['workflowRunId'])
    captured = []
    def generate(root, _preferences, frozen):
        captured.append((root / 'inputs' / 'trace-index.json').read_bytes())
        assert all(item['path'] != 'trace-index.json' for item in frozen['state']['sources'])
        return {format: [] for format in ('md', 'xlsx', 'pptx', 'word', 'pdf')}
    monkeypatch.setattr(module, '_generate', generate)
    module.run_preference_preflight(draft, materials, expected_version=draft['version'],
        expected_content_hash=draft['contentHash'], formats=('word', 'pdf'))
    assert captured == [value['traceIndexText'].encode()]
