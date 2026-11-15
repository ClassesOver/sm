import {afterEach,expect,it,vi} from 'vitest'
import {createNativeApi} from './native-api'
afterEach(()=>vi.unstubAllGlobals())
it('New and Save As submit source identity through the authenticated native host',async()=>{
 const result={documentId:'independent',revision:1,filename:'Copy.docx',editor:{url:'/reports/v1/native/open/grant',openUrl:'/reports/v1/native/open/grant'}}
 const fetcher=vi.fn(async(_url:RequestInfo|URL,_options?:RequestInit)=>new Response(JSON.stringify(result)));vi.stubGlobal('fetch',fetcher)
 const api=createNativeApi('source',2,'csrf'),payload={requestId:'click',expectedSha256:'a'.repeat(64),filename:'Copy.docx'}
 expect(await api.newWord(payload)).toEqual(result);expect(await api.saveWordAs(payload)).toEqual(result)
 expect(fetcher.mock.calls.map(call=>call[0])).toEqual(['/reports/v1/native/source/2/api/word/new','/reports/v1/native/source/2/api/word/save-as'])
 for(const [,options] of fetcher.mock.calls){expect(JSON.parse(options!.body as string)).toEqual(payload);expect(new Headers(options!.headers).get('X-CSRF-Token')).toBe('csrf')}
})
