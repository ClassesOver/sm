import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {NativeDraft} from './native-draft'
import {bindPdfExistingImagePanel} from './pdf-existing-image'
const sha='a'.repeat(64),pageId='sha256:'+sha+':page:0'
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
const panels:ReturnType<typeof bindPdfExistingImagePanel>[]=[]
const descriptors=Object.fromEntries(['showModal','close'].map(name=>[name,Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype,name)]))
beforeEach(()=>{
 localStorage.clear()
 Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:function(this:HTMLDialogElement){this.open=true}})
 Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value:function(this:HTMLDialogElement){this.open=false;this.dispatchEvent(new Event('close'))}})
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage(){}} as never)
 vi.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockReturnValue('data:image/png;base64,'+png)
})
afterEach(()=>{
 panels.splice(0).forEach(panel=>panel.dispose());vi.restoreAllMocks();vi.unstubAllGlobals();document.body.replaceChildren()
 for(const name of ['showModal','close']){const descriptor=descriptors[name];if(descriptor)Object.defineProperty(HTMLDialogElement.prototype,name,descriptor);else Reflect.deleteProperty(HTMLDialogElement.prototype,name)}
})
function fixture(){
 const root=document.body.appendChild(document.createElement('div'))
 const draft=new NativeDraft({documentId:'loading',revision:1,sourceSha256:sha,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},localStorage)
 const images=[0,1].map(index=>({pageId,pageIndex:0,rect:[60,90,160,170] as [number,number,number,number],imageId:(index?'d':'b').repeat(64),expectedImageSha256:'c'.repeat(64),aboveText:true,editable:true,replaceable:true,bakeable:true}))
 const panel=bindPdfExistingImagePanel({root,draft,pages:()=>[{pageId,index:0,rotation:0,cropBox:{x:0,y:0,width:400,height:500},mediaBox:{x:0,y:0,width:400,height:500}}],images:()=>images,unavailable:()=>null,refresh:async()=>{},status(){}})
 panels.push(panel);panel.open()
 let resolve!:(bitmap:ImageBitmap)=>void,reject!:(reason:Error)=>void
 vi.stubGlobal('createImageBitmap',()=>new Promise<ImageBitmap>((yes,no)=>{resolve=yes;reject=no}))
 const input=root.querySelector<HTMLInputElement>('input[type=file]')!
 Object.defineProperty(input,'files',{configurable:true,value:[new File(['pixels'],'replacement.png',{type:'image/png'})]})
 input.dispatchEvent(new Event('change'))
 return {panel,draft,dialog:root.querySelector('dialog')!,root,resolve:()=>resolve({width:2,height:2,close(){}} as ImageBitmap),reject:()=>reject(Error('解码失败'))}
}
it('blocks apply while replacement pixels are being decoded and enables it after conversion',async()=>{
 const f=fixture(),apply=f.root.querySelector<HTMLButtonElement>('[data-pdf-existing-image-confirm]')!
 expect(apply.disabled).toBe(true);expect(f.dialog.getAttribute('aria-busy')).toBe('true')
 expect(f.root.querySelector('[aria-label="图像替换状态"]')?.textContent).toContain('正在')
 apply.dispatchEvent(new Event('click'));expect(f.draft.operations).toEqual([])
 f.resolve();await vi.waitFor(()=>expect(apply.disabled).toBe(false))
 expect(f.dialog.getAttribute('aria-busy')).toBe('false')
 apply.click();await vi.waitFor(()=>expect(f.draft.operations[0]?.image).toBe(png))
})
it.each(['target','reopen','dispose'])('ignores replacement decoding after %s changes the editing session',async action=>{
 const f=fixture()
 if(action==='target'){const select=f.root.querySelector<HTMLSelectElement>('[aria-label="已有图像选择"]')!;select.value='1';select.dispatchEvent(new Event('change'))}
 if(action==='reopen'){f.panel.cancel();f.panel.open()}
 if(action==='dispose')f.panel.dispose()
 f.resolve();await new Promise(resolve=>setTimeout(resolve,0))
 expect(f.draft.operations).toEqual([])
 if(action!=='dispose'){
  expect(f.root.querySelector('[aria-label="图像替换状态"]')?.textContent).toBe('不替换像素')
  f.root.querySelector<HTMLButtonElement>('[data-pdf-existing-image-confirm]')!.click()
  await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(1))
  expect(f.draft.operations[0]?.image).toBeUndefined()
  expect(f.draft.operations[0]?.imageId).toBe((action==='target'?'d':'b').repeat(64))
 }
})
it('keeps decoder failure visible, restores availability, and preserves the unchanged draft',async()=>{
 const f=fixture();f.reject()
 await vi.waitFor(()=>expect(f.root.querySelector('[role=alert]')?.textContent).toContain('解码失败'))
 expect(f.dialog.open).toBe(true);expect(f.draft.operations).toEqual([])
 expect(f.root.querySelector<HTMLButtonElement>('[data-pdf-existing-image-confirm]')!.disabled).toBe(false)
 expect(document.activeElement).toBe(f.root.querySelector('[role=alert]'))
})
it('cancels an outstanding replacement when the user explicitly chooses not to replace',async()=>{
 const f=fixture();f.resolve()
 await vi.waitFor(()=>expect(f.root.querySelector('[aria-label="图像替换状态"]')?.textContent).toContain('replacement.png'))
 const input=f.root.querySelector<HTMLInputElement>('input[type=file]')!;input.dispatchEvent(new Event('change'))
 const clear=[...f.root.querySelectorAll('button')].find(button=>button.textContent==='不替换')!
 expect(clear.hidden).toBe(false);clear.click();f.resolve();await new Promise(resolve=>setTimeout(resolve,0))
 expect(f.root.querySelector('[aria-label="图像替换状态"]')?.textContent).toBe('不替换像素')
 const apply=f.root.querySelector<HTMLButtonElement>('[data-pdf-existing-image-confirm]')!;expect(apply.disabled).toBe(false);apply.click()
 await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(1));expect(f.draft.operations[0]?.image).toBeUndefined()
})
