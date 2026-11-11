import { afterEach, expect, it } from 'vitest'
import { Editor, Extension, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { CellSelection, TableMap } from '@tiptap/pm/tables'
import { NodeSelection } from '@tiptap/pm/state'
import { NativeTableStructure, createDocxTableCommands } from './docx-tables'
import { type DocxPmNode } from './docx-operations'
const attrs=(v:Record<string,unknown>)=>Object.fromEntries(Object.entries(v).map(([key,value])=>[key,{default:value}]))
const Doc=Node.create({name:'doc',topNode:true,content:'block+'}),Text=Node.create({name:'text',group:'inline'})
const Paragraph=Node.create({name:'docParagraph',group:'block',content:'text*',addAttributes:()=>attrs({docxIndex:null}),renderHTML:()=>['p',0]})
const Table=Node.create({name:'docTable',group:'block',content:'docTableRow+',addAttributes:()=>attrs({docxIndex:null,cellMar:null,cellMarEdited:false,rawTblPr:'source'}),renderHTML:()=>['table',['tbody',0]]})
const Row=Node.create({name:'docTableRow',content:'docTableCell+',renderHTML:()=>['tr',0]})
const Cell=Node.create({name:'docTableCell',content:'docParagraph+',addAttributes:()=>attrs({colspan:1,rowspan:1,colwidth:null,cellMar:null,noWrap:null,tcPrEdited:false,rawTcPr:'source-cell'}),renderHTML:()=>['td',0]})
const Roles=Extension.create({name:'roles',extendNodeSchema:e=>({tableRole:({docTable:'table',docTableRow:'row',docTableCell:'cell'} as Record<string,string>)[e.name]})})
const editors:Editor[]=[];afterEach(()=>{editors.splice(0).forEach(e=>e.destroy());document.body.replaceChildren()})
function setup(){
 const content:DocxPmNode={type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'body'}]},{type:'docTable',attrs:{docxIndex:1,cellMar:{top:0,right:109,bottom:7,left:108}},content:[0,1].map(r=>({type:'docTableRow',content:[0,1].map(c=>({type:'docTableCell',attrs:{cellMar:c?null:{left:r?71:33,top:0}},content:[{type:'docParagraph',content:[{type:'text',text:`${r}:${c}`}]}]}))}))}]}
 const editor=new Editor({extensions:[Doc,Paragraph,Text,Table,Row,Cell,Roles,NativeTableStructure,UndoRedo],content,editorProps:{handleScrollToSelection:()=>true}});editors.push(editor)
 const baseline=editor.getJSON() as DocxPmNode,anchor:any={docxIndex:1,blockId:'table',expectedObjectSha256:'sha',editable:false,tableCellWrapEditable:true,tableCellWrapSource:{cells:[0,1,2,3].map(n=>({top:Math.floor(n/2),left:n%2,bottom:Math.floor(n/2)+1,right:n%2+1,rawPresent:false,hasPhysicalNoWrap:false,raw:null,noWrap:false,resetNoWrap:false}))}}

 const errors:string[]=[],commands=createDocxTableCommands(editor,baseline,[anchor],e=>errors.push(String(e))),start=editor.state.doc.child(0).nodeSize+1
 const select=(n=0)=>editor.commands.setTextSelection(start+2+TableMap.get(editor.state.doc.child(1)).map[n]),margins=()=>editor.state.doc.child(1).attrs.cellMar
 const cell=(n=0)=>editor.state.doc.nodeAt(start+TableMap.get(editor.state.doc.child(1)).map[n])!
 const rect=()=>{const map=TableMap.get(editor.state.doc.child(1));editor.view.dispatch(editor.state.tr.setSelection(CellSelection.create(editor.state.doc,start+map.map[0],start+map.map[3])))}
 const open=()=>commands.run('table-properties')
 return{editor,anchor,baseline,commands,errors,start,select,margins,cell,rect,open}
}
const dialog=()=>document.querySelector<HTMLElement>('[role="dialog"][aria-label="自动换行"]')!
const submit=()=>dialog().querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
const checkbox=()=>dialog().querySelector<HTMLInputElement>('input[type="checkbox"]')!
const toggle=()=>checkbox().click()
it('properties navigation exposes separate wrap control and preserves noop undo source semantics',()=>{
 const f=setup();f.select();f.commands.run('table-properties');document.querySelector<HTMLButtonElement>('[data-action="cell-wrap"]')!.click();expect(checkbox().checked).toBe(true);submit();expect(f.editor.getJSON()).toEqual(f.baseline);expect(f.editor.can().undo()).toBe(false)
 f.commands.run('table-cell-wrap');toggle();submit();expect(f.cell().attrs.noWrap).toBe(true);expect(f.cell(1).attrs.noWrap).toBeNull();expect(f.cell().attrs.tcPrEdited).toBe(false);expect(f.editor.state.doc.child(1).attrs.nativeTableCellWrap.steps).toEqual([{top:0,left:0,bottom:1,right:1,wrap:false}]);f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(f.baseline)
})
it('mixed range stays unchanged until touched; stale selection and readonly refuse',()=>{
 const f=setup();const table=f.editor.state.doc.child(1),map=TableMap.get(table),pos=f.start+map.map[0];f.editor.view.dispatch(f.editor.state.tr.setNodeMarkup(pos,undefined,{...f.cell().attrs,noWrap:true}));f.anchor.tableCellWrapSource.cells[0]={...f.anchor.tableCellWrapSource.cells[0],rawPresent:true,hasPhysicalNoWrap:true,raw:'<w:noWrap/>',noWrap:true};f.baseline.content![1]=f.editor.getJSON().content![1] as DocxPmNode
 // Commands capture the original baseline object by reference.
 f.rect();f.commands.run('table-cell-wrap');expect(checkbox().indeterminate).toBe(true);submit();expect(f.editor.state.doc.child(1).attrs.nativeTableCellWrap).toBeNull()
 f.commands.run('table-cell-wrap');toggle();f.select(1);submit();expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/选区|改变/)
 dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click();f.editor.setEditable(false);expect(f.commands.reason('table-cell-wrap')).toMatch(/不可编辑|保存/)
})

