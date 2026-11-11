"""实际报告编辑后撤销原件，新交付不能继承旧知识支持结论。"""

import hashlib
import json
import os
import re
import shutil
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile

import pytest
from httpx import ASGITransport, AsyncClient
from openpyxl import load_workbook

from smart_reporting.report_editor import (
    ReportEditorService,
    ReportSlidesEditorService,
    ReportWorkbookEditorService,
)
from smart_reporting.report_editor.slides_api import create_report_slides_editor_router
from smart_reporting.report_editor.workbook_api import create_report_workbook_editor_router
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.tests.test_report_background_delivery import auth_context as auth_context
from smart_reporting.tests.test_report_background_delivery import basis_context as basis_context
from smart_reporting.tests.test_report_background_delivery import (
    document_context as document_context,
)
from smart_reporting.tests.test_report_background_delivery import exercise_background_report
from smart_reporting.tests.test_report_background_delivery import index_context as index_context
from smart_reporting.tests.test_report_background_delivery import (
    receipt_snapshot as receipt_snapshot,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def archive_registered_sources(report, editor, context, folder):
    index = await editor.trace.require_index(context)
    manifest = await editor.trace.load_manifest(context)
    assert manifest is not None and manifest.trace_index is not None
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'context.json').write_text(context.model_dump_json(by_alias=True, indent=2))
    raw = await report.runtime._read_identity_bytes(context.scope['threadId'],
        FileIdentity(path=manifest.trace_index.path, size=manifest.trace_index.size, sha256=manifest.trace_index.sha256))
    (folder / 'trace-index.json').write_bytes(raw)
    if context.artifact_manifest is not None:
        raw = await report.runtime._read_identity_bytes(context.scope['threadId'], context.artifact_manifest)
        (folder / 'artifact-manifest.json').write_bytes(raw)
    registered = folder / 'registered-files'
    registered.mkdir(exist_ok=True)
    for file in index.files:
        raw = await report.runtime._read_identity_bytes(context.scope['threadId'],
            FileIdentity(path=file.path, size=file.size, sha256=file.sha256))
        (registered / file.resource_id).write_bytes(raw)


