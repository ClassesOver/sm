import {afterEach,expect,it,vi} from 'vitest'
import {Editor,Extension,Mark,Node} from '@tiptap/core'
import {UndoRedo} from '@tiptap/extensions'
import {Plugin,PluginKey} from '@tiptap/pm/state'
import {createDocxTextRevisionControls} from './docx-text-revision-controls'
import {normalizeDocxTextRevisions,replayDocxTextRevisions} from './docx-text-revisions'
import {TRACK_IGNORE,TrackChangesExtension} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/revisions'
import type {DocxPmNode} from './docx-operations'
import type {DocxTextRevisionAnchor} from './docx-text-revisions-core'
const Doc=Node.create({name:'doc',topNode:true,content:'block+'}),Text=Node.create({name:'text',group:'inline'})
const Paragraph=Node.create({name:'docParagraph',group:'block',content:'inline*',addAttributes:()=>({docxIndex:{default:0},nativeTextRevisionOperations:{default:null}}),renderHTML:()=>['p',0]})
const marks=['ins','del'].map(name=>Mark.create({name,addAttributes:()=>({author:{default:'A'},date:{default:null},id:{default:'7'},move:{default:null}}),renderHTML:()=>[name,0]}))
const disposals:(()=>void)[]=[]
afterEach(()=>{disposals.splice(0).forEach(dispose=>dispose());document.body.replaceChildren()})
function fixture(multiple=false,onReviewAI?: (selection:{blockId:string;revisionId:string},instruction?:string)=>void){
 const root=document.body.appendChild(document.createElement('div')),errors:unknown[]=[],ignored:boolean[]=[]
 let baseline:DocxPmNode,ready=false,locked=false
 const anchor:DocxTextRevisionAnchor={docxIndex:0,blockId:'body',expectedObjectSha256:'sha',reviewTargets:[['a',0,3,'😀同'],['b',3,4,'同']].map(([revisionId,from,to,text])=>({revisionId:String(revisionId),blockId:'body',expectedObjectSha256:'sha',originalRevisionId:'7',type:'insertion',author:'A <script>',date:null,sourceRange:{from:Number(from),to:Number(to),text:String(text)}}))}
 const anchors=[anchor,...(multiple?[{...structuredClone(anchor),docxIndex:1,blockId:'second',reviewTargets:anchor.reviewTargets!.map(t=>({...t,blockId:'second',revisionId:'second-'+t.revisionId,type:'deletion' as const}))}]:[])]
 const guardKey=new PluginKey('revisionGuard')
 const Guard=Extension.create({name:'revisionGuard',addProseMirrorPlugins:()=>[new Plugin({key:guardKey,filterTransaction(tr){if(!ready||!tr.docChanged)return true;try{if(locked)return false;const result=normalizeDocxTextRevisions(baseline,tr.doc.toJSON(),anchors,tr.doc.type.schema);return JSON.stringify(result.current)===JSON.stringify(baseline)}catch{return false}}})]})
 const editor=new Editor({element:root.appendChild(document.createElement('div')),extensions:[Doc,Paragraph,Text,...marks,UndoRedo,TrackChangesExtension,Guard],content:{type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'😀同同',marks:[{type:'ins',attrs:{author:'A <script>'}}]}]}]},editorProps:{handleScrollToSelection:()=>true}})
 if(multiple){const content=editor.getJSON();content.content!.push({type:'docParagraph',attrs:{docxIndex:1},content:[{type:'text',text:'😀同同',marks:[{type:'del',attrs:{author:'A <script>'}}]}]});editor.commands.setContent(content)}
 baseline=editor.getJSON();ready=true
 editor.on('transaction',({transaction})=>{if(transaction.docChanged)ignored.push(transaction.getMeta(TRACK_IGNORE)===true)})
 ;(editor.storage as any).trackChanges.enabled=true
 const controls=createDocxTextRevisionControls({editor,baseline,anchors,container:root,onReviewAI,readOnlyReason:()=>locked?'正在保存':null,onError:error=>errors.push(error)})
 disposals.push(()=>{controls.dispose();editor.destroy()})
 return {editor,baseline,anchor,anchors,controls,errors,ignored,bypass:()=>{editor.unregisterPlugin(guardKey);(editor.storage as any).trackChanges.enabled=false},lock:()=>{locked=true;controls.refresh()}}
}
const row=(id:string)=>document.querySelector<HTMLElement>(`[data-revision-id="${id}"]`)!
const click=(id:string,action:string)=>row(id).querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!.click()
it('accepts exact source target in one history step, keeps adjacent merged wrapper and undoes/redoes real decisions',()=>{
 const f=fixture();f.controls.open()
 expect(document.querySelector('[role="dialog"]')?.getAttribute('aria-label')).toBe('正文修订列表')
 expect(document.querySelector('script')).toBeNull();expect(row('a').textContent).toContain('A <script>')
 click('a','accept');expect(f.editor.state.doc.textContent).toBe('😀同同')
 expect(f.editor.state.doc.child(0).lastChild!.marks.some(mark=>mark.type.name==='ins')).toBe(true)
 expect(f.editor.state.doc.child(0).firstChild!.marks).toEqual([])
 click('b','reject');expect(f.editor.state.doc.textContent).toBe('😀同')
 expect(normalizeDocxTextRevisions(f.baseline,f.editor.getJSON(),[f.anchor],f.editor.schema).operations).toHaveLength(2)
 expect(f.ignored).toEqual([true,true])
 expect(f.editor.commands.undo()).toBe(true);expect(f.editor.state.doc.textContent).toBe('😀同同')
 expect(f.editor.commands.undo()).toBe(true);expect(f.editor.getJSON()).toEqual(f.baseline)
 expect(f.editor.commands.redo()).toBe(true);expect(f.editor.commands.redo()).toBe(true);expect(f.editor.state.doc.textContent).toBe('😀同')
 expect(f.errors).toEqual([])
})
it('locates precise UTF16 range, next navigates unresolved targets, locking blocks actions',()=>{
 const f=fixture();f.controls.open();click('b','locate');expect(f.editor.state.selection.from).toBe(4);expect(f.editor.state.selection.to).toBe(5)
 document.querySelector<HTMLButtonElement>('[data-action="next"]')!.click();expect(f.editor.state.selection.from).toBe(1);expect(f.editor.state.selection.to).toBe(4)
 f.lock();expect(row('a').querySelector<HTMLButtonElement>('[data-action="accept"]')!.disabled).toBe(true);click('a','accept');expect(f.editor.getJSON()).toEqual(f.baseline)
 expect(document.querySelector('[role="dialog"]')!.textContent).toContain('正在保存')
})
it('refreshes restored batch intent and refuses unverified current projection',()=>{
 const f=fixture(),operation={kind:'resolveTextRevision',blockId:'body',expectedObjectSha256:'sha',revisionId:'a',action:'reject'}
 const restored=replayDocxTextRevisions(f.baseline,[operation],[f.anchor],f.editor.schema)
 f.editor.commands.setContent(restored,{emitUpdate:false});f.controls.open()
 expect(row('a').textContent).toContain('已拒绝');expect(row('a').querySelector<HTMLButtonElement>('[data-action="accept"]')!.disabled).toBe(true)
 click('b','locate');expect(f.editor.state.selection.from).toBe(1);expect(f.editor.state.selection.to).toBe(2)
 // Simulate an untrusted out-of-band restore while the production Guard is bypassed.
 f.bypass();const fake=f.editor.getJSON() as DocxPmNode;fake.content![0].content![0].text='伪造';f.editor.commands.setContent(fake,{emitUpdate:false})
 expect(row('b').querySelector<HTMLButtonElement>('[data-action="accept"]')!.disabled).toBe(true);click('b','accept');expect(f.editor.state.doc.textContent).toContain('伪造');expect(document.querySelector('[role="status"]')!.textContent).toContain('草稿无效')
})

