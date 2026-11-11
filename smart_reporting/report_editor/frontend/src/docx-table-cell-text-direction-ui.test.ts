import { afterEach, expect, it } from 'vitest'
import { Editor, Extension, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { CellSelection, TableMap } from '@tiptap/pm/tables'
import { NodeSelection } from '@tiptap/pm/state'
import { NativeTableStructure, createDocxTableCommands } from './docx-tables'
import { createDocxRibbon } from './docx-ribbon'
import { projectDocxCellTextDirection, type DocxCellTextDirectionAnchor } from './docx-table-cell-text-direction'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'
const attrs=(values:Record<string,unknown>)=>Object.fromEntries(Object.entries(values).map(([key,value])=>[key,{default:value}]))
const Doc=Node.create({name:'doc',topNode:true,content:'block+'}),Text=Node.create({name:'text',group:'inline'})
const Paragraph=Node.create({name:'docParagraph',group:'block',content:'text*',addAttributes:()=>attrs({docxIndex:null}),renderHTML:()=>['p',0]})
const Table=Node.create({name:'docTable',group:'block',content:'docTableRow+',addAttributes:()=>attrs({docxIndex:null}),renderHTML:()=>['table',['tbody',0]]})
const Row=Node.create({name:'docTableRow',content:'docTableCell*',renderHTML:()=>['tr',0]})
const Cell=Node.create({name:'docTableCell',content:'docParagraph+',addAttributes:()=>attrs({colspan:1,rowspan:1,colwidth:null,textDirection:null,tcPrEdited:false,rawTcPr:'source'}),renderHTML:()=>['td',0]})
const Roles=Extension.create({name:'roles',extendNodeSchema:e=>({tableRole:({docTable:'table',docTableRow:'row',docTableCell:'cell'} as Record<string,string>)[e.name]})})
const editors:Editor[]=[];afterEach(()=>{editors.splice(0).forEach(e=>e.destroy());document.body.replaceChildren()})
function setup(merged=false){
 const cell=(text:string,direction:string|null)=>({type:'docTableCell',attrs:{textDirection:direction},content:[{type:'docParagraph',content:[{type:'text',text}]}]})
 const content:DocxPmNode={type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'body'}]},{type:'docTable',attrs:{docxIndex:1},content:[{type:'docTableRow',content:[cell('A1',null),cell('B1','tbRl')]},{type:'docTableRow',content:[cell('A2','btLr'),cell('B2',null)]}]}]}
 if(merged){content.content![1].content![0].content![0].attrs!.rowspan=2;content.content![1].content![1].content!.splice(0,1)}
 const editor=new Editor({extensions:[Doc,Paragraph,Text,Table,Row,Cell,Roles,NativeTableStructure,UndoRedo],content,editorProps:{handleScrollToSelection:()=>true}});editors.push(editor)
 const baseline=editor.getJSON() as DocxPmNode,table=editor.state.doc.child(1),map=TableMap.get(table),anchor:DocxAnchor&DocxCellTextDirectionAnchor={docxIndex:1,blockId:'table',expectedObjectSha256:'sha',editable:false,cellTextDirectionEditable:true,cellTextDirectionCells:[],cellTextDirections:[]}
 table.forEach((row,offset,r)=>row.forEach((cell,cellOffset,c)=>{anchor.cellTextDirectionCells!.push({...map.findCell(offset+1+cellOffset),physicalRow:r,physicalColumn:c});anchor.cellTextDirections!.push(cell.attrs.textDirection)}))
 const errors:string[]=[],commands=createDocxTableCommands(editor,baseline,[anchor],e=>errors.push(String(e))),start=editor.state.doc.child(0).nodeSize+1
 const select=()=>editor.commands.setTextSelection(start+2+TableMap.get(editor.state.doc.child(1)).map[0])
 const directions=()=>{const values:unknown[]=[];editor.state.doc.child(1).forEach(row=>row.forEach(cell=>values.push(cell.attrs.textDirection)));return values}
 return{editor,anchor,baseline,commands,errors,start,select,directions}
}
it('三方向caret单格、NodeSelection整表、横排clear及独立undo/redo保内容',()=>{
 const f=setup();f.select();expect(f.commands.reason('table-text-direction-rotate-90')).toBeNull();f.commands.run('table-text-direction-rotate-90');expect(f.directions()).toEqual(['tbRl','tbRl','btLr',null]);const first=f.editor.getJSON()
 f.commands.run('table-text-direction-rotate-270');expect(f.directions()[0]).toBe('btLr');f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(first);f.editor.commands.redo();expect(f.directions()[0]).toBe('btLr')
 f.commands.run('table-text-direction-horizontal');expect(f.directions()[0]).toBeNull();expect(f.commands.active!('table-text-direction-horizontal')).toBe(true)
 f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,f.start-1)));f.commands.run('table-text-direction-rotate-270');expect(f.directions()).toEqual(['btLr','btLr','btLr','btLr']);expect(f.editor.state.selection).toBeInstanceOf(NodeSelection);expect(f.editor.state.doc.child(1).textContent).toBe('A1B1A2B2');expect(f.errors).toEqual([])
})
it('CellSelection混合方向无active，rowspan唯一owner修改且保留原rawTcPr',()=>{
 const f=setup(true),map=TableMap.get(f.editor.state.doc.child(1));f.editor.view.dispatch(f.editor.state.tr.setSelection(CellSelection.create(f.editor.state.doc,f.start+map.map[0],f.start+map.map[3])))
 for(const suffix of ['horizontal','rotate-90','rotate-270'])expect(f.commands.active!(`table-text-direction-${suffix}`)).toBe(false)
 f.commands.run('table-text-direction-rotate-90');expect(f.directions()).toEqual(['tbRl','tbRl','tbRl']);expect(f.editor.state.selection).toBeInstanceOf(CellSelection)
 const table=(f.editor.getJSON() as DocxPmNode).content![1];expect(table.content![0].content![0].attrs).toMatchObject({rawTcPr:'source',tcPrEdited:true});expect(table.attrs!.nativeTableCellTextDirection).toEqual({steps:[{top:0,left:0,bottom:2,right:2,direction:'tbRl'}]})
})
it('签发方向或格网失配拒绝，readonly/锁/nested/新表/文字修改明确拒绝',()=>{
 const f=setup();f.select();expect(()=>projectDocxCellTextDirection(f.baseline.content![1],{...f.anchor,cellTextDirections:['btLr']},[{top:0,left:0,bottom:1,right:1,direction:'lrTb'}],f.editor.schema)).toThrow(/来源|方向/)
 expect(()=>projectDocxCellTextDirection(f.baseline.content![1],{...f.anchor,cellTextDirectionCells:[]},[{top:0,left:0,bottom:1,right:1,direction:'lrTb'}],f.editor.schema)).toThrow(/网格/)
 f.anchor.cellTextDirectionEditable=false;f.anchor.cellTextDirectionReadOnlyReason='来源方向歧义';expect(f.commands.reason('table-text-direction-horizontal')).toBe('来源方向歧义');f.anchor.cellTextDirectionEditable=true
 f.editor.setEditable(false);expect(f.commands.reason('table-text-direction-horizontal')).toMatch(/保存|不可编辑/);f.editor.setEditable(true)
 expect(createDocxTableCommands(f.editor,f.baseline,[f.anchor],()=>{},()=>true).reason('table-text-direction-horizontal')).toMatch(/嵌套/)
 f.editor.commands.insertContent('changed');expect(f.commands.reason('table-text-direction-horizontal')).toMatch(/同表|先保存/)
})
it('Ribbon三方向可用且aria-pressed随选区，方向后其他表编辑互斥',()=>{
 const f=setup();f.select();const ribbon=createDocxRibbon(f.editor,true,undefined,undefined,undefined,[f.anchor],f.commands);document.body.append(ribbon);ribbon.querySelector<HTMLButtonElement>('[data-tab-id="tableLayout"]')!.click()
 for(const suffix of ['horizontal','rotate-90','rotate-270'])expect(ribbon.querySelector<HTMLButtonElement>(`[data-action="table-text-direction-${suffix}"]`)!.disabled).toBe(false)
 expect(ribbon.querySelector('[data-action="table-text-direction-horizontal"]')!.getAttribute('aria-pressed')).toBe('true')
 f.commands.run('table-text-direction-rotate-90');for(const action of ['table-autofit-fixed','table-column-width','table-row-height','table-repeat-header-rows','table-insert-row-before'])expect(f.commands.reason(action)).toMatch(/文字方向|先保存/)
})

