import {afterEach,expect,it,vi} from 'vitest'
import {Editor,Node} from '@tiptap/core'
import {UndoRedo} from '@tiptap/extensions'
import {NativeDraft} from './native-draft'
import {createDocxCommentCreationControls,normalizeDocxCommentCreation,replayDocxCommentCreation,selectedDocxCommentRanges,type DocxCommentCreationModel} from './docx-comment-create'
const sha='a'.repeat(64),sourceId='b'.repeat(64),targetId='c'.repeat(64)
const model:DocxCommentCreationModel={sourceSha256:sha,sourceId,readOnlyReason:null,targets:[{targetId,blockIndex:0,paragraphOrdinal:0,expectedParagraphSha256:'d'.repeat(64),text:'Alpha 😀 Beta Gamma',readOnlyReason:null}]}
const disposals:(()=>void)[]=[]
afterEach(()=>{disposals.splice(0).forEach(f=>f());document.body.replaceChildren()})
function fixture(currentModel=model){
 const model=currentModel
 const root=document.body.appendChild(document.createElement('div')),errors:unknown[]=[],storage=new Map<string,string>()
 const draft=new NativeDraft({documentId:'new-comment',revision:1,sourceSha256:sha,scope:{database:'db',companyId:'co',userId:'u',threadId:'t'}},{getItem:k=>storage.get(k)??null,setItem:(k,v)=>{storage.set(k,v)},removeItem:k=>{storage.delete(k)}})
 const Doc=Node.create({name:'doc',topNode:true,content:'block+',addAttributes:()=>({nativeCommentCreationOperations:{default:null}})})
 const Paragraph=Node.create({name:'docParagraph',group:'block',content:'inline*',addAttributes:()=>({docxIndex:{default:0}}),renderHTML:()=>['p',0]})
 const Text=Node.create({name:'text',group:'inline'})
 const editor=new Editor({element:root.appendChild(document.createElement('div')),extensions:[Doc,Paragraph,Text,UndoRedo],content:{type:'doc',content:model.targets.map(t=>({type:'docParagraph',attrs:{docxIndex:t.blockIndex},...(t.text?{content:[{type:'text',text:t.text}]}:{})}))}})
 const baseline=editor.getJSON(),collect=(doc:any)=>normalizeDocxCommentCreation(baseline,doc,model).operations
 editor.on('update',()=>draft.setOperations(collect(editor.getJSON())))
 const controls=createDocxCommentCreationControls({editor,container:root,model,collectOperations:collect,readOnlyReason:()=>null,onError:e=>errors.push(e),clientId:()=> 'new-thread-1',now:()=>new Date('2026-11-11T01:02:03Z')})
 disposals.push(()=>{controls.dispose();editor.destroy()});return{root,editor,controls,draft,baseline,errors}
}
it('captures exact selection, cancel leaves draft empty and unblurred save joins undo redo and recovery',()=>{
 const f=fixture();f.editor.commands.setTextSelection({from:7,to:14});f.controls.openNew()
 const input=f.root.querySelector<HTMLTextAreaElement>('[data-new-comment-text]')!
 input.value='取消的输入';input.dispatchEvent(new Event('input',{bubbles:true}));f.root.querySelector<HTMLButtonElement>('[data-new-comment-cancel]')!.click();expect(f.draft.operations).toEqual([])
 f.controls.openNew();input.value='精确新批注😀';input.dispatchEvent(new Event('input',{bubbles:true}));expect(f.draft.operations).toEqual([])
 f.controls.flush();expect(f.draft.operations[0]).toMatchObject({kind:'createComment',sourceId,text:'精确新批注😀',date:'2026-11-11T01:02:03Z',ranges:[{targetId,from:6,to:13,text:'😀 Beta'}]})
 expect(f.editor.state.doc.textContent).toBe(model.targets[0].text)
 f.editor.commands.undo();expect(f.draft.operations).toEqual([]);f.editor.commands.redo();expect(f.draft.operations).toHaveLength(1)
 const restored=replayDocxCommentCreation(f.baseline,f.draft.operations,model);expect(normalizeDocxCommentCreation(f.baseline,restored,model).operations).toEqual(f.draft.operations)
 expect(()=>replayDocxCommentCreation(f.baseline,[{...f.draft.operations[0],sourceId:'f'.repeat(64)}],model)).toThrow();expect(f.errors).toEqual([])
})
it('collapsed caret selects source word and stale composer input is retained for recovery',()=>{
 const f=fixture();f.editor.commands.setTextSelection(3);f.controls.openNew()
 expect(f.root.querySelector('[data-new-comment-selection]')!.textContent).toBe('Alpha')
 const input=f.root.querySelector<HTMLTextAreaElement>('[data-new-comment-text]')!;input.value='保留';input.dispatchEvent(new Event('input',{bubbles:true}))
 f.editor.commands.insertContent('changed');expect(()=>f.controls.flush()).toThrow();expect(input.value).toBe('保留');expect(f.draft.operations).toEqual([])
})

it('keeps ordinary empty paragraphs inside a precise cross paragraph selection',()=>{
 const extended={...model,targets:[model.targets[0],{...model.targets[0],targetId:'e'.repeat(64),blockIndex:1,text:''},{...model.targets[0],targetId:'f'.repeat(64),blockIndex:2,text:'Second'}]}
 const f=fixture(extended);f.editor.commands.setTextSelection({from:3,to:27})
 expect(selectedDocxCommentRanges(f.editor,extended).map(r=>({from:r.from,to:r.to,text:r.text}))).toEqual([{from:2,to:19,text:'pha 😀 Beta Gamma'},{from:0,to:0,text:''},{from:0,to:3,text:'Sec'}])
})

