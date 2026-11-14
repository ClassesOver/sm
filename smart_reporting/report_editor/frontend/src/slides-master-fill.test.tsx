import React from 'react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {createSlidesEditorView} from './slides-main'
import {createEditorShell} from './shell'
import {NativeDraft} from './native-draft'
import {validateMasterElementDraft} from './slides-master-elements-model'
vi.mock('./slides-canvas',()=>({mountSlidesCanvas:()=>({update(){},destroy(){}})}))
vi.mock('./vendor/genoffice/renderer/SlideThumb',()=>({SlideThumb:()=> <figure data-source-master-thumbnail/>}))
const views:ReturnType<typeof createSlidesEditorView>[]=[]
beforeEach(()=>vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}unobserve(){}}))
afterEach(()=>{views.splice(0).forEach(view=>view.dispose());document.body.replaceChildren();vi.unstubAllGlobals()})
async function fixture(initial:object[]=[],allowFill=true){
 const parts=(['master','layout'] as const).map((kind,index)=>({kind,partPath:`ppt/${index?'slideLayouts/slideLayout':'slideMasters/slideMaster'}1.xml`,name:kind,structureEditable:true,elements:[{spid:7,name:'原品牌',text:'',editable:!index,reason:index?'无正文文字':null,fillEditable:allowFill,fillValue:index?null:'#AABBCC',fillReason:allowFill?null:'源填充不可编辑'}]}))
 const deck={revision:1,sha256:'a'.repeat(64),size:{cx:9144000,cy:6858000},masterTextParts:parts,slides:[{slideIndex:0,elements:[],animations:[]}]},tree={slides:[{slideIndex:0,widthPx:960,heightPx:720,nodes:[]}],masterTextParts:parts.map(part=>({...part,slide:{widthPx:960,heightPx:720,nodes:[]}}))}
 const shell=createEditorShell(document.body.appendChild(document.createElement('main')),'full','pptx'),draft=new NativeDraft({documentId:'master-fill',revision:1,sourceSha256:deck.sha256,scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}});if(initial.length)draft.setOperations(initial as never)
 const request=vi.fn(async(path:string)=>path==='deck'?deck:tree),view=createSlidesEditorView(shell.editor,{native:true,draft,request:request as never,save:shell.save,download:shell.exportPptx});views.push(view);await view.ready
 const open=async(index=0)=>{shell.editor.querySelector<HTMLButtonElement>('[data-command=slideMaster]')!.click();await vi.waitFor(()=>expect(shell.editor.querySelector('.slides-master-text-dialog[open]')).not.toBeNull());const dialog=shell.editor.querySelector<HTMLDialogElement>('.slides-master-text-dialog')!;dialog.querySelector<HTMLButtonElement>(`[data-master-part="${parts[index]!.partPath}"]`)!.click();return dialog}
 return{parts,shell,draft,request,open}
}
const fill=(dialog:Element,value:string)=>{const input=dialog.querySelector<HTMLInputElement>('[data-master-fill-color]')!;input.value=value;dialog.querySelector<HTMLButtonElement>('[data-master-fill-apply]')!.click()}
it('空文字shape按fillEditable填充，同NativeDraft预览并可撤销重做',async()=>{
 const app=await fixture(),dialog=await app.open(1);expect(dialog.querySelector<HTMLTextAreaElement>('[data-master-text]')!.disabled).toBe(true);expect(dialog.querySelector('[data-master-fill-color]')).not.toBeNull();expect(dialog.querySelector('[data-master-fill-status]')!.textContent).toContain('复杂或继承');fill(dialog,'#1a73e8')
 expect((app.draft.operations[0] as any).masterElementEdits).toEqual([{kind:'setFill',partPath:app.parts[1]!.partPath,spid:7,fill:'#1A73E8'}]);await vi.waitFor(()=>expect(app.request).toHaveBeenCalledWith('render-tree',expect.objectContaining({body:expect.stringContaining('setFill')})));expect(app.shell.editor.textContent).toContain('填充 #1A73E8')
 const saved=structuredClone(app.draft.operations);app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action=onUndo]')!.click();expect((app.draft.operations[0] as any)?.masterElementEdits).toBeUndefined();app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action=onRedo]')!.click();expect(app.draft.operations).toEqual(saved)
})
it('同值不写草稿，none与恢复来源颜色共存其它部件，删除会清理同对象填充',async()=>{
 const app=await fixture();let dialog=await app.open();fill(dialog,'#aabbcc');expect(app.draft.operations).toEqual([]);dialog.querySelector<HTMLButtonElement>('[data-master-close]')!.click()
 dialog=await app.open(1);dialog.querySelector<HTMLButtonElement>('[data-master-fill-none]')!.click();const other=structuredClone((app.draft.operations[0] as any).masterElementEdits)
 dialog=await app.open();fill(dialog,'#112233');dialog=await app.open();fill(dialog,'#aabbcc');expect((app.draft.operations[0] as any).masterElementEdits).toEqual(other)
 dialog=await app.open();fill(dialog,'#112233');dialog=await app.open();dialog.querySelector<HTMLButtonElement>('[data-master-delete-element]')!.click();expect((app.draft.operations[0] as any).masterElementEdits).toEqual([...other,{kind:'delete',partPath:app.parts[0]!.partPath,spid:7}])
})
it('恢复填充草稿投影颜色，填充能力不能由textEditable替代',async()=>{
 const edits=[{kind:'setFill',partPath:'ppt/slideMasters/slideMaster1.xml',spid:7,fill:'#123456'}],app=await fixture([{kind:'editSlides',edits:[],masterElementEdits:edits}]),dialog=await app.open();expect(dialog.querySelector<HTMLInputElement>('[data-master-fill-color]')!.value).toBe('#123456');expect(dialog.querySelector('[data-master-fill-status]')!.textContent).toContain('草稿');expect(()=>validateMasterElementDraft(edits,app.parts.map(part=>({...part,elements:part.elements.map(el=>({...el,editable:true,fillEditable:false}))})) as never)).toThrow()
})
it('fillEditable=false不能因文字可写而开启填充',async()=>{
 const app=await fixture([],false),dialog=await app.open();expect(dialog.querySelector<HTMLButtonElement>('[data-master-fill-apply]')!.disabled).toBe(true);expect(dialog.querySelector<HTMLButtonElement>('[data-master-fill-none]')!.disabled).toBe(true)
})
it('填充提交检查输入法与来源草稿快照',async()=>{
 const app=await fixture(),dialog=await app.open(),text=dialog.querySelector<HTMLTextAreaElement>('[data-master-text]')!;text.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));fill(dialog,'#112233');expect(app.draft.operations).toEqual([]);text.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));app.draft.setOperations([{kind:'editSlides',edits:[]}]);dialog.querySelector<HTMLButtonElement>('[data-master-fill-none]')!.click();expect((app.draft.operations[0] as any).masterElementEdits).toBeUndefined();expect(dialog.textContent).toContain('草稿已变化')
})

it('重复采纳已有填充不改事务顺序或写新历史',async()=>{
 const edits=[{kind:'setFill',partPath:'ppt/slideMasters/slideMaster1.xml',spid:7,fill:'#123456'},{kind:'setFill',partPath:'ppt/slideLayouts/slideLayout1.xml',spid:7,fill:'none'}],initial=[{kind:'editSlides',edits:[],masterElementEdits:edits}],app=await fixture(initial),dialog=await app.open();fill(dialog,'#123456');expect(app.draft.operations).toEqual(initial);expect(dialog.isConnected).toBe(true)
})

it('填充颜色严格拒绝末尾换行',()=>{
 const parts=[{kind:'master' as const,partPath:'ppt/slideMasters/slideMaster1.xml',name:'master',structureEditable:true,elements:[{spid:7,name:'shape',text:'',editable:false,reason:null,fillEditable:true}]}];for(const fill of ['#123456\n','none\n'])expect(()=>validateMasterElementDraft([{kind:'setFill',partPath:parts[0]!.partPath,spid:7,fill}],parts)).toThrow()
})
