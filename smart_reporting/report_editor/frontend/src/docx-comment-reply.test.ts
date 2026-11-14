import {afterEach,expect,it,vi} from 'vitest'
import {Editor,Node} from '@tiptap/core'
import {UndoRedo} from '@tiptap/extensions'
import {NativeDraft} from './native-draft'
import {createDocxCommentReplyControls,normalizeDocxCommentReplies,replayDocxCommentReplies,verifiedDocxCommentReplyModel,type DocxCommentReplyModel} from './docx-comment-reply'
const sha='a'.repeat(64),sourceId='b'.repeat(64),targetId='c'.repeat(64)
const target={sourceId,targetId,expectedCommentsSha256:'d'.repeat(64),expectedObjectSha256:'e'.repeat(64),originalCommentId:'1',ordinal:0,author:'Alice',date:null,initials:null,text:'父批注',relationshipIds:[],editableText:true,readOnlyReason:null,parentId:null,canReply:true,replyReadOnlyReason:null}
const model:DocxCommentReplyModel={sourceSha256:sha,sourceId,readOnlyReason:null,targets:[target,{...target,targetId:'f'.repeat(64),originalCommentId:'2',ordinal:1,text:'已有回复',parentId:'1',canReply:false,replyReadOnlyReason:'请回复根线程'}]}
const disposals:(()=>void)[]=[]
afterEach(()=>{disposals.splice(0).forEach(f=>f());document.body.replaceChildren()})
function fixture(replyModel:DocxCommentReplyModel=model){
 const root=document.body.appendChild(document.createElement('div')),errors:unknown[]=[],storage=new Map<string,string>()
 let lock:string|null=null
 const draft=new NativeDraft({documentId:'reply-comment',revision:1,sourceSha256:sha,scope:{database:'db',companyId:'co',userId:'u',threadId:'t'}},{getItem:k=>storage.get(k)??null,setItem:(k,v)=>{storage.set(k,v)},removeItem:k=>{storage.delete(k)}})
 const Doc=Node.create({name:'doc',topNode:true,content:'block+',addAttributes:()=>({nativeCommentReplyOperations:{default:null}})})
 const Paragraph=Node.create({name:'docParagraph',group:'block',content:'inline*',renderHTML:()=>['p',0]})
 const Text=Node.create({name:'text',group:'inline'})
 const editor=new Editor({element:root.appendChild(document.createElement('div')),extensions:[Doc,Paragraph,Text,UndoRedo],content:'<p>锚点正文</p>'})
 const baseline=editor.getJSON(),collect=(doc:any)=>normalizeDocxCommentReplies(baseline,doc,replyModel).operations
 editor.on('update',()=>draft.setOperations(collect(editor.getJSON())))
 const controls=createDocxCommentReplyControls({editor,container:root,model:replyModel,collectOperations:collect,readOnlyReason:()=>lock,onError:e=>errors.push(e),clientId:()=> 'reply-1',now:()=>new Date('2026-11-11T01:02:03Z')})
 disposals.push(()=>{controls.dispose();editor.destroy()});return{root,editor,controls,draft,baseline,errors,setLock:(value:string|null)=>{lock=value}}
}
it('binds an existing root, cancel is clean and unblurred reply flush supports undo redo and recovery',()=>{
 const f=fixture();f.controls.openFor(targetId)
 const input=f.root.querySelector<HTMLTextAreaElement>('[data-comment-reply-text]')!
 expect(f.root.querySelector('[data-comment-reply-parent]')!.textContent).toContain('父批注')
 input.value='取消';f.root.querySelector<HTMLButtonElement>('[data-comment-reply-cancel]')!.click();expect(f.draft.operations).toEqual([])
 f.controls.openFor(targetId);input.value='回复中文😀';expect(f.draft.operations).toEqual([]);f.controls.flush()
 expect(f.draft.operations[0]).toMatchObject({kind:'replyComment',sourceId,targetId,expectedCommentsSha256:target.expectedCommentsSha256,expectedObjectSha256:target.expectedObjectSha256,text:'回复中文😀',author:'用户',date:'2026-11-11T01:02:03Z'})
 expect(f.editor.state.doc.textContent).toBe('锚点正文')
 f.editor.commands.undo();expect(f.draft.operations).toEqual([]);f.editor.commands.redo();expect(f.draft.operations).toHaveLength(1)
 const restored=replayDocxCommentReplies(f.baseline,f.draft.operations,model);expect(normalizeDocxCommentReplies(f.baseline,restored,model).operations).toEqual(f.draft.operations)
 expect(()=>replayDocxCommentReplies(f.baseline,[{...f.draft.operations[0],sourceId:'f'.repeat(64)}],model)).toThrow();expect(f.errors).toEqual([])
})
it('rejects nonroot and stale parent input without creating a root comment or losing input',()=>{
 const f=fixture();f.controls.openFor('f'.repeat(64));expect(f.errors).toHaveLength(1);expect(f.draft.operations).toEqual([])
 f.controls.openFor(targetId);const input=f.root.querySelector<HTMLTextAreaElement>('[data-comment-reply-text]')!;input.value='保留回复'
 f.editor.commands.insertContent('变化');expect(()=>f.controls.flush()).toThrow();expect(input.value).toBe('保留回复');expect(f.draft.operations).toEqual([])
})
it('server parent identity must agree with the parsed thread before reply is enabled',()=>{
 const verified=verifiedDocxCommentReplyModel(model,sha,[{id:'1',author:'Alice',text:'父批注',parentId:'2'},{id:'2',author:'Alice',text:'已有回复',parentId:'1'}])
 expect(verified.targets[0].canReply).toBe(false);expect(verified.targets[0].replyReadOnlyReason).toContain('来源')
})

