import type { NativeOperation } from './native-draft'
import { afterEach, expect, it, vi } from 'vitest'
import { createSlidesNativeAIClient, mountSlidesNativeAI, type SlidesNativeAIClient } from './slides-native-ai'

afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

function setup() {
  const host = document.createElement('div'); document.body.append(host)
  let operations: NativeOperation[] = []
  const candidate = { editId: 'candidate', status: 'succeeded', snapshotSha256: 's'.repeat(64), proposal: { summary: '润色标题', operations: [{ kind: 'editSlides', edits: [{ slideIndex: 0, elementId: 'title', text: '候选标题' }], order: [0] }] } }
  const api = { start: vi.fn(async () => ({ ...candidate, status: 'running' })), status: vi.fn(async () => candidate),
    accept: vi.fn(async () => ({ operations: candidate.proposal.operations })), cancel: vi.fn(async () => ({})), cancelRequest: vi.fn(async () => ({})) }
  const apply = vi.fn((next: NativeOperation[]) => { operations = next })
  const view = mountSlidesNativeAI(host, { api: api as unknown as SlidesNativeAIClient, locked: () => false,
    context: scope => ({ expectedSha256: 'a'.repeat(64), operations, scope: scope === 'deck' ? 'deck' : 'selection', selection: scope === 'deck' ? [] : [{ slideIndex: 0, elementId: 'title' }],
      label: '第 1 页 · 标题', objects: [{ slideIndex: 0, elementId: 'title', text: '人工文字', name: '标题' }] }), apply })
  const submit = () => { host.querySelector<HTMLTextAreaElement>('textarea')!.value = '润色'; host.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true })) }
  return { host, api, apply, view, submit, change: () => { operations = [{ kind: 'editSlides', backgrounds: [{ slideIndex: 0, color: '#123456' }] }] } }
}

it('quotes the selected object, previews Chinese candidates and requires explicit acceptance', async () => {
  const { host, api, apply, view, submit } = setup()
  expect(host.textContent).toContain('AI 助手')
  expect(host.textContent).toContain('第 1 页 · 标题')
  submit()
  await vi.waitFor(() => expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false))
  expect(api.start).toHaveBeenCalledWith(expect.objectContaining({ instruction: '润色', selection: [{ slideIndex: 0, elementId: 'title' }], operations: [] }), expect.any(AbortSignal))
  expect(host.textContent).toContain('人工文字'); expect(host.textContent).toContain('候选标题')
  expect(apply).not.toHaveBeenCalled()
  host.querySelector<HTMLButtonElement>('.native-ai-accept')!.click()
  await vi.waitFor(() => expect(apply).toHaveBeenCalledWith([{ kind: 'editSlides', edits: [{ slideIndex: 0, elementId: 'title', text: '候选标题' }], order: [0] }]))
  view.dispose()
})

it('refuses stale full drafts before acceptance without overwriting manual edits', async () => {
  const { host, api, apply, view, submit, change } = setup()
  submit(); await vi.waitFor(() => expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false))
  change(); host.querySelector<HTMLButtonElement>('.native-ai-accept')!.click()
  await vi.waitFor(() => expect(host.textContent).toContain('草稿已变化'))
  expect(api.accept).not.toHaveBeenCalled(); expect(apply).not.toHaveBeenCalled(); view.dispose()
})

it('shows style-only candidates including explicit removal before adoption', async () => {
  const { host, api, apply, view, submit } = setup()
  api.status.mockResolvedValueOnce({ editId: 'style', status: 'succeeded', snapshotSha256: 's'.repeat(64), proposal: {
    summary: '标题样式', operations: [{ kind: 'editSlides', edits: [], textFormatting: [{ slideIndex: 0, elementId: 'title', fontSizePt: 24, color: '#123456', bold: false }] }],
  } } as never)
  submit()
  await vi.waitFor(() => expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false))
  expect(host.textContent).toContain('字号 24')
  expect(host.textContent).toContain('颜色 #123456')
  expect(host.textContent).toContain('取消粗体')
  expect(apply).not.toHaveBeenCalled()
  view.dispose()
})

