import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { PolicyDefaultBinding } from './default-binding'

const scope = { database: 'warehouse', companyId: 'a' }
const fetcher = vi.fn()
let root: Root, client: QueryClient
let current: { version: number; policyVersion: { policyId: string; revision: number }; backgroundReleaseId: string | null; issues: unknown[] }
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
beforeEach(() => {
  current = { version: 3, policyVersion: { policyId: 'monthly', revision: 1 }, backgroundReleaseId: 'background-kept', issues: [] }
  sessionStorage.clear(); Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('fetch', fetcher)
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.includes('/statistical-policies/')) return response({ published: { revision: 2, contentHash: 'target-hash', document: { name: '月报新规则', scenario: 'budget_execution' } }, retirement: null })
    if (path.includes('/business-evidence-releases/catalog?')) return response({ items: [{ releaseId: 'background-kept', kind: 'background', availableForSelection: true }] })
    if (init?.method === 'PUT') {
      const body = JSON.parse(String(init.body))
      current = { ...current, version: body.expectedVersion + 1, policyVersion: body.policyVersion, backgroundReleaseId: body.backgroundReleaseId }
      return response(current)
    }
    return response(current)
  })
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); vi.unstubAllGlobals(); fetcher.mockReset() })
async function until(check: () => void) {
  for (let i = 0; i < 70; i++) { await act(async () => { await new Promise(resolve => setTimeout(resolve, 15)) }); try { check(); return } catch {} }
  check()
}
const button = (name: string) => [...document.querySelectorAll('button')].find(item => item.textContent?.replaceAll(' ', '').includes(name))!
async function click(name: string) { await act(async () => button(name).click()) }
async function ack() { await act(async () => document.querySelector<HTMLInputElement>('[aria-label="确认调整场景默认"]')!.click()) }
async function mount() {
  await act(async () => root.render(<QueryClientProvider client={client}><PolicyDefaultBinding scope={scope} policyId="monthly" revision={2} username="admin" csrf="csrf" /></QueryClientProvider>))
  await until(() => expect(document.body.textContent).toContain('当前默认：'))
}
it('requires explicit confirmation and preserves the background with the exact default CAS version', async () => {
  await mount(); expect(button('确认调整默认').disabled).toBe(true)
  await ack(); await click('确认调整默认')
  await until(() => expect(document.body.textContent).toContain('默认配置已更新'))
  const puts = fetcher.mock.calls.filter(([, init]) => init?.method === 'PUT')
  expect(puts).toHaveLength(1)
  expect(JSON.parse(String(puts[0][1].body))).toEqual({ scopeDatabase: 'warehouse', companyId: 'a', expectedVersion: 3,
    policyVersion: { policyId: 'monthly', revision: 2 }, backgroundReleaseId: 'background-kept' })
  expect(document.body.textContent).toContain('仅影响新报告')
})
it('reads an unknown committed result after remount and does not repeat the PUT', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => { const reply = await handler(path, init); if (init?.method === 'PUT') throw Error('lost'); return reply })
  await mount(); await ack(); await click('确认调整默认')
  await until(() => expect(document.body.textContent).toContain('默认调整结果待确认'))
  await act(async () => root.unmount()); root = createRoot(document.getElementById('root')!); await mount()
  await click('读取原默认调整结果')
  await until(() => expect(document.body.textContent).toContain('当前默认与原目标一致'))
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1)
})
it('preserves a conflicting request and requires explicit recheck against the latest version', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.includes('/business-evidence-releases/catalog?')) return response({ items: [{ releaseId: 'background-kept', kind: 'background', availableForSelection: true }] })
    if (init?.method === 'PUT') { current = { ...current, version: 4, policyVersion: { policyId: 'other', revision: 1 } }; return response({ code: 'management_version_conflict', message: 'changed' }, 409) }
    return handler(path, init)
  })
  await mount(); await ack(); await click('确认调整默认'); await click('读取原默认调整结果')
  await until(() => expect(document.body.textContent).toContain('默认配置已变化'))
  expect(button('确认调整默认').disabled).toBe(true)
  expect(sessionStorage.length).toBe(1)
  await click('保留原请求并重新核对')
  expect(button('确认调整默认').disabled).toBe(true)
  expect(sessionStorage.length).toBe(1)
  fetcher.mockImplementation(handler); await ack(); await click('确认调整默认')
  await until(() => expect(document.body.textContent).toContain('默认配置已更新'))
  const bodies = fetcher.mock.calls.filter(([, init]) => init?.method === 'PUT').map(([, init]) => JSON.parse(String(init.body)))
  expect(bodies.map(item => item.expectedVersion)).toEqual([3, 4])
})
it('does not submit when request storage fails', async () => {
  await mount(); await ack()
  const setter = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('disabled') })
  await click('确认调整默认')
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(0)
  expect(document.body.textContent).toContain('无法保存默认调整请求'); setter.mockRestore()
})
it('allows only an explicit identical retry after verifying the original default is unchanged', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => { if (init?.method === 'PUT') throw Error('not committed'); return handler(path, init) })
  await mount(); await ack(); await click('确认调整默认'); await click('读取原默认调整结果')
  await until(() => expect(document.body.textContent).toContain('默认仍与提交前一致'))
  expect(button('确认重提原默认调整').disabled).toBe(true)
  fetcher.mockImplementation(handler); await ack(); await click('确认重提原默认调整')
  await until(() => expect(document.body.textContent).toContain('默认配置已更新'))
  const bodies = fetcher.mock.calls.filter(([, init]) => init?.method === 'PUT').map(([, init]) => init.body)
  expect(bodies).toHaveLength(2); expect(bodies[0]).toBe(bodies[1])
})

