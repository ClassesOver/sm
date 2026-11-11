import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { PolicyEvidencePicker } from './evidence-picker'
let root: Root, client: QueryClient
const fetcher = vi.fn(), changed = vi.fn(), scope = { database: 'warehouse', companyId: 'a' }
const response = (value: unknown) => new Response(JSON.stringify(value))
const entry = (releaseId: string, available = true) => ({ releaseId, kind: 'rule_evidence', publishedAt: '2026-11-11T00:00:00Z', availableForSelection: available,
 documents: [{ documentId: 'budget-rules', revision: 1, title: '预算管理制度', reviewStatus: available ? 'approved' : 'revoked', ingestionStatus: 'ready' }] })
beforeEach(() => {
 Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
 vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
 vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
 vi.stubGlobal('fetch', fetcher); fetcher.mockImplementation(async (path: string) => path.includes('/catalog?')
  ? response({ items: [entry(path.includes('after=') || path.includes('q=rules-2') ? 'rules-2' : 'rules-1')], nextCursor: path.includes('after=') ? null : 'rules-1' })
  : response({ releaseId: 'rules-2', kind: 'rule_evidence', documents: [{ reference: { documentId: 'budget-rules', revision: 1 }, metadata: { title: '预算管理制度' } }] }))
 client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); vi.unstubAllGlobals(); fetcher.mockReset(); changed.mockReset() })
async function until(check: () => void) { for (let i = 0; i < 60; i++) { await act(async () => { await new Promise(resolve => setTimeout(resolve, 15)) }); try { check(); return } catch {} } check() }
const button = (text: string) => [...document.querySelectorAll('button')].find(b => b.textContent?.replaceAll(' ', '') === text)!
async function click(text: string) { await act(async () => button(text).click()) }
async function mount() { await act(async () => root.render(<QueryClientProvider client={client}><PolicyEvidencePicker scope={scope} value="rules-old" disabled={false} onChange={changed} /></QueryClientProvider>)) }
it('loads only on opening, paginates scoped rule releases and never auto selects', async () => {
 await mount(); expect(fetcher).not.toHaveBeenCalled()
 await click('从已发布制度依据中选择'); await until(() => expect(document.body.textContent).toContain('rules-1'))
 await click('加载更多集合'); await until(() => expect(document.body.textContent).toContain('rules-2'))
 expect(changed).not.toHaveBeenCalled()
 expect(fetcher.mock.calls.every(([path]) => path.includes('kind=rule_evidence') && path.includes('companyId=a'))).toBe(true)
 await click('选择集合rules-2'); await until(() => expect(changed).toHaveBeenCalledWith('rules-2'))
 expect(document.body.textContent).toContain('预算管理制度')
 expect(document.body.textContent).toContain('修订 1')
})
it('does not allow selecting a collection whose member was revoked', async () => {
 fetcher.mockImplementation(async () => response({ items: [entry('rules-1', false)], nextCursor: null }))
 await mount(); await click('从已发布制度依据中选择'); await until(() => expect(document.body.textContent).toContain('已撤销'))
 expect(button('选择集合rules-1').disabled).toBe(true); expect(changed).not.toHaveBeenCalled()
})
it('revalidates collection kind and exact identity before applying a selection', async () => {
 const handler = fetcher.getMockImplementation()!
 fetcher.mockImplementation(async (path: string) => path.includes('/catalog?') ? handler(path) : response({ releaseId: 'other', kind: 'background', documents: [] }))
 await mount(); await click('从已发布制度依据中选择'); await until(() => expect(document.body.textContent).toContain('rules-1'))
 await click('选择集合rules-1'); await until(() => expect(document.body.textContent).toContain('集合身份或用途与所选制度依据不一致'))
 expect(changed).not.toHaveBeenCalled()
})
it('retains original choice if a collection member is revoked after opening', async () => {
 const handler = fetcher.getMockImplementation()!
 fetcher.mockImplementation(async (path: string) => path.includes('q=rules-1') ? response({ items: [entry('rules-1', false)], nextCursor: null }) : handler(path))
 await mount(); await click('从已发布制度依据中选择'); await until(() => expect(document.body.textContent).toContain('rules-1'))
 await click('选择集合rules-1'); await until(() => expect(document.body.textContent).toContain('当前审核状态已不可用'))
 expect(changed).not.toHaveBeenCalled()
})

it('selects only explicitly requested background purpose without auto selecting',async()=>{
 fetcher.mockImplementation(async(path:string)=>path.includes('/catalog?')?response({items:[{...entry('context-1'),kind:'background'}],nextCursor:null}):response({releaseId:'context-1',kind:'background',documents:[{reference:{documentId:'budget-rules',revision:1},metadata:{title:'预算管理制度'}}]}))
 await act(async()=>root.render(<QueryClientProvider client={client}><PolicyEvidencePicker scope={scope} value="" kind="background" disabled={false} onChange={changed}/></QueryClientProvider>))
 expect(changed).not.toHaveBeenCalled();await click('从已发布背景材料中选择');await until(()=>expect(button('选择集合context-1')).toBeTruthy())
 await click('选择集合context-1');await until(()=>expect(changed).toHaveBeenCalledWith('context-1'))
 expect(fetcher.mock.calls.filter(([p])=>p.includes('/catalog?')).every(([p])=>p.includes('kind=background'))).toBe(true)
})

it('rejects a duplicate release member instead of accepting a missing distinct member',async()=>{
 const first={documentId:'budget-rules',revision:1,title:'预算管理制度',reviewStatus:'approved',ingestionStatus:'ready'}
 fetcher.mockImplementation(async(p:string)=>p.includes('/catalog?')?response({items:[{...entry('rules-1'),documents:[first,{...first,documentId:'second'}]}],nextCursor:null}):response({releaseId:'rules-1',kind:'rule_evidence',documents:[1,2].map(()=>({reference:{documentId:'budget-rules',revision:1},metadata:{title:'预算管理制度'}}))}))
 await mount();await click('从已发布制度依据中选择');await until(()=>expect(button('选择集合rules-1')).toBeTruthy())
 await click('选择集合rules-1');await until(()=>expect(document.body.textContent).toContain('集合身份或用途与所选制度依据不一致'))
 expect(changed).not.toHaveBeenCalled()
})
