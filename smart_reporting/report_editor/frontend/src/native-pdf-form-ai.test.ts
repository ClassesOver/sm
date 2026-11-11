import {afterEach,expect,it,vi} from 'vitest'
import {bindNativePDFFormAI,type PDFFormAIJob} from './native-pdf-form-ai'
import {NativeDraft} from './native-draft'
import type {PdfFormField} from './pdf-operations'
afterEach(()=>{document.body.replaceChildren();localStorage.clear()})
const base=[{kind:'rotatePage',pageId:'p',delta:90}]
const fill={kind:'setFormValue',fieldId:'income',name:'收入<img>',fieldKind:'text',expectedFieldSha256:'f'.repeat(64),value:'84'}
const result:PDFFormAIJob={editId:'forms',status:'succeeded',snapshotSha256:'b'.repeat(64),result:{answer:'填写建议',proposal:{summary:'收入更新',operations:[...base,fill],changes:[{fieldId:'income',name:'收入<img>',fieldKind:'text',before:'42',after:'84'}],previewDigest:'d'.repeat(64),appliedOperationIndices:[0,1],skippedOperations:[]}}}
function fixture(overrides:object={}){
 const root=document.body.appendChild(document.createElement('div'))
 const draft=new NativeDraft({documentId:'forms',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},localStorage);draft.setOperations(base)
 let fields:PdfFormField[]=[{fieldId:'income',name:'收入<img>',kind:'text',value:'42',editable:true,expectedFieldSha256:'f'.repeat(64)},{fieldId:'secret',name:'未授权',kind:'text',value:'秘密',editable:true,expectedFieldSha256:'s'.repeat(64)}]
 const api={pdfFormAIStart:vi.fn().mockResolvedValue(result),pdfFormAIStatus:vi.fn(),pdfFormAIAccept:vi.fn().mockResolvedValue({operations:[...base,fill],previewDigest:'d'.repeat(64)}),pdfFormAICancel:vi.fn().mockResolvedValue({}),...overrides}
 const refresh=vi.fn().mockResolvedValue(undefined),changed=vi.fn()
 const binding=bindNativePDFFormAI(root,{api:api as never,draft,fields:()=>fields,view:{refresh},canEdit:()=>true,onDraftChange:changed})
 const click=(id:string)=>root.querySelector<HTMLButtonElement>('[data-pdf-form-ai='+id+']')!.click()
 const select=()=>{const input=root.querySelector<HTMLInputElement>('[data-pdf-form-ai-field=income]')!;input.checked=true;input.dispatchEvent(new Event('change'))}
 const instruction=()=>{const input=root.querySelector('textarea')!;input.value='收入填写84';input.dispatchEvent(new Event('input'))}
 binding.open();return{root,draft,api,binding,click,select,instruction,refresh,changed,invalidate:()=>{fields=[]}}
}
it('默认全不选且只授权用户明确勾选字段，显示真实前后值并明确采纳完整合批',async()=>{
 const f=fixture();f.instruction();f.click('start');expect(f.api.pdfFormAIStart).not.toHaveBeenCalled()
 expect(f.root.querySelectorAll('input:checked')).toHaveLength(0);expect(f.root.querySelector('[data-pdf-form-ai=start] svg')).not.toBeNull()
 f.select();f.click('start');await vi.waitFor(()=>expect(f.root.textContent).toContain('收入<img>（text）：42 → 84'))
 expect(f.root.querySelector('img')).toBeNull();expect(f.draft.operations).toEqual(base)
 expect(f.api.pdfFormAIStart.mock.calls[0][0]).toMatchObject({operations:base,selection:[{fieldId:'income'}]})
 f.click('accept');await vi.waitFor(()=>expect(f.refresh).toHaveBeenCalled())
 expect(f.api.pdfFormAIAccept.mock.calls[0][1]).toEqual({expectedSha256:'a'.repeat(64),operations:base,snapshotSha256:'b'.repeat(64)})
 expect(f.draft.operations).toEqual([...base,fill]);expect(f.changed).toHaveBeenCalledOnce();f.binding.dispose()
})
it('start回执前关闭取消请求且丢弃迟到候选',async()=>{
 let finish!:(job:PDFFormAIJob)=>void
 const f=fixture({pdfFormAIStart:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve}))});f.select();f.instruction();f.click('start')
 const id=f.api.pdfFormAIStart.mock.calls[0][0].clientRequestId;f.click('close');expect(f.api.pdfFormAICancel).toHaveBeenCalledWith(id)
 finish(result);await Promise.resolve();await Promise.resolve();expect(f.root.textContent).not.toContain('收入更新');expect(f.draft.operations).toEqual(base);f.binding.dispose()
})
it('候选后草稿变化拒绝采纳且字段失效不回退全文',async()=>{
 const f=fixture();f.select();f.instruction();f.click('start');await vi.waitFor(()=>expect(f.root.textContent).toContain('收入更新'))
 f.draft.setOperations([...base,{kind:'manual'}]);f.click('accept');expect(f.api.pdfFormAIAccept).not.toHaveBeenCalled();expect(f.root.textContent).toContain('草稿或授权字段已变化')
 f.invalidate();f.click('start');expect(f.api.pdfFormAIStart).toHaveBeenCalledTimes(1);expect(f.root.textContent).toContain('失效选区不会扩大');f.binding.dispose()
})
it('轮询复用SSE中文进度，采纳等待期间人工草稿不会被覆盖',async()=>{
 let finish!:(v:object)=>void
 const f=fixture({pdfFormAIStart:vi.fn().mockResolvedValue({...result,status:'running',result:undefined}),pdfFormAIStatus:vi.fn().mockResolvedValue(result),pdfFormAIEvents:vi.fn(async(_id,emit)=>{emit({sequence:1,kind:'toolCompleted',toolName:'list_form_fields',toolCallId:'fields',outcome:'success'})}),pdfFormAIAccept:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve}))})
 f.select();f.instruction();f.click('start');await vi.waitFor(()=>expect(f.root.textContent).toContain('读取表单字段'))
 expect(f.api.pdfFormAIStatus).toHaveBeenCalledWith('forms',expect.any(AbortSignal));f.click('accept')
 f.draft.setOperations([{kind:'manual'}]);finish({operations:[...base,fill],previewDigest:'d'.repeat(64)})
 await vi.waitFor(()=>expect(f.root.textContent).toContain('草稿或授权字段已变化'));expect(f.draft.operations).toEqual([{kind:'manual'}]);expect(f.refresh).not.toHaveBeenCalled();f.binding.dispose()
})
it('表单HTTP方法使用独立路由和CSRF，取消按请求身份且支持keepalive',async()=>{
 const {createNativeApi}=await import('./native-api')
 const fetcher=vi.fn().mockImplementation(async()=>new Response(JSON.stringify(result)));vi.stubGlobal('fetch',fetcher)
 try{
  const api=createNativeApi('form',1,'csrf'),signal=new AbortController().signal
  const payload={clientRequestId:'request',expectedSha256:'a'.repeat(64),operations:base,selection:[{fieldId:'income'}],instruction:'填84'}
  await api.pdfFormAIStart(payload,signal);await api.pdfFormAIStatus('task/id',signal);await api.pdfFormAIAccept('task/id',{expectedSha256:payload.expectedSha256,operations:base,snapshotSha256:'b'.repeat(64)},signal);await api.pdfFormAICancel('request')
  const path='/reports/v1/native/form/1/api/ai/forms/'
  expect(fetcher.mock.calls.map(([url])=>url)).toEqual([path+'start',path+'task%2Fid?waitMs=20000',path+'task%2Fid/accept',path+'cancel'])
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(payload);expect(new Headers(fetcher.mock.calls[2][1].headers).get('X-CSRF-Token')).toBe('csrf');expect(fetcher.mock.calls[3][1].keepalive).toBe(true)
 }finally{vi.unstubAllGlobals()}
})
it('填写要求变化取消待响应请求并使旧候选及采纳响应失效',async()=>{
 let finish!:(v:PDFFormAIJob)=>void
 const f=fixture({pdfFormAIStart:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve}))});f.select();f.instruction();f.click('start')
 const input=f.root.querySelector('textarea')!;input.value='改填另一金额';input.dispatchEvent(new Event('input'))
 expect(f.api.pdfFormAICancel).toHaveBeenCalledOnce();finish(result);await Promise.resolve();await Promise.resolve()
 expect(f.root.querySelector<HTMLButtonElement>('[data-pdf-form-ai=accept]')!.disabled).toBe(true);expect(f.draft.operations).toEqual(base);f.binding.dispose()
})
it('采纳等待期间修改要求不能写入旧填写候选',async()=>{
 let finish!:(v:object)=>void
 const f=fixture({pdfFormAIAccept:vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve}))});f.select();f.instruction();f.click('start');await vi.waitFor(()=>expect(f.root.textContent).toContain('收入更新'));f.click('accept')
 const input=f.root.querySelector('textarea')!;input.value='改填另一金额';input.dispatchEvent(new Event('input'));finish({operations:[...base,fill],previewDigest:'d'})
 await Promise.resolve();await Promise.resolve();expect(f.draft.operations).toEqual(base);expect(f.refresh).not.toHaveBeenCalled();f.binding.dispose()
})
