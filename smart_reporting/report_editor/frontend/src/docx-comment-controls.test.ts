import {afterEach,expect,it,vi} from 'vitest'
import {Editor,Extension,Mark,Node} from '@tiptap/core'
import {UndoRedo} from '@tiptap/extensions'
import {Plugin} from '@tiptap/pm/state'
import {createDocxCommentControls} from './docx-comment-controls'
import {commentTextOperationsOf,normalizeDocxCommentText,replayDocxCommentText,type DocxCommentTextModel} from './docx-comment-text'
import {NativeDraft} from './native-draft'
import {docxCommentThreadOperationsOf,projectedDocxCommentThreads,updateDocxCommentThreadOperations,type DocxCommentThreadModel} from './docx-comment-thread'
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
it('toggles the Review comments panel closed and flushes edits before hiding it',()=>{
 const f=fixture(),panel=f.root.querySelector<HTMLElement>('.docx-comment-panel')!
 f.controls.toggle();expect(f.controls.visible).toBe(true);expect(panel.hidden).toBe(false)
 input(f,'Toggle close edit')
 f.controls.toggle();expect(f.controls.visible).toBe(false);expect(panel.hidden).toBe(true)
 expect(f.draft.operations[0]).toMatchObject({kind:'editCommentText',text:'Toggle close edit'})
 expect(f.editor.state.doc.textContent).toBe('Body')
 f.controls.toggle();expect(f.controls.visible).toBe(true);expect(panel.hidden).toBe(false)
 expect(f.root.querySelector<HTMLTextAreaElement>('[data-comment-text]')!.value).toBe('Toggle close edit')
})
it('returns focus to the Review toggle and keeps the panel visible when a locked flush fails',()=>{
 const f=fixture(),opener=document.body.appendChild(document.createElement('button')),panel=f.root.querySelector<HTMLElement>('.docx-comment-panel')!
 f.controls.toggle({currentTarget:opener});expect(document.activeElement).toBe(f.root.querySelector('[data-comment-text]'))
 input(f,'Retain while locked');f.lock();f.controls.toggle({currentTarget:opener})
 expect(f.controls.visible).toBe(true);expect(panel.hidden).toBe(false)
 expect(f.root.querySelector<HTMLTextAreaElement>('[data-comment-text]')!.value).toBe('Retain while locked')
 expect(f.controls.hasPendingInput).toBe(true);expect(f.draft.operations).toEqual([])
 f.controls.refresh()
})
it('returns focus to the opener after a successful Review toggle close',()=>{
 const f=fixture(),opener=document.body.appendChild(document.createElement('button'))
 f.controls.toggle({currentTarget:opener});f.controls.toggle({currentTarget:opener})
 expect(f.controls.visible).toBe(false);expect(document.activeElement).toBe(opener)
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

it('provides a desktop title close that applies input and returns focus to the actual opener',()=>{
 const f=fixture(),opener=document.body.appendChild(document.createElement('button'))
 f.controls.open({currentTarget:opener})
 const panel=f.root.querySelector<HTMLElement>('.docx-comment-editor')!
 expect(panel.querySelector('header h2')?.textContent).toBe('已有批注文字')
 input(f,'Title closed edit')
 panel.querySelector<HTMLButtonElement>('[aria-label="应用并关闭已有批注"]')!.click()
 expect(panel.hidden).toBe(true);expect(document.activeElement).toBe(opener)
 expect(f.draft.operations[0]).toMatchObject({kind:'editCommentText',text:'Title closed edit'})
})
it('keeps a failed title close visible with its pending input and focuses close when no target exists',()=>{
 const f=fixture();f.controls.open();input(f,'Keep this');f.lock()
 f.root.querySelector<HTMLButtonElement>('[aria-label="应用并关闭已有批注"]')!.click()
 expect(f.root.querySelector<HTMLElement>('.docx-comment-panel')!.hidden).toBe(false)
 expect(f.controls.hasPendingInput).toBe(true);expect(f.draft.operations).toEqual([])
 expect(f.root.querySelector<HTMLTextAreaElement>('textarea')!.value).toBe('Keep this')
 const empty=fixture({...model,commentTargets:[]});empty.controls.open()
 expect(document.activeElement).toBe(empty.root.querySelector('[data-comment-title-close]'))
})
it('keeps a refocused textarea visible within the desktop panel scroll area',()=>{
 const f=fixture(),field=f.root.querySelector<HTMLTextAreaElement>('textarea')!,scroll=vi.fn()
 field.scrollIntoView=scroll;f.controls.open()
 expect(scroll).toHaveBeenCalledWith({block:'nearest'})
 field.blur();scroll.mockClear();field.focus()
 expect(scroll).toHaveBeenCalledWith({block:'nearest'})
})

it('navigates only trusted open comment anchors in document order with wraparound, including readonly mode',()=>{
 const root=document.body.appendChild(document.createElement('div')),Doc=Node.create({name:'doc',topNode:true,content:'block+'})
 const Paragraph=Node.create({name:'docParagraph',group:'block',content:'inline*',renderHTML:()=>['p',0]}),Text=Node.create({name:'text',group:'inline'})
 const Comment=Mark.create({name:'comment',addAttributes:()=>({ids:{default:''}}),renderHTML:({mark})=>['span',{'data-comment-ids':mark.attrs.ids},0]})
 const editor=new Editor({element:root.appendChild(document.createElement('div')),extensions:[Doc,Paragraph,Text,Comment],content:{type:'doc',content:[
  {type:'docParagraph',content:[{type:'text',text:'first',marks:[{type:'comment',attrs:{ids:'1'}}]}]},
  {type:'docParagraph',content:[{type:'text',text:'resolved',marks:[{type:'comment',attrs:{ids:'2'}}]}]},
  {type:'docParagraph',content:[{type:'text',text:'last',marks:[{type:'comment',attrs:{ids:'3'}}]}]},
  {type:'docParagraph',content:[{type:'text',text:'orphan'}]},
 ]}})
 const targets=['1','2','3','4'].map((originalCommentId,ordinal)=>({sourceId,targetId:'abcd'[ordinal]!.repeat(64),expectedCommentsSha256:'e'.repeat(64),expectedObjectSha256:'f'.repeat(64),originalCommentId,ordinal,author:'A',date:null,initials:null,text:originalCommentId,relationshipIds:[],editableText:true,readOnlyReason:null,parentId:null,done:originalCommentId==='2',canDelete:true,canResolve:true,threadReadOnlyReason:null}))
 const comments:DocxCommentTextModel={sourceSha256:sha,sourceId,commentReadOnlyReason:null,commentTargets:targets.map(({parentId,done,canDelete,canResolve,threadReadOnlyReason,...target})=>target)}
 const threads:DocxCommentThreadModel={sourceSha256:sha,sourceId,readOnlyReason:null,targets}
 const controls=createDocxCommentControls({editor,container:root,model:comments,thread:{model:threads,readOnlyReason:()=>null},collectOperations:()=>[],readOnlyReason:()=>null,onError:error=>{throw error}})
 const doc=editor.getJSON(),initial=editor.state.selection.from
 expect(controls.navigationReason()).toBe('')
 expect(controls.navigate(1)).toBe(true)
 expect(controls.visible).toBe(true)
 expect(targets.some(target=>target.targetId===root.querySelector<HTMLSelectElement>('[data-comment-target]')!.value)).toBe(true)
 expect(editor.state.selection.from).toBeGreaterThan(initial)
 const last=editor.state.selection.from
 expect(controls.navigate(1)).toBe(true);expect(editor.state.selection.from).toBeLessThan(last)
 expect(controls.navigate(-1)).toBe(true);expect(editor.state.selection.from).toBe(last)
 editor.setEditable(false)
 const readonlyDoc=editor.getJSON(),position=editor.state.selection.from
 expect(controls.navigate(-1)).toBe(true);expect(editor.state.selection.from).not.toBe(position)
 expect(editor.getJSON()).toEqual(readonlyDoc);expect(editor.getJSON()).toEqual(doc)
 controls.dispose();editor.destroy()
})

it('deletes only the trusted thread under the caret through the existing thread intent and history',()=>{
 const root=document.body.appendChild(document.createElement('div')),Doc=Node.create({name:'doc',topNode:true,content:'block+',addAttributes:()=>({nativeCommentThreadOperations:{default:null}})})
 const Paragraph=Node.create({name:'docParagraph',group:'block',content:'inline*',renderHTML:()=>['p',0]}),Text=Node.create({name:'text',group:'inline'})
 const Comment=Mark.create({name:'comment',addAttributes:()=>({ids:{default:''}}),renderHTML:({mark})=>['span',{'data-comment-ids':mark.attrs.ids},0]})
 const editor=new Editor({element:root.appendChild(document.createElement('div')),extensions:[Doc,Paragraph,Text,Comment,UndoRedo],content:{type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'Body',marks:[{type:'comment',attrs:{ids:'7'}}]}]}]}})
 const target={...model.commentTargets[0],originalCommentId:'7',canDelete:true,canResolve:true,parentId:null,done:false,threadReadOnlyReason:null}
 const comments:DocxCommentTextModel={...model,commentTargets:[{...model.commentTargets[0],originalCommentId:'7'}]}
 const threads:DocxCommentThreadModel={sourceSha256:sha,sourceId,readOnlyReason:null,targets:[target]}
 let locked=false
 const errors:unknown[]=[],confirm=vi.spyOn(window,'confirm').mockReturnValue(true)
 const controls=createDocxCommentControls({editor,container:root,model:comments,thread:{model:threads,readOnlyReason:()=>locked?'文档受保护':null},collectOperations:doc=>docxCommentThreadOperationsOf(doc,threads),readOnlyReason:()=>locked?'文档受保护':null,onError:error=>errors.push(error)})
 expect(controls.deleteAtCaretReason()).toBeNull()
 expect(controls.deleteAtCaret()).toBe(true)
 expect(confirm).toHaveBeenCalledWith('删除此批注及其回复？')
 expect(docxCommentThreadOperationsOf(editor.getJSON(),threads)).toEqual([{kind:'deleteComment',sourceId,targetId,expectedCommentsSha256:'a'.repeat(64),expectedObjectSha256:'b'.repeat(64)}])
 expect(projectedDocxCommentThreads([{id:'7',text:'Original'}],editor.getJSON(),threads)).toEqual([])
 expect(controls.deleteAtCaretReason()).toBe('当前没有可删除的可信批注')
 expect(controls.deleteAtCaret()).toBe(false)
 expect(editor.state.doc.textContent).toBe('Body')
 expect(editor.commands.undo()).toBe(true)
 expect(projectedDocxCommentThreads([{id:'7',text:'Original'}],editor.getJSON(),threads)).toEqual([{id:'7',text:'Original'}])
 expect(editor.commands.redo()).toBe(true)
 expect(projectedDocxCommentThreads([{id:'7',text:'Original'}],editor.getJSON(),threads)).toEqual([])
 editor.commands.undo()
 locked=true;editor.setEditable(false)
 expect(controls.deleteAtCaretReason()).toBe('文档受保护')
 expect(controls.deleteAtCaret()).toBe(false)
 expect(docxCommentThreadOperationsOf(editor.getJSON(),threads)).toEqual([])
 expect(errors).toEqual([])
 controls.dispose();editor.destroy();confirm.mockRestore()
})

