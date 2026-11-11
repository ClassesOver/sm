import {afterEach,expect,it} from 'vitest'
import {Editor,Node} from '@tiptap/core'
import {UndoRedo} from '@tiptap/extensions'
import {NativeDraft} from './native-draft'
import {createDocxBookmarksControls,normalizeDocxBookmarks,replayDocxBookmarks,selectedDocxBookmarkRanges,type DocxBookmarksModel} from './docx-bookmarks'
const sha='a'.repeat(64),sourceId='b'.repeat(64),targetId='c'.repeat(64)
const model:DocxBookmarksModel={sourceSha256:sha,sourceId,readOnlyReason:null,bookmarks:[],targets:[{targetId,blockIndex:0,paragraphOrdinal:0,expectedParagraphSha256:'d'.repeat(64),text:'Alpha 😀 Beta Gamma',readOnlyReason:null}]}
const cleanup:(()=>void)[]=[];afterEach(()=>{cleanup.splice(0).forEach(f=>f());document.body.replaceChildren()})
function fixture(m=model){
 const root=document.body.appendChild(document.createElement('div')),errors:unknown[]=[],memory=new Map<string,string>()
 const draft=new NativeDraft({documentId:'bookmark',revision:1,sourceSha256:sha,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},{getItem:k=>memory.get(k)??null,setItem:(k,v)=>{memory.set(k,v)},removeItem:k=>{memory.delete(k)}})
 const Doc=Node.create({name:'doc',topNode:true,content:'block+',addAttributes:()=>({nativeBookmarkOperations:{default:null}})}),Paragraph=Node.create({name:'docParagraph',group:'block',content:'inline*',addAttributes:()=>({docxIndex:{default:0}}),renderHTML:()=>['p',0]}),Text=Node.create({name:'text',group:'inline'})
 const editor=new Editor({element:root.appendChild(document.createElement('div')),extensions:[Doc,Paragraph,Text,UndoRedo],content:{type:'doc',content:m.targets.map(t=>({type:'docParagraph',attrs:{docxIndex:t.blockIndex},...(t.text?{content:[{type:'text',text:t.text}]}:{})}))}})
 const baseline=editor.getJSON(),collect=(doc:any)=>normalizeDocxBookmarks(baseline,doc,m).operations
 editor.on('update',()=>draft.setOperations(collect(editor.getJSON())))
 const controls=createDocxBookmarksControls({editor,container:root,model:m,collectOperations:collect,readOnlyReason:()=>null,onError:e=>errors.push(e)})
 cleanup.push(()=>{controls.dispose();editor.destroy()});return{root,editor,draft,baseline,controls,errors}
}
it('creates exact selection through UI with PM UndoRedo, deletion and recovery',()=>{
 const f=fixture();f.editor.commands.setTextSelection({from:7,to:14});f.controls.open()
 f.root.querySelector<HTMLInputElement>('[data-bookmark-name]')!.value='精确Bookmark';f.root.querySelector<HTMLButtonElement>('[data-bookmark-add]')!.click()
 expect(f.draft.operations).toEqual([{kind:'createBookmark',sourceId,name:'精确Bookmark',ranges:[{targetId,expectedParagraphSha256:'d'.repeat(64),from:6,to:13,text:'😀 Beta'}]}])
 expect(f.editor.state.doc.textContent).toBe(model.targets[0].text)
 f.editor.commands.undo();expect(f.draft.operations).toEqual([]);f.editor.commands.redo();expect(f.draft.operations).toHaveLength(1)
 expect(normalizeDocxBookmarks(f.baseline,replayDocxBookmarks(f.baseline,f.draft.operations,model),model).operations).toEqual(f.draft.operations)
 f.root.querySelector<HTMLButtonElement>('[data-bookmark-go]')!.click();expect(f.editor.state.selection.from).toBe(7);expect(f.editor.state.selection.to).toBe(14)
 f.root.querySelector<HTMLButtonElement>('[data-bookmark-delete]')!.click();expect(f.draft.operations).toEqual([]);f.editor.commands.undo();expect(f.draft.operations).toHaveLength(1);expect(f.errors).toEqual([])
})
it('lists readonly objects and deletes only trustworthy existing range, Undo restores it',()=>{
 const range={targetId,expectedParagraphSha256:'d'.repeat(64),from:0,to:5,text:'Alpha'},m={...model,bookmarks:[{bookmarkId:'e'.repeat(64),name:'Existing',ranges:[range],readOnlyReason:null},{bookmarkId:'f'.repeat(64),name:'Complex',ranges:[],readOnlyReason:'复杂锚点'}]}
 const f=fixture(m);f.controls.open();const remove=f.root.querySelectorAll<HTMLButtonElement>('[data-bookmark-delete]');expect(remove[1].disabled).toBe(true);remove[0].click()
 expect(f.draft.operations).toEqual([{kind:'deleteBookmark',sourceId,bookmarkId:'e'.repeat(64)}]);f.editor.commands.undo();expect(f.draft.operations).toEqual([])
})
it('rejects caret, surrogate split, stale body, duplicate name and foreign identities',()=>{
 const f=fixture();f.editor.commands.setTextSelection(3);expect(()=>selectedDocxBookmarkRanges(f.editor,model)).toThrow()
 f.editor.commands.setTextSelection({from:8,to:14});expect(()=>selectedDocxBookmarkRanges(f.editor,model)).toThrow()
 f.editor.commands.setTextSelection({from:7,to:14});const ranges=selectedDocxBookmarkRanges(f.editor,model)
 expect(()=>replayDocxBookmarks(f.baseline,[{kind:'createBookmark',sourceId:'f'.repeat(64),name:'A',ranges}],model)).toThrow()
 expect(()=>replayDocxBookmarks(f.baseline,[{kind:'createBookmark',sourceId,name:'A',ranges},{kind:'createBookmark',sourceId,name:'A',ranges}],model)).toThrow()
 f.editor.commands.insertContent('changed');expect(()=>selectedDocxBookmarkRanges(f.editor,model)).toThrow()
})
it('keeps exact cross paragraph selection including empty middle paragraph',()=>{
 const m={...model,targets:[model.targets[0],{...model.targets[0],targetId:'e'.repeat(64),blockIndex:1,text:''},{...model.targets[0],targetId:'f'.repeat(64),blockIndex:2,text:'Second'}]},f=fixture(m)
 f.editor.commands.setTextSelection({from:3,to:27});expect(selectedDocxBookmarkRanges(f.editor,m).map(r=>({from:r.from,to:r.to,text:r.text}))).toEqual([{from:2,to:19,text:'pha 😀 Beta Gamma'},{from:0,to:0,text:''},{from:0,to:3,text:'Sec'}])
})
it('preserves bookmark buttons through mousedown focus transaction so real click commits deletion',()=>{
 const range={targetId,expectedParagraphSha256:'d'.repeat(64),from:0,to:5,text:'Alpha'},m={...model,bookmarks:[{bookmarkId:'e'.repeat(64),name:'Existing',ranges:[range],readOnlyReason:null}]},f=fixture(m)
 f.controls.open();const button=f.root.querySelector<HTMLButtonElement>('[data-bookmark-delete]')!
 // Browser default focus on mousedown blurs PM; its focus transaction refreshes the list.
 const down=new MouseEvent('mousedown',{bubbles:true,cancelable:true});button.dispatchEvent(down)
 if(!down.defaultPrevented)f.editor.commands.setMeta('blur',{event:new FocusEvent('blur')})
 button.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));if(button.isConnected)button.click()
 expect(down.defaultPrevented).toBe(true);expect(f.draft.operations).toEqual([{kind:'deleteBookmark',sourceId,bookmarkId:'e'.repeat(64)}])
})
