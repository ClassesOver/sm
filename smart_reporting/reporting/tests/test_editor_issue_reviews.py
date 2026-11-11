"""报告反馈入口沿用修订会话与CSRF，不能借请求扩大对象范围。"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.reporting.tests.test_editor_recalculation import native_editor


@pytest.mark.anyio
async def test_editor_issue_http_binds_source_objects_and_requires_write_session(tmp_path, monkeypatch):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.report_editor.api import EDITOR_SESSION_COOKIE, create_report_editor_router
    from smart_reporting.report_editor.service import (
        InMemoryReportEditorRepository,
        ReportEditorGrantService,
    )

    editor, repository, context, _ = await native_editor(tmp_path)
    source = await editor._source_context(context)
    index = await editor.trace.require_index(source)
    subject_id = index.subject_bindings[0].subject_id
    calls = []
    stored = []

    class Reviews:
        async def submit(self, **options):
            calls.append(options)
            if not set(options['payload']['objectRefs']) <= set(options['allowed_object_refs']):
                raise ManagementError('management_issue_scope_mismatch', '只能反馈本报告对象', 403)
            result = {'review': {**options['payload'], 'status': 'open'}, 'version': 1}
            stored.append(result)
            return result

        async def report_list(self, **options):
            calls.append(options)
            return {'items': stored, 'nextCursor': None}

    reviews = Reviews()
    editor.trace.report_basis_service = SimpleNamespace()
    monkeypatch.setattr('smart_reporting.management.report_issue_reviews.ReportIssueReviewService', lambda bases: reviews)
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    path = f'/reports/v1/editor/{context.report_id}/{context.revision}/api/issue-reviews'
    payload = {'issueId': 'issue-C02', 'objectRefs': [subject_id], 'category': 'calculation', 'description': '比例汇总可能有误'}
    before = repository.state.model_dump(mode='json')
    async with AsyncClient(transport=ASGITransport(app), base_url='http://reports.test') as client:
        assert (await client.get(path)).status_code == 404
        assert (await client.post(path, json=payload)).status_code == 403
        await client.get(f'/reports/v1/editor/open/{raw}', follow_redirects=False)
        assert (await client.post(path, json=payload)).status_code == 403
        assert not calls
        headers = {'origin': 'http://reports.test', 'x-csrf-token': grants.csrf_token(client.cookies.get(EDITOR_SESSION_COOKIE))}
        response = await client.post(path, json=payload, headers=headers)
        assert response.status_code == 200 and response.json()['review']['status'] == 'open'
        assert response.headers['cache-control'] == 'no-store'
        binding = calls[0]
        assert binding['run_id'] == source.workflow_run_id
        assert binding['basis_id'] == index.report_basis_id
        assert binding['report_id'] == context.report_id and binding['revision'] == context.revision
        assert binding['user_id'] == source.scope['userId'] and binding['thread_id'] == source.scope['callerThreadId']
        assert set(binding['allowed_object_refs']) == {index.report_basis_id, *(x.subject_id for x in index.subject_bindings)}
        listed = await client.get(path)
        assert listed.status_code == 200 and listed.json()['items'] == [response.json()]
        assert listed.headers['cache-control'] == 'no-store'
        assert (await client.post(path, json={**payload, 'status': 'resolved'}, headers=headers)).status_code == 422
        assert (await client.post(path, json={**payload, 'objectRefs': ['foreign-object']}, headers=headers)).status_code == 403
        assert (await client.get(path.replace(context.report_id, 'foreign-report'))).status_code == 404
        assert (await client.post(path.replace(context.report_id, 'foreign-report'), json=payload, headers=headers)).status_code == 403
    assert repository.state.model_dump(mode='json') == before
