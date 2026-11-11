import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MetricEditor } from './editor'

let root: Root, client: QueryClient
const fetcher = vi.fn(), scope = { database: 'warehouse', companyId: 'a' }
const definition = { id: 'budget', name: '预算额', scopeId: 'scope-a', revision: 2, kind: 'sum',
  fieldRef: 'source.db.budget.amount', timeField: 'source.db.budget.day', unit: '元', grain: ['project'],
  dimensions: [{ id: 'project', fieldRef: 'source.db.budget.project' }], numeratorVersion: null, denominatorVersion: null,
  timeZone: null, storageTimeZone: null, aggregationPolicy: { observationKind: 'flow', timeAggregation: 'sum', reset: null }, aliases: [] as string[] }
let draft: { version: number; document: typeof definition; contentHash: string }
let published: null | { revision: number; document: typeof definition; contentHash: string }
const response = (value: unknown) => new Response(JSON.stringify(value))
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  sessionStorage.clear(); vi.stubGlobal('fetch', fetcher)
  draft = { version: 3, document: definition, contentHash: 'hash-3' }; published = null
  fetcher.mockImplementation(async (_: string, init: RequestInit) => {
    if (init.method === 'PUT') {
      const body = JSON.parse(String(init.body)); draft = { version: body.expectedVersion + 1,
        document: { ...body.definition, scopeId: 'scope-a', revision: 2 }, contentHash: 'hash-4' }; return response(draft)
    }
    if (init.method === 'POST') { published = { revision: draft.document.revision, document: draft.document, contentHash: draft.contentHash }; return response({ ...published, issues: [] }) }
    return response({ draft, published, retirement: null })
  })
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); vi.unstubAllGlobals(); fetcher.mockReset() })
async function until(check: () => void) {
  for (let i = 0; i < 70; i++) { await act(async () => { await new Promise(resolve => setTimeout(resolve, 15)) }); try { check(); return } catch {} } check()
}
async function mount() {
  await act(async () => root.render(<QueryClientProvider client={client}><MetricEditor scope={scope} metricId="budget" username="admin" csrf="csrf" /></QueryClientProvider>))
  await until(() => expect(document.querySelector<HTMLInputElement>('#metric-name')?.value).toBe('预算额'))
}
const button = (name: string) => [...document.querySelectorAll('button')].find(item => item.textContent?.replaceAll(' ', '').includes(name))!
async function click(name: string) { await act(async () => button(name).click()) }
async function name(value: string) {
  const input = document.querySelector<HTMLInputElement>('#metric-name')!
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })) })
}
it('saves with CAS without sending server identity or auto publishing', async () => {
  await mount(); await name('调整后预算'); await click('保存指标草稿')
  await until(() => expect(document.body.textContent).toContain('草稿已保存'))
  const body = JSON.parse(String(fetcher.mock.calls.find(([, init]) => init.method === 'PUT')![1].body))
  expect(body).toMatchObject({ scopeDatabase: 'warehouse', companyId: 'a', expectedVersion: 3, definition: { id: 'budget', name: '调整后预算', grain: ['project'] } })
  expect(body.definition).not.toHaveProperty('scopeId'); expect(body.definition).not.toHaveProperty('revision')
  expect(fetcher.mock.calls.filter(([, init]) => init.method === 'POST')).toHaveLength(0)
})
it('recovers a saved unknown response after remount by GET without repeating PUT', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init: RequestInit) => { const result = await handler(path, init); if (init.method === 'PUT') throw Error('lost'); return result })
  await mount(); await name('恢复预算'); await click('保存指标草稿')
  await until(() => expect(document.body.textContent).toContain('结果待确认'))
  await act(async () => root.unmount()); root = createRoot(document.getElementById('root')!)
  await act(async () => root.render(<QueryClientProvider client={client}><MetricEditor scope={scope} metricId="budget" username="admin" csrf="csrf" /></QueryClientProvider>))
  await click('读取原提交结果'); await until(() => expect(document.body.textContent).toContain('当前草稿与原提交一致'))
  expect(fetcher.mock.calls.filter(([, init]) => init.method === 'PUT')).toHaveLength(1)
})
it('publishes a saved exact version only after explicit acknowledgement', async () => {
  await mount(); expect(button('发布指标版本').disabled).toBe(true)
  await act(async () => document.querySelector<HTMLInputElement>('[aria-label="确认指标发布"]')!.click())
  await click('发布指标版本'); await until(() => expect(document.body.textContent).toContain('指标版本已发布'))
  expect(JSON.parse(String(fetcher.mock.calls.find(([, init]) => init.method === 'POST')![1].body))).toEqual({ scopeDatabase: 'warehouse', companyId: 'a', expectedVersion: 3 })
  expect(document.body.textContent).toContain('不会自动替换口径或默认')
})
it('preserves local input on 409 without automatically retrying or rebasing', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init: RequestInit) => init.method === 'PUT'
    ? new Response(JSON.stringify({ code: 'management_version_conflict', message: '草稿已更新' }), { status: 409 }) : handler(path, init))
  await mount(); await name('本地修改'); await click('保存指标草稿')
  await until(() => expect(document.body.textContent).toContain('结果待确认'))
  await click('读取原提交结果'); await until(() => expect(document.body.textContent).toContain('原请求尚未登记'))
  expect(document.querySelector<HTMLInputElement>('#metric-name')!.value).toBe('本地修改')
  expect(fetcher.mock.calls.filter(([, init]) => init.method === 'PUT')).toHaveLength(1)
})
it('can explicitly retry an uncommitted first publish only after rechecking its draft', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init: RequestInit) => {
    if (init.method === 'POST') throw Error('never reached server')
    if (path.includes('revision=')) return new Response(JSON.stringify({ code: 'management_metric_not_found' }), { status: 404 })
    return handler(path, init)
  })
  await mount(); await act(async () => document.querySelector<HTMLInputElement>('[aria-label="确认指标发布"]')!.click())
  await click('发布指标版本'); await click('读取原提交结果')
  await until(() => expect(document.body.textContent).toContain('原请求尚未登记'))
  expect(button('确认重提原请求').disabled).toBe(true)
  await act(async () => document.querySelector<HTMLInputElement>('[aria-label="确认指标发布"]')!.click())
  expect(button('确认重提原请求').disabled).toBe(false)
  expect(fetcher.mock.calls.filter(([, init]) => init.method === 'POST')).toHaveLength(1)
})
it('blocks corrupted account-scoped cache without issuing a write', async () => {
  sessionStorage.setItem('management-metric-editor:' + JSON.stringify(['admin', 'warehouse', 'a', 'budget']), '{broken')
  await act(async () => root.render(<QueryClientProvider client={client}><MetricEditor scope={scope} metricId="budget" username="admin" csrf="csrf" /></QueryClientProvider>))
  await until(() => expect(document.body.textContent).toContain('本地指标草稿无法读取'))
  expect(button('保存指标草稿').disabled).toBe(true)
  expect(button('发布指标版本').disabled).toBe(true)
})
it('retains an externally advanced conflicting draft and local input', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init: RequestInit) => {
    if (init.method === 'PUT') { draft = { ...draft, version: 5 }; throw Error('lost') }
    return handler(path, init)
  })
  await mount(); await name('保留我的改动'); await click('保存指标草稿'); await click('读取原提交结果')
  await until(() => expect(document.body.textContent).toContain('服务器版本与原请求冲突'))
  expect(document.querySelector<HTMLInputElement>('#metric-name')!.value).toBe('保留我的改动')
  expect(button('确认重提原请求')).toBeUndefined()
})
it('recovers an immutable published version after a lost response without another POST', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init: RequestInit) => { const result = await handler(path, init); if (init.method === 'POST') throw Error('lost'); return result })
  await mount(); await act(async () => document.querySelector<HTMLInputElement>('[aria-label="确认指标发布"]')!.click())
  await click('发布指标版本'); await click('读取原提交结果')
  await until(() => expect(document.body.textContent).toContain('当前发布与原提交一致'))
  expect(fetcher.mock.calls.filter(([, init]) => init.method === 'POST')).toHaveLength(1)
})
it('does not write if request persistence fails', async () => {
  await mount(); await name('本地修改')
  const setter = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('full') })
  try {
    await click('保存指标草稿'); expect(document.body.textContent).toContain('未提交')
    expect(fetcher.mock.calls.filter(([, init]) => init.method !== 'GET')).toHaveLength(0)
  } finally { setter.mockRestore() }
})
it('can recheck an uncommitted first save when no server metric exists', async () => {
  const { scopeId: _, revision: __, ...value } = definition
  sessionStorage.setItem('management-metric-editor:' + JSON.stringify(['admin', 'warehouse', 'a', 'budget']), JSON.stringify({
    baseline: null, value, pending: { action: 'save', expectedVersion: 0, definition: value, revision: null, contentHash: null },
  }))
  fetcher.mockImplementation(async () => new Response(JSON.stringify({ code: 'management_metric_not_found' }), { status: 404 }))
  await act(async () => root.render(<QueryClientProvider client={client}><MetricEditor scope={scope} metricId="budget" username="admin" csrf="csrf" /></QueryClientProvider>))
  await click('读取原提交结果')
  await until(() => expect(document.body.textContent).toContain('原请求尚未登记'))
  expect(fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true)
})
it('compares the saved target to the published version, excluding unsaved input', async () => {
  published = { revision: 1, contentHash: 'old-hash', document: { ...definition, revision: 1, name: '旧预算', unit: '万元',
    fieldRef: 'source.db.budget.original_amount' } }
  await mount()
  const comparison = document.querySelector('[aria-label="指标发布变更"]')!
  expect(comparison.textContent).toContain('当前发布：版本 1')
  expect(comparison.textContent).toContain('目标发布：版本 2')
  expect(comparison.textContent).toContain('旧预算')
  expect(comparison.textContent).toContain('source.db.budget.original_amount')
  expect(comparison.textContent).toContain('取数字段')
  expect(comparison.textContent).toContain('万元')
  await name('尚未保存的新名称')
  expect(comparison.textContent).not.toContain('尚未保存的新名称')
  expect(document.body.textContent).toContain('以下对比仅包含已保存草稿')
  expect(button('发布指标版本').disabled).toBe(true)
})
it('shows exact ratio dependency changes and preserves the published formula', async () => {
  const ratio = { ...definition, kind: 'ratio', fieldRef: null, timeField: null, unit: '%',
    numeratorVersion: { metricId: 'actual', revision: 2 }, denominatorVersion: { metricId: 'budget', revision: 1 } }
  draft = { ...draft, document: ratio as unknown as typeof definition }
  published = { revision: 1, contentHash: 'old-ratio', document: { ...ratio, revision: 1,
    numeratorVersion: { metricId: 'actual', revision: 1 } } as unknown as typeof definition }
  await mount()
  const comparison = document.querySelector('[aria-label="指标发布变更"]')!
  expect(comparison.textContent).toContain('分子指标版本')
  expect(comparison.textContent).toContain('actual · 版本 1')
  expect(comparison.textContent).toContain('actual · 版本 2')
  expect(comparison.textContent).toContain('比率')
  expect(comparison.textContent).not.toContain('old-ratio')
  expect(published.document.numeratorVersion).toEqual({ metricId: 'actual', revision: 1 })
})

