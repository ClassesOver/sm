import {expect,it} from 'vitest'
import {Schema} from '@tiptap/pm/model'
import {parseDocx,saveDocx,readSections} from '@genoffice/docx-engine'
import {buildDocx} from '../../../reporting/doc_engine/packages/docx-engine/tests/helpers/build-docx'
import {tableAlignmentAvailability,editTableAlignment} from '../../../reporting/doc_engine/bridge/docx-table-alignment'
import {blocksToPmDoc,pmDocOptions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/convert'
import {withDocxTableAlignmentDisplayIndents} from './docx-table-alignment-baseline'
import {projectDocxTableAlignment} from './docx-table-alignment'
import {docxOperations,replayDocxOperations,type DocxPmNode} from './docx-operations'
function schemaFor(json:DocxPmNode){
 const attrs:Record<string,any>={},marks:Record<string,any>={};const walk=(n:DocxPmNode)=>{attrs[n.type]??={};for(const k of Object.keys(n.attrs??{}))attrs[n.type][k]={default:null};for(const m of n.marks??[]){marks[m.type]??={attrs:{}};for(const k of Object.keys(m.attrs??{}))marks[m.type].attrs[k]={default:null}};n.content?.forEach(walk)};walk(json)
 const cell={content:'docParagraph+',tableRole:'cell',attrs:attrs.docTableCell??attrs.docTableHeader};return new Schema({nodes:{doc:{content:'docTable+'},text:{group:'inline'},docParagraph:{content:'inline*',attrs:attrs.docParagraph},docTable:{content:'docTableRow+',tableRole:'table',attrs:{...attrs.docTable,nativeTableAlignment:{default:null}}},docTableRow:{content:'(docTableCell|docTableHeader)*',tableRole:'row',attrs:attrs.docTableRow},docTableCell:cell,docTableHeader:{...cell,tableRole:'header_cell'}},marks})
}
it('projects real imported legacy display indent through repeated changes and collector/replay while preserving XML indent',async()=>{
 for(const mode of ['legacy14','inherited','modern15','rtl','spaced','floating']){
  const bytes=await buildDocx({bodyXml:`<w:tbl><w:tblPr><w:tblStyle w:val="Indent"/>${mode==='rtl'?'<w:bidiVisual/>':''}${mode==='floating'?'<w:tblpPr w:horzAnchor="margin" w:vertAnchor="margin" w:tblpX="0"/>':''}<w:tblW w:w="2000" w:type="dxa"/><w:jc w:val="center"/>${mode==='spaced'?'<w:tblCellSpacing w:w="15" w:type="dxa"/>':''}<w:tblInd w:w="-109" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid><w:gridCol w:w="2000"/></w:tblGrid><w:tr><w:tc><w:tcPr><w:tcW w:w="2000" w:type="dxa"/>${mode==='inherited'?'':'<w:tcMar><w:left w:w="33" w:type="dxa"/></w:tcMar>'}</w:tcPr><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc></w:tr></w:tbl>`,extraStylesXml:'<w:style w:type="table" w:styleId="Indent"><w:tblPr><w:tblCellMar><w:left w:w="71" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>'}),parsed=await parseDocx(bytes)
  parsed.compatibilityMode=mode==='modern15'?15:14
  const sections=readSections(parsed),options=pmDocOptions(parsed),baseline=blocksToPmDoc(parsed.blocks,sections,options) as DocxPmNode,schema=schemaFor(baseline),source=schema.nodeFromJSON(baseline).toJSON() as DocxPmNode,block=parsed.blocks.find(b=>b.type==='table')!
  const anchors=withDocxTableAlignmentDisplayIndents([{docxIndex:block.docxIndex!,blockId:'t',expectedObjectSha256:'sha',editable:false,...tableAlignmentAvailability(block)}],parsed.blocks,sections,options)
  if(mode==='legacy14')expect(anchors[0].tableAlignmentDisplayIndents).toEqual({left:-142,center:-109,right:-109})
  if(mode==='inherited')expect(block.table!.cellMarTwips?.left).toBe(71)
  const forged=structuredClone(source.content![0]);forged.attrs!.indentTwips=999
  expect(()=>projectDocxTableAlignment(forged,anchors[0],'left',schema)).toThrow(/显示缩进/)
  expect(()=>projectDocxTableAlignment(source.content![0],{...anchors[0],tableAlignmentDisplayIndents:{left:NaN,center:-109,right:-109}},'left',schema)).toThrow(/显示缩进/)
  let current=source.content![0]
  for(const alignment of ['left','right','left','center'] as const){
   current=projectDocxTableAlignment(current,anchors[0],alignment,schema)
   const changed=editTableAlignment(block,alignment),reopened=await parseDocx(await saveDocx(parsed,[{kind:'xml',docxIndex:block.docxIndex!,xml:changed.xml}]))
   reopened.compatibilityMode=parsed.compatibilityMode
   const expected=(blocksToPmDoc(reopened.blocks,readSections(reopened),pmDocOptions(reopened)) as DocxPmNode).content![0]
   expect(current.attrs!.indentTwips,`${mode} ${alignment}`).toBe(expected.attrs!.indentTwips)
   expect(changed.xml).toContain('<w:tblInd w:w="-109" w:type="dxa"/>')
   const edited={...source,content:[current]},ops=docxOperations(source,edited,anchors,undefined,schema)
   expect(ops).toEqual([{kind:'setTableAlignment',blockId:'t',expectedObjectSha256:'sha',alignment}])
   expect(replayDocxOperations(source,ops,anchors,undefined,schema)).toEqual(edited)
  }
 }
})