it('checks the complete draft again after an in-flight acceptance', async () => {
  const { host, api, apply, view, submit, change } = setup()
  let resolve!: (value: { operations: NativeOperation[] }) => void
  api.accept.mockImplementationOnce(() => new Promise(done => { resolve = done }) as never)
  submit(); await vi.waitFor(() => expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false))
  host.querySelector<HTMLButtonElement>('.native-ai-accept')!.click(); await vi.waitFor(() => expect(api.accept).toHaveBeenCalled())
  change(); resolve({ operations: [{ kind: 'editSlides', edits: [] }] })
  await vi.waitFor(() => expect(host.textContent).toContain('草稿已变化'))
  expect(apply).not.toHaveBeenCalled(); view.dispose()
})

it('uses the PPTX-specific native route and native CSRF for start and explicit acceptance', async () => {
  const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ editId: 'id', operations: [] })))
  vi.stubGlobal('fetch', fetcher)
  const client = createSlidesNativeAIClient('document', 3, 'native-token')
  const payload = { expectedSha256: 'a'.repeat(64), operations: [], selection: [{ slideIndex: 0, elementId: 'id' }], scope: 'selection' as const, instruction: '润色', clientRequestId: 'request-fixture' }
  const signal = new AbortController().signal
  await client.start(payload, signal)
  await client.accept('candidate', { expectedSha256: payload.expectedSha256, operations: [], snapshotSha256: 'b'.repeat(64) }, signal)
  expect(fetcher.mock.calls[0]).toEqual(['/reports/v1/native/document/3/api/slides-ai/start', expect.objectContaining({ method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'native-token' }, body: JSON.stringify(payload) })])
  expect(fetcher.mock.calls[1][0]).toBe('/reports/v1/native/document/3/api/slides-ai/candidate/accept')
  await client.cancelRequest(payload.clientRequestId)
  expect(fetcher.mock.calls[2]).toEqual(['/reports/v1/native/document/3/api/slides-ai/cancel-request', expect.objectContaining({ method: 'POST', keepalive: true, body: JSON.stringify({ clientRequestId: payload.clientRequestId }) })])
})

it('requires an explicit whole-deck scope change before requesting deck-wide changes', async () => {
  const { host, api, submit, view } = setup()
  const scope = host.querySelector<HTMLSelectElement>('select')!
  expect(scope.value).toBe('object')
  scope.value = 'deck'; scope.dispatchEvent(new Event('change'))
  submit()
  await vi.waitFor(() => expect(api.start).toHaveBeenCalledWith(expect.objectContaining({ scope: 'deck', selection: [] }), expect.any(AbortSignal)))
  view.dispose()
})

it('cancels by request identity before start resolves and also cleans up a late job identity', async () => {
  const { host, api, submit, view } = setup()
  let finish!: (value: unknown) => void
  api.start.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }) as never)
  submit()
  const payload = (api.start.mock.calls as unknown as [{ clientRequestId: string }][])[0][0]
  expect(payload.clientRequestId).toMatch(/^[a-zA-Z0-9_-]+$/)
  expect(host.querySelector<HTMLButtonElement>('.native-ai-cancel')!.hidden).toBe(false)
  host.querySelector<HTMLButtonElement>('.native-ai-cancel')!.click()
  expect(api.cancelRequest).toHaveBeenCalledWith(payload.clientRequestId)
  finish({ editId: 'late-id', status: 'running', snapshotSha256: 's'.repeat(64) })
  await vi.waitFor(() => expect(api.cancel).toHaveBeenCalledWith('late-id'))
  expect(api.status).not.toHaveBeenCalled(); view.dispose()
})

