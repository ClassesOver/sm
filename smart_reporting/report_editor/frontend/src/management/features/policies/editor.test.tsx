import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { PolicyEditor } from './editor'

let root: Root, client: QueryClient
const fetcher = vi.fn(), scope = { database: 'warehouse', companyId: 'a' }
const definition = { id: 'monthly', name: '月度预算口径', scopeId: 'scope-a', revision: 2, scenario: 'budget_execution',
 validFrom: '2026-01-01', validTo: '2027-01-01' as string | null, metricVersions: [{ metricId: 'budget', revision: 1 }],
 evidenceReleaseId: 'rules-1', decisionNotes: '原始决策说明',
 filters: [{ fieldRef: 'warehouse.test.budget.project', operator: 'eq', values: ['A'] }],
 joins: [{ leftKeys: ['warehouse.test.budget.project'], rightKeys: ['warehouse.test.actual.project'], cardinality: 'many_to_one', outputGrain: ['project'] }],
 readinessPolicy: { expectedPeriods: [], expectedGroups: [], watermarkField: 'warehouse.test.budget.updated', maximumDelaySeconds: 3600, emptyObservation: 'unknown' } }
let draft: { version: number; document: typeof definition; contentHash: string }
let published: null | { revision: number; document: typeof definition; contentHash: string }
const response = (value: unknown) => new Response(JSON.stringify(value))
beforeEach(() => {
 Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
 vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
 vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
 vi.stubGlobal('fetch', fetcher); sessionStorage.clear()
 draft = { version: 3, document: definition, contentHash: 'draft-3' }
 published = { revision: 1, document: { ...definition, revision: 1, name: '旧口径' }, contentHash: 'published-1' }
 fetcher.mockImplementation(async (path: string, init: RequestInit) => {
  if (path.includes('/metrics/')) return response({ published: { revision: 1, document: { id: 'budget', name: '预算额', unit: 'CNY', grain: ['project'] } }, retirement: null })
  if (path.includes('/business-evidence-releases/')) return response({ releaseId: 'rules-1', kind: 'rule_evidence', documents: [{ reference: { documentId: 'rules', revision: 1 }, metadata: { title: '预算管理制度' } }] })
  if (path.endsWith('/preview')) return response({ calculationChanged: false, changedFields: [], metricVersionsChanged: false, evidenceChanged: false, issues: [{ code: 'missing_time_zone', impact: 'warning', message: '未声明时区，需业务核对' }] })
  if (init.method === 'PUT') {
   const body = JSON.parse(String(init.body)); draft = { version: body.expectedVersion + 1, document: { ...body.definition, scopeId: 'scope-a', revision: 2 }, contentHash: 'draft-4' }; return response(draft)
  }
  if (path.endsWith('/publish')) { published = { revision: draft.document.revision, document: draft.document, contentHash: draft.contentHash }; return response({ ...published, issues: [{ message: '未声明时区，需业务核对' }] }) }
  return response({ draft, published, retirement: null })
 })
 client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); vi.unstubAllGlobals(); fetcher.mockReset() })
