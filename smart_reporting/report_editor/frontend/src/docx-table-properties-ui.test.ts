import { afterEach, expect, it } from 'vitest'
import { act } from 'react'
import { Editor, Extension, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { CellSelection, TableMap } from '@tiptap/pm/tables'
import { NodeSelection } from '@tiptap/pm/state'
import { NativeTableStructure, createDocxTableCommands } from './docx-tables'
import { type DocxPmNode } from './docx-operations'
import { tablePropertiesPatchOf } from './docx-table-properties'
const attrs=(v:Record<string,unknown>)=>Object.fromEntries(Object.entries(v).map(([key,value])=>[key,{default:value}]))
const Doc=Node.create({name:'doc',topNode:true,content:'block+'}),Text=Node.create({name:'text',group:'inline'})
const Paragraph=Node.create({name:'docParagraph',group:'block',content:'text*',addAttributes:()=>attrs({docxIndex:null}),renderHTML:()=>['p',0]})
const Table=Node.create({name:'docTable',group:'block',content:'docTableRow+',addAttributes:()=>attrs({docxIndex:null,cellMar:null,cellMarEdited:false,rawTblPr:'source',tblCaption:null,tblDescription:null,tblAltEdited:false,tblAlign:null,tblAutoFit:'fixed',tblAutoFitEdited:false,tblFloat:null,tblFloatSource:null,tblFloatSuppressed:false,tblFloatXTwips:null,tblFloatYTwips:null,tblFloatHorzAnchor:null,tblFloatVertAnchor:null,tblFloatWidthPx:null,tblFloatDistance:null,tblFloatEdited:false,widthPx:400,widthPct:null,colWidthsPct:[50,50]}),renderHTML:()=>['table',['tbody',0]]})
const Row=Node.create({name:'docTableRow',content:'docTableCell+',addAttributes:()=>attrs({heightTwips:null,heightRule:null,cantSplit:false,cantSplitEdited:false,repeatHeader:false,repeatHeaderEdited:false}),renderHTML:()=>['tr',0]})
const Cell=Node.create({name:'docTableCell',content:'docParagraph+',addAttributes:()=>attrs({colspan:1,rowspan:1,colwidth:null,cellMar:null,noWrap:null,tcPrEdited:false,rawTcPr:'source-cell',vAlign:null}),renderHTML:()=>['td',0]})
const Roles=Extension.create({name:'roles',extendNodeSchema:e=>({tableRole:({docTable:'table',docTableRow:'row',docTableCell:'cell'} as Record<string,string>)[e.name]})})
const editors:Editor[]=[];afterEach(()=>{editors.splice(0).forEach(e=>e.destroy());document.body.replaceChildren()})
function setup(){
 const content:DocxPmNode={type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'body'}]},{type:'docTable',attrs:{docxIndex:1,cellMar:{top:0,right:109,bottom:7,left:108}},content:[0,1].map(r=>({type:'docTableRow',content:[0,1].map(c=>({type:'docTableCell',attrs:{cellMar:c?null:{left:r?71:33,top:0}},content:[{type:'docParagraph',content:[{type:'text',text:`${r}:${c}`}]}]}))}))}]}
 const editor=new Editor({extensions:[Doc,Paragraph,Text,Table,Row,Cell,Roles,NativeTableStructure,UndoRedo],content,editorProps:{handleScrollToSelection:()=>true}});editors.push(editor)
 const baseline=editor.getJSON() as DocxPmNode,anchor:any={docxIndex:1,blockId:'table',expectedObjectSha256:'sha',editable:false,tableCellWrapEditable:true,tableCellWrapSource:{cells:[0,1,2,3].map(n=>({top:Math.floor(n/2),left:n%2,bottom:Math.floor(n/2)+1,right:n%2+1,rawPresent:false,hasPhysicalNoWrap:false,raw:null,noWrap:false,resetNoWrap:false}))}}

 anchor.tablePropertiesEditable=true;anchor.columnWidthMaxTwips=8640;anchor.rowHeightMaxTwips=12960;
 anchor.tableAltTextEditable=true;anchor.tableAltTextSource={title:'',description:'',rawTitle:null,rawDescription:null}
 const errors:string[]=[],commands=createDocxTableCommands(editor,baseline,[anchor],e=>errors.push(String(e))),start=editor.state.doc.child(0).nodeSize+1
 const select=(n=0)=>editor.commands.setTextSelection(start+2+TableMap.get(editor.state.doc.child(1)).map[n]),margins=()=>editor.state.doc.child(1).attrs.cellMar
 const cell=(n=0)=>editor.state.doc.nodeAt(start+TableMap.get(editor.state.doc.child(1)).map[n])!
 const rect=()=>{const map=TableMap.get(editor.state.doc.child(1));editor.view.dispatch(editor.state.tr.setSelection(CellSelection.create(editor.state.doc,start+map.map[0],start+map.map[3])))}
 const open=()=>commands.run('table-properties')
 return{editor,anchor,baseline,commands,errors,start,select,margins,cell,rect,open}
}

