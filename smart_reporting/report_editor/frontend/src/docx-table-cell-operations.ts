import type {Editor} from '@tiptap/core'
import type {Node as PmNode,Schema} from '@tiptap/pm/model'
import {EditorState,NodeSelection,Selection,type Transaction} from '@tiptap/pm/state'
import {closeHistory} from '@tiptap/pm/history'
import {TableMap,selectedRect} from '@tiptap/pm/tables'
import type {DocxPmNode} from './docx-operations'
import {applyDocxTableCellChange,assertDocxTableCellChange,type DocxTableCellChange,type DocxTableCellRect} from './docx-table-cell-operations-core'
import {createModal} from './modal'
import {buttonClasses} from './button'

export type DocxTableCellOperation={kind:'editTableCells';blockId:string;expectedObjectSha256:string;change:DocxTableCellChange}
export interface DocxTableCellAnchor {docxIndex:number;blockId:string;expectedObjectSha256:string;tableCellsEditable?:boolean;tableCellsReadOnlyReason?:string|null;tableCellsWidthsTwips?:number[];tableCellsMaxWidthTwips?:number}
export type DocxTableCellAction='table-insert-cells'|'table-delete-cells'
const fail=(message='单元格操作的来源、操作或文档已改变，请先保存'):never=>{throw new Error(message)}
const stable=(v:unknown):string=>JSON.stringify(v,(_key,value)=>value&&typeof value==='object'&&!Array.isArray(value)?Object.fromEntries(Object.keys(value).sort().map(k=>[k,value[k]])):value)
const same=(a:unknown,b:unknown)=>stable(a)===stable(b)
export function isDocxTableCellOperation(value:unknown):value is DocxTableCellOperation {return !!value&&typeof value==='object'&&(value as {kind:string}).kind==='editTableCells'}
export function assertDocxTableCellOperationBatch(operations:readonly unknown[]):void {
 if(!operations.some(isDocxTableCellOperation))return
 if(operations.length!==1)fail('插入或删除单元格须单独保存，不能混合其他操作')
 const op=operations[0] as DocxTableCellOperation,keys=['kind','blockId','expectedObjectSha256','change']
 if(Array.isArray(op)||Object.keys(op).length!==keys.length||Object.keys(op).some(k=>!keys.includes(k))||typeof op.blockId!=='string'||!op.blockId||typeof op.expectedObjectSha256!=='string'||!/^[a-f0-9]{64}$/.test(op.expectedObjectSha256))fail()
 assertDocxTableCellChange(op.change)
}
function grid(table:PmNode,anchor:DocxTableCellAnchor){
 const widths=anchor.tableCellsWidthsTwips,max=anchor.tableCellsMaxWidthTwips
 if(anchor.tableCellsEditable!==true)fail(anchor.tableCellsReadOnlyReason?.startsWith('docx_table_cells_')?'此表格包含暂不能安全保留的结构或标记':anchor.tableCellsReadOnlyReason??undefined)
 if(table.type.name!=='docTable'||!Array.isArray(widths)||!widths.length||widths.some(w=>!Number.isSafeInteger(w)||w<=0||w>31680)||!Number.isSafeInteger(max)||max!<=0||max!>31680)fail()
 table.check();const map=TableMap.get(table)
 if(map.problems?.length||map.height<1||map.height>100||map.width<1||map.width>30||map.width*map.height>1000||map.width!==widths!.length)fail()
 for(const offset of new Set(map.map)){
  const cell=table.nodeAt(offset)!
  if(cell.attrs.colspan!==1||cell.attrs.rowspan!==1||cell.attrs.gridGap)fail()
  cell.descendants(n=>{if(['docTable','docNestedTable'].includes(n.type.name)||n.type.spec.tableRole==='table')fail()})
 }
 return {map,widths:widths!,max:max!}
}
/** Restore exact signed column widths before taking the immutable baseline. Other imported attributes stay intact. */
export function normalizeDocxTableCellSources(doc:DocxPmNode,anchors:readonly DocxTableCellAnchor[],schema:Schema):DocxPmNode {
 return {...doc,content:doc.content?.map(source=>{
  const matching=anchors.filter(a=>a.docxIndex===source.attrs?.docxIndex),anchor=matching[0]
  if(source.type!=='docTable'||anchor?.tableCellsEditable!==true)return source
  if(matching.length!==1)fail()
  const table=schema.nodeFromJSON(source),{map,widths}=grid(table,anchor),rows:PmNode[]=[]
  table.forEach((row,rowOffset)=>{const cells:PmNode[]=[];row.forEach((cell,offset)=>{const rect=map.findCell(rowOffset+1+offset);cells.push(cell.type.create({...cell.attrs,colwidth:widths.slice(rect.left,rect.right).map(w=>w/15)},cell.content,cell.marks))});rows.push(row.type.create(row.attrs,cells,row.marks))})
  return table.type.create(table.attrs,rows,table.marks).toJSON() as DocxPmNode
 })}
}
function source(original:DocxPmNode,blockId:string,sha:string,anchors:readonly DocxTableCellAnchor[],schema:Schema){
 const matches=anchors.filter(a=>a.blockId===blockId)
 if(matches.length!==1)fail()
 const anchor=matches[0]
 if(anchor.expectedObjectSha256!==sha||!Number.isSafeInteger(anchor.docxIndex)||anchor.docxIndex<0||anchors.filter(a=>a.docxIndex===anchor.docxIndex).length!==1)fail()
 const journal=original.attrs?.nativeDocxOperations
 if(journal!=null&&(!Array.isArray(journal)||journal.length))fail('请先保存已有修改，再插入或删除单元格')
 const doc=schema.nodeFromJSON(original);doc.check();const found:{pos:number;table:PmNode}[]=[]
 doc.forEach((node,pos)=>{if(node.attrs.docxIndex===anchor.docxIndex)found.push({pos,table:node})})
 if(found.length!==1)fail()
 const {pos,table}=found[0],{map,widths,max}=grid(table,anchor)
 for(const offset of new Set(map.map)){const cell=table.nodeAt(offset)!,rect=map.findCell(offset);if(!same(cell.attrs.colwidth,widths.slice(rect.left,rect.right).map(w=>w/15)))fail('表格来源列宽已改变，请重新加载')}
 return {doc,pos,table,map,max,anchor}
}
function projection(original:DocxPmNode,op:DocxTableCellOperation,anchors:readonly DocxTableCellAnchor[],schema:Schema):Transaction {
 assertDocxTableCellOperationBatch([op]);const {doc,pos,table,max}=source(original,op.blockId,op.expectedObjectSha256,anchors,schema)
 const replacement=applyDocxTableCellChange(table,op.change,max),tr=EditorState.create({doc}).tr
 if(replacement)tr.replaceWith(pos,pos+table.nodeSize,replacement);else tr.delete(pos,pos+table.nodeSize)
 tr.setDocAttribute('nativeDocxOperations',[structuredClone(op)]);tr.doc.check();return tr
}
/** Replay starts with the original full document; the shared core owns all table geometry. */
export function replayDocxTableCellOperation(original:DocxPmNode,operations:readonly unknown[],anchors:readonly DocxTableCellAnchor[],schema:Schema):DocxPmNode {
 assertDocxTableCellOperationBatch(operations)
 if(!operations.some(isDocxTableCellOperation))return structuredClone(original)
 return projection(original,operations[0] as DocxTableCellOperation,anchors,schema).doc.toJSON() as DocxPmNode
}
export function normalizeDocxTableCellOperation(original:DocxPmNode,current:DocxPmNode,anchors:readonly DocxTableCellAnchor[],schema:Schema):{current:DocxPmNode;operations:DocxTableCellOperation[]} {
 const journal=current.attrs?.nativeDocxOperations
 if(!Array.isArray(journal)||!journal.some(isDocxTableCellOperation))return {current,operations:[]}
 assertDocxTableCellOperationBatch(journal);const operations=structuredClone(journal) as DocxTableCellOperation[]
 if(!same(current,replayDocxTableCellOperation(original,operations,anchors,schema)))fail('单元格操作后不能混入其他修改，请撤销或先保存')
 return {current:structuredClone(original),operations}
}
export function createDocxTableCellControls(options:{editor:Editor;baseline:DocxPmNode;anchors:readonly DocxTableCellAnchor[];root?:HTMLElement;reason:()=>string|null;onError:(error:unknown)=>void}){
 const {editor,baseline,anchors}=options,sourceSnapshot=structuredClone(baseline),anchorSnapshot=structuredClone(anchors)
 let active:{close:()=>void}|null=null,disposed=false
 function context(action:DocxTableCellAction){
  if(disposed||!['table-insert-cells','table-delete-cells'].includes(action))fail()
  const locked=options.reason();if(locked)fail(locked)
  if(!same(baseline,sourceSnapshot)||!same(anchors,anchorSnapshot))fail('文档或表格来源已改变，请重新加载')
  if(!editor.isEditable||editor.isDestroyed||editor.view.composing)fail('当前不可编辑或正在输入，请稍后重试')
  if(editor.storage.trackChanges?.enabled)fail('修订模式暂不支持插入或删除单元格')
  if(!same(editor.getJSON(),baseline))fail('请先保存已有修改，再插入或删除单元格')
  const selection=editor.state.selection;let table:PmNode,tablePos:number,rect:DocxTableCellRect
  if(selection instanceof NodeSelection&&selection.node.type.name==='docTable'){table=selection.node;tablePos=selection.from;const map=TableMap.get(table);rect={top:0,left:0,bottom:map.height,right:map.width}}
  else {try{const selected=selectedRect(editor.state);table=selected.table;tablePos=selected.tableStart-1;rect={top:selected.top,left:selected.left,bottom:selected.bottom,right:selected.right}}catch{fail('请将光标放入表格或选择单元格')}}
  if(editor.state.doc.resolve(tablePos!).depth!==0)fail('仅支持正文顶层表格')
  const matching=anchors.filter(a=>a.docxIndex===table!.attrs.docxIndex);if(matching.length!==1)fail()
  const anchor=matching[0];source(baseline,anchor.blockId,anchor.expectedObjectSha256,anchors,editor.schema)
  return {anchor,rect:rect!,selection:selection.toJSON()}
 }
 function reason(action:DocxTableCellAction):string|null {try{context(action);return null}catch(e){return e instanceof Error?e.message:String(e)}}
 function run(action:DocxTableCellAction):boolean {try{
  const frozen=context(action);active?.close()
  const insert=action==='table-insert-cells',label=insert?'插入单元格':'删除单元格'
  const choices=insert?[['above','上方插入'],['below','下方插入'],['left','左侧插入'],['right','右侧插入']]:[['shiftLeft','右侧单元格左移'],['shiftUp','下方单元格上移'],['row','删除整行'],['column','删除整列']]
  let composing=false,closed=false,timer:ReturnType<typeof setInterval>|undefined
  const close=()=>{if(closed)return;closed=true;if(timer)clearInterval(timer);editor.off('transaction',refresh);editor.off('destroy',close);modal.remove();if(active?.close===close)active=null}
  const modal=createModal({root:options.root??editor.view.dom.ownerDocument.body,label,cardClass:'docx-table-property-dialog',closeLabel:`关闭${label}`,onRequestClose:close,content:`<h2>${label}</h2><form novalidate><div class="table-dialog-radios" role="radiogroup" aria-label="${insert?'插入位置':'删除方式'}">${choices.map(([value,text])=>`<label><input type="radio" name="table-cells-mode" value="${value}" ${value===(insert?'below':'shiftLeft')?'checked':''}>${text}</label>`).join('')}</div>${insert?'<label>数量<input aria-label="数量" type="number" min="1" max="100" step="1" value="1"></label>':''}<p role="alert"></p><button type="button" data-action="cancel" class="${buttonClasses('secondary')}">取消</button><button type="submit" class="${buttonClasses('primary')}">确定</button></form>`})
  const alert=modal.card.querySelector<HTMLElement>('[role=alert]')!,ok=modal.card.querySelector<HTMLButtonElement>('[type=submit]')!
  function validateLive(){
   const current=context(action)
   if(!same(current.selection,frozen.selection)||!same(current.rect,frozen.rect)||!same(current.anchor,frozen.anchor))fail('表格选区或来源已改变，请取消并重新打开对话框')
   if(composing)fail('正在输入，请完成输入后重试')
  }
  function refresh(){if(closed)return;try{validateLive();ok.disabled=false}catch(e){ok.disabled=true;alert.textContent=e instanceof Error?e.message:String(e)}}
  modal.card.querySelector('[data-action=cancel]')!.addEventListener('click',close)
  modal.overlay.addEventListener('compositionstart',()=>{composing=true;refresh()})
  modal.overlay.addEventListener('compositionend',()=>{composing=false;refresh()})
  modal.overlay.addEventListener('keydown',event=>{if(composing&&event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation()}},true)
  modal.card.querySelector('form')!.addEventListener('submit',event=>{event.preventDefault();try{
   validateLive()
   const mode=modal.card.querySelector<HTMLInputElement>('input[type=radio]:checked')!.value
   let change:DocxTableCellChange
   if(insert){const raw=modal.card.querySelector<HTMLInputElement>('input[type=number]')!.value;if(!/^[1-9]\d{0,2}$/.test(raw)||Number(raw)>100)fail('数量须为 1 至 100 的整数');change={type:'insert',rect:frozen.rect,where:mode as 'above'|'below'|'left'|'right',count:Number(raw)}}
   else change={type:'delete',rect:frozen.rect,mode:mode as 'shiftLeft'|'shiftUp'|'row'|'column'}
   const op:DocxTableCellOperation={kind:'editTableCells',blockId:frozen.anchor.blockId,expectedObjectSha256:frozen.anchor.expectedObjectSha256,change},projected=projection(baseline,op,anchors,editor.schema)
   const tr=closeHistory(editor.state.tr);for(const step of projected.steps)tr.step(step)
   tr.setSelection(Selection.fromJSON(tr.doc,projected.selection.toJSON())).scrollIntoView();editor.view.dispatch(tr)
   if(!editor.state.doc.eq(projected.doc))fail('编辑器未接受单元格操作，请检查当前编辑状态后重试')
   editor.view.dispatch(closeHistory(editor.state.tr));close()
  }catch(e){alert.textContent=e instanceof Error?e.message:String(e);options.onError(e)}})
  active={close};editor.on('transaction',refresh);editor.on('destroy',close);timer=setInterval(refresh,150);modal.open(modal.card.querySelector<HTMLInputElement>('input:checked'));return true
 }catch(e){options.onError(e);return false}}
 return {reason,run,dispose(){disposed=true;active?.close()}}
}
