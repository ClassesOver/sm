"""Word structure HTTP/file acceptance with actual native SQL and isolated fixtures."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from docx import Document
from docx.oxml.ns import qn
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from lxml import etree
from sqlalchemy import text

from scripts.probe_native_docx_tables import fixture
from smart_reporting.app import require_workspace_capability
from smart_reporting.report_editor import native_publication
from smart_reporting.report_editor.native import NativeEditorService
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_import import NativeImportService
from smart_reporting.report_editor.native_import_api import create_native_import_router
from smart_reporting.report_editor.native_models import NativeScope
from smart_reporting.report_editor.repository import SqlAlchemyReportEditorRepository
from smart_reporting.report_editor.service import ReportEditorGrantService
from smart_reporting.reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportDownloadGrantService,
    ReportDownloadHttpService,
    SqlAlchemyDownloadGrantRepository,
    SqlAlchemyReportArtifactRepository,
)
from smart_reporting.reporting.tests import test_native_repository_postgres_integration as sql_tests
from smart_reporting.reporting.tests.test_native_publication_nonblocking import create_publication
from smart_reporting.tests.test_reporting_request_identity import SECRET, _capability

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
postgres_repositories = sql_tests.postgres_repositories
anyio_backend = sql_tests.anyio_backend


def digest(content):
    return hashlib.sha256(content).hexdigest()


def four_tables(path):
    fixture(path)
    doc = Document(path)
    table = doc.tables[0]
    for node, width in zip(table._tbl.tblGrid, [2401, 3000, 3599], strict=True):
        node.set(qn('w:w'), str(width))
    for row in table.rows:
        for cell, width in zip(row.cells, [2401, 3000, 3599], strict=True):
            cell._tc.get_or_add_tcPr().find(qn('w:tcW')).set(qn('w:w'), str(width))
    for _ in range(3):
        doc._element.body.insert(len(doc._element.body) - 1, deepcopy(table._tbl))
    doc.save(path)
    return path.read_bytes()


def structural_ops(model):
    tables = [block for block in model['blocks'] if block['type'] == 'table']
    kinds = ['insertTableRow', 'deleteTableRow', 'insertTableColumn', 'deleteTableColumn']
    assert len(tables) == 4 and all(table['structureEditable'] for table in tables)
    return [{'kind': kind, 'blockId': table['blockId'], 'expectedObjectSha256': table['expectedObjectSha256'], 'index': 1}
            for table, kind in zip(tables, kinds, strict=True)]


def readback(original, result, *, followup=False):
    before, after = Document(BytesIO(original)), Document(BytesIO(result))
    expected_widths = [[2401, 3000, 3599], [2401, 3000, 3599], [2401, 1500, 1500, 3599], [2401, 6599]]
    report = []
    for index, table in enumerate(after.tables):
        expected = [[f'R{r}C{c}' for c in range(3)] for r in range(3)]
        widths = expected_widths[index]
        if index == 0:
            expected.insert(1, ['', '', ''])
            if followup:
                for row in expected:
                    row.insert(0, '')
                widths = [1200, 1201, 3000, 3599]
        elif index == 1:
            expected.pop(1)
        elif index == 2:
            for row in expected:
                row.insert(1, '')
        else:
            for row in expected:
                row.pop(1)
        matrix = [[cell.text for cell in row.cells] for row in table.rows]
        assert matrix == expected
        assert [int(node.get(qn('w:w'))) for node in table._tbl.tblGrid] == widths
        source_paragraphs = {cell.text: [etree.tostring(p._p, method='c14n') for p in cell.paragraphs]
                             for row in before.tables[index].rows for cell in row.cells}
        for row in table.rows:
            for ci, cell in enumerate(row.cells):
                assert int(cell._tc.get_or_add_tcPr().find(qn('w:tcW')).get(qn('w:w'))) == widths[ci]
                if cell.text:
                    assert [etree.tostring(p._p, method='c14n') for p in cell.paragraphs] == source_paragraphs[cell.text]
        report.append({'table': index, 'matrix': matrix, 'widthsTwips': widths})
    assert [p.text for p in after.paragraphs] == [p.text for p in before.paragraphs]
    from zipfile import ZipFile
    with ZipFile(BytesIO(original)) as a, ZipFile(BytesIO(result)) as b:
        names = {name for name in a.namelist() if not name.endswith('/')}
        assert names == {name for name in b.namelist() if not name.endswith('/')}
        for name in names - {'word/document.xml', 'docProps/core.xml'}:
            assert a.read(name) == b.read(name), name
    return report


@pytest.mark.parametrize('delivery_store', ['memory', 'postgres'])
async def test_word_structure_sql_failure_retry_concurrent_save_and_revision_chain(postgres_repositories, tmp_path, monkeypatch, delivery_store):
    repo, independent = postgres_repositories
    evidence_dir = Path(os.environ['NATIVE_SQL_EVIDENCE_DIR']) if os.environ.get('NATIVE_SQL_EVIDENCE_DIR') else None
    if evidence_dir:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / 'evidence.json').write_text(json.dumps({'ok': False, 'reason': 'acceptance_not_completed'}))
    publication, _, downloads = await create_publication(tmp_path)
    publication.repository = repo
    if delivery_store == 'postgres':
        grants = SqlAlchemyDownloadGrantRepository(repo.engine)
        editor_repository = SqlAlchemyReportEditorRepository(repo.engine)
        await grants.create_schema()
        await editor_repository.create_schema()
        artifacts = SqlAlchemyReportArtifactRepository(repo.engine)
        publication.download_grants = ReportDownloadGrantService(grants)
        publication.editor_grants = ReportEditorGrantService(editor_repository, secret='public-test-only-editor-secret-0123456789')
        publication.artifact_persistence = ReportArtifactPersistenceService(artifacts, publication.workspace)
        downloads = ReportDownloadHttpService(publication.download_grants, artifacts, workspace_service=publication.workspace)
    publication.validator = AsyncMock(side_effect=RuntimeError('public-test-only-review-failure'))
    editor = NativeEditorService(publication.workspace, repo, publication.editor_grants, report_editor=None,
                                 docx_enabled=True, publication=publication)
    importer = NativeImportService(publication.workspace, repo, publication.editor_grants)
    app = FastAPI()
    app.state.agentos_context = SimpleNamespace(settings=SimpleNamespace(workspace_hmac_secret=SECRET))
    app.middleware('http')(require_workspace_capability)
    app.include_router(create_native_import_router(importer, enabled=True))
    app.include_router(create_native_editor_router(publication.editor_grants, editor=editor, download_service=downloads, cookie_secure=False))
    original = four_tables(tmp_path / 'four-tables.docx')
    engine_calls = 0
    actual_patch = native_publication.patch_docx

    def fail_first_patch(content, operations):
        nonlocal engine_calls
        engine_calls += 1
        if engine_calls == 1:
            raise ValueError('public-test-only-transient-engine-failure')
        return actual_patch(content, operations)

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        uploaded = await client.post('/reports/v1/native/import', headers={'X-Workspace-Thread': 'thread-1', 'X-Workspace-Capability': _capability()},
                                     data={'requestId': 'word-tables-import'}, files={'file': ('tables.docx', original)})
        assert uploaded.status_code == 200, uploaded.text
        opened = await client.get(uploaded.json()['editor']['url'], follow_redirects=True)
        assert opened.status_code == 200
        base = opened.url.path + '/api'
        context = (await client.get(base + '/context')).json()
        document_id = context['context']['documentId']
        headers = {'Origin': 'http://test', 'X-CSRF-Token': context['csrfToken']}
        preview = await client.post(base + '/preview', headers=headers, json={'expectedSha256': digest(original), 'operations': []})
        assert preview.status_code == 200, preview.text
        operations = structural_ops(preview.json()['model'])
        payload = {'expectedSha256': digest(original), 'operations': operations, 'requestId': 'word-tables-save'}
        stale = await client.post(base + '/save', headers=headers, json={**payload, 'expectedSha256': 'f' * 64})
        assert stale.status_code == 409
        mixed = await client.post(base + '/preview', headers=headers, json={'expectedSha256': digest(original), 'operations': [operations[0], operations[0]]})
        assert mixed.status_code == 422 and 'batch_conflict' in mixed.text
        assert await sql_tests.database_state(independent, document_id) == (2, 1)
        monkeypatch.setattr(native_publication, 'patch_docx', fail_first_patch)
        failed = await client.post(base + '/save', headers=headers, json=payload)
        assert failed.status_code == 422, failed.text
        assert await sql_tests.database_state(independent, document_id) == (3, 2)
        async with independent.engine.connect() as connection:
            failure = (await connection.execute(text('SELECT status, failure_code FROM report_native_revisions_v1 WHERE revision = 2'))).one()
        assert tuple(failure) == ('failed', 'native_engine_failed')
        responses = await asyncio.gather(*(client.post(base + '/save', headers=headers, json=payload) for _ in range(2)))
        for response in responses:
            assert response.status_code == 200, response.text
            assert response.json()['revision'] == 2 and response.json()['revisionRegistered']
            assert response.json()['validation']['ok'] is False
        result = responses[0].json()
        artifact = result['artifacts']['word']
        assert responses[1].json()['artifacts']['word']['sha256'] == artifact['sha256']
        assert engine_calls == 2  # One injected failure, one actual transformation; saved retry does no work.
        assert await sql_tests.database_state(independent, document_id) == (3, 2)
        # Same-revision retry intentionally rotates/revokes the previous grant.
        # Verify the active returned grant, rather than treating a revoked token as current.
        download_attempts = [await client.get(response.json()['artifacts']['word']['downloadUrl']) for response in responses]
        assert sorted(response.status_code for response in download_attempts) == [200, 403]
        downloaded = next(response for response in download_attempts if response.status_code == 200)
        assert digest(downloaded.content) == artifact['sha256']
        report2 = readback(original, downloaded.content)
        assert (await client.get(base + '/file')).content == original
        conflict = await client.post(base + '/save', headers=headers, json={**payload, 'note': 'changed retry identity'})
        assert conflict.status_code == 409, conflict.text
        assert await sql_tests.database_state(independent, document_id) == (3, 2)
        opened2 = await client.get(result['editor']['openUrl'], follow_redirects=True)
        base2 = opened2.url.path + '/api'
        context2 = (await client.get(base2 + '/context')).json()
        headers2 = {'Origin': 'http://test', 'X-CSRF-Token': context2['csrfToken']}
        preview2 = await client.post(base2 + '/preview', headers=headers2, json={'expectedSha256': artifact['sha256'], 'operations': []})
        assert preview2.status_code == 200
        old_anchor = await client.post(base2 + '/preview', headers=headers2, json={'expectedSha256': artifact['sha256'], 'operations': [operations[0]]})
        assert old_anchor.status_code == 422
        fresh_table = next(block for block in preview2.json()['model']['blocks'] if block['type'] == 'table')
        fresh_op = {'kind': 'insertTableColumn', 'blockId': fresh_table['blockId'], 'expectedObjectSha256': fresh_table['expectedObjectSha256'], 'index': 0}
        result3 = await client.post(base2 + '/save', headers=headers2, json={'expectedSha256': artifact['sha256'], 'operations': [fresh_op], 'requestId': 'word-tables-followup'})
        assert result3.status_code == 200, result3.text
        result3 = result3.json()
        assert result3['revision'] == 3 and result3['parentRevision'] == 2 and result3['revisionRegistered']
        artifact3 = result3['artifacts']['word']
        downloaded3 = await client.get(artifact3['downloadUrl'])
        assert downloaded3.status_code == 200 and digest(downloaded3.content) == artifact3['sha256']
        report3 = readback(original, downloaded3.content, followup=True)
        assert engine_calls == 3
        assert (await client.get(base2 + '/file')).content == downloaded.content
        assert (await client.get(base + '/file')).content == original
        opened3 = await client.get(result3['editor']['openUrl'], follow_redirects=True)
        assert (await client.get(opened3.url.path + '/api/file')).content == downloaded3.content
        assert await sql_tests.database_state(independent, document_id) == (4, 3)
        scope = NativeScope.model_validate(context['context']['scope'])
        revision2 = await independent.get_revision(document_id, 2, scope=scope)
        revision3 = await independent.get_revision(document_id, 3, scope=scope)
        assert revision2.context.source_file.sha256 == digest(downloaded.content)
        assert revision3.context.source_file.sha256 == digest(downloaded3.content)
        assert revision2.status == revision3.status == 'saved'
        assert revision3.parent_revision == 2 and revision3.request_id == 'word-tables-followup'
        assert revision2.failure_code is None and revision3.failure_code is None
        assert revision2.validation.ok is False and revision3.validation.ok is False
        for revision in (revision2, revision3):
            assert 'native_validation_failed' in {issue.code for issue in revision.validation.issues}
        assert await independent.get_revision(document_id, 3, scope=scope.model_copy(update={'user_id': 'foreign'})) is None
        async with independent.engine.connect() as connection:
            version = (await connection.execute(text('SELECT version()'))).scalar_one()
            rows = (await connection.execute(text('SELECT revision, parent_revision, status, failure_code FROM report_native_revisions_v1 ORDER BY revision'))).mappings().all()
        delivery_evidence = {'store': delivery_store}
        if delivery_store == 'postgres':
            async with independent.engine.connect() as connection:
                persisted_files = (await connection.execute(text('SELECT artifact_key, revision, size, sha256 FROM report_artifact_files_v1 ORDER BY revision'))).mappings().all()
                assert [row['revision'] for row in persisted_files] == [2, 3]
                for row, content in zip(persisted_files, (downloaded.content, downloaded3.content), strict=True):
                    chunks = (await connection.execute(text('SELECT content FROM report_artifact_chunks_v1 WHERE artifact_key = :key ORDER BY chunk_index'), {'key': row['artifact_key']})).scalars().all()
                    assert b''.join(chunks) == content and row['size'] == len(content) and row['sha256'] == digest(content)
                grants = (await connection.execute(text('SELECT revision, revoked_at IS NOT NULL AS revoked FROM report_download_grants_v2 ORDER BY revision, revoked_at IS NULL'))).mappings().all()
                assert [(row['revision'], row['revoked']) for row in grants] == [(2, True), (2, False), (3, False)]
                session_count = (await connection.execute(text('SELECT count(*) FROM report_editor_sessions_v1'))).scalar_one()
                editor_grant_count = (await connection.execute(text('SELECT count(*) FROM report_editor_grants_v1'))).scalar_one()
                assert session_count >= 3 and editor_grant_count >= 3
            delivery_evidence.update({'persistedFiles': [dict(row) for row in persisted_files], 'downloadGrants': [dict(row) for row in grants],
                                      'editorSessions': session_count, 'editorGrants': editor_grant_count, 'chunkBytesIndependentlyVerified': True})
        receipt = {'ok': True, 'postgresVersion': version, 'sourceSha256': digest(original), 'revision2Sha256': digest(downloaded.content),
                   'revision3Sha256': digest(downloaded3.content), 'engineCalls': engine_calls, 'nextRevision': 4,
                   'rows': [dict(row) for row in rows], 'revision2Readback': report2, 'revision3Readback': report3,
                   'failureObserved': list(failure), 'concurrentHttpRequests': 2,
                   'concurrentDownloadStatuses': [response.status_code for response in download_attempts],
                   'delivery': delivery_evidence, 'provenance': 'real native PostgreSQL and engines; in-process ASGI; delivery_store selects actual SQL or explicit doubles', 'desktopVerified': False}
        if evidence_dir:
            for name, content in [('source.docx', original), ('revision-2.docx', downloaded.content), ('revision-3.docx', downloaded3.content)]:
                (evidence_dir / name).write_bytes(content)
            (evidence_dir / 'evidence.json').write_text(json.dumps(receipt, indent=2))
