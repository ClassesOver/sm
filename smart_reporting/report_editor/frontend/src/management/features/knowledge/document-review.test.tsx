import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DocumentReview } from './document-review'
let root: Root, client: QueryClient
const fetcher = vi.fn(), scope = { database: 'warehouse', companyId: 'a' }
const revision = { revision: 1, stateVersion: 3, originalHash: 'hash-one', reviewStatus: 'pending', ingestionStatus: 'parsed', reviewReceipt: null }
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status })
beforeEach(() => {
 Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); sessionStorage.clear()
 vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
 vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }); vi.stubGlobal('fetch', fetcher)
 fetcher.mockImplementation(async (_path, options) => options.method === 'POST'
  ? response({ stateVersion: 4, reviewStatus: 'approved', ingestionStatus: 'parsed' })
  : response({ documentId: 'rules', revisions: [revision] }))
 client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); fetcher.mockReset() })
async function until(check: () => void) { for(let i=0;i<60;i++){ await act(async()=>{await new Promise(r=>setTimeout(r,15))});try{check();return}catch{} } check() }
async function mount(target = revision) { await act(async () => root.render(<QueryClientProvider client={client}><DocumentReview scope={scope} documentId="rules" target={target} username="admin" csrf="csrf" /></QueryClientProvider>)) }
const button = (text: string) => [...document.querySelectorAll('button')].find(b=>b.textContent?.replaceAll(' ','')===text)!
async function click(text: string) { await act(async()=>button(text).click()) }
async function fillReason() { await act(async()=>{const field=document.querySelector('textarea')!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,'核对合计比值原文');field.dispatchEvent(new Event('input',{bubbles:true}))}) }
async function confirm() { await act(async()=>document.querySelector<HTMLInputElement>('input[type=checkbox]')!.click()) }
it('requires reason and explicit acknowledgement and submits the exact CAS revision once', async()=>{
 await mount(); expect(button('提交原件审核').disabled).toBe(true)
 await fillReason(); await confirm(); await click('提交原件审核')
 await until(()=>expect(document.body.textContent).toContain('审核决定已登记'))
 const writes=fetcher.mock.calls.filter(([,o])=>o.method==='POST');expect(writes).toHaveLength(1)
 expect(writes[0][0]).toContain('/rules/revisions/1/review')
 expect(JSON.parse(writes[0][1].body)).toEqual({scopeDatabase:'warehouse',companyId:'a',expectedVersion:3,decision:'approved',reason:'核对合计比值原文'})
 expect(document.body.textContent).toContain('不会发布证据集合')
})
it('recovers an unknown review after remount using reads only and the original identity', async()=>{
 fetcher.mockRejectedValueOnce(Error('connection lost'))
 await mount();await fillReason();await confirm();await click('提交原件审核')
 await until(()=>expect(document.body.textContent).toContain('原件审核结果待确认'))
 await act(async()=>root.unmount());root=createRoot(document.getElementById('root')!)
 fetcher.mockResolvedValue(response({documentId:'rules',revisions:[{...revision,stateVersion:4,reviewStatus:'approved',reviewReceipt:{decision:'approved',reason:'核对合计比值原文'}}]}))
 await mount();await click('读取原审核结果')
 await until(()=>expect(document.body.textContent).toContain('当前状态与原审核决定一致'))
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(1)
})
it('retains original reason and blocks overwriting a conflicting review', async()=>{
 fetcher.mockResolvedValueOnce(response({message:'状态冲突',code:'management_version_conflict'},409))
 await mount();await fillReason();await confirm();await click('提交原件审核')
 await until(()=>expect(document.body.textContent).toContain('原件审核结果待确认'))
 fetcher.mockResolvedValue(response({documentId:'rules',revisions:[{...revision,stateVersion:4,reviewStatus:'rejected',reviewReceipt:{decision:'rejected',reason:'另一位审核意见'}}]}))
 await click('读取原审核结果');await until(()=>expect(document.body.textContent).toContain('当前状态与原审核请求不一致'))
 expect(document.body.textContent).toContain('核对合计比值原文');expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(1)
})
it('does not write when the original request cannot be persisted', async()=>{
 vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('full')})
 await mount();await fillReason();await confirm();await click('提交原件审核')
 await until(()=>expect(document.body.textContent).toContain('无法保存原审核请求'))
 expect(fetcher).not.toHaveBeenCalled()
})
it('does not offer reapproval for an already revoked revision', async()=>{
 await mount({...revision,reviewStatus:'revoked'})
 expect(document.body.textContent).toContain('已撤销修订不可重新启用')
 expect(button('提交原件审核')).toBeUndefined()
})
it('rejects a stored request whose document identity does not match this revision', async()=>{
 sessionStorage.setItem('management-document-review:'+JSON.stringify(['admin',scope,'rules',1]),JSON.stringify({documentId:'other',revision:1,originalHash:'hash-one',expectedVersion:3,decision:'approved',reason:'另一原件审核'}))
 await mount();await until(()=>expect(document.body.textContent).toContain('原审核缓存损坏'))
 expect(button('提交原件审核').disabled).toBe(true);expect(fetcher).not.toHaveBeenCalled()
})
it('requires a fresh acknowledgement before explicitly resubmitting an unchanged request', async()=>{
 fetcher.mockRejectedValueOnce(Error('connection lost'))
 await mount();await fillReason();await confirm();await click('提交原件审核')
 await until(()=>expect(document.body.textContent).toContain('原件审核结果待确认'))
 fetcher.mockResolvedValueOnce(response({documentId:'rules',revisions:[revision]}))
 await click('读取原审核结果');await until(()=>expect(document.body.textContent).toContain('当前状态版本未变'))
 expect(button('提交原件审核').disabled).toBe(true)
 await confirm();await click('提交原件审核');await until(()=>expect(document.body.textContent).toContain('审核决定已登记'))
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(2)
})

it('shows revocation impact and permits explicit revocation when lookup fails',async()=>{
 fetcher.mockImplementation(async (_path,options)=>options.method==='POST'
  ? response({stateVersion:4,reviewStatus:'revoked',ingestionStatus:'parsed'}) : response({message:'影响查询暂不可用',code:'unavailable'},503))
 await mount()
 await act(async()=>document.querySelector('[aria-label="审核决定"]')!.dispatchEvent(new MouseEvent('mousedown',{bubbles:true})))
 await until(()=>expect(document.querySelector('.ant-select-item-option[title="撤销原件访问"]')).toBeTruthy())
 await act(async()=>document.querySelector<HTMLElement>('.ant-select-item-option[title="撤销原件访问"]')!.click())
 await until(()=>expect(button('核对撤销影响')).toBeTruthy());await click('核对撤销影响')
 await until(()=>expect(document.body.textContent).toContain('影响查询暂不可用'))
 expect(document.body.textContent).toContain('仍可明确提交撤销')
 await fillReason();await confirm();await click('提交原件审核')
 await until(()=>expect(document.body.textContent).toContain('审核决定已登记'))
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(1)
})
