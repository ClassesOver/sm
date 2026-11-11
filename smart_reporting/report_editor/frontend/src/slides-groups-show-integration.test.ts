import { afterEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'
import { NativeDraft } from './native-draft'
const show=vi.hoisted(()=>({open:vi.fn(()=>({dispose:vi.fn()})),canvas:undefined as any}))
vi.mock('./slides-show',()=>({openSlidesShow:show.open}))
vi.mock('./slides-canvas',()=>({mountSlidesCanvas:()=>({update(state:any){show.canvas=state},destroy(){}})}))
const views:ReturnType<typeof createSlidesEditorView>[]=[]
afterEach(()=>{views.splice(0).forEach(view=>view.dispose());document.body.replaceChildren();show.open.mockClear();show.canvas=undefined})
const source={revision:1,sha256:'a'.repeat(64),size:{cx:9144000,cy:5143500},slides:[{slideIndex:0,elements:[{id:'a',type:'text',name:'甲',text:'甲',editable:true,deletable:true,groupEditable:true},{id:'b',type:'shape',name:'乙',text:'乙',editable:true,deletable:true,groupEditable:true},{id:'g',type:'group',name:'来源组合',text:'',editable:false,ungroupEditable:true}]},{slideIndex:1,elements:[{id:'other',type:'text',name:'另一页',text:'另一页',editable:true,deletable:true}]},{slideIndex:2,hidden:true,elements:[]}]}
async function open(operations:any[]=[],tree?:()=>Promise<unknown>){
 const draft=new NativeDraft({documentId:'groups-show',revision:1,sourceSha256:source.sha256,scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}})
 if(operations.length)draft.setOperations(operations)
 const shell=createEditorShell(document.body.appendChild(document.createElement('main')),'full','pptx')
 const request=vi.fn(async(path:string,init?:RequestInit)=>path==='deck'?source:path==='render-tree'?(tree?tree():{slides:source.slides.map(s=>({slideIndex:s.slideIndex,widthPx:960,heightPx:540,hidden:s.hidden,nodes:[]}))}):{revision:2,revisionRegistered:true,validation:{issues:[]}})
 const view=createSlidesEditorView(shell.editor,{native:true,draft,request:request as any,save:shell.save,download:shell.exportPptx});views.push(view);await view.ready
 await vi.waitFor(()=>expect(show.canvas).toBeDefined())
 const command=(id:string)=>shell.editor.querySelector<HTMLButtonElement>(`[data-command="${id}"]`)!
 return{view,draft,shell,request,command}
}
it('组合单次历史、同页编辑受保护、撤回后可继续输入和保存',async()=>{
 const app=await open();app.shell.editor.querySelector<HTMLInputElement>('[data-arrange-object="b"]')!.click()
 expect(app.command('groupObjects')).not.toBeNull();app.command('groupObjects').click()
 expect(app.draft.operations[0]?.groupEdits).toEqual([{slideIndex:0,kind:'group',elementIds:['a','b']}])
 const select=app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!;select.value='a';select.dispatchEvent(new Event('change',{bubbles:true}))
 const before=structuredClone(app.draft.operations),input=app.shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!
 expect(input.disabled).toBe(true)
 show.canvas.onGeometry('a',{x:1,y:1,width:100,height:100});expect(app.draft.operations).toEqual(before)
 input.value='不应覆盖';input.dispatchEvent(new Event('input',{bubbles:true}));expect(app.draft.operations).toEqual(before)
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click();expect(app.draft.operations).toEqual([])
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click();expect(app.draft.operations).toEqual(before)
 app.shell.save.click();await vi.waitFor(()=>expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(true))
 expect(JSON.parse(app.request.mock.calls.find(([path])=>path==='save')![1]!.body as string).operations[0].groupEdits).toEqual(before[0]?.groupEdits)
})
it('来源组可选择并取消组合',async()=>{
 const app=await open();const select=app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!;select.value='g';select.dispatchEvent(new Event('change',{bubbles:true}))
 app.command('ungroupObjects').click();expect(app.draft.operations[0]?.groupEdits).toEqual([{slideIndex:0,kind:'ungroup',elementId:'g'}])
})
it('放映使用完整草稿快照及真实顺序，隐藏页跳过且不修改草稿或保存',async()=>{
 const operations=[{kind:'editSlides',order:[1,0,2],edits:[{slideIndex:0,elementId:'a',text:'保留草稿'}]}]
 const app=await open(operations,async()=>({slides:[{slideIndex:0,widthPx:960,heightPx:540,nodes:[]},{slideIndex:1,widthPx:960,heightPx:540,nodes:[]},{slideIndex:2,hidden:true,widthPx:960,heightPx:540,nodes:[]}]}))
 const before=structuredClone(app.draft.operations);app.command('startShowCurrent').click();await vi.waitFor(()=>expect(show.open).toHaveBeenCalledOnce())
 const options=(show.open.mock.calls[0] as any[])[1];expect(options.slides).toHaveLength(2);expect(options.startIndex).toBe(1)
 expect(app.draft.operations).toEqual(before);expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(false)
 const request=app.request.mock.calls.filter(([path,init])=>path==='render-tree'&&init).at(-1)!
 expect(JSON.parse(request[1]!.body as string).operations).toEqual(before)
})

it('恢复组合草稿时先拒绝同页混合编辑',async()=>{
 await expect(open([{kind:'editSlides',groupEdits:[{slideIndex:0,kind:'group',elementIds:['a','b']}],edits:[{slideIndex:0,elementId:'a',text:'冲突'}]}])).rejects.toThrow('不能与同页其他修改')
})
it('放映异步响应到达时拒绝已变化的完整草稿',async()=>{
 let resolveTree!:(value:unknown)=>void,calls=0
 const tree={slides:[{slideIndex:0,widthPx:960,heightPx:540,nodes:[]}]}
 const app=await open([],()=>++calls===1?Promise.resolve(tree):new Promise(resolve=>{resolveTree=resolve}))
 app.command('startShow').click()
 await vi.waitFor(()=>expect(resolveTree).toBeDefined())
 app.draft.setOperations([{kind:'editSlides',edits:[{slideIndex:0,elementId:'a',text:'新草稿'}]}])
 const before=structuredClone(app.draft.operations);resolveTree(tree)
 await vi.waitFor(()=>expect(app.shell.editor.querySelector('.status-message')!.textContent).toContain('页面或草稿已变化'))
 expect(show.open).not.toHaveBeenCalled();expect(app.draft.operations).toEqual(before)
 expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(false)
})