it('blocks selecting a retired target even if the current default needs repair', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => path.includes('/statistical-policies/')
    ? response({ published: { revision: 2, contentHash: 'target-hash', document: { name: '月报新规则', scenario: 'budget_execution' } }, retirement: { reason: '已退役' } }) : handler(path, init))
  await mount(); expect(document.body.textContent).toContain('当前选中版本已退役')
  expect(button('确认调整默认').disabled).toBe(true)
})

it('does not hide current semantic warnings after a successful binding update', async () => {
  current.issues = [{ code: 'ratio_unit_mismatch', impact: 'unavailable', message: '原单位尚待业务核对' }]
  await mount(); await ack(); await click('确认调整默认')
  await until(() => expect(document.body.textContent).toContain('默认配置已更新'))
  await until(() => expect(document.body.textContent).toContain('原单位尚待业务核对'))
})

it('retains a malformed pending cache and blocks new writes', async () => {
  const key = 'management-policy-default:' + JSON.stringify(['admin', 'warehouse', 'a', 'budget_execution'])
  sessionStorage.setItem(key, '{broken')
  await mount(); expect(document.body.textContent).toContain('默认调整请求缓存无法读取')
  expect(button('确认调整默认').disabled).toBe(true); expect(sessionStorage.getItem(key)).toBe('{broken')
})

function backgroundResponses(){
 const handler=fetcher.getMockImplementation()!
 fetcher.mockImplementation(async(path:string,init?:RequestInit)=>{
  if(path.includes('/business-evidence-releases/catalog?'))return response({items:[{releaseId:'background-new',kind:'background',publishedAt:'2026-11-11T00:00:00Z',availableForSelection:true,documents:[{documentId:'context',revision:1,title:'本期项目背景',reviewStatus:'approved',ingestionStatus:'ready'}]}],nextCursor:null})
  if(path.includes('/business-evidence-releases/background-new?'))return response({releaseId:'background-new',kind:'background',documents:[{reference:{documentId:'context',revision:1},metadata:{title:'本期项目背景'}}]})
  return handler(path,init)
 })
}
async function chooseBackground(){
 await click('从已发布背景材料中选择');await until(()=>expect(button('选择集合background-new')).toBeTruthy())
 await click('选择集合background-new');await until(()=>expect(document.body.textContent).toContain('本次背景：background-new'))
}
it('changes only the background with the same policy revision and exact default CAS',async()=>{
 current.policyVersion={policyId:'monthly',revision:2};backgroundResponses();await mount();await ack()
 expect(button('确认调整默认').disabled).toBe(true)
 await chooseBackground();expect(button('确认调整默认').disabled).toBe(true)
 await ack();await click('确认调整默认');await until(()=>expect(document.body.textContent).toContain('默认配置已更新'))
 const writes=fetcher.mock.calls.filter(([,i])=>i?.method==='PUT')
 expect(writes).toHaveLength(1);expect(JSON.parse(String(writes[0][1].body))).toMatchObject({expectedVersion:3,policyVersion:{policyId:'monthly',revision:2},backgroundReleaseId:'background-new'})
 expect(fetcher.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(0)
})
it('explicitly removes background without publishing a new formula version',async()=>{
 current.policyVersion={policyId:'monthly',revision:2};await mount();await click('本次不使用背景材料');await ack();await click('确认调整默认')
 await until(()=>expect(document.body.textContent).toContain('默认配置已更新'))
 expect(current.backgroundReleaseId).toBeNull();expect(current.policyVersion.revision).toBe(2)
 expect(fetcher.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(0)
})
it('recovers a committed background-only change after remount without another write',async()=>{
 current.policyVersion={policyId:'monthly',revision:2};backgroundResponses()
 const handler=fetcher.getMockImplementation()!
 fetcher.mockImplementation(async(p:string,i?:RequestInit)=>{const r=await handler(p,i);if(i?.method==='PUT')throw Error('lost');return r})
 await mount();await chooseBackground();await ack();await click('确认调整默认');await until(()=>expect(document.body.textContent).toContain('默认调整结果待确认'))
 await act(async()=>root.unmount());root=createRoot(document.getElementById('root')!);await mount();await click('读取原默认调整结果')
 await until(()=>expect(document.body.textContent).toContain('当前默认与原目标一致'))
 expect(current.backgroundReleaseId).toBe('background-new');expect(fetcher.mock.calls.filter(([,i])=>i?.method==='PUT')).toHaveLength(1)
})

it('retains an uncommitted background request and disables retry if the selected release is revoked',async()=>{
 current.policyVersion={policyId:'monthly',revision:2};backgroundResponses()
 const handler=fetcher.getMockImplementation()!
 let revoked=false
 fetcher.mockImplementation(async(p:string,i?:RequestInit)=>{
  if(i?.method==='PUT')throw Error('not committed')
  if(revoked&&p.includes('/business-evidence-releases/catalog?'))return response({items:[],nextCursor:null})
  return handler(p,i)
 })
 await mount();await chooseBackground();await ack();await click('确认调整默认');await until(()=>expect(document.body.textContent).toContain('默认调整结果待确认'))
 revoked=true;await click('读取原默认调整结果');await until(()=>expect(document.body.textContent).toContain('原背景集合已不可用'))
 expect(button('确认重提原默认调整')).toBeUndefined();expect(button('保留原请求并重新核对')).toBeTruthy()
 expect(sessionStorage.length).toBe(1);expect(fetcher.mock.calls.filter(([,i])=>i?.method==='PUT')).toHaveLength(1)
})
