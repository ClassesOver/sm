import {readFileSync} from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import {afterEach,expect,it} from 'vitest'
import {Editor,Extension} from '@tiptap/core'
import {Plugin} from '@tiptap/pm/state'
import {editorExtensions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import {docxOperations,type DocxAnchor,type DocxPmNode} from './docx-operations'
import {normalizeDocxTextRevisions,projectDocxTextRevisions} from './docx-text-revisions'
import {assertDocxTextRevisionBatch} from './docx-text-revisions-core'
import {assertDocxTrackedChangesBatch,normalizeDocxTrackedChanges} from './docx-tracked-changes'
import {docxTrackedInputProjection} from './docx-tracked-input-guard'
import {normalizePlainDocxRuns} from './docx-plain-paragraph-runs'
import {normalizeDocxNotes,notesOperationsOf,type DocxNotesModel} from './docx-notes'
import {docxNativeOperationsOf} from './docx-native-history'
import {commentTextOperationsOf} from './docx-comment-text'

// 执行 main 实际闭包；隔离布局启动，保留真实 PM、投影及 notes/plain fallback。
const source=ts.createSourceFile('docx-main.tsx',readFileSync('src/docx-main.tsx','utf8'),ts.ScriptTarget.Latest,true)
const declarations=new Map<string,string>()
let filterBody=''
const visit=(node:ts.Node)=>{
 if(ts.isVariableDeclaration(node)&&ts.isIdentifier(node.name)&&['collectOperationsUnchecked','collectOperations'].includes(node.name.text))declarations.set(node.name.text,node.parent.parent.getText(source))
 if(ts.isMethodDeclaration(node)&&node.name.getText(source)==='filterTransaction')filterBody=node.body!.getText(source)
 ts.forEachChild(node,visit)
}
visit(source)
if(declarations.size!==2)throw new Error('main collectOperations closures not found')
const code=ts.transpileModule(`${declarations.get('collectOperationsUnchecked')}\n${declarations.get('collectOperations')}\nglobalThis.collect = collectOperations;globalThis.filterTransaction=(transaction)=>${filterBody}`,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText
const editors:Editor[]=[]
afterEach(()=>editors.splice(0).forEach(editor=>editor.destroy()))
function setup(withNotes:boolean,targetCount=1,plainBold=false){
 const intent=Extension.create({name:'testRevisionIntent',addGlobalAttributes:()=>[{types:['docParagraph'],attributes:{nativeTextRevisionOperations:{default:null,rendered:false}}}]})
 const editor=new Editor({extensions:[...editorExtensions,intent],editorProps:{handleScrollToSelection:()=>true},content:{type:'doc',content:[
  {type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'前'},{type:'text',text:'新增'.repeat(targetCount),marks:[{type:'ins',attrs:{author:'甲',date:null,move:null}}]},{type:'text',text:'后'}]},
  {type:'docParagraph',attrs:{docxIndex:1},content:[{type:'text',text:'abc',...(plainBold?{marks:[{type:'bold'}]}:{})}]},
 ]}})
 editors.push(editor)
 const baseline=editor.getJSON() as DocxPmNode
 const anchors:DocxAnchor[]=[{docxIndex:0,blockId:'review',expectedObjectSha256:'sha-review',editable:false,reviewTargets:Array.from({length:targetCount},(_,index)=>({blockId:'review',expectedObjectSha256:'sha-review',revisionId:index?`wrapper-${index}`:'wrapper',originalRevisionId:'7',type:'insertion' as const,author:'甲',date:null,sourceRange:{from:1+index*2,to:3+index*2,text:'新增'}}))},
  {docxIndex:1,blockId:'plain',expectedObjectSha256:'sha-plain',editable:true}]
 const notesModel:DocxNotesModel|undefined=withNotes?{footnotes:[],endnotes:[],referenceBlocks:anchors.map(a=>({blockId:a.blockId,expectedObjectSha256:a.expectedObjectSha256,editable:a.editable}))}:undefined
 const op={kind:'resolveTextRevision',blockId:'review',expectedObjectSha256:'sha-review',revisionId:'wrapper',action:'reject'}
 const live=structuredClone(baseline)
 live.content![0]=projectDocxTextRevisions(baseline.content![0],anchors[0],anchors[0].reviewTargets!.map(target=>({...op,revisionId:target.revisionId})),editor.schema)
 live.content![1].content=[{type:'text',text:'a'},{type:'text',text:'新字',marks:[{type:'bold'}]},{type:'text',text:'bc'}]
 const pass=(_baseline:DocxPmNode,current:DocxPmNode)=>({current,operations:[]})
 const sandbox=vm.createContext({baseline,anchors,notesModel,editor,ready:true,refreshing:false,saving:false,draft:{saving:false,closed:false},context:{editingEnabled:true},reportError:()=>{},parsed:{styles:new Map()},stylesPaneModel:undefined,crossReferencesModel:undefined,captionSource:undefined,bookmarksModel:undefined,tocSource:undefined,commentThreadsModel:undefined,commentRepliesModel:undefined,commentCreationModel:undefined,commentsModel:undefined,pageColorModel:undefined,watermarkModel:undefined,sectionOperation:()=>[],headerFooterOperations:()=>[],docxNativeOperationsOf,commentTextOperationsOf,richPasteSource:{normalize:pass},equationSource:{normalize:pass},
  currentStyles:()=>new Map(),stylesPaneOperations:()=>[],normalizeStylesPane:pass,normalizeDocxCrossReferences:pass,normalizeDocxCaption:pass,normalizeDocxBookmarks:pass,normalizeDocxToc:pass,
  normalizeDocxCommentThreads:pass,normalizeDocxCommentReplies:pass,normalizeDocxCommentCreation:pass,normalizeDocxCommentText:pass,normalizeDocxPictures:(_baseline:DocxPmNode,current:DocxPmNode)=>({baseline,current,operations:[]}),normalizeDocxDropCaps:(_baseline:DocxPmNode,current:DocxPmNode)=>({baseline,current,operations:[]}),docxPageColorOperations:()=>[],docxWatermarkOperations:()=>[],
  assertDocxBookmarksBatch:()=>{},assertDocxTocBatch:()=>{},assertDocxCrossReferencesBatch:()=>{},assertDocxCaptionBatch:()=>{},assertDocxCommentThreadBatch:()=>{},assertDocxCommentReplyBatch:()=>{},assertDocxCommentCreationBatch:()=>{},assertDocxCommentTextBatch:()=>{},
  docxOperations,normalizePlainDocxRuns,normalizeDocxNotes,notesOperationsOf,normalizeDocxTextRevisions,assertDocxTextRevisionBatch,normalizeDocxTrackedChanges,assertDocxTrackedChangesBatch,docxTrackedInputProjection})
 vm.runInContext(code,sandbox)
 return {collect:sandbox.collect as (node:DocxPmNode)=>Record<string,unknown>[],filterTransaction:sandbox.filterTransaction,editor,live,op,baseline,anchors,schema:editor.schema}
}
for(const withNotes of [false,true])it(`main ${withNotes?'notes':'plain'} guard lets the native recorder finish a second disjoint keyboard transaction`,()=>{
 const f=setup(withNotes),start=f.editor.state.doc.child(0).nodeSize+1
 f.editor.registerPlugin(new Plugin({filterTransaction:f.filterTransaction}))
 f.editor.storage.trackChanges.enabled=true;f.editor.storage.trackChanges.author='user'
 f.editor.commands.insertContentAt(start,'新😀')
 expect(f.collect(f.editor.getJSON()).filter(op=>op.kind==='recordTextRevision')).toHaveLength(1)
 f.editor.commands.deleteRange({from:start+4,to:start+5})
 expect(f.collect(f.editor.getJSON()).filter(op=>op.kind==='recordTextRevision')).toEqual([
  {kind:'recordTextRevision',blockId:'plain',expectedObjectSha256:'sha-plain',from:0,to:0,text:'新😀'},
  {kind:'recordTextRevision',blockId:'plain',expectedObjectSha256:'sha-plain',from:1,to:2,text:''},
 ])
})
for(const withNotes of [false,true])it(`main ${withNotes?'notes':'plain'} guard keeps raw-input fallback within text and source permissions`,()=>{
 const f=setup(withNotes),start=f.editor.state.doc.child(0).nodeSize+1
 f.editor.registerPlugin(new Plugin({filterTransaction:f.filterTransaction}))
 f.editor.storage.trackChanges.enabled=true;f.editor.storage.trackChanges.author='user'
 f.editor.commands.insertContentAt(start,'新😀')
 const accepted=f.editor.getJSON()
 const reject=(transaction:Parameters<typeof docxTrackedInputProjection>[0])=>{f.editor.view.dispatch(transaction);expect(f.editor.getJSON()).toEqual(accepted)}
 reject(f.editor.state.tr.insertText('越权',2))
 reject(f.editor.state.tr.replaceWith(start+4,start+5,f.schema.text('伪',[f.schema.marks.bold.create()])))
 reject(f.editor.state.tr.insertText('x',start+4).insertText('y',start+6))
 reject(f.editor.state.tr.delete(start+4,start+5).setMeta('trackIgnore',true))
 reject(f.editor.state.tr.delete(start+4,start+5).setMeta('composition',1))
 reject(f.editor.state.tr.delete(start+1,start+2))
 f.anchors[1].editable=false
 reject(f.editor.state.tr.delete(start+4,start+5))
 f.anchors[1].editable=true;f.anchors[1].revisionReadOnlyReason='来源只读'
 reject(f.editor.state.tr.delete(start+4,start+5))
 expect(f.collect({...accepted,content:[accepted.content![0],f.baseline.content![1]]})).toEqual([])
})
it('main guard requires exact inherited marks in the raw-input fallback',()=>{
 const f=setup(true,1,true),start=f.editor.state.doc.child(0).nodeSize+1
 f.editor.registerPlugin(new Plugin({filterTransaction:f.filterTransaction}))
 f.editor.storage.trackChanges.enabled=true;f.editor.storage.trackChanges.author='user'
 f.editor.commands.insertContentAt(start,{type:'text',text:'新😀',marks:[{type:'bold'}]})
 const accepted=f.editor.getJSON()
 f.editor.view.dispatch(f.editor.state.tr.replaceWith(start+4,start+5,f.schema.text('X')))
 expect(f.editor.getJSON()).toEqual(accepted)
 f.editor.view.dispatch(f.editor.state.tr.replaceWith(start+4,start+5,f.schema.text('X',[f.schema.marks.bold.create()])))
 expect(f.collect(f.editor.getJSON()).filter(op=>op.kind==='recordTextRevision')).toEqual([
  {kind:'recordTextRevision',blockId:'plain',expectedObjectSha256:'sha-plain',from:0,to:0,text:'新😀'},
  {kind:'recordTextRevision',blockId:'plain',expectedObjectSha256:'sha-plain',from:1,to:2,text:'X'},
 ])
})
for(const withNotes of [false,true]){
 it(`main ${withNotes?'notes':'plain'} fallback preserves cross-paragraph text-format plan and strict revision`,()=>{
  const f=setup(withNotes),operations=f.collect(f.live)
  expect(operations).toHaveLength(2)
  expect(operations).toContainEqual(f.op)
  expect(operations).toContainEqual(expect.objectContaining({kind:'patchParagraphRuns',blockId:'plain',expectedObjectSha256:'sha-plain'}))
  expect(operations.some(op=>op.kind==='replaceParagraph'&&op.blockId==='review')).toBe(false)
 })
 it(`main ${withNotes?'notes':'plain'} fallback cannot swallow forged revision preview or identity`,()=>{
  const f=setup(withNotes),forged=structuredClone(f.live)
  forged.content![0].content![0].text='越权'
  expect(()=>f.collect(forged)).toThrow()
  const stale=structuredClone(f.live)
  ;(stale.content![0].attrs!.nativeTextRevisionOperations as Record<string,unknown>[])[0].revisionId='foreign'
  expect(()=>f.collect(stale)).toThrow()
 })
}

