"""上传响应未知时按组织和原请求读取登记事实，不重新写入。"""

import hashlib

import httpx
import pytest
from fastapi import FastAPI

from smart_reporting.management.api import SESSION_COOKIE
from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_business_document_ingestion import register
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_upload_request_readback_retains_exact_identity_after_processing_and_scope_isolation(document_context):
    from smart_reporting.management.models import ManagementError

    service, token, scope, other, *_ = document_context
    content = '执行额合计除以预算额合计'.encode()
    uploaded = await register(document_context, request_id='unknown-upload', body=content)
    await service.ingest_revision(await service.claim_next())
    result = await service.get_registration(token, scope, 'unknown-upload')
    assert result['requestId'] == 'unknown-upload'
    assert result['receipt']['documentId'] == 'budget-rules'
    assert result['receipt']['jobId'] == uploaded.job_id and result['receipt']['revision'] == 1
    assert result['receipt']['status'] == 'parsed'
    assert result['expectedVersion'] == 0 and result['filename'] == 'rules.txt'
    assert result['originalHash'] == hashlib.sha256(content).hexdigest()
    assert result['metadata']['id'] == 'budget-rules'
    assert result['metadata']['kind'] == 'rule_evidence'
    assert 'original_resource_id' not in str(result) and 'parseReceipt' not in result
    with pytest.raises(ManagementError) as foreign:
        await service.get_registration(token, other, 'unknown-upload')
    assert foreign.value.status == 404
    assert await service.read_original(token, scope, 'budget-rules', 1) == content


async def test_upload_request_http_requires_session_scope_valid_id_and_is_read_only(document_context):
    from smart_reporting.management.business_documents_api import create_business_documents_router
    from smart_reporting.management.settings import ManagementSettings

    service, token, scope, *_ = document_context
    await register(document_context)
    app = FastAPI()
    app.include_router(create_business_documents_router(service, ManagementSettings(public_origin='https://reports.example')))
    path = '/management/api/v1/business-document-requests/'
    params = {'scopeDatabase': scope.database, 'companyId': scope.company_id}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://reports.example') as client:
        assert (await client.get(path+'upload-1', params=params)).status_code == 401
        client.cookies.set(SESSION_COOKIE, token, path='/management')
        found = await client.get(path+'upload-1', params=params)
        assert found.status_code == 200 and found.headers['cache-control'] == 'no-store'
        assert found.json()['requestId'] == 'upload-1'
        assert (await client.get(path+'missing', params=params)).status_code == 404
        assert (await client.get(path+'upload-1', params={**params, 'companyId':'b'})).status_code == 404
        assert (await client.get(path+'invalid%20id', params=params)).status_code == 422