it('merged lower logical selection edits owner once and rejects bare table selection',()=>{
 const f=setup(),owner=f.cell()
 const table=f.editor.state.doc.child(1),upper=table.child(0),lower=table.child(1)
 const merged=table.type.create(table.attrs,[
  upper.type.create(upper.attrs,[owner.type.create({...owner.attrs,rowspan:2},owner.content),upper.child(1)]),
  lower.type.create(lower.attrs,[lower.child(1)])
 ])
 f.editor.view.dispatch(f.editor.state.tr.replaceWith(f.start-1,f.start-1+table.nodeSize,merged))
 f.baseline.content![1]=f.editor.getJSON().content![1] as DocxPmNode
 const c=f.anchor.tableCellWrapSource.cells
 f.anchor.tableCellWrapSource.cells=[{...c[0],bottom:2},c[1],c[3]]
 f.select(2);f.commands.run('table-cell-wrap');toggle();submit()
 expect(f.cell().attrs.noWrap).toBe(true)
 expect(f.cell(3).attrs.noWrap).toBeNull()
 expect(f.editor.state.doc.child(1).attrs.nativeTableCellWrap.steps).toEqual([{top:0,left:0,bottom:2,right:1,wrap:false}])
 f.editor.commands.undo()
 f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,f.start-1)))
 expect(f.commands.reason('table-cell-wrap')).toMatch(/单元格/)
})

it('all older table commands explicitly refuse a pending wrap edit',()=>{
 const f=setup();f.select();f.commands.run('table-cell-wrap');toggle();submit()
 for(const action of ['table-insert-row-before','table-repeat-header-rows','table-split-cells','table-column-width','table-row-height','table-autofit-contents','table-text-direction-rotate-90','table-align-top-left','table-alignment','table-row-breaks','table-cell-margins']){
  expect(f.commands.reason(action),action).toMatch(/自动换行/)
 }
})

it('unchanged submission still refuses stale document or source identity',()=>{
 for(const kind of ['document','source']){
  const f=setup();f.select();f.commands.run('table-cell-wrap')
  if(kind==='source')f.anchor.expectedObjectSha256='changed'
  else f.editor.view.dispatch(f.editor.state.tr.insertText('changed',1))
  submit()
  expect(dialog().querySelector('[role="alert"]')!.textContent,kind).toMatch(/文档、选区或来源已改变/)
  expect(f.editor.state.doc.child(1).attrs.nativeTableCellWrap).toBeNull()
  dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
 }
})