it('adopts explicit metric conflict choices using a new CAS only on later save',async()=>{
 const handler=fetcher.getMockImplementation()!;let first=true
 fetcher.mockImplementation(async(path:string,init:RequestInit)=>{
  if(init.method==='PUT'&&first){first=false;draft={...draft,version:4,contentHash:'server-4',document:{...draft.document,name:'服务器指标名称',aliases:['服务器别名']}};return new Response('{}',{status:409})}return handler(path,init)
 })
 await mount();await name('本地指标名称');await click('保存指标草稿');await click('读取原提交结果')
 await until(()=>expect(document.querySelector('[aria-label="指标冲突逐项对照"]')).toBeTruthy())
 expect(button('采用指标核对结果继续编辑').disabled).toBe(true)
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="指标名称：保留本地"]')!.click())
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="别名：采用服务器"]')!.click())
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="确认指标冲突选择"]')!.click())
 await click('采用指标核对结果继续编辑');await until(()=>expect(document.body.textContent).toContain('已按服务器指标草稿版本 4 准备本地修改'))
 expect(document.querySelector<HTMLInputElement>('#metric-name')!.value).toBe('本地指标名称')
 expect(document.querySelector<HTMLTextAreaElement>('[aria-label="指标别名"]')!.value).toBe('服务器别名')
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='PUT')).toHaveLength(1)
 const archive=Object.keys(sessionStorage).find(k=>k.startsWith('management-metric-conflict:'))!
 expect(JSON.parse(sessionStorage.getItem(archive)!)).toMatchObject({pending:{expectedVersion:3,definition:{name:'本地指标名称'}}})
 await click('保存指标草稿');await until(()=>expect(document.body.textContent).toContain('草稿已保存'))
 expect(JSON.parse(fetcher.mock.calls.filter(([,o])=>o.method==='PUT').at(-1)![1].body)).toMatchObject({expectedVersion:4,definition:{name:'本地指标名称',aliases:['服务器别名']}})
})
it('resets metric choices when the server advances again before adoption',async()=>{
 const handler=fetcher.getMockImplementation()!
 fetcher.mockImplementation(async(path:string,init:RequestInit)=>{if(init.method==='PUT'){draft={...draft,version:4,contentHash:'server-4',document:{...draft.document,name:'服务器名称'}};return new Response('{}',{status:409})}return handler(path,init)})
 await mount();await name('本地修改');await click('保存指标草稿');await click('读取原提交结果')
 await until(()=>expect(document.querySelector('[aria-label="指标名称：保留本地"]')).toBeTruthy())
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="指标名称：保留本地"]')!.click())
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="确认指标冲突选择"]')!.click())
 draft={...draft,version:5,contentHash:'server-5',document:{...draft.document,name:'服务器再次修改'}}
 await click('采用指标核对结果继续编辑');await until(()=>expect(document.body.textContent).toContain('服务器指标草稿再次变化'))
 expect(button('采用指标核对结果继续编辑').disabled).toBe(true)
 expect(document.querySelector<HTMLInputElement>('#metric-name')!.value).toBe('本地修改')
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='PUT')).toHaveLength(1)
})