it('flushes the open target and refuses to mix its text edit with another thread deletion',()=>{
 const root=document.body.appendChild(document.createElement('div')),Doc=Node.create({name:'doc',topNode:true,content:'block+',addAttributes:()=>({nativeCommentTextOperations:{default:null},nativeCommentThreadOperations:{default:null}})})
 const Paragraph=Node.create({name:'docParagraph',group:'block',content:'inline*',renderHTML:()=>['p',0]}),Text=Node.create({name:'text',group:'inline'})
 const Comment=Mark.create({name:'comment',addAttributes:()=>({ids:{default:''}}),renderHTML:({mark})=>['span',{'data-comment-ids':mark.attrs.ids},0]})
 const editor=new Editor({element:root.appendChild(document.createElement('div')),extensions:[Doc,Paragraph,Text,Comment,UndoRedo],content:{type:'doc',content:[
  {type:'docParagraph',content:[{type:'text',text:'First',marks:[{type:'comment',attrs:{ids:'7'}}]}]},
  {type:'docParagraph',content:[{type:'text',text:'Second',marks:[{type:'comment',attrs:{ids:'8'}}]}]},
 ]}})
 const first={...model.commentTargets[0],targetId:'1'.repeat(64),originalCommentId:'7',text:'First comment',ordinal:0},second={...model.commentTargets[0],targetId:'2'.repeat(64),originalCommentId:'8',text:'Second comment',ordinal:1}
 const comments:DocxCommentTextModel={...model,commentTargets:[first,second]}
 const targets=[first,second].map(target=>({...target,parentId:null,done:false,canDelete:true,canResolve:true,threadReadOnlyReason:null}))
 const threads:DocxCommentThreadModel={sourceSha256:sha,sourceId,readOnlyReason:null,targets}
 const errors:unknown[]=[],confirm=vi.spyOn(window,'confirm').mockReturnValue(true)
 const controls=createDocxCommentControls({editor,container:root,model:comments,thread:{model:threads,readOnlyReason:()=>null},collectOperations:()=>[],readOnlyReason:()=>null,onError:error=>errors.push(error)})
 editor.commands.setTextSelection(1);controls.open()
 const field=root.querySelector<HTMLTextAreaElement>('[data-comment-text]')!;field.value='Edited first';field.dispatchEvent(new Event('input',{bubbles:true}))
 editor.commands.setTextSelection(editor.state.doc.child(0).nodeSize+1)
 expect(controls.deleteAtCaret()).toBe(false)
 expect(commentTextOperationsOf(editor.getJSON(),comments)).toEqual([{kind:'editCommentText',sourceId,targetId:first.targetId,expectedCommentsSha256:first.expectedCommentsSha256,expectedObjectSha256:first.expectedObjectSha256,text:'Edited first'}])
 expect(docxCommentThreadOperationsOf(editor.getJSON(),threads)).toEqual([])
 expect(confirm).not.toHaveBeenCalled();expect(errors).toHaveLength(1);controls.dispose();editor.destroy();confirm.mockRestore()
})

