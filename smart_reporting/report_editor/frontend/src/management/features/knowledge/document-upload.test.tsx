import { webcrypto } from 'node:crypto'
import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DocumentUpload } from './document-upload'
let root: Root, client: QueryClient
const fetcher=vi.fn(), uploaded=vi.fn(), scope={database:'warehouse',companyId:'a'}
const receipt={documentId:'rules',revision:1,version:1,jobId:'job-one',status:'queued',issueCodes:[]}
const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status})
beforeEach(()=>{
 Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});sessionStorage.clear();vi.stubGlobal('crypto',webcrypto)
 vi.stubGlobal('matchMedia',()=>({matches:false,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){}}))
 vi.stubGlobal('ResizeObserver',class{observe(){}unobserve(){}disconnect(){}});vi.stubGlobal('fetch',fetcher)
 fetcher.mockResolvedValue(response(receipt,201));client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 document.body.innerHTML='<div id="root"></div>';root=createRoot(document.getElementById('root')!)
})
afterEach(async()=>{await act(async()=>root.unmount());client.clear();vi.restoreAllMocks();vi.unstubAllGlobals();fetcher.mockReset();uploaded.mockReset()})
async function until(check:()=>void){for(let i=0;i<90;i++){await act(async()=>{await new Promise(r=>setTimeout(r,15))});try{check();return}catch{}}check()}
async function mount(){await act(async()=>root.render(<QueryClientProvider client={client}><DocumentUpload scope={scope} username="admin" csrf="csrf" onUploaded={uploaded}/></QueryClientProvider>))}
async function fill(label:string,value:string){await act(async()=>{const field=document.querySelector<HTMLInputElement>('input[aria-label="'+label+'"]')!;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}))})}
async function file(){const blob=new File(['合计比值'], 'rules.txt',{type:'text/plain'});Object.defineProperty(blob,'arrayBuffer',{value:async()=>new TextEncoder().encode('合计比值').buffer});await act(async()=>{const field=document.querySelector<HTMLInputElement>('input[type=file]')!;Object.defineProperty(field,'files',{configurable:true,value:[blob]});field.dispatchEvent(new Event('change',{bubbles:true}))})}
const button=(name:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.replaceAll(' ','')===name)!
async function click(name:string){await act(async()=>button(name).click())}
async function prepare(){await fill('原件标识','rules');await fill('原件标题','预算制度');await file();await act(async()=>document.querySelector<HTMLInputElement>('input[type=checkbox]')!.click())}
it('uploads multipart with cached original identity and explicit version zero, without approving or publishing',async()=>{
 await mount();await prepare();await click('登记原件修订');await until(()=>expect(uploaded).toHaveBeenCalledWith(receipt))
 const [path,options]=fetcher.mock.calls[0];expect(path).toContain('/business-documents');expect(options.body).toBeInstanceOf(FormData)
 expect(options.body.get('expectedVersion')).toBe('0');expect(options.body.get('companyId')).toBe('a')
 expect(JSON.parse(options.body.get('metadata'))).toMatchObject({id:'rules',title:'预算制度',kind:'rule_evidence'})
 expect(fetcher.mock.calls).toHaveLength(1);expect(document.body.textContent).toContain('尚未审核或发布')
})
it('recovers an uploaded request after loss and remount without retaining or resending file bytes',async()=>{
 fetcher.mockRejectedValueOnce(Error('lost'));await mount();await prepare();await click('登记原件修订')
 await until(()=>expect(document.body.textContent).toContain('上传登记结果待确认'))
 const cached=JSON.parse([...Array(sessionStorage.length)].map((_,i)=>sessionStorage.getItem(sessionStorage.key(i)!)).find(v=>v?.includes('originalHash'))!)
 expect(cached.filename).toBe('rules.txt');expect(cached.originalHash).toHaveLength(64)
 fetcher.mockResolvedValue(response({...cached,receipt}))
 await act(async()=>root.unmount());root=createRoot(document.getElementById('root')!);await mount();await click('读取原上传结果')
 await until(()=>expect(document.body.textContent).toContain('原上传请求已登记'))
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(1)
})
it('preserves pending upload on mismatched readback instead of accepting another file',async()=>{
 fetcher.mockRejectedValueOnce(Error('lost'));await mount();await prepare();await click('登记原件修订')
 await until(()=>expect(document.body.textContent).toContain('上传登记结果待确认'))
 fetcher.mockResolvedValue(response({requestId:'other',expectedVersion:0,filename:'rules.txt',originalHash:'f'.repeat(64),metadata:{id:'rules',title:'预算制度',kind:'rule_evidence',validFrom:null,validTo:null,eventTime:null,appliesTo:[]},receipt}))
 await click('读取原上传结果');await until(()=>expect(document.body.textContent).toContain('登记身份与原上传不一致'))
 expect(uploaded).not.toHaveBeenCalled();expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(1)
})
it('does not send file bytes when pending request storage fails',async()=>{
 vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('full')});await mount();await prepare();await click('登记原件修订')
 await until(()=>expect(document.body.textContent).toContain('无法保存原上传请求'));expect(fetcher).not.toHaveBeenCalled()
})
it('requires readback and unchanged current version before explicit same-file resubmission',async()=>{
 fetcher.mockRejectedValueOnce(Error('lost'));await mount();await prepare();await click('登记原件修订')
 await until(()=>expect(document.body.textContent).toContain('上传登记结果待确认'))
 fetcher.mockResolvedValueOnce(response({code:'management_registration_not_found',message:'尚未登记'},404))
 fetcher.mockResolvedValueOnce(response({code:'management_document_not_found',message:'无原件'},404))
 await click('读取原上传结果');await until(()=>expect(document.body.textContent).toContain('当前版本未变'))
 expect(button('登记原件修订').disabled).toBe(true)
 await file();await act(async()=>document.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());await click('登记原件修订')
 await until(()=>expect(uploaded).toHaveBeenCalledWith(receipt))
 const writes=fetcher.mock.calls.filter(([,o])=>o.method==='POST')
 expect(writes).toHaveLength(2);expect(writes[0][1].body.get('requestId')).toBe(writes[1][1].body.get('requestId'))
})
it('retains an unknown registration when another revision appeared rather than overwriting it',async()=>{
 fetcher.mockRejectedValueOnce(Error('lost'));await mount();await prepare();await click('登记原件修订')
 await until(()=>expect(document.body.textContent).toContain('上传登记结果待确认'))
 fetcher.mockResolvedValueOnce(response({code:'management_registration_not_found',message:'尚未登记'},404))
 fetcher.mockResolvedValueOnce(response({documentId:'rules',version:1}))
 await click('读取原上传结果');await until(()=>expect(document.body.textContent).toContain('原件已有其他修订'))
 expect(button('登记原件修订').disabled).toBe(true);expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(1)
})
