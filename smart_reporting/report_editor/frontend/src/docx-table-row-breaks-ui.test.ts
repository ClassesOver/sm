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
const Row=Node.create({name:'docTableRow',content:'docTableCell+',addAttributes:()=>attrs({cantSplit:false,cantSplitEdited:false,rawTrPr:'source-row'}),renderHTML:()=>['tr',0]})
const Cell=Node.create({name:'docTableCell',content:'docParagraph+',addAttributes:()=>attrs({colspan:1,rowspan:1,colwidth:null,cellMar:null,tcPrEdited:false,rawTcPr:'source-cell'}),renderHTML:()=>['td',0]})
const Roles=Extension.create({name:'roles',extendNodeSchema:e=>({tableRole:({docTable:'table',docTableRow:'row',docTableCell:'cell'} as Record<string,string>)[e.name]})})
const editors:Editor[]=[];afterEach(()=>{editors.splice(0).forEach(e=>e.destroy());document.body.replaceChildren()})
function setup(){
 const content:DocxPmNode={type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'body'}]},{type:'docTable',attrs:{docxIndex:1,cellMar:{top:0,right:109,bottom:7,left:108}},content:[0,1].map(r=>({type:'docTableRow',attrs:{cantSplit:r===0},content:[0,1].map(c=>({type:'docTableCell',attrs:{cellMar:c?null:{left:r?71:33,top:0}},content:[{type:'docParagraph',content:[{type:'text',text:`${r}:${c}`}]}]}))}))}]}
 const editor=new Editor({extensions:[Doc,Paragraph,Text,Table,Row,Cell,Roles,NativeTableStructure,UndoRedo],content,editorProps:{handleScrollToSelection:()=>true}});editors.push(editor)
 const baseline=editor.getJSON() as DocxPmNode,anchor:any={docxIndex:1,blockId:'table',expectedObjectSha256:'sha',editable:false,tableCellMarginOverridesEditable:true,tableCellMarginOverridesSource:{cells:[{top:0,left:0,bottom:1,right:1,rawPresent:true,raw:{left:33,top:0},effective:{left:33,top:0},resetEffective:{left:77,top:7}},{top:0,left:1,bottom:1,right:2,rawPresent:false,raw:null,effective:null,resetEffective:null},{top:1,left:0,bottom:2,right:1,rawPresent:true,raw:{left:71,top:0},effective:{left:71,top:0},resetEffective:null},{top:1,left:1,bottom:2,right:2,rawPresent:true,raw:null,effective:null,resetEffective:null}]}}
 anchor.rowBreakEditable=true;anchor.rowBreakSource={cells:anchor.tableCellMarginOverridesSource.cells.map(({top,left,bottom,right}:any)=>({top,left,bottom,right})),rows:[{cantSplit:true,raw:'<w:cantSplit/>'},{cantSplit:false,raw:null}]}
 anchor.tableCellMarginOverridesSource.cells.forEach((cell:any)=>{cell.hasPhysicalOverrides=cell.rawPresent})
 const errors:string[]=[],commands=createDocxTableCommands(editor,baseline,[anchor],e=>errors.push(String(e))),start=editor.state.doc.child(0).nodeSize+1
 const select=(n=0)=>editor.commands.setTextSelection(start+2+TableMap.get(editor.state.doc.child(1)).map[n]),margins=()=>editor.state.doc.child(1).attrs.cellMar
 const cell=(n=0)=>editor.state.doc.nodeAt(start+TableMap.get(editor.state.doc.child(1)).map[n])!
 const rect=()=>{const map=TableMap.get(editor.state.doc.child(1));editor.view.dispatch(editor.state.tr.setSelection(CellSelection.create(editor.state.doc,start+map.map[0],start+map.map[3])))}
 const open=()=>commands.run('table-properties')
 return{editor,anchor,baseline,commands,errors,start,select,margins,cell,rect,open}
}
const dialog=()=>document.querySelector<HTMLElement>('[role="dialog"][aria-label="行跨页"]')!
const checkbox=()=>dialog().querySelector<HTMLInputElement>('[data-action="allow-break"]')!
const submit=()=>dialog().querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
const choose=(value:boolean)=>{checkbox().checked=value;checkbox().indeterminate=false;checkbox().dispatchEvent(new Event('change',{bubbles:true}))}
const open=(f:ReturnType<typeof setup>)=>f.commands.run('table-row-breaks')
it('行跨页来源入口可用，混合不操作不dirty，独立undo redo与行带',()=>{
 const f=setup();f.rect();expect(f.commands.reason('table-row-breaks')).toBeNull();open(f);expect(checkbox().indeterminate).toBe(true);expect(checkbox().getAttribute('aria-checked')).toBe('mixed');submit();expect(f.editor.getJSON()).toEqual(f.baseline);expect(f.editor.can().undo()).toBe(false)
 open(f);choose(false);submit();expect(f.editor.state.doc.child(1).content.content.map(row=>row.attrs.cantSplit)).toEqual([true,true]);f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(f.baseline);f.editor.commands.redo();expect(f.editor.state.doc.child(1).child(1).attrs.cantSplit).toBe(true)
})
it('首行caret无操作，全表NodeSelection，连续重叠steps及真实collector草稿',()=>{
 const f=setup();f.select();open(f);expect(checkbox().checked).toBe(false);submit();expect(f.editor.getJSON()).toEqual(f.baseline)
 open(f);choose(true);submit();f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,f.start-1)));open(f);choose(false);submit();expect(f.editor.state.selection).toBeInstanceOf(NodeSelection)
 const anchors:DocxAnchor[]=[{docxIndex:0,blockId:'body',expectedObjectSha256:'body',editable:true},f.anchor],operations=docxOperations(f.baseline,f.editor.getJSON(),anchors,undefined,f.editor.schema)
 expect(operations[0]).toEqual({kind:'setTableRowBreaks',blockId:'table',expectedObjectSha256:'sha',steps:[{top:0,bottom:1,allowBreak:true},{top:0,bottom:2,allowBreak:false}]});expect(replayDocxOperations(f.baseline,operations,anchors,undefined,f.editor.schema)).toEqual(f.editor.getJSON())
})
it('过期选区/来源/文档与锁阻止提交，nested和同表独立意图双向互斥',()=>{
 const f=setup();f.select();open(f);choose(true);f.select(3);submit();expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/选区|选择/);dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
 open(f);f.anchor.rowBreakSource.rows[0].raw='changed';submit();expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/来源|改变/);dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click();f.anchor.rowBreakSource.rows[0].raw='<w:cantSplit/>'
 f.select();open(f);choose(true);submit();for(const action of ['table-cell-margins','table-align-top-left','table-text-direction-horizontal','table-autofit-fixed','table-row-height','table-column-width','table-repeat-header-rows','table-insert-row-before'])expect(f.commands.reason(action)).not.toBeNull()
 expect(createDocxTableCommands(f.editor,f.baseline,[f.anchor],()=>{},()=>true).reason('table-row-breaks')).toMatch(/嵌套/);f.editor.setEditable(false);expect(f.commands.reason('table-row-breaks')).toMatch(/保存|不可编辑/)
})
it('属性保留边距dialog并独立导航，边距不可用仍可行跨页，cap原因各自独立',()=>{
 const f=setup();f.select();f.commands.run('table-properties');let margin=document.querySelector<HTMLElement>('[role="dialog"][aria-label="单元格边距"]')!;expect(margin).not.toBeNull();margin.querySelector<HTMLButtonElement>('[data-action="row-breaks"]')!.click();expect(dialog()).not.toBeNull();submit();expect(f.editor.getJSON()).toEqual(f.baseline)
 f.anchor.tableCellMarginOverridesEditable=false;f.anchor.tableCellMarginOverridesReadOnlyReason='边距来源不可编辑';expect(f.commands.reason('table-properties')).toBeNull();f.commands.run('table-properties');const menu=document.querySelector<HTMLElement>('[aria-label="表格属性选项"]')!;expect(menu.querySelector<HTMLButtonElement>('[data-action="margins"]')!.disabled).toBe(true);menu.querySelector<HTMLButtonElement>('[data-action="row-breaks"]')!.click();expect(dialog()).not.toBeNull();submit()
 f.anchor.tableCellMarginOverridesEditable=true;f.anchor.rowBreakEditable=false;f.anchor.rowBreakReadOnlyReason='跨页来源歧义';expect(f.commands.reason('table-properties')).toBeNull();f.commands.run('table-properties');margin=document.querySelector('[aria-label="单元格边距"]')!;expect(margin.querySelector<HTMLButtonElement>('[data-action="row-breaks"]')!.disabled).toBe(true);expect(margin.querySelector('[data-row-reason]')!.textContent).toBe('跨页来源歧义')
})
it('当前所选合并owner决定行带，不向全列其他合并格扩展',()=>{
 const f=setup();const value=structuredClone(f.baseline) as DocxPmNode,rows=value.content![1].content!;rows[0].content![0].attrs!.rowspan=2;rows[1].content!.shift();f.editor.commands.setContent(value);const baseline=f.editor.getJSON() as DocxPmNode
 const anchor={...f.anchor,rowBreakSource:{rows:f.anchor.rowBreakSource.rows,cells:[{top:0,left:0,bottom:2,right:1},{top:0,left:1,bottom:1,right:2},{top:1,left:1,bottom:2,right:2}]}},commands=createDocxTableCommands(f.editor,baseline,[anchor],e=>f.errors.push(String(e)))
 f.editor.commands.setTextSelection(f.start+2+TableMap.get(f.editor.state.doc.child(1)).map[0]);commands.run('table-row-breaks');expect(dialog().textContent).toContain('第 1–2 行');choose(false);submit();const intent=f.editor.state.doc.child(1).attrs.nativeTableRowBreaks;expect(intent.steps).toEqual([{top:0,bottom:2,allowBreak:false}]);f.editor.commands.undo()
 f.editor.commands.setTextSelection(f.start+2+TableMap.get(f.editor.state.doc.child(1)).map[1]);commands.run('table-row-breaks');expect(dialog().textContent).toContain('第 1 行');choose(true);submit();expect(f.editor.state.doc.child(1).attrs.nativeTableRowBreaks.steps).toEqual([{top:0,bottom:1,allowBreak:true}])
})
