import {afterEach,expect,it,vi} from 'vitest'
import {createNativeApi} from './native-api'
afterEach(()=>vi.unstubAllGlobals())
it('Word 阅读使用独立路由、原生授权、可中止轮询和关闭时保活取消',async()=>{
 const fetcher=vi.fn().mockImplementation(async()=>new Response(JSON.stringify({taskId:'t',status:'cancelled'})));vi.stubGlobal('fetch',fetcher)
 const api=createNativeApi('word',2,'csrf'),signal=new AbortController().signal
 const payload={clientRequestId:'request',action:'ask' as const,instruction:'问题',expectedSha256:'a'.repeat(64),operations:[],selection:[]}
 await api.wordAIStart(payload,signal);await api.wordAIStatus('t/1',signal);await api.wordAICancel('request')
 expect(fetcher.mock.calls.map(call=>call[0])).toEqual(['/reports/v1/native/word/2/api/ai/word-read/start','/reports/v1/native/word/2/api/ai/word-read/t%2F1?waitMs=20000','/reports/v1/native/word/2/api/ai/word-read/cancel'])
 expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(payload);expect(fetcher.mock.calls[1][1].signal).toBe(signal)
 expect(new Headers(fetcher.mock.calls[0][1].headers).get('X-CSRF-Token')).toBe('csrf');expect(fetcher.mock.calls[2][1].keepalive).toBe(true)
})
it('Word 只读模型使用无正文 GET，复用会话并支持中止',async()=>{
 const fetcher=vi.fn().mockImplementation(async()=>new Response(JSON.stringify({sourceSha256:'a',model:{blocks:[]}})));vi.stubGlobal('fetch',fetcher)
 const api=createNativeApi('word',2),signal=new AbortController().signal
 expect(await api.readModel(signal)).toEqual({sourceSha256:'a',model:{blocks:[]}})
 expect(fetcher.mock.calls[0][0]).toBe('/reports/v1/native/word/2/api/read-model')
 expect(fetcher.mock.calls[0][1]).toMatchObject({method:'GET',credentials:'same-origin',cache:'no-store',signal})
 expect(fetcher.mock.calls[0][1].body).toBeUndefined()
})