it('disposal cancels by client request even when abort loses the start response entirely', async () => {
  const { api, submit, view } = setup()
  api.start.mockImplementationOnce((...args: unknown[]) => new Promise((_resolve, reject) => {
    ;(args[1] as AbortSignal).addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
  }) as never)
  submit()
  const payload = (api.start.mock.calls as unknown as [{ clientRequestId: string }][])[0][0]
  view.dispose()
  expect(api.cancelRequest).toHaveBeenCalledWith(payload.clientRequestId)
  await Promise.resolve(); await Promise.resolve()
  expect(api.status).not.toHaveBeenCalled(); expect(api.cancel).not.toHaveBeenCalled()
})
it('表格与图表候选显示当前真实值到候选的中文差异，仍需明确采纳',async()=>{
 const host=document.body.appendChild(document.createElement('div'))
 const objects=[{slideIndex:0,elementId:'table',name:'经营表',text:'收入 42',type:'table',tableCells:[['收入','42']]},{slideIndex:0,elementId:'chart',name:'经营图',text:'本期 收入42',type:'chart',chartKind:'bar' as const,chartCategories:['本期'],chartSeries:[{name:'收入',values:[42]}]}]
 const operations=[{kind:'editSlides',tableCells:[{slideIndex:0,elementId:'table',row:0,col:1,text:'73'}],chartEdits:[{slideIndex:0,elementId:'chart',kind:'line',categories:['下期'],series:[{name:'收入',values:[73]}]}]}]
 const api={start:vi.fn().mockResolvedValue({editId:'complex',status:'succeeded',snapshotSha256:'s',proposal:{summary:'核对数据',operations}}),cancel:vi.fn().mockResolvedValue({}),cancelRequest:vi.fn().mockResolvedValue({}),accept:vi.fn().mockResolvedValue({operations})},apply=vi.fn()
 const view=mountSlidesNativeAI(host,{api:api as never,locked:()=>false,context:()=>({expectedSha256:'a'.repeat(64),operations:[],selection:objects.map(({slideIndex,elementId})=>({slideIndex,elementId})),scope:'selection',label:'当前对象',objects}),apply})
 expect(host.querySelector('[type=submit] svg')).not.toBeNull()
 host.querySelector('textarea')!.value='更新表格与图表';host.querySelector('form')!.dispatchEvent(new Event('submit',{cancelable:true}))
 await vi.waitFor(()=>expect(host.textContent).toContain('第1页 表格 经营表 第1行2列：42 → 73'))
 expect(host.textContent).toContain('类型：簇状柱形图 → 折线图');expect(host.textContent).toContain('类别：本期 → 下期');expect(host.textContent).toContain('序列：收入：42 → 收入：73')
 expect(apply).not.toHaveBeenCalled();host.querySelector<HTMLButtonElement>('.native-ai-accept')!.click()
 await vi.waitFor(()=>expect(apply).toHaveBeenCalledWith(operations));view.dispose()
})

it('打开助手只聚焦现有输入，不提交 AI 任务', () => {
  const { host, api, view } = setup()
  view.open()
  expect(document.activeElement).toBe(host.querySelector('textarea'))
  expect(api.start).not.toHaveBeenCalled()
  view.dispose()
})

it('备注显式按页授权，展示备注前后差异并等待采纳，不发送画布对象授权',async()=>{
 const host=document.body.appendChild(document.createElement('div'))
 const operations:NativeOperation[]=[{kind:'editSlides',notesEdits:[{slideIndex:0,text:'原备注草稿'}]}]
 const candidate={editId:'notes',status:'succeeded',snapshotSha256:'n'.repeat(64),proposal:{summary:'补充演讲者备注',operations:[{kind:'editSlides',notesEdits:[{slideIndex:0,text:'候选演讲稿'}]}]}}
 const api={start:vi.fn(async()=>candidate),status:vi.fn(),accept:vi.fn(async()=>({operations:candidate.proposal.operations})),cancel:vi.fn(async()=>({})),cancelRequest:vi.fn(async()=>({}))},apply=vi.fn()
 const view=mountSlidesNativeAI(host,{api:api as unknown as SlidesNativeAIClient,locked:()=>false,apply,context:scope=>({expectedSha256:'a'.repeat(64),operations,scope:scope==='notes'?'notes':'selection',selection:scope==='notes'?[{slideIndex:0}]:[{slideIndex:0,elementId:'title'}],objects:[],notes:[{slideIndex:0,text:'原备注草稿'}],label:'当前页备注'})})
 const scope=host.querySelector<HTMLSelectElement>('select')!;scope.value='notes';scope.dispatchEvent(new Event('change'))
 host.querySelector<HTMLTextAreaElement>('textarea')!.value='润色本页演讲者备注';host.querySelector('form')!.dispatchEvent(new Event('submit',{cancelable:true}))
 await vi.waitFor(()=>expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false))
 expect(api.start).toHaveBeenCalledWith(expect.objectContaining({scope:'notes',selection:[{slideIndex:0}],operations}),expect.any(AbortSignal))
 expect(host.textContent).toContain('原备注草稿 → 候选演讲稿');expect(apply).not.toHaveBeenCalled()
 host.querySelector<HTMLButtonElement>('.native-ai-accept')!.click();await vi.waitFor(()=>expect(apply).toHaveBeenCalledWith(candidate.proposal.operations));view.dispose()
})
