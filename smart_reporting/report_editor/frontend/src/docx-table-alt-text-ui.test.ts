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
const Table=Node.create({name:'docTable',group:'block',content:'docTableRow+',addAttributes:()=>attrs({docxIndex:null,cellMar:null,cellMarEdited:false,rawTblPr:'source',tblCaption:null,tblDescription:null,tblAltEdited:false}),renderHTML:()=>['table',['tbody',0]]})
const Row=Node.create({name:'docTableRow',content:'docTableCell+',renderHTML:()=>['tr',0]})
const Cell=Node.create({name:'docTableCell',content:'docParagraph+',addAttributes:()=>attrs({colspan:1,rowspan:1,colwidth:null,cellMar:null,noWrap:null,tcPrEdited:false,rawTcPr:'source-cell'}),renderHTML:()=>['td',0]})
const Roles=Extension.create({name:'roles',extendNodeSchema:e=>({tableRole:({docTable:'table',docTableRow:'row',docTableCell:'cell'} as Record<string,string>)[e.name]})})
const editors:Editor[]=[];afterEach(()=>{editors.splice(0).forEach(e=>e.destroy());document.body.replaceChildren()})
function setup(){
 const content:DocxPmNode={type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'body'}]},{type:'docTable',attrs:{docxIndex:1,cellMar:{top:0,right:109,bottom:7,left:108}},content:[0,1].map(r=>({type:'docTableRow',content:[0,1].map(c=>({type:'docTableCell',attrs:{cellMar:c?null:{left:r?71:33,top:0}},content:[{type:'docParagraph',content:[{type:'text',text:`${r}:${c}`}]}]}))}))}]}
 const editor=new Editor({extensions:[Doc,Paragraph,Text,Table,Row,Cell,Roles,NativeTableStructure,UndoRedo],content,editorProps:{handleScrollToSelection:()=>true}});editors.push(editor)
 const baseline=editor.getJSON() as DocxPmNode,anchor:any={docxIndex:1,blockId:'table',expectedObjectSha256:'sha',editable:false,tableCellWrapEditable:true,tableCellWrapSource:{cells:[0,1,2,3].map(n=>({top:Math.floor(n/2),left:n%2,bottom:Math.floor(n/2)+1,right:n%2+1,rawPresent:false,hasPhysicalNoWrap:false,raw:null,noWrap:false,resetNoWrap:false}))}}

 anchor.tableAltTextEditable=true;anchor.tableAltTextSource={title:'',description:'',rawTitle:null,rawDescription:null}
 const errors:string[]=[],commands=createDocxTableCommands(editor,baseline,[anchor],e=>errors.push(String(e))),start=editor.state.doc.child(0).nodeSize+1
 const select=(n=0)=>editor.commands.setTextSelection(start+2+TableMap.get(editor.state.doc.child(1)).map[n]),margins=()=>editor.state.doc.child(1).attrs.cellMar
 const cell=(n=0)=>editor.state.doc.nodeAt(start+TableMap.get(editor.state.doc.child(1)).map[n])!
 const rect=()=>{const map=TableMap.get(editor.state.doc.child(1));editor.view.dispatch(editor.state.tr.setSelection(CellSelection.create(editor.state.doc,start+map.map[0],start+map.map[3])))}
 const open=()=>commands.run('table-properties')
 return{editor,anchor,baseline,commands,errors,start,select,margins,cell,rect,open}
}
const dialog=()=>document.querySelector<HTMLElement>('[role="dialog"][aria-label="标题/说明"]')!
const submit=()=>dialog().querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
const fill=(title:string,description:string)=>{dialog().querySelector<HTMLInputElement>('input')!.value=title;dialog().querySelector<HTMLTextAreaElement>('textarea')!.value=description;submit()}
it('properties exposes alt title/description; trim noop clear and final pair undo preserve source',()=>{
 const f=setup();f.select();f.open();document.querySelector<HTMLButtonElement>('[data-action="table-alt-text"]')!.click();fill('  ',' ');expect(f.editor.getJSON()).toEqual(f.baseline);expect(f.editor.can().undo()).toBe(false)
 f.commands.run('table-alt-text');fill(' 标题 & < > " ',' 第一行\n第二行 ');let table=f.editor.state.doc.child(1);expect(table.attrs.nativeTableAltText).toEqual({title:'标题 & < > "',description:'第一行\n第二行'});expect(table.attrs.tblAltEdited).toBe(false);expect(table.attrs.rawTblPr).toBe('source');expect(table.toJSON().content).toEqual(f.baseline.content![1].content)
 f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(f.baseline);f.editor.commands.redo();f.rect();f.commands.run('table-alt-text');fill('标题 & < > "','changed');expect(f.editor.state.doc.child(1).attrs.tblCaption).toBe('标题 & < > "')
 f.commands.run('table-alt-text');fill(' ',' ');table=f.editor.state.doc.child(1);expect(table.attrs.nativeTableAltText).toEqual({title:'',description:''});expect(table.attrs.tblCaption).toBeNull();expect(table.attrs.tblDescription).toBeNull()
})
it('rejects bare table selection readonly nested invalid values and stale unchanged submissions',()=>{
 for(const kind of ['selection','document','anchor']){const f=setup();f.select();f.commands.run('table-alt-text');if(kind==='selection')f.select(3);else if(kind==='document')f.editor.view.dispatch(f.editor.state.tr.insertText('x',1));else f.anchor.expectedObjectSha256='changed';submit();expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/改变|选择/);dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()}
 const f=setup();f.select();f.commands.run('table-alt-text');fill('x'.repeat(256),'');expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/无效|invalid/);dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
 f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,f.start-1)));expect(f.commands.reason('table-alt-text')).toMatch(/单元格/);f.select();expect(f.commands.reason('table-alt-text')).toBeNull();expect(createDocxTableCommands(f.editor,f.baseline,[f.anchor],()=>{},()=>true).reason('table-alt-text')).toMatch(/嵌套/);f.editor.setEditable(false);expect(f.commands.reason('table-alt-text')).toMatch(/不可编辑|保存/)
})
it('pending alt prevents older table modification entry points',()=>{
 const f=setup();f.select();f.commands.run('table-alt-text');fill('title','description')
 for(const action of ['table-insert-row-before','table-repeat-header-rows','table-split-cells','table-column-width','table-row-height','table-autofit-contents','table-text-direction-rotate-90','table-align-top-left','table-alignment','table-row-breaks','table-cell-margins','table-cell-wrap'])expect(f.commands.reason(action),action).toMatch(/标题|替代文字/)
})

