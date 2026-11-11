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
const Table=Node.create({name:'docTable',group:'block',content:'docTableRow+',addAttributes:()=>attrs({docxIndex:null,cellMar:null,cellMarEdited:false,rawTblPr:'source',tblAlign:null,tblFloatSource:false,tblFloatSuppressed:false}),renderHTML:()=>['table',['tbody',0]]})
const Row=Node.create({name:'docTableRow',content:'docTableCell+',addAttributes:()=>attrs({cantSplit:false,cantSplitEdited:false,rawTrPr:'source-row'}),renderHTML:()=>['tr',0]})
const Cell=Node.create({name:'docTableCell',content:'docParagraph+',addAttributes:()=>attrs({colspan:1,rowspan:1,colwidth:null,cellMar:null,tcPrEdited:false,rawTcPr:'source-cell'}),renderHTML:()=>['td',0]})
const Roles=Extension.create({name:'roles',extendNodeSchema:e=>({tableRole:({docTable:'table',docTableRow:'row',docTableCell:'cell'} as Record<string,string>)[e.name]})})
const editors:Editor[]=[];afterEach(()=>{editors.splice(0).forEach(e=>e.destroy());document.body.replaceChildren()})
function setup(){
 const content:DocxPmNode={type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'body'}]},{type:'docTable',attrs:{docxIndex:1,cellMar:{top:0,right:109,bottom:7,left:108}},content:[0,1].map(r=>({type:'docTableRow',attrs:{cantSplit:r===0},content:[0,1].map(c=>({type:'docTableCell',attrs:{cellMar:c?null:{left:r?71:33,top:0}},content:[{type:'docParagraph',content:[{type:'text',text:`${r}:${c}`}]}]}))}))}]}
 const editor=new Editor({extensions:[Doc,Paragraph,Text,Table,Row,Cell,Roles,NativeTableStructure,UndoRedo],content,editorProps:{handleScrollToSelection:()=>true}});editors.push(editor)
 const baseline=editor.getJSON() as DocxPmNode,anchor:any={docxIndex:1,blockId:'table',expectedObjectSha256:'sha',editable:false,tableCellMarginOverridesEditable:true,tableCellMarginOverridesSource:{cells:[{top:0,left:0,bottom:1,right:1,rawPresent:true,raw:{left:33,top:0},effective:{left:33,top:0},resetEffective:{left:77,top:7}},{top:0,left:1,bottom:1,right:2,rawPresent:false,raw:null,effective:null,resetEffective:null},{top:1,left:0,bottom:2,right:1,rawPresent:true,raw:{left:71,top:0},effective:{left:71,top:0},resetEffective:null},{top:1,left:1,bottom:2,right:2,rawPresent:true,raw:null,effective:null,resetEffective:null}]}}
 anchor.tableAlignmentEditable=true;anchor.tableAlignmentSource={alignment:null,raw:'<w:jc w:val="start"/>',rawIndent:null,rawWidth:null,bidiVisual:false,positioning:'inline',cells:anchor.tableCellMarginOverridesSource.cells.map(({top,left,bottom,right}:any)=>({top,left,bottom,right}))}
 anchor.rowBreakEditable=true;anchor.rowBreakSource={cells:anchor.tableCellMarginOverridesSource.cells.map(({top,left,bottom,right}:any)=>({top,left,bottom,right})),rows:[{cantSplit:true,raw:'<w:cantSplit/>'},{cantSplit:false,raw:null}]}
 anchor.tableCellMarginOverridesSource.cells.forEach((cell:any)=>{cell.hasPhysicalOverrides=cell.rawPresent})
 const errors:string[]=[],commands=createDocxTableCommands(editor,baseline,[anchor],e=>errors.push(String(e))),start=editor.state.doc.child(0).nodeSize+1
 const select=(n=0)=>editor.commands.setTextSelection(start+2+TableMap.get(editor.state.doc.child(1)).map[n]),margins=()=>editor.state.doc.child(1).attrs.cellMar
 const cell=(n=0)=>editor.state.doc.nodeAt(start+TableMap.get(editor.state.doc.child(1)).map[n])!
 const rect=()=>{const map=TableMap.get(editor.state.doc.child(1));editor.view.dispatch(editor.state.tr.setSelection(CellSelection.create(editor.state.doc,start+map.map[0],start+map.map[3])))}
 const open=()=>commands.run('table-properties')
 return{editor,anchor,baseline,commands,errors,start,select,margins,cell,rect,open}
}
it('整表对齐独立入口可用且未改值确认不dirty',()=>{
 const f=setup();f.select();expect(f.commands.reason('table-alignment')).toBeNull();f.commands.run('table-alignment');const dialog=document.querySelector<HTMLElement>('[role="dialog"][aria-label="整表对齐"]')!;expect(dialog).not.toBeNull();expect(dialog.querySelector<HTMLSelectElement>('select')!.value).toBe('left');dialog.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));expect(f.editor.getJSON()).toEqual(f.baseline);expect(f.editor.can().undo()).toBe(false)
})
const dialog=()=>document.querySelector<HTMLElement>('[role="dialog"][aria-label="整表对齐"]')!
const submit=()=>dialog().querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
const choose=(value:string)=>{dialog().querySelector<HTMLSelectElement>('select')!.value=value;submit()}
const open=(f:ReturnType<typeof setup>)=>f.commands.run('table-alignment')
it('连续最终值与left重开null语义、矩形/NodeSelection定位整表、UndoRedo和真实collector草稿',()=>{
 const f=setup();f.rect();open(f);choose('center');expect(f.editor.state.doc.child(1).attrs.tblAlign).toBe('center');f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(f.baseline);f.editor.commands.redo();f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,f.start-1)));open(f);choose('right');expect(f.editor.state.selection).toBeInstanceOf(NodeSelection);open(f);choose('left');expect(f.editor.state.doc.child(1).attrs.tblAlign).toBeNull();expect(f.editor.state.doc.child(1).attrs.nativeTableAlignment).toEqual({alignment:'left'})
 const anchors:DocxAnchor[]=[{docxIndex:0,blockId:'body',expectedObjectSha256:'body',editable:true},f.anchor],operations=docxOperations(f.baseline,f.editor.getJSON(),anchors,undefined,f.editor.schema);expect(operations).toEqual([{kind:'setTableAlignment',blockId:'table',expectedObjectSha256:'sha',alignment:'left'}]);expect(replayDocxOperations(f.baseline,operations,anchors,undefined,f.editor.schema)).toEqual(f.editor.getJSON());expect(f.errors).toEqual([])
})
it('属性导航保持边距与行入口，能力独立fallback，RTL/浮动说明可见',()=>{
 const f=setup();f.select();f.anchor.tableAlignmentSource.bidiVisual=true;f.anchor.tableAlignmentSource.positioning='floating';f.commands.run('table-properties');const margins=document.querySelector<HTMLElement>('[aria-label="单元格边距"]')!;expect(margins.querySelector('[data-action="row-breaks"]')).not.toBeNull();margins.querySelector<HTMLButtonElement>('[data-action="table-alignment"]')!.click();expect(dialog().textContent).toMatch(/起始侧.*从右到左/s);expect(dialog().querySelector('[role="note"]')!.textContent).toMatch(/浮动定位优先/);submit();expect(f.editor.getJSON()).toEqual(f.baseline)
 f.anchor.tableCellMarginOverridesEditable=false;f.anchor.rowBreakEditable=false;expect(f.commands.reason('table-properties')).toBeNull();f.commands.run('table-properties');document.querySelector<HTMLButtonElement>('[aria-label="表格属性选项"] [data-action="table-alignment"]')!.click();expect(dialog()).not.toBeNull();submit()
})
it('stale来源/选区/文字、锁、nested以及全部同表意图拒绝',()=>{
 const f=setup();f.select();open(f);f.select(3);choose('center');expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/选区|选择/);dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click();open(f);f.anchor.tableAlignmentSource.raw='changed';submit();expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/来源|改变/);dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click();f.anchor.tableAlignmentSource.raw='<w:jc w:val="start"/>'
 for(const name of ['nativeTableStructure','nativeTableCellShape','nativeTableColumnWidths','nativeTableRowHeights','nativeTableAutoFit','nativeTableCellTextDirection','nativeTableCellAlignment','nativeTableCellMargins','nativeTableCellMarginOverrides','nativeTableRowBreaks']){const table=f.editor.state.doc.child(1);f.editor.view.dispatch(f.editor.state.tr.setNodeMarkup(f.start-1,undefined,{...table.attrs,[name]:{steps:[]}}));expect(f.commands.reason('table-alignment')).not.toBeNull();f.editor.view.dispatch(f.editor.state.tr.setNodeMarkup(f.start-1,undefined,{...table.attrs}))}
 open(f);choose('center');for(const action of ['table-cell-margins','table-row-breaks','table-align-top-left','table-text-direction-horizontal','table-autofit-fixed','table-row-height','table-column-width','table-repeat-header-rows','table-insert-row-before'])expect(f.commands.reason(action)).not.toBeNull();expect(createDocxTableCommands(f.editor,f.baseline,[f.anchor],()=>{},()=>true).reason('table-alignment')).toMatch(/嵌套/);f.editor.setEditable(false);expect(f.commands.reason('table-alignment')).toMatch(/保存|不可编辑/)
})
it('merged owner定位整表且不改所有cell，额外intent字段/过期doc及伪造草稿拒绝',()=>{
 const f=setup();const value=structuredClone(f.baseline) as DocxPmNode,rows=value.content![1].content!;rows[0].content![0].attrs!.rowspan=2;rows[1].content!.shift();f.editor.commands.setContent(value);const baseline=f.editor.getJSON() as DocxPmNode,anchor={...f.anchor,tableAlignmentSource:{...f.anchor.tableAlignmentSource,cells:[{top:0,left:0,bottom:2,right:1},{top:0,left:1,bottom:1,right:2},{top:1,left:1,bottom:2,right:2}]}}
 const commands=createDocxTableCommands(f.editor,baseline,[anchor],e=>f.errors.push(String(e)));f.editor.commands.setTextSelection(f.start+2+TableMap.get(f.editor.state.doc.child(1)).map[0]);commands.run('table-alignment');choose('right');expect((f.editor.getJSON() as DocxPmNode).content![1].content).toEqual(baseline.content![1].content)
 const anchors:DocxAnchor[]=[{docxIndex:0,blockId:'body',expectedObjectSha256:'body',editable:true},anchor],operations=docxOperations(baseline,f.editor.getJSON(),anchors,undefined,f.editor.schema);expect(operations[0].kind).toBe('setTableAlignment');expect(()=>replayDocxOperations(baseline,[{...operations[0],expectedObjectSha256:'forged'}],anchors,undefined,f.editor.schema)).toThrow();expect(()=>replayDocxOperations(baseline,[{...operations[0],raw:'forged'}],anchors,undefined,f.editor.schema)).toThrow()
 const table=f.editor.state.doc.child(1);f.editor.view.dispatch(f.editor.state.tr.setNodeMarkup(f.start-1,undefined,{...table.attrs,nativeTableAlignment:{alignment:'right',foreign:true}}));expect(commands.reason('table-alignment')).toMatch(/草稿/)
})
it('raw start/end无操作不规范化，floating警示下仍可写jc',()=>{
 for(const [raw,current] of [['start',null],['end','right']] as const){const f=setup();const value=structuredClone(f.baseline) as DocxPmNode;value.content![1].attrs!.tblAlign=current;f.editor.commands.setContent(value);const baseline=f.editor.getJSON() as DocxPmNode,anchor={...f.anchor,tableAlignmentSource:{...f.anchor.tableAlignmentSource,raw:`<w:jc w:val="${raw}"/>`,alignment:current}};const commands=createDocxTableCommands(f.editor,baseline,[anchor],e=>f.errors.push(String(e)));f.select();const undoBefore=f.editor.can().undo();commands.run('table-alignment');submit();expect(f.editor.getJSON()).toEqual(baseline);expect(f.editor.can().undo()).toBe(undoBefore)}
 const f=setup();f.anchor.tableAlignmentSource.positioning='floating';f.select();open(f);expect(dialog().querySelector('[role="note"]')!.textContent).toMatch(/当前位置仍保持原浮动定位/);choose('center');expect(f.editor.state.doc.child(1).attrs.tblAlign).toBe('center');const operations=docxOperations(f.baseline,f.editor.getJSON(),[{docxIndex:0,blockId:'body',expectedObjectSha256:'body',editable:true},f.anchor],undefined,f.editor.schema);expect(operations[0]).toMatchObject({kind:'setTableAlignment',alignment:'center'})
})
