"""已登记事实投影的真实PPTX表格字段进入SQL证据链，完整合同仍不就绪。"""

import base64
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.dml.color import RGBColor
from sqlalchemy import select

from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.management.format_preferences import FormatPreferenceService
from smart_reporting.management.preference_executor import executor_manifest
from smart_reporting.management.preference_verification import PreferenceVerificationHandoffService
from smart_reporting.management.repository import preference_verification_results
from smart_reporting.preferences.models import FormatPreferences
from smart_reporting.report_editor.repository import SqlAlchemyReportEditorRepository
from smart_reporting.report_editor.service import ReportEditorGrantService
from smart_reporting.reporting.delivery.pptx_tables import project_fact_slide_tables
from smart_reporting.reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    SqlAlchemyReportArtifactRepository,
    report_artifact_chunks_v1,
    report_artifact_files_v1,
)
from smart_reporting.reporting.tests.test_trace_table_builder import _bundle
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_report_preflight import native_case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def manifest_diff(before, after, path=''):
    """测试诊断保留实际变化值；文件列表用路径标注，不只记录总摘要。"""
    if type(before) is dict and type(after) is dict:
        changes = []
        for key in sorted(before.keys() | after.keys()):
            location = f'{path}.{key}' if path else key
            if key not in before or key not in after:
                changes.append({'path': location, 'beforePresent': key in before,
                    'afterPresent': key in after, 'before': before.get(key), 'after': after.get(key)})
            else:
                changes.extend(manifest_diff(before[key], after[key], location))
        return changes
    if type(before) is list and type(after) is list and len(before) == len(after):
        changes = []
        for index, (left, right) in enumerate(zip(before, after, strict=True)):
            label = left['path'] if isinstance(left, dict) and isinstance(right, dict) and left.get('path') == right.get('path') and 'path' in left else index
            changes.extend(manifest_diff(left, right, f'{path}[{label}]'))
        return changes
    return [] if type(before) is type(after) and before == after else [{'path': path, 'before': before, 'after': after}]


