import { transferableAbortController } from 'node:util'
import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ManagementApp } from '../../app'
let root: Root
const fetcher = vi.fn(), response = (body: unknown) => new Response(JSON.stringify(body))
const row = { documentId: 'rules', title: '预算制度', version: 2, revision: 2, kind: 'rule_evidence', recordedAt: '2026-11-11T00:00:00Z', reviewStatus: 'pending', ingestionStatus: 'parsed' }
beforeEach(()=>{
 Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});sessionStorage.clear()
 window.history.replaceState({},'', '/management/knowledge?database=warehouse&companyId=a&document=rules&revision=1')
 vi.stubGlobal('AbortController',class{constructor(){return transferableAbortController()}})
 vi.stubGlobal('matchMedia',()=>({matches:false,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){}}))
 vi.stubGlobal('ResizeObserver',class{observe(){}unobserve(){}disconnect(){}});vi.stubGlobal('fetch',fetcher)
 fetcher.mockImplementation(async(path:string)=>{
  if(path.endsWith('/me')) return response({username:'admin',csrfToken:'csrf'})
  if(path.includes('/scopes')) return response({items:[{id:'org',name:'组织A',database:'warehouse',companyId:'a'}],nextCursor:null})
  if(path.includes('/business-evidence-releases/catalog?'))return response({items:[],nextCursor:null})
  if(path.includes('/business-documents/rules'))return response({documentId:'rules',version:2,revisions:[2,1].map(revision=>({revision,stateVersion:3,originalHash:'hash-'+revision,metadata:{title:'预算制度修订'+revision,kind:'rule_evidence',validFrom:null,validTo:null,eventTime:null,appliesTo:[]},reviewStatus:'pending',ingestionStatus:'parsed',reviewReceipt:null,mediaType:'text/plain',sizeBytes:42,recordedAt:'2026-11-11T00:00:00Z'}))})
  return response({items:path.includes('after=')?[]:[row],nextCursor:path.includes('after=')?null:'rules'})
 })
 document.body.innerHTML='<div id="root"></div>';root=createRoot(document.getElementById('root')!)
})
afterEach(async()=>{await act(async()=>root.unmount());vi.unstubAllGlobals();fetcher.mockReset()})
async function until(check:()=>void){for(let i=0;i<90;i++){await act(async()=>{await new Promise(r=>setTimeout(r,20))});try{check();return}catch{}}check()}
it('opens an exact historical revision from URL and provides scoped paginated originals directory',async()=>{
 await act(async()=>root.render(<ManagementApp/>))
 await until(()=>expect(document.body.textContent).toContain('预算制度修订1'))
 expect(document.querySelector('h1')?.textContent).toBe('业务知识')
 expect(document.querySelector('section[aria-label="原件修订详情"]')?.textContent).toContain('修订 1')
 expect(document.querySelector('section[aria-label="原件修订详情"]')?.textContent).not.toContain('预算制度修订2')
 const more=[...document.querySelectorAll('button')].find(b=>b.textContent?.replaceAll(' ','')==='加载更多原件')!
 await act(async()=>more.click());await until(()=>expect(fetcher.mock.calls.some(([p])=>p.includes('after=rules'))).toBe(true))
 expect(fetcher.mock.calls.filter(([p])=>p.includes('/business-documents')).every(([p])=>p.includes('companyId=a'))).toBe(true)
 expect(fetcher.mock.calls.every(([,o])=>o.method==='GET')).toBe(true)
})
it('finds an exact revision task and opens its existing retry view without an upload receipt',async()=>{
 const handler=fetcher.getMockImplementation()!
 fetcher.mockImplementation(async(path:string,...rest:unknown[])=>{
  if(path.includes('/revisions/1/ingestion-jobs'))return response({items:[{jobId:'historical-job',documentId:'rules',revision:1,attempt:1,status:'failed',issueCodes:['document_parse_failed']}],nextCursor:null})
  if(path.includes('/business-ingestion-jobs/historical-job'))return response({jobId:'historical-job',documentId:'rules',revision:1,attempt:1,status:'failed',issueCodes:['document_parse_failed']})
  return handler(path,...rest)
 })
 await act(async()=>root.render(<ManagementApp/>))
 await until(()=>expect(document.body.textContent).toContain('预算制度修订1'))
 const button=(name:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.replaceAll(' ','')===name)!
 await act(async()=>button('查看此修订解析任务').click())
 await until(()=>expect(button('查看任务historical-job')).toBeTruthy())
 await act(async()=>button('查看任务historical-job').click())
 await until(()=>expect(document.querySelector('section[aria-label="解析失败重试"]')).toBeTruthy())
 expect(new URLSearchParams(location.search).get('job')).toBe('historical-job')
 expect(fetcher.mock.calls.every(([,o])=>o.method==='GET')).toBe(true)
})

it('clears the task identity when opening another original revision',async()=>{
 window.history.replaceState({},'', '/management/knowledge?database=warehouse&companyId=a&document=rules&revision=1&job=old-task')
 await act(async()=>root.render(<ManagementApp/>))
 await until(()=>expect(document.body.textContent).toContain('预算制度修订1'))
 await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='查看原件 rules')!.click())
 await until(()=>expect(new URLSearchParams(location.search).get('revision')).toBe('2'))
 expect(new URLSearchParams(location.search).has('job')).toBe(false)
})
