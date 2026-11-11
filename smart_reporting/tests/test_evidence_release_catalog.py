"""已发布集合目录：组织隔离、真实分页、当前审核状态与原读回契约。"""

import httpx
import pytest
from fastapi import FastAPI

from smart_reporting.management.api import SESSION_COOKIE
from smart_reporting.reporting.business_knowledge.retrieval import DocumentRevisionRef
from smart_reporting.reporting.tests.test_business_evidence_index import (
    index_context as index_context,
)
from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_business_document_ingestion import metadata, register
from smart_reporting.tests.test_business_evidence_publication import (
    approved_document,
    evidence_service,
    publish,
)
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_catalog_is_scoped_paginated_filtered_and_marks_revoked_members(document_context, index_context):
    await approved_document(document_context)
    service = evidence_service(document_context, index_context)
    documents, token, scope, other, *_ = document_context
    first = await publish(service, document_context, request_id='release-one')
    second = await publish(service, document_context, request_id='release-two')
    await register(document_context, request_id='background-upload', details=metadata(id='background', title='预算变化背景', kind='background'))
    await documents.ingest_revision(await documents.claim_next())
    detail = await documents.get_document(token, scope, 'background')
    await documents.review_revision(token, scope, 'background', 1, decision='approved', reason='合成原件核对', expected_version=detail['revisions'][0]['stateVersion'])
    background = await service.publish(token, scope, request_id='background-release', kind='background', revision_ids=(DocumentRevisionRef(document_id='background', revision=1),))
    # 同名文档和发布请求在另一组织单独登记，不得进入本组织目录。
    foreign_context = (documents, token, other, scope, document_context[5], document_context[4])
    await approved_document(foreign_context)
    foreign = await publish(service, foreign_context, request_id='release-one')
    seen, cursor = [], None
    while True:
        page = await service.list_releases(token, scope, kind='rule_evidence', limit=1, after=cursor)
        seen.extend(page['items'])
        cursor = page['nextCursor']
        if cursor is None:
            break
    assert {item['releaseId'] for item in seen} == {first.release_id, second.release_id}
    assert all(item['kind'] == 'rule_evidence' and item['availableForSelection'] for item in seen)
    assert all(item['documents'] == [{'documentId': 'budget-rules', 'revision': 1, 'title': '合成预算制度', 'reviewStatus': 'approved', 'ingestionStatus': 'ready'}] for item in seen)
    assert (await service.list_releases(token, scope, kind='background'))['items'][0]['releaseId'] == background.release_id
    assert {i['releaseId'] for i in (await service.list_releases(token, scope, query='合成预算制度'))['items']} == {first.release_id, second.release_id}
    assert (await service.list_releases(token, scope, query='%'))['items'] == []
    assert (await service.list_releases(token, scope, query=foreign.release_id))['items'] == []
    assert [i['releaseId'] for i in (await service.list_releases(token, other))['items']] == [foreign.release_id]
    current = await documents.get_document(token, scope, 'budget-rules')
    await documents.review_revision(token, scope, 'budget-rules', 1, decision='revoked', reason='合成撤销', expected_version=current['revisions'][0]['stateVersion'])
    unavailable = await service.list_releases(token, scope, kind='rule_evidence')
    assert all(not item['availableForSelection'] and item['documents'][0]['reviewStatus'] == 'revoked' for item in unavailable['items'])
    assert await service.get(token, scope, first.release_id) == first


async def test_catalog_http_auth_validation_no_store_and_original_request_readback(document_context, index_context):
    from smart_reporting.management.business_evidence_api import create_business_evidence_router
    from smart_reporting.management.settings import ManagementSettings

    await approved_document(document_context)
    service = evidence_service(document_context, index_context)
    release = await publish(service, document_context)
    app = FastAPI()
    app.include_router(create_business_evidence_router(service, ManagementSettings(public_origin='https://reports.example')))
    base = '/management/api/v1/business-evidence-releases'
    params = {'scopeDatabase': 'warehouse', 'companyId': 'a'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://reports.example') as client:
        assert (await client.get(base + '/catalog', params=params)).status_code == 401
        client.cookies.set(SESSION_COOKIE, document_context[1], path='/management')
        result = await client.get(base + '/catalog', params={**params, 'kind': 'rule_evidence', 'limit': 1})
        assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
        assert result.json()['items'][0]['releaseId'] == release.release_id
        for invalid in ({'limit': 0}, {'kind': 'other'}, {'after': 'x' * 129}, {'q': 'x' * 201}):
            assert (await client.get(base + '/catalog', params={**params, **invalid})).status_code == 422
        assert (await client.get(base + '/catalog', params={**params, 'companyId': 'b'})).json()['items'] == []
        readback = await client.get(base, params={**params, 'requestId': 'release-1'})
        assert readback.json() == release.model_dump(mode='json', by_alias=True)
        assert (await client.get(base + '/' + release.release_id, params=params)).status_code == 200