@pytest.mark.parametrize('fault', ['valid', 'last_cell_color', 'extra_native_table'])
async def test_registered_fact_table_native_fields_persist_and_recheck_without_full_approval(auth_context, tmp_path, monkeypatch, fault):
    from smart_reporting.management import preference_preflight, preference_report_preflight

    auth, repository, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    admin = (await auth.login('admin', OLD_PASSWORD, '127.0.0.1')).raw_token
    bound, _, states, context, root, spec, _, _ = await native_case(tmp_path, 'pptx')
    raw = _bundle().model_dump_json(by_alias=True).encode()
    source = FileIdentity(path='table-facts.json', size=len(raw), sha256=sha256(raw).hexdigest())
    (root / source.path).write_bytes(raw)
    tables = project_fact_slide_tables('analysis_001', source, raw)
    assert tables
    spec['slides'] = [{**spec['slides'][0], 'tables': tables}]

    def saved(path, value):
        content = json.dumps(value, ensure_ascii=False).encode()
        (root / path).write_bytes(content)
        return {'path': path, 'size': len(content), 'sha256': sha256(content).hexdigest()}

    job = deepcopy(context.job)
    pointer = job['pptxNativeInput']
    pointer['spec'] = saved('native-spec.json', spec)
    pointer['receipt'] = saved('report.pptx.receipt.json', {'schemaVersion': 'pptx-native-receipt/1',
        'binding': pointer['binding'], 'artifact': pointer['artifact'], 'spec': pointer['spec']})
    context = context.model_copy(update={'job': job})
    states.state.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
    states.state.payload['workflowCheckpoint'] = {'deterministicFactFiles': {'analysis_001': source.model_dump()}}
    states.state.payload['artifacts'] = [pointer['artifact'], pointer['spec'], pointer['receipt'], source.model_dump()]
    preferences = FormatPreferenceService(auth, FormatPreferences.model_validate({'common': {'signer': '字段验收署名'}}))
    editor_repository = SqlAlchemyReportEditorRepository(repository.engine)
    await editor_repository.create_schema()
    grants = ReportEditorGrantService(editor_repository, secret='table-fields-fixture-' * 3)
    grant, _ = await grants.issue(context)
    editor, _ = await grants.exchange(grant)
    bound.preferences, bound.grants = preferences, grants
    async with repository.engine.begin() as connection:
        await connection.run_sync(lambda sync: report_artifact_files_v1.metadata.create_all(sync,
            tables=[report_artifact_files_v1, report_artifact_chunks_v1]))
    artifacts = SqlAlchemyReportArtifactRepository(repository.engine)
    bound.editor.artifact_persistence = ReportArtifactPersistenceService(artifacts, bound.editor.workspace)
    service = PreferenceVerificationHandoffService(preferences=preferences, bound=bound)
    before_run = executor_manifest()
    assert service.evidence._runtime_identity_gaps(before_run) == []
    original_generate = preference_preflight._generate

    def actual_generation_with_fault(directory, document, frozen):
        issues = original_generate(directory, document, frozen)
        if fault != 'valid':
            path = directory / 'report.pptx'
            deck = Presentation(path)
            shapes = [(slide, shape) for slide in deck.slides for shape in slide.shapes if shape.has_table]
            assert shapes
            slide, shape = shapes[-1]
            if fault == 'last_cell_color':
                cell = shape.table.cell(len(shape.table.rows) - 1, len(shape.table.columns) - 1)
                cell.text_frame.paragraphs[-1].runs[-1].font.color.rgb = RGBColor(254, 1, 2)
            else:
                slide.shapes._spTree.insert_element_before(deepcopy(shape._element), 'p:extLst')
            deck.save(path)
        return issues

    async def native_only(function, *args, **kwargs):
        return function(*args, **kwargs)

    def no_pdf_preview(*args, **kwargs):
        raise RuntimeError('native-only SQL fixture does not verify PDF visual output')

    monkeypatch.setattr(preference_preflight, '_generate', actual_generation_with_fault)
    monkeypatch.setattr(preference_preflight, 'libreoffice_to_pdf', no_pdf_preview)
    monkeypatch.setattr(preference_report_preflight, 'run_office_engine', native_only)
    draft = (await preferences.detail(admin))['draft']
    token = (await service.create(admin, expected_version=draft['version'], expected_hash=draft['contentHash']))['handoffToken']
    await service.confirm(token, editor, report_id=context.report_id, revision=context.revision)
    payload = await service.run(admin, token, expected_version=draft['version'], expected_hash=draft['contentHash'])
    receipt = payload['verificationReceipt']
    async with repository.engine.connect() as connection:
        row = (await connection.execute(select(preference_verification_results).where(
            preference_verification_results.c.id == receipt['id']))).mappings().one()
    document = row['document']
    assert row['content_hash'] == receipt['contentHash'] == configuration_hash(document)
    assert document['retained']['issues'] == []
    assert document['binding']['valid'] is document['binding']['artifactAccessAuthorized'] is True
    assert source.model_dump() in document['binding']['identities']
    fields = [item for item in document['evidence'] if item.get('readerGroup') == 'pptx_native_table_fields_v1']
    assert len(fields) == 11
    failed = {item['path'] for item in fields if item['status'] == 'failed'}
    assert failed == ({'pptx.typography.table.color'} if fault == 'last_cell_color' else
        {item['path'] for item in fields} if fault == 'extra_native_table' else set())
    reference = document['retained']['formats']['pptx']['artifact']
    independent = SqlAlchemyReportArtifactRepository(repository.engine)
    metadata = await independent.get(reference['artifactKey'])
    content = b''.join([chunk async for chunk in independent.stream(reference['artifactKey'])])
    assert content == base64.b64decode(payload['formats']['pptx']['artifact']['base64'], validate=True)
    assert metadata.size == len(content) == reference['size']
    assert metadata.sha256 == sha256(content).hexdigest() == reference['sha256']
    assert all(item['artifact'] == {'sizeBytes': len(content), 'sha256': metadata.sha256} for item in fields)
    before_prepare = executor_manifest()
    prepare_error = None
    try:
        prepared = await service.evidence.prepare(admin, expected_version=draft['version'],
            expected_hash=draft['contentHash'], evidence_ids=[receipt['id']])
    except Exception as error:
        prepare_error = error
        raise
    finally:
        after_prepare = executor_manifest()
        recorded = document['executorManifest']
        snapshots = {'beforeRun': before_run, 'recorded': recorded,
            'beforePrepare': before_prepare, 'afterPrepare': after_prepare}
        differences = {label: manifest_diff(recorded, current) for label, current in snapshots.items() if label != 'recorded'}
        diagnostic = {'fault': fault, 'recordedExecutorManifestHash': document['executorManifestHash'],
            'digests': {label: configuration_hash(current) for label, current in snapshots.items()},
            'differencesFromRecorded': differences,
            'prepareError': {'type': type(prepare_error).__name__, 'code': getattr(prepare_error, 'code', None),
                'status': getattr(prepare_error, 'status', None)} if prepare_error else None}
        output = Path('output/system-config-preferences/pptx-table-field-evidence')
        output.mkdir(parents=True, exist_ok=True)
        (output / ('sql-executor-' + fault + '.json')).write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2))
        assert diagnostic['digests']['recorded'] == document['executorManifestHash']
        assert all(bool(changes) == (diagnostic['digests'][label] != diagnostic['digests']['recorded'])
            for label, changes in differences.items())
        if getattr(prepare_error, 'code', None) == 'management_preference_evidence_stale':
            assert differences['beforePrepare'] or differences['afterPrepare'], 'stale必须保留实际执行器清单差异，不能仅归因并发'
    assert prepared['status'] == document['assessment']['status'] == 'incomplete'
    assert prepared['canApply'] is document['assessment']['canApply'] is False
    assert any('visual' in gap['missingDimensions'] for gap in prepared['missingRequirements'])
    assert {gap['path'] for gap in prepared['missingRequirements'] if gap['reason'] == 'check_failed'} == failed
    if fault == 'valid':
        assert not any(gap.get('path') in {item['path'] for item in fields}
            and gap.get('scenario') == 'configured_field' for gap in prepared['missingRequirements'])
