import { afterEach, expect, it } from 'vitest'
import { Editor, Extension, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { CellSelection, TableMap } from '@tiptap/pm/tables'
import { NodeSelection } from '@tiptap/pm/state'
import { NativeTableStructure, createDocxTableCommands } from './docx-tables'
import { createDocxRibbon } from './docx-ribbon'
import type { DocxCellMarginsAnchor } from './docx-table-cell-margins'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'
const attrs=(v:Record<string,unknown>)=>Object.fromEntries(Object.entries(v).map(([key,value])=>[key,{default:value}]))
const Doc=Node.create({name:'doc',topNode:true,content:'block+'}),Text=Node.create({name:'text',group:'inline'})
const Paragraph=Node.create({name:'docParagraph',group:'block',content:'text*',addAttributes:()=>attrs({docxIndex:null}),renderHTML:()=>['p',0]})
const Table=Node.create({name:'docTable',group:'block',content:'docTableRow+',addAttributes:()=>attrs({docxIndex:null,cellMar:null,cellMarEdited:false,rawTblPr:'source'}),renderHTML:()=>['table',['tbody',0]]})
const Row=Node.create({name:'docTableRow',content:'docTableCell+',renderHTML:()=>['tr',0]})
const Cell=Node.create({name:'docTableCell',content:'docParagraph+',addAttributes:()=>attrs({colspan:1,rowspan:1,colwidth:null,cellMar:null,tcPrEdited:false,rawTcPr:'source-cell'}),renderHTML:()=>['td',0]})
const Roles=Extension.create({name:'roles',extendNodeSchema:e=>({tableRole:({docTable:'table',docTableRow:'row',docTableCell:'cell'} as Record<string,string>)[e.name]})})
const editors:Editor[]=[];afterEach(()=>{editors.splice(0).forEach(e=>e.destroy());document.body.replaceChildren()})
function setup(){
 const content:DocxPmNode={type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'body'}]},{type:'docTable',attrs:{docxIndex:1,cellMar:{top:0,right:109,bottom:7,left:108}},content:[0,1].map(r=>({type:'docTableRow',content:[0,1].map(c=>({type:'docTableCell',attrs:{cellMar:c?null:{left:r?71:33,top:0}},content:[{type:'docParagraph',content:[{type:'text',text:`${r}:${c}`}]}]}))}))}]}
 const editor=new Editor({extensions:[Doc,Paragraph,Text,Table,Row,Cell,Roles,NativeTableStructure,UndoRedo],content,editorProps:{handleScrollToSelection:()=>true}});editors.push(editor)
 const baseline=editor.getJSON() as DocxPmNode,anchor:DocxAnchor&DocxCellMarginsAnchor={docxIndex:1,blockId:'table',expectedObjectSha256:'sha',editable:false,tableCellMarginsEditable:true,tableCellMarginsSource:{defaults:{top:0,right:109,bottom:7,left:108},raw:'source',cells:[{left:33,top:0},null,{left:71,top:0},null]}}
 const errors:string[]=[],commands=createDocxTableCommands(editor,baseline,[anchor],e=>errors.push(String(e))),start=editor.state.doc.child(0).nodeSize+1
 const select=()=>editor.commands.setTextSelection(start+2+TableMap.get(editor.state.doc.child(1)).map[0]),margins=()=>editor.state.doc.child(1).attrs.cellMar
 return{editor,anchor,baseline,commands,errors,start,select,margins}
}
const dialog=()=>document.querySelector<HTMLElement>('[role="dialog"][aria-label="默认单元格边距"]')!
const fill=(side:string,value:string)=>dialog().querySelector<HTMLInputElement>(`[data-margin="${side}"]`)!.value=value
const submit=()=>dialog().querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
it('整表默认无操作提交保留奇数twip，显式单位/0输入且tcMar覆盖全部不动，独立undo/redo',()=>{
 const f=setup();f.select();expect(f.commands.reason('table-cell-margins')).toBeNull();f.commands.run('table-cell-margins');expect(dialog().querySelector<HTMLInputElement>('[data-margin="right"]')!.value).toBe('5.45');submit();expect(f.margins()).toEqual({top:0,right:109,bottom:7,left:108});expect(f.editor.getJSON()).toEqual(f.baseline);expect(f.editor.can().undo()).toBe(false)
 const first=f.editor.getJSON();f.commands.run('table-cell-margins');fill('right','0.31cm');fill('bottom','1pt');fill('left','0');submit();expect(f.margins()).toEqual({top:0,right:176,bottom:20,left:0})
 f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(first);f.editor.commands.redo();expect(f.margins().right).toBe(176)
 const table=(f.editor.getJSON() as DocxPmNode).content![1];expect(table.content).toEqual(f.baseline.content![1].content);expect(table.attrs!.nativeTableCellMargins).toEqual({margins:{top:0,right:176,bottom:20,left:0}});expect(f.errors).toEqual([])
})
it('CellSelection/NodeSelection只是定位整表，非法输入和stale选择/文档/锁拒绝',()=>{
 const f=setup(),map=TableMap.get(f.editor.state.doc.child(1));f.editor.view.dispatch(f.editor.state.tr.setSelection(CellSelection.create(f.editor.state.doc,f.start+map.map[0],f.start+map.map[3])));f.commands.run('table-cell-margins')
 for(const value of ['-1','28351twip','1417.6pt','NaN','1bogus','']){fill('top',value);submit();expect(dialog().querySelector('[role="alert"]')!.textContent).not.toBe('');expect(f.editor.getJSON()).toEqual(f.baseline)}
 fill('top','0');f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,f.start-1)));submit();expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/选区|选择/);dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
 f.commands.run('table-cell-margins');fill('top','42twip');submit();expect(f.margins().top).toBe(42);expect(f.editor.state.selection).toBeInstanceOf(NodeSelection)
 f.commands.run('table-cell-margins');f.editor.setEditable(false);submit();expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/保存|不可编辑/)
})
it('readonly/nested与同表混编拒绝，Ribbon默认入口启用',()=>{
 const f=setup();f.select();const ribbon=createDocxRibbon(f.editor,true,undefined,undefined,undefined,[f.anchor],f.commands);document.body.append(ribbon);ribbon.querySelector<HTMLButtonElement>('[data-tab-id="tableLayout"]')!.click();expect(ribbon.querySelector<HTMLButtonElement>('[data-action="table-cell-margins"]')!.disabled).toBe(false)
 f.anchor.tableCellMarginsEditable=false;f.anchor.tableCellMarginsReadOnlyReason='来源边距歧义';expect(f.commands.reason('table-cell-margins')).toBe('来源边距歧义');f.anchor.tableCellMarginsEditable=true
 expect(createDocxTableCommands(f.editor,f.baseline,[f.anchor],()=>{},()=>true).reason('table-cell-margins')).toMatch(/嵌套/)
 f.commands.run('table-cell-margins');fill('top','20twip');submit();for(const action of ['table-align-top-left','table-text-direction-horizontal','table-autofit-fixed','table-row-height','table-column-width','table-repeat-header-rows','table-insert-row-before'])expect(f.commands.reason(action)).toMatch(/边距|先保存/)
})
it('真实collector/replay保整表意图，forged hash/额外字段/篡改cell覆盖拒绝',()=>{
 const f=setup();f.select();f.commands.run('table-cell-margins');fill('bottom','20twip');submit();f.commands.run('table-cell-margins');fill('bottom','40twip');submit();const anchors=[{docxIndex:0,blockId:'body',expectedObjectSha256:'body',editable:true},f.anchor],operations=docxOperations(f.baseline,f.editor.getJSON(),anchors,undefined,f.editor.schema),operation=operations[0]
 expect(operation).toEqual({kind:'setTableCellMargins',blockId:'table',expectedObjectSha256:'sha',margins:{top:0,right:109,bottom:40,left:108}});expect(replayDocxOperations(f.baseline,operations,anchors,undefined,f.editor.schema)).toEqual(f.editor.getJSON())
 expect(()=>replayDocxOperations(f.baseline,[{...operation,expectedObjectSha256:'forged'}],anchors,undefined,f.editor.schema)).toThrow();expect(()=>replayDocxOperations(f.baseline,[{...operation,rawXml:'forged'}],anchors,undefined,f.editor.schema)).toThrow()
 const changed=structuredClone(f.editor.getJSON()) as DocxPmNode;changed.content![1].content![0].content![0].attrs!.cellMar={left:999};expect(()=>docxOperations(f.baseline,changed,anchors,undefined,f.editor.schema)).toThrow(/边距|同表/)
})

it('对话框stale来源/文档与取消无事务，额外意图字段和基线语义篡改拒绝',()=>{
 const f=setup();f.select();f.commands.run('table-cell-margins');fill('top','2pt');f.anchor.tableCellMarginsSource!.raw='changed';submit();expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/来源|改变/);expect(f.editor.getJSON()).toEqual(f.baseline);dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
 f.anchor.tableCellMarginsSource!.raw='source';f.commands.run('table-cell-margins');f.editor.commands.insertContent('changed');submit();expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/同表|改变|保存/);dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
})
