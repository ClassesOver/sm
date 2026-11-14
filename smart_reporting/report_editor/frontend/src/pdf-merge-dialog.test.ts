import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {webcrypto} from 'node:crypto'
import {bindPdfMergeDialog} from './pdf-merge-dialog'
import type {NativeSaveResponse} from './native-api'

beforeEach(()=>{
  vi.stubGlobal('crypto',webcrypto)
  Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value(this:HTMLDialogElement){this.open=true}})
  Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value(this:HTMLDialogElement){this.open=false;this.dispatchEvent(new Event('close'))}})
})
afterEach(()=>{document.body.replaceChildren();vi.unstubAllGlobals()})
const result:NativeSaveResponse={documentId:'child',revision:1,parentRevision:null,revisionRegistered:false,
  artifacts:{pdf:{downloadUrl:'/verified/merged',sha256:'c'.repeat(64)}},validation:{ok:false,issues:[{code:'registration',message:'登记失败，下载仍可用'}]}}
function fixture(){
  const root=document.body.appendChild(document.createElement('div'))
  const merge=vi.fn(async(_payload:unknown)=>result),prepareSource=vi.fn(async()=>({sha256:'b'.repeat(64),merge}))
  const view=bindPdfMergeDialog({root,unavailable:()=>null,prepareSource})
  return{root,view,merge,prepareSource,input:root.querySelector<HTMLInputElement>('input[type=file]')!,apply:root.querySelector<HTMLButtonElement>('[data-pdf-merge-apply]')!}
}
function pick(f:ReturnType<typeof fixture>,names=['second.pdf','first.pdf']){
  const files=names.map(name=>{const bytes=new TextEncoder().encode(`%PDF-${name}`);return{name,size:bytes.length,arrayBuffer:async()=>bytes.buffer} as File})
  Object.defineProperty(f.input,'files',{configurable:true,value:files});f.input.dispatchEvent(new Event('change'))
}
it('多选可调整顺序，先保存来源后按所列顺序合并，验收失败仍显示实际下载',async()=>{
  const f=fixture();f.view.open();pick(f)
  f.root.querySelector<HTMLButtonElement>('[aria-label="上移 first.pdf"]')!.click();f.apply.click()
  await vi.waitFor(()=>expect(f.root.querySelector('a')?.getAttribute('href')).toBe('/verified/merged'))
  expect(f.prepareSource).toHaveBeenCalledOnce();expect(f.root.textContent).toContain('登记失败，下载仍可用')
  const payload=f.merge.mock.calls[0]![0] as {expectedSha256:string;files:{bytesBase64:string}[]}
  expect(payload.expectedSha256).toBe('b'.repeat(64));expect(payload.files.map(file=>atob(file.bytesBase64))).toEqual(['%PDF-first.pdf','%PDF-second.pdf'])
  f.root.querySelector('dialog')!.close();f.view.open();expect(f.root.querySelector('a')).not.toBeNull();expect(f.merge).toHaveBeenCalledOnce()
})
it('取消和空选择不保存；无效文件在保存之前拒绝',async()=>{
  const f=fixture();f.view.open();f.root.querySelector('dialog')!.close();expect(f.prepareSource).not.toHaveBeenCalled()
  f.view.open();f.apply.click();expect(f.prepareSource).not.toHaveBeenCalled();pick(f,['invalid.pdf'])
  Object.defineProperty(f.input.files![0],'arrayBuffer',{value:async()=>new TextEncoder().encode('invalid PDF').buffer})
  f.apply.click();await vi.waitFor(()=>expect(f.root.textContent).toContain('不是有效 PDF'));expect(f.prepareSource).not.toHaveBeenCalled();expect(f.merge).not.toHaveBeenCalled()
})
it('预览确认未完成保留所选文件，未提交合并',async()=>{
  const f=fixture();f.prepareSource.mockRejectedValueOnce(new Error('请勾选确认实际预览'))
  f.view.open();pick(f);f.apply.click();await vi.waitFor(()=>expect(f.root.textContent).toContain('请勾选确认'))
  expect(f.merge).not.toHaveBeenCalled();expect(f.root.textContent).toContain('second.pdf');expect(f.apply.disabled).toBe(false)
})
it('关闭等待中的合并不丢已生成结果，销毁后不挂载迟到结果',async()=>{
  const f=fixture();let resolve!:(value:NativeSaveResponse)=>void
  f.merge.mockImplementation(()=>new Promise(done=>{resolve=done}));f.view.open();pick(f);f.apply.click()
  await vi.waitFor(()=>expect(f.merge).toHaveBeenCalledOnce());f.root.querySelector('dialog')!.close();resolve(result)
  await new Promise(done=>setTimeout(done,0));f.view.open();expect(f.root.querySelector('a')).not.toBeNull();f.view.dispose();expect(f.root.querySelector('dialog')).toBeNull()
})
