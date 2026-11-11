"""原件管理目录只返回当前组织最新修订摘要，不暴露原文和存储路径。"""

import httpx
import pytest
from fastapi import FastAPI

from smart_reporting.management.api import SESSION_COOKIE
from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_business_document_ingestion import metadata, register
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

@pytest.fixture
def anyio_backend():
    return 'asyncio'

async def test_catalog_lists_latest_revision_with_scoped_literal_search_and_pagination(document_context):
    service, token, scope, other, *_ = document_context
    await register(document_context)
    await register(document_context, 'revision-two', expected_version=1, details=metadata(title='预算制度修订'))
    await register(document_context, 'background', details=metadata(id='background', title='预算背景', kind='background'))
    foreign = (service, token, other, scope, document_context[5], document_context[4])
    await register(foreign, details=metadata(title='其他组织的同名制度'))
    first = await service.list_documents(token, scope, limit=1)
    assert first['items'][0]['documentId'] == 'background'
    second = await service.list_documents(token, scope, limit=1, after=first['nextCursor'])
    assert second['nextCursor'] is None
    row = second['items'][0]
    assert row['documentId'] == 'budget-rules' and row['revision'] == row['version'] == 2
    assert row['title'] == '预算制度修订' and row['kind'] == 'rule_evidence'
    assert row['reviewStatus'] == 'pending' and row['ingestionStatus'] == 'queued'
    assert not {'parseReceipt', 'originalHash', 'originalResourceId', 'document'} & row.keys()
    assert (await service.list_documents(token, scope, query='预算制度修订'))['items'] == [row]
    assert (await service.list_documents(token, scope, query='%'))['items'] == []
    assert (await service.list_documents(token, scope, kind='background'))['items'] == first['items']
    assert (await service.list_documents(token, scope, review_status='approved'))['items'] == []
    assert (await service.list_documents(token, other))['items'][0]['title'] == '其他组织的同名制度'

async def test_catalog_http_auth_validation_and_no_store(document_context):
    from smart_reporting.management.business_documents_api import create_business_documents_router
    from smart_reporting.management.settings import ManagementSettings
    service, token, scope, *_ = document_context
    await register(document_context)
    app = FastAPI()
    app.include_router(create_business_documents_router(service, ManagementSettings(public_origin='https://reports.example')))
    path = '/management/api/v1/business-documents'
    params = {'scopeDatabase': scope.database, 'companyId': scope.company_id}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://reports.example') as client:
        assert (await client.get(path, params=params)).status_code == 401
        client.cookies.set(SESSION_COOKIE, token, path='/management')
        result = await client.get(path, params=params)
        assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
        assert len(result.json()['items']) == 1
        for invalid in ({'limit':0}, {'q':'x'*201}, {'kind':'bad'}, {'reviewStatus':'bad'}, {'after':'x'*129}):
            assert (await client.get(path, params={**params, **invalid})).status_code == 422
        assert (await client.get(path, params={**params,'companyId':'b'})).json()['items'] == []
        assert (await client.get(path+'/budget-rules', params=params)).status_code == 200
