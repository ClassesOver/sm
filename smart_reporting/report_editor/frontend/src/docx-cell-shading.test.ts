import { expect, it } from 'vitest'
import { docxCellShadingCapability, patchDocxCellShading } from '../../../reporting/doc_engine/bridge/docx-cell-shading'
import { normalizeDocxCellShading, replayDocxCellShading, safeDocxCellFill } from './docx-cell-shading'
import type { DocxPmNode } from './docx-operations'
const cell='<w:tc><w:tcPr><w:tcW w:w="2000"/><w:shd w:val="pct20" w:themeFill="accent1"/><w:vAlign w:val="center"/></w:tcPr><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Rich</w:t></w:r><w:hyperlink r:id="rId5"><w:r><w:t>Link</w:t></w:r></w:hyperlink></w:p></w:tc>'
const table=(xml=cell)=>`<w:tbl><w:tblPr><w:tblStyle w:val="MyStyle"/></w:tblPr><w:tr>${xml}</w:tr></w:tbl>`
it('changes only direct shading and preserves rich body',()=>{
 expect(docxCellShadingCapability(table(),cell)).toEqual({shadingEditable:true})
 expect(patchDocxCellShading(cell,'00B050')).toBe(cell.replace('<w:shd w:val="pct20" w:themeFill="accent1"/>','<w:shd w:val="clear" w:color="auto" w:fill="00B050"/>'))
 expect(patchDocxCellShading(cell,null)).toBe(cell.replace('<w:shd w:val="pct20" w:themeFill="accent1"/>',''))
})
it('creates tcPr shading in order, preserves paragraph shading',()=>{
 const body='<w:p><w:pPr><w:shd w:fill="FF0000"/></w:pPr></w:p>'
 expect(patchDocxCellShading(`<w:tc>${body}</w:tc>`,'ABCDEF')).toBe(`<w:tc><w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="ABCDEF"/></w:tcPr>${body}</w:tc>`)
 expect(patchDocxCellShading('<w:tc><w:tcPr><w:vAlign w:val="top"/></w:tcPr><w:p/></w:tc>','ABCDEF')).toContain('<w:shd w:val="clear" w:color="auto" w:fill="ABCDEF"/><w:vAlign')
 expect(patchDocxCellShading(`<w:tc>${body}</w:tc>`,null)).toBe(`<w:tc>${body}</w:tc>`)
})
it.each(['<w:gridSpan w:val="2"/>','<w:tbl/>','<w:ins/>','<w:tcPrChange/>','<w:sdt/>'])('reports separate readonly for %s',tag=>expect(docxCellShadingCapability(table(cell.replace('<w:p>',`${tag}<w:p>`)),cell).shadingEditable).toBe(false))
it.each(['#FF0000','red','123',false,{},undefined])('refuses invalid fill %s',fill=>{
 expect(()=>patchDocxCellShading(cell,fill)).toThrow(/cell_shading/);expect(()=>safeDocxCellFill(fill)).toThrow()
})
const anchors=[{docxIndex:0,blockId:'table',expectedObjectSha256:'table-hash',editable:false,cells:[[{cellId:'cell',expectedObjectSha256:'cell-hash',editable:false,shadingEditable:true}]]}]
const source=():DocxPmNode=>({type:'doc',content:[{type:'docTable',attrs:{docxIndex:0},content:[{type:'docTableRow',content:[{type:'docTableCell',attrs:{fill:'FFC000',rawTcPr:'keep'},content:[{type:'docParagraph',content:[{type:'text',text:'rich',marks:[{type:'bold'}]}]}]}]}]}]})
const operation=(fill:string|null)=>({kind:'setCellShading',blockId:'table',cellId:'cell',expectedObjectSha256:'cell-hash',fill})
it('normalizes rich cell shading independently of text eligibility and restores null',()=>{
 const baseline=source(),current=replayDocxCellShading(baseline,[operation(null)],anchors)
 expect(current.content![0]!.content![0]!.content![0]!.attrs!.fill).toBe(null)
 const normalized=normalizeDocxCellShading(baseline,current,anchors)
 expect(normalized.operations).toEqual([operation(null)]);expect(normalized.current).toEqual(normalized.baseline);expect(baseline).toEqual(source())
})
it('rejects forged identities, extra fields, duplicate targets and shading+body edits',()=>{
 for(const operations of [[{...operation(null),cellId:'foreign'}],[{...operation(null),xml:'<w:tc/>'}],[operation(null),operation('ABCDEF')]])expect(()=>replayDocxCellShading(source(),operations,anchors)).toThrow()
 const current=replayDocxCellShading(source(),[operation(null)],anchors)
 current.content![0]!.content![0]!.content![0]!.content![0]!.content![0]!.text='changed'
 expect(()=>normalizeDocxCellShading(source(),current,anchors)).toThrow()
})
it('keeps all tcPr whitespace/comments bytes outside the direct shading',()=>{
 const original='<w:tc><w:tcPr>\n<w:tcW w:w="2000"/> <!-- keep -->\n<w:shd w:fill="FFC000"/>\n<w:vAlign w:val="top"/>\n</w:tcPr><w:p/></w:tc>'
 expect(patchDocxCellShading(original,null)).toBe(original.replace('<w:shd w:fill="FFC000"/>',''))
})
import { afterEach } from 'vitest'
import { Editor, Node, Extension } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { NodeSelection, TextSelection } from '@tiptap/pm/state'
import { TableMap, CellSelection } from '@tiptap/pm/tables'
import { applyDocxCellShading } from './docx-cell-shading'
const Doc=Node.create({name:'doc',topNode:true,content:'block+'})
const P=Node.create({name:'docParagraph',group:'block',content:'text*',renderHTML:()=>['p',0]})
const Text=Node.create({name:'text',group:'inline'})
const Table=Node.create({name:'docTable',group:'block',content:'docTableRow+',addAttributes:()=>({docxIndex:{default:0}}),renderHTML:()=>['table',['tbody',0]]})
const Row=Node.create({name:'docTableRow',content:'docTableCell+',renderHTML:()=>['tr',0]})
const Cell=Node.create({name:'docTableCell',content:'docParagraph+',addAttributes:()=>Object.fromEntries(Object.entries({colspan:1,rowspan:1,colwidth:null,fill:null}).map(([key,value])=>[key,{default:value}])),renderHTML:()=>['td',0]})
const Roles=Extension.create({name:'roles',extendNodeSchema:extension=>({tableRole:({docTable:'table',docTableRow:'row',docTableCell:'cell'} as Record<string,string>)[extension.name]})})
const editors:Editor[]=[]
afterEach(()=>{editors.splice(0).forEach(editor=>editor.destroy());document.body.replaceChildren()})
function setup(){
 const editor=new Editor({extensions:[Doc,P,Text,Table,Row,Cell,Roles,UndoRedo],editorProps:{handleScrollToSelection:()=>true},content:{type:'doc',content:[{type:'docTable',attrs:{docxIndex:0},content:[{type:'docTableRow',content:['FF0000','00B050'].map(fill=>({type:'docTableCell',attrs:{fill},content:[{type:'docParagraph',content:[{type:'text',text:'keep'}]}]}))}]}]}})
 editors.push(editor)
 const anchors=[{docxIndex:0,blockId:'table',cells:[['a','b'].map(cellId=>({cellId,expectedObjectSha256:cellId+'-hash',shadingEditable:true}))]}]
 const positions=TableMap.get(editor.state.doc.child(0)).map.map(pos=>pos+1)
 return {editor,anchors,positions,fills:()=>(editor.getJSON() as DocxPmNode).content![0]!.content![0]!.content!.map(cell=>cell.attrs!.fill)}
}
it('caret changes just its cell, with real undo/redo',()=>{
 const f=setup();f.editor.view.dispatch(f.editor.state.tr.setSelection(TextSelection.create(f.editor.state.doc,f.positions[0]!+2)))
 expect(applyDocxCellShading(f.editor,null,f.anchors)).toBe(true);expect(f.fills()).toEqual([null,'00B050'])
 f.editor.commands.undo();expect(f.fills()).toEqual(['FF0000','00B050']);f.editor.commands.redo();expect(f.fills()).toEqual([null,'00B050'])
})
it('selected table shades all cells; selected anchor already target leaves whole selection unchanged',()=>{
 const f=setup();f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,0)))
 expect(applyDocxCellShading(f.editor,'ABCDEF',f.anchors)).toBe(true);expect(f.fills()).toEqual(['ABCDEF','ABCDEF'])
 f.editor.commands.undo();f.editor.view.dispatch(f.editor.state.tr.setSelection(CellSelection.create(f.editor.state.doc,f.positions[0]!,f.positions[1]!)))
 expect(applyDocxCellShading(f.editor,'00B050',f.anchors)).toBe(false);expect(f.fills()).toEqual(['FF0000','00B050'])
})
it('rejects selection containing readonly cell atomically',()=>{
 const f=setup();f.anchors[0]!.cells[0]![1]!.shadingEditable=false;f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,0)))
 expect(()=>applyDocxCellShading(f.editor,null,f.anchors)).toThrow();expect(f.fills()).toEqual(['FF0000','00B050'])
})
import { docxCellShadingUnavailable } from './docx-cell-shading'
it('derives ribbon capability from every selected cell, without changing source selection',()=>{
 const f=setup();f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,0)))
 expect(docxCellShadingUnavailable(f.editor,f.anchors)).toBe(null)
 const selection=f.editor.state.selection
 const restricted=f.anchors as import('./docx-cell-shading').DocxCellShadingAnchor[]
 restricted[0]!.cells![0]![1]!.shadingEditable=false;restricted[0]!.cells![0]![1]!.shadingReadOnlyReason='此单元格修订尚未接受'
 expect(docxCellShadingUnavailable(f.editor,restricted)).toBe('此单元格修订尚未接受')
 expect(f.editor.state.selection).toBe(selection)
 f.editor.view.dispatch(f.editor.state.tr.setSelection(TextSelection.create(f.editor.state.doc,f.positions[0]!+2)))
 expect(docxCellShadingUnavailable(f.editor,restricted)).toBe(null)
})
