import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {createEditorShell} from './shell'
import {createSlidesEditorView} from './slides-main'
import {NativeDraft} from './native-draft'
import {validateZoomDraft} from './slides-zoom-model'
vi.mock('./vendor/genoffice/renderer/SlideThumb',()=>({SlideThumb:()=>null}))
vi.mock('./slides-canvas',()=>({mountSlidesCanvas:()=>({update(){},destroy(){}})}))
vi.mock('./slides-print-render',()=>({renderSlidesPrintImages:vi.fn(async(slides:unknown[])=>slides.map(()=> 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='))}))
const gridFailure=vi.hoisted(()=>({once:true}))
vi.mock('./slides-zoom-grid',async importActual=>{const actual=await importActual<typeof import('./slides-zoom-grid')>();return {...actual,mountZoomGrid:async(...args:Parameters<typeof actual.mountZoomGrid>)=>{if(gridFailure.once){gridFailure.once=false;throw Error('缩略图读取失败')}return actual.mountZoomGrid(...args)}}})
let view:ReturnType<typeof createSlidesEditorView>
it('拒绝缺少服务端页面身份的Zoom草稿',()=>{
 expect(()=>validateZoomDraft([{slideIdentity:undefined,targetSlideIdentity:undefined,bytesBase64:'iVBORw0KGgo=',geometry:{x:0,y:0,width:1,height:1},mode:'slide'}],[{}])).toThrow('缩放定位草稿无效')
})
beforeEach(()=>{vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}});Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:function(){this.open=true}});Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value:function(){this.open=false;this.dispatchEvent(new Event('close'))}})})
afterEach(()=>{view?.dispose();document.body.replaceChildren();vi.unstubAllGlobals()})
it('Slide Zoom提交服务端页身份，支持Undo/Redo与草稿重开，Summary显式不可用',async()=>{
 const source={sha256:'a'.repeat(64),revision:1,size:{cx:9144000,cy:5143500},sections:[{name:'第二节',slideIndices:[1,2]}],slides:[0,1,2].map(slideIndex=>({slideIndex,slideIdentity:String(slideIndex+1).repeat(64),elements:[]}))}
 const tree={slides:source.slides.map(s=>({...s,widthPx:960,heightPx:540,nodes:[],scale:1,background:{kind:'solid',color:'#fff'}}))}
 const draft=new NativeDraft({documentId:'zoom-test',revision:1,sourceSha256:source.sha256,scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}}),shell=createEditorShell(document.body.appendChild(document.createElement('main')),'full','pptx')
 const request=vi.fn(async(path:string)=>path==='deck'?source:path==='preview'?{sourceSha256:source.sha256,model:source}:tree)
 const mount=async()=>{view=createSlidesEditorView(shell.editor,{native:true,draft,request:request as never,save:shell.save,download:shell.exportPptx});await view.ready;await new Promise(r=>setTimeout(r,30))}
 await mount()
 shell.editor.querySelector<HTMLButtonElement>('[data-command="slideZoom"]')!.click();await vi.waitFor(()=>expect(shell.editor.querySelector('.status-message')!.textContent).toContain('缩略图读取失败'));expect(document.querySelector('dialog')).toBeNull()
 const opener=shell.editor.querySelector<HTMLButtonElement>('[data-command="slideZoom"]')!
 const open=async()=>{opener.focus();opener.click();await vi.waitFor(()=>expect(document.querySelector('dialog[aria-label="幻灯片缩放定位"]')).not.toBeNull())}
 await open();document.querySelector<HTMLButtonElement>('[data-settings-close]')!.click();expect(document.querySelector('dialog')).toBeNull();expect(document.activeElement).toBe(opener)
 await open();document.querySelector('dialog')!.dispatchEvent(new Event('cancel',{cancelable:true}));expect(document.querySelector('dialog')).toBeNull();expect(document.activeElement).toBe(opener)
 await open()
 await vi.waitFor(()=>expect(document.querySelector('.zoom-items button')).not.toBeNull());const dialog=document.querySelector('dialog')!;dialog.querySelector<HTMLButtonElement>('.zoom-items button')!.click();dialog.querySelector<HTMLButtonElement>('[value=insert]')!.click();await vi.waitFor(()=>expect(draft.operations[0]?.zoomInsertions).toHaveLength(1))
 expect(draft.operations[0]?.zoomInsertions).toMatchObject([{slideIdentity:'1'.repeat(64),targetSlideIdentity:'2'.repeat(64),mode:'slide',geometry:{width:240,height:135}}])
 expect(document.querySelector('dialog')).toBeNull();expect(document.activeElement).toBe(opener)
 shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click();expect(draft.operations[0]?.zoomInsertions).toBeUndefined()
 shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click();expect(draft.operations[0]?.zoomInsertions).toHaveLength(1)
 view.dispose();await mount();expect(draft.operations[0]?.zoomInsertions).toHaveLength(1)
 expect(shell.editor.querySelector<HTMLButtonElement>('[data-command="summaryZoom"]')!.disabled).toBe(true)
 expect(shell.editor.querySelector<HTMLButtonElement>('[data-command="summaryZoom"]')!.title).toContain('原子')
})
