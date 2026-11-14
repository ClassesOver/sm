import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {NativeDraft} from './native-draft'
import {bindPdfExistingImagePanel} from './pdf-existing-image'

const sha='a'.repeat(64),pageId='sha256:'+sha+':page:0'
const target={pageId,pageIndex:0,rect:[60,90,160,170] as [number,number,number,number],imageId:'b'.repeat(64),expectedImageSha256:'c'.repeat(64),aboveText:true,editable:true,replaceable:false,replaceReason:'同一图像数据被多处引用'}
const descriptors={showModal:Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype,'showModal'),close:Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype,'close')}
const panels:ReturnType<typeof bindPdfExistingImagePanel>[]=[]
beforeEach(()=>{
 localStorage.clear()
 Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:function(this:HTMLDialogElement){this.open=true}})
 Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value:function(this:HTMLDialogElement){this.open=false;this.dispatchEvent(new Event('close'))}})
})
afterEach(()=>{
 panels.splice(0).forEach(panel=>panel.dispose());document.body.replaceChildren();vi.restoreAllMocks()
 for(const name of ['showModal','close'] as const){const descriptor=descriptors[name];if(descriptor)Object.defineProperty(HTMLDialogElement.prototype,name,descriptor);else Reflect.deleteProperty(HTMLDialogElement.prototype,name)}
})
function fixture(image:typeof target & {bakeable?:boolean;bakeReason?:string}=target,refresh:()=>Promise<void>=async()=>{}){
 const opener=document.body.appendChild(document.createElement('button'));opener.textContent='编辑图像';opener.focus()
 const root=document.body.appendChild(document.createElement('div'))
 const draft=new NativeDraft({documentId:'image-panel',revision:1,sourceSha256:sha,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},localStorage)
 const status=vi.fn()
 const panel=bindPdfExistingImagePanel({root,draft,pages:()=>[{pageId,index:0,rotation:0,cropBox:{x:0,y:0,width:400,height:500},mediaBox:{x:0,y:0,width:400,height:500}}],images:()=>[image],unavailable:()=>null,refresh,status})
 panels.push(panel);panel.open()
 return {panel,opener,draft,status,dialog:root.querySelector('dialog')!}
}

it('groups existing image controls and exposes unsupported replacement without changing the draft',()=>{
 const {dialog,draft}=fixture()
 expect([...dialog.querySelectorAll('fieldset legend')].map(node=>node.textContent)).toEqual(['位置与尺寸','替换图像','像素编辑'])
 const selection=dialog.querySelector('select')!
 expect(document.activeElement).toBe(selection)
 expect(dialog.querySelector('[role=region][aria-label="已有图像编辑说明"]')?.getAttribute('tabindex')).toBe('0')
 const pick=dialog.querySelector<HTMLButtonElement>('[data-pdf-existing-image-replace]')!
 expect(pick.disabled).toBe(true)
 expect(dialog.querySelector('[role=status]')?.textContent).toContain('多处引用')
 expect(draft.operations).toEqual([])
})

it.each(['cancel','title','escape'])('returns focus and discards unsubmitted image geometry on %s',action=>{
 const {dialog,opener,panel,draft}=fixture()
 dialog.querySelector<HTMLInputElement>('[aria-label="已有图像宽度"]')!.value='200'
 if(action==='escape'){
  const event=new Event('cancel',{cancelable:true});dialog.dispatchEvent(event);expect(event.defaultPrevented).toBe(true)
 }else{
  const close=action==='title'?dialog.querySelector<HTMLButtonElement>('[aria-label="关闭编辑已有图像"]'):[...dialog.querySelectorAll('button')].find(button=>button.textContent==='取消')
  expect(close).not.toBeNull();close!.focus();close!.click()
 }
 expect(dialog.open).toBe(false);expect(document.activeElement).toBe(opener);expect(draft.operations).toEqual([])
 panel.open();expect(dialog.querySelector<HTMLInputElement>('[aria-label="已有图像宽度"]')!.value).toBe('100')
})

it('keeps invalid geometry editable and announces the reason before staging a valid edit',async()=>{
 const {dialog,draft}=fixture(),width=dialog.querySelector<HTMLInputElement>('[aria-label="已有图像宽度"]')!,apply=dialog.querySelector<HTMLButtonElement>('[data-pdf-existing-image-confirm]')!
 width.value='';apply.click()
 const alert=dialog.querySelector('[role=alert]')!
 expect(alert.getAttribute('aria-label')).toBe('已有图像校验提示');expect(alert.getAttribute('tabindex')).toBe('0')
 expect(alert.textContent).toContain('有限数值');expect(dialog.open).toBe(true);expect(draft.operations).toEqual([])
 width.value='150';apply.click();await vi.waitFor(()=>expect(dialog.open).toBe(false))
 expect(draft.operations).toEqual([{kind:'transformExistingImage',sourceSha256:sha,pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,rect:[60,90,210,170]}])
})

