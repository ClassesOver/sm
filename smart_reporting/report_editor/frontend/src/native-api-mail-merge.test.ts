import {afterEach,it,expect,vi} from 'vitest'
import {createNativeApi} from './native-api'
afterEach(()=>vi.unstubAllGlobals())
it('downloads binary mail merge with CSRF, cancellation and both identity receipts',async()=>{
 const fetcher=vi.fn().mockResolvedValue(new Response(new Uint8Array([80,75,3,4]),{headers:{'X-Native-Export-Sha256':'output','X-Native-Export-Size':'4','X-Native-Source-Sha256':'source'}}));vi.stubGlobal('fetch',fetcher)
 const payload={mode:'perRecord' as const,namePattern:'Name',documentSha256:'source',sourceSha256:'csv',sourceBase64:'TmFtZQpBZGEK'},signal=new AbortController().signal
 const result=await createNativeApi('document',1,'csrf').mailMergeExport(payload,signal)
 expect(result).toMatchObject({sha256:'output',size:4,sourceSha256:'source',filename:'mail-merge.zip'});expect(new Uint8Array(result.content)).toEqual(new Uint8Array([80,75,3,4]))
 expect(fetcher.mock.calls[0][0]).toBe('/reports/v1/native/document/1/api/mail-merge/export');expect(fetcher.mock.calls[0][1].signal).toBe(signal);expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(payload);expect(new Headers(fetcher.mock.calls[0][1].headers).get('X-CSRF-Token')).toBe('csrf')
})