async function until(check: () => void) { for (let i = 0; i < 70; i++) { await act(async () => { await new Promise(resolve => setTimeout(resolve, 15)) }); try { check(); return } catch {} } check() }
async function mount() {
 await act(async () => root.render(<QueryClientProvider client={client}><PolicyEditor scope={scope} policyId="monthly" username="admin" csrf="csrf" /></QueryClientProvider>))
 await until(() => expect(document.querySelector<HTMLInputElement>('#policy-name')?.value).toBe('月度预算口径'))
}
const button = (name: string) => [...document.querySelectorAll('button')].find(item => item.textContent?.replaceAll(' ', '').includes(name))!
async function click(name: string) { await act(async () => button(name).click()) }
async function input(id: string, value: string) { const field = document.querySelector<HTMLInputElement>('#' + id)!; await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(field, value); field.dispatchEvent(new Event('input', { bubbles: true })) }) }
it('saves CAS draft preserving filters, joins and readiness without server identity or default mutation', async () => {
 await mount(); await input('policy-name', '修订口径'); await click('保存口径草稿')
 await until(() => expect(document.body.textContent).toContain('口径草稿已保存'))
 const body = JSON.parse(String(fetcher.mock.calls.find(([, init]) => init.method === 'PUT')![1].body))
 expect(body).toMatchObject({ expectedVersion: 3, scopeDatabase: 'warehouse', companyId: 'a', definition: { name: '修订口径', filters: definition.filters, joins: definition.joins, readinessPolicy: definition.readinessPolicy } })
 expect(body.definition).not.toHaveProperty('scopeId'); expect(body.definition).not.toHaveProperty('revision')
 expect(fetcher.mock.calls.some(([path]) => path.includes('report-policy-defaults'))).toBe(false)
})
it('requires a preview of saved content and acknowledgement, keeping soft issues visible', async () => {
 await mount(); expect(button('发布口径版本').disabled).toBe(true)
 await click('核对发布变更'); await until(() => expect(document.body.textContent).toContain('未声明时区，需业务核对'))
 expect(document.body.textContent).toContain('计算规则未变')
 await act(async () => document.querySelector<HTMLInputElement>('[aria-label="确认口径发布"]')!.click())
 expect(button('发布口径版本').disabled).toBe(false)
 await click('发布口径版本'); await until(() => expect(document.body.textContent).toContain('口径版本已发布'))
 expect(document.body.textContent).toContain('未声明时区，需业务核对')
 expect(JSON.parse(String(fetcher.mock.calls.find(([path]) => path.endsWith('/publish'))![1].body))).toEqual({ scopeDatabase: 'warehouse', companyId: 'a', expectedVersion: 3 })
})
it('invalidates preview after local modification and does not publish unsaved content', async () => {
 await mount(); await click('核对发布变更'); await until(() => expect(document.body.textContent).toContain('计算规则未变'))
 await input('policy-name', '尚未保存'); expect(button('发布口径版本').disabled).toBe(true)
 expect(document.body.textContent).not.toContain('计算规则未变')
})
it('restores a lost save response after remount with reads only', async () => {
 const handler = fetcher.getMockImplementation()!
 fetcher.mockImplementation(async (path: string, init: RequestInit) => { const result = await handler(path, init); if (init.method === 'PUT') throw Error('lost'); return result })
 await mount(); await input('policy-name', '保存恢复'); await click('保存口径草稿')
 await until(() => expect(document.body.textContent).toContain('结果待确认'))
 await act(async () => root.unmount()); root = createRoot(document.getElementById('root')!)
 await act(async () => root.render(<QueryClientProvider client={client}><PolicyEditor scope={scope} policyId="monthly" username="admin" csrf="csrf" /></QueryClientProvider>))
 await click('读取原口径提交结果'); await until(() => expect(document.body.textContent).toContain('当前草稿与原提交一致'))
 expect(fetcher.mock.calls.filter(([, init]) => init.method === 'PUT')).toHaveLength(1)
})
it('restores exact published revision after loss without resubmission', async () => {
 const handler = fetcher.getMockImplementation()!
 fetcher.mockImplementation(async (path: string, init: RequestInit) => { const result = await handler(path, init); if (path.endsWith('/publish')) throw Error('lost'); return result })
 await mount(); await click('核对发布变更'); await until(() => expect(document.body.textContent).toContain('计算规则未变'))
 await act(async () => document.querySelector<HTMLInputElement>('[aria-label="确认口径发布"]')!.click()); await click('发布口径版本')
 await act(async () => root.unmount()); root = createRoot(document.getElementById('root')!)
 await act(async () => root.render(<QueryClientProvider client={client}><PolicyEditor scope={scope} policyId="monthly" username="admin" csrf="csrf" /></QueryClientProvider>))
 await click('读取原口径提交结果')
 await until(() => expect(document.body.textContent).toContain('当前发布与原提交一致'))
 expect(document.body.textContent).toContain('原发布核对告警：未声明时区，需业务核对')
 expect(fetcher.mock.calls.filter(([path]) => path.endsWith('/publish'))).toHaveLength(1)
})
it('preserves conflicting local content and never automatically retries', async () => {
 const handler = fetcher.getMockImplementation()!
 fetcher.mockImplementation(async (path: string, init: RequestInit) => { if (init.method === 'PUT') { draft = { ...draft, version: 5 }; return new Response(JSON.stringify({ message: '版本冲突' }), { status: 409 }) } return handler(path, init) })
 await mount(); await input('policy-name', '我的修改'); await click('保存口径草稿'); await click('读取原口径提交结果')
 await until(() => expect(document.body.textContent).toContain('服务器版本与原请求冲突'))
 expect(document.querySelector<HTMLInputElement>('#policy-name')!.value).toBe('我的修改')
 expect(fetcher.mock.calls.filter(([, init]) => init.method === 'PUT')).toHaveLength(1)
})
it('blocks writes when scoped cache is corrupted', async () => {
 sessionStorage.setItem('management-policy-editor:' + JSON.stringify(['admin', 'warehouse', 'a', 'monthly']), '{bad')
 await act(async () => root.render(<QueryClientProvider client={client}><PolicyEditor scope={scope} policyId="monthly" username="admin" csrf="csrf" /></QueryClientProvider>))
 await until(() => expect(document.body.textContent).toContain('口径缓存无法读取'))
 expect(button('保存口径草稿').disabled).toBe(true); expect(button('发布口径版本').disabled).toBe(true)
})
it('does not send a save if original request persistence fails', async () => {
 await mount(); await input('policy-name', '保留此修改')
 const setter = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('full') })
 try {
  await click('保存口径草稿'); expect(document.body.textContent).toContain('未提交')
  expect(fetcher.mock.calls.filter(([, init]) => init.method === 'PUT')).toHaveLength(0)
 } finally { setter.mockRestore() }
})
it('rechecks an uncommitted first save and requires another acknowledgement before retry', async () => {
 const { scopeId: _, revision: __, ...value } = definition
 sessionStorage.setItem('management-policy-editor:' + JSON.stringify(['admin', 'warehouse', 'a', 'monthly']), JSON.stringify({ value, baseline: null,
  pending: { action: 'save', expectedVersion: 0, definition: value, revision: null, contentHash: null, previewIssues: [] } }))
 const handler = fetcher.getMockImplementation()!
 fetcher.mockImplementation(async (path: string, init: RequestInit) => path.includes('/statistical-policies/')
  ? new Response(JSON.stringify({ code: 'management_policy_not_found' }), { status: 404 }) : handler(path, init))
 await act(async () => root.render(<QueryClientProvider client={client}><PolicyEditor scope={scope} policyId="monthly" username="admin" csrf="csrf" /></QueryClientProvider>))
 await click('读取原口径提交结果'); await until(() => expect(document.body.textContent).toContain('原口径请求尚未登记'))
 expect(button('确认重提原口径请求').disabled).toBe(true)
 await act(async () => document.querySelector<HTMLInputElement>('[aria-label="确认口径发布"]')!.click())
 expect(button('确认重提原口径请求').disabled).toBe(false)
 expect(fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true)
})
it('rejects a background collection as policy rule evidence', async () => {
 const handler = fetcher.getMockImplementation()!
 fetcher.mockImplementation(async (path: string, init: RequestInit) => path.includes('/business-evidence-releases/')
  ? response({ releaseId: 'rules-1', kind: 'background', documents: [] }) : handler(path, init))
 await mount(); await until(() => expect(document.body.textContent).toContain('不能使用背景集合'))
 expect(button('发布口径版本').disabled).toBe(true)
})
it('compares local and server fields then prepares a new CAS draft without writing automatically', async()=>{
 const handler=fetcher.getMockImplementation()!
 let first=true
 fetcher.mockImplementation(async(path:string,init:RequestInit)=>{
  if(init.method==='PUT'&&first){first=false;draft={...draft,version:4,contentHash:'server-4',document:{...draft.document,name:'另一管理员名称',decisionNotes:'服务器补充说明'}};return new Response(JSON.stringify({message:'版本冲突'}),{status:409})}
  return handler(path,init)
 })
 await mount();await input('policy-name','我的名称');await click('保存口径草稿');await click('读取原口径提交结果')
 await until(()=>expect(document.querySelector('[aria-label="口径冲突逐项对照"]')).toBeTruthy())
 expect(document.body.textContent).toContain('另一管理员名称');expect(document.body.textContent).toContain('服务器补充说明')
 expect(button('采用核对结果继续编辑').disabled).toBe(true)
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="口径名称：保留本地"]')!.click())
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="口径决策说明：采用服务器"]')!.click())
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="确认口径冲突选择"]')!.click())
 await click('采用核对结果继续编辑')
 await until(()=>expect(document.body.textContent).toContain('已按服务器草稿版本 4 准备本地修改'))
 expect(document.querySelector<HTMLInputElement>('#policy-name')!.value).toBe('我的名称')
 expect(document.querySelector<HTMLTextAreaElement>('#policy-notes')!.value).toBe('服务器补充说明')
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='PUT')).toHaveLength(1)
 const archiveKey=Object.keys(sessionStorage).find(k=>k.startsWith('management-policy-conflict:'))!
 expect(JSON.parse(sessionStorage.getItem(archiveKey)!)).toMatchObject({pending:{expectedVersion:3,definition:{name:'我的名称'}}})
 await click('保存口径草稿');await until(()=>expect(document.body.textContent).toContain('口径草稿已保存'))
 const last=fetcher.mock.calls.filter(([,o])=>o.method==='PUT').at(-1)!
 expect(JSON.parse(last[1].body)).toMatchObject({expectedVersion:4,definition:{name:'我的名称',decisionNotes:'服务器补充说明'}})
})
it('retains original pending request and resets choices when server advances again during conflict adoption',async()=>{
 const handler=fetcher.getMockImplementation()!
 fetcher.mockImplementation(async(path:string,init:RequestInit)=>{
  if(init.method==='PUT'){draft={...draft,version:4,contentHash:'server-4',document:{...draft.document,name:'服务器名称'}};return new Response('{}',{status:409})}return handler(path,init)
 })
 await mount();await input('policy-name','我的修改');await click('保存口径草稿');await click('读取原口径提交结果')
 await until(()=>expect(document.querySelector('[aria-label="口径名称：保留本地"]')).toBeTruthy())
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="口径名称：保留本地"]')!.click())
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="确认口径冲突选择"]')!.click())
 draft={...draft,version:5,contentHash:'server-5',document:{...draft.document,name:'再次修改的名称'}}
 await click('采用核对结果继续编辑');await until(()=>expect(document.body.textContent).toContain('服务器草稿再次变化'))
 expect(button('采用核对结果继续编辑').disabled).toBe(true)
 expect(document.querySelector<HTMLInputElement>('#policy-name')!.value).toBe('我的修改')
 expect(JSON.parse(sessionStorage.getItem('management-policy-editor:'+JSON.stringify(['admin','warehouse','a','monthly']))!).pending.expectedVersion).toBe(3)
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='PUT')).toHaveLength(1)
})
it('keeps the original request when the conflict archive cannot be persisted',async()=>{
 const handler=fetcher.getMockImplementation()!
 fetcher.mockImplementation(async(path:string,init:RequestInit)=>{
  if(init.method==='PUT'){draft={...draft,version:4,contentHash:'server-4',document:{...draft.document,name:'服务器名称'}};return new Response('{}',{status:409})}return handler(path,init)
 })
 await mount();await input('policy-name','我的修改');await click('保存口径草稿');await click('读取原口径提交结果')
 await until(()=>expect(document.querySelector('[aria-label="口径名称：保留本地"]')).toBeTruthy())
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="口径名称：保留本地"]')!.click())
 await act(async()=>document.querySelector<HTMLInputElement>('[aria-label="确认口径冲突选择"]')!.click())
 const setter=vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('full')})
 try{await click('采用核对结果继续编辑');await until(()=>expect(document.body.textContent).toContain('无法保存核对记录'))}
 finally{setter.mockRestore()}
 expect(document.querySelector<HTMLInputElement>('#policy-name')!.value).toBe('我的修改')
 expect(JSON.parse(sessionStorage.getItem('management-policy-editor:'+JSON.stringify(['admin','warehouse','a','monthly']))!).pending.expectedVersion).toBe(3)
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='PUT')).toHaveLength(1)
})
it('does not offer conflict adoption for a returned draft with another policy identity',async()=>{
 const handler=fetcher.getMockImplementation()!
 fetcher.mockImplementation(async(path:string,init:RequestInit)=>{
  if(init.method==='PUT'){draft={...draft,version:4,document:{...draft.document,id:'foreign-policy'}};return new Response('{}',{status:409})}return handler(path,init)
 })
 await mount();await input('policy-name','我的修改');await click('保存口径草稿');await click('读取原口径提交结果')
 await until(()=>expect(document.body.textContent).toContain('原口径提交结果仍无法确认'))
 expect(document.querySelector('[aria-label="口径冲突逐项对照"]')).toBeNull()
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='PUT')).toHaveLength(1)
})
it('shows saved policy changes with old and target values across calculation evidence and explanation',async()=>{
 published={revision:1,contentHash:'old-policy',document:{...definition,revision:1,name:'旧发布口径',scenario:'prior_scenario',validFrom:'2025-01-01',validTo:null,
  metricVersions:[{metricId:'budget',revision:2}],evidenceReleaseId:'old-rules',decisionNotes:'旧版说明',filters:[],joins:[],
  readinessPolicy:{...definition.readinessPolicy,watermarkField:'warehouse.test.budget.old_updated',maximumDelaySeconds:7200}}}
 await mount();await click('核对发布变更')
 await until(()=>expect(document.querySelector('[aria-label="口径发布逐项差异"]')).toBeTruthy())
 const area=document.querySelector('[aria-label="口径发布逐项差异"]')!
 for(const text of ['旧发布口径','月度预算口径','prior_scenario','budget_execution','2025-01-01','2026-01-01','无结束日期','2027-01-01','budget / 2','budget / 1','old-rules','rules-1','旧版说明','原始决策说明','文本「A」','多对一','7200','3600','warehouse.test.budget.old_updated','计算与适用范围','制度依据','说明与命名'])expect(area.textContent).toContain(text)
 await input('policy-name','未保存的新名称')
 expect(document.body.textContent).not.toContain('旧发布口径')
 expect(button('发布口径版本').disabled).toBe(true)
})
it('shows every saved field on first policy publication with an explicit empty current version',async()=>{
 published=null;await mount();await click('核对发布变更')
 await until(()=>expect(document.querySelector('[aria-label="口径发布逐项差异"]')).toBeTruthy())
 const area=document.querySelector('[aria-label="口径发布逐项差异"]')!
 expect(area.textContent).toContain('首次发布')
 for(const text of ['口径名称','报告场景','生效开始','生效结束','精确指标版本','制度依据集合','口径决策说明','筛选条件','表关联','数据充分性规则'])expect(area.textContent).toContain(text)
})
it('does not preview a stale saved policy after the server draft changes',async()=>{
 await mount();draft={...draft,version:4,contentHash:'new-draft',document:{...draft.document,name:'别人更新的口径'}}
 await click('核对发布变更');await until(()=>expect(document.body.textContent).toContain('服务器草稿已变化'))
 expect(fetcher.mock.calls.filter(([path])=>path.endsWith('/preview'))).toHaveLength(0)
 expect(button('发布口径版本').disabled).toBe(true)
 expect(document.querySelector<HTMLInputElement>('#policy-name')!.value).toBe('月度预算口径')
})
it('refreshes the current published version before displaying the saved release comparison',async()=>{
 await mount()
 published={revision:2,contentHash:draft.contentHash,document:{...draft.document}}
 await click('核对发布变更');await until(()=>expect(document.querySelector('[aria-label="口径发布逐项差异"]')).toBeTruthy())
 const area=document.querySelector('[aria-label="口径发布逐项差异"]')!
 expect(area.textContent).toContain('当前发布：版本 2；目标发布：版本 2')
 expect(area.textContent).toContain('0 项定义变化')
 expect(area.textContent).not.toContain('旧口径')
 expect(button('发布口径版本').disabled).toBe(true)
})
