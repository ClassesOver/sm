import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {createEditorShell} from './shell'
import {createSlidesEditorView} from './slides-main'
import {NativeDraft} from './native-draft'
const canvas=vi.hoisted(()=>({state:undefined as any}))
vi.mock('./slides-canvas',()=>({mountSlidesCanvas:()=>({update(state:any){canvas.state=state},destroy(){}})}))
const views:ReturnType<typeof createSlidesEditorView>[]=[]
beforeEach(()=>vi.stubGlobal('ResizeObserver',class{observe(){}unobserve(){}disconnect(){}}))
afterEach(()=>{views.splice(0).forEach(v=>v.dispose());document.body.replaceChildren();canvas.state=undefined;vi.unstubAllGlobals()})
const source={revision:1,sha256:'a'.repeat(64),size:{cx:9144000,cy:5143500},slides:[{slideIndex:0,elements:[{id:'a',name:'甲',type:'text',text:'甲正文',editable:true,deletable:true,clipboardEditable:true,linkEditable:true,elementLink:null,brushSource:{supported:true,text:{bold:true,color:'#123456'},align:'center'},geometry:{x:10,y:10,width:100,height:50}},{id:'b',name:'乙',type:'shape',text:'乙正文',editable:true,deletable:true,clipboardEditable:true,linkEditable:true,elementLink:null,brushSource:{supported:true,text:{bold:false,color:'#654321'},align:'left'},geometry:{x:150,y:10,width:100,height:50}}]},{slideIndex:1,elements:[]}]}
async function open(operations:any[]=[]){
 const draft=new NativeDraft({documentId:'clipboard-links',revision:1,sourceSha256:source.sha256,scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}})
 if(operations.length)draft.setOperations(operations)
 const shell=createEditorShell(document.body.appendChild(document.createElement('main')),'full','pptx')
 const request=vi.fn(async(path:string)=>path==='deck'?source:path==='render-tree'?{slides:source.slides.map(s=>({slideIndex:s.slideIndex,widthPx:960,heightPx:540,nodes:[]}))}:{revision:2,revisionRegistered:true,validation:{issues:[]}})
 const view=createSlidesEditorView(shell.editor,{native:true,draft,request:request as any,save:shell.save,download:shell.exportPptx});views.push(view);await view.ready;await vi.waitFor(()=>expect(canvas.state).toBeDefined())
 const command=(id:string)=>shell.editor.querySelector<HTMLButtonElement>('[data-command="'+id+'"]')!
 return{shell,draft,view,request,command}
}
it('复制不落历史，粘贴来源引用一次提交并可撤销重做',async()=>{
 const app=await open();app.command('copy').click();expect(app.draft.operations).toEqual([]);app.command('paste').click()
 expect(app.draft.operations[0]?.clipboardPastes).toEqual([{sourceSlideIndex:0,elementIds:['a'],slideIndex:0,dx:20,dy:20}])
 const before=structuredClone(app.draft.operations)
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click();expect(app.draft.operations).toEqual([])
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click();expect(app.draft.operations).toEqual(before)
})
it.each([false,true])('画布选择接管焦点后支持对象复制粘贴，框选=%s',async multiple=>{
 const app=await open(),host=app.shell.editor.querySelector<HTMLElement>('.slides-canvas')!
 const input=app.shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!;input.focus()
 if(multiple)canvas.state.onSelectMany(['a','b']);else canvas.state.onSelect('a')
 expect(document.activeElement).toBe(host)
 for(const key of ['c','v'])host.dispatchEvent(new KeyboardEvent('keydown',{key,ctrlKey:true,bubbles:true,cancelable:true}))
 expect(app.draft.operations[0]?.clipboardPastes).toEqual([{sourceSlideIndex:0,elementIds:multiple?['a','b']:['a'],slideIndex:0,dx:20,dy:20}])
})
it.each(['c','x','v'])('目标已消费的%s快捷键不触发对象剪贴板',async key=>{
 const app=await open(),host=app.shell.editor.querySelector<HTMLElement>('.slides-canvas')!
 app.command('copy').click();canvas.state.onSelect('a')
 const status=app.shell.editor.querySelector<HTMLElement>('.status-message')!;status.textContent='目标控件正在处理快捷键'
 let consumed=false;host.addEventListener('keydown',event=>{consumed=true;event.preventDefault()},{once:true})
 host.dispatchEvent(new KeyboardEvent('keydown',{key,ctrlKey:true,bubbles:true,cancelable:true}))
 expect(consumed).toBe(true);expect(app.draft.operations).toEqual([]);expect(status.textContent).toBe('目标控件正在处理快捷键')
})
it.each([{isComposing:true},{keyCode:229}])('组合输入标记%s不触发对象剪贴板',async marker=>{
 const app=await open(),host=app.shell.editor.querySelector<HTMLElement>('.slides-canvas')!
 app.command('copy').click();canvas.state.onSelect('a')
 for(const key of ['c','x','v']){
  const event=new KeyboardEvent('keydown',{key,ctrlKey:true,...marker,bubbles:true,cancelable:true});host.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(false);expect(app.draft.operations).toEqual([])
 }
})
it('文字输入框Escape保留格式刷，由画布Escape退出',async()=>{
 const app=await open();app.command('formatBrush').click()
 const input=app.shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!;input.focus()
 const event=new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true});input.dispatchEvent(event)
 expect(event.defaultPrevented).toBe(false);expect(app.command('formatBrush').getAttribute('aria-pressed')).toBe('true')
 canvas.state.onSelect('');const host=app.shell.editor.querySelector<HTMLElement>('.slides-canvas')!
 host.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}))
 expect(app.command('formatBrush').getAttribute('aria-pressed')).toBe('false')
})
it('剪切用已有删除草稿，粘贴仍引用保存来源并可刷新恢复',async()=>{
 const app=await open();app.command('cut').click();expect(app.draft.operations[0]?.deletions).toEqual([{slideIndex:0,elementId:'a'}]);app.command('paste').click()
 const before=structuredClone(app.draft.operations);expect(before[0]?.clipboardPastes).toHaveLength(1)
 app.view.dispose();views.splice(views.indexOf(app.view),1);document.body.replaceChildren()
 const recovered=await open(before);expect(recovered.draft.operations).toEqual(before)
})
it('格式刷保留目标正文且文字/段落一次历史，once应用后退出',async()=>{
 const app=await open();app.command('formatBrush').click();expect(app.draft.operations).toEqual([]);canvas.state.onSelect('b')
 expect(app.draft.operations[0]?.textFormatting).toContainEqual({slideIndex:0,elementId:'b',bold:true,color:'#123456'})
 expect(app.draft.operations[0]?.paragraphFormatting).toContainEqual({slideIndex:0,elementId:'b',align:'center'})
 expect(app.draft.operations[0]?.edits).toEqual([])
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click();expect(app.draft.operations).toEqual([])
})
it('恢复链接与粘贴字段时不覆盖已有来源草稿',async()=>{
 const operations=[{kind:'editSlides',order:[1,0],linkEdits:[{slideIndex:0,elementId:'a',target:{kind:'slide',slideIndex:1}}],clipboardPastes:[{sourceSlideIndex:0,elementIds:['b'],slideIndex:1,dx:20,dy:20}]}]
 const app=await open(operations);expect(app.draft.operations).toEqual(operations)
 app.shell.save.click();await vi.waitFor(()=>expect(app.request.mock.calls.some(([path])=>path==='save')).toBe(true))
})
it('持续格式刷重复目标不增加历史，Esc退出',async()=>{
 const app=await open();app.command('formatBrush').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));canvas.state.onSelect('b')
 const before=structuredClone(app.draft.operations);expect(before[0]?.textFormatting).toHaveLength(1)
 expect(app.command('formatBrush').getAttribute('aria-pressed')).toBe('true')
 canvas.state.onSelect('b');expect(app.draft.operations).toEqual(before)
 app.command('formatBrush').focus();window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}))
 expect(app.command('formatBrush').getAttribute('aria-pressed')).toBe('false')
 canvas.state.onSelect('b');expect(app.draft.operations).toEqual(before)
})
it('格式刷同源无变化不提交历史',async()=>{
 const app=await open();app.command('formatBrush').click();canvas.state.onSelect('a');expect(app.draft.operations).toEqual([])
 expect(app.command('formatBrush').getAttribute('aria-pressed')).toBe('false')
})
it('超链接对话框提交与移除各一次历史，可撤销重做',async()=>{
 const app=await open();app.command('insertLink').click()
 const url=app.shell.editor.querySelector<HTMLInputElement>('[data-link-url]')!;url.value='https://example.com/a?q=$&b=1'
 app.shell.editor.querySelector<HTMLButtonElement>('[data-link-confirm]')!.click()
 const linked=structuredClone(app.draft.operations)
 expect(linked[0]?.linkEdits).toEqual([{slideIndex:0,elementId:'a',target:{kind:'url',url:'https://example.com/a?q=$&b=1'}}])
 app.command('insertLink').click();app.shell.editor.querySelector<HTMLButtonElement>('[data-link-remove]')!.click()
 expect(app.draft.operations[0]?.linkEdits).toEqual([{slideIndex:0,elementId:'a',target:null}])
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click();expect(app.draft.operations).toEqual(linked)
 app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click();expect(app.draft.operations).toEqual([expect.objectContaining({linkEdits:[expect.objectContaining({target:null})]})])
})
it('超链接对话框拒绝已变化对象，保留对话框和草稿',async()=>{
 const app=await open();app.command('insertLink').click();canvas.state.onSelect('b')
 app.shell.editor.querySelector<HTMLInputElement>('[data-link-url]')!.value='https://example.com'
 app.shell.editor.querySelector<HTMLButtonElement>('[data-link-confirm]')!.click()
 expect(app.draft.operations).toEqual([]);expect(app.shell.editor.querySelector('.slides-native-link-dialog [role="alert"]')?.textContent).toContain('已变化')
 expect(app.shell.editor.querySelector('[data-link-url]')).toBeTruthy()
})
it('来源页有未保存编辑时禁用复制，输入框快捷键不被劫持',async()=>{
 const app=await open([{kind:'editSlides',order:[0,1],edits:[{slideIndex:0,elementId:'a',text:'新正文'}]}])
 expect(app.command('copy').disabled).toBe(true)
 const input=document.createElement('input');app.shell.editor.append(input);input.focus()
 const event=new KeyboardEvent('keydown',{key:'c',ctrlKey:true,bubbles:true,cancelable:true});input.dispatchEvent(event)
 expect(event.defaultPrevented).toBe(false);expect(app.draft.operations).toEqual([expect.objectContaining({edits:[expect.objectContaining({text:'新正文'})]})])
})
it('已有来源链接直接确定不产生草稿历史',async()=>{
 const element=source.slides[0]!.elements[0]!,before=element.elementLink
 Object.assign(element,{elementLink:{kind:'url',url:'https://example.com/'}})
 try{
  const app=await open();app.command('insertLink').click()
  app.shell.editor.querySelector<HTMLButtonElement>('[data-link-confirm]')!.click()
  expect(app.draft.operations).toEqual([]);expect(app.draft.canUndo).toBe(false)
 }finally{element.elementLink=before}
})
it('非原生模式不吞掉浏览器复制快捷键',async()=>{
 const shell=createEditorShell(document.body.appendChild(document.createElement('main')),'full','pptx')
 const request=vi.fn(async(path:string)=>path==='deck'?source:{slides:source.slides.map(s=>({slideIndex:s.slideIndex,widthPx:960,heightPx:540,nodes:[]}))})
 const view=createSlidesEditorView(shell.editor,{request:request as any,save:shell.save,download:shell.exportPptx});views.push(view);await view.ready
 const focus=document.createElement('button');shell.editor.append(focus);focus.focus()
 const event=new KeyboardEvent('keydown',{key:'c',ctrlKey:true,bubbles:true,cancelable:true});focus.dispatchEvent(event)
 expect(event.defaultPrevented).toBe(false)
})
