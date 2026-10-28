"""混合比例的分母文件是登记、核验、修订继承的必要依赖。"""
import hashlib
import json

import pytest

from smart_reporting.reporting.trace.contracts_v1 import (
    FactFileEntryV1,
    TableDerivationV1,
    TraceFileRefV1,
    derive_resource_id,
)
from smart_reporting.reporting.trace.index_builder import encode_trace_index
from smart_reporting.reporting.trace.semantic_bindings import statement_fingerprints
from smart_reporting.reporting.trace.table_sources import (
    resolve_table_derivation,
    table_derivation_token,
)

from .lineage_fixtures.manifest import register_trace_manifest
from .test_trace_subject_validate import _make_editor_with_table_derivation


async def ratio_editor(tmp_path):
    editor, context, _, numerator_path = await _make_editor_with_table_derivation(tmp_path)
    index = await editor.trace.require_index(context)
    thread = context.scope['threadId']
    numerator_id = derive_resource_id(numerator_path)
    path = 'reports/revision-1/denominator.json'
    resource_id = derive_resource_id(path)
    table = json.dumps({'periods': ['2025-01'], 'scope': {'company': '甲院'},
                        'findings': [{'columns': ['科室', '金额'], 'columnMeta': {'金额': {'unit': '元'}},
                                      'rows': [['甲科', 60], ['乙科', 40]]}]}).encode()
    fact = json.dumps({'analysisId': 'analysis_003', 'metrics': [{
        'factId': 'fact-aaaaaaaaaaaaaaaa', 'total': 200, 'unit': '元', 'scope': {'company': '甲院'},
        'aggregation': 'sum', 'periodAggregation': 'sum',
        'periodValues': [{'period': '2025-01', 'value': 200}], 'periodGranularity': 'month',
        'periodStart': '2025-01', 'periodEnd': '2025-01'}]}).encode()
    proof = TableDerivationV1.model_validate({'operands': [{
        'fileResourceId': numerator_id, 'tablePointer': '/findings/0', 'rowIndex': 0,
        'columnIndex': 1, 'coefficient': '1'}], 'unit': '%', 'denominatorFact': {
            'analysisId': 'analysis_003', 'fileResourceId': resource_id,
            'jsonPointer': '/metrics/0', 'factKind': 'metric', 'factKey': 'fact-aaaaaaaaaaaaaaaa'}})
    token = table_derivation_token(proof, {numerator_id: table, resource_id: fact})
    assert token
    markdown = '2025年1月甲科占甲院收入30%[[claim:claim-table-0]]。'
    for location, raw in [(path, fact), (numerator_path, table), (context.markdown_path, markdown.encode())]:
        await editor.workspace.awrite_bytes(thread, location, raw, overwrite=location != path)
    updates = {numerator_id: table, index.markdown_file_resource_id: markdown.encode()}
    files = tuple(file.model_copy(update={'size': len(updates[file.resource_id]),
                  'sha256': hashlib.sha256(updates[file.resource_id]).hexdigest()})
                  if file.resource_id in updates else file for file in index.files)
    ref = index.subject_bindings[0].number_reference.model_copy(update={
        'token': token, 'table_derivation': proof, 'display_text': '30%',
        'statement_sha256': statement_fingerprints(markdown, ('claim-table-0',))['claim-table-0'],
    })
    index = index.model_copy(update={
        'files': (*files, TraceFileRefV1(resourceId=resource_id, path=path, mediaType='application/json',
                                        size=len(fact), sha256=hashlib.sha256(fact).hexdigest())),
        'fact_files': (*index.fact_files, FactFileEntryV1(analysisId='analysis_003', fileResourceId=resource_id, contentKind='deterministic_bundle')),
        'subject_bindings': (index.subject_bindings[0].model_copy(update={'number_reference': ref}),),
    })
    await editor.workspace.awrite_bytes(thread, 'reports/revision-1/trace-index-v1.json', encode_trace_index(index), overwrite=True)
    manifest = await register_trace_manifest(editor.workspace, thread, index, overwrite=True)
    return editor, context.model_copy(update={'artifact_manifest': manifest}), markdown, path


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('fault', ['none', 'missing', 'changed'])
async def test_editor_ratio_requires_unchanged_denominator_file(tmp_path, fault):
    editor, context, markdown, path = await ratio_editor(tmp_path)
    if fault == 'missing':
        await editor.workspace.adelete_file(context.scope['threadId'], path)
    elif fault == 'changed':
        await editor.workspace.awrite_bytes(context.scope['threadId'], path, b'{}', overwrite=True)
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result['subjects'][0]['status'] == ('valid' if fault == 'none' else 'unbound')
    if fault != 'none':
        assert result['subjects'][0]['warnings']


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_ratio_denominator_frozen_bytes_survive_resource_rebinding(tmp_path):
    from smart_reporting.report_editor.trace_revisions import snapshot_revision_lineage
    from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile

    editor, context, markdown, path = await ratio_editor(tmp_path)
    index = await editor.trace.require_index(context)
    manifest = await editor.trace.load_manifest(context)
    target = 'reports/revision-2/report.md'
    thread = context.scope['threadId']
    await editor.workspace.awrite_text(thread, target, markdown)
    path_map = {file.path: f'reports/revision-2/resources/{file.path}' for file in index.files
                if file.resource_id != index.markdown_file_resource_id}
    _, identity = await snapshot_revision_lineage(
        editor.workspace, thread, manifest=manifest, index=index,
        markdown_file=ArtifactFile(path=target, mediaType='text/markdown', size=len(markdown.encode()),
                                  sha256=hashlib.sha256(markdown.encode()).hexdigest()),
        target_revision=2, path_map=path_map, manifest_path='reports/revision-2/manifest.json',
    )
    next_context = context.model_copy(update={'revision': 2, 'markdown_path': target, 'artifact_manifest': identity})
    migrated = await editor.trace.require_index(next_context)
    number = migrated.subject_bindings[0].number_reference
    assert number.table_derivation.denominator_fact.file_resource_id == derive_resource_id(path_map[path])
    sources = {file.resource_id: await editor.trace._read_registered_file(next_context, file, max_bytes=100000)
               for file in migrated.files if file.media_type == 'application/json'}
    assert resolve_table_derivation(number.token, number.table_derivation, sources)['value'] == 30
    result = await editor.trace.validate(next_context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result['subjects'][0]['status'] == 'valid'
