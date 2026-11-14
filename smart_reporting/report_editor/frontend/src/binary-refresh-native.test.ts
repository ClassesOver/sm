import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import style from './style.css?raw'
import nativeStyle from './native.css?raw'
import pdfStyle from './pdf.css?raw'
import docxStyle from './docx.css?raw'
import officeStyle from './office-theme.css?raw'
import refreshStyle from './binary-refresh.css?raw'
import { startNativeEditor } from './native-main'
const views = vi.hoisted(() => ({ pdf: vi.fn(), docx: vi.fn() }))
vi.mock('./pdf-main', () => ({ createPdfEditorView: views.pdf }))
vi.mock('./docx-main', () => ({ createDocxEditorView: views.docx }))
const sha = 'a'.repeat(64), digest = 'b'.repeat(64)
let options: any
let failPreview = false
let pendingInput = false
let capability = true
let origin = 'report'
let saveResult: unknown
let fetcher: ReturnType<typeof vi.fn>
let taskReads = 0
const task = { taskId: 'recalc-fixture', status: 'completed', result: { issueCodes: ['code_only'], validationPassed: false }, execution: { status: 'completed', runId: 'run', issueCodes: [] } }
beforeEach(() => {
  document.body.innerHTML = '<div id="app"></div>'
  const css = document.createElement('style'); css.textContent = style + nativeStyle + pdfStyle + docxStyle + officeStyle + refreshStyle; document.head.append(css)
  localStorage.clear(); failPreview = false; pendingInput = false; capability = true; origin = 'report'; taskReads = 0
  saveResult = { revision: 2, revisionRegistered: true, artifacts: { word: { downloadUrl: '/saved.docx' }, pdf: { downloadUrl: '/saved.pdf' } }, validation: { ok: false, issues: [{code:'saved_warning',message:'保存告警'}] }, editor: { openUrl: '/reports/v1/native/doc/2' } }
  for (const view of [views.pdf, views.docx]) view.mockImplementation(async (_shell, value) => {
    options = value
    if (failPreview) throw new Error('preview broken')
    return { setSaving() {}, dispose() {}, flushPendingEdits() { if(pendingInput) { pendingInput = false; value.draft.setOperations([{kind:'replaceParagraph',text:'未提交输入'}]) } } }
  })
  fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/context')) return new Response(JSON.stringify({ context: { documentId: 'doc', revision: Number(location.pathname.split('/').at(-1)), format: location.search.includes('word') ? 'docx' : 'pdf', origin, sourceFile: { sha256: sha, size: 12 }, scope: { database: 'fixture', companyId: 'c', userId: 'u', threadId: 't' } }, contextSha256: digest, dataRefresh: {available: capability}, csrfToken: 'native-token', editingEnabled: true }))
    if (url.endsWith('/save')) return new Response(JSON.stringify(saveResult))
    if (url.endsWith('/delivery')) return new Response(JSON.stringify({ task, delivery: { revision: 2, pdf: {downloadUrl:'/actual.pdf'}, word:{downloadUrl:'/actual.docx'}, validation: {ok:false,issues:[{code:'post_validation',message:'后置验收失败'}]} } }))
    if(url.includes('/by-request/')) taskReads++
    return new Response(JSON.stringify(task))
  })
  vi.stubGlobal('fetch', fetcher)
})
afterEach(() => { window.dispatchEvent(new Event('pagehide')); document.head.querySelectorAll('style').forEach(s=>s.remove()); vi.unstubAllGlobals() })
const refreshButton = () => document.querySelector<HTMLButtonElement>('[data-action="binary-refresh"]')!
it.each(['pdf','docx'])('mounts %s formal refresh with exact native CSRF and only the actual target download', async format => {
  history.replaceState({}, '', '/reports/v1/native/doc/1' + (format==='docx'?'?word':''))
  await startNativeEditor()
  expect(refreshButton()).not.toBeNull()
  for(let element:Element|null=refreshButton();element;element=element.parentElement)expect(getComputedStyle(element).display).not.toBe('none')
  refreshButton().click()
  await vi.waitFor(()=>expect(document.querySelector('.binary-refresh-result')?.textContent).toContain('后置验收失败'))
  const post = fetcher.mock.calls.find(([url,init])=>String(url).endsWith('/recalculations') && init?.method==='POST')!
  expect(JSON.parse(post[1]!.body as string)).toEqual({requestId: expect.any(String),expectedBinarySha256:sha})
  expect(new Headers(post[1]!.headers).get('X-CSRF-Token')).toBe('native-token')
  const links = document.querySelectorAll<HTMLAnchorElement>('.binary-refresh-result a')
  expect(links).toHaveLength(1)
  expect(links[0].getAttribute('href')).toBe(format==='pdf'?'/actual.pdf':'/actual.docx')
  for(let element:Element|null=links[0];element;element=element.parentElement)expect(getComputedStyle(element).display).not.toBe('none')
  expect(document.querySelector('.binary-refresh-result')!.textContent).toContain('code_only')
})
it('flushes pending native input, saves once, and stops on the closed old branch', async()=>{
  history.replaceState({}, '', '/reports/v1/native/doc/1'); await startNativeEditor(); pendingInput=true
  refreshButton().click()
  await vi.waitFor(()=>expect(document.querySelector('.native-next-revision')).not.toBeNull())
  expect(fetcher.mock.calls.filter(([url])=>String(url).endsWith('/save'))).toHaveLength(1)
  expect(fetcher.mock.calls.some(([url])=>String(url).endsWith('/recalculations'))).toBe(false)
  refreshButton().click(); await Promise.resolve()
  expect(fetcher.mock.calls.some(([url])=>String(url).endsWith('/recalculations'))).toBe(false)
})
it.each(['upload','derived'])('does not expose formal refresh for %s', async value=>{
  origin=value;history.replaceState({}, '', '/reports/v1/native/doc/1'); await startNativeEditor()
  expect(refreshButton()).toBeNull()
})
it('recovers the exact cached task before broken preview even when capability is unavailable', async()=>{
  history.replaceState({}, '', '/reports/v1/native/doc/1'); await startNativeEditor();refreshButton().click()
  await vi.waitFor(()=>expect(taskReads).toBeGreaterThan(0))
  window.dispatchEvent(new Event('pagehide'));document.body.innerHTML='<div id="app"></div>'
  capability=false;failPreview=true;await startNativeEditor()
  await vi.waitFor(()=>expect(document.querySelector('.binary-refresh-result')?.textContent).toContain('后置验收失败'))
  expect(refreshButton()).toBeNull()
  expect(document.body.textContent).toContain('preview broken')
})

