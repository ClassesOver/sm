/** Native source-only table cell operations; client supplies intent, never XML. */
import {createHash} from 'node:crypto'
import {generateTableModelXml,type Block,type TableCell,type TableModel} from '@genoffice/docx-engine'
import {splitXmlChildren} from '../packages/docx-engine/src/generate.ts'
import {tableLifecycleAvailability} from './docx-table-lifecycle.ts'
import {Schema,applyDocxTableCellChange,assertDocxTableCellChange} from '../../../report_editor/frontend/src/docx-table-cell-operations-core.ts'
export interface TableCellOperationsContext {blockId:string;expectedObjectSha256:string;protectedDocument:boolean;maxWidthTwips:number}
const fail=(code:string):never=>{throw new Error(`docx_table_cells_${code}`)}
const open=(xml:string)=>/^<[\w:.-]+\b(?:[^>"']|"[^"]*"|'[^']*')*>/.exec(xml)?.[0]??fail('source_invalid')
const children=(xml:string)=>open(xml).endsWith('/>')?[]:splitXmlChildren(xml.slice(open(xml).length,xml.lastIndexOf('</')))
const child=(xml:string,name:string)=>children(xml).find(p=>p.name===name)?.xml??''
const width=(xml:string)=>Number(/\bw:w=["'](\d+)["']/.exec(xml)?.[1])
function source(block:Block,protectedDocument:boolean,maxWidthTwips:number){
 const safe=tableLifecycleAvailability(block,protectedDocument)
 if(!safe.tableLifecycleEditable)fail(safe.tableLifecycleReadOnlyReason??'source_unsupported')
 if(!Number.isSafeInteger(maxWidthTwips)||maxWidthTwips<1||maxWidthTwips>31680)fail('width_invalid')
 const xml=block.originalXml!,parts=children(xml),grid=child(xml,'w:tblGrid'),widths=children(grid).map(p=>width(p.xml)),rows=parts.filter(p=>p.name==='w:tr').map(p=>({xml:p.xml,pr:child(p.xml,'w:trPr'),cells:children(p.xml).filter(c=>c.name==='w:tc').map(c=>c.xml)}))
 if(widths.some(w=>!Number.isSafeInteger(w)||w<1)||!widths.length||widths.length>30||rows.length>100||rows.length*widths.length>1000)fail('size_invalid')
 return {xml,grid,widths,rows,pr:child(xml,'w:tblPr')}
}
export function tableCellOperationsAvailability(block:Block,protectedDocument:boolean,maxWidthTwips:number){
 try{const s=source(block,protectedDocument,maxWidthTwips);return {tableCellsEditable:true,tableCellsReadOnlyReason:null,tableCellsWidthsTwips:s.widths,tableCellsMaxWidthTwips:maxWidthTwips}}
 catch(e){return {tableCellsEditable:false,tableCellsReadOnlyReason:e instanceof Error?e.message:'docx_table_cells_unsupported',tableCellsWidthsTwips:[] as number[],tableCellsMaxWidthTwips:maxWidthTwips}}
}
const attributes=(a:Record<string,unknown>)=>Object.fromEntries(Object.entries(a).map(([k,v])=>[k,{default:v}]))
const visual={fill:null,borders:null,vAlign:null,cellMar:null,textDirection:null,noWrap:null,align:null,bold:null,color:null}
const schema=new Schema({nodes:{doc:{content:'(docTable|docParagraph)+'},text:{group:'inline'},docParagraph:{content:'text*',attrs:attributes({docxIndex:null,sourceParagraph:null})},docTable:{content:'docTableRow+',tableRole:'table',attrs:attributes({colWidthsPct:null,widthPx:null,widthPct:null})},docTableRow:{content:'docTableCell*',tableRole:'row',attrs:attributes({sourceRow:null,heightTwips:null,heightRule:null,cantSplit:false,cantSplitEdited:false})},docTableCell:{content:'docParagraph+',tableRole:'cell',attrs:attributes({...visual,colspan:1,rowspan:1,colwidth:null,gridGap:false,sourceCell:null,tcPrEdited:false})}}})
function resizedCell(xml:string,w:number){return xml.replace(/<w:tcW\b[^>]*\/>/,tag=>tag.replace(/(\bw:w=)(["'])\d+\2/,(_,prefix,q)=>`${prefix}${q}${w}${q}`))}
export function editDocxTableCellOperation(block:Block,operation:unknown,context:TableCellOperationsContext):{sourceXml:string;replacementXml:string}{
 if(!operation||typeof operation!=='object'||Array.isArray(operation))fail('operation_invalid')
 const op=operation as Record<string,unknown>,keys=['kind','blockId','expectedObjectSha256','change']
 if(op.kind!=='editTableCells'||Object.keys(op).length!==keys.length||Object.keys(op).some(k=>!keys.includes(k)))fail('operation_invalid')
 if(!context||context.protectedDocument!==false)fail('protected')
 if(!context.blockId||op.blockId!==context.blockId||typeof op.expectedObjectSha256!=='string'||!/^[a-f0-9]{64}$/.test(op.expectedObjectSha256)||op.expectedObjectSha256!==context.expectedObjectSha256)fail('anchor_invalid')
 const s=source(block,context.protectedDocument,context.maxWidthTwips)
 if(createHash('sha256').update(s.xml).digest('hex')!==context.expectedObjectSha256)fail('anchor_invalid')
 assertDocxTableCellChange(op.change)
 const m=block.table!,table=schema.node('docTable',{colWidthsPct:s.widths.map(w=>w*100/s.widths.reduce((a,b)=>a+b,0)),widthPx:m.widthPct?null:s.widths.reduce((a,b)=>a+b,0)/15,widthPct:m.widthPct??null},m.rows.map((row,y)=>schema.node('docTableRow',{sourceRow:y,heightTwips:m.rowHeightsTwips?.[y]??null,heightRule:m.rowHeightRules?.[y]??null,cantSplit:m.rowCantSplit?.[y]??false},row.map((c,x)=>schema.node('docTableCell',{...Object.fromEntries(Object.keys(visual).map(k=>[k,k==='cellMar'?c.cellMarTwips??null:c[k as keyof TableCell]??null])),sourceCell:`${y}:${x}`,colwidth:[s.widths[x]/15]},schema.node('docParagraph',{sourceParagraph:`${y}:${x}`},schema.text(`CELL_${y}_${x}`)))))))
 const next=applyDocxTableCellChange(table,op.change,context.maxWidthTwips)
 if(!next)return {sourceXml:s.xml,replacementXml:''}
 if(next.type.name==='docParagraph')return {sourceXml:s.xml,replacementXml:'<w:p/>'}
 const widths=Array.from({length:next.firstChild!.childCount},(_,x)=>Math.max(1,Math.round(next.firstChild!.child(x).attrs.colwidth[0]*15)))
 const sourceCell=(key:string)=>{const [y,x]=key.split(':').map(Number);return s.rows[y].cells[x]}
 const model:TableModel={rows:[],colWidthsTwips:widths,colWidthsPct:widths.map(w=>w*100/widths.reduce((a,b)=>a+b,0)),rowHeightsTwips:[],rowHeightRules:[],rowCantSplit:[]}
 next.forEach(row=>{const cells:TableCell[]=[];row.forEach(c=>cells.push({paras:[''],richParas:[{runs:[]}],...Object.fromEntries(Object.keys(visual).filter(k=>c.attrs[k]!=null).map(k=>[k==='cellMar'?'cellMarTwips':k,c.attrs[k]])),gridGap:!!c.attrs.gridGap,tcPrEdited:true}));model.rows.push(cells);model.rowHeightsTwips!.push(row.attrs.heightTwips);model.rowHeightRules!.push(row.attrs.heightRule);model.rowCantSplit!.push(row.attrs.cantSplit)})
 const generated=generateTableModelXml(model),generatedRows=children(generated).filter(p=>p.name==='w:tr')
 const outRows:string[]=[]
 next.forEach((row,_off,y)=>{
  const generatedRow=generatedRows[y].xml,generatedCells=children(generatedRow).filter(p=>p.name==='w:tc');let index=0
  const outCells:string[]=[]
  row.forEach((c,_off,x)=>{
   if(c.attrs.gridGap)return
   let xml=generatedCells[index++].xml
   const origin=c.attrs.sourceCell as string|null
   if(origin){const original=sourceCell(origin);xml=resizedCell(original,widths[x]);if(!c.textContent){const pr=child(original,'w:tcPr'),paragraph=children(original).find(p=>p.name==='w:p')?.xml??'<w:p/>',pPr=child(paragraph,'w:pPr');xml='<w:tc>'+resizedCell('<w:tc>'+pr+'</w:tc>',widths[x]).slice(6,-7)+'<w:p>'+pPr+'</w:p></w:tc>'}}
   outCells.push(xml)
  })
  const origin=row.attrs.sourceRow as number|null,generatedPr=child(generatedRow,'w:trPr'),gaps=children(generatedPr||'<w:trPr/>').filter(p=>['w:gridBefore','w:gridAfter','w:wBefore','w:wAfter'].includes(p.name)).map(p=>p.xml).join('')
  let pr=origin==null?generatedPr:s.rows[origin].pr
  if(gaps)pr=pr?pr.replace('</w:trPr>',()=>gaps+'</w:trPr>'):'<w:trPr>'+gaps+'</w:trPr>'
  outRows.push('<w:tr>'+pr+outCells.join('')+'</w:tr>')
 })
 const changed=JSON.stringify(widths)!==JSON.stringify(s.widths)
 let pr=s.pr
 if(changed)pr=pr.replace(/<w:tblW\b[^>]*\/>/,tag=>/\bw:type=["']dxa["']/.test(tag)?tag.replace(/(\bw:w=)(["'])\d+\2/,(_,prefix,q)=>`${prefix}${q}${widths.reduce((a,b)=>a+b,0)}${q}`):tag)
 return {sourceXml:s.xml,replacementXml:open(s.xml)+pr+(changed?child(generated,'w:tblGrid'):s.grid)+outRows.join('')+'</w:tbl>'}
}