it('deletes resolved or all trusted threads with one confirmation and atomic history',()=>{
 const root=document.body.appendChild(document.createElement('div')),Doc=Node.create({name:'doc',topNode:true,content:'block+',addAttributes:()=>({nativeCommentTextOperations:{default:null},nativeCommentThreadOperations:{default:null}})})
 const Paragraph=Node.create({name:'docParagraph',group:'block',content:'inline*',renderHTML:()=>['p',0]}),Text=Node.create({name:'text',group:'inline'})
 const Comment=Mark.create({name:'comment',addAttributes:()=>({ids:{default:''}}),renderHTML:({mark})=>['span',{'data-comment-ids':mark.attrs.ids},0]})
 const editor=new Editor({element:root.appendChild(document.createElement('div')),extensions:[Doc,Paragraph,Text,Comment,UndoRedo],content:{type:'doc',content:[
  {type:'docParagraph',content:[{type:'text',text:'Resolved',marks:[{type:'comment',attrs:{ids:'7'}}]}]},
  {type:'docParagraph',content:[{type:'text',text:'Open',marks:[{type:'comment',attrs:{ids:'8'}}]}]},
 ]}})
 const resolved={...model.commentTargets[0],targetId:'1'.repeat(64),originalCommentId:'7',ordinal:0,text:'Resolved',parentId:null},reply={...model.commentTargets[0],targetId:'2'.repeat(64),originalCommentId:'9',ordinal:1,text:'Reply',parentId:'7'},open={...model.commentTargets[0],targetId:'3'.repeat(64),originalCommentId:'8',ordinal:2,text:'Open',parentId:null}
 const comments:DocxCommentTextModel={...model,commentTargets:[resolved,reply,open]}
 const targets=[resolved,reply,open].map((target,index)=>({...target,parentId:target.parentId??null,done:index<2,canDelete:true,canResolve:target.parentId===null,threadReadOnlyReason:null}))
 const threads:DocxCommentThreadModel={sourceSha256:sha,sourceId,readOnlyReason:null,targets}
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(true),controls=createDocxCommentControls({editor,container:root,model:comments,thread:{model:threads,readOnlyReason:()=>null},collectOperations:()=>[],readOnlyReason:()=>null,onError:error=>{throw error}})
 const replyTarget=targets.find(target=>target.parentId==='7')!
 replyTarget.canDelete=false
 expect(controls.deleteAllReason(true)).toBe('所选批注线程不能删除')
 expect(controls.deleteAll(true)).toBe(false);expect(confirm).not.toHaveBeenCalled();expect(editor.getJSON().attrs?.nativeCommentThreadOperations).toBeNull()
 replyTarget.canDelete=true
 confirm.mockReturnValue(false)
 expect(controls.deleteAll(true)).toBe(false);expect(editor.getJSON().attrs?.nativeCommentThreadOperations).toBeNull()
 confirm.mockReturnValue(true)
 expect(controls.deleteAllReason(true)).toBeNull();expect(controls.deleteAll(true)).toBe(true)
 expect(confirm).toHaveBeenCalledWith('删除所有已解决的批注？')
 expect(docxCommentThreadOperationsOf(editor.getJSON(),threads)).toEqual([
  {kind:'deleteComment',sourceId,targetId:resolved.targetId,expectedCommentsSha256:resolved.expectedCommentsSha256,expectedObjectSha256:resolved.expectedObjectSha256},
 ])
 expect(projectedDocxCommentThreads([{id:'7',text:'Resolved',done:true},{id:'9',text:'Reply',done:true},{id:'8',text:'Open',done:false}],editor.getJSON(),threads)).toEqual([{id:'8',text:'Open',done:false}])
 expect(controls.deleteAllReason(true)).toBe('当前没有可删除的可信已解决批注')
 expect(controls.deleteAllReason(false)).toBeNull();expect(controls.deleteAll(false)).toBe(true)
 expect(confirm).toHaveBeenCalledWith('删除文档中的所有批注？')
 expect(docxCommentThreadOperationsOf(editor.getJSON(),threads)).toHaveLength(2)
 expect(editor.commands.undo()).toBe(true)
 expect(docxCommentThreadOperationsOf(editor.getJSON(),threads)).toEqual([{kind:'deleteComment',sourceId,targetId:resolved.targetId,expectedCommentsSha256:resolved.expectedCommentsSha256,expectedObjectSha256:resolved.expectedObjectSha256}])
 expect(projectedDocxCommentThreads([{id:'7',text:'Resolved',done:true},{id:'9',text:'Reply',done:true},{id:'8',text:'Open',done:false}],editor.getJSON(),threads)).toEqual([{id:'8',text:'Open',done:false}])
 expect(editor.commands.redo()).toBe(true)
 expect(projectedDocxCommentThreads([{id:'7',text:'Resolved',done:true},{id:'9',text:'Reply',done:true},{id:'8',text:'Open',done:false}],editor.getJSON(),threads)).toEqual([])
 controls.dispose();editor.destroy();confirm.mockRestore()
})

