import { afterEach, expect, it } from 'vitest'
import { Editor, Extension, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { CellSelection, TableMap } from '@tiptap/pm/tables'
import { NodeSelection } from '@tiptap/pm/state'
import { NativeTableStructure, createDocxTableCommands } from './docx-tables'
import { createDocxRibbon } from './docx-ribbon'
import { normalizeDocxAutoFitSources, projectDocxAutoFit, type DocxAutoFitAnchor } from './docx-table-autofit'
import { docxOperations, replayDocxOperations } from './docx-operations'
import type { DocxAnchor, DocxPmNode } from './docx-operations'
const attrs=(values:Record<string,unknown>)=>Object.fromEntries(Object.entries(values).map(([k,v])=>[k,{default:v}]))
const Doc=Node.create({name:'doc',topNode:true,content:'block+'}),Text=Node.create({name:'text',group:'inline'})
const Paragraph=Node.create({name:'docParagraph',group:'block',content:'text*',addAttributes:()=>attrs({docxIndex:null}),renderHTML:()=>['p',0]})
const Table=Node.create({name:'docTable',group:'block',content:'docTableRow+',addAttributes:()=>attrs({docxIndex:null,tblAutoFit:'fixed',tblAutoFitEdited:false,widthPx:400,widthPct:null,colWidthsPct:[40,60],rawTblPr:'original'}),renderHTML:()=>['table',['tbody',0]]})
const Row=Node.create({name:'docTableRow',content:'docTableCell+',addAttributes:()=>attrs({rawTrPr:'original-row'}),renderHTML:()=>['tr',0]})
const Cell=Node.create({name:'docTableCell',content:'docParagraph+',addAttributes:()=>attrs({colspan:1,rowspan:1,colwidth:null,rawTcPr:'original-cell'}),renderHTML:()=>['td',0]})
const Roles=Extension.create({name:'roles',extendNodeSchema:e=>({tableRole:({docTable:'table',docTableRow:'row',docTableCell:'cell'} as Record<string,string>)[e.name]})})
const editors:Editor[]=[];afterEach(()=>{editors.splice(0).forEach(e=>e.destroy());document.body.replaceChildren()})
function setup(mode:'fixed'|'window'|'contents'='fixed'){
 const content:DocxPmNode={type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'body'}]},{type:'docTable',attrs:{docxIndex:1,tblAutoFit:mode,widthPx:mode==='window'?null:400,widthPct:mode==='window'?70:null},content:[0,1].map(r=>({type:'docTableRow',content:[0,1].map(c=>({type:'docTableCell',attrs:{colwidth:[c?240:160]},content:[{type:'docParagraph',content:[{type:'text',text:`${r}:${c}`}]}]}))}))}]}
 const editor=new Editor({extensions:[Doc,Paragraph,Text,Table,Row,Cell,Roles,NativeTableStructure,UndoRedo],content,editorProps:{handleScrollToSelection:()=>true}});editors.push(editor)
 const table=editor.state.doc.child(1),map=TableMap.get(table),anchor:DocxAnchor&DocxAutoFitAnchor={docxIndex:1,blockId:'table',expectedObjectSha256:'sha',editable:false,autoFitEditable:true,autoFitMode:mode,autoFitWidthsTwips:[2401,3601],autoFitContentWidthTwips:9000,autoFitCells:[]}
 table.forEach((row,offset,r)=>row.forEach((_cell,cellOffset,c)=>anchor.autoFitCells!.push({...map.findCell(offset+1+cellOffset),physicalRow:r,physicalColumn:c})))
 const original=editor.getJSON() as DocxPmNode,normalized=normalizeDocxAutoFitSources(original,[anchor],editor.schema)
 editor.chain().setMeta('addToHistory',false).setContent(normalized,{emitUpdate:false}).run();const baseline=editor.getJSON() as DocxPmNode,errors:string[]=[],commands=createDocxTableCommands(editor,baseline,[anchor],e=>errors.push(String(e)))
 const select=()=>editor.commands.setTextSelection(editor.state.doc.child(0).nodeSize+3+TableMap.get(editor.state.doc.child(1)).map[0])
 const live=()=>(editor.getJSON() as DocxPmNode).content![1];return{editor,anchor,original,baseline,commands,errors,select,live}
}
it('归一化只恢复可信奇数twip格宽，保留contents/非100%pct初始属性且不登记intent',()=>{
 for(const mode of ['fixed','window','contents'] as const){const f=setup(mode),table=f.baseline.content![1];expect(table.content![0].content![0].attrs!.colwidth).toEqual([2401/15]);expect(table.attrs).toEqual(f.original.content![1].attrs);expect(table.attrs!.nativeTableAutoFit).toBeNull();expect(f.editor.can().undo()).toBe(false)}
})
it('三入口全表切换完整有序意图，NodeSelection/CellSelection保留，独立undo/redo',()=>{
 const f=setup();f.select();expect(f.commands.reason('table-autofit-contents')).toBeNull();f.commands.run('table-autofit-contents');expect(f.live().attrs!.tblAutoFit).toBe('contents');expect(f.live().content![0].content![0].attrs!.colwidth).toBeNull()
 const contents=f.editor.getJSON();f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,f.editor.state.doc.child(0).nodeSize)));f.commands.run('table-autofit-window');expect(f.editor.state.selection).toBeInstanceOf(NodeSelection);expect(f.live().attrs!.widthPct).toBe(100)
 f.commands.run('table-autofit-fixed');expect(f.live().attrs!.widthPx).toBe(600);expect(f.live().attrs!.nativeTableAutoFit).toEqual({steps:[{mode:'contents'},{mode:'window'},{mode:'fixed'}]});expect(f.commands.active!('table-autofit-fixed')).toBe(true)
 f.editor.commands.undo();expect(f.live().attrs!.tblAutoFit).toBe('window');f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(contents);f.editor.commands.redo();expect(f.live().attrs!.tblAutoFit).toBe('window');expect(f.errors).toEqual([])
})
it('来源只读、锁、新表、同表文字/结构混编明确拒绝，格网失配拒绝',()=>{
 const f=setup();f.select();f.anchor.autoFitEditable=false;f.anchor.autoFitReadOnlyReason='来源无可信网格';expect(f.commands.reason('table-autofit-fixed')).toBe('来源无可信网格');f.anchor.autoFitEditable=true
 f.editor.setEditable(false);expect(f.commands.reason('table-autofit-fixed')).toMatch(/保存|不可编辑/);f.editor.setEditable(true)
 f.editor.commands.insertContent('changed');expect(f.commands.reason('table-autofit-fixed')).toMatch(/先保存|同表/)
 expect(()=>projectDocxAutoFit(f.baseline.content![1],{...f.anchor,autoFitCells:[]},[{mode:'contents'}],f.editor.schema)).toThrow(/网格/)
})
it('Ribbon三入口启用并反映模式，AutoFit后行高/列宽/标题/增删互斥',()=>{
 const f=setup();f.select();const ribbon=createDocxRibbon(f.editor,true,undefined,undefined,undefined,[f.anchor],f.commands);document.body.append(ribbon);ribbon.querySelector<HTMLButtonElement>('[data-tab-id="tableLayout"]')!.click()
 for(const mode of ['contents','window','fixed']){const button=ribbon.querySelector<HTMLButtonElement>(`[data-action="table-autofit-${mode}"]`)!;expect(button.disabled).toBe(false);expect(button.getAttribute('aria-pressed')).toBe(String(mode==='fixed'))}
 f.commands.run('table-autofit-contents');for(const action of ['table-column-width','table-row-height','table-repeat-header-rows','table-insert-row-before'])expect(f.commands.reason(action)).toMatch(/自动调整|AutoFit|先保存/)
})

