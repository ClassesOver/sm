import {afterEach,expect,it,vi} from 'vitest'
import {createEditorShell} from './shell'
import {createSlidesEditorView} from './slides-main'
import {NativeDraft} from './native-draft'
const canvas=vi.hoisted(()=>({state:undefined as any,updates:0}))
vi.mock('./slides-canvas',()=>({mountSlidesCanvas:()=>({update(state:any){canvas.state=state;canvas.updates++},destroy(){}})}))
const views:ReturnType<typeof createSlidesEditorView>[]=[]
afterEach(()=>{views.splice(0).forEach(v=>v.dispose());document.body.replaceChildren();canvas.state=undefined;canvas.updates=0})
const source={revision:1,sha256:'b'.repeat(64),size:{cx:9144000,cy:5143500},slides:[{slideIndex:0,notesText:'原备注',notesEditable:true,notesReason:null,elements:[{id:'a',type:'text',name:'甲',text:'正文甲',editable:true,geometry:{x:10,y:10,width:100,height:50}}]},{slideIndex:1,notesText:'',notesEditable:true,notesReason:null,elements:[]}]}
async function open(operations:any[]=[]){
 const draft=new NativeDraft({documentId:'notes',revision:1,sourceSha256:source.sha256,scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}})
 if(operations.length)draft.setOperations(operations)
 const shell=createEditorShell(document.body.appendChild(document.createElement('main')),'full','pptx')
 const request=vi.fn(async(path:string)=>path==='deck'?source:path==='render-tree'?{slides:source.slides.map(s=>({slideIndex:s.slideIndex,widthPx:960,heightPx:540,nodes:[]}))}:{revision:2,revisionRegistered:true,validation:{issues:[]}})
 const view=createSlidesEditorView(shell.editor,{native:true,draft,request:request as any,save:shell.save,download:shell.exportPptx});views.push(view);await view.ready;await vi.waitFor(()=>expect(canvas.state).toBeDefined())
 const text=()=>shell.editor.querySelector<HTMLTextAreaElement>('[data-notes-text]')!
 const type=(value:string)=>{text().value=value;text().dispatchEvent(new Event('input',{bubbles:true}))}
 const history=(direction:string)=>shell.editor.querySelector<HTMLButtonElement>('[data-source-action="'+direction+'"]')!.click()
 return {shell,draft,request,view,text,type,history}
}
it('备注输入立即进入草稿且不修改正文或重复预览',async()=>{
 const app=await open();expect(app.text()?.value).toBe('原备注');const before=canvas.updates
 app.type('新备注\n\n😀 $& & < >');expect(app.draft.operations[0]?.notesEdits).toEqual([{slideIndex:0,text:'新备注\n\n😀 $& & < >'}])
 expect(app.draft.operations[0]?.edits).toEqual([]);expect(canvas.updates).toBe(before)
})
it('不失焦换页与保存保留两页备注来源',async()=>{
 const app=await open();app.type('零号备注');app.shell.editor.querySelector<HTMLButtonElement>('.slide-open[data-slide-index="1"]')!.click();expect(app.text().value).toBe('')
 app.type('一号备注');app.shell.save.click();await vi.waitFor(()=>expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(true))
 const call=app.request.mock.calls.find(([path])=>path==='save') as any
 const payload=JSON.parse(call[1].body);expect(payload.operations[0].notesEdits).toEqual([{slideIndex:0,text:'零号备注'},{slideIndex:1,text:'一号备注'}])
})
it('备注一次输入可撤销重做且相同输入不增加历史',async()=>{
 const app=await open();app.type('原备注');expect(app.draft.operations).toEqual([]);app.type('新备注');app.type('新备注');app.history('onUndo');expect(app.text().value).toBe('原备注');expect(app.draft.operations).toEqual([])
 app.history('onRedo');expect(app.text().value).toBe('新备注')
})
it('备注草稿恢复与重排不覆盖已有正文操作',async()=>{
 const operations=[{kind:'editSlides',order:[1,0],edits:[{slideIndex:0,elementId:'a',text:'已有正文'}],notesEdits:[{slideIndex:0,text:'恢复备注'}]}]
 const app=await open(operations);expect(app.draft.operations).toEqual(operations);expect(app.text().value).toBe('恢复备注')
 app.type('继续备注');expect(app.draft.operations[0]?.edits).toEqual(operations[0]!.edits)
})
it('输入法尚未完成时禁止切页及保存，完成后仍绑定原页',async()=>{
 const app=await open();app.text().dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));app.type('输入中')
 app.shell.editor.querySelector<HTMLButtonElement>('.slide-open[data-slide-index="1"]')!.click();expect(app.text().value).toBe('输入中');expect(app.draft.operations).toEqual([])
 app.shell.save.click();expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(false)
 app.text().dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));expect(app.draft.operations[0]?.notesEdits).toEqual([{slideIndex:0,text:'输入中'}])
})
it('备注显示开关不制造历史或丢失草稿',async()=>{
 const app=await open();const control=app.shell.editor.querySelector<HTMLButtonElement>('[data-command="notes"]')!;expect(control.disabled).toBe(false)
 app.type('保持');const before=structuredClone(app.draft.operations);control.click();expect(app.shell.editor.querySelector<HTMLElement>('[data-notes-panel]')!.hidden).toBe(true);control.click();expect(app.text().value).toBe('保持');expect(app.draft.operations).toEqual(before)
})
it.each(['复制幻灯片','删除幻灯片'])('输入法未完成时缩略图%s不改来源和页面结构',async label=>{
 const app=await open();app.text().dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));app.type('原页输入中')
 app.shell.editor.querySelector('.slide-open[data-slide-index="1"]')!.closest('.slide-row')!.querySelector<HTMLButtonElement>('[aria-label="'+label+'"]')!.click()
 expect(app.draft.operations).toEqual([]);expect(app.shell.editor.querySelectorAll('.slide-row')).toHaveLength(2)
 app.text().dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));expect(app.draft.operations[0]?.notesEdits).toEqual([{slideIndex:0,text:'原页输入中'}])
})
it('输入法未完成时移除新建页不改变既有草稿',async()=>{
 const app=await open();app.shell.editor.querySelector<HTMLButtonElement>('[data-command="addSlide"]')!.click();app.shell.editor.querySelector<HTMLButtonElement>('.slide-open[data-slide-index="0"]')!.click()
 const before=structuredClone(app.draft.operations);app.text().dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));app.type('原页输入中')
 app.shell.editor.querySelector<HTMLButtonElement>('[aria-label="移除新建的幻灯片"]')!.click();expect(app.draft.operations).toEqual(before);expect(app.shell.editor.querySelectorAll('.slide-row')).toHaveLength(3)
 app.text().dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));expect(app.draft.operations[0]?.notesEdits).toEqual([{slideIndex:0,text:'原页输入中'}])
})
it('带尾换行备注撤回后恢复来源文本且清除草稿',async()=>{
 const app=await open();app.type('新备注\n');
 const row=Array.from(app.shell.editor.querySelectorAll('li')).find(item=>item.textContent?.includes('演讲者备注'))!
 row.querySelector<HTMLButtonElement>('[aria-label="撤销此项修改"]')!.click()
 expect(app.text().value).toBe('原备注');expect(app.draft.operations[0]?.notesEdits??[]).toEqual([])
})
it('输入法未完成时禁止读取不完整备注上下文',async()=>{
 const app=await open();app.text().dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));app.type('读取输入中')
 await expect(app.view.officeReadContext('document')).rejects.toThrow('备注')
})
it('重排后待保存备注显示当前页面序号',async()=>{
 const app=await open();app.type('待保存备注')
 app.shell.editor.querySelector('.slide-open[data-slide-index="1"]')!.closest('.slide-row')!.querySelector<HTMLButtonElement>('[aria-label="上移页面"]')!.click()
 const row=Array.from(app.shell.editor.querySelectorAll('li')).find(item=>item.textContent?.includes('演讲者备注'))!
 expect(row.textContent).toContain('第 2 页')
})