it('accepts supported revisions across paragraphs atomically and restores the whole batch with one undo',()=>{
 const f=fixture(true);f.controls.open();f.controls.applyAll('accept')
 expect(f.editor.state.doc.child(0).textContent).toBe('😀同同');expect(f.editor.state.doc.child(1).textContent).toBe('')
 const result=normalizeDocxTextRevisions(f.baseline,f.editor.getJSON(),f.anchors,f.editor.schema)
 expect(result.operations).toHaveLength(4);expect(f.ignored).toEqual([true])
 expect(replayDocxTextRevisions(f.baseline,result.operations,f.anchors,f.editor.schema)).toEqual(f.editor.getJSON())
 expect(f.editor.commands.undo()).toBe(true);expect(f.editor.getJSON()).toEqual(f.baseline)
 expect(f.editor.commands.redo()).toBe(true);expect(f.editor.state.doc.child(1).textContent).toBe('');expect(f.errors).toEqual([])
})
it('rejects only pending supported targets and keeps prior decisions in a separate history step',()=>{
 const f=fixture(true);f.controls.open();click('a','accept');f.controls.applyAll('reject')
 expect(f.editor.state.doc.child(0).textContent).toBe('😀同');expect(f.editor.state.doc.child(1).textContent).toBe('😀同同')
 const ops=normalizeDocxTextRevisions(f.baseline,f.editor.getJSON(),f.anchors,f.editor.schema).operations
 expect(ops.find(op=>op.revisionId==='a')?.action).toBe('accept');expect(ops).toHaveLength(4)
 expect(f.editor.commands.undo()).toBe(true);expect(normalizeDocxTextRevisions(f.baseline,f.editor.getJSON(),f.anchors,f.editor.schema).operations).toHaveLength(1)
 expect(f.errors).toEqual([])
})
it('validates every authorized target before changing any paragraph and blocks locked batches',()=>{
 const f=fixture(true);f.controls.open();f.anchors[1].reviewTargets![0].sourceRange!.text='伪造'
 f.controls.applyAll('accept');expect(f.editor.getJSON()).toEqual(f.baseline);expect(f.ignored).toEqual([]);expect(f.errors).toHaveLength(1)
 const locked=fixture();locked.controls.open();locked.lock();locked.controls.applyAll('reject');expect(locked.editor.getJSON()).toEqual(locked.baseline);expect(locked.errors).toHaveLength(1)
})
it('labels supported-only scope and preserves unsupported revisions rather than claiming all resolved',()=>{
 const f=fixture(true);f.anchors[1].reviewTargets=[];f.anchors[1].revisionReadOnlyReason='复杂修订保留'
 f.controls.open()
 const button=document.querySelector<HTMLButtonElement>('[data-action="reject-all"]')!
 expect(button.textContent).toBe('拒绝所有支持的正文修订');button.click()
 expect(f.editor.state.doc.child(0).textContent).toBe('');expect(f.editor.state.doc.child(1).toJSON()).toEqual(f.baseline.content![1])
 expect(document.querySelector('[role="dialog"]')!.textContent).toContain('其他故事中的修订均保留')
 expect(document.querySelector('[role="status"]')!.textContent).toContain('复杂修订保留')
 expect(button.disabled).toBe(true);expect(f.errors).toEqual([])
})

it('每条AI修订入口绑定真实wrapper身份，不直接接受或拒绝',()=>{
 const open=vi.fn(),f=fixture(false,open);f.controls.open()
 const button=row('b').querySelector<HTMLButtonElement>('[data-action=ai-review-revision]')!
 expect(button.querySelector('svg')).not.toBeNull();button.click()
 expect(open).toHaveBeenCalledWith({blockId:'body',revisionId:'b'},'')
 expect(f.editor.getJSON()).toEqual(f.baseline);expect(f.ignored).toEqual([])
})
