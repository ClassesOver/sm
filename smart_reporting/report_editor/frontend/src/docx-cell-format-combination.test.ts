/** 同表边框与底纹：可信有序投影、草稿及真实schema回归。 */
import { expect, it } from 'vitest'
import type { NativeOperation } from './native-draft'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'
import { replayDocxCellBorders } from './docx-cell-borders'
import { replayDocxCellShading } from './docx-cell-shading'
const anchors:DocxAnchor[]=[{docxIndex:0,blockId:'table',expectedObjectSha256:'table-hash',editable:false,bordersEditable:true,cells:[[{cellId:'a',expectedObjectSha256:'a-hash',editable:false,shadingEditable:true}]]}]
const source=():DocxPmNode=>({
 type:'doc',content:[{
  type:'docTable',attrs:{docxIndex:0,nativeCellBorders:null,borders:null},content:[{
   type:'docTableRow',content:[{
    type:'docTableCell',attrs:{fill:'FFC000',borders:null},content:[{
     type:'docParagraph',content:[{type:'text',text:'rich',marks:[{type:'bold'}]}]
    }]
   }]
  }]
 }]
})
const borders={kind:'setTableCellBorders',blockId:'table',expectedObjectSha256:'table-hash',steps:[{range:null,mode:'outer',pen:{style:'single',szEighths:12,color:'FF0000'}}]}
const shading={kind:'setCellShading',blockId:'table',cellId:'a',expectedObjectSha256:'a-hash',fill:'00B050'}
it.each(['border-first','shade-first'])('source permits same-table colors and borders: %s',order=>{
 const baseline=source()
 const current=order==='border-first'?replayDocxCellShading(replayDocxCellBorders(baseline,[borders],anchors),[shading],anchors):replayDocxCellBorders(replayDocxCellShading(baseline,[shading],anchors),[borders],anchors)
 const ops=docxOperations(baseline,current,anchors)
 expect(ops.map(op=>op.kind)).toEqual(['setTableCellBorders','setCellShading'])
 expect(replayDocxOperations(baseline,ops,anchors)).toEqual(current)
})
it('draft restores both trusted operations instead of rejecting the same table',()=>{
 expect(()=>replayDocxOperations(source(),[borders,shading],anchors)).not.toThrow()
})
it.each(['extra-border','duplicate-shade','stale-cell','structure','body','raw-attribute'])('keeps %s rejected in a combined draft',fault=>{
 const ops=[borders,shading] as NativeOperation[]
 if(fault==='extra-border')ops.push(borders)
 else if(fault==='duplicate-shade')ops.push(shading)
 else if(fault==='stale-cell')ops[1]={...shading,expectedObjectSha256:'foreign'}
 else if(fault==='structure')ops.push({kind:'restructureTable',blockId:'table',expectedObjectSha256:'table-hash',steps:[{kind:'insertTableRow',index:1}]})
 else {
  const current=replayDocxOperations(source(),ops,anchors)
  if(fault==='body')current.content![0]!.content![0]!.content![0]!.content![0]!.content![0]!.text='tampered'
  else current.content![0]!.content![0]!.content![0]!.attrs!.rawTcPr='<w:tcPr/>'
  expect(()=>docxOperations(source(),current,anchors)).toThrow();return
 }
 expect(()=>replayDocxOperations(source(),ops,anchors)).toThrow()
})
import { afterEach } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { Plugin, TextSelection } from '@tiptap/pm/state'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { NativeCellBorders, applyDocxCellBorders } from './docx-cell-borders'
import { applyDocxCellShading } from './docx-cell-shading'
const editors:Editor[]=[]
afterEach(()=>{editors.splice(0).forEach(editor=>editor.destroy());document.body.replaceChildren()})
it.each(['border-first','shade-first'])('uses real schema transactions, guard, undo and replay: %s',order=>{
 let baseline:DocxPmNode,ready=false
 const errors:string[]=[]
 const Guard=Extension.create({name:'combinationGuard',addProseMirrorPlugins:()=>[new Plugin({filterTransaction(tr){if(!ready||!tr.docChanged)return true;try{docxOperations(baseline,tr.doc.toJSON(),anchors);return true}catch(error){errors.push(String(error));return false}}})]})
 const editor=new Editor({extensions:[...editorExtensions,NativeCellBorders,Guard],content:source(),editorProps:{handleScrollToSelection:()=>true}})
 editors.push(editor);baseline=editor.getJSON() as DocxPmNode;ready=true
 editor.view.dispatch(editor.state.tr.setSelection(TextSelection.create(editor.state.doc,4)))
 const border=()=>applyDocxCellBorders(editor,'outer',borders.steps[0]!.pen,anchors)
 const shade=()=>applyDocxCellShading(editor,'00B050',anchors)
 expect(order==='border-first'?border():shade()).toBe(true)
 const first=editor.getJSON()
 expect(order==='border-first'?shade():border()).toBe(true)
 const current=editor.getJSON(),ops=docxOperations(baseline,current as DocxPmNode,anchors)
 expect(ops.map(op=>op.kind)).toEqual(['setTableCellBorders','setCellShading'])
 expect(replayDocxOperations(baseline,ops,anchors)).toEqual(current)
 editor.commands.undo();expect(editor.getJSON()).toEqual(first)
 editor.commands.redo();expect(editor.getJSON()).toEqual(current)
 expect(errors).toEqual([])
})
