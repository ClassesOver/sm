"""回复的真实 FastAPI/session/CSRF 与生产 Node bridge 验收，仓储为既有内存夹具。"""
import hashlib
import json
from io import BytesIO
from zipfile import ZipFile

from httpx import ASGITransport, AsyncClient
from lxml import etree as E
import pytest

from smart_reporting.reporting.tests.test_docx_comment_http import http_env, import_and_open, anyio_backend  # noqa: F401
from smart_reporting.reporting.tests.test_docx_comment_reply import modern_source, operation, selected, NS, W, W14, W15


@pytest.mark.anyio
async def test_reply_http_save_download_and_reopen_real_parent_nonblocking(http_env,tmp_path):
    env=http_env;env.original=modern_source()
    async def failed_validation(context,artifacts):
        raise RuntimeError('reply_validation_probe')
    env.publication.validator=failed_validation
    async with AsyncClient(transport=ASGITransport(app=env.app),base_url='http://test') as client:
        base,context,headers=await import_and_open(client,env)
        expected=context['context']['sourceFile']['sha256']
        inspect=await client.post(base+'/preview',headers=headers,json={'expectedSha256':expected,'operations':[]})
        assert inspect.status_code==200,inspect.text
        target=inspect.json()['model']['commentReplies']['targets'][0]
        reply=operation(target,'HTTP真实回复😀')
        payload={'expectedSha256':expected,'operations':[reply]}
        assert (await client.post(base+'/preview',json=payload)).status_code==403
        for bad in ({**reply,'sourceId':'f'*64},{**reply,'expectedObjectSha256':'0'*64}):
            denied=await client.post(base+'/preview',headers=headers,json={**payload,'operations':[bad]})
            assert denied.status_code==422,denied.text
        preview=await client.post(base+'/preview',headers=headers,json=payload)
        assert preview.status_code==200,preview.text
        assert preview.json()['model']['commentReplies']['targets'][-1]['parentId']=='1'
        request={**payload,'requestId':'reply-http-save'}
        response=await client.post(base+'/save',headers=headers,json=request)
        assert response.status_code==200,response.text
        result=response.json();artifact=result['artifacts']['word']
        assert result['revisionRegistered'] and result['revision']==2 and result['parentRevision']==1
        assert result['validation']['ok'] is False and result['validation']['issues']
        async with AsyncClient(transport=ASGITransport(app=env.app),base_url='http://test') as downloader:
            download=await downloader.get(artifact['downloadUrl'])
        assert download.status_code==200 and hashlib.sha256(download.content).hexdigest()==artifact['sha256']
        with ZipFile(BytesIO(env.original)) as a,ZipFile(BytesIO(download.content)) as b:
            assert b.testzip() is None and a.namelist()==b.namelist()
            changed=[n for n in a.namelist() if a.read(n)!=b.read(n)]
            assert set(changed)=={'word/document.xml','word/comments.xml','word/commentsExtended.xml'}
            for n in b.namelist():
                if n.endswith(('.xml','.rels')):E.fromstring(b.read(n))
            comments=E.fromstring(b.read('word/comments.xml'));new=comments[-1];pid=new[-1].get(f'{{{W14}}}paraId')
            ex=E.fromstring(b.read('word/commentsExtended.xml'))
            assert ex.xpath('w15:commentEx[@w15:paraId=$pid]/@w15:paraIdParent',namespaces=NS,pid=pid)==['AA000001']
            assert ''.join(new.xpath('.//w:t/text()',namespaces=NS))==reply['text']
            assert selected(E.fromstring(b.read('word/document.xml')),new.get(f'{{{W}}}id'))=='Anchor text'
            assert b.read('word/people.xml')==a.read('word/people.xml') and b.read('custom/preserved.xml')==a.read('custom/preserved.xml')
        repeated=await client.post(base+'/save',headers=headers,json=request)
        assert repeated.status_code==200 and repeated.json()['revision']==2 and env.publication.repository.completions==1
        assert (await client.get(base+'/file')).content==env.original
        reopened=await client.get(result['editor']['openUrl'],follow_redirects=True)
        assert reopened.status_code==200,reopened.text
        next_base=reopened.url.path+'/api';next_context=(await client.get(next_base+'/context')).json()
        next_headers={'Origin':'http://test','X-CSRF-Token':next_context['csrfToken']}
        next_expected=next_context['context']['sourceFile']['sha256']
        next_model=await client.post(next_base+'/preview',headers=next_headers,json={'expectedSha256':next_expected,'operations':[]})
        assert next_model.status_code==200,next_model.text
        child=next_model.json()['model']['commentReplies']['targets'][-1]
        assert child['parentId']=='1' and child['canReply'] is False and child['text']==reply['text']
        stale=await client.post(next_base+'/save',headers=next_headers,json={**request,'requestId':'stale-reply','expectedSha256':next_expected})
        assert stale.status_code==422 and env.publication.repository.completions==1
        (tmp_path/'source.docx').write_bytes(env.original);(tmp_path/'downloaded.docx').write_bytes(download.content)
        evidence={'bridgeSha256':env.bridge_sha256,'sourceSha256':expected,'outputSha256':artifact['sha256'],'parentId':'1','sharedAnchor':'Anchor text','changedParts':changed,'revision':2,'validationFailedButLinkIssued':True,'staleRejected':True,'realBridgeCalls':len(env.calls)}
        (tmp_path/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print('reply_http_evidence='+json.dumps(evidence,ensure_ascii=False))
