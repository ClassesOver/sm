import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DocumentImpact } from './document-impact'
let root: Root, client: QueryClient
const fetcher=vi.fn(), opened=vi.fn(), scope={database:'warehouse',companyId:'a'}
const item={kind:'report',referenceId:'run-one',revision:null,name:'run-one',basisId:'basis-one',policyVersion:{policyId:'policy-one',revision:1},evidenceKind:null}
const response=(body:unknown)=>new Response(JSON.stringify(body))
beforeEach(()=>{
 Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true})
 vi.stubGlobal('matchMedia',()=>({matches:false,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){}}))
 vi.stubGlobal('ResizeObserver',class{observe(){}unobserve(){}disconnect(){}});vi.stubGlobal('fetch',fetcher)
 fetcher.mockImplementation(async(path:string)=>response({documentRevision:{documentId:'rules',revision:1},items:[{...item,referenceId:path.includes('after=')?'run-two':'run-one'}],nextCursor:path.includes('after=')?null:'one'}))
 client=new QueryClient({defaultOptions:{queries:{retry:false}}});document.body.innerHTML='<div id="root"></div>';root=createRoot(document.getElementById('root')!)
})
afterEach(async()=>{await act(async()=>root.unmount());client.clear();vi.unstubAllGlobals();fetcher.mockReset();opened.mockReset()})
async function until(check:()=>void){for(let i=0;i<60;i++){await act(async()=>{await new Promise(r=>setTimeout(r,15))});try{check();return}catch{}}check()}
const button=(name:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.replaceAll(' ','')===name)!
async function click(name:string){await act(async()=>button(name).click())}
async function mount(){await act(async()=>root.render(<QueryClientProvider client={client}><DocumentImpact scope={scope} documentId="rules" revision={1}/></QueryClientProvider>))}
it('reads exact revision impact explicitly and keeps paged registered references',async()=>{
 await mount();expect(fetcher).not.toHaveBeenCalled();await click('核对撤销影响')
 await until(()=>expect(document.body.textContent).toContain('run-one'));await click('加载更多关联');await until(()=>expect(document.body.textContent).toContain('run-two'))
 expect(document.body.textContent).toContain('不代表报告实际引用了每份原件')
 expect(fetcher.mock.calls.every(([p,o])=>p.includes('/business-documents/rules/revisions/1/impact?')&&p.includes('companyId=a')&&o.method==='GET')).toBe(true)
})
it('rejects references returned for another original revision',async()=>{
 fetcher.mockImplementation(async()=>response({documentRevision:{documentId:'rules',revision:2},items:[item],nextCursor:null}))
 await mount();await click('核对撤销影响');await until(()=>expect(document.body.textContent).toContain('影响结果与所选原件修订不一致'))
 expect(document.body.textContent).not.toContain('run-one')
})
it('distinguishes empty registered references from unread impact and never writes',async()=>{
 fetcher.mockImplementation(async()=>response({documentRevision:{documentId:'rules',revision:1},items:[],nextCursor:null}))
 await mount();expect(document.body.textContent).not.toContain('未发现登记关联');await click('核对撤销影响')
 await until(()=>expect(document.body.textContent).toContain('未发现登记关联'))
 expect(fetcher.mock.calls.every(([,o])=>o.method==='GET')).toBe(true)
})
