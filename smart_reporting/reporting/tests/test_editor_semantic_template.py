"""编辑器只恢复原修订冻结判断，预览不重新问模型。"""

import hashlib
import json
from copy import deepcopy
from io import BytesIO

import pytest
from agno.run import RunContext
from docx import Document

from smart_reporting.reporting.template_semantic_review import TemplateSignatureReviewer
from smart_reporting.reporting.tests.test_editor_template_render import render_case
from smart_reporting.reporting.tests.test_editor_template_source import fixture
from smart_reporting.reporting.tests.test_template_runtime import identity
from smart_reporting.reporting.tests.test_template_semantic_review import (
    Executor,
    opinion,
    template_bytes,
)
from smart_reporting.reporting.workflow.runtime.template_semantics import (
    semantic_review_path,
    semantic_review_reference,
)


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def review(raw):
    return await TemplateSignatureReviewer(Executor([opinion(raw), opinion(raw)])).review(raw,
        run_context=RunContext(run_id='run', user_id='owner', session_id='session', session_state={}))


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['none', 'missing_marker', 'bad_marker', 'record_drift', 'derived_fallback'])
async def test_source_rehydrates_only_matching_registered_origin_review(fault):
    from smart_reporting.report_editor.template_source import resolve_editor_template

    editor, context, scope, root, _, _, template_identity, _ = fixture()
    raw = template_bytes()
    record = await review(raw)
    marker = semantic_review_reference(record)
    template_identity.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    path = semantic_review_path(scope.run_id, raw)
    root.payload['artifacts'] = [identity(path, encoded).model_dump()]
    job = {**context.job, '_templateSemanticReview': deepcopy(marker)}
    if fault == 'missing_marker':
        job.pop('_templateSemanticReview')
    elif fault == 'bad_marker':
        job['_templateSemanticReview']['recordSha256'] = 'f' * 64
    elif fault == 'record_drift':
        encoded += b' '
    context = context.model_copy(update={'job': job})
    root.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
    if fault == 'derived_fallback':
        binding = {'schemaVersion': 1, 'originRevision': 1, 'originContextSha256': context.digest(),
            'materialRunId': scope.run_id, 'identity': deepcopy(template_identity)}
        context = context.model_copy(update={'revision': 2,
            'job': {**context.job, '_templateSource': binding}})
        context.job.pop('_templateSemanticReview')
        root.payload['reportEditorContexts']['2'] = context.model_dump(mode='json', by_alias=True)

    async def read(_thread, target):
        return (raw if target == template_identity['path'] else encoded), 'application/octet-stream'

    editor.workspace.afile_bytes.side_effect = read
    source = await resolve_editor_template(editor, context=context, source_context=context)
    assert source.content == raw
    if fault == 'none':
        assert source.semantic_review == record
        assert not source.semantic_issues
    else:
        assert source.semantic_review is None
        if fault not in {'missing_marker', 'derived_fallback'}:
            assert source.semantic_issues


@pytest.mark.anyio
async def test_editor_actual_document_uses_frozen_semantic_slot_and_truthful_provenance(tmp_path):
    from smart_reporting.report_editor.template_render import render_editor_template
    from smart_reporting.reporting.contract import ReportFileInput

    case = await render_case(tmp_path)
    raw = template_bytes()
    source_identity = ReportFileInput(filename='语义模板.docx',
        **identity('inputs/semantic.docx', raw).model_dump())
    await case.editor.workspace.awrite_bytes(case.context.scope['threadId'], source_identity.path, raw)
    case.source.identity = source_identity
    case.source.content = raw
    case.source.semantic_review = await review(raw)
    case.source.binding['identity'] = source_identity.model_dump(mode='json', by_alias=True)
    result = await render_editor_template(case.editor, template_source=case.source,
        context=case.context, source_context=case.context, document=case.document,
        snapshot_path=case.snapshot, output_path='reports/revision-2/report.pdf',
        formats=('word', 'pdf'), render_manifest=None, run_context=case.run)
    stored = (await case.editor.workspace.afile_bytes(case.context.scope['threadId'], result['wordPath']))[0]
    text = '\n'.join(Document(BytesIO(stored))._element.body.xpath('.//w:t/text()'))
    assert text.count('清川分析室') == 1 and text.count('2001-02-03') == 1
    assert '文字编制' in text and '2026年9月16日' in text and '1234.5600' in text
    source = result['validation']['layoutProvenance']['formats']['word']
    assert source['placement'] == 'semantic_template_slot'
    assert source['signatureReadback'] == 'passed'
    assert result['validation']['layoutProvenance']['layoutValidation'] == 'unverified'
    detail = result['validation']['readback']['word']['templateReadback']
    assert detail['signature']['declaration'] == 'semantic_signature_sdt'
    assert detail['semanticPreparation']['preparationReadback']['status'] == 'passed'
    assert detail['outsideDeclaredTargets']['status'] == 'passed'
    assert result['validation']['ok'] is False