it.each(['failed','unregistered','unknown'])('save-first %s never submits and retains trustworthy generated downloads',async kind=>{
  history.replaceState({}, '', '/reports/v1/native/doc/1');await startNativeEditor();pendingInput=true
  if(kind==='failed') fetcher.mockImplementationOnce(async()=>new Response(JSON.stringify({detail:{message:'409 save conflict'}}),{status:409}))
  else saveResult={...(saveResult as object),revisionRegistered:kind==='unregistered'?false:undefined}
  refreshButton().click()
  await vi.waitFor(()=>expect(fetcher.mock.calls.some(([url])=>String(url).endsWith('/save'))).toBe(true))
  await vi.waitFor(()=>expect(options.draft.saving).toBe(false))
  expect(fetcher.mock.calls.some(([url])=>String(url).endsWith('/recalculations'))).toBe(false)
  if(kind!=='failed') expect(document.querySelector('.native-delivery a')).not.toBeNull()
})
it('unknown submit reads original requestId before explicit idempotent retry without another save or flush',async()=>{
  history.replaceState({}, '', '/reports/v1/native/doc/1');await startNativeEditor()
  const normal=fetcher.getMockImplementation()!
  let attempt=0
  fetcher.mockImplementation(async(url:string,init?:RequestInit)=>{
    if(url.endsWith('/recalculations')){attempt++;if(attempt===1)throw new Error('connection lost')}
    if(url.includes('/by-request/')) return new Response(JSON.stringify({taskId:'recalc-fixture',status:'pending',result:null,execution:{status:'not_dispatched',runId:null,issueCodes:['dispatch_pending']}}))
    return normal(url,init)
  })
  refreshButton().click()
  await vi.waitFor(()=>expect(document.body.textContent).toContain('not_dispatched'))
  expect(fetcher.mock.calls.at(-1)![0]).toContain('/by-request/')
  const first=fetcher.mock.calls.find(([url])=>String(url).endsWith('/recalculations'))!
  const retry=[...document.querySelectorAll<HTMLButtonElement>('.binary-refresh button')].find(b=>b.textContent==='重试原刷新任务')!
  retry.click();await vi.waitFor(()=>expect(attempt).toBe(2))
  const posts=fetcher.mock.calls.filter(([url])=>String(url).endsWith('/recalculations'))
  expect(posts.map(([,init])=>JSON.parse(init!.body as string))).toEqual([JSON.parse(first[1]!.body as string),JSON.parse(first[1]!.body as string)])
  expect(fetcher.mock.calls.some(([url])=>String(url).endsWith('/save'))).toBe(false)
})
it.each(['revision','context','sha','document'])('does not reuse cached task across a changed %s',async field=>{
  history.replaceState({}, '', '/reports/v1/native/doc/1');await startNativeEditor();refreshButton().click()
  await vi.waitFor(()=>expect(taskReads).toBeGreaterThan(0));window.dispatchEvent(new Event('pagehide'))
  document.body.innerHTML='<div id="app"></div>';fetcher.mockClear()
  const normal=fetcher.getMockImplementation()!
  fetcher.mockImplementation(async(url:string,init?:RequestInit)=>{
    const response=await normal(url,init)
    if(!url.endsWith('/context'))return response
    const value=await response.json()
    if(field==='context')value.contextSha256='c'.repeat(64)
    if(field==='sha')value.context.sourceFile.sha256='c'.repeat(64)
    if(field==='document')value.context.documentId='other'
    return new Response(JSON.stringify(value))
  })
  history.replaceState({},'',field==='revision'?'/reports/v1/native/doc/2':field==='document'?'/reports/v1/native/other/1':'/reports/v1/native/doc/1')
  await startNativeEditor();await Promise.resolve()
  expect(fetcher.mock.calls.some(([url])=>String(url).includes('/by-request/'))).toBe(false)
  expect(refreshButton().disabled).toBe(false)
})
it('unverified recovery preserves actual download but never claims passed validation',async()=>{
  history.replaceState({}, '', '/reports/v1/native/doc/1');await startNativeEditor()
  const normal=fetcher.getMockImplementation()!
  const recovered={taskId:'recalc-fixture',reportId:'report',status:'unavailable',inputVerified:false,errorCode:'refresh_task_input_unverified'}
  fetcher.mockImplementation(async(url:string,init?:RequestInit)=>{
    if(url.includes('/by-request/')) return new Response(JSON.stringify(recovered))
    if(url.endsWith('/delivery'))return new Response(JSON.stringify({task:recovered,delivery:{pdf:{downloadUrl:'/verified.pdf'},validation:{ok:true,issues:[{code:'frozen_missing'}]}}}))
    return normal(url,init)
  })
  refreshButton().click();await vi.waitFor(()=>expect(document.querySelector('.binary-refresh-result a')).not.toBeNull())
  expect(document.querySelector('.binary-refresh-result')!.textContent).toContain('inputVerified=false')
  expect(document.querySelector('.binary-refresh-result')!.textContent).not.toContain('文件验收通过')
})

