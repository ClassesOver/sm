// @vitest-environment jsdom
import {afterEach,expect,it} from 'vitest'
import {Editor,Node} from '@tiptap/core'
import {UndoRedo} from '@tiptap/extensions'
import {NativeDocxCrossReference,createDocxCrossReferenceControls,normalizeDocxCrossReferences,replayDocxCrossReferences,verifiedDocxCrossReferenceModel,assertDocxCrossReferencesBatch,type DocxCrossReferencesModel} from './docx-cross-reference'
const a='a'.repeat(64),b='b'.repeat(64),c='c'.repeat(64),d='d'.repeat(64),e='e'.repeat(64),f='f'.repeat(64)
const model:DocxCrossReferencesModel={sourceSha256:a,sourceId:b,readOnlyReason:null,targets:[{targetId:c,blockIndex:0,paragraphOrdinal:0,expectedParagraphSha256:d,text:'可信 😀 原文',readOnlyReason:null},{targetId:e,blockIndex:1,paragraphOrdinal:0,expectedParagraphSha256:f,text:'Alpha 😀 Beta',readOnlyReason:null}],bookmarks:[{bookmarkId:a,name:'Target',readOnlyReason:null,ranges:[{targetId:c,expectedParagraphSha256:d,from:3,to:5,text:'😀'}]}]}
const op={kind:'insertCrossReference',sourceId:b,bookmarkId:a,targetId:e,expectedParagraphSha256:f,offset:6}
const cleanup:(()=>void)[]=[];afterEach(()=>{cleanup.splice(0).forEach(f=>f());document.body.replaceChildren()})
function fixture(m=model){
 const root=document.body.appendChild(document.createElement('div')),errors:unknown[]=[]
 const Doc=Node.create({name:'doc',topNode:true,content:'block+'}),P=Node.create({name:'docParagraph',group:'block',content:'inline*',addAttributes:()=>({docxIndex:{default:0}}),renderHTML:()=>['p',0]}),Text=Node.create({name:'text',group:'inline'})
 const editor=new Editor({editorProps:{handleScrollToSelection:()=>true},element:root.appendChild(document.createElement('div')),extensions:[Doc,P,Text,UndoRedo,NativeDocxCrossReference],content:{type:'doc',content:m.targets.map(t=>({type:'docParagraph',attrs:{docxIndex:t.blockIndex},content:[{type:'text',text:t.text}]}))}})
 const baseline=editor.getJSON(),collect=(doc:any)=>normalizeDocxCrossReferences(baseline,doc,m).operations,controls=createDocxCrossReferenceControls({editor,container:root,model:m,collectOperations:collect,readOnlyReason:()=>null,onError:error=>errors.push(error)})
 cleanup.push(()=>{controls.dispose();editor.destroy()});return{root,editor,baseline,collect,controls,errors}
}
it('UI inserts precise trusted cached range in one UndoRedo transaction and replays exactly',()=>{
 const x=fixture();x.editor.commands.setTextSelection(17);x.controls.open();x.root.querySelector<HTMLButtonElement>('[data-cross-reference-insert]')!.click()
 expect(x.collect(x.editor.getJSON())).toEqual([op]);expect(x.root.textContent).toContain('😀');const current=x.editor.getJSON();expect(normalizeDocxCrossReferences(x.baseline,current,model).current).toEqual(x.baseline)
 expect(replayDocxCrossReferences(x.baseline,[op],model)).toEqual(current);expect(x.editor.commands.undo()).toBe(true);expect(x.editor.getJSON()).toEqual(x.baseline);expect(x.editor.commands.redo()).toBe(true);expect(x.editor.getJSON()).toEqual(current);expect(x.errors).toEqual([])
})
it('rejects forged cache/shape, illegal intent, mixed batches and unauthorized structural changes',()=>{
 const x=fixture(),projected=replayDocxCrossReferences(x.baseline,[op],model)
 const forged=structuredClone(projected);forged.content![1].content!.find(n=>n.type==='docxCrossReference')!.attrs!.text='forged';expect(()=>normalizeDocxCrossReferences(x.baseline,forged,model)).toThrow()
 const altered=structuredClone(projected);altered.content![1].content![0].text='forged';expect(()=>normalizeDocxCrossReferences(x.baseline,altered,model)).toThrow()
 for(const operation of [{...op,sourceId:f},{...op,preview:'forged'},{...op,offset:7},{...op,bookmarkId:f},{...op,targetId:c,expectedParagraphSha256:d,offset:1}])expect(()=>replayDocxCrossReferences(x.baseline,[operation],model)).toThrow()
 expect(()=>replayDocxCrossReferences(x.baseline,[op,op],model)).toThrow();expect(()=>assertDocxCrossReferencesBatch([op,{kind:'replaceText'}])).toThrow()
 const injected=structuredClone(x.baseline);injected.content![0].attrs!.nativeCrossReferenceOperations=[op];expect(()=>normalizeDocxCrossReferences(x.baseline,injected,model)).toThrow()
})
it('locks UI and refuses stale caret, unsaved text and already pending intent',()=>{
 const x=fixture();x.editor.commands.setTextSelection(2);x.controls.open();x.root.querySelector<HTMLButtonElement>('[data-cross-reference-insert]')!.click();expect(x.errors).toHaveLength(1);expect(x.collect(x.editor.getJSON())).toEqual([])
 x.editor.commands.setTextSelection(17);x.editor.setEditable(false);x.controls.refresh();expect(x.root.querySelector<HTMLButtonElement>('[data-cross-reference-insert]')!.disabled).toBe(true)
 x.editor.setEditable(true);x.controls.refresh();x.root.querySelector<HTMLButtonElement>('[data-cross-reference-insert]')!.click();expect(x.collect(x.editor.getJSON())).toEqual([op]);x.controls.refresh();expect(x.root.querySelector<HTMLButtonElement>('[data-cross-reference-insert]')!.disabled).toBe(true)
})
it('model verifier rejects duplicate names, stale range text and split surrogate boundaries',()=>{
 expect(verifiedDocxCrossReferenceModel(model,a)).toEqual(model)
 for(const value of [{...model,sourceSha256:f},{...model,bookmarks:[model.bookmarks[0],{...model.bookmarks[0],bookmarkId:f}]},{...model,bookmarks:[{...model.bookmarks[0],ranges:[{...model.bookmarks[0].ranges[0],text:'forged'}]}]},{...model,bookmarks:[{...model.bookmarks[0],ranges:[{...model.bookmarks[0].ranges[0],from:4,text:'x'}]}]}])expect(()=>verifiedDocxCrossReferenceModel(value,a)).toThrow()
})
it('numeric XML entities align with real parseDocx and PM text',async()=>{
 const {parseDocx,readSections}=await import('@genoffice/docx-engine'),{buildDocx}=await import('../../../reporting/doc_engine/packages/docx-engine/tests/helpers/build-docx'),{spawnSync}=await import('node:child_process'),{resolve}=await import('node:path'),{blocksToPmDoc,pmDocOptions}=await import('./vendor/genoffice-docs/apps/docs/src/renderer/editor/convert'),{editorExtensions}=await import('./vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions')
 const inspectDocxCrossReferences=async(bytes:Uint8Array)=>{const script='import {inspectDocxCrossReferences} from "./bridge/docx-cross-reference.ts";let input="";for await(const part of process.stdin)input+=part;process.stdout.write(JSON.stringify(await inspectDocxCrossReferences(new Uint8Array(JSON.parse(input)))));',result=spawnSync(process.execPath,['--import','tsx','--input-type=module','-e',script],{cwd:resolve(process.cwd(),'../../reporting/doc_engine'),input:JSON.stringify(Array.from(bytes)),encoding:'utf8',timeout:15000});expect(result.status,result.stderr).toBe(0);return JSON.parse(result.stdout) as DocxCrossReferencesModel}
 const bytes=await buildDocx({bodyXml:'<w:p><w:bookmarkStart w:id="1" w:name="Target"/><w:r><w:t>&#22270;&#x1F600;&#38;lt;</w:t></w:r><w:bookmarkEnd w:id="1"/></w:p><w:p><w:r><w:t>A&#x1F600;B</w:t></w:r></w:p>'}),m=await inspectDocxCrossReferences(bytes),parsed=await parseDocx(bytes),editor=new Editor({extensions:[...editorExtensions,NativeDocxCrossReference],content:blocksToPmDoc(parsed.blocks,readSections(parsed),pmDocOptions(parsed))})
 try{const baseline=editor.getJSON(),t=m.targets[1];expect(editor.state.doc.child(0).textContent).toBe('图😀&lt;');expect(editor.state.doc.child(1).textContent).toBe('A😀B');expect(m.targets.map(t=>t.text)).toEqual(['图😀&lt;','A😀B']);const operation={kind:'insertCrossReference',sourceId:m.sourceId!,bookmarkId:m.bookmarks[0].bookmarkId,targetId:t.targetId,expectedParagraphSha256:t.expectedParagraphSha256,offset:3},projected=replayDocxCrossReferences(baseline,[operation],m);expect(normalizeDocxCrossReferences(baseline,projected,m).current).toEqual(baseline);expect(projected.content![1].content!.find(n=>n.type==='docxCrossReference')!.attrs!.text).toBe('图😀&lt;')}finally{editor.destroy()}
},20000)
