import { afterEach, expect, it } from 'vitest'
import { Editor, Extension, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { CellSelection, TableMap } from '@tiptap/pm/tables'
import { NodeSelection } from '@tiptap/pm/state'
import { NativeTableStructure, createDocxTableCommands } from './docx-tables'
import { createDocxRibbon } from './docx-ribbon'
import { projectDocxCellAlignment, type DocxCellAlignmentAnchor } from './docx-table-cell-alignment'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'
const attrs=(values:Record<string,unknown>)=>Object.fromEntries(Object.entries(values).map(([key,value])=>[key,{default:value}]))
const Doc=Node.create({name:'doc',topNode:true,content:'block+'}),Text=Node.create({name:'text',group:'inline'})
const paragraphAttrs={docxIndex:null,align:null,bidi:false,bidiInherited:false,bidiInferred:false}
const Heading=Node.create({name:'docHeading',group:'block',content:'text*',addAttributes:()=>attrs(paragraphAttrs),renderHTML:()=>['h2',0]})
const List=Node.create({name:'docListItem',group:'block',content:'text*',addAttributes:()=>attrs(paragraphAttrs),renderHTML:()=>['p',0]})
const Paragraph=Node.create({name:'docParagraph',group:'block',content:'text*',addAttributes:()=>attrs(paragraphAttrs),renderHTML:()=>['p',0]})
const Table=Node.create({name:'docTable',group:'block',content:'docTableRow+',addAttributes:()=>attrs({docxIndex:null}),renderHTML:()=>['table',['tbody',0]]})
const Row=Node.create({name:'docTableRow',content:'docTableCell*',renderHTML:()=>['tr',0]})
const Cell=Node.create({name:'docTableCell',content:'(docParagraph|docHeading|docListItem)+',addAttributes:()=>attrs({colspan:1,rowspan:1,colwidth:null,vAlign:null,tcPrEdited:false,rawTcPr:'source'}),renderHTML:()=>['td',0]})
const Roles=Extension.create({name:'roles',extendNodeSchema:e=>({tableRole:({docTable:'table',docTableRow:'row',docTableCell:'cell'} as Record<string,string>)[e.name]})})
const editors:Editor[]=[];afterEach(()=>{editors.splice(0).forEach(e=>e.destroy());document.body.replaceChildren()})
function setup(merged=false){
 const cell=(text:string,direction:string|null)=>({type:'docTableCell',attrs:{vAlign:direction==='tbRl'?'center':direction==='btLr'?'bottom':null},content:[{type:'docParagraph',content:[{type:'text',text}]},{type:'docParagraph',attrs:{bidi:true},content:[{type:'text',text:'שלום explicit'}]},{type:'docParagraph',attrs:{bidiInferred:true},content:[{type:'text',text:'שלום inferred'}]},{type:'docListItem',attrs:{bidi:true,bidiInherited:true},content:[{type:'text',text:'שלום inherited list'}]},{type:'docHeading',attrs:{align:'right'},content:[{type:'text',text:'Heading'}]}]})
 const content:DocxPmNode={type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'body'}]},{type:'docTable',attrs:{docxIndex:1},content:[{type:'docTableRow',content:[cell('A1',null),cell('B1','tbRl')]},{type:'docTableRow',content:[cell('A2','btLr'),cell('B2',null)]}]}]}
 if(merged){content.content![1].content![0].content![0].attrs!.rowspan=2;content.content![1].content![1].content!.splice(0,1)}
 const editor=new Editor({extensions:[Doc,Paragraph,Heading,List,Text,Table,Row,Cell,Roles,NativeTableStructure,UndoRedo],content,editorProps:{handleScrollToSelection:()=>true}});editors.push(editor)
 const baseline=editor.getJSON() as DocxPmNode,table=editor.state.doc.child(1),map=TableMap.get(table),anchor:DocxAnchor&DocxCellAlignmentAnchor={docxIndex:1,blockId:'table',expectedObjectSha256:'sha',editable:false,cellAlignmentEditable:true,cellAlignmentCells:[],cellAlignments:[],cellAlignmentParagraphs:[]}
 table.forEach((row,offset,r)=>row.forEach((cell,cellOffset,c)=>{anchor.cellAlignmentCells!.push({...map.findCell(offset+1+cellOffset),physicalRow:r,physicalColumn:c});anchor.cellAlignments!.push(cell.attrs.vAlign);anchor.cellAlignmentParagraphs!.push(cell.content.content.map(p=>({type:p.type.name as 'docParagraph'|'docListItem'|'docHeading',align:p.attrs.align??null,bidi:p.attrs.bidi===true,bidiInherited:p.attrs.bidiInherited===true,bidiInferred:p.attrs.bidiInferred===true})))}))
 const errors:string[]=[],commands=createDocxTableCommands(editor,baseline,[anchor],e=>errors.push(String(e))),start=editor.state.doc.child(0).nodeSize+1
 const select=()=>editor.commands.setTextSelection(start+2+TableMap.get(editor.state.doc.child(1)).map[0])
 const directions=()=>{const values:unknown[]=[];editor.state.doc.child(1).forEach(row=>row.forEach(cell=>values.push(cell.attrs.vAlign)));return values}
 return{editor,anchor,baseline,commands,errors,start,select,directions}
}