it('flushes pending comment text and stops batch deletion when the existing save contract forbids mixing them',()=>{
 const root=document.body.appendChild(document.createElement('div')),Doc=Node.create({name:'doc',topNode:true,content:'block+',addAttributes:()=>({nativeCommentTextOperations:{default:null},nativeCommentThreadOperations:{default:null}})})
 const Paragraph=Node.create({name:'docParagraph',group:'block',content:'inline*',renderHTML:()=>['p',0]}),Text=Node.create({name:'text',group:'inline'})
 const Comment=Mark.create({name:'comment',addAttributes:()=>({ids:{default:''}}),renderHTML:({mark})=>['span',{'data-comment-ids':mark.attrs.ids},0]})
 const editor=new Editor({element:root.appendChild(document.createElement('div')),extensions:[Doc,Paragraph,Text,Comment,UndoRedo],content:{type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'Body',marks:[{type:'comment',attrs:{ids:'7'}}]}]}]}})
 const target={...model.commentTargets[0],originalCommentId:'7',parentId:null,done:true,canDelete:true,canResolve:true,threadReadOnlyReason:null}
 const comments:DocxCommentTextModel={...model,commentTargets:[{...model.commentTargets[0],originalCommentId:'7'}]},threads:DocxCommentThreadModel={sourceSha256:sha,sourceId,readOnlyReason:null,targets:[target]},errors:unknown[]=[]
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(true),controls=createDocxCommentControls({editor,container:root,model:comments,thread:{model:threads,readOnlyReason:()=>null},collectOperations:doc=>{
  const textOperations=commentTextOperationsOf(doc,comments),threadOperations=docxCommentThreadOperationsOf(doc,threads)
  if(textOperations.length&&threadOperations.length)throw new Error('批注线程修改需独立保存')
  return[]
 },readOnlyReason:()=>null,onError:error=>errors.push(error)})
 controls.open();const field=root.querySelector<HTMLTextAreaElement>('[data-comment-text]')!;field.value='Edited note';field.dispatchEvent(new Event('input',{bubbles:true}))
 expect(controls.deleteAll(true)).toBe(false)
 expect(commentTextOperationsOf(editor.getJSON(),comments)).toMatchObject([{kind:'editCommentText',targetId,text:'Edited note'}])
 expect(docxCommentThreadOperationsOf(editor.getJSON(),threads)).toEqual([])
 expect(confirm).not.toHaveBeenCalled();expect(errors).toHaveLength(1)
 controls.dispose();editor.destroy();confirm.mockRestore()
})

