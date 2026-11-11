import {afterEach,expect,it} from 'vitest'
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
