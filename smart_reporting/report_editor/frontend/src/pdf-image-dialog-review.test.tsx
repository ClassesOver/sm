// 只读review探针：不修改被审查的source dialog与宿主控制器。
import {afterEach,expect,it,vi} from 'vitest'
import {createElement} from 'react'
import {flushSync} from 'react-dom'
import {createRoot,type Root} from 'react-dom/client'
import {CropDialog,CutoutDialog} from './vendor/genoffice-pdf/renderer/ImageDialogs'
let root:Root|undefined
afterEach(()=>{root?.unmount();root=undefined;vi.restoreAllMocks();vi.unstubAllGlobals();document.body.replaceChildren()})
async function mount(kind:'crop'|'cutout'='crop'){
 vi.stubGlobal('Image',class {naturalWidth=100;naturalHeight=80;onload:(()=>void)|null=null;onerror:(()=>void)|null=null;set src(_value:string){if(kind==='crop')queueMicrotask(()=>this.onload?.())}})
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage(){}} as never)
 vi.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockReturnValue('data:image/png;base64,iVBORw0KGgo=')
 const host=document.body.appendChild(document.createElement('div'));root=createRoot(host)
 const onApply=vi.fn(),onCancel=vi.fn(),t=((key:string)=>key) as never
 flushSync(()=>root!.render(kind==='crop'?createElement(CropDialog,{t,image:'pixels',onApply,onCancel}):createElement(CutoutDialog,{t,image:'pixels',onApply,onCancel})))
 if(kind==='crop')await vi.waitFor(()=>expect(host.querySelector<HTMLButtonElement>('.primary')?.disabled).toBe(false))
 return {host,onApply,onCancel}
}
it('Enter on the focused cancel button does not apply the crop',async()=>{
 const f=await mount(),cancel=f.host.querySelector<HTMLButtonElement>('.pdf-modal-actions button')!;cancel.focus();cancel.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));expect(f.onApply).not.toHaveBeenCalled()
})
it('IME composition Enter does not apply the crop',async()=>{
 const f=await mount();f.host.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:true,bubbles:true,cancelable:true}));expect(f.onApply).not.toHaveBeenCalled()
})
it.each(['crop','cutout'] as const)('IME composition Escape does not close %s',async kind=>{
 const f=await mount(kind);f.host.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',isComposing:true,bubbles:true,cancelable:true}));expect(f.onCancel).not.toHaveBeenCalled()
})
