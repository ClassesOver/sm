import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { webcrypto } from 'node:crypto'
import { bindPdfExternalPagesDialog, type PdfExternalPagesRequest } from './pdf-external-pages'
import type { NativeSaveResponse } from './native-api'
beforeEach(()=>{
  vi.stubGlobal('crypto',webcrypto)
  Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value(this:HTMLDialogElement){this.open=true}})
  Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value(this:HTMLDialogElement){this.open=false;this.dispatchEvent(new Event('close'))}})
})
afterEach(()=>{document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals()})
const result=():NativeSaveResponse=>({documentId:'parent',revision:5,parentRevision:4,revisionRegistered:true,artifacts:{pdf:{downloadUrl:'/real.pdf'}},editor:{openUrl:'/next'},validation:{ok:false,issues:[{code:'pending',message:'尚待验收'}]}})
function fixture(){
  const root=document.createElement('div');document.body.append(root);let blocked:string|null=null
  const submit=vi.fn(async(_payload:PdfExternalPagesRequest)=>result())
  const view=bindPdfExternalPagesDialog({root,sourceSha256:'a'.repeat(64),pageCount:()=>3,currentPage:()=>2,unavailable:()=>blocked,submit})
  const dialog=root.querySelector('dialog')!,file=root.querySelector<HTMLInputElement>('input[type=file]')!,apply=root.querySelector<HTMLButtonElement>('[data-pdf-external-pages-apply]')!
  const upload=(value='%PDF-external')=>{const picked=new File([value],'external.pdf',{type:'application/pdf'});Object.defineProperty(picked,'arrayBuffer',{value:async()=>new TextEncoder().encode(value).buffer});Object.defineProperty(file,'files',{configurable:true,value:[picked]});file.dispatchEvent(new Event('change'))}
  return {root,view,dialog,file,apply,submit,upload,block:()=>{blocked='请先保存草稿'}}
}
it('uploads actual PDF bytes with dual SHA and parent-based insertion index while keeping failed validation links',async()=>{
  const f=fixture();f.view.open('insert');f.upload();f.apply.click()
  await vi.waitFor(()=>expect(f.root.querySelectorAll('a')).toHaveLength(2))
  expect(f.submit.mock.calls[0]![0]).toMatchObject({action:'insert',expectedSha256:'a'.repeat(64),afterPage:2,bytesBase64:'JVBERi1leHRlcm5hbA=='})
  expect(f.submit.mock.calls[0]![0].externalSha256).toBe('32668d4a39f36d2256034e98f9e0251856db576aaac80b7e03a77bedef990392')
  expect(f.root.textContent).toContain('验收未通过');expect(f.root.textContent).toContain('尚待验收')
})
it('honors an explicit insertion position including the beginning of the document',async()=>{
  const f=fixture();f.view.open('insert',0);f.upload();f.apply.click()
  await vi.waitFor(()=>expect(f.submit).toHaveBeenCalledTimes(1))
  expect(f.submit.mock.calls[0]![0].afterPage).toBe(0)
})
it('replacement submits selected parent pages and retries preserve request identity',async()=>{
  const f=fixture();f.submit.mockRejectedValueOnce(new Error('temporary'))
  f.view.open('replace');f.upload();f.root.querySelector<HTMLInputElement>('[aria-label="替换父 PDF 页码"]')!.value='3,1'
  f.apply.click();await vi.waitFor(()=>expect(f.submit).toHaveBeenCalledTimes(1))
  await vi.waitFor(()=>expect(f.apply.disabled).toBe(false));f.apply.click();await vi.waitFor(()=>expect(f.submit).toHaveBeenCalledTimes(2))
  const [a,b]=f.submit.mock.calls.map(call=>call[0]);expect(a).toEqual(b);expect(a!.pages).toEqual([3,1]);expect(a!.afterPage).toBeUndefined()
})
it('rejects missing non-PDF invalid page selection and changed editability before submit',async()=>{
  const f=fixture();f.view.open('replace');f.apply.click();expect(f.submit).not.toHaveBeenCalled()
  f.upload('not pdf');f.apply.click();await vi.waitFor(()=>expect(f.root.textContent).toContain('PDF'))
  f.upload();f.root.querySelector<HTMLInputElement>('[aria-label="替换父 PDF 页码"]')!.value='4';f.apply.click();await Promise.resolve();expect(f.submit).not.toHaveBeenCalled()
  f.block();f.apply.dispatchEvent(new MouseEvent('click'));await Promise.resolve();expect(f.submit).not.toHaveBeenCalled()
})
it.each(['close','dispose'])('late server result does not repaint after %s',async action=>{
  const f=fixture();let finish!:(value:NativeSaveResponse)=>void;f.submit.mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
  f.view.open('insert');f.upload();f.apply.click();await vi.waitFor(()=>expect(f.submit).toHaveBeenCalledTimes(1))
  if(action==='close')f.dialog.close();else f.view.dispose()
  const before=f.root.innerHTML;finish(result());await new Promise(resolve=>setTimeout(resolve,0));expect(f.root.innerHTML).toBe(before)
  if(action==='close'){f.view.open('insert');expect(f.root.querySelectorAll('a')).toHaveLength(2)}
})
