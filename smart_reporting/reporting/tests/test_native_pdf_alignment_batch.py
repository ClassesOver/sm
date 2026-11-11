import base64
import hashlib
from io import BytesIO
import json
from zipfile import ZipFile

import pytest
from httpx import ASGITransport,AsyncClient
from pypdf import PdfReader

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_protection import protection_client
from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture
from smart_reporting.reporting.tests.test_pdf_external_pages import pdf
from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.mark.anyio
@pytest.mark.parametrize('kind',['createFormField','editFormFieldRequired','editFormWidget','arrangeFormWidgets','appendRadioWidget','editFormTextProperties','transformExistingImage'])
async def test_pdf_object_design_requires_actual_preview_confirmation_before_reserving(tmp_path,kind):
    editor,context,_,_=await fixture(tmp_path)
    with pytest.raises(ReportingError) as caught:
        await editor.save(context,request_id='unconfirmed-design',expected_sha256=context.source_file.sha256,operations=[{'kind':kind}])
    assert caught.value.code=='native_pdf_text_confirmation_required'
    assert not editor.repository.rows

@pytest.mark.anyio
@pytest.mark.parametrize('action,options,count',[('insert',{'afterPage':1},3),('replace',{'pages':[1]},2)])
async def test_external_pages_http_delivers_real_foreign_pages(tmp_path,action,options,count):
    editor,context,source,app,base,token=await protection_client(tmp_path)
    foreign=pdf('foreign',2)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE,token,path=base)
        response=await client.post(base+'/api/external-pages',headers={'Origin':'http://test','X-CSRF-Token':editor.grants.csrf_token(token)},json={'requestId':'external-'+action,'expectedSha256':context.source_file.sha256,'action':action,'externalSha256':hashlib.sha256(foreign).hexdigest(),'bytesBase64':base64.b64encode(foreign).decode(),**options})
        assert response.status_code==200,response.text
        saved=response.json();artifact=saved['artifacts']['pdf']
        downloaded=await client.get(artifact['downloadUrl'])
        assert downloaded.status_code==200 and hashlib.sha256(downloaded.content).hexdigest()==artifact['sha256']
        reader=PdfReader(BytesIO(downloaded.content));assert len(reader.pages)==count
        text=' '.join(page.extract_text() for page in reader.pages)
        assert 'foreign 1' in text and 'foreign 2' in text
        assert ('Amount due 500' in text)==(action=='insert')
        assert await editor.read_file(context)==source

@pytest.mark.anyio
@pytest.mark.parametrize('patch,status',[
    ({'pages':[0]},422),({'pages':[1,1]},422),({'dpi':True},422),
    ({'format':'pptx'},422),({'expectedSha256':'0'*64},409),
])
async def test_pdf_images_http_rejects_invalid_export_parameters(tmp_path,patch,status):
    editor,context,_,app,base,token=await protection_client(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE,token,path=base)
        response=await client.post(base+'/api/export-images',headers={'Origin':'http://test','X-CSRF-Token':editor.grants.csrf_token(token)},json={'expectedSha256':context.source_file.sha256,'pages':[1],'format':'png','dpi':144,**patch})
        assert response.status_code==status,response.text

@pytest.mark.anyio
@pytest.mark.parametrize('image_format',['png','jpeg'])
async def test_pdf_images_http_returns_verified_zip_without_changing_source(tmp_path,image_format):
    editor,context,source,app,base,token=await protection_client(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE,token,path=base)
        payload={'expectedSha256':context.source_file.sha256,'pages':[1],'format':image_format,'dpi':144}
        assert (await client.post(base+'/api/export-images',json=payload)).status_code==403
        response=await client.post(base+'/api/export-images',headers={'Origin':'http://test','X-CSRF-Token':editor.grants.csrf_token(token)},json=payload)
        assert response.status_code==200,response.text
        assert response.headers['x-native-export-sha256']==hashlib.sha256(response.content).hexdigest()
        assert int(response.headers['x-native-export-size'])==len(response.content)
        assert response.headers['x-native-source-sha256']==context.source_file.sha256
        with ZipFile(BytesIO(response.content)) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            assert manifest['pages']==[1] and manifest['format']==image_format
            entry=manifest['images'][0];raw=archive.read(entry['name'])
            assert hashlib.sha256(raw).hexdigest()==entry['sha256']
            assert raw.startswith(b'\x89PNG' if image_format=='png' else b'\xff\xd8')
        assert await editor.read_file(context)==source
