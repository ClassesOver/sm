import { afterEach, describe, expect, it, vi } from 'vitest'
import { createNativeApi, NativeApiError, type NativeSaveResponse } from './native-api'

const request = { requestId: 'stable-id', expectedSha256: 'a'.repeat(64), operations: [{ kind: 'rotatePage', pageId: 'page', delta: 90 }] }
afterEach(() => vi.unstubAllGlobals())

describe('native HTTP client', () => {
  it('encodes the immutable route and uses context CSRF for every write', async () => {
    const fetcher = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ ok: true })))
    vi.stubGlobal('fetch', fetcher)
    const api = createNativeApi('doc name', 2, 'csrf-value')
    await api.context()
    await api.preview({ expectedSha256: request.expectedSha256, operations: request.operations })
    await api.save(request)
    await api.export(request)
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      '/reports/v1/native/doc%20name/2/api/context', '/reports/v1/native/doc%20name/2/api/preview',
      '/reports/v1/native/doc%20name/2/api/save', '/reports/v1/native/doc%20name/2/api/export',
    ])
    for (const [, init] of fetcher.mock.calls) {
      expect(init.credentials).toBe('same-origin')
      expect(init.cache).toBe('no-store')
      if (init.method === 'POST') {
        expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-value')
        expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
      }
    }
    expect(JSON.parse(fetcher.mock.calls[2][1].body)).toEqual(request)
  })

  it('returns original file bytes and forwards cancellation', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(new Uint8Array([1, 2, 3])))
    vi.stubGlobal('fetch', fetcher)
    const signal = new AbortController().signal
    const result = await createNativeApi('document', 1).file(signal)
    expect(new Uint8Array(result)).toEqual(new Uint8Array([1, 2, 3]))
    expect(fetcher.mock.calls[0][0]).toBe('/reports/v1/native/document/1/api/file')
    expect(fetcher.mock.calls[0][1].signal).toBe(signal)
  })

  it('requests a clipped identity-bound PDF image background with cancellable authorization', async () => {
    const target = { sourceSha256: 'a'.repeat(64), pageId: `sha256:${'a'.repeat(64)}:page:0`, imageId: 'b'.repeat(64), expectedImageSha256: 'c'.repeat(64), clip: { x: 4, y: 8, width: 20, height: 10 }, pxWidth: 20 }
    const response = { ...target, image: 'iVBORw0KGgoAAA', width: 20, height: 10, sha256: 'd'.repeat(64) }
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(response)))
    vi.stubGlobal('fetch', fetcher)
    const signal = new AbortController().signal
    await expect(createNativeApi('document', 3, 'csrf').imageBackground(target, signal)).resolves.toEqual(response)
    expect(fetcher.mock.calls[0][0]).toBe('/reports/v1/native/document/3/api/image-background')
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(target)
    expect(fetcher.mock.calls[0][1].signal).toBe(signal)
    expect(new Headers(fetcher.mock.calls[0][1].headers).get('X-CSRF-Token')).toBe('csrf')
  })

  it('preserves server status/code and meaningful failure detail', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { code: 'native_source_changed', message: '来源已变化' } }), { status: 409 })))
    const error = await createNativeApi('document', 1, 'csrf').save(request).catch(error => error)
    expect(error).toBeInstanceOf(NativeApiError)
    expect(error).toMatchObject({ status: 409, code: 'native_source_changed', message: '来源已变化' })
  })

  it('retains saved identities and note when both link grants failed', async () => {
    const result: NativeSaveResponse = {
      documentId: 'document', revision: 2, parentRevision: 1, revisionRegistered: true, note: '修订备注',
      artifacts: { pdf: { path: 'native/revisions/2/report.pdf', size: 100, sha256: 'a'.repeat(64) } },
      validation: { ok: false, issues: [{ code: 'native_download_fallback_failed', message: '文件保留，可重试签发' }] },
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(result))))
    expect(await createNativeApi('document', 1, 'csrf').save(request)).toEqual(result)
  })

  it('does not send a write without CSRF or with an invalid route', async () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    await expect(createNativeApi('document', 1).save(request)).rejects.toThrow(/授权/)
    expect(() => createNativeApi('../other', 1)).toThrow()
    expect(() => createNativeApi('document', 0)).toThrow()
    expect(fetcher).not.toHaveBeenCalled()
  })
})

