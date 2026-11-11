import {readFileSync} from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import {afterEach,expect,it} from 'vitest'
import {Editor,Extension} from '@tiptap/core'
import {editorExtensions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import {docxOperations,type DocxAnchor,type DocxPmNode} from './docx-operations'
import {normalizeDocxTextRevisions,projectDocxTextRevisions} from './docx-text-revisions'
import {assertDocxTextRevisionBatch} from './docx-text-revisions-core'
import {normalizePlainDocxRuns} from './docx-plain-paragraph-runs'
import {normalizeDocxNotes,notesOperationsOf,type DocxNotesModel} from './docx-notes'

// 执行 main 实际闭包；隔离布局启动，保留真实 PM、投影及 notes/plain fallback。
const source=ts.createSourceFile('docx-main.tsx',readFileSync('src/docx-main.tsx','utf8'),ts.ScriptTarget.Latest,true)
const declarations=new Map<string,string>()
const visit=(node:ts.Node)=>{
 if(ts.isVariableDeclaration(node)&&ts.isIdentifier(node.name)&&['collectOperationsUnchecked','collectOperations'].includes(node.name.text))declarations.set(node.name.text,node.parent.parent.getText(source))
 ts.forEachChild(node,visit)
}
visit(source)
if(declarations.size!==2)throw new Error('main collectOperations closures not found')
const code=ts.transpileModule(`${declarations.get('collectOperationsUnchecked')}\n${declarations.get('collectOperations')}\nglobalThis.collect = collectOperations`,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText
const editors:Editor[]=[]
afterEach(()=>editors.splice(0).forEach(editor=>editor.destroy()))
function setup(withNotes:boolean,targetCount=1){
 const intent=Extension.create({name:'testRevisionIntent',addGlobalAttributes:()=>[{types:['docParagraph'],attributes:{nativeTextRevisionOperations:{default:null,rendered:false}}}]})
 const editor=new Editor({extensions:[...editorExtensions,intent],editorProps:{handleScrollToSelection:()=>true},content:{type:'doc',content:[
  {type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'前'},{type:'text',text:'新增'.repeat(targetCount),marks:[{type:'ins',attrs:{author:'甲',date:null,move:null}}]},{type:'text',text:'后'}]},
  {type:'docParagraph',attrs:{docxIndex:1},content:[{type:'text',text:'abc'}]},
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
 const sandbox=vm.createContext({baseline,anchors,notesModel,editor,parsed:{styles:new Map()},sectionOperation:()=>[],headerFooterOperations:()=>[],
  docxOperations,normalizePlainDocxRuns,normalizeDocxNotes,notesOperationsOf,normalizeDocxTextRevisions,assertDocxTextRevisionBatch})
 vm.runInContext(code,sandbox)
 return {collect:sandbox.collect as (node:DocxPmNode)=>Record<string,unknown>[],live,op}
}
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