@pytest.mark.parametrize('edit_title', [True, False], ids=['edit', 'unchanged-export'])
async def test_workbook_edit_after_source_withdrawal_does_not_inherit_supported_claims(
    basis_context, document_context, receipt_snapshot, monkeypatch, edit_title,
):
    async def inspect(report):
        runtime = report.runtime
        folder = Path('/tmp') / f'smart-reporting-edit-withdrawal-{os.getpid()}-xlsx-{"edit" if edit_title else "unchanged"}'
        folder.mkdir(exist_ok=True)
        shutil.copytree(report.evidence_dir, folder / 'parent', dirs_exist_ok=True)
        await archive_registered_sources(report, report.editor, report.context, folder / 'parent')
        parent = (report.evidence_dir / 'c02-corrected.xlsx').read_bytes()
        with ZipFile(BytesIO(parent)) as package:
            mapping = json.loads(package.read('smart-reporting/source-mapping.json'))
        assert mapping['sources']['claims']
        assert all(item['support']['supportStatus'] == 'supported' for item in mapping['sources']['claims'])
        service = ReportWorkbookEditorService(state_repository=runtime.state_repository,
            workspace_registry=runtime.workspace_registry, workspace=runtime.workspace_service,
            editor_grants=runtime.editor_grants, artifact_persistence=runtime.artifact_persistence,
            download_grants=runtime.download_grants, public_base_url='https://reports.test')
        grant, _ = await runtime.editor_grants.issue(report.context, capabilities={'xlsx_editor': True})
        app = report.download_app
        app.include_router(create_report_workbook_editor_router(runtime.editor_grants, workbooks=service,
            static_dir=Path(__file__).resolve().parents[1] / 'report_editor/static', cookie_secure=False))
        document = await report.editor.read_document(report.context)
        async with AsyncClient(transport=ASGITransport(app), base_url='https://reports.test') as client:
            opened = await client.get('/reports/v1/workbooks/open/' + grant)
            assert opened.status_code == 303
            prefix = opened.headers['location'] + '/api'
            headers = {'X-CSRF-Token': client.cookies.get('report_workbook_csrf')}
            payload = {'expectedSha256': report.context.xlsx_sha256, 'operations': [{'kind': 'applyCellEdits',
                'edits': [{'sheetName': '汇总', 'row': 0, 'column': 0, 'writeValue': True,
                    'cell': {'value': '预算执行报告 人工复核'}}]}] if edit_title else []}
            documents, token, scope = document_context[:3]
            detail = await documents.get_document(token, scope, 'known-context')
            await documents.review_revision(token, scope, 'known-context', 1, decision='revoked',
                reason='编辑后重新导出前撤销支持原件', expected_version=detail['revisions'][0]['stateVersion'])
            current = await report.editor.trace.validate(report.context, document.markdown, document.sha256)
            assert any(item['kind'] == 'recommendation' and item['supportStatus'] == 'unverified'
                and not item['evidenceRefs'] for item in current['quality']['claimSupport'])
            historical = await client.get(report.delivery['xlsx']['downloadUrl'])
            assert historical.status_code == 200 and historical.content == parent
            response = await client.post(prefix + '/save', json=payload, headers=headers)
            assert response.status_code == 200, response.text
            result = response.json()
            assert result['revision'] == report.context.revision + 1 and result['revisionRegistered']
            assert not result['validation']['ok']
            assert 'workbook_semantic_verification_pending' in {item['code'] for item in result['validation']['issues']}
            download = await client.get(result['xlsx']['downloadUrl'])
            assert download.status_code == 200
            raw = download.content
            assert len(raw) == result['xlsx']['size'] and hashlib.sha256(raw).hexdigest() == result['xlsx']['sha256']
            historical = await client.get(report.delivery['xlsx']['downloadUrl'])
            # 新修订签发会轮换旧下载授权；原件撤销本身不使原授权失效。
            assert historical.status_code == 404
            assert historical.json()['detail']['code'] == 'report_download_grant_invalid'
            opened = await client.get(result['editor']['openUrl'])
            assert opened.status_code == 303
            current_file = await client.get(opened.headers['location'] + '/api/file')
            assert current_file.status_code == 200 and current_file.content == raw
        (folder / 'edited.xlsx').write_bytes(raw)
        (folder / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        (folder / 'current-after-withdrawal.json').write_text(json.dumps(current, ensure_ascii=False, indent=2))
        with ZipFile(BytesIO(raw)) as package:
            revised = json.loads(package.read('smart-reporting/source-mapping.json'))
        (folder / 'edited-source-mapping.json').write_text(json.dumps(revised, ensure_ascii=False, indent=2))
        book = load_workbook(BytesIO(raw), data_only=True)
        try:
            assert book.worksheets[0]['A1'].value == '本修订待核验'
            assert '尚未重新核验' in book.worksheets[0]['A6'].value
            assert f'第 {result["revision"]} 版' in book.worksheets[0]['A3'].value
            if edit_title:
                assert book['汇总']['A1'].value == '预算执行报告 人工复核'
        finally:
            book.close()
        assert revised['sources']['claims']
        assert all(item['support']['supportStatus'] == 'unverified' and not item['support']['evidenceRefs']
            for item in revised['sources']['claims']), '新文件保留了已撤销原件的旧支持结论'
        assert await report.editor.read_document(report.context) == document
        original, _ = await runtime.workspace_service.afile_bytes(report.context.scope['threadId'], report.context.xlsx_path)
        assert original == parent
        assert urlsplit(result['editor']['openUrl']).path.startswith('/reports/v1/workbooks/open/')

    await exercise_background_report(basis_context, document_context, receipt_snapshot, monkeypatch,
        'known', 'supported', delivery_format='xlsx', after_native_report=inspect)


async def test_document_edit_and_source_withdrawal_reexports_current_support(
    basis_context, document_context, receipt_snapshot, monkeypatch,
):
    from docx import Document
    from pypdf import PdfReader

    async def inspect(report):
        runtime = report.runtime
        folder = Path('/tmp') / f'smart-reporting-edit-withdrawal-{os.getpid()}-document'
        folder.mkdir(exist_ok=True)
        shutil.copytree(report.evidence_dir, folder / 'parent', dirs_exist_ok=True)
        await archive_registered_sources(report, report.editor, report.context, folder / 'parent')
        editor = ReportEditorService(state_repository=runtime.state_repository,
            workspace_registry=runtime.workspace_registry, workspace=runtime.workspace_service,
            report_tools=runtime.report_tools, artifact_persistence=runtime.artifact_persistence,
            download_grants=runtime.download_grants, editor_grants=runtime.editor_grants,
            public_base_url='https://reports.test', report_basis_service=runtime.report_basis_service,
            business_evidence_service=runtime.business_evidence_service)
        original = await editor.read_document(report.context)
        before = await editor.trace.validate(report.context, original.markdown, original.sha256)
        assert any(item['kind'] == 'recommendation' and item['supportStatus'] == 'supported'
            for item in before['quality']['claimSupport'])
        note = '复核记录：本报告保留原始计算，说明材料另行核对。'
        draft = await editor.save_draft(report.context, markdown=original.markdown + '\n\n' + note + '\n',
            expected_sha256=original.sha256)
        documents, token, scope = document_context[:3]
        detail = await documents.get_document(token, scope, 'known-context')
        await documents.review_revision(token, scope, 'known-context', 1, decision='revoked',
            reason='编辑后重新导出前撤销支持原件', expected_version=detail['revisions'][0]['stateVersion'])
        async with AsyncClient(transport=ASGITransport(report.download_app), base_url='https://reports.test') as client:
            for label, suffix in [('pdf', 'pdf'), ('word', 'docx')]:
                historical = await client.get(report.delivery[label]['downloadUrl'])
                assert historical.status_code == 200
                assert historical.content == (folder / 'parent' / f'c02-corrected.{suffix}').read_bytes()
        result = await editor.export_revision(report.context, expected_sha256=draft.sha256, settings={'sources': True})
        (folder / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        assert result['revision'] == report.context.revision + 1
        async with AsyncClient(transport=ASGITransport(report.download_app), base_url='https://reports.test') as client:
            for label, suffix in [('pdf', 'pdf'), ('word', 'docx')]:
                response = await client.get(result[label]['downloadUrl'])
                assert response.status_code == 200
                raw = response.content
                assert len(raw) == result[label]['size'] and hashlib.sha256(raw).hexdigest() == result[label]['sha256']
                (folder / f'edited.{suffix}').write_bytes(raw)
                if suffix == 'pdf':
                    text = '\n'.join(page.extract_text() or '' for page in PdfReader(BytesIO(raw)).pages)
                else:
                    text = '\n'.join(item.text for item in Document(BytesIO(raw)).paragraphs)
                (folder / f'{suffix}-text.txt').write_text(text)
                compact = re.sub(r'\s+', '', text)
                assert note in compact
                assert '建议核对采购付款安排，解释本期预算执行率时区分支付时点与计算公式。（建议，待核实）' in compact
                parent, _ = await runtime.workspace_service.afile_bytes(report.context.scope['threadId'], report.content[label + 'Path'])
                assert parent == (folder / 'parent' / f'c02-corrected.{suffix}').read_bytes()
        grant = urlsplit(result['editor']['openUrl']).path.rsplit('/', 1)[-1]
        _, session = await runtime.editor_grants.exchange(grant)
        context = await editor.context_for_session(session)
        document = await editor.read_document(context)
        current = await editor.trace.validate(context, document.markdown, document.sha256)
        assert any(item['kind'] == 'recommendation' and item['supportStatus'] == 'unverified'
            and not item['evidenceRefs'] for item in current['quality']['claimSupport'])
        (folder / 'current-after-export.json').write_text(json.dumps(current, ensure_ascii=False, indent=2, default=str))
        assert (await runtime.workspace_service.afile_bytes(report.context.scope['threadId'], report.context.markdown_path))[0].decode() == original.markdown
        (folder / 'edited.md').write_text(document.markdown)
        await archive_registered_sources(report, editor, context, folder / 'new-sources')
        await editor.aclose()

    await exercise_background_report(basis_context, document_context, receipt_snapshot, monkeypatch,
        'known', 'supported', delivery_format='document', after_native_report=inspect)


async def test_slides_edit_after_source_withdrawal_keeps_new_revision_explicitly_unverified(
    basis_context, document_context, receipt_snapshot, monkeypatch,
):
    from pptx import Presentation

    async def inspect(report):
        runtime = report.runtime
        folder = Path('/tmp') / f'smart-reporting-edit-withdrawal-{os.getpid()}-pptx'
        folder.mkdir(exist_ok=True)
        shutil.copytree(report.evidence_dir, folder / 'parent', dirs_exist_ok=True)
        await archive_registered_sources(report, report.editor, report.context, folder / 'parent')
        parent = (report.evidence_dir / 'c02-corrected.pptx').read_bytes()
        service = ReportSlidesEditorService(state_repository=runtime.state_repository,
            workspace_registry=runtime.workspace_registry, workspace=runtime.workspace_service,
            editor_grants=runtime.editor_grants, artifact_persistence=runtime.artifact_persistence,
            download_grants=runtime.download_grants, public_base_url='https://reports.test')
        grant, _ = await runtime.editor_grants.issue(report.context, capabilities={'pptx_editor': True})
        app = report.download_app
        app.include_router(create_report_slides_editor_router(runtime.editor_grants, slides=service,
            static_dir=Path(__file__).resolve().parents[1] / 'report_editor/static', cookie_secure=False))
        document = await report.editor.read_document(report.context)
        async with AsyncClient(transport=ASGITransport(app), base_url='https://reports.test') as client:
            opened = await client.get('/reports/v1/slides/open/' + grant)
            assert opened.status_code == 303
            prefix = opened.headers['location'] + '/api'
            response = await client.get(prefix + '/deck')
            assert response.status_code == 200
            deck = response.json()
            title = next(item for item in deck['slides'][0]['elements'] if item.get('text'))
            payload = {'expectedSha256': report.context.pptx_sha256, 'edits': [
                {'slideIndex': 0, 'elementId': title['id'], 'text': '预算执行报告 人工复核'}]}
            documents, token, scope = document_context[:3]
            detail = await documents.get_document(token, scope, 'known-context')
            await documents.review_revision(token, scope, 'known-context', 1, decision='revoked',
                reason='编辑后重新导出前撤销支持原件', expected_version=detail['revisions'][0]['stateVersion'])
            current = await report.editor.trace.validate(report.context, document.markdown, document.sha256)
            assert any(item['kind'] == 'recommendation' and item['supportStatus'] == 'unverified'
                and not item['evidenceRefs'] for item in current['quality']['claimSupport'])
            historical = await client.get(report.delivery['pptx']['downloadUrl'])
            assert historical.status_code == 200 and historical.content == parent
            response = await client.post(prefix + '/save', json=payload,
                headers={'X-CSRF-Token': client.cookies.get('report_slides_csrf')})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result['revision'] == report.context.revision + 1
            assert result['validation']['ok'] is False
            assert 'pptx_semantic_verification_pending' in {item['code'] for item in result['validation']['issues']}
            response = await client.get(result['pptx']['downloadUrl'])
            assert response.status_code == 200, response.text
            raw = response.content
        (folder / 'edited.pptx').write_bytes(raw)
        (folder / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        (folder / 'current-after-withdrawal.json').write_text(json.dumps(current, ensure_ascii=False, indent=2, default=str))
        assert len(raw) == result['pptx']['size'] and hashlib.sha256(raw).hexdigest() == result['pptx']['sha256']
        deck = Presentation(BytesIO(raw))
        text = '\n'.join(shape.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame)
        assert '预算执行报告 人工复核' in text and '70.00%' in text
        notice = '\n'.join(shape.text for shape in deck.slides[0].shapes if shape.has_text_frame)
        assert '本修订待核验' in notice and '尚未重新核验' in notice
        assert f'第 {result["revision"]} 版' in notice
        (folder / 'pptx-text.txt').write_text(text)
        parent_file, _ = await runtime.workspace_service.afile_bytes(report.context.scope['threadId'], report.context.pptx_path)
        assert parent_file == parent and await report.editor.read_document(report.context) == document
        _, session = await runtime.editor_grants.exchange(urlsplit(result['editor']['openUrl']).path.rsplit('/', 1)[-1])
        context = await service.context_for_session(session)
        assert context.revision == result['revision'] and context.pptx_sha256 == result['pptx']['sha256']
        assert context.job['validation']['ok'] is False and 'claimSupport' not in context.job['validation']
        (folder / 'new-context.json').write_text(context.model_dump_json(by_alias=True, indent=2))

    await exercise_background_report(basis_context, document_context, receipt_snapshot, monkeypatch,
        'known', 'supported', delivery_format='pptx', after_native_report=inspect)