it('AI写入使用原生会话CSRF、状态轮询可取消且完整草稿随采纳提交', async () => {
  const fetcher=vi.fn().mockImplementation(async()=>new Response(JSON.stringify({editId:'job',status:'cancelled'})))
  vi.stubGlobal('fetch',fetcher)
  const api=createNativeApi('doc',1,'token'), signal=new AbortController().signal
  const payload={expectedSha256:'a'.repeat(64),operations:[{kind:'replaceParagraph',text:'尚未保存'}]}
  await api.aiStart({...payload,instruction:'调整',selection:[{blockId:'p'}]})
  await api.aiStatus('job/id',signal)
  await api.aiAccept('job/id',{...payload,snapshotSha256:'b'.repeat(64)})
  await api.aiCancel('job/id')
  await api.aiCancelRequest('request-1')
  expect(fetcher.mock.calls[1][0]).toBe('/reports/v1/native/doc/1/api/ai/job%2Fid?waitMs=20000')
  expect(fetcher.mock.calls[1][1].signal).toBe(signal)
  for(const index of [0,2,3,4]) expect(new Headers(fetcher.mock.calls[index][1].headers).get('X-CSRF-Token')).toBe('token')
  expect(fetcher.mock.calls[4][0]).toBe('/reports/v1/native/doc/1/api/ai/cancel-request')
  expect(JSON.parse(fetcher.mock.calls[4][1].body)).toEqual({clientRequestId:'request-1'})
  expect(JSON.parse(fetcher.mock.calls[2][1].body).operations).toEqual(payload.operations)
})

it('真实PDF预览字节必须与显示的确认清单摘要一致',async()=>{
  const digest='b'.repeat(64)
  vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(new Response(new Uint8Array([37,80,68,70]),{headers:{'X-Native-Preview-Digest':digest}})).mockResolvedValueOnce(new Response('changed',{headers:{'X-Native-Preview-Digest':'c'.repeat(64)}})))
  const api=createNativeApi('doc',1,'csrf'),payload={expectedSha256:'a'.repeat(64),operations:[],expectedPreviewDigest:digest}
  expect(new Uint8Array(await api.previewFile(payload))).toEqual(new Uint8Array([37,80,68,70]))
  await expect(api.previewFile(payload)).rejects.toThrow('预览')
})

it('PDF阅读取消在页面卸载时仍使用keepalive并保留同源CSRF', async () => {
  const fetcher=vi.fn().mockImplementation(async()=>new Response(JSON.stringify({taskId:'t',clientRequestId:'request',status:'cancelled'})))
  vi.stubGlobal('fetch',fetcher)
  await createNativeApi('document',1,'csrf').pdfAICancel('request')
  expect(fetcher.mock.calls[0][0]).toBe('/reports/v1/native/document/1/api/ai/read/cancel')
  const init=fetcher.mock.calls[0][1]
  expect(init.keepalive).toBe(true)
  expect(init.signal).toBeUndefined()
  expect(init.credentials).toBe('same-origin')
  expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf')
  expect(JSON.parse(init.body)).toEqual({clientRequestId:'request'})
})

it('Office阅读使用独立路由、真实草稿选区、可取消轮询及SSE进度',async()=>{
  const fetcher=vi.fn().mockImplementation(async()=>new Response(JSON.stringify({taskId:'t',status:'completed'})))
  vi.stubGlobal('fetch',fetcher)
  const api=createNativeApi('office',1,'token'),signal=new AbortController().signal
  const payload={clientRequestId:'request',expectedSha256:'a'.repeat(64),operations:[{kind:'editSlides',edits:[]}],selection:[{slideIndex:0,elementId:'shape'}],action:'summarize' as const,instruction:''}
  await api.officeAIStart(payload,signal)
  await api.officeAIStatus('task/id',signal)
  await api.officeAICancel('request')
  const base='/reports/v1/native/office/1/api/ai/office-read'
  expect(fetcher.mock.calls.map(([url])=>url)).toEqual([base+'/start',base+'/task%2Fid?waitMs=20000',base+'/cancel'])
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(payload)
  expect(fetcher.mock.calls[1][1].signal).toBe(signal)
  expect(fetcher.mock.calls[2][1].keepalive).toBe(true)
  expect(new Headers(fetcher.mock.calls[2][1].headers).get('X-CSRF-Token')).toBe('token')
  fetcher.mockResolvedValueOnce(new Response('id: 1\nevent: progress\ndata: {"kind":"terminal","sequence":1,"status":"completed"}\n\n',{headers:{'Content-Type':'text/event-stream'}}))
  const onEvent=vi.fn()
  await api.officeAIEvents('task/id',onEvent,signal)
  expect(fetcher.mock.calls[3][0]).toBe(base+'/task%2Fid/events?after=0')
  expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({kind:'terminal'}))
})
