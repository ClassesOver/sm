import {createHash} from 'node:crypto'
import type {Block,ParsedDoc} from '@genoffice/docx-engine'
import {generateTableModelXml,splitXmlChildren} from '../packages/docx-engine/src/generate'
import {XMLValidator} from 'fast-xml-parser'
import {DEFAULT_TABLE_LOOK,normalizeTableStylePatch,tablePresetCell,type TableStylePatch,type TableStyleOption} from '../../../report_editor/frontend/src/docx-table-style-core'
type Context=Pick<ParsedDoc,'styles'|'protection'>
function fail(reason='unsupported'):never{throw Error(`docx_table_style_${reason}`)}
function open(xml:string){return xml.match(/^<[\w:.-]+\b(?:[^>"']|"[^"]*"|'[^']*')*>/)?.[0]??fail()}
function parts(xml:string){const head=open(xml);if(head.endsWith('/>'))return[];const inner=xml.slice(head.length,xml.lastIndexOf('</')),children=splitXmlChildren(inner);if(inner.replace(/<!--[\s\S]*?-->/g,'').replace(/\s/g,'')!==children.map(c=>c.xml).join('').replace(/<!--[\s\S]*?-->/g,'').replace(/\s/g,''))fail();return children}
function one(xml:string,name:string){const matches=parts(xml).filter(c=>c.name===name);if(matches.length>1)fail('duplicate_property');return matches[0]?.xml}
const order=['w:tblStyle','w:tblpPr','w:tblOverlap','w:bidiVisual','w:tblStyleRowBandSize','w:tblStyleColBandSize','w:tblW','w:jc','w:tblCellSpacing','w:tblInd','w:tblBorders','w:shd','w:tblLayout','w:tblCellMar','w:tblLook','w:tblCaption','w:tblDescription','w:tblPrChange','w:cnfStyle','w:tcW','w:gridSpan','w:hMerge','w:vMerge','w:tcBorders','w:noWrap','w:tcMar','w:textDirection','w:tcFitText','w:vAlign','w:hideMark']
/** Replace only the named direct child; all other source bytes remain untouched. */
function setChild(xml:string,name:string,value:string|null):string {
 const old=one(xml,name),head=open(xml)
 if(old){const at=xml.indexOf(old,head.length);return xml.slice(0,at)+(value??'')+xml.slice(at+old.length)}
 if(!value)return xml
 if(head.endsWith('/>'))return head.slice(0,-2)+'>'+value+`</${head.match(/^<([^\s/>]+)/)![1]}>`
 const sequence=head.startsWith('<w:tcPr')?['w:cnfStyle','w:tcW','w:gridSpan','w:hMerge','w:vMerge','w:tcBorders','w:shd','w:noWrap','w:tcMar','w:textDirection','w:tcFitText','w:vAlign','w:hideMark']:order
 const next=parts(xml).find(c=>sequence.indexOf(c.name)>sequence.indexOf(name)),at=['w:tblPr','w:tcPr'].includes(name)?head.length:next?xml.indexOf(next.xml,head.length):xml.lastIndexOf('</')
 return xml.slice(0,at)+value+xml.slice(at)
}
function options(context:Context):TableStyleOption[]{return[...context.styles.values()].filter(s=>s.type==='table'&&s.styleId!=='TableNormal').map(s=>({styleId:s.styleId,name:s.name}))}
function inspect(block:Block,context?:Context){
 const xml=block.originalXml
 if(context?.protection?.enforced)fail('protected')
 if(block.type!=='table'||!block.table||!xml||xml.length>4*1024*1024||XMLValidator.validate(xml)!==true||!/^<w:tbl(?:\s|>)/.test(xml)||!xml.endsWith('</w:tbl>')||/<!DOCTYPE|<!ENTITY|\sxmlns(?::[\w.-]+)?\s*=|<w:(?:ins|del|moveFrom|moveTo|sdt|tblPrChange|tblGridChange|trPrChange|tcPrChange|tblPrExChange|cellMerge|cellIns|cellDel|vMerge|hMerge|gridSpan|gridBefore|gridAfter)\b/.test(xml)||(xml.match(/<w:tbl\b/g)??[]).length!==1)fail()
 const props=one(xml,'w:tblPr')
 if(props){one(props,'w:tblStyle');one(props,'w:tblLook')}
 const rows=parts(xml).filter(c=>c.name==='w:tr').map(row=>parts(row.xml).filter(c=>c.name==='w:tc').map(cell=>{const pr=one(cell.xml,'w:tcPr');if(pr){one(pr,'w:shd');one(pr,'w:tcBorders')}return cell.xml}))
 if(!rows.length||rows.length!==block.table.rows.length||rows.some((r,i)=>!r.length||r.length!==block.table!.rows[i].length))fail('source_mismatch')
 return{xml,rows,source:{styleId:block.table.tblStyleId||null,look:{...(block.table.tableLook??DEFAULT_TABLE_LOOK)}}}
}
export function tableStyleAvailability(block:Block,context:Context){try{return{tableStyleEditable:true,tableStyleReadOnlyReason:null,tableStyleSource:inspect(block,context).source,tableStyleOptions:options(context)}}catch(error){return{tableStyleEditable:false,tableStyleReadOnlyReason:error instanceof Error?error.message:'docx_table_style_unsupported',tableStyleOptions:options(context)}}}
export function editTableStyle(block:Block,input:unknown,context:Context){
 const patch=normalizeTableStylePatch(input),initial=inspect(block,context),model=structuredClone(block.table!)
 if(patch.style){if(patch.style.kind==='document'){const id=patch.style.styleId;if(!options(context).some(s=>s.styleId===id))fail('unknown_document_style');model.tblStyleId=id}else model.tblStyleId=''}
 if(patch.look)model.tableLook=patch.look
 if(patch.style?.kind==='preset'||patch.preset){const id=patch.style?.kind==='preset'?patch.style.id:patch.preset!;model.rows=model.rows.map((row,r)=>row.map(cell=>{const v=tablePresetCell(id,r);return{...cell,fill:v.fill??undefined,borders:v.borders}}))}
 // The source writer owns escaping, TableLook bit flags and preset cell serialization.
 const generated=generateTableModelXml(model,initial.xml),generatedPr=one(generated,'w:tblPr')!,sourcePr=one(initial.xml,'w:tblPr')??'<w:tblPr/>'
 let props=sourcePr
 if(patch.style)props=setChild(props,'w:tblStyle',one(generatedPr,'w:tblStyle')??null)
 if(patch.look)props=setChild(props,'w:tblLook',one(generatedPr,'w:tblLook')??null)
 let xml=!one(initial.xml,'w:tblPr')&&props===sourcePr?initial.xml:setChild(initial.xml,'w:tblPr',props)
 if(patch.style?.kind==='preset'||patch.preset){
  const generatedRows=parts(generated).filter(c=>c.name==='w:tr')
  let rowIndex=0
  for(const row of parts(xml).filter(c=>c.name==='w:tr')){
   let nextRow=row.xml;const cells=parts(row.xml).filter(c=>c.name==='w:tc'),generatedCells=parts(generatedRows[rowIndex++].xml).filter(c=>c.name==='w:tc')
   for(let c=0;c<cells.length;c++){
    const cell=cells[c].xml,generatedProps=one(generatedCells[c].xml,'w:tcPr')!;let cellPr=one(cell,'w:tcPr')??'<w:tcPr/>'
    for(const name of ['w:tcBorders','w:shd'])cellPr=setChild(cellPr,name,one(generatedProps,name)??null)
    nextRow=nextRow.replace(cell,setChild(cell,'w:tcPr',cellPr))
   }
   xml=xml.replace(row.xml,nextRow)
  }
 }
 return{xml,patch,source:initial.source}
}
export function validateTableStyleOperation(block:Block,input:unknown,context:Context){
 if(!input||typeof input!=='object'||Array.isArray(input))fail('invalid')
 const op=input as Record<string,unknown>
 if(Object.keys(op).some(k=>!['kind','blockId','expectedObjectSha256','style','look','preset'].includes(k))||op.kind!=='setTableStyle'||typeof op.blockId!=='string'||!op.blockId.length||op.expectedObjectSha256!==createHash('sha256').update(block.originalXml??'').digest('hex'))fail('anchor_invalid')
 return editTableStyle(block,{...(Object.hasOwn(op,'style')?{style:op.style}:{}),...(Object.hasOwn(op,'look')?{look:op.look}:{}),...(Object.hasOwn(op,'preset')?{preset:op.preset}:{})},context)
}
export function verifyTableStyleResult(block:Block,result:ReturnType<typeof editTableStyle>){
 if(block.originalXml!==result.xml)fail('roundtrip_mismatch')
 const patch=result.patch
 if(patch.style&&(block.table?.tblStyleId??'')!==(patch.style.kind==='document'?patch.style.styleId:''))fail('roundtrip_style')
 if(patch.look&&Object.keys(DEFAULT_TABLE_LOOK).some(k=>block.table?.tableLook?.[k as keyof typeof DEFAULT_TABLE_LOOK]!==patch.look![k as keyof typeof DEFAULT_TABLE_LOOK]))fail('roundtrip_look')
 if(patch.style?.kind==='preset'||patch.preset){const id=patch.style?.kind==='preset'?patch.style.id:patch.preset!;for(const [r,row] of block.table!.rows.entries())for(const cell of row){const expected=tablePresetCell(id,r);if((expected.fill===null?Boolean(cell.rawTcPr&&one(cell.rawTcPr,'w:shd')):(cell.fill??null)!==expected.fill)||['top','left','bottom','right'].some(side=>{const b=cell.borders?.[side as 'top'];return b?.style!=='single'||b.szEighths!==4||b.color!==expected.borders.top.color}))fail('roundtrip_preset')}}
}
