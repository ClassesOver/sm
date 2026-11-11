import {afterEach,expect,it,vi} from 'vitest'
import {Editor,Extension,Node} from '@tiptap/core'
import {UndoRedo} from '@tiptap/extensions'
import {Plugin} from '@tiptap/pm/state'
import {createDocxCommentControls} from './docx-comment-controls'
import {commentTextOperationsOf,normalizeDocxCommentText,replayDocxCommentText,type DocxCommentTextModel} from './docx-comment-text'
import {NativeDraft} from './native-draft'
import type {DocxPmNode} from './docx-operations'
const sourceId='c'.repeat(64),targetId='d'.repeat(64),sha='e'.repeat(64)
const model:DocxCommentTextModel={sourceSha256:sha,sourceId,commentReadOnlyReason:null,commentTargets:[{sourceId,targetId,expectedCommentsSha256:'a'.repeat(64),expectedObjectSha256:'b'.repeat(64),originalCommentId:'7',ordinal:0,author:'Alice <script>',date:null,initials:null,text:'Original',relationshipIds:[],editableText:true,readOnlyReason:null}]}
const disposals:(()=>void)[]=[]
afterEach(()=>{disposals.splice(0).forEach(dispose=>dispose());document.body.replaceChildren()})
function fixture(currentModel=model,onReviewAI?: (selection:{sourceId:string;targetId:string},instruction?:string)=>void){
 const model=currentModel
 const root=document.body.appendChild(document.createElement('div')),errors:unknown[]=[]
 const store=new Map<string,string>(),draft=new NativeDraft({documentId:'word-comments',revision:1,sourceSha256:sha,scope:{database:'db',companyId:'co',userId:'u',threadId:'t'}},{getItem:k=>store.get(k)??null,setItem:(k,v)=>{store.set(k,v)},removeItem:k=>{store.delete(k)}})
 let baseline:DocxPmNode,ready=false,locked=false
 const Doc=Node.create({name:'doc',topNode:true,content:'block+',addAttributes:()=>({nativeCommentTextOperations:{default:null}})})
 const Paragraph=Node.create({name:'docParagraph',group:'block',content:'inline*',renderHTML:()=>['p',0]})
 const Text=Node.create({name:'text',group:'inline'})
 const collect=(doc:DocxPmNode)=>{const n=normalizeDocxCommentText(baseline,doc,model);if(JSON.stringify(n.current.content)!==JSON.stringify(baseline.content))throw new Error('批注修改必须独立保存');return n.operations}
 const Guard=Extension.create({name:'commentGuard',addProseMirrorPlugins:()=>[new Plugin({filterTransaction(tr){if(!ready||!tr.docChanged)return true;try{if(locked)return false;collect(tr.doc.toJSON());return true}catch{return false}}})]})
 const editor=new Editor({element:root.appendChild(document.createElement('div')),extensions:[Doc,Paragraph,Text,UndoRedo,Guard],content:{type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'Body'}]}]},onUpdate(){if(ready)draft.setOperations(collect(editor.getJSON()))}})
 baseline=editor.getJSON();ready=true
 const controls=createDocxCommentControls({editor,container:root,model,onReviewAI,collectOperations:collect,readOnlyReason:()=>locked?'正在保存':null,onError:error=>errors.push(error)})
 disposals.push(()=>{controls.dispose();editor.destroy()})
 return {root,editor,controls,draft,errors,baseline,lock(){locked=true;editor.setEditable(false);controls.refresh()}}
}
function input(f:ReturnType<typeof fixture>,text:string){const field=f.root.querySelector<HTMLTextAreaElement>('[data-comment-text]')!;field.value=text;field.dispatchEvent(new Event('input',{bubbles:true}));return field}
it('flushes unblurred textarea into one source-bound draft intent and undo redo update panel text',()=>{
 const f=fixture();f.controls.open();expect(f.root.querySelector('script')).toBeNull()
 input(f,'Edited 😀');expect(f.draft.operations).toEqual([])
 f.controls.flush();expect(f.draft.operations).toEqual([{kind:'editCommentText',sourceId,targetId,expectedCommentsSha256:'a'.repeat(64),expectedObjectSha256:'b'.repeat(64),text:'Edited 😀'}])
 expect(f.editor.state.doc.textContent).toBe('Body')
 expect(f.editor.commands.undo()).toBe(true);expect(f.draft.operations).toEqual([]);expect(f.root.querySelector<HTMLTextAreaElement>('[data-comment-text]')!.value).toBe('Original')
 expect(f.editor.commands.redo()).toBe(true);expect(f.root.querySelector<HTMLTextAreaElement>('[data-comment-text]')!.value).toBe('Edited 😀')
 input(f,'Original');f.controls.flush();expect(f.draft.operations).toEqual([])
 expect(f.errors).toEqual([])
})
it('retains pending text on a locked flush and prevents stale document intent from being committed',()=>{
 const f=fixture();f.controls.open();input(f,'Pending');f.lock()
 expect(()=>f.controls.flush()).toThrow('正在保存');expect(f.root.querySelector<HTMLTextAreaElement>('[data-comment-text]')!.value).toBe('Pending');expect(f.draft.operations).toEqual([])
})
it('restores source-bound operations and rejects forged intent without mutating draft',()=>{
 const f=fixture(),operation={kind:'editCommentText',sourceId,targetId,expectedCommentsSha256:'a'.repeat(64),expectedObjectSha256:'b'.repeat(64),text:'Restored'}
 const restored=replayDocxCommentText(f.baseline,[operation],model);f.editor.commands.setContent(restored,{emitUpdate:false});f.editor.view.dispatch(f.editor.state.tr.setDocAttribute('nativeCommentTextOperations',[operation]));f.controls.open()
 expect(f.root.querySelector<HTMLTextAreaElement>('[data-comment-text]')!.value).toBe('Restored')
 const before=f.editor.getJSON();f.editor.view.dispatch(f.editor.state.tr.setDocAttribute('nativeCommentTextOperations',[{...operation,sourceId:'f'.repeat(64)}]));expect(f.editor.getJSON()).toEqual(before)
 expect(commentTextOperationsOf(before,model)).toEqual([operation])
})
it('retains pending input after undo changes its captured document instead of applying it to a stale snapshot',()=>{
 const f=fixture();f.controls.open();input(f,'Applied');f.controls.flush();input(f,'Unapplied')
 expect(f.editor.commands.undo()).toBe(true);expect(f.draft.operations).toEqual([])
 expect(()=>f.controls.flush()).toThrow('来源已经变化')
 expect(f.root.querySelector<HTMLTextAreaElement>('[data-comment-text]')!.value).toBe('Unapplied')
 expect(f.controls.hasPendingInput).toBe(true)
 f.root.querySelector<HTMLButtonElement>('[data-comment-reload]')!.click()
 expect(f.controls.hasPendingInput).toBe(false)
 expect(f.root.querySelector<HTMLTextAreaElement>('[data-comment-text]')!.value).toBe('Original')
 input(f,'Fresh edit');f.controls.flush()
 expect(f.draft.beginSave({action:'save'}).operations[0]).toMatchObject({kind:'editCommentText',text:'Fresh edit'})
})
it('flushes pending comment text on close without touching document content',()=>{
 const f=fixture();f.controls.open();input(f,'Closed edit')
 f.root.querySelector<HTMLButtonElement>('[data-comment-close]')!.click()
 expect(f.root.querySelector<HTMLElement>('.docx-comment-panel')!.hidden).toBe(true)
 expect(f.draft.operations[0]).toMatchObject({kind:'editCommentText',text:'Closed edit'})
 expect(f.editor.state.doc.textContent).toBe('Body')
})
it('does not apply discarded local input when the reload button receives textarea focus',()=>{
 const f=fixture();f.controls.open();const field=input(f,'Discard this'),reload=f.root.querySelector<HTMLButtonElement>('[data-comment-reload]')!
 field.dispatchEvent(new FocusEvent('blur',{relatedTarget:reload}));reload.click()
 expect(f.draft.operations).toEqual([]);expect(field.value).toBe('Original');expect(f.controls.hasPendingInput).toBe(false)
})
it('flushes each authorized target on selection changes without replacing another comment intent',()=>{
 const second={...model.commentTargets[0],targetId:'f'.repeat(64),originalCommentId:'8',ordinal:1,text:'Second',author:'Bob'}
 const f=fixture({...model,commentTargets:[...model.commentTargets,second]});f.controls.open();input(f,'First edit')
 const select=f.root.querySelector<HTMLSelectElement>('[data-comment-target]')!
 select.value=second.targetId;select.dispatchEvent(new Event('change',{bubbles:true}))
 expect(f.draft.operations).toHaveLength(1);expect(f.draft.operations[0]).toMatchObject({targetId,text:'First edit'})
 expect(f.root.querySelector<HTMLTextAreaElement>('[data-comment-text]')!.value).toBe('Second')
 input(f,'Second edit');f.controls.flush()
 expect(f.draft.operations).toEqual([expect.objectContaining({targetId,text:'First edit'}),expect.objectContaining({targetId:second.targetId,text:'Second edit'})])
})
it('scrolls the opened comment panel into view and focuses its editable text without another scroll',()=>{
 const f=fixture(),panel=f.root.querySelector<HTMLElement>('.docx-comment-panel')!,field=f.root.querySelector<HTMLTextAreaElement>('[data-comment-text]')!
 const scroll=vi.fn(),focus=vi.spyOn(field,'focus');panel.scrollIntoView=scroll
 f.controls.open()
 expect(panel.hidden).toBe(false);expect(scroll).toHaveBeenCalledWith({block:'nearest'})
 expect(focus).toHaveBeenCalledWith({preventScroll:true});expect(document.activeElement).toBe(field)
 expect(f.draft.operations).toEqual([])
})

it('AI回复入口只传当前真实根批注并保持草稿不变，锁定时禁用',()=>{
 const open=vi.fn(),f=fixture(model,open);f.controls.open()
 const button=f.root.querySelector<HTMLButtonElement>('[data-comment-ai=reply]')!
 expect(button.hidden).toBe(false);expect(button.querySelector('svg')).not.toBeNull()
 button.click();expect(open).toHaveBeenCalledWith({sourceId,targetId},'');expect(f.draft.operations).toEqual([])
 f.lock();expect(button.disabled).toBe(true)
})