it('blocks saving while dispatch is in flight and disables the action until preview is loaded',async()=>{
  history.replaceState({}, '', '/reports/v1/native/doc/1')
  let load: ((value:unknown)=>void)|undefined
  views.pdf.mockImplementationOnce(async(_shell,value)=>{options=value;return await new Promise(resolve=>{load=resolve})})
  const opening=startNativeEditor()
  await vi.waitFor(()=>expect(refreshButton()).not.toBeNull())
  expect(refreshButton().disabled).toBe(true);refreshButton().click()
  expect(fetcher.mock.calls).toHaveLength(1)
  load!({setSaving(){},refresh:async()=>{}});await opening
  let deliver: ((value:Response)=>void)|undefined
  const normal=fetcher.getMockImplementation()!
  fetcher.mockImplementation(async(url:string,init?:RequestInit)=>url.endsWith('/recalculations')?await new Promise<Response>(resolve=>{deliver=resolve}):normal(url,init))
  refreshButton().click();await vi.waitFor(()=>expect(deliver).toBeDefined())
  const save=document.querySelector<HTMLButtonElement>('[data-action=save]')!
  expect(save.disabled).toBe(true);save.click()
  expect(fetcher.mock.calls.some(([url])=>String(url).endsWith('/save'))).toBe(false)
  deliver!(new Response(JSON.stringify(task)))
  await vi.waitFor(()=>expect(document.querySelector('.binary-refresh-result a')).not.toBeNull())
})

it('keeps original-task reads from racing an active save',async()=>{
 history.replaceState({}, '', '/reports/v1/native/doc/1');await startNativeEditor();refreshButton().click()
 await vi.waitFor(()=>expect(document.querySelector('.binary-refresh-result a')).not.toBeNull())
 const normal=fetcher.getMockImplementation()!
 let finish: ((response:Response)=>void)|undefined
 fetcher.mockImplementation(async(url:string,init?:RequestInit)=>url.endsWith('/save')?await new Promise<Response>(resolve=>{finish=resolve}):normal(url,init))
 pendingInput=true;document.querySelector<HTMLButtonElement>('[data-action=save]')!.click()
 await vi.waitFor(()=>expect(finish).toBeDefined())
 const read=[...document.querySelectorAll<HTMLButtonElement>('.binary-refresh button')].find(b=>b.textContent==='读取原刷新任务')!
 const count=taskReads
 expect(read.disabled).toBe(true);read.click();await Promise.resolve();expect(taskReads).toBe(count)
 finish!(new Response(JSON.stringify(saveResult)))
 await vi.waitFor(()=>expect(options.draft.saving).toBe(false))
})