it('九宫格全部组合，LTR/显式/推断/继承RTL按视觉对齐，Heading不改且tcPrEdited不置位',()=>{
 const f=setup();f.select()
 for(const [vertical,vAttr] of [['top',null],['middle','center'],['bottom','bottom']] as const)for(const horizontal of ['left','center','right'] as const){
  f.commands.run(`table-align-${vertical}-${horizontal}`);const cell=f.editor.state.doc.child(1).firstChild!.firstChild!
  expect(cell.attrs.vAlign).toBe(vAttr);expect(cell.attrs.tcPrEdited).toBe(false);expect(cell.attrs.rawTcPr).toBe('source')
  expect(cell.content.content.map(p=>p.attrs.align)).toEqual([horizontal==='left'?null:horizontal,horizontal==='right'?null:horizontal,horizontal==='right'?null:horizontal,horizontal==='right'?null:horizontal,'right'])
  expect(f.commands.active!(`table-align-${vertical}-${horizontal}`)).toBe(true)
 }
 expect(f.errors).toEqual([])
})
it('caret单格、CellSelection合并owner、NodeSelection全表及独立undo/redo保持选择',()=>{
 const f=setup(true);f.select();f.commands.run('table-align-middle-center');const once=f.editor.getJSON();expect(f.directions()).toEqual(['center','center',null])
 const map=TableMap.get(f.editor.state.doc.child(1));f.editor.view.dispatch(f.editor.state.tr.setSelection(CellSelection.create(f.editor.state.doc,f.start+map.map[0],f.start+map.map[3])));f.commands.run('table-align-bottom-right');expect(f.directions()).toEqual(['bottom','bottom','bottom']);expect(f.editor.state.selection).toBeInstanceOf(CellSelection)
 f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(once);f.editor.commands.redo();expect(f.directions()).toEqual(['bottom','bottom','bottom'])
 f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,f.start-1)));f.commands.run('table-align-top-left');expect(f.directions()).toEqual([null,null,null]);expect(f.editor.state.selection).toBeInstanceOf(NodeSelection)
})
it('Ribbon九入口启用且active同步，readonly/锁/nested/同表文字与其他结构混编拒绝',()=>{
 const f=setup();f.select();const ribbon=createDocxRibbon(f.editor,true,undefined,undefined,undefined,[f.anchor],f.commands);document.body.append(ribbon);ribbon.querySelector<HTMLButtonElement>('[data-tab-id="tableLayout"]')!.click()
 for(const v of ['top','middle','bottom'])for(const h of ['left','center','right'])expect(ribbon.querySelector<HTMLButtonElement>(`[data-action="table-align-${v}-${h}"]`)!.disabled).toBe(false)
 f.anchor.cellAlignmentEditable=false;f.anchor.cellAlignmentReadOnlyReason='来源段落对齐歧义';expect(f.commands.reason('table-align-top-left')).toBe('来源段落对齐歧义');f.anchor.cellAlignmentEditable=true
 f.editor.setEditable(false);expect(f.commands.reason('table-align-top-left')).toMatch(/保存|不可编辑/);f.editor.setEditable(true)
 expect(createDocxTableCommands(f.editor,f.baseline,[f.anchor],()=>{},()=>true).reason('table-align-top-left')).toMatch(/嵌套/)
 f.commands.run('table-align-bottom-center');expect(ribbon.querySelector('[data-action="table-align-bottom-center"]')!.getAttribute('aria-pressed')).toBe('true')
 for(const action of ['table-autofit-fixed','table-row-height','table-column-width','table-text-direction-horizontal','table-repeat-header-rows','table-insert-row-before'])expect(f.commands.reason(action)).toMatch(/对齐|先保存/)
})
it('真实collector/replay保完整九宫格顺序，baseline与同表文字保护',()=>{
 const f=setup();f.select();f.commands.run('table-align-bottom-right');f.commands.run('table-align-top-left')
 const anchors=[{docxIndex:0,blockId:'body',expectedObjectSha256:'body',editable:true},f.anchor],operations=docxOperations(f.baseline,f.editor.getJSON(),anchors,undefined,f.editor.schema)
 expect(operations).toEqual([{kind:'setTableCellAlignment',blockId:'table',expectedObjectSha256:'sha',steps:[{top:0,left:0,bottom:1,right:1,vertical:'bottom',horizontal:'right'},{top:0,left:0,bottom:1,right:1,vertical:'top',horizontal:'left'}]}]);expect(replayDocxOperations(f.baseline,operations,anchors,undefined,f.editor.schema)).toEqual(f.editor.getJSON())
 const changed=structuredClone(f.editor.getJSON()) as DocxPmNode;changed.content![1].content![0].content![0].content![0].content![0].text='tampered';expect(()=>docxOperations(f.baseline,changed,anchors,undefined,f.editor.schema)).toThrow(/对齐|同表/)
 expect(f.baseline.content![1].content![0].content![0].attrs).toMatchObject({vAlign:null,tcPrEdited:false})
})
it('草稿伪造hash、额外顶层字段及同表其他意图拒绝',()=>{
 const f=setup();f.select();f.commands.run('table-align-bottom-right');const anchors=[{docxIndex:0,blockId:'body',expectedObjectSha256:'body',editable:true},f.anchor],operations=docxOperations(f.baseline,f.editor.getJSON(),anchors,undefined,f.editor.schema),operation=operations[0]
 expect(()=>replayDocxOperations(f.baseline,[{...operation,expectedObjectSha256:'forged'}],anchors,undefined,f.editor.schema)).toThrow(/身份|来源|草稿/)
 expect(()=>replayDocxOperations(f.baseline,[{...operation,rawXml:'forged'}],anchors,undefined,f.editor.schema)).toThrow(/字段|草稿|对齐/)
 expect(()=>replayDocxOperations(f.baseline,[operation,{kind:'setTableCellTextDirection',blockId:'table',expectedObjectSha256:'sha',steps:[{top:0,left:0,bottom:1,right:1,direction:'tbRl'}]}],anchors,undefined,f.editor.schema)).toThrow(/同表|保存|混用/)
 for(const key of ['nativeTableCellTextDirection','nativeTableAutoFit','nativeTableColumnWidths','nativeTableRowHeights','nativeTableCellShape','nativeTableStructure']){const source=structuredClone(f.baseline.content![1]);source.attrs![key]={steps:[]};expect(()=>projectDocxCellAlignment(source,f.anchor,[{top:0,left:0,bottom:1,right:1,vertical:'top',horizontal:'left'}],f.editor.schema)).toThrow(/同表|保存/)}
})
it('无表/新表及过期来源语义拒绝，不产生部分事务',()=>{
 const f=setup();f.editor.commands.setTextSelection(2);expect(f.commands.reason('table-align-top-left')).not.toBeNull();f.select()
 const before=f.editor.getJSON();f.anchor.cellAlignmentParagraphs![0][0].bidi=true;f.commands.run('table-align-middle-center');expect(f.editor.getJSON()).toEqual(before);expect(f.errors.at(-1)).toMatch(/来源|方向|段落/)
 const table=f.editor.state.doc.child(1);f.editor.view.dispatch(f.editor.state.tr.setNodeMarkup(f.start-1,undefined,{...table.attrs,docxIndex:null,nativeTableInsert:{rows:2,cols:2}}));expect(f.commands.reason('table-align-top-left')).toMatch(/新增|保存/)
})