it('真实collector/replay保留全部有序模式，草稿不得覆盖并拒绝同表文字',()=>{
 const f=setup('window');f.select();for(const mode of ['contents','window','fixed','fixed'])f.commands.run(`table-autofit-${mode}`)
 const anchors=[{docxIndex:0,blockId:'body',expectedObjectSha256:'body',editable:true},f.anchor]
 const operations=docxOperations(f.baseline,f.editor.getJSON(),anchors,undefined,f.editor.schema)
 expect(operations).toEqual([{kind:'setTableAutoFit',blockId:'table',expectedObjectSha256:'sha',steps:[{mode:'contents'},{mode:'window'},{mode:'fixed'},{mode:'fixed'}]}])
 expect(replayDocxOperations(f.baseline,operations,anchors,undefined,f.editor.schema)).toEqual(f.editor.getJSON())
 expect(normalizeDocxAutoFitSources(f.editor.getJSON(),anchors,f.editor.schema)).toEqual(f.editor.getJSON())
 const altered=structuredClone(f.editor.getJSON()) as DocxPmNode;altered.content![1].content![0].content![0].content![0].content![0].text='tampered'
 expect(()=>docxOperations(f.baseline,altered,anchors,undefined,f.editor.schema)).toThrow(/自动调整|同表|AutoFit/)
})
it('直接fixed保留奇数twip精度，CellSelection整表改模式，既有其他意图不能吞并',()=>{
 const f=setup('contents'),start=f.editor.state.doc.child(0).nodeSize+1,map=TableMap.get(f.editor.state.doc.child(1))
 f.editor.view.dispatch(f.editor.state.tr.setSelection(CellSelection.create(f.editor.state.doc,start+map.map[0],start+map.map[3])))
 f.commands.run('table-autofit-fixed');expect(f.live().attrs!.widthPx).toBe(6002/15);expect(f.live().content![1].content![1].attrs!.colwidth).toEqual([3601/15]);expect(f.editor.state.selection).toBeInstanceOf(CellSelection)
 const source=structuredClone(f.baseline.content![1]);source.attrs!.nativeTableRowHeights={steps:[{top:0,bottom:1,heightTwips:600}]}
 expect(()=>projectDocxAutoFit(source,f.anchor,[{mode:'window'}],f.editor.schema)).toThrow(/同表|先保存/)
})

it('无表、新增未保存、nested输入和已有其他结构意图拒绝AutoFit',()=>{
 const f=setup();f.editor.commands.setTextSelection(2);expect(f.commands.reason('table-autofit-fixed')).not.toBeNull();f.select()
 const nested=createDocxTableCommands(f.editor,f.baseline,[f.anchor],()=>{},()=>true);expect(nested.reason('table-autofit-window')).toMatch(/嵌套/)
 const tableStart=f.editor.state.doc.child(0).nodeSize,table=f.editor.state.doc.child(1)
 f.editor.view.dispatch(f.editor.state.tr.setNodeMarkup(tableStart,undefined,{...table.attrs,docxIndex:null,nativeTableInsert:{rows:2,cols:2}}));expect(f.commands.reason('table-autofit-contents')).toMatch(/新增|保存/)
 for(const intent of ['nativeTableStructure','nativeTableCellShape','nativeTableColumnWidths','nativeTableRowHeights']){
  const source=structuredClone(f.baseline.content![1]);source.attrs![intent]={steps:[]};expect(normalizeDocxAutoFitSources({type:'doc',content:[source]},[f.anchor],f.editor.schema).content![0]).toEqual(source);expect(()=>projectDocxAutoFit(source,f.anchor,[{mode:'contents'}],f.editor.schema)).toThrow(/同表|保存/)
 }
})