it('adopts the complete server calculation group without mixing ratio and sum fields',async()=>{
 const handler=fetcher.getMockImplementation()!
 fetcher.mockImplementation(async(path:string,init:RequestInit)=>{
  if(init.method==='PUT'){draft={...draft,version:4,contentHash:'server-ratio',document:{...draft.document,kind:'ratio',unit:'%',fieldRef:null,timeField:null,numeratorVersion:{metricId:'actual',revision:2},denominatorVersion:{metricId:'budget',revision:1}} as unknown as typeof definition};return new Response('{}',{status:409})}return handler(path,init)
 })
 await mount();await name('本地保留名称');await click('保存指标草稿');await click('读取原提交结果')
 await until(()=>expect(document.querySelector('[aria-label="计算定义：采用服务器"]')).toBeTruthy())
 expect(document.querySelector('[aria-label="指标冲突逐项对照"]')!.textContent).toContain('actual / 2')
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="指标名称：保留本地"]')!.click())
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="计算定义：采用服务器"]')!.click())
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="确认指标冲突选择"]')!.click())
 await click('采用指标核对结果继续编辑');await until(()=>expect(document.body.textContent).toContain('已按服务器指标草稿版本 4'))
 const saved=JSON.parse(sessionStorage.getItem('management-metric-editor:'+JSON.stringify(['admin','warehouse','a','budget']))!)
 expect(saved.value).toMatchObject({name:'本地保留名称',kind:'ratio',unit:'%',fieldRef:null,timeField:null,numeratorVersion:{metricId:'actual',revision:2},denominatorVersion:{metricId:'budget',revision:1}})
 expect(saved.pending).toBeNull();expect(fetcher.mock.calls.filter(([,o])=>o.method==='PUT')).toHaveLength(1)
})
it('retains metric pending request when conflict record persistence fails',async()=>{
 const handler=fetcher.getMockImplementation()!
 fetcher.mockImplementation(async(path:string,init:RequestInit)=>{if(init.method==='PUT'){draft={...draft,version:4,contentHash:'server-4',document:{...draft.document,name:'服务器名称'}};return new Response('{}',{status:409})}return handler(path,init)})
 await mount();await name('本地修改');await click('保存指标草稿');await click('读取原提交结果')
 await until(()=>expect(document.querySelector('[aria-label="指标名称：保留本地"]')).toBeTruthy())
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="指标名称：保留本地"]')!.click())
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="确认指标冲突选择"]')!.click())
 const setter=vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('full')})
 try{await click('采用指标核对结果继续编辑');await until(()=>expect(document.body.textContent).toContain('无法保存记录'))}finally{setter.mockRestore()}
 expect(JSON.parse(sessionStorage.getItem('management-metric-editor:'+JSON.stringify(['admin','warehouse','a','budget']))!).pending.expectedVersion).toBe(3)
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='PUT')).toHaveLength(1)
})
