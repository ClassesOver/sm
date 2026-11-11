import { afterEach, expect, it } from 'vitest'
import { Editor, Node, Extension } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { CellSelection, TableMap } from '@tiptap/pm/tables'
import { TextSelection, NodeSelection } from '@tiptap/pm/state'
import { NativeCellBorders, applyDocxCellBorders, normalizeDocxCellBorders, replayDocxCellBorders, docxCellBordersUnavailable } from './docx-cell-borders'
import { docxCellBordersCapability, patchDocxTableCellBorders } from '../../../reporting/doc_engine/bridge/docx-cell-borders'
import { safeDocxCellBorderSteps, DOCX_CELL_BORDER_MODES } from '../../../reporting/doc_engine/bridge/docx-cell-borders-spec'
import type { DocxPmNode } from './docx-operations'
const pen={style:'single',szEighths:12,color:'FF0000'}
const ids=[[{cellId:'00'},{cellId:'01'}],[{cellId:'10'},{cellId:'11'}]]
const rich='<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Keep</w:t></w:r><w:hyperlink r:id="rId5"><w:r><w:t>Link</w:t></w:r></w:hyperlink></w:p>'
const oldSide='<w:tl2br w:val="double" w:themeColor="accent1" w:sz="8"/>'
const cell=(index:string)=>`<w:tc><w:tcPr><w:tcW w:w="2000"/><w:tcBorders>\n${oldSide}<!--keep--></w:tcBorders><w:shd w:fill="FFFF00"/></w:tcPr>${rich.replace('Keep','Keep'+index)}</w:tc>`
const table=()=>`<w:tbl><w:tblPr><w:tblStyle w:val="Style1"/><w:tblBorders><w:insideH w:val="single"/><w:insideV w:val="single"/><w:bottom w:val="double" w:themeColor="accent2"/></w:tblBorders></w:tblPr><w:tr>${cell('00')}${cell('01')}</w:tr><w:tr>${cell('10')}${cell('11')}</w:tr></w:tbl>`
it.each(DOCX_CELL_BORDER_MODES)('patches %s without rewriting rich runs, shade, style or unhit theme borders',mode=>{
 const result=patchDocxTableCellBorders(table(),[{range:null,mode,pen}],ids)
 const counts={bottom:2,top:2,left:2,right:2,none:0,all:16,outer:8,inner:8,insideH:4,insideV:4,tl2br:4,tr2bl:4}
 expect(result.match(/w:color="FF0000"/g)?.length??0).toBe(counts[mode])
 expect(result.match(/<w:hyperlink /g)).toHaveLength(4)
 expect(result.match(/<w:shd w:fill="FFFF00"\/>/g)).toHaveLength(4)
 expect(result).toContain('<w:tblStyle w:val="Style1"/>')
 if(!['none','tl2br'].includes(mode))expect(result.match(/w:themeColor="accent1"/g)).toHaveLength(4)
 expect(result).toContain('<w:bottom w:val="double" w:themeColor="accent2"/>')
})
it('No Border writes six explicit none sides only on target cells and clears all table inside borders',()=>{
 const result=patchDocxTableCellBorders(table(),[{range:{fromCellId:'00',toCellId:'01'},mode:'none',pen}],ids)
 expect(result.match(/w:val="none"/g)).toHaveLength(12)
 expect(result).not.toContain('<w:insideH');expect(result).not.toContain('<w:insideV')
 expect(result).toContain(cell('10'));expect(result).toContain(cell('11'))
})
it('keeps unmatched raw side/comment/whitespace and has an independent rich-body capability',()=>{
 expect(docxCellBordersCapability(table())).toEqual({bordersEditable:true})
 expect(patchDocxTableCellBorders(table(),[{range:null,mode:'top',pen}],ids)).toContain(`${oldSide}<!--keep-->`)
 for(const tag of ['<w:gridSpan/>','<w:tcPrChange/>','<w:tbl/>'])expect(docxCellBordersCapability(table().replace('<w:p>',tag+'<w:p>')).bordersEditable).toBe(false)
})
it.each([
 [{range:null,mode:'all',pen:{...pen,style:'art'}}],
 [{range:null,mode:'all',pen:{...pen,szEighths:6}}],
 [{range:null,mode:'all',pen:{...pen,color:'#FF0000'}}],
 [{range:null,mode:'all',pen,xml:'<w:tbl/>'}],
 [{range:{fromCellId:'foreign',toCellId:'11'},mode:'none',pen}],
])('rejects untrusted protocol %j',steps=>expect(()=>patchDocxTableCellBorders(table(),steps,ids)).toThrow(/cell_borders/))
const defaults=(data:Record<string,unknown>)=>Object.fromEntries(Object.entries(data).map(([key,value])=>[key,{default:value}]))
const Doc=Node.create({name:'doc',topNode:true,content:'block+'}),P=Node.create({name:'docParagraph',group:'block',content:'text*',renderHTML:()=>['p',0]}),Text=Node.create({name:'text',group:'inline'})
const Table=Node.create({name:'docTable',group:'block',content:'docTableRow+',addAttributes:()=>defaults({docxIndex:0,borders:{insideH:{style:'single'}}}),renderHTML:()=>['table',['tbody',0]]})
const Row=Node.create({name:'docTableRow',content:'docTableCell+',renderHTML:()=>['tr',0]})
const Cell=Node.create({name:'docTableCell',content:'docParagraph+',addAttributes:()=>defaults({colspan:1,rowspan:1,colwidth:null,borders:null}),renderHTML:()=>['td',0]})
const Roles=Extension.create({name:'roles',extendNodeSchema:extension=>({tableRole:({docTable:'table',docTableRow:'row',docTableCell:'cell'} as Record<string,string>)[extension.name]})})
const editors:Editor[]=[]
afterEach(()=>{editors.splice(0).forEach(editor=>editor.destroy());document.body.replaceChildren()})
function setup(){
 const editor=new Editor({extensions:[Doc,P,Text,Table,Row,Cell,Roles,NativeCellBorders,UndoRedo],editorProps:{handleScrollToSelection:()=>true},content:{type:'doc',content:[{type:'docTable',attrs:{docxIndex:0},content:ids.map(row=>({type:'docTableRow',content:row.map(({cellId})=>({type:'docTableCell',content:[{type:'docParagraph',content:[{type:'text',text:cellId}]}]}))}))}]}})
 editors.push(editor)
 const anchors=[{docxIndex:0,blockId:'table',expectedObjectSha256:'sha',bordersEditable:true,cells:ids}]
 const baseline=editor.getJSON() as DocxPmNode,positions=TableMap.get(editor.state.doc.child(0)).map.map(pos=>pos+1)
 const select=(from:number,to?:number)=>editor.view.dispatch(editor.state.tr.setSelection(to===undefined?TextSelection.create(editor.state.doc,positions[from]!+2):CellSelection.create(editor.state.doc,positions[from]!,positions[to]!)))
 return {editor,anchors,baseline,positions,select}
}
it('bare caret formats whole table; selection limits cells; ordered steps restore draft with real undo',()=>{
 const f=setup();f.select(0)
 expect(applyDocxCellBorders(f.editor,'outer',pen,f.anchors)).toBe(true)
 let normalized=normalizeDocxCellBorders(f.baseline,f.editor.getJSON() as DocxPmNode,f.anchors)
 expect(normalized.current).toEqual(f.baseline);expect(normalized.operations[0]!.steps).toEqual([{range:null,mode:'outer',pen}])
 f.select(0,1);expect(applyDocxCellBorders(f.editor,'none',pen,f.anchors)).toBe(true)
 normalized=normalizeDocxCellBorders(f.baseline,f.editor.getJSON() as DocxPmNode,f.anchors)
 expect(normalized.operations[0]!.steps).toHaveLength(2)
 expect(replayDocxCellBorders(f.baseline,normalized.operations,f.anchors)).toEqual(f.editor.getJSON())
 f.editor.commands.undo();expect(normalizeDocxCellBorders(f.baseline,f.editor.getJSON() as DocxPmNode,f.anchors).operations[0]!.steps).toHaveLength(1)
 f.editor.commands.redo();expect(normalizeDocxCellBorders(f.baseline,f.editor.getJSON() as DocxPmNode,f.anchors).operations[0]!.steps).toHaveLength(2)
})
it('rejects forged steps, body edits, readonly sources; NodeSelection covers whole table',()=>{
 const f=setup();f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,0)))
 expect(docxCellBordersUnavailable(f.editor,f.anchors)).toBe(null)
 applyDocxCellBorders(f.editor,'all',pen,f.anchors)
 const current=f.editor.getJSON() as DocxPmNode
 current.content![0]!.content![1]!.content![0]!.content![0]!.content![0]!.text='tamper'
 expect(()=>normalizeDocxCellBorders(f.baseline,current,f.anchors)).toThrow()
 expect(()=>safeDocxCellBorderSteps([])).toThrow()
 f.anchors[0]!.bordersEditable=false
 expect(docxCellBordersUnavailable(f.editor,f.anchors)).toBeTruthy()
})
import { createDocxCellBorderUiState, createDocxCellBordersControls } from './docx-cell-borders-controls'
it('keeps pen state without mutating document until a source gallery command is applied',()=>{
 const f=setup();f.select(0);const state=createDocxCellBorderUiState(),controls=createDocxCellBordersControls(f.editor,f.anchors,state)
 document.body.append(controls.element)
 const style=controls.element.querySelector<HTMLSelectElement>('[data-action="table-border-style"]')!,width=controls.element.querySelector<HTMLSelectElement>('[data-action="table-border-width"]')!,color=controls.element.querySelector<HTMLInputElement>('[data-action="table-border-color"]')!
 expect(style.options).toHaveLength(8);expect(width.options).toHaveLength(5)
 style.value='dashed';style.dispatchEvent(new Event('change'));width.value='18';width.dispatchEvent(new Event('change'));color.value='#00b050';color.dispatchEvent(new Event('input'))
 expect(f.editor.getJSON()).toEqual(f.baseline)
 controls.element.querySelector<HTMLButtonElement>('[data-action="table-border-outer"]')!.click()
 expect(normalizeDocxCellBorders(f.baseline,f.editor.getJSON() as DocxPmNode,f.anchors).operations[0]!.steps[0]!.pen).toEqual({style:'dashed',szEighths:18,color:'00B050'})
 expect(state.lastMode).toBe('outer')
})
import { docxOperations, replayDocxOperations, type DocxAnchor } from './docx-operations'
it('integrates strict ordinary diff and draft replay without enabling rich-cell text rewrite',()=>{
 const f=setup(),anchors:DocxAnchor[]=f.anchors.map(anchor=>({...anchor,editable:false,cells:anchor.cells.map(row=>row.map(cell=>({...cell,expectedObjectSha256:'cell-hash',editable:false})))}))
 f.select(1);applyDocxCellBorders(f.editor,'bottom',pen,anchors)
 const operations=docxOperations(f.baseline,f.editor.getJSON() as DocxPmNode,anchors,undefined,f.editor.schema)
 expect(operations).toHaveLength(1);expect(operations[0]!.kind).toBe('setTableCellBorders')
 expect(replayDocxOperations(f.baseline,operations,anchors,undefined,f.editor.schema)).toEqual(f.editor.getJSON())
 expect(()=>replayDocxOperations(f.baseline,[...operations,{kind:'replaceCellText',blockId:'table',cellId:'00',expectedObjectSha256:'cell-hash',text:'mixed'}],anchors,undefined,f.editor.schema)).toThrow(/同表边框/)
})
it('retains more than fifty source border commands under the existing request payload budget',()=>{
 const steps=Array.from({length:51},(_,index)=>({range:null,mode:index%2?'none':'outer',pen}))
 expect(safeDocxCellBorderSteps(steps)).toHaveLength(51)
})
it('does not invent a ten-thousand-cell limit for an already parsed source table',()=>{
 const row='<w:tr>'+Array.from({length:101},()=>'<w:tc><w:p/></w:tc>').join('')+'</w:tr>'
 const xml='<w:tbl>'+row.repeat(100)+'</w:tbl>'
 expect(docxCellBordersCapability(xml)).toEqual({bordersEditable:true})
})