it('clears a transient read only status when reply input is unlocked after recovery',()=>{
 const f=fixture();f.controls.openFor(targetId)
 f.setLock('当前文档不可编辑或正在保存');f.controls.refresh()
 expect(f.root.querySelector('[role=status]')!.textContent).toBe('当前文档不可编辑或正在保存')
 f.setLock(null);f.controls.refresh()
 expect(f.root.querySelector<HTMLTextAreaElement>('[data-comment-reply-text]')!.disabled).toBe(false)
 expect(f.root.querySelector('[role=status]')!.textContent).not.toContain('不可编辑')
})

const twoRoots:DocxCommentReplyModel={...model,targets:[model.targets[0],{...model.targets[1],author:'Bob',text:'第二根批注',parentId:null,canReply:true,replyReadOnlyReason:null}]}
it.each(['','  \n '])('rebinds an empty reply from first to second root before flush (%j)',empty=>{
 const f=fixture(twoRoots),second=twoRoots.targets[1]
 f.controls.openFor(targetId)
 const input=f.root.querySelector<HTMLTextAreaElement>('[data-comment-reply-text]')!;input.value=empty
 f.editor.view.dispatch(f.editor.state.tr.setDocAttribute('nativeCommentReplyOperations',[]))
 f.controls.openFor(second.targetId)
 expect(f.root.querySelector('[data-comment-reply-parent]')!.textContent).toBe('Bob：第二根批注')
 expect(input.value).toBe('');input.value='只回复第二根'
 f.controls.flush()
 expect(f.draft.operations).toHaveLength(1)
 expect(f.draft.operations[0]).toMatchObject({kind:'replyComment',targetId:second.targetId,text:'只回复第二根'})
 expect(f.errors).toEqual([])
})
it('keeps nonempty input attached to first root when switching is rejected',()=>{
 const f=fixture(twoRoots),input=f.root.querySelector<HTMLTextAreaElement>('[data-comment-reply-text]')!
 f.controls.openFor(targetId);input.value='尚未提交的第一根回复'
 f.controls.openFor(twoRoots.targets[1].targetId)
 expect(f.root.querySelector('[data-comment-reply-parent]')!.textContent).toContain('父批注')
 expect(input.value).toBe('尚未提交的第一根回复');expect(f.errors).toHaveLength(1)
 f.controls.flush()
 expect(f.draft.operations[0]).toMatchObject({targetId,text:'尚未提交的第一根回复'})
})

it('title cancel discards only local reply input and returns focus to the reply entry',()=>{
 const f=fixture(),opener=document.body.appendChild(document.createElement('button'))
 opener.focus();f.controls.openFor(targetId)
 const input=f.root.querySelector<HTMLTextAreaElement>('[data-comment-reply-text]')!
 input.value='已加入草稿';f.controls.flush();f.controls.openFor(targetId);input.value='仅本地输入'
 f.root.querySelector<HTMLButtonElement>('[aria-label="取消并关闭批注回复"]')!.click()
 expect(f.root.querySelector<HTMLElement>('.docx-comment-reply')!.hidden).toBe(true)
 expect(document.activeElement).toBe(opener);expect(input.value).toBe('')
 expect(f.draft.operations).toHaveLength(1);expect(f.draft.operations[0]).toMatchObject({text:'已加入草稿'})
})
it('exposes parent and reply drafts as named keyboard regions and recovers focus after undo empties the list',()=>{
 const f=fixture();f.controls.openFor(targetId)
 const parent=f.root.querySelector<HTMLElement>('[data-comment-reply-parent]')!,list=f.root.querySelector<HTMLElement>('[data-comment-reply-list]')!,input=f.root.querySelector<HTMLTextAreaElement>('textarea')!
 expect(parent.getAttribute('role')).toBe('region');expect(parent.tabIndex).toBe(0)
 expect(list.getAttribute('aria-label')).toBe('待保存的批注回复');expect(list.hidden).toBe(true)
 input.value='第一条回复\n换行';f.controls.flush();expect(list.hidden).toBe(false)
 expect(list.querySelector('time')?.dateTime).toBe('2026-11-11T01:02:03Z')
 expect(list.querySelector('p')?.textContent).toBe('第一条回复\n换行')
 list.focus();f.editor.commands.undo();expect(list.hidden).toBe(true);expect(document.activeElement).toBe(input)
 f.editor.commands.redo();openerFocus();f.editor.commands.undo();expect(document.activeElement?.textContent).toBe('外部入口')
 function openerFocus(){const button=document.body.appendChild(document.createElement('button'));button.textContent='外部入口';button.focus()}
})
it('scrolls the reply input into view whenever keyboard navigation returns to it',()=>{
 const f=fixture(),input=f.root.querySelector<HTMLTextAreaElement>('textarea')!,scroll=vi.fn();input.scrollIntoView=scroll
 f.controls.openFor(targetId);expect(scroll).toHaveBeenCalledWith({block:'nearest'})
 input.blur();scroll.mockClear();input.focus();expect(scroll).toHaveBeenCalledWith({block:'nearest'})
})
