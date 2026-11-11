import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { RevisionJobs } from './revision-jobs'
let root: Root, client: QueryClient
const fetcher=vi.fn(), opened=vi.fn(), scope={database:'warehouse',companyId:'a'}
const job={jobId:'one',documentId:'rules',revision:1,attempt:1,status:'failed',issueCodes:['document_parse_failed']}
const response=(body:unknown)=>new Response(JSON.stringify(body))
beforeEach(()=>{
 Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true})
 vi.stubGlobal('matchMedia',()=>({matches:false,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){}}))
 vi.stubGlobal('ResizeObserver',class{observe(){}unobserve(){}disconnect(){}});vi.stubGlobal('fetch',fetcher)
 fetcher.mockImplementation(async(path:string)=>response({items:[{...job,jobId:path.includes('after=')?'two':'one'}],nextCursor:path.includes('after=')?null:'one'}))
 client=new QueryClient({defaultOptions:{queries:{retry:false}}});document.body.innerHTML='<div id="root"></div>';root=createRoot(document.getElementById('root')!)
})
afterEach(async()=>{await act(async()=>root.unmount());client.clear();vi.unstubAllGlobals();fetcher.mockReset();opened.mockReset()})
async function until(check:()=>void){for(let i=0;i<60;i++){await act(async()=>{await new Promise(r=>setTimeout(r,15))});try{check();return}catch{}}check()}
const button=(name:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.replaceAll(' ','')===name)!
async function click(name:string){await act(async()=>button(name).click())}
async function mount(){await act(async()=>root.render(<QueryClientProvider client={client}><RevisionJobs scope={scope} documentId="rules" revision={1} onOpen={opened}/></QueryClientProvider>))}
it('reads only on explicit opening and preserves exact revision scope through paging',async()=>{
 await mount();expect(fetcher).not.toHaveBeenCalled();await click('查看此修订解析任务')
 await until(()=>expect(button('查看任务one')).toBeTruthy());await click('加载更多修订任务');await until(()=>expect(button('查看任务two')).toBeTruthy())
 await click('查看任务one');expect(opened).toHaveBeenCalledWith('one')
 expect(fetcher.mock.calls.every(([p,o])=>p.includes('/business-documents/rules/revisions/1/ingestion-jobs?')&&p.includes('companyId=a')&&o.method==='GET')).toBe(true)
})
it('rejects another revision returned by the task directory without opening it',async()=>{
 fetcher.mockImplementation(async()=>response({items:[{...job,revision:2}],nextCursor:null}))
 await mount();await click('查看此修订解析任务');await until(()=>expect(document.body.textContent).toContain('任务身份与所选原件修订不一致'))
 expect(button('查看任务one')).toBeUndefined();expect(opened).not.toHaveBeenCalled()
})
it('shows an empty directory without creating or retrying a task',async()=>{
 fetcher.mockImplementation(async()=>response({items:[],nextCursor:null}))
 await mount();await click('查看此修订解析任务');await until(()=>expect(document.body.textContent).toContain('该修订没有可读取的解析任务'))
 expect(fetcher.mock.calls.every(([,o])=>o.method==='GET')).toBe(true)
})
