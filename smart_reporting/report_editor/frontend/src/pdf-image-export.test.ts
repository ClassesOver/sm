import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { webcrypto, createHash } from 'node:crypto'
import { bindPdfImageExportDialog, type PdfImageExportRequest, type PdfImageExportResult } from './pdf-image-export'
beforeEach(()=>{
  vi.stubGlobal('crypto',webcrypto)
  Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value(this:HTMLDialogElement){this.open=true}})
  Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value(this:HTMLDialogElement){this.open=false;this.dispatchEvent(new Event('close'))}})
  Object.defineProperty(URL,'createObjectURL',{configurable:true,value:vi.fn(()=> 'blob:verified')})
  Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:vi.fn()})
})
afterEach(()=>{document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals()})
const bytes=new Uint8Array([80,75,3,4,1,2,3,4])
const result=():PdfImageExportResult=>({content:bytes.buffer,sha256:createHash('sha256').update(bytes).digest('hex'),size:bytes.length,sourceSha256:'a'.repeat(64),filename:'pdf-pages-png.zip'})
function fixture(){const root=document.createElement('div');document.body.append(root);let blocked:string|null=null
  const exportImages=vi.fn(async(_payload:PdfImageExportRequest)=>result())
  const view=bindPdfImageExportDialog({root,sourceSha256:'a'.repeat(64),pageCount:()=>4,currentPage:()=>2,unavailable:()=>blocked,exportImages})
  const dialog=root.querySelector('dialog')!,apply=root.querySelector<HTMLButtonElement>('[data-pdf-image-export-apply]')!
  return{root,view,dialog,apply,exportImages,block:()=>{blocked='先保存草稿'}}}
it('exports requested saved pages and exposes only an identity-verified session ZIP',async()=>{
  const f=fixture();f.view.open('jpeg');f.root.querySelector<HTMLInputElement>('[aria-label="导出图片页码"]')!.value='4,1-2';f.apply.click()
  await vi.waitFor(()=>expect(f.root.querySelector('a')).not.toBeNull())
  expect(f.exportImages.mock.calls[0]![0]).toEqual({expectedSha256:'a'.repeat(64),pages:[4,1,2],format:'jpeg',dpi:144})
  expect(f.root.querySelector('a')!.getAttribute('href')).toBe('blob:verified');expect(f.root.textContent).toContain('本次会话')
  f.view.dispose();expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:verified')
})
it.each(['sha','size','source','signature'])('refuses ZIP identity mismatch: %s',async kind=>{
  const f=fixture(),value=result()
  if(kind==='sha')value.sha256='f'.repeat(64);if(kind==='size')value.size++;if(kind==='source')value.sourceSha256='f'.repeat(64);if(kind==='signature')value.content=new Uint8Array([1,2,3,4]).buffer
  f.exportImages.mockResolvedValue(value);f.view.open();f.apply.click()
  await vi.waitFor(()=>expect(f.root.textContent).toContain('身份'));expect(f.root.querySelector('a')).toBeNull()
})
it('rejects invalid selections and changed editability before export',async()=>{const f=fixture();f.view.open();f.root.querySelector<HTMLInputElement>('[aria-label="导出图片页码"]')!.value='5';f.apply.click();expect(f.exportImages).not.toHaveBeenCalled();f.block();f.apply.dispatchEvent(new MouseEvent('click'));expect(f.exportImages).not.toHaveBeenCalled()})
it('ignores a completed export after closing the dialog',async()=>{const f=fixture();let done!:(value:PdfImageExportResult)=>void;f.exportImages.mockImplementation(()=>new Promise(resolve=>{done=resolve}));f.view.open();f.apply.click();await vi.waitFor(()=>expect(f.exportImages).toHaveBeenCalledTimes(1));f.dialog.close();const before=f.root.innerHTML;done(result());await new Promise(resolve=>setTimeout(resolve,0));expect(f.root.innerHTML).toBe(before);expect(URL.createObjectURL).not.toHaveBeenCalled()})