it('完整源五tabs打开、取消无草稿；一次确定收集统一属性操作并undo/redo',async()=>{
 const f=setup();f.select();await act(async()=>f.open());expect(document.querySelectorAll('[role=tab]')).toHaveLength(5)
 expect([...document.querySelectorAll('[role=tab]')].map(n=>n.textContent)).toEqual(['Table','行','列','单元格','可选文字'])
 const cancel=[...document.querySelectorAll<HTMLButtonElement>('.modal-actions button')].find(n=>n.textContent==='取消')!;await act(async()=>cancel.click());expect(f.editor.getJSON()).toEqual(f.baseline)
 await act(async()=>f.open());await act(async()=>document.querySelectorAll<HTMLButtonElement>('[role=tab]')[4].click())
 const input=document.querySelector<HTMLInputElement>('.table-alt-text input')!,textarea=document.querySelector<HTMLTextAreaElement>('.table-alt-text textarea')!
 const change=(el:HTMLInputElement|HTMLTextAreaElement,value:string)=>{Object.getOwnPropertyDescriptor(el instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value')!.set!.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}))}
 await act(async()=>{change(input,'标题');change(textarea,'说明')})
 await act(async()=>[...document.querySelectorAll<HTMLButtonElement>('.modal-actions button')].find(n=>n.textContent==='确定')!.click())
 expect(f.errors).toEqual([]);expect(f.editor.state.doc.child(1).attrs.nativeTableProperties).toEqual({alt:{title:'标题',description:'说明'}})
 f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(f.baseline);f.editor.commands.redo();expect(f.editor.state.doc.child(1).attrs.tblCaption).toBe('标题')
})

it('根据内容自动调整只收集模式，不把清除的显示宽度当作零列宽',async()=>{
 const f=setup();f.select();await act(async()=>f.open())
 await act(async()=>document.querySelectorAll<HTMLInputElement>('input[name=table-autofit]')[0].click())
 await act(async()=>[...document.querySelectorAll<HTMLButtonElement>('.modal-actions button')].find(n=>n.textContent==='确定')!.click())
 expect(f.errors).toEqual([])
 expect(f.editor.state.doc.child(1).attrs.nativeTableProperties).toEqual({table:{autoFit:'contents'}})
 expect(f.editor.state.doc.child(1).attrs.widthPx).toBe(400)
 expect(f.editor.state.doc.child(1).attrs.rawTblPr).toBe('source')
 const source=f.baseline.content![1],resized=structuredClone(source)
 resized.attrs={...resized.attrs,tblAutoFit:'contents',widthPx:200,colWidthsPct:[50,50]}
 expect(tablePropertiesPatchOf(source,resized,f.editor.schema)).toEqual({table:{autoFit:'contents'},widthsTwips:[1500,1500]})
 f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(f.baseline)
})