it('main collector emits a source-anchored tracked text operation without degrading it to a paragraph patch',()=>{
 const f=setup(false),tracked=structuredClone(f.live)
 tracked.content![1].content=[
  {type:'text',text:'a'},
  {type:'text',text:'b',marks:[{type:'del',attrs:{author:'forged',date:'forged',move:null}}]},
  {type:'text',text:'X',marks:[{type:'ins',attrs:{author:'forged',date:'forged',move:null}}]},
  {type:'text',text:'c'},
 ]
 const operations=f.collect(tracked)
 expect(operations).toContainEqual({kind:'recordTextRevision',blockId:'plain',expectedObjectSha256:'sha-plain',from:1,to:2,text:'X'})
 expect(operations.some(op=>op.kind==='patchParagraphRuns'&&op.blockId==='plain')).toBe(false)
 expect(operations.some(op=>op.kind==='recordTextRevision'&&('author'in op||'date'in op))).toBe(false)
})

for(const withNotes of [false,true]){
 it(`main ${withNotes?'notes':'plain'} validates a partial revision decision while leaving other source revisions intact`,()=>{
  const f=setup(withNotes,2),live=structuredClone(f.baseline)
  live.content![0]=projectDocxTextRevisions(f.baseline.content![0],f.anchors[0],[f.op],f.schema)
  expect(f.collect(live)).toEqual([f.op])
  const forged=structuredClone(live);forged.content![0].content![0].text='篡改'
  expect(()=>f.collect(forged)).toThrow()
  const foreign=structuredClone(live)
  ;(foreign.content![0].attrs!.nativeTextRevisionOperations as Record<string,unknown>[])[0].revisionId='foreign'
  expect(()=>f.collect(foreign)).toThrow()
 })
 it(`main ${withNotes?'notes':'plain'} preserves two disjoint tracked edits in one paragraph`,()=>{
  const f=setup(withNotes),tracked=structuredClone(f.live)
  tracked.content![1].content=[
   {type:'text',text:'新😀',marks:[{type:'ins',attrs:{author:'forged',date:'forged',move:null}}]},
   {type:'text',text:'a'},
   {type:'text',text:'b',marks:[{type:'del',attrs:{author:'forged',date:'forged',move:null}}]},
   {type:'text',text:'c'},
  ]
  const operations=f.collect(tracked)
  expect(operations).toHaveLength(3)
  expect(operations).toContainEqual(f.op)
  expect(operations.filter(op=>op.kind==='recordTextRevision')).toEqual([
   {kind:'recordTextRevision',blockId:'plain',expectedObjectSha256:'sha-plain',from:0,to:0,text:'新😀'},
   {kind:'recordTextRevision',blockId:'plain',expectedObjectSha256:'sha-plain',from:1,to:2,text:''},
  ])
  expect(operations.some(op=>op.kind==='patchParagraphRuns'&&op.blockId==='plain')).toBe(false)
 })
}

for(const withNotes of [false,true]){
 it(`main ${withNotes?'notes':'plain'} counts merged revision and paragraph-run operations at the 500 boundary`,()=>{
  const allowed=setup(withNotes,499),operations=allowed.collect(allowed.live)
  expect(operations).toHaveLength(500)
  expect(operations.filter(op=>op.kind==='resolveTextRevision')).toHaveLength(499)
  expect(operations.filter(op=>op.kind==='patchParagraphRuns')).toHaveLength(1)
  const overflow=setup(withNotes,500)
  expect(()=>overflow.collect(overflow.live)).toThrow(/500/)
 })
}
