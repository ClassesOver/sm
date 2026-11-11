import { afterEach, expect, it } from 'vitest'
import { Editor, Extension, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { CellSelection, TableMap } from '@tiptap/pm/tables'
import { NodeSelection } from '@tiptap/pm/state'
import { docxOperations, replayDocxOperations } from './docx-operations'
import { NativeTableStructure, createDocxTableCommands } from './docx-tables'
import { createDocxRibbon } from './docx-ribbon'
import { projectDocxRowHeights, type DocxRowHeightAnchor } from './docx-table-row-height'
import type { DocxAnchor, DocxPmNode } from './docx-operations'
const attrs = (values: Record<string, unknown>) => Object.fromEntries(Object.entries(values).map(([name, value]) => [name, { default: value }]))
const Doc = Node.create({ name:'doc',topNode:true,content:'block+' })
const Paragraph = Node.create({name:'docParagraph',group:'block',content:'text*',addAttributes:()=>attrs({docxIndex:null}),renderHTML:()=>['p',0]})
const Text=Node.create({name:'text',group:'inline'})
const Table=Node.create({name:'docTable',group:'block',content:'docTableRow+',addAttributes:()=>attrs({docxIndex:null}),renderHTML:()=>['table',['tbody',0]]})
const Row=Node.create({name:'docTableRow',content:'docTableCell*',addAttributes:()=>attrs({heightTwips:null,heightRule:null,rawTrPr:null}),renderHTML:()=>['tr',0]})
const Cell=Node.create({name:'docTableCell',content:'docParagraph+',addAttributes:()=>attrs({colspan:1,rowspan:1,colwidth:null}),renderHTML:()=>['td',0]})
const Roles=Extension.create({name:'roles',extendNodeSchema:extension=>({tableRole:({docTable:'table',docTableRow:'row',docTableCell:'cell'} as Record<string,string>)[extension.name]})})
const editors:Editor[]=[]
afterEach(()=>{editors.splice(0).forEach(editor=>editor.destroy());document.body.replaceChildren()})
function setup(merged=false){
 const cell=(text:string)=>({type:'docTableCell',content:[{type:'docParagraph',content:[{type:'text',text}]}]})
 const content:DocxPmNode={type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'body'}]},{type:'docTable',attrs:{docxIndex:1},content:[{type:'docTableRow',attrs:{heightTwips:300,heightRule:'exact',rawTrPr:'first'},content:[cell('A1'),cell('B1')]},{type:'docTableRow',attrs:{heightTwips:400,heightRule:'atLeast',rawTrPr:'second'},content:[cell('A2'),cell('B2')]}]}]}
 if(merged){const table=content.content![1];table.content![0].content![0].attrs={rowspan:2};table.content![1].content!.splice(0,1)}
 const editor=new Editor({extensions:[Doc,Paragraph,Text,Table,Row,Cell,Roles,NativeTableStructure,UndoRedo],content,editorProps:{handleScrollToSelection:()=>true}});editors.push(editor)
 const baseline=editor.getJSON() as DocxPmNode,table=editor.state.doc.child(1),map=TableMap.get(table)
 const anchor:DocxAnchor&DocxRowHeightAnchor={docxIndex:1,blockId:'table',expectedObjectSha256:'sha',editable:false,rowHeightEditable:true,rowHeightMaxTwips:1200,rowHeightsTwips:[300,400],rowHeightRules:['exact','atLeast'],rowHeightCells:[]}
 table.forEach((row,rowOffset,physicalRow)=>row.forEach((_cell,offset,physicalColumn)=>anchor.rowHeightCells!.push({...map.findCell(rowOffset+1+offset),physicalRow,physicalColumn})))
 const errors:string[]=[],commands=createDocxTableCommands(editor,baseline,[anchor],error=>errors.push(String(error)))
 const select=(row=0,col=0)=>{const map=TableMap.get(editor.state.doc.child(1));editor.commands.setTextSelection(editor.state.doc.child(0).nodeSize+3+map.map[row*map.width+col])}
 const heights=()=>editor.state.doc.child(1).content.content.map(row=>[row.attrs.heightTwips,row.attrs.heightRule])
 return{editor,baseline,anchor,commands,errors,select,heights}
}
const dialog=()=>document.querySelector<HTMLElement>('[role="dialog"][aria-label="行高"]')!
const submit=(value:string)=>{dialog().querySelector<HTMLInputElement>('[aria-label="行高（twip）"]')!.value=value;dialog().querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))}
it('指定行高保留exact、截断节上限、清空自动，分步撤销重做不改内容',()=>{
 const f=setup();f.select();expect(f.commands.reason('table-row-height')).toBeNull()
 f.commands.run('table-row-height');submit('600');expect(f.heights()).toEqual([[600,'exact'],[400,'atLeast']]);expect(f.errors).toEqual([])
 const once=f.editor.getJSON();f.commands.run('table-row-height');submit('5000');expect(f.heights()[0]).toEqual([1200,'exact'])
 f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(once);f.editor.commands.redo();expect(f.heights()[0]).toEqual([1200,'exact'])
 f.commands.run('table-row-height');submit('');expect(f.heights()[0]).toEqual([null,null]);expect(f.editor.state.doc.child(1).textContent).toBe('A1B1A2B2')
 expect(f.editor.getHTML()).not.toContain('nativeTableRowHeights')
})
it('rowspan caret覆盖完整行带，NodeSelection整表与多行选区同源投影',()=>{
 const f=setup(true);f.select();f.commands.run('table-row-height');submit('700');expect(f.heights()).toEqual([[700,'exact'],[700,'atLeast']])
 f.editor.commands.undo();f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,f.editor.state.doc.child(0).nodeSize)))
 f.commands.run('table-row-height');submit('');expect(f.heights()).toEqual([[null,null],[null,null]])
 const projected=projectDocxRowHeights(f.baseline.content![1],f.anchor,[{top:0,bottom:2,heightTwips:800}],f.editor.schema)
 expect(projected.content!.map(row=>row.attrs!.heightTwips)).toEqual([800,800]);expect(projected.content![0].attrs!.rawTrPr).toBe('first')
})
it('严格拒绝非法输入、冻结选区变化、保存锁、复杂混编与来源格网失配',()=>{
 const f=setup();f.select();f.commands.run('table-row-height')
 for(const value of ['-1','1.5','9007199254740992']){submit(value);expect(dialog().querySelector('[role="alert"]')!.textContent).not.toBe('');expect(f.editor.getJSON()).toEqual(f.baseline)}
 f.select(1,1);submit('600');expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/选区|选择/)
 dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click();f.commands.run('table-row-height');f.editor.setEditable(false);submit('600');expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/不可编辑|正在保存/)
 expect(()=>projectDocxRowHeights(f.baseline.content![1],{...f.anchor,rowHeightCells:[]},[{top:0,bottom:1,heightTwips:600}],f.editor.schema)).toThrow(/来源网格/)
 const altered=structuredClone(f.baseline.content![1]);altered.attrs={...altered.attrs,nativeTableColumnWidths:{steps:[]}}
 expect(()=>projectDocxRowHeights(altered,f.anchor,[{top:0,bottom:1,heightTwips:600}],f.editor.schema)).toThrow(/先保存|同表/)
})
it('Ribbon开放来源行高及均分行并拒绝同表其他结构修改',()=>{
 const f=setup();f.select();const ribbon=createDocxRibbon(f.editor,true,undefined,undefined,undefined,[f.anchor],f.commands);document.body.append(ribbon)
 ribbon.querySelector<HTMLButtonElement>('[data-tab-id="tableLayout"]')!.click();const button=(id:string)=>ribbon.querySelector<HTMLButtonElement>(`[data-action="${id}"]`)!
 expect(button('table-row-height').disabled).toBe(false);expect(button('table-distribute-rows').disabled).toBe(false)
 button('table-row-height').click();submit('600');expect(f.heights()[0]).toEqual([600,'exact'])
 for(const action of ['table-column-width','table-merge-cells','table-insert-row-before','table-repeat-header-rows']){if(action==='table-merge-cells'){const start=f.editor.state.doc.child(0).nodeSize+1,map=TableMap.get(f.editor.state.doc.child(1));f.editor.view.dispatch(f.editor.state.tr.setSelection(CellSelection.create(f.editor.state.doc,start+map.map[0],start+map.map[3])))}expect(f.commands.reason(action)).toMatch(/先保存|行高|来源表格/)}
})

