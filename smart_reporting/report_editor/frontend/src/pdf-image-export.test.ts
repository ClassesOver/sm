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
function fixture(count=4, prepareSource?:()=>Promise<{sha256:string;exportImages:(payload:PdfImageExportRequest)=>Promise<PdfImageExportResult>}>){const root=document.createElement('div');document.body.append(root);let blocked:string|null=null
  const exportImages=vi.fn(async(_payload:PdfImageExportRequest)=>result())
  const view=bindPdfImageExportDialog({root,sourceSha256:'a'.repeat(64),pageCount:()=>count,currentPage:()=>2,unavailable:()=>blocked,exportImages,prepareSource})
  const dialog=root.querySelector('dialog')!,apply=root.querySelector<HTMLButtonElement>('[data-pdf-image-export-apply]')!
  return{root,view,dialog,apply,exportImages,block:()=>{blocked='先保存草稿'}}}
it('exports requested saved pages and exposes only an identity-verified session ZIP',async()=>{
  const f=fixture();f.view.open('jpeg');f.root.querySelector<HTMLInputElement>('[aria-label="导出图片页码"]')!.value='4,1-2';f.apply.click()
  await vi.waitFor(()=>expect(f.root.querySelector('a')).not.toBeNull())
  expect(f.exportImages.mock.calls[0]![0]).toEqual({expectedSha256:'a'.repeat(64),pages:[4,1,2],format:'jpeg',dpi:150})
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
it('keeps both Tab directions on the available close action during export',()=>{
  const f=fixture();f.exportImages.mockImplementation(()=>new Promise(()=>{}));f.view.open();f.apply.click()
  const close=[...f.root.querySelectorAll('button')].find(button=>button.textContent==='关闭')!;close.focus()
  for(const shiftKey of [false,true]){
    const tab=new KeyboardEvent('keydown',{key:'Tab',shiftKey,bubbles:true,cancelable:true});close.dispatchEvent(tab)
    expect(tab.defaultPrevented).toBe(true);expect(document.activeElement).toBe(close)
  }
  close.click();expect(f.dialog.open).toBe(false);f.view.dispose()
})
it('starts a ribbon export with all saved pages at the source resolution and switches to the current page', async () => {
  const f = fixture()
  const range = f.root.querySelector<HTMLInputElement>('[aria-label="导出图片页码"]')!
  f.view.open('jpeg', 'all')
  expect(range.value).toBe('1-4')
  f.apply.click()
  await vi.waitFor(() => expect(f.exportImages).toHaveBeenCalledWith({ expectedSha256:'a'.repeat(64), pages:[1,2,3,4], format:'jpeg', dpi:150 }))
  await vi.waitFor(() => expect(f.apply.disabled).toBe(false))
  const current = [...f.dialog.querySelectorAll('button')].find(button => button.textContent === '当前页')!
  current.click()
  expect(range.value).toBe('2')
  f.apply.click()
  await vi.waitFor(() => expect(f.exportImages.mock.calls[1]?.[0].pages).toEqual([2]))
})

it('shows the page limit when all pages exceed the export budget and allows a smaller range', async () => {
  const f = fixture(51)
  f.view.open('png', 'all')
  expect(f.root.textContent).toContain('最多 50 页')
  f.apply.click()
  expect(f.exportImages).not.toHaveBeenCalled()
  f.root.querySelector<HTMLInputElement>('[aria-label="导出图片页码"]')!.value = '3-4'
  f.apply.click()
  await vi.waitFor(() => expect(f.exportImages.mock.calls[0]?.[0].pages).toEqual([3,4]))
})

it('exports and verifies using the newly saved source instead of the original transport', async () => {
  const expectedSha256='c'.repeat(64)
  const exportSaved=vi.fn(async()=>({...result(),sourceSha256:expectedSha256}))
  const prepareSource=vi.fn(async()=>({sha256:expectedSha256,exportImages:exportSaved}))
  const f=fixture(3,prepareSource)
  f.view.open('jpeg','all');f.apply.click()
  await vi.waitFor(()=>expect(f.root.querySelector('a')).not.toBeNull())
  expect(prepareSource).toHaveBeenCalledOnce()
  expect(exportSaved).toHaveBeenCalledWith({expectedSha256,pages:[1,2,3],format:'jpeg',dpi:150})
  expect(f.exportImages).not.toHaveBeenCalled()
})

it('does not start rendering after the dialog closes during source save', async () => {
  const exportSaved=vi.fn(async()=>result())
  let finish!: () => void
  const f=fixture(3,()=>new Promise(resolve=>{finish=()=>resolve({sha256:'c'.repeat(64),exportImages:exportSaved})}))
  f.view.open('png','all');f.apply.click();f.dialog.close();finish()
  await new Promise(resolve=>setTimeout(resolve,0))
  expect(exportSaved).not.toHaveBeenCalled()
  expect(f.exportImages).not.toHaveBeenCalled()
})
