import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { IngestionTask } from './ingestion-task'
let root:Root,client:QueryClient
const fetcher=vi.fn(),scope={database:'warehouse',companyId:'a'}
const failed={jobId:'job-one',documentId:'rules',revision:2,attempt:1,status:'failed',issueCodes:['document_parse_failed']}
const response=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status})
beforeEach(()=>{
 Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});sessionStorage.clear()
 vi.stubGlobal('matchMedia',()=>({matches:false,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){}}))
 vi.stubGlobal('ResizeObserver',class{observe(){}unobserve(){}disconnect(){}});vi.stubGlobal('fetch',fetcher)
 fetcher.mockImplementation(async(_p,o)=>response(o.method==='POST'?{...failed,status:'queued',issueCodes:[]}:failed))
 client=new QueryClient({defaultOptions:{queries:{retry:false}}});document.body.innerHTML='<div id="root"></div>';root=createRoot(document.getElementById('root')!)
})
afterEach(async()=>{await act(async()=>root.unmount());client.clear();vi.restoreAllMocks();vi.unstubAllGlobals();fetcher.mockReset()})
async function until(check:()=>void){for(let i=0;i<70;i++){await act(async()=>{await new Promise(r=>setTimeout(r,15))});try{check();return}catch{}}check()}
async function mount(){await act(async()=>root.render(<QueryClientProvider client={client}><IngestionTask scope={scope} jobId="job-one" documentId="rules" revision={2} username="admin" csrf="csrf"/></QueryClientProvider>));await until(()=>expect(document.body.textContent).toContain('解析失败'))}
const button=(name:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.replaceAll(' ','')===name)!
async function click(name:string){await act(async()=>button(name).click())}
async function confirm(){await act(async()=>document.querySelector<HTMLInputElement>('input[type=checkbox]')!.click())}
it('only reads initially and requires explicit acknowledgement before enqueueing the exact failed attempt',async()=>{
 await mount();expect(fetcher.mock.calls.every(([,o])=>o.method==='GET')).toBe(true)
 expect(button('重新排队解析').disabled).toBe(true);await confirm();await click('重新排队解析')
 await until(()=>expect(document.body.textContent).toContain('已请求重新排队'))
 const writes=fetcher.mock.calls.filter(([,o])=>o.method==='POST');expect(writes).toHaveLength(1)
 expect(writes[0][0]).toContain('/business-ingestion-jobs/job-one/retry')
 expect(JSON.parse(writes[0][1].body)).toEqual({scopeDatabase:'warehouse',companyId:'a',expectedAttempt:1})
})
it('recovers after remount by reading progressed task state without requeueing',async()=>{
 await mount();fetcher.mockRejectedValueOnce(Error('lost'));await confirm();await click('重新排队解析')
 await until(()=>expect(document.body.textContent).toContain('重试结果待确认'))
 await act(async()=>root.unmount());client.clear();root=createRoot(document.getElementById('root')!)
 fetcher.mockImplementation(async()=>response({...failed,status:'parsed',attempt:2,issueCodes:[]}))
 await act(async()=>root.render(<QueryClientProvider client={client}><IngestionTask scope={scope} jobId="job-one" documentId="rules" revision={2} username="admin" csrf="csrf"/></QueryClientProvider>))
 await click('读取原重试状态');await until(()=>expect(document.body.textContent).toContain('当前任务已推进'))
 expect(document.body.textContent).toContain('不能据此认定唯一重试请求')
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(1)
})
it('requires renewed acknowledgement before explicit retry when the failed attempt did not change',async()=>{
 await mount();fetcher.mockRejectedValueOnce(Error('lost'));await confirm();await click('重新排队解析')
 await until(()=>expect(document.body.textContent).toContain('重试结果待确认'));await click('读取原重试状态')
 await until(()=>expect(document.body.textContent).toContain('当前仍为原失败尝试'))
 expect(button('重新排队解析').disabled).toBe(true)
 await confirm();await click('重新排队解析');await until(()=>expect(document.body.textContent).toContain('已请求重新排队'))
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(2)
})
it('does not show retry controls for a different task identity',async()=>{
 fetcher.mockResolvedValue(response({...failed,documentId:'other'}))
 await act(async()=>root.render(<QueryClientProvider client={client}><IngestionTask scope={scope} jobId="job-one" documentId="rules" revision={2} username="admin" csrf="csrf"/></QueryClientProvider>))
 await until(()=>expect(document.body.textContent).toContain('任务身份与当前原件修订不一致'))
 expect(button('重新排队解析')).toBeUndefined()
})
it('does not retry transcription-required material automatically or offer it as a failed parse',async()=>{
 fetcher.mockResolvedValue(response({...failed,status:'needs_transcription',issueCodes:['pdf_requires_transcription']}))
 await act(async()=>root.render(<QueryClientProvider client={client}><IngestionTask scope={scope} jobId="job-one" documentId="rules" revision={2} username="admin" csrf="csrf"/></QueryClientProvider>))
 await until(()=>expect(document.body.textContent).toContain('需人工转录'))
 expect(button('重新排队解析')).toBeUndefined();expect(fetcher.mock.calls.every(([,o])=>o.method==='GET')).toBe(true)
})
it('blocks the write if the original retry request cannot be persisted',async()=>{
 await mount();vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('full')})
 await confirm();await click('重新排队解析');await until(()=>expect(document.body.textContent).toContain('无法保存原重试请求'))
 expect(fetcher.mock.calls.every(([,o])=>o.method==='GET')).toBe(true)
})