it('includes a thread resolved in the current draft in the resolved batch',()=>{
 const root=document.body.appendChild(document.createElement('div')),Doc=Node.create({name:'doc',topNode:true,content:'block+',addAttributes:()=>({nativeCommentThreadOperations:{default:null}})})
 const Paragraph=Node.create({name:'docParagraph',group:'block',content:'inline*',renderHTML:()=>['p',0]}),Text=Node.create({name:'text',group:'inline'})
 const Comment=Mark.create({name:'comment',addAttributes:()=>({ids:{default:''}}),renderHTML:({mark})=>['span',{'data-comment-ids':mark.attrs.ids},0]})
 const editor=new Editor({element:root.appendChild(document.createElement('div')),extensions:[Doc,Paragraph,Text,Comment,UndoRedo],content:{type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'Open',marks:[{type:'comment',attrs:{ids:'8'}}]}]}]}})
 const target={...model.commentTargets[0],originalCommentId:'8',parentId:null,done:false,canDelete:true,canResolve:true,threadReadOnlyReason:null},comments:DocxCommentTextModel={...model,commentTargets:[{...model.commentTargets[0],originalCommentId:'8'}]},threads:DocxCommentThreadModel={sourceSha256:sha,sourceId,readOnlyReason:null,targets:[target]}
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(true),controls=createDocxCommentControls({editor,container:root,model:comments,thread:{model:threads,readOnlyReason:()=>null},collectOperations:()=>[],readOnlyReason:()=>null,onError:error=>{throw error}})
 expect(controls.deleteAllReason(true)).toBe('当前没有可删除的可信已解决批注')
 const resolveOperation=updateDocxCommentThreadOperations(threads,[],target.targetId,true)
 editor.view.dispatch(editor.state.tr.setDocAttribute('nativeCommentThreadOperations',resolveOperation))
 expect(projectedDocxCommentThreads([{id:'8',done:false}],editor.getJSON(),threads)).toEqual([{id:'8',done:true}])
 expect(controls.deleteAllReason(true)).toBeNull();expect(controls.deleteAll(true)).toBe(true)
 expect(docxCommentThreadOperationsOf(editor.getJSON(),threads)).toMatchObject([{kind:'deleteComment',targetId:target.targetId}])
 controls.dispose();editor.destroy();confirm.mockRestore()
})