it('新建批注以命名预览和待保存列表分组，不改原始选区和输入',()=>{
 const f=fixture();f.editor.commands.setTextSelection({from:7,to:14});f.controls.openNew()
 expect(f.root.querySelector('.docx-comment-create header h2')?.textContent).toBe('新建批注')
 const preview=f.root.querySelector<HTMLElement>('[data-new-comment-selection]')!
 expect(preview.getAttribute('role')).toBe('region');expect(preview.getAttribute('aria-label')).toBe('所选文字');expect(preview.tabIndex).toBe(0)
 expect(preview.textContent).toBe('😀 Beta')
 const list=f.root.querySelector<HTMLElement>('[data-new-comment-list]')!
 expect(list.getAttribute('aria-label')).toBe('待保存的新批注');expect(list.hidden).toBe(true)
 expect(f.root.querySelector<HTMLElement>('[data-new-comment-empty]')?.hidden).toBe(false)
 expect(f.draft.operations).toEqual([])
})

it.each(['[data-new-comment-cancel]','[aria-label="取消并关闭新建批注"]'])('取消入口 %s 只丢弃当前输入并返回入口，保留已提交草稿',selector=>{
 const f=fixture();f.editor.commands.setTextSelection({from:7,to:14});f.controls.openNew()
 const input=f.root.querySelector<HTMLTextAreaElement>('[data-new-comment-text]')!
 input.value='已加入草稿';f.controls.flush();const before=structuredClone(f.draft.operations)
 const opener=f.root.appendChild(document.createElement('button'));opener.focus();f.controls.openNew();input.value='取消的输入'
 f.root.querySelector<HTMLButtonElement>(selector)!.click()
 expect(f.root.querySelector<HTMLElement>('.docx-comment-create')!.hidden).toBe(true);expect(input.value).toBe('')
 expect(f.controls.hasPendingInput).toBe(false);expect(f.draft.operations).toEqual(before);expect(document.activeElement).toBe(opener)
})

it('草稿行分离作者时间与多行内容，列表清空时恢复输入焦点，外部焦点不被刷新抢走',()=>{
 const f=fixture();f.editor.commands.setTextSelection({from:7,to:14});f.controls.openNew()
 const input=f.root.querySelector<HTMLTextAreaElement>('[data-new-comment-text]')!,value='长批注'.repeat(80)+'\n第二行😀'
 input.value=value;f.controls.flush()
 const list=f.root.querySelector<HTMLElement>('[data-new-comment-list]')!
 expect(list.hidden).toBe(false);expect(list.querySelector('li p')?.textContent).toBe(value)
 expect(list.querySelector('time')?.getAttribute('datetime')).toBe('2026-11-11T01:02:03Z')
 expect(f.root.querySelector<HTMLElement>('[data-new-comment-empty]')?.hidden).toBe(true)
 list.focus();expect(document.activeElement).toBe(list);f.editor.commands.undo()
 expect(list.hidden).toBe(true);expect(document.activeElement).toBe(input)
 const outside=f.root.appendChild(document.createElement('button'));outside.focus();f.editor.commands.redo()
 expect(document.activeElement).toBe(outside);expect(list.hidden).toBe(false)
})

it('锁定时保持取消入口可用，且不能提交或丢失输入',()=>{
 const f=fixture();f.editor.commands.setTextSelection({from:7,to:14});f.controls.openNew()
 const input=f.root.querySelector<HTMLTextAreaElement>('[data-new-comment-text]')!;input.value='锁定时保留'
 f.editor.setEditable(false);f.controls.refresh()
 expect(input.disabled).toBe(true);expect(f.root.querySelector<HTMLButtonElement>('[data-new-comment-submit]')?.disabled).toBe(true)
 expect(f.root.querySelector<HTMLButtonElement>('[aria-label="取消并关闭新建批注"]')?.disabled).toBe(false)
 expect(()=>f.controls.flush()).toThrow();expect(input.value).toBe('锁定时保留');expect(f.draft.operations).toEqual([])
})

it('入口按钮阻止鼠标默认焦点时，使用实际点击入口恢复焦点',()=>{
 const f=fixture();f.editor.commands.setTextSelection({from:7,to:14})
 const outside=f.root.appendChild(document.createElement('button')),opener=f.root.appendChild(document.createElement('button'))
 opener.addEventListener('mousedown',event=>event.preventDefault());opener.addEventListener('click',f.controls.openNew)
 outside.focus();opener.click();f.root.querySelector<HTMLButtonElement>('[data-new-comment-cancel]')!.click()
 expect(document.activeElement).toBe(opener);expect(f.draft.operations).toEqual([])
})

it('文本框重新获得焦点时恢复可见区域，保留文字和 UTF16 选区',()=>{
 const f=fixture();f.editor.commands.setTextSelection({from:7,to:14});f.controls.openNew()
 const input=f.root.querySelector<HTMLTextAreaElement>('[data-new-comment-text]')!,scroll=vi.fn()
 Object.defineProperty(input,'scrollIntoView',{configurable:true,value:scroll})
 input.value='A😀BCDE';input.setSelectionRange(1,5)
 f.root.querySelector<HTMLButtonElement>('[data-new-comment-submit]')!.focus();input.focus()
 expect(scroll).toHaveBeenCalledWith({block:'nearest'});expect(input.value).toBe('A😀BCDE');expect([input.selectionStart,input.selectionEnd]).toEqual([1,5])
 expect(f.draft.operations).toEqual([])
})
