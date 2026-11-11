import { webcrypto } from 'node:crypto'
import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { EvidenceReleaseManager } from './evidence-release'
let root:Root, client:QueryClient
const fetcher=vi.fn(), scope={database:'warehouse',companyId:'a'}
const metadata={id:'rules',title:'预算制度',kind:'rule_evidence',validFrom:null,validTo:null,eventTime:null,appliesTo:[]}
const revision={revision:1,originalHash:'a'.repeat(64),metadata,reviewStatus:'approved',ingestionStatus:'parsed'}
const reply=(v:unknown,status=200)=>new Response(JSON.stringify(v),{status})
let publishBody:any
beforeEach(()=>{
 Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});sessionStorage.clear();vi.stubGlobal('crypto',webcrypto)
 vi.stubGlobal('matchMedia',()=>({matches:false,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){}}))
 vi.stubGlobal('ResizeObserver',class{observe(){}unobserve(){}disconnect(){}});vi.stubGlobal('fetch',fetcher)
 publishBody=null
 fetcher.mockImplementation(async(path:string,o:any)=>{
  if(o.method==='POST'){publishBody=JSON.parse(o.body);return reply({releaseId:'release-one',requestId:publishBody.requestId,kind:'rule_evidence',documents:[{reference:{documentId:'rules',revision:1},metadata}]},201)}
  if(path.includes('/business-documents/rules'))return reply({documentId:'rules',revisions:[{...revision,revision:2,reviewStatus:'pending'},revision]})
  if(path.includes('/business-documents?'))return reply({items:[{documentId:'rules',title:'预算制度',revision:1,kind:'rule_evidence',reviewStatus:'approved',ingestionStatus:'parsed'}],nextCursor:null})
  return reply({items:[],nextCursor:null})
 })
 client=new QueryClient({defaultOptions:{queries:{retry:false}}});document.body.innerHTML='<div id="root"></div>';root=createRoot(document.getElementById('root')!)
})
afterEach(async()=>{await act(async()=>root.unmount());client.clear();vi.restoreAllMocks();vi.unstubAllGlobals();fetcher.mockReset()})
async function until(check:()=>void){for(let i=0;i<75;i++){await act(async()=>{await new Promise(r=>setTimeout(r,15))});try{check();return}catch{}}check()}
const button=(name:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.replaceAll(' ','')===name)!
async function click(name:string){await act(async()=>button(name).click())}
async function mount(){await act(async()=>root.render(<QueryClientProvider client={client}><EvidenceReleaseManager scope={scope} username="admin" csrf="csrf"/></QueryClientProvider>))}
async function choose(){await click('选择集合原件');await until(()=>expect(button('读取修订rules')).toBeTruthy());await click('读取修订rules');await until(()=>expect(button('加入rules修订1')).toBeTruthy());await click('加入rules修订1')}
async function confirm(){await act(async()=>document.querySelector<HTMLInputElement>('input[type=checkbox]')!.click())}
it('requires explicit exact revision selection and acknowledgement, excludes unapproved newer revisions',async()=>{
 await mount();await choose();expect(button('加入rules修订2').disabled).toBe(true)
 expect(button('发布证据集合').disabled).toBe(true);await confirm();await click('发布证据集合')
 await until(()=>expect(document.body.textContent).toContain('集合已发布'))
 expect(publishBody).toMatchObject({scopeDatabase:'warehouse',companyId:'a',kind:'rule_evidence',revisionIds:[{documentId:'rules',revision:1}]})
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(1)
 expect(document.body.textContent).toContain('不会自动调整口径、默认或历史报告')
})
it('restores an unknown publication by original request without reposting after remount',async()=>{
 const handler=fetcher.getMockImplementation()!
 fetcher.mockImplementation(async(path:string,o:any)=>{if(o.method==='POST'){publishBody=JSON.parse(o.body);throw Error('lost')}return handler(path,o)})
 await mount();await choose();await confirm();await click('发布证据集合');await until(()=>expect(document.body.textContent).toContain('集合发布结果待确认'))
 await act(async()=>root.unmount());client.clear();root=createRoot(document.getElementById('root')!)
 fetcher.mockImplementation(async(path:string,o:any)=>path.includes('requestId=')?reply({releaseId:'release-one',requestId:publishBody.requestId,kind:'rule_evidence',documents:[{reference:{documentId:'rules',revision:1},metadata}]}):handler(path,o))
 await mount();await click('读取原集合发布结果');await until(()=>expect(document.body.textContent).toContain('原请求集合已发布'))
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(1)
})
it('retains original selection when a member is revoked before publication',async()=>{
 await mount();await choose()
 const handler=fetcher.getMockImplementation()!
 fetcher.mockImplementation(async(path:string,o:any)=>path.includes('/business-documents/rules')?reply({documentId:'rules',revisions:[{...revision,reviewStatus:'revoked'}]}):handler(path,o))
 await confirm();await click('发布证据集合');await until(()=>expect(document.body.textContent).toContain('所选原件修订已不可发布'))
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(0)
 expect(document.body.textContent).toContain('预算制度')
})
it('blocks writes when the publication request cannot be cached',async()=>{
 await mount();await choose();vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('full')})
 await confirm();await click('发布证据集合');await until(()=>expect(document.body.textContent).toContain('无法保存原集合发布请求'))
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(0)
})
it('does not accept a recovery release with wrong purpose or member revision',async()=>{
 const handler=fetcher.getMockImplementation()!
 fetcher.mockImplementation(async(path:string,o:any)=>{if(o.method==='POST'){publishBody=JSON.parse(o.body);throw Error('lost')}return handler(path,o)})
 await mount();await choose();await confirm();await click('发布证据集合');await until(()=>expect(document.body.textContent).toContain('集合发布结果待确认'))
 fetcher.mockImplementation(async(path:string,o:any)=>path.includes('requestId=')?reply({releaseId:'wrong',requestId:publishBody.requestId,kind:'background',documents:[{reference:{documentId:'rules',revision:2},metadata}]}):handler(path,o))
 await click('读取原集合发布结果');await until(()=>expect(document.body.textContent).toContain('集合身份或用途与原请求不一致'))
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(1)
})
it('publishes a background collection only from explicitly selected background revisions',async()=>{
 const meta={...metadata,kind:'background'}
 fetcher.mockImplementation(async(path:string,o:any)=>{
  if(o.method==='POST'){publishBody=JSON.parse(o.body);return reply({releaseId:'background-one',requestId:publishBody.requestId,kind:'background',documents:[{reference:{documentId:'rules',revision:1},metadata:meta}]},201)}
  if(path.includes('/business-documents/rules'))return reply({documentId:'rules',revisions:[{...revision,metadata:meta}]})
  if(path.includes('/business-documents?'))return reply({items:[{documentId:'rules',title:'背景资料',revision:1,kind:'background',reviewStatus:'approved',ingestionStatus:'parsed'}],nextCursor:null})
  return reply({items:[],nextCursor:null})
 })
 await mount()
 await act(async()=>{document.querySelector('[aria-label="集合用途"]')!.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}))})
 await until(()=>expect(document.querySelector('[title="背景材料"]')).toBeTruthy())
 await act(async()=>document.querySelector<HTMLElement>('[title="背景材料"]')!.click())
 await choose();await confirm();await click('发布证据集合');await until(()=>expect(document.body.textContent).toContain('集合已发布'))
 expect(publishBody.kind).toBe('background')
})
it('allows only an explicitly reconfirmed original request after a missing release is read back',async()=>{
 const handler=fetcher.getMockImplementation()!
 fetcher.mockImplementation(async(path:string,o:any)=>{if(o.method==='POST'){publishBody=JSON.parse(o.body);throw Error('lost')}return handler(path,o)})
 await mount();await choose();await confirm();await click('发布证据集合');await until(()=>expect(document.body.textContent).toContain('集合发布结果待确认'))
 const originalRequest=publishBody.requestId
 fetcher.mockImplementation(async(path:string,o:any)=>path.includes('requestId=')?reply({code:'management_evidence_not_found',message:'未发布'},404):handler(path,o))
 await click('读取原集合发布结果');await until(()=>expect(document.body.textContent).toContain('尚未找到原请求集合'))
 expect(button('发布证据集合').disabled).toBe(true);await confirm();await click('发布证据集合')
 await until(()=>expect(document.body.textContent).toContain('集合已发布'));expect(publishBody.requestId).toBe(originalRequest)
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(2)
})

it.each(['duplicate', 'purpose', 'identity'])('rejects inconsistent cached publication members: %s',async(problem)=>{
 const member={documentId:'rules',revision:1,originalHash:'a'.repeat(64),metadata}
 const documents=problem==='duplicate'?[member,member]:[{...member,metadata:{...metadata,...(problem==='purpose'?{kind:'background'}:{id:'another'})}}]
 sessionStorage.setItem('management-evidence-publication:'+JSON.stringify(['admin','warehouse','a']),JSON.stringify({requestId:'original',kind:'rule_evidence',documents}))
 await mount();expect(document.body.textContent).toContain('原集合发布缓存损坏')
 expect(button('发布证据集合').disabled).toBe(true)
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(0)
})
