import type {Editor} from '@tiptap/core'
import type {Schema} from '@tiptap/pm/model'
import {EditorState,NodeSelection,Selection,type Transaction} from '@tiptap/pm/state'
import {closeHistory} from '@tiptap/pm/history'
import {CellSelection,TableMap,deleteTable,selectedRect} from '@tiptap/pm/tables'
import {splitTableAtSelection} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/table-ops'
import type {DocxPmNode} from './docx-operations'

export type DocxTableLifecycleOperation={kind:'deleteTable';blockId:string;expectedObjectSha256:string}|{kind:'splitTable';blockId:string;expectedObjectSha256:string;row:number}
export interface DocxTableLifecycleAnchor {docxIndex:number;blockId:string;expectedObjectSha256:string;tableLifecycleEditable?:boolean;tableLifecycleReadOnlyReason?:string|null}
export type DocxTableLifecycleAction='table-delete'|'table-split-table'
const fail=(message='表格删除或拆分的来源、操作或文档已改变，请先保存'):never=>{throw new Error(message)}
const stable=(v:unknown):string=>JSON.stringify(v,(_key,value)=>value&&typeof value==='object'&&!Array.isArray(value)?Object.fromEntries(Object.keys(value).sort().map(k=>[k,value[k]])):value)
const same=(a:unknown,b:unknown)=>stable(a)===stable(b)
/** Kind recognition deliberately includes malformed lifecycle records so validation cannot skip them. */
export function isDocxTableLifecycleOperation(value:unknown):value is DocxTableLifecycleOperation {
 return !!value&&typeof value==='object'&&['deleteTable','splitTable'].includes((value as {kind:string}).kind)
}
export function assertDocxTableLifecycleBatch(operations:readonly unknown[]):void {
 if(!operations.some(isDocxTableLifecycleOperation))return
 if(operations.length!==1)fail('表格删除或拆分须单独保存，不能混合其他操作')
 const op=operations[0] as DocxTableLifecycleOperation
 const keys=op.kind==='splitTable'?['kind','blockId','expectedObjectSha256','row']:['kind','blockId','expectedObjectSha256']
 if(Object.keys(op).length!==keys.length||Object.keys(op).some(k=>!keys.includes(k))||typeof op.blockId!=='string'||!op.blockId||typeof op.expectedObjectSha256!=='string'||!/^[a-f0-9]{64}$/.test(op.expectedObjectSha256)||op.kind==='splitTable'&&(!Number.isSafeInteger(op.row)||op.row<1))fail()
}
function projection(original:DocxPmNode,op:DocxTableLifecycleOperation,anchors:readonly DocxTableLifecycleAnchor[],schema:Schema):Transaction {
 assertDocxTableLifecycleBatch([op])
 const matches=anchors.filter(a=>a.blockId===op.blockId)
 if(matches.length!==1)fail()
 const anchor=matches[0]
 if(anchor.tableLifecycleEditable!==true||anchor.expectedObjectSha256!==op.expectedObjectSha256||!Number.isSafeInteger(anchor.docxIndex)||anchors.filter(a=>a.docxIndex===anchor.docxIndex).length!==1)fail(anchor.tableLifecycleReadOnlyReason?.startsWith('docx_table_lifecycle_')?'此表格包含暂不能安全保留的结构或标记':anchor.tableLifecycleReadOnlyReason??undefined)
 const journal=original.attrs?.nativeDocxOperations
 if(journal!=null&&(!Array.isArray(journal)||journal.length))fail('请先保存已有修改，再删除或拆分表格')
 const doc=schema.nodeFromJSON(original);doc.check()
 const found:{pos:number;node:typeof doc}[]=[]
 doc.forEach((node,pos)=>{if(node.attrs.docxIndex===anchor.docxIndex)found.push({pos,node})})
 if(found.length!==1||found[0].node.type.name!=='docTable')fail()
 const {pos, node:table}=found[0],map=TableMap.get(table)
 if(map.problems?.length||map.height<1||map.width<1||map.height>100||map.width>30||map.height*map.width>1000)fail()
 // The source command handles merged tables too; this contract admits only ordinary signed tables.
 for(const offset of new Set(map.map)){
  const cell=table.nodeAt(offset)!
  if(cell.attrs.colspan!==1||cell.attrs.rowspan!==1||cell.attrs.gridGap)fail()
  cell.descendants(n=>{if(['docNestedTable','docTable'].includes(n.type.name))fail()})
 }
 if(op.kind==='splitTable'&&op.row>=map.height)fail()
 // PM deleteTable resolves the table from an interior cell even for a UI table NodeSelection.
 const selection=CellSelection.create(doc,pos+1+map.map[(op.kind==='splitTable'?op.row:0)*map.width])
 const state=EditorState.create({doc,selection}),captured:{tr?:Transaction}={}
 const command=op.kind==='deleteTable'?deleteTable:splitTableAtSelection()
 if(!command(state,tr=>{captured.tr=tr})||!captured.tr)fail()
 captured.tr!.setDocAttribute('nativeDocxOperations',[structuredClone(op)])
 captured.tr!.doc.check()
 return captured.tr!
}
/** Replay always starts from the immutable source, never an already edited table. */
export function replayDocxTableLifecycle(original:DocxPmNode,operations:readonly unknown[],anchors:readonly DocxTableLifecycleAnchor[],schema:Schema):DocxPmNode {
 assertDocxTableLifecycleBatch(operations)
 if(!operations.some(isDocxTableLifecycleOperation))return structuredClone(original)
 return projection(original,operations[0] as DocxTableLifecycleOperation,anchors,schema).doc.toJSON() as DocxPmNode
}
/** Full-document comparison disallows extra body edits, forged lower identities and mixed journals. */
export function normalizeDocxTableLifecycle(original:DocxPmNode,current:DocxPmNode,anchors:readonly DocxTableLifecycleAnchor[],schema:Schema):{current:DocxPmNode;operations:DocxTableLifecycleOperation[]} {
 const journal=current.attrs?.nativeDocxOperations
 if(!Array.isArray(journal)||!journal.some(isDocxTableLifecycleOperation))return {current,operations:[]}
 assertDocxTableLifecycleBatch(journal)
 const operations=structuredClone(journal) as DocxTableLifecycleOperation[]
 if(!same(current,replayDocxTableLifecycle(original,operations,anchors,schema)))fail('表格删除或拆分后不能混入其他修改，请撤销或先保存')
 return {current:structuredClone(original),operations}
}
export function createDocxTableLifecycleControls(options:{editor:Editor;baseline:DocxPmNode;anchors:readonly DocxTableLifecycleAnchor[];reason:()=>string|null;onError:(error:unknown)=>void}) {
 const {editor,baseline,anchors}=options
 const sourceSnapshot=structuredClone(baseline),anchorSnapshot=structuredClone(anchors)
 function operation(action:DocxTableLifecycleAction):DocxTableLifecycleOperation {
  if(!['table-delete','table-split-table'].includes(action))fail()
  const locked=options.reason();if(locked)fail(locked)
  if(!same(baseline,sourceSnapshot)||!same(anchors,anchorSnapshot))fail('文档或表格来源已改变，请重新加载')
  if(!editor.isEditable||editor.isDestroyed||editor.view.composing)fail('当前不可编辑或正在输入，请稍后重试')
  if(editor.storage.trackChanges?.enabled)fail('修订模式暂不支持删除或拆分表格')
  if(!same(editor.getJSON(),baseline))fail('请先保存已有修改，再删除或拆分表格')
  const selection=editor.state.selection
  let table,tablePos:number,row=0
  if(selection instanceof NodeSelection&&selection.node.type.name==='docTable'){table=selection.node;tablePos=selection.from}
  else {try{const rect=selectedRect(editor.state);table=rect.table;tablePos=rect.tableStart-1;row=rect.top}catch{fail('请将光标放入表格或选择表格')}}
  if(editor.state.doc.resolve(tablePos!).depth!==0)fail('仅支持正文顶层表格')
  const anchor=anchors.find(a=>a.docxIndex===table!.attrs.docxIndex)
  if(!anchor)fail()
  if(action==='table-split-table'&&row===0)fail('第一行不能作为拆分位置，请选择后续行')
  const op:DocxTableLifecycleOperation=action==='table-delete'?{kind:'deleteTable',blockId:anchor!.blockId,expectedObjectSha256:anchor!.expectedObjectSha256}:{kind:'splitTable',blockId:anchor!.blockId,expectedObjectSha256:anchor!.expectedObjectSha256,row}
  projection(baseline,op,anchors,editor.schema)
  return op
 }
 function run(action:DocxTableLifecycleAction):boolean {try{
   const op=operation(action),projected=projection(baseline,op,anchors,editor.schema)
   const tr=closeHistory(editor.state.tr)
   for(const step of projected.steps)tr.step(step)
   tr.setSelection(Selection.fromJSON(tr.doc,projected.selection.toJSON())).scrollIntoView()
   editor.view.dispatch(tr);editor.view.dispatch(closeHistory(editor.state.tr))
   return true
  }catch(e){options.onError(e);return false}}
 return {
  reason(action:DocxTableLifecycleAction):string|null {try{operation(action);return null}catch(e){return e instanceof Error?e.message:String(e)}},
  run,
  /** Own the source shortcut only within this editor and a top-level table selection.
   * An unavailable owned command is consumed so another PM keymap cannot bypass validation. */
  handleKey(event:KeyboardEvent):boolean {
   if(event.defaultPrevented||event.isComposing||event.keyCode===229||editor.isDestroyed||editor.view.composing
    ||event.key!=='Enter'||!event.shiftKey||!(event.ctrlKey||event.metaKey)||event.altKey)return false
   const dom=editor.view.dom,win=dom.ownerDocument.defaultView!
   const target=event.target instanceof win.Element?event.target:event.target instanceof win.Node?event.target.parentElement:null
   if(!target||!dom.contains(target)||target.closest('.ProseMirror')!==dom
    ||target.closest('input,textarea,select,button,[role=dialog],.doc-nested-table'))return false
   const uneditable=target.closest('[contenteditable=false]')
   if(uneditable&&uneditable!==dom)return false
   try {
    const selection=editor.state.selection
    const tablePos=selection instanceof NodeSelection&&selection.node.type.name==='docTable'?selection.from:selectedRect(editor.state).tableStart-1
    if(editor.state.doc.resolve(tablePos).depth!==0)return false
   }catch{return false}
   event.preventDefault();event.stopPropagation()
   run('table-split-table')
   return true
  },
  dispose() {},
 }
}