it('真实collector/replay保留有序设置/清除/重复方向，baseline原属性不动',()=>{
 const f=setup();f.select();for(const suffix of ['rotate-90','horizontal','rotate-270','rotate-270'])f.commands.run(`table-text-direction-${suffix}`)
 const anchors=[{docxIndex:0,blockId:'body',expectedObjectSha256:'body',editable:true},f.anchor],operations=docxOperations(f.baseline,f.editor.getJSON(),anchors,undefined,f.editor.schema)
 expect(operations).toEqual([{kind:'setTableCellTextDirection',blockId:'table',expectedObjectSha256:'sha',steps:['tbRl','lrTb','btLr','btLr'].map(direction=>({top:0,left:0,bottom:1,right:1,direction}))}])
 expect(replayDocxOperations(f.baseline,operations,anchors,undefined,f.editor.schema)).toEqual(f.editor.getJSON())
 const changed=structuredClone(f.editor.getJSON()) as DocxPmNode;changed.content![1].content![0].content![0].content![0].content![0].text='tampered';expect(()=>docxOperations(f.baseline,changed,anchors,undefined,f.editor.schema)).toThrow(/方向|同表/)
 expect(f.baseline.content![1].content![0].content![0].attrs).toMatchObject({textDirection:null,tcPrEdited:false,rawTcPr:'source'})
})
it('无表/新增表格与其他intent反向混编拒绝，已有方向step不吞其他编辑',()=>{
 const f=setup();f.editor.commands.setTextSelection(2);expect(f.commands.reason('table-text-direction-horizontal')).not.toBeNull();f.select()
 for(const key of ['nativeTableStructure','nativeTableCellShape','nativeTableColumnWidths','nativeTableRowHeights','nativeTableAutoFit']){
  const source=structuredClone(f.baseline.content![1]);source.attrs![key]={steps:[]};expect(()=>projectDocxCellTextDirection(source,f.anchor,[{top:0,left:0,bottom:1,right:1,direction:'tbRl'}],f.editor.schema)).toThrow(/同表|保存/)
 }
 const table=f.editor.state.doc.child(1);f.editor.view.dispatch(f.editor.state.tr.setNodeMarkup(f.start-1,undefined,{...table.attrs,docxIndex:null,nativeTableInsert:{rows:2,cols:2}}));expect(f.commands.reason('table-text-direction-horizontal')).toMatch(/新增|保存/)
})