it('keeps incoming pixel edits in the scroll body and restores focus after applying opacity',async()=>{
 const {dialog,draft,opener}=fixture({...target,bakeable:true})
 const kind=dialog.querySelector<HTMLSelectElement>('[aria-label="已有图像像素编辑"]')!
 expect(kind.closest('.pdf-existing-image-body')).not.toBeNull()
 kind.value='opacity';kind.dispatchEvent(new Event('change'))
 expect(dialog.querySelector<HTMLInputElement>('[aria-label="已有图像宽度"]')!.disabled).toBe(true)
 const opacity=dialog.querySelector<HTMLInputElement>('[aria-label="图像透明度百分比"]')!
 expect(opacity.parentElement!.hidden).toBe(false);opacity.value='25'
 dialog.querySelector<HTMLButtonElement>('[data-pdf-existing-image-confirm]')!.click()
 await vi.waitFor(()=>expect(dialog.open).toBe(false))
 expect(document.activeElement).toBe(opener)
 expect(draft.operations).toEqual([{kind:'transformExistingImage',sourceSha256:sha,pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,rect:target.rect,bake:{kind:'opacity',alpha:.75}}])
})

it('groups pixel controls and exposes disabled bake reasons as keyboard-readable feedback',()=>{
 const {dialog}=fixture()
 expect([...dialog.querySelectorAll('fieldset legend')].map(node=>node.textContent)).toEqual(['位置与尺寸','替换图像','像素编辑'])
 const kind=dialog.querySelector<HTMLSelectElement>('[aria-label="已有图像像素编辑"]')!
 expect(kind.closest('fieldset')?.querySelector('legend')?.textContent).toBe('像素编辑')
 const feedback=dialog.querySelector<HTMLElement>('[role=status][aria-label="图像像素编辑状态"]')!
 expect(feedback).not.toBeNull();expect(feedback.tabIndex).toBe(0)
 expect(feedback.textContent).toContain('暂不支持');expect(feedback.textContent).toContain('旋转');expect(kind.disabled).toBe(true)
})
it('disables quarter-turn rotation for non-bakeable existing images and exposes the source reason',()=>{
 const {dialog,draft}=fixture({...target,bakeable:false,replaceReason:'图像旋转矩阵不支持安全烘焙'})
 const kind=dialog.querySelector<HTMLSelectElement>('[aria-label="已有图像像素编辑"]')!
 expect(kind.disabled).toBe(true);expect(kind.title).toContain('暂不支持裁剪、翻转、旋转与透明度')
 expect([...kind.options].map(option=>option.value)).toContain('rotate-cw')
 expect(draft.operations).toEqual([])
})

it.each([['rotate-cw',1],['rotate-ccw',3]] as const)('stages image %s as a centered single-page quarter turn with undo/redo',async(value,turns)=>{
 const {dialog,draft,status}=fixture({...target,bakeable:true})
 const kind=dialog.querySelector<HTMLSelectElement>('[aria-label="已有图像像素编辑"]')!
 kind.value=value;kind.dispatchEvent(new Event('change'))
 dialog.querySelector<HTMLButtonElement>('[data-pdf-existing-image-confirm]')!.click()
 await vi.waitFor(()=>expect(dialog.open).toBe(false))
 const operation={kind:'transformExistingImage',sourceSha256:sha,pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,rect:[70,80,150,180],bake:{kind:'rotate',quarterTurns:turns}}
 expect(draft.operations).toEqual([operation]);expect(status).toHaveBeenCalledWith(expect.stringContaining('旋转'))
 draft.undo();expect(draft.operations).toEqual([])
 draft.redo();expect(draft.operations).toEqual([operation])
})
it('rejects blank crop input without silently substituting zero and focuses the error',()=>{
 const {dialog,draft}=fixture({...target,bakeable:true})
 const kind=dialog.querySelector<HTMLSelectElement>('[aria-label="已有图像像素编辑"]')!
 kind.value='crop';kind.dispatchEvent(new Event('change'))
 dialog.querySelector<HTMLInputElement>('[aria-label="裁去左侧百分比"]')!.value='25'
 dialog.querySelector<HTMLInputElement>('[aria-label="裁去右侧百分比"]')!.value=''
 dialog.querySelector<HTMLButtonElement>('[data-pdf-existing-image-confirm]')!.click()
 const feedback=dialog.querySelector<HTMLElement>('[role=alert]')!
 expect(dialog.open).toBe(true);expect(draft.operations).toEqual([])
 expect(feedback.textContent).toContain('整数');expect(document.activeElement).toBe(feedback)
 expect(dialog.querySelector<HTMLInputElement>('[aria-label="裁去左侧百分比"]')!.value).toBe('25')
})

it('reports refresh failure after staging without hiding the error in a closed dialog',async()=>{
 const {dialog,draft,opener,status}=fixture({...target,bakeable:true},async()=>{throw Error('预览服务暂不可用')})
 const kind=dialog.querySelector<HTMLSelectElement>('[aria-label="已有图像像素编辑"]')!
 kind.value='flip-h';kind.dispatchEvent(new Event('change'))
 dialog.querySelector<HTMLButtonElement>('[data-pdf-existing-image-confirm]')!.click()
 await vi.waitFor(()=>expect(status).toHaveBeenCalledWith(expect.stringContaining('预览服务暂不可用')))
 expect(status.mock.calls.at(-1)?.[0]).toContain('已暂存')
 expect(draft.operations).toHaveLength(1);expect(dialog.open).toBe(false);expect(document.activeElement).toBe(opener)
})
