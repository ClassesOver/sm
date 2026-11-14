import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { startNativeEditor } from './native-main'
import { bindNativeAI } from './native-ai'
import { NativeDraft } from './native-draft'
const views = vi.hoisted(() => ({ pdf: vi.fn(), docx: vi.fn() }))
vi.mock('./pdf-main', () => ({ createPdfEditorView: views.pdf }))
vi.mock('./docx-main', () => ({ createDocxEditorView: views.docx }))
const sha = 'a'.repeat(64)
let options: any
let fetcher: ReturnType<typeof vi.fn>
let finishAccept: (response: Response) => void
let finishRefresh: (response: Response) => void
const viewRefresh = vi.fn(async () => {})
const task = (status = 'completed') => ({taskId:'task',status,result:{validationPassed:false},execution:{status:'completed',issueCodes:[]}})
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status})
const aiButton = (name: string) => document.querySelector<HTMLButtonElement>(`[data-ai=${name}]`)!
const refreshButton = () => document.querySelector<HTMLButtonElement>('[data-action=binary-refresh]')!
const calls = (suffix: string) => fetcher.mock.calls.filter(([url]) => String(url).endsWith(suffix))
const operation = (format: string) => format === 'pdf' ? {kind:'replaceText',pageId:'p1',objectId:'o1',newText:'采纳文字'} : {kind:'replaceParagraph',blockId:'p1',text:'采纳文字'}
beforeEach(() => {
  document.body.innerHTML = '<div id="app"></div>'; localStorage.clear(); viewRefresh.mockClear()
  for (const view of [views.pdf, views.docx]) view.mockImplementation(async (_shell, value) => {
    options = value
    return {refresh:viewRefresh,flushPendingEdits(){},setSaving(){},dispose(){}}
  })
  fetcher = vi.fn(async (url: string) => {
    if (url.endsWith('/context')) return response({context:{documentId:'doc',revision:1,format:location.search.includes('word')?'docx':'pdf',origin:'report',sourceFile:{sha256:sha,size:12},scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},contextSha256:'b'.repeat(64),dataRefresh:{available:true},csrfToken:'token',editingEnabled:true,aiEnabled:true,pdfTextEnabled:true})
    if (url.endsWith('/ai/start')) return response({editId:'edit',status:'succeeded',snapshotSha256:'s'.repeat(64),proposal:{summary:'候选',operations:[]}})
    if (url.endsWith('/ai/edit/accept')) return await new Promise<Response>(resolve => {finishAccept=resolve})
    if (url.endsWith('/ai/edit/cancel')) return response({})
    if (url.endsWith('/recalculations')) return await new Promise<Response>(resolve => {finishRefresh=resolve})
    if (url.endsWith('/delivery')) return response({task:task(),delivery:{pdf:{downloadUrl:'/trusted.pdf'},word:{downloadUrl:'/trusted.docx'},validation:{ok:false,issues:[{code:'validation_failed',message:'后置验收失败'}]}}})
    return response(task())
  })
  vi.stubGlobal('fetch', fetcher)
})
afterEach(() => {window.dispatchEvent(new Event('pagehide'));vi.unstubAllGlobals()})
async function openCandidate(format: string) {
  history.replaceState({},'', '/reports/v1/native/doc/1' + (format==='docx'?'?word':''))
  await startNativeEditor()
  options.onSelectionChange(format==='pdf'?[{pageId:'p1',objectId:'o1'}]:[{blockId:'p1'}])
  document.querySelector<HTMLTextAreaElement>('.native-ai textarea')!.value='改写选区'
  aiButton('start').click()
  await vi.waitFor(() => expect(aiButton('accept').disabled).toBe(false))
}
async function assertDownload(format: string) {
  await vi.waitFor(() => expect(document.querySelector('.binary-refresh-result a')).not.toBeNull())
  expect(document.querySelector('.binary-refresh-result a')!.getAttribute('href')).toBe(format==='pdf'?'/trusted.pdf':'/trusted.docx')
  expect(document.querySelector('.binary-refresh-result')!.textContent).toContain('后置验收失败')
}
it.each(['pdf','docx'])('%s keeps cancelled acceptance locked until its late response drains without writing', async format => {
  await openCandidate(format); aiButton('accept').click()
  await vi.waitFor(() => expect(calls('/ai/edit/accept')).toHaveLength(1))
  expect(refreshButton().disabled).toBe(true)
  refreshButton().click(); expect(calls('/recalculations')).toHaveLength(0)
  aiButton('cancel').click()
  expect(refreshButton().disabled).toBe(true)
  aiButton('start').click(); refreshButton().click()
  expect(calls('/ai/start')).toHaveLength(1); expect(calls('/recalculations')).toHaveLength(0)
  finishAccept(response({operations:[operation(format)]}))
  await vi.waitFor(() => expect(refreshButton().disabled).toBe(false))
  expect(options.draft.operations).toEqual([]); expect(viewRefresh).not.toHaveBeenCalled()
  refreshButton().click(); await vi.waitFor(() => expect(calls('/recalculations')).toHaveLength(1))
  finishRefresh(response(task())); await assertDownload(format)
})
it.each([['pdf','success'],['pdf','failure'],['docx','success'],['docx','failure']])('%s releases acceptance lock after %s', async (format, outcome) => {
  await openCandidate(format); aiButton('accept').click()
  await vi.waitFor(() => expect(calls('/ai/edit/accept')).toHaveLength(1))
  expect(refreshButton().disabled).toBe(true)
  finishAccept(outcome==='success'?response({operations:[operation(format)]}):response({detail:{message:'采纳失败'}},409))
  await vi.waitFor(() => expect(refreshButton().disabled).toBe(false))
  expect(options.draft.operations).toEqual(outcome==='success'?[operation(format)]:[])
  if (outcome==='success') expect(viewRefresh).toHaveBeenCalledTimes(1)
  else {
    refreshButton().click(); await vi.waitFor(() => expect(calls('/recalculations')).toHaveLength(1))
    finishRefresh(response(task())); await assertDownload(format)
  }
})
it.each([['pdf','completed'],['pdf','failed'],['docx','completed'],['docx','failed']])('%s blocks AI entry throughout %s refresh and releases it with trustworthy delivery', async (format, outcome) => {
  await openCandidate(format); refreshButton().click()
  await vi.waitFor(() => expect(calls('/recalculations')).toHaveLength(1))
  expect(aiButton('start').disabled).toBe(true); expect(aiButton('accept').disabled).toBe(true)
  // 直接调用处理器也必须经过保护，不能只依靠禁用按钮。
  await aiButton('accept').onclick!.call(aiButton('accept'),new MouseEvent('click') as PointerEvent)
  await aiButton('start').onclick!.call(aiButton('start'),new MouseEvent('click') as PointerEvent)
  expect(calls('/ai/edit/accept')).toHaveLength(0); expect(calls('/ai/start')).toHaveLength(1)
  expect(options.draft.operations).toEqual([]); expect(viewRefresh).not.toHaveBeenCalled()
  const normal=fetcher.getMockImplementation()!
  fetcher.mockImplementation(async(url:string) => url.includes('/by-request/')?response(task(outcome)):normal(url))
  finishRefresh(response(task(outcome))); await assertDownload(format)
  await vi.waitFor(() => expect(aiButton('accept').disabled).toBe(false))
  aiButton('accept').click(); await vi.waitFor(() => expect(calls('/ai/edit/accept')).toHaveLength(1))
  finishAccept(response({operations:[operation(format)]}))
  await vi.waitFor(() => expect(options.draft.operations).toEqual([operation(format)]))
})
it('rejects an acceptance response if the external write lock changes while awaiting it',async()=>{
  let locked=false, finish!: (value:unknown)=>void
  const draft=new NativeDraft({documentId:'guard',revision:1,sourceSha256:sha,scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},localStorage)
  const api={aiStart:vi.fn().mockResolvedValue({editId:'edit',status:'succeeded',snapshotSha256:'snapshot'}),aiAccept:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve})),aiCancel:vi.fn().mockResolvedValue({})}
  const root=document.createElement('div'),refresh=vi.fn(async()=>{})
  const binding=bindNativeAI(root,{api:api as never,draft,view:{refresh},onDraftChange(){},locked:()=>locked})
  binding.setSelection([{blockId:'p1'}]);root.querySelector('textarea')!.value='改写'
  root.querySelector<HTMLButtonElement>('[data-ai=start]')!.click()
  await vi.waitFor(()=>expect(root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.disabled).toBe(false))
  root.querySelector<HTMLButtonElement>('[data-ai=accept]')!.click();locked=true
  finish({operations:[operation('docx')]})
  await vi.waitFor(()=>expect(root.textContent).toContain('当前修订正在保存、刷新或已关闭'))
  expect(draft.operations).toEqual([]);expect(refresh).not.toHaveBeenCalled();binding.dispose()
})
