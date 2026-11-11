/** 默认边距只补直属tblCellMar；样式、行例外、所有物理tcMar及内容保持原字节。 */
import type {Block} from '@genoffice/docx-engine'
import {XMLValidator} from 'fast-xml-parser'
import {splitXmlChildren} from '../packages/docx-engine/src/generate.ts'
import {normalizeTableCellMargins,type TableCellMargins,type PartialTableCellMargins,type TableCellMarginsSource} from '../../../report_editor/frontend/src/docx-table-cell-margins-core.ts'
interface Element {name:string;xml:string;start:number}
function fail():never{throw new Error('docx_table_cell_margins_unsupported')}
const openOf=(node:Element)=>node.xml.match(/^<[\w:.-]+\b(?:[^>"']|"[^"]*"|'[^']*')*>/)?.[0]??fail()
function children(node:Element):Element[]{
 const open=openOf(node);if(open.endsWith('/>'))return[]
 const inner=node.xml.slice(open.length,node.xml.lastIndexOf('</')),parts=splitXmlChildren(inner)
 if(inner.replace(/\s/g,'')!==parts.map(p=>p.xml).join('').replace(/\s/g,''))fail()
 let cursor=open.length
 return parts.map(part=>{const at=node.xml.indexOf(part.xml,cursor);cursor=at+part.xml.length;return{...part,start:node.start+at}})
}
function attributes(node:Element){
 const open=openOf(node),result:Record<string,string>={}
 for(const match of open.matchAll(/([^\s=<>]+)\s*=\s*(["'])([\s\S]*?)\2/g)){if(Object.hasOwn(result,match[1]))fail();result[match[1]]=match[3]}
 return result
}
function one(parts:Element[],name:string){const matches=parts.filter(part=>part.name===name);if(matches.length>1)fail();return matches[0]}
function marginsOf(node:Element):PartialTableCellMargins|null{
 if(Object.keys(attributes(node)).length)fail()
 const result:PartialTableCellMargins={}
 const names:Record<string,keyof TableCellMargins>={'w:top':'top','w:right':'right','w:bottom':'bottom','w:left':'left','w:start':'left','w:end':'right'}
 for(const child of children(node)){
  const side=names[child.name],attr=attributes(child)
  if(!side||Object.hasOwn(result,side)||Object.keys(attr).some(name=>!['w:w','w:type'].includes(name))||!/^\d+$/.test(attr['w:w']??'')||attr['w:type']!==undefined&&attr['w:type']!=='dxa'||children(child).length)fail()
  result[side]=Number(attr['w:w'])
 }
 return normalizeTableCellMargins(result)
}
function sourceOf(block:Block){
 const xml=block.originalXml
 if(block.type!=='table'||!block.table||!xml||xml.length>1024*1024||XMLValidator.validate(xml)!==true||!/^<w:tbl(?:\s|>)/.test(xml)||/<!DOCTYPE|<!ENTITY|\sxmlns(?::\w+)?\s*=/.test(xml))fail()
 const root:Element={name:'w:tbl',xml,start:0},parts=children(root),props=one(parts,'w:tblPr')
 if(parts.some(part=>!['w:tblPr','w:tblGrid','w:tr'].includes(part.name)))fail()
 const propParts=props?children(props):[],target=one(propParts,'w:tblCellMar')
 if(props&&Object.keys(attributes(props)).length||propParts.some(part=>part.name==='w:tblPrChange'||part!==target&&/<w:tblCellMar\b/.test(part.xml)))fail()
 const rawDefaults=target?marginsOf(target):null,defaults=normalizeTableCellMargins(block.table.cellMarTwips)
 if(rawDefaults&&JSON.stringify(rawDefaults)!==JSON.stringify(defaults))fail()
 const cells=block.table.rows.flatMap(row=>row.filter(cell=>cell.vMerge!=='continue').map(cell=>{if(cell.gridGap||cell.hMerge)fail();return normalizeTableCellMargins(cell.cellMarTwips)}))
 if(!cells.length||cells.length>1000||block.table.rows.length>100||block.table.rows.some(row=>row.length>30))fail()
 const source:TableCellMarginsSource={defaults,raw:target?.xml??null,cells}
 return{xml,root,props,propParts,target,source}
}
export function tableCellMarginsAvailability(block:Block){
 try{const s=sourceOf(block);return{tableCellMarginsEditable:true,tableCellMarginsReadOnlyReason:null,tableCellMarginsSource:s.source}}
 catch(error){return{tableCellMarginsEditable:false,tableCellMarginsReadOnlyReason:error instanceof Error?error.message:'docx_table_cell_margins_unsupported'}}
}
export function editTableCellMargins(block:Block,margins:TableCellMargins){
 const value=normalizeTableCellMargins(margins,true) as TableCellMargins,s=sourceOf(block)
 const tag='<w:tblCellMar>'+(['top','left','bottom','right'] as const).map(side=>`<w:${side} w:w="${value[side]}" w:type="dxa"/>`).join('')+'</w:tblCellMar>'
 let start:number,end:number,replacement:string
 if(s.target){start=s.target.start;end=start+s.target.xml.length;replacement=tag}
 else if(!s.props){start=openOf(s.root).length;end=start;replacement=`<w:tblPr>${tag}</w:tblPr>`}
 else if(openOf(s.props).endsWith('/>')){start=s.props.start+s.props.xml.length-2;end=start+2;replacement=`>${tag}</w:tblPr>`}
 else{const next=s.propParts.find(part=>['w:tblLook','w:tblCaption','w:tblDescription','w:tblPrChange'].includes(part.name));start=next?.start??s.props.start+s.props.xml.lastIndexOf('</');end=start;replacement=tag}
 return{xml:s.xml.slice(0,start)+replacement+s.xml.slice(end),margins:value,source:s.source}
}
export function verifyTableCellMarginsResult(block:Block,result:ReturnType<typeof editTableCellMargins>){
 const s=sourceOf(block)
 if(block.originalXml!==result.xml||JSON.stringify(s.source.defaults)!==JSON.stringify(normalizeTableCellMargins(result.margins,true))||JSON.stringify(s.source.cells)!==JSON.stringify(result.source.cells))fail()
}