it('真实collector/replay恢复多步行高，原baseline不改并拒绝同表文字变化',()=>{
 const f=setup();f.select();f.commands.run('table-row-height');submit('600');f.select(1,1);f.commands.run('table-row-height');submit('')
 const anchors=[{docxIndex:0,blockId:'body',expectedObjectSha256:'body-sha',editable:true},f.anchor]
 const operations=docxOperations(f.baseline,f.editor.getJSON(),anchors,undefined,f.editor.schema)
 expect(operations).toEqual([{kind:'setTableRowHeights',blockId:'table',expectedObjectSha256:'sha',steps:[{top:0,bottom:1,heightTwips:600},{top:1,bottom:2,heightTwips:null}]}])
 expect(replayDocxOperations(f.baseline,operations,anchors,undefined,f.editor.schema)).toEqual(f.editor.getJSON())
 const changed=structuredClone(f.editor.getJSON()) as DocxPmNode;changed.content![1].content![0].content![0].content![0].content![0].text='tampered'
 expect(()=>docxOperations(f.baseline,changed,anchors,undefined,f.editor.schema)).toThrow(/同表|行高|布局|保存/)
 expect(f.baseline.content![1].content![0].attrs!.heightTwips).toBe(300)
})

it('源hRule省略按有效atLeast比较，baseline保持原属性',()=>{
 const f=setup(),source=structuredClone(f.baseline.content![1]);source.content![1].attrs!.heightRule=null
 const projected=projectDocxRowHeights(source,f.anchor,[{top:1,bottom:2,heightTwips:650}],f.editor.schema)
 expect(projected.content![1].attrs!.heightRule).toBe('atLeast');expect(source.content![1].attrs!.heightRule).toBeNull()
})
it('输入0恢复自动行高并提交null步骤',()=>{
 const f=setup();f.select();f.commands.run('table-row-height');submit('0')
 expect(f.heights()[0]).toEqual([null,null])
 expect(f.editor.state.doc.child(1).attrs.nativeTableRowHeights.steps).toEqual([{top:0,bottom:1,heightTwips:null}])
})
it('跨行CellSelection覆盖两行且来源只读原因返回Ribbon',()=>{
 const f=setup(),start=f.editor.state.doc.child(0).nodeSize+1,map=TableMap.get(f.editor.state.doc.child(1))
 f.editor.view.dispatch(f.editor.state.tr.setSelection(CellSelection.create(f.editor.state.doc,start+map.map[0],start+map.map[3])))
 f.commands.run('table-row-height');submit('650');expect(f.heights()).toEqual([[650,'exact'],[650,'atLeast']])
 f.anchor.rowHeightEditable=false;f.anchor.rowHeightReadOnlyReason='来源行高含不支持的规则'
 expect(f.commands.reason('table-row-height')).toBe('来源行高含不支持的规则')
})
it('均分按真实DOM高度，caret整表，set与均分共享有序意图并独立undo',async()=>{
 const f=setup();document.body.append(f.editor.view.dom);f.select()
 const rows=[...f.editor.view.dom.querySelectorAll('tr')]
 rows.forEach((row,i)=>row.getBoundingClientRect=()=>({height:i?70:30} as DOMRect))
 expect(f.commands.reason('table-distribute-rows')).toBeNull();f.commands.run('table-distribute-rows')
 await new Promise(resolve=>setTimeout(resolve,60));expect(f.heights()).toEqual([[750,'atLeast'],[750,'atLeast']])
 expect(f.editor.state.doc.child(1).attrs.nativeTableRowHeights.steps).toEqual([{kind:'distributeTableRows',top:0,bottom:2,heightTwips:750}])
 f.commands.run('table-row-height');submit('600');expect(f.heights()[0]).toEqual([600,'atLeast'])
 f.editor.commands.undo();expect(f.heights()).toEqual([[750,'atLeast'],[750,'atLeast']]);f.editor.commands.undo();expect(f.heights()).toEqual([[300,'exact'],[400,'atLeast']])
})
it('均分等待期间选区变化、保存锁或缺失行不产生事务',async()=>{
 const f=setup();document.body.append(f.editor.view.dom);f.select()
 const rows=[...f.editor.view.dom.querySelectorAll('tr')];rows.forEach(row=>row.getBoundingClientRect=()=>({height:40} as DOMRect))
 f.commands.run('table-distribute-rows');f.select(1,1);await new Promise(resolve=>setTimeout(resolve,60));expect(f.editor.getJSON()).toEqual(f.baseline);expect(f.errors.at(-1)).toMatch(/改变/)
 f.commands.run('table-distribute-rows');f.editor.setEditable(false);await new Promise(resolve=>setTimeout(resolve,60));expect(f.editor.getJSON()).toEqual(f.baseline);f.editor.setEditable(true)
 rows[1].getBoundingClientRect=()=>({height:0} as DOMRect);f.commands.run('table-distribute-rows');await new Promise(resolve=>setTimeout(resolve,60));expect(f.editor.getJSON()).toEqual(f.baseline);expect(f.errors.at(-1)).toMatch(/高度|测量/)
})
it('均分完整CellSelection及rowspan行带，超节高度保留并强制atLeast',async()=>{
 const f=setup(true);document.body.append(f.editor.view.dom);f.select();[...f.editor.view.dom.querySelectorAll('tr')].forEach(row=>row.getBoundingClientRect=()=>({height:100} as DOMRect))
 f.commands.run('table-distribute-rows');await new Promise(resolve=>setTimeout(resolve,60));expect(f.heights()).toEqual([[1500,'atLeast'],[1500,'atLeast']]);expect(f.errors).toEqual([])
 const anchors=[{docxIndex:0,blockId:'body',expectedObjectSha256:'body-sha',editable:true},f.anchor],operations=docxOperations(f.baseline,f.editor.getJSON(),anchors,undefined,f.editor.schema)
 expect(operations[0]).toMatchObject({kind:'setTableRowHeights',steps:[{kind:'distributeTableRows',top:0,bottom:2,heightTwips:1500}]})
 expect(replayDocxOperations(f.baseline,operations,anchors,undefined,f.editor.schema)).toEqual(f.editor.getJSON())
})
