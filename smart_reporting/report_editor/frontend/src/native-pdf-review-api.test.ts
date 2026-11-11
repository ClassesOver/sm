import {afterEach,expect,it,vi} from 'vitest'
import {createNativeApi} from './native-api'
afterEach(()=>vi.unstubAllGlobals())
it('审阅请求保留完整base与CSRF，取消可在面板卸载后keepalive发送',async()=>{
 const fetcher=vi.fn().mockResolvedValue({ok:true,json:async()=>({status:'running'})});vi.stubGlobal('fetch',fetcher)
 const api=createNativeApi('review doc',2,'csrf-review'),operations=[{kind:'rotatePage',pageId:'p',delta:90}]
 await api.pdfReviewStart({clientRequestId:'req',expectedSha256:'a'.repeat(64),operations,instruction:''})
 await api.pdfReviewStatus('edit/id')
 await api.pdfReviewAccept('edit/id',{expectedSha256:'a'.repeat(64),operations,snapshotSha256:'b'.repeat(64)})
 await api.pdfReviewCancel('req')
 expect(fetcher.mock.calls.map(([url])=>url)).toEqual(['/reports/v1/native/review%20doc/2/api/ai/review/start','/reports/v1/native/review%20doc/2/api/ai/review/edit%2Fid?waitMs=20000','/reports/v1/native/review%20doc/2/api/ai/review/edit%2Fid/accept','/reports/v1/native/review%20doc/2/api/ai/review/cancel'])
 expect(JSON.parse(fetcher.mock.calls[0][1].body).operations).toEqual(operations)
 expect(JSON.parse(fetcher.mock.calls[2][1].body).operations).toEqual(operations)
 for(const [,init] of fetcher.mock.calls.filter(([,init])=>init.method==='POST')) expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-review')
 expect(fetcher.mock.calls[3][1].keepalive).toBe(true)
 expect(fetcher.mock.calls[0][1].keepalive).toBeUndefined()
})
it('未获CSRF的审阅写请求不会发往服务端',async()=>{
 const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher)
 await expect(createNativeApi('doc',1).pdfReviewCancel('req')).rejects.toMatchObject({code:'native_csrf_missing'})
 expect(fetcher).not.toHaveBeenCalled()
})
