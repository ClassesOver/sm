"""上传工作簿/演示文稿沿用原生独立修订和非阻断交付。"""
from io import BytesIO
import hashlib
from unittest.mock import AsyncMock

import pytest
from openpyxl import Workbook, load_workbook
from pptx import Presentation
from pptx.util import Inches

from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.report_editor.native_models import NativeEditorContext, NATIVE_MEDIA
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.tests.test_native_publication_nonblocking import create_publication

@pytest.fixture
def anyio_backend(): return 'asyncio'

@pytest.mark.anyio
@pytest.mark.parametrize('format',['xlsx','pptx'])
async def test_office_native_save_keeps_download_when_validation_fails(tmp_path,format):
    service,old,downloads=await create_publication(tmp_path)
    stream=BytesIO()
    if format=='xlsx':
        book=Workbook();book.active['A1']='原文';book.save(stream)
        operations=[{'kind':'applyCellEdits','edits':[{'sheetName':'Sheet','row':0,'column':0,'writeValue':True,'cell':{'value':'修改后'}}]}]
    else:
        deck=Presentation();slide=deck.slides.add_slide(deck.slide_layouts[6]);box=slide.shapes.add_textbox(Inches(1),Inches(1),Inches(3),Inches(1));box.text='原文';deck.save(stream)
        from smart_reporting.report_editor.slides import ReportSlidesEditorService
        info=ReportSlidesEditorService._run_engine(stream.getvalue(),'inspect')
        element=info['slides'][0]['elements'][0]
        operations=[{'kind':'editSlides','edits':[{'slideIndex':0,'elementId':element['id'],'text':'修改后'}]}]
    source=stream.getvalue();key=bind_native_workspace(service.workspace,old.scope)
    path=f'native/original.{format}';await service.workspace.awrite_bytes(key,path,source)
    context=NativeEditorContext(documentId='document',revision=1,format=format,origin='upload',scope=old.scope,sourceFile=ArtifactFile(path=path,size=len(source),sha256=hashlib.sha256(source).hexdigest(),mediaType=NATIVE_MEDIA[format]))
    service.validator=AsyncMock(side_effect=RuntimeError('validation unavailable'))
    result=await service.save_revision(context,operations=operations,request_id='save',expected_sha256=context.source_file.sha256)
    assert not result['validation']['ok']
    assert result['revisionRegistered'] is True
    assert result['artifacts'][format]['downloadUrl']
    assert 'editor' in result
    url=result['artifacts'][format]['downloadUrl'];raw=url.split('/')[-2]
    _,chunks=await downloads.stream(raw,artifact=format);changed=b''.join([chunk async for chunk in chunks])
    assert hashlib.sha256(changed).hexdigest()==result['artifacts'][format]['sha256']
    if format=='xlsx': assert load_workbook(BytesIO(changed)).active['A1'].value=='修改后'
    else: assert '修改后' in '\n'.join(shape.text for shape in Presentation(BytesIO(changed)).slides[0].shapes if shape.has_text_frame)
    assert (await service.workspace.afile_bytes(key,path))[0]==source
    retry=await service.save_revision(context,operations=operations,request_id='save',expected_sha256=context.source_file.sha256)
    assert retry['revision']==result['revision']


@pytest.mark.anyio
@pytest.mark.parametrize('format',['xlsx','pptx'])
async def test_office_native_http_session_download_survives_disabled_editing(tmp_path,format):
    from fastapi import FastAPI
    from httpx import AsyncClient,ASGITransport
    from smart_reporting.report_editor.native import NativeEditorService
    from smart_reporting.report_editor.native_api import create_native_editor_router
    from smart_reporting.report_editor.native_import import NativeImportService
    from smart_reporting.reporting.tests.test_native_editor_api import Repository
    publication,old,downloads=await create_publication(tmp_path)
    repository=Repository();publication.repository=repository
    editor=NativeEditorService(publication.workspace,repository,publication.editor_grants,office_enabled=True,publication=publication)
    stream=BytesIO()
    if format=='xlsx': book=Workbook();book.active['A1']='original';book.save(stream)
    else: deck=Presentation();slide=deck.slides.add_slide(deck.slide_layouts[6]);slide.shapes.add_textbox(Inches(1),Inches(1),Inches(2),Inches(1)).text='original';deck.save(stream)
    source=stream.getvalue()
    opened=await NativeImportService(publication.workspace,repository,publication.editor_grants).import_file(old.scope,source,request_id='upload')
    app=FastAPI();app.include_router(create_native_editor_router(publication.editor_grants,editor=editor,download_service=downloads,cookie_secure=False))
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get(opened['editor']['url'],follow_redirects=True)).status_code==200
        base=f"/reports/v1/native/{opened['documentId']}/1/api"
        context=(await client.get(base+'/context')).json()
        assert context['editingEnabled'] and context['context']['format']==format
        preview=await client.post(base+'/preview',json={'expectedSha256':hashlib.sha256(source).hexdigest(),'operations':[]},headers={'Origin':'http://test','X-CSRF-Token':context['csrfToken']})
        assert preview.status_code==200,preview.text
        editor.office_enabled=False
        assert (await client.get(base+'/context')).json()['editingEnabled'] is False
        assert (await client.get(base+'/file')).content==source
