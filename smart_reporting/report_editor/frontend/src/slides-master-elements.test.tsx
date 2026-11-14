import React from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createSlidesEditorView } from './slides-main'
import { createEditorShell } from './shell'
import { NativeDraft } from './native-draft'

vi.mock('./slides-canvas',()=>({mountSlidesCanvas:()=>({update(){},destroy(){}})}))
vi.mock('./vendor/genoffice/renderer/SlideThumb',()=>({SlideThumb:()=> <figure data-source-master-thumbnail/>}))
const views:ReturnType<typeof createSlidesEditorView>[]=[]
beforeEach(()=>vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}unobserve(){}}))
afterEach(()=>{views.splice(0).forEach(view=>view.dispose());document.body.replaceChildren();vi.unstubAllGlobals()})
async function fixture(initial:object[]=[],structureEditable=true){
 const parts=['master','layout'].map((kind,index)=>({kind,partPath:`ppt/${index?'slideLayouts/slideLayout':'slideMasters/slideMaster'}1.xml`,name:kind,structureEditable,elements:[{spid:7,name:'原品牌',text:`${kind}来源`,editable:true,reason:null,transformEditable:true,transformValue:{x:10,y:20,width:300,height:80,rotationDeg:0},strokeEditable:true,strokeValue:'none'}]}))
 const deck={revision:1,sha256:'a'.repeat(64),size:{cx:9144000,cy:6858000},masterTextParts:parts,slides:[{slideIndex:0,elements:[],animations:[]}]}
 const tree={slides:[{slideIndex:0,widthPx:960,heightPx:720,nodes:[]}],masterTextParts:parts.map(part=>({...part,slide:{widthPx:960,heightPx:720,nodes:[]}}))}
 const shell=createEditorShell(document.body.appendChild(document.createElement('main')),'full','pptx')
 const draft=new NativeDraft({documentId:'master-elements',revision:1,sourceSha256:deck.sha256,scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}})
 if(initial.length)draft.setOperations(initial as never)
 const request=vi.fn(async(path:string)=>path==='deck'?deck:tree),view=createSlidesEditorView(shell.editor,{native:true,draft,request:request as never,save:shell.save,download:shell.exportPptx});views.push(view);await view.ready
 const open=async()=>{shell.editor.querySelector<HTMLButtonElement>('[data-command=slideMaster]')!.click();await vi.waitFor(()=>expect(shell.editor.querySelector('.slides-master-text-dialog[open]')).not.toBeNull());return shell.editor.querySelector<HTMLDialogElement>('.slides-master-text-dialog')!}
 const add=async()=>{const dialog=await open();expect(dialog.querySelector('[data-master-add-textbox]')).not.toBeNull();dialog.querySelector<HTMLButtonElement>('[data-master-add-textbox]')!.click();return shell.editor.querySelector<HTMLDialogElement>('.slides-master-element-editor')!}
 return{shell,draft,request,open,add}
}
const change=(host:Element,name:string,value:string)=>{const input=host.querySelector<HTMLInputElement|HTMLTextAreaElement>(`[name=${name}]`)!;input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}))}
it('母版新文字框进入同一草稿，可改文字位置尺寸、撤销重做并移除待新增框',async()=>{
 const app=await fixture();let editor=await app.add();change(editor,'text','新品牌 <&>😀\n第二行');change(editor,'x','96');change(editor,'width','400');editor.querySelector<HTMLButtonElement>('[data-master-element-apply]')!.click()
 const first=structuredClone(app.draft.operations),addition=(first[0] as any).masterElementEdits[0];expect(addition).toMatchObject({kind:'addTextBox',text:'新品牌 <&>😀\n第二行',box:{x:96,width:400}})
 await vi.waitFor(()=>expect(app.request).toHaveBeenCalledWith('render-tree',expect.objectContaining({body:expect.stringContaining('masterElementEdits')})))
 let dialog=await app.open();dialog.querySelector<HTMLButtonElement>('[data-master-edit-new]')!.click();editor=app.shell.editor.querySelector<HTMLDialogElement>('.slides-master-element-editor')!;expect(editor.querySelector<HTMLTextAreaElement>('[name=text]')!.value).toBe(addition.text);change(editor,'text','改后品牌');change(editor,'height','120');editor.querySelector<HTMLButtonElement>('[data-master-element-apply]')!.click()
 expect((app.draft.operations[0] as any).masterElementEdits).toEqual([{...addition,text:'改后品牌',box:{...addition.box,height:120}}])
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action=onUndo]')!.click();expect(app.draft.operations).toEqual(first);app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action=onRedo]')!.click();expect((app.draft.operations[0] as any).masterElementEdits[0].text).toBe('改后品牌')
 dialog=await app.open();dialog.querySelector<HTMLButtonElement>('[data-master-remove-new]')!.click();expect((app.draft.operations[0] as any).masterElementEdits).toBeUndefined()
})
it('删除原有文字会清理同对象文字草稿，保留其它部件并可撤销恢复',async()=>{
 const app=await fixture();let dialog=await app.open();dialog.querySelector<HTMLElement>('[data-master-rich-text]')!.textContent='母版改字';dialog.querySelector<HTMLButtonElement>('[data-master-apply]')!.click()
 dialog=await app.open();dialog.querySelector<HTMLButtonElement>('[data-master-part="ppt/slideLayouts/slideLayout1.xml"]')!.click();dialog.querySelector<HTMLElement>('[data-master-rich-text]')!.textContent='版式改字';dialog.querySelector<HTMLButtonElement>('[data-master-apply]')!.click();const before=structuredClone(app.draft.operations)
 dialog=await app.open();expect(dialog.querySelector('[data-master-delete-element]')).not.toBeNull();dialog.querySelector<HTMLButtonElement>('[data-master-delete-element]')!.click()
 expect((app.draft.operations[0] as any).masterElementEdits).toEqual([{kind:'delete',partPath:'ppt/slideMasters/slideMaster1.xml',spid:7}]);expect((app.draft.operations[0] as any).masterTextEdits).toHaveLength(1);expect((app.draft.operations[0] as any).masterTextEdits[0]).toMatchObject({partPath:'ppt/slideLayouts/slideLayout1.xml',spid:7,paragraphs:[{runs:[{text:'版式改字'}]}]})
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action=onUndo]')!.click();expect(app.draft.operations).toEqual(before)
})
it('新框取消、非法尺寸、输入法与过期草稿不会制造结构修改',async()=>{
 const app=await fixture();let editor=await app.add();editor.querySelector<HTMLButtonElement>('[data-master-element-cancel]')!.click();expect(app.draft.operations).toEqual([])
 app.shell.editor.querySelector<HTMLButtonElement>('[data-master-close]')!.click();editor=await app.add();change(editor,'width','0');editor.querySelector<HTMLButtonElement>('[data-master-element-apply]')!.click();expect(app.draft.operations).toEqual([]);expect(editor.textContent).toContain('尺寸')
 change(editor,'width','400');const text=editor.querySelector<HTMLTextAreaElement>('[name=text]')!;text.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));expect(editor.querySelector<HTMLButtonElement>('[data-master-element-apply]')!.disabled).toBe(true);text.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));app.draft.setOperations([{kind:'editSlides',edits:[]}]);editor.querySelector<HTMLButtonElement>('[data-master-element-apply]')!.click();expect((app.draft.operations[0] as any).masterElementEdits).toBeUndefined();expect(editor.textContent).toContain('草稿已变化')
})
it('恢复草稿隐藏已删除对象，同值编辑不写入',async()=>{
 const addition={kind:'addTextBox',partPath:'ppt/slideMasters/slideMaster1.xml',clientId:'restored',text:'恢复品牌',box:{x:48,y:48,width:480,height:96}}
 const initial=[{kind:'editSlides',edits:[],masterElementEdits:[addition,{kind:'delete',partPath:addition.partPath,spid:7}]}],app=await fixture(initial)
 let dialog=await app.open();expect(dialog.querySelector<HTMLSelectElement>('[data-master-element]')!.options.length).toBe(0);dialog.querySelector<HTMLButtonElement>('[data-master-edit-new]')!.click();const editor=app.shell.editor.querySelector<HTMLDialogElement>('.slides-master-element-editor')!;editor.querySelector<HTMLButtonElement>('[data-master-element-apply]')!.click();expect(app.draft.operations).toEqual(initial);expect(editor.isConnected).toBe(false)
})
it('只读部件不允许结构操作',async()=>{
 const app=await fixture([],false),dialog=await app.open();expect(dialog.querySelector<HTMLButtonElement>('[data-master-add-textbox]')!.disabled).toBe(true);expect(dialog.querySelector<HTMLButtonElement>('[data-master-delete-element]')!.disabled).toBe(true)
})
it('既有母版对象几何进入同一草稿且支持撤销重做',async()=>{
 const app=await fixture(),dialog=await app.open();change(dialog,'x','96');change(dialog,'width','400');change(dialog,'rotationDeg','12.5');dialog.querySelector<HTMLButtonElement>('[data-master-transform-apply]')!.click()
 const first=structuredClone(app.draft.operations),transform=(first[0] as any).masterElementEdits[0];expect(transform).toMatchObject({kind:'setTransform',box:{x:96,width:400,rotationDeg:12.5}})
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action=onUndo]')!.click();expect(app.draft.operations).toEqual([])
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action=onRedo]')!.click();expect((app.draft.operations[0] as any).masterElementEdits).toEqual([transform])
})
it('既有母版对象轮廓支持实色和无轮廓并进入同一草稿历史',async()=>{
 const app=await fixture(),dialog=await app.open();change(dialog,'stroke-color','#12ab34');dialog.querySelector<HTMLButtonElement>('[data-master-stroke-apply]')!.click()
 expect((app.draft.operations[0] as any).masterElementEdits).toEqual([{kind:'setStroke',partPath:'ppt/slideMasters/slideMaster1.xml',spid:7,stroke:{color:'#12AB34',widthPt:1}}])
 const second=await app.open();second.querySelector<HTMLButtonElement>('[data-master-stroke-none]')!.click();expect((app.draft.operations[0] as any).masterElementEdits).toBeUndefined()
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action=onUndo]')!.click();expect((app.draft.operations[0] as any).masterElementEdits[0].stroke).toEqual({color:'#12AB34',widthPt:1})
})
it('外层输入法不允许结构操作',async()=>{
 const app=await fixture(),dialog=await app.open();dialog.querySelector<HTMLElement>('[data-master-rich-text]')!.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));dialog.querySelector<HTMLButtonElement>('[data-master-add-textbox]')!.click();expect(app.shell.editor.querySelector('.slides-master-element-editor')).toBeNull();dialog.querySelector<HTMLButtonElement>('[data-master-delete-element]')!.click();expect(app.draft.operations).toEqual([])
})
