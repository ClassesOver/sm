import { afterEach, expect, it } from 'vitest'
import { Editor, Extension, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { CellSelection, TableMap } from '@tiptap/pm/tables'
import { NodeSelection } from '@tiptap/pm/state'
import { NativeTableStructure, createDocxTableCommands } from './docx-tables'
import { createDocxRibbon } from './docx-ribbon'
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
 const baseline=editor.getJSON() as DocxPmNode,anchor:any={docxIndex:1,blockId:'table',expectedObjectSha256:'sha',editable:false,tableCellMarginOverridesEditable:true,tableCellMarginOverridesSource:{cells:[{top:0,left:0,bottom:1,right:1,rawPresent:true,raw:{left:33,top:0},effective:{left:33,top:0},resetEffective:{left:77,top:7}},{top:0,left:1,bottom:1,right:2,rawPresent:false,raw:null,effective:null,resetEffective:null},{top:1,left:0,bottom:2,right:1,rawPresent:true,raw:{left:71,top:0},effective:{left:71,top:0},resetEffective:null},{top:1,left:1,bottom:2,right:2,rawPresent:true,raw:null,effective:null,resetEffective:null}]}}
 anchor.tableCellMarginOverridesSource.cells.forEach((cell:any)=>{cell.hasPhysicalOverrides=cell.rawPresent})
 const errors:string[]=[],commands=createDocxTableCommands(editor,baseline,[anchor],e=>errors.push(String(e))),start=editor.state.doc.child(0).nodeSize+1
 const select=(n=0)=>editor.commands.setTextSelection(start+2+TableMap.get(editor.state.doc.child(1)).map[n]),margins=()=>editor.state.doc.child(1).attrs.cellMar
 const cell=(n=0)=>editor.state.doc.nodeAt(start+TableMap.get(editor.state.doc.child(1)).map[n])!
 const rect=()=>{const map=TableMap.get(editor.state.doc.child(1));editor.view.dispatch(editor.state.tr.setSelection(CellSelection.create(editor.state.doc,start+map.map[0],start+map.map[3])))}
 const open=()=>commands.run('table-properties')
 return{editor,anchor,baseline,commands,errors,start,select,margins,cell,rect,open}
}
const dialog=()=>document.querySelector<HTMLElement>('[role="dialog"][aria-label="单元格边距"]')!
const input=(side:string)=>dialog().querySelector<HTMLInputElement>(`[data-margin="${side}"]`)!
const fill=(side:string,value:string)=>{input(side).value=value;input(side).dispatchEvent(new Event('input',{bubbles:true}))}
const submit=()=>dialog().querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
const reset=()=>dialog().querySelector<HTMLButtonElement>('[data-action="inherit"]')!.click()
it('单格无操作保奇数twip，四边单位零值覆盖及undo redo',()=>{
 const f=setup();f.select();expect(f.commands.reason('table-properties')).toBeNull();f.open();expect(input('right').value).toBe('5.45');submit();expect(f.editor.getJSON()).toEqual(f.baseline);expect(f.editor.can().undo()).toBe(false)
 f.open();fill('right','0.31cm');fill('bottom','1pt');fill('left','0');submit();expect(f.cell().attrs.cellMar).toEqual({top:0,right:176,bottom:20,left:0});expect(f.cell(1).attrs.cellMar).toBeNull();expect(f.cell().attrs.tcPrEdited).toBe(false)
 f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(f.baseline);f.editor.commands.redo();expect(f.cell().attrs.cellMar.left).toBe(0);expect(f.errors).toEqual([])
})
it('混合矩形不填不dirty，部分输入须完整，NodeSelection整表统一覆盖',()=>{
 const f=setup();f.rect();f.open();expect(input('left').value).toBe('');expect(input('left').placeholder).toBe('多个值');submit();expect(f.editor.getJSON()).toEqual(f.baseline)
 f.open();fill('right','2pt');submit();expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/多个|完整|四边/);expect(f.editor.getJSON()).toEqual(f.baseline);fill('left','3pt');submit();expect(dialog()).toBeNull();expect([0,1,2,3].map(n=>f.cell(n).attrs.cellMar)).toEqual(Array(4).fill({top:0,right:40,bottom:7,left:60}))
 f.editor.commands.undo();f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,f.start-1)));f.open();fill('left','4pt');submit();expect(f.cell(3).attrs.cellMar.left).toBe(80);expect(f.editor.state.selection).toBeInstanceOf(NodeSelection)
})
it('恢复继承使用rawPresent与resetEffective，重复reset不追加，空tcMar可清除',()=>{
 const f=setup();f.select(1);f.open();reset();expect(f.editor.getJSON()).toEqual(f.baseline);expect(f.editor.can().undo()).toBe(false)
 f.select();f.open();reset();expect(f.cell().attrs.cellMar).toEqual({left:77,top:7});f.open();reset();expect(((f.editor.getJSON() as DocxPmNode).content![1].attrs!.nativeTableCellMarginOverrides as {steps:unknown[]}).steps).toHaveLength(1)
 f.select(3);f.open();reset();expect(((f.editor.getJSON() as DocxPmNode).content![1].attrs!.nativeTableCellMarginOverrides as {steps:unknown[]}).steps).toHaveLength(2)
})
it('Ribbon入口、stale选择/来源/文档、锁与非法输入保护',()=>{
 const f=setup();f.select();const ribbon=createDocxRibbon(f.editor,true,undefined,undefined,undefined,[f.anchor],f.commands);document.body.append(ribbon);ribbon.querySelector<HTMLButtonElement>('[data-tab-id="tableLayout"]')!.click();const button=ribbon.querySelector<HTMLButtonElement>('[data-action="table-properties"]')!;expect(button.disabled).toBe(false);button.click();expect(dialog()).not.toBeNull()
 for(const value of ['-0.00001pt','28351twip','1417.6pt','NaN','1bogus','']){fill('top',value);submit();expect(dialog().querySelector('[role="alert"]')!.textContent).not.toBe('');expect(f.editor.getJSON()).toEqual(f.baseline)}
 fill('top','0');f.select(1);submit();expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/选区|选择/);dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click();f.open();f.anchor.tableCellMarginOverridesSource.cells[0].rawPresent=false;reset();expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/来源|改变/);dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
 f.anchor.tableCellMarginOverridesSource.cells[0].rawPresent=true;f.open();f.editor.commands.insertContent('changed');submit();expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/同表|改变|保存/);dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click();f.editor.setEditable(false);expect(f.commands.reason('table-properties')).toMatch(/保存|不可编辑/)
})
it('有序set/reset与collector草稿replay，同表其它操作双向拒绝',()=>{
 const f=setup();f.select();f.open();fill('left','0');submit();f.rect();f.open();reset();const anchors:DocxAnchor[]=[{docxIndex:0,blockId:'body',expectedObjectSha256:'body',editable:true},f.anchor],operations=docxOperations(f.baseline,f.editor.getJSON(),anchors,undefined,f.editor.schema)
 expect(operations[0].kind).toBe('setTableCellMarginOverrides');expect((operations[0] as any).steps).toHaveLength(2);expect(replayDocxOperations(f.baseline,operations,anchors,undefined,f.editor.schema)).toEqual(f.editor.getJSON());expect(()=>replayDocxOperations(f.baseline,[{...operations[0],expectedObjectSha256:'forged'}],anchors,undefined,f.editor.schema)).toThrow()
 for(const action of ['table-cell-margins','table-align-top-left','table-text-direction-horizontal','table-autofit-fixed','table-row-height','table-column-width','table-repeat-header-rows','table-merge-cells','table-insert-row-before'])expect(f.commands.reason(action)).not.toBeNull()
 const g=setup();g.select();const table=g.editor.state.doc.child(1);g.editor.view.dispatch(g.editor.state.tr.setNodeMarkup(g.start-1,undefined,{...table.attrs,nativeTableCellMargins:{margins:{top:0,right:109,bottom:7,left:108}}}));expect(g.commands.reason('table-properties')).not.toBeNull()
})
it('无表/新表/嵌套/过期来源及畸形意图拒绝，全部同表独立意图反向互斥',()=>{
 const f=setup();expect(f.commands.reason('table-properties')).not.toBeNull();f.select();expect(createDocxTableCommands(f.editor,f.baseline,[f.anchor],()=>{},()=>true).reason('table-properties')).toMatch(/嵌套/)
 f.anchor.tableCellMarginOverridesEditable=false;f.anchor.tableCellMarginOverridesReadOnlyReason='来源覆盖声明歧义';expect(f.commands.reason('table-properties')).toBe('来源覆盖声明歧义');f.anchor.tableCellMarginOverridesEditable=true
 for(const name of ['nativeTableStructure','nativeTableCellShape','nativeTableColumnWidths','nativeTableRowHeights','nativeTableAutoFit','nativeTableCellTextDirection','nativeTableCellAlignment','nativeTableCellMargins']){
  const table=f.editor.state.doc.child(1);f.editor.view.dispatch(f.editor.state.tr.setNodeMarkup(f.start-1,undefined,{...table.attrs,[name]:{steps:[]}}));expect(f.commands.reason('table-properties')).toMatch(/同表|保存/);f.editor.view.dispatch(f.editor.state.tr.setNodeMarkup(f.start-1,undefined,{...table.attrs}))
 }
 const table=f.editor.state.doc.child(1);f.editor.view.dispatch(f.editor.state.tr.setNodeMarkup(f.start-1,undefined,{...table.attrs,nativeTableCellMarginOverrides:{steps:[],foreign:true}}));expect(f.commands.reason('table-properties')).toMatch(/草稿/);f.editor.view.dispatch(f.editor.state.tr.setNodeMarkup(f.start-1,undefined,{...table.attrs,docxIndex:99}));expect(f.commands.reason('table-properties')).toMatch(/来源|新增/)
})

it('owner无直属覆盖而隐藏continuation有覆盖时允许恢复继承并签发保存步骤',()=>{
 const f=setup();f.anchor.tableCellMarginOverridesSource.cells[0].rawPresent=false;f.anchor.tableCellMarginOverridesSource.cells[0].raw=null;f.anchor.tableCellMarginOverridesSource.cells[0].hasPhysicalOverrides=true;f.select();f.open();reset();expect(f.cell().attrs.cellMar).toEqual({left:77,top:7})
 const operations=docxOperations(f.baseline,f.editor.getJSON(),[{docxIndex:0,blockId:'body',expectedObjectSha256:'body',editable:true},f.anchor],undefined,f.editor.schema)
 expect(operations[0].kind).toBe('setTableCellMarginOverrides');expect((operations[0] as any).steps).toEqual([{top:0,left:0,bottom:1,right:1,margins:null}])
})
