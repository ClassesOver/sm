"""原生总览分别呈现事实证明与问题完成状态。"""

import pytest

from smart_reporting.reporting.tests.test_registered_claim_support import native_quality_inputs
from smart_reporting.reporting.tests.test_registered_question_coverage import questions
from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['none', 'missing', 'conflict', 'edited'])
async def test_native_overview_never_equates_verified_fact_with_complete_answer(tmp_path, fault):
    change = (lambda item: item.update(metricVersion={'metricId': 'foreign', 'revision': 1})) if fault == 'conflict' else None
    index, markdown, sources = await native_quality_inputs(tmp_path, change=change)
    if fault == 'missing':
        sources.clear()
    if fault == 'edited':
        markdown = markdown.replace('预算合计', '收入合计')
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64, questions=questions())
    overview = quality.registered_management_overview
    assert overview.report_basis_id == index.report_basis_id
    budget, reason = overview.rows
    assert budget.question_id == 'q-budget' and budget.status != 'answered'
    assert reason.question_id == 'q-reason' and reason.status == 'unavailable'
    assert bool(budget.facts) == (fault == 'none')
    assert 'question_completion_mapping_unavailable' in budget.issue_codes
    from smart_reporting.reporting.workflow.registered_overview import (
        registered_overview_projection,
    )

    payload = registered_overview_projection(overview, quality.markdown_sha256)
    assert ('300.123456789123456789' in payload['markdown']) == (fault == 'none')
    assert '为什么变化？' in payload['markdown']
    assert '完成条件尚未确认' in payload['markdown']
    if fault == 'none':
        assert '2026-11-01' in payload['markdown'] and '2026-12-01' in payload['markdown']
        assert '不含结束日' in payload['markdown']
    with pytest.raises(ValueError):
        registered_overview_projection(overview, 'f' * 64)


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['none', 'source', 'basis', 'forged_support'])
async def test_registered_reader_rechecks_current_native_proofs(tmp_path, fault):
    import hashlib

    from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
    from smart_reporting.reporting.trace.contracts_v1 import (
        TraceFileRefV1,
        canonical_json_bytes,
        derive_resource_id,
    )
    from smart_reporting.reporting.workflow.overview_sources import registered_management_overview

    runtime, _, scope, _, _, _, contents, index = await native_quality_inputs(tmp_path, publication_fixture=True)
    sources = {file.resource_id: contents[file.path] for file in index.files}
    markdown = sources[index.markdown_file_resource_id].decode()
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64, questions=questions())
    if fault == 'basis':
        quality = quality.model_copy(update={'report_basis_id': 'foreign'})
    if fault == 'forged_support':
        # 身份完整的JSON也不能让旧通过结论替代当前正文语义核验。
        subject, = index.subject_bindings
        receipt = subject.number_reference.semantic_receipt
        interpretation = receipt.interpretation.model_copy(update={'metric_version': None})
        number = subject.number_reference.model_copy(update={'semantic_receipt': receipt.model_copy(update={'interpretation': interpretation})})
        index = index.model_copy(update={'subject_bindings': (subject.model_copy(update={'number_reference': number}),)})
    raw = canonical_json_bytes(quality.model_dump(mode='json', by_alias=True))
    path = 'reports/quality-bundle-v1.json'
    await runtime.workspace_service.awrite_bytes(scope.workspace_key, path, raw, overwrite=True)
    entry = TraceFileRefV1(resourceId=derive_resource_id(path), path=path, mediaType='application/json',
        size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    index = index.model_copy(update={'files': (*index.files, entry)})
    await runtime.workspace_service.awrite_bytes(scope.workspace_key, 'reports/trace-index-v1.json',
        canonical_json_bytes(index.model_dump(mode='json', by_alias=True)), overwrite=True)
    identity = await register_trace_manifest(runtime.workspace_service, scope.workspace_key, index, overwrite=True)
    from smart_reporting.reporting.delivery.artifacts_v1 import ReportArtifactManifest
    manifest = ReportArtifactManifest.model_validate_json(await runtime.workspace_service.read_limited_regular_file(
        scope.workspace_key, identity.path, max_bytes=16 * 1024 * 1024))
    if fault == 'source':
        source = next(file for file in index.files if file.resource_id == index.fact_files[0].file_resource_id)
        await runtime.workspace_service.awrite_bytes(scope.workspace_key, source.path, b'changed', overwrite=True)
    if fault in {'source', 'basis'}:
        with pytest.raises(ValueError):
            await registered_management_overview(runtime.workspace_service, scope.workspace_key, manifest, 'a' * 64)
    else:
        overview = await registered_management_overview(runtime.workspace_service, scope.workspace_key, manifest, 'a' * 64)
        assert bool(overview.rows[0].facts) == (fault == 'none')


@pytest.mark.anyio
async def test_actual_editor_recomputes_native_overview_after_text_change(tmp_path):
    import hashlib

    from smart_reporting.report_editor import ReportEditorContext, ReportEditorService

    runtime, arguments, scope, durable, _, _, _, _ = await native_quality_inputs(tmp_path, publication_fixture=True)
    output = await runtime.issue_http_publication(**arguments)
    assert output['pdf']['downloadUrl'] and output['word']['downloadUrl']
    runtime.workspace_registry.resolve(scope)
    editor = ReportEditorService(state_repository=runtime.state_repository,
        workspace_registry=runtime.workspace_registry, workspace=runtime.workspace_service,
        trace_cursor_secret=b'trace-cursor-secret-32-bytes-ok!')
    context = ReportEditorContext.model_validate(durable.payload['reportEditorContexts']['2'])
    index = await editor.trace.require_index(context)
    file = next(file for file in index.files if file.resource_id == index.markdown_file_resource_id)
    markdown = (await editor.trace._read_registered_file(context, file, max_bytes=16 * 1024 * 1024)).decode()
    for changed in (False, True):
        current = markdown.replace('预算合计', '收入合计') if changed else markdown
        result = await editor.trace.validate(context, current, hashlib.sha256(current.encode()).hexdigest())
        overview = result['quality']['registeredManagementOverview']
        assert bool(overview['rows'][0]['facts']) is not changed


@pytest.mark.anyio
async def test_real_pdf_and_word_preserve_native_facts_and_unanswered_questions(tmp_path):
    import hashlib

    import pypdf
    from docx import Document

    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime
    from smart_reporting.reporting.tests.test_report_runtime_full_render import (
        _DEPENDENCIES_OK,
        _SKIP_REASON,
        _build_workspace,
    )
    from smart_reporting.reporting.workflow.registered_overview import (
        registered_overview_projection,
    )

    if not _DEPENDENCIES_OK:
        pytest.skip(_SKIP_REASON)
    index, body, sources = await native_quality_inputs(tmp_path / 'proof')
    markdown = '# 智能运营全链路渲染验证报告\n\n[[section:section_001]]\n\n## 1. Report\n\n' + body
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64, questions=questions())
    assert quality.claim_support[0].support_status == 'supported', quality.issues
    workspace = tmp_path / 'render'
    state = _build_workspace(workspace)
    state['_documentContext'].update({
        'sections': [{'code': 'section_001', 'sectionNumber': '1', 'title': 'Report'}],
        'headingNumbers': [{'level': 2, 'number': '1', 'title': 'Report',
            'sectionCode': 'section_001', 'anchor': 'report-section-section_001'}]})
    state['_managementOverviewProjection'] = registered_overview_projection(
        quality.registered_management_overview, hashlib.sha256(markdown.encode()).hexdigest())
    (workspace / 'report.md').write_text(markdown, encoding='utf-8')
    runtime = ReportRuntime(workspace)
    result = runtime.render_markdown(state, 'report.md', 'out/report.pdf',
        '.reporting-tmp/workspace-report-native-overview-render/render.pdf')
    assert result['status'] == 'rendered'
    pdf = pypdf.PdfReader(workspace / result['pdfPath'])
    word = Document(workspace / result['wordPath'])
    texts = ('\n'.join(page.extract_text() or '' for page in pdf.pages),
        '\n'.join(p.text for p in word.paragraphs) + '\n'.join(cell.text for table in word.tables for row in table.rows for cell in row.cells))
    for text in texts:
        compact = ''.join(text.split())
        assert '300.123456789123456789' in compact
        assert '为什么变化？' in compact and '尚无法回答' in compact
        assert '部分回答' in compact and '完成条件尚未确认' in compact
        assert '2026-11-01' in compact and '2026-12-01' in compact
        assert '不含结束日' in compact
