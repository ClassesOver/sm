"""编辑器复核使用本修订冻结画像，不能沿用父报告检查点。"""

import pytest

from smart_reporting.report_editor import ReportEditorContext
from smart_reporting.reporting.tests.test_editor_recalculation import native_editor


@pytest.mark.anyio
async def test_editor_uses_bound_revision_analysis_context_after_parent_checkpoint_changes(tmp_path):
    editor, repository, context, _ = await native_editor(tmp_path)
    identity = {'path': 'revision-4/dataset-contexts.json', 'size': 100, 'sha256': 'a' * 64}
    updated = ReportEditorContext.model_validate({
        **context.model_dump(mode='json', by_alias=True), 'analysisContextFile': identity})
    repository.state.payload['reportEditorContexts'][str(updated.revision)] = updated.model_dump(mode='json', by_alias=True)
    repository.state.payload['workflowCheckpoint'] = {'files': [
        {'path': 'parent/detailed-analysis-context.json', 'size': 20, 'sha256': 'b' * 64}]}
    restored = await editor._restore(updated)
    assert await editor._registered_analysis_context_file(restored) == identity
    assert context.digest() != updated.digest()
    assert repository.state.payload['workflowCheckpoint']['files'][0]['path'].startswith('parent/')


@pytest.mark.anyio
async def test_http_publication_preserves_already_frozen_revision_manifest(tmp_path):
    from smart_reporting.reporting.tests.test_http_publication_lineage import _publication_fixture

    runtime, arguments, scope, durable, _, _, _, _ = await _publication_fixture(tmp_path)
    first = await runtime.issue_http_publication(**arguments)
    context = ReportEditorContext.model_validate(durable.payload['reportEditorContexts']['2'])
    runtime.workspace_registry.resolve(scope)
    manifest_bytes, _ = await runtime.workspace_service.afile_bytes(scope.workspace_key, context.artifact_manifest.path)
    replay = {**arguments['output'], 'markdownPath': context.markdown_path,
        'artifactManifest': context.artifact_manifest.model_dump(mode='json', by_alias=True),
        'editorJob': context.job}
    result = await runtime.issue_http_publication(**{**arguments, 'output': replay})
    restored = ReportEditorContext.model_validate(durable.payload['reportEditorContexts']['2'])
    assert result['pdf']['downloadUrl'] and first['pdf']['downloadUrl']
    assert restored.artifact_manifest == context.artifact_manifest
    assert not result.get('publicationIssues')
    runtime.workspace_registry.resolve(scope)
    assert (await runtime.workspace_service.afile_bytes(scope.workspace_key, context.artifact_manifest.path))[0] == manifest_bytes