it('untouched source whitespace remains raw and merged owner edits only table attrs',()=>{
 const f=setup();const table=f.editor.state.doc.child(1),rows=[table.child(0),table.child(1)],owner=rows[0].child(0)
 const merged=table.type.create({...table.attrs,tblCaption:' title ',tblDescription:' description '},[rows[0].type.create(rows[0].attrs,[owner.type.create({...owner.attrs,rowspan:2},owner.content),rows[0].child(1)]),rows[1].type.create(rows[1].attrs,[rows[1].child(1)])])
 f.editor.view.dispatch(f.editor.state.tr.replaceWith(f.start-1,f.start-1+table.nodeSize,merged));f.baseline.content![1]=f.editor.getJSON().content![1] as DocxPmNode;Object.assign(f.anchor.tableAltTextSource,{title:' title ',description:' description ',rawTitle:'raw-title',rawDescription:'raw-description'})
 f.select(2);f.commands.run('table-alt-text');submit();expect(f.editor.getJSON()).toEqual(f.baseline)
 f.commands.run('table-alt-text');fill('new','desc');expect(f.editor.state.doc.child(1).toJSON().content).toEqual(f.baseline.content![1].content)
})

it('untouched CRLF or CR description retains original source bytes and values',()=>{
 for(const description of [' 第一行\r\n第二行 ',' 第一行\r第二行 ']){
  const f=setup(),table=f.editor.state.doc.child(1)
  f.editor.view.dispatch(f.editor.state.tr.setNodeMarkup(f.start-1,undefined,{...table.attrs,tblCaption:' title ',tblDescription:description}))
  f.baseline.content![1]=f.editor.getJSON().content![1] as DocxPmNode;Object.assign(f.anchor.tableAltTextSource,{title:' title ',description,rawTitle:'raw-title',rawDescription:'raw-CR'})
  f.select();f.commands.run('table-alt-text');expect(dialog().querySelector<HTMLTextAreaElement>('textarea')!.value).toBe(description.replace(/\r\n?/g,'\n'));submit();expect(f.editor.getJSON()).toEqual(f.baseline)
 }
})
