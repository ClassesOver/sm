/** 从可信原生模型生成属性片段；只移植触及属性，原单元格正文与未知 XML 保持原字节。 */
import type { Block } from '@genoffice/docx-engine'
import { generateTableModelXml, splitXmlChildren } from '../packages/docx-engine/src/generate.ts'
import { editTableAltText } from './docx-table-alt-text.ts'
import { tableColumnWidthAvailability } from './docx-table-column-width.ts'
import { normalizeTablePropertiesPatch, type TablePropertiesPatch } from '../../../report_editor/frontend/src/docx-table-properties-core.ts'
type Element={name:string;xml:string;start:number}
const fail=():never=>{throw new Error('docx_table_properties_unsupported')}
function children(xml:string):Element[]{const open=xml.match(/^<[\w:.-]+\b[^>]*>/)?.[0]??fail();if(open.endsWith('/>'))return[];const inner=xml.slice(open.length,xml.lastIndexOf('</')),parts=splitXmlChildren(inner);if(inner.replace(/\s/g,'')!==parts.map(p=>p.xml).join('').replace(/\s/g,''))fail();let at=open.length;return parts.map(p=>{const start=xml.indexOf(p.xml,at);at=start+p.xml.length;return{...p,start}})}
const one=(xml:string,name:string)=>{const parts=children(xml).filter(p=>p.name===name);if(parts.length>1)fail();return parts[0]}
function sourceOf(block:Block,maxWidth:number){
 if(!block.table||!block.originalXml||/<w:(?:tblPrChange|tblGridChange|trPrChange|tcPrChange|cellMerge|cellIns|cellDel)\b/.test(block.originalXml))fail()
 const model=structuredClone(block.table);model.autoFit='fixed';model.floatSide=null;model.floatPos=undefined
 const generated=generateTableModelXml(model,block.originalXml),xml=graft(block.originalXml,generated,'w:tblPr',new Set(['w:tblW','w:tblLayout','w:tblpPr','w:tblOverlap']))
 const s=tableColumnWidthAvailability({...block,originalXml:xml},maxWidth);if(!s.columnWidthEditable)fail();return s
}
export function tablePropertiesAvailability(block:Block,maxWidth:number){try{sourceOf(block,maxWidth);return{tablePropertiesEditable:true,tablePropertiesReadOnlyReason:null}}catch{return{tablePropertiesEditable:false,tablePropertiesReadOnlyReason:'docx_table_properties_unsupported'}}}
/** 不重建容器：替换旧目标、按 generator 顺序补新目标；保留其它节点及空白。 */
function graft(source:string,generated:string,container:string,names:Set<string>):string{
 const old=one(source,container),fresh=one(generated,container),before=old?children(old.xml):[],after=fresh?children(fresh.xml):[]
 let inner=old?old.xml.slice(old.xml.match(/^<[^>]*>/)![0].length,old.xml.lastIndexOf('</')):''
 if(old?.xml.endsWith('/>'))inner=''
 for(const item of before.filter(c=>names.has(c.name)).reverse())inner=inner.replace(item.xml,'')
 const retained=before.filter(c=>!names.has(c.name))
 for(const item of after.filter(c=>names.has(c.name))){const next=after.slice(after.indexOf(item)+1).find(c=>retained.some(p=>p.name===c.name));const at=next?inner.indexOf(retained.find(p=>p.name===next.name)!.xml):inner.length;inner=inner.slice(0,at)+item.xml+inner.slice(at)}
 const replacement=inner?'<'+container+'>'+inner+'</'+container+'>':''
 if(old)return source.slice(0,old.start)+replacement+source.slice(old.start+old.xml.length)
 if(!replacement)return source
 const at=source.match(/^<[^>]*>/)![0].length;return source.slice(0,at)+replacement+source.slice(at)
}
export function editTableProperties(block:Block,maxWidth:number,maxHeight:number,input:TablePropertiesPatch){
 const patch=normalizeTablePropertiesPatch(input),s=sourceOf(block,maxWidth),model=structuredClone(block.table!),original=block.originalXml!,grid=s.columnWidthsTwips!,cols=grid.length
 const rows=children(original).filter(n=>n.name==='w:tr');if(rows.length!==model.rows.length)fail()
 const tableNames=new Set<string>(),rowNames=new Map<number,Set<string>>(),cellNames=new Map<string,Set<string>>()
 const t=patch.table
 if(t){if(t.autoFit!==undefined){model.autoFit=t.autoFit;tableNames.add('w:tblW');tableNames.add('w:tblLayout')};if(t.align!==undefined){model.align=t.align;tableNames.add('w:jc')};if(t.margins){model.cellMarTwips=t.margins;tableNames.add('w:tblCellMar')};if(t.wrap!==undefined){model.floatSide=t.wrap==='none'?null:t.wrap;model.floatPos=t.wrap==='none'?undefined:{xTwips:t.xTwips??model.floatPos?.xTwips??0,yTwips:t.yTwips??model.floatPos?.yTwips??0,horzAnchor:model.floatPos?.horzAnchor??'margin',vertAnchor:model.floatPos?.vertAnchor??'margin',distanceTwips:t.distanceTwips===undefined?model.floatPos?.distanceTwips:{top:t.distanceTwips,right:t.distanceTwips,bottom:t.distanceTwips,left:t.distanceTwips}};tableNames.add('w:tblpPr');tableNames.add('w:tblOverlap')}}
 if(patch.widthsTwips){if(patch.widthsTwips.length!==cols||patch.widthsTwips.reduce((a,b)=>a+b,0)>maxWidth)fail();model.colWidthsTwips=patch.widthsTwips;const sum=patch.widthsTwips.reduce((a,b)=>a+b,0);model.colWidthsPct=patch.widthsTwips.map(n=>n/sum*100);if((t?.autoFit??model.autoFit)==='fixed')tableNames.add('w:tblW')}
 for(const r of patch.rows??[]){if(r.index>=rows.length)fail();const names=new Set<string>();rowNames.set(r.index,names);if(r.heightTwips!==undefined){if(r.heightTwips!==null&&r.heightTwips>maxHeight)fail();model.rowHeightsTwips??=Array(rows.length).fill(null);model.rowHeightRules??=Array(rows.length).fill(null);model.rowHeightsTwips[r.index]=r.heightTwips;model.rowHeightRules[r.index]=r.heightRule!;names.add('w:trHeight')};if(r.cantSplit!==undefined){model.rowCantSplit??=Array(rows.length).fill(null);model.rowCantSplit[r.index]=r.cantSplit;names.add('w:cantSplit')};if(r.repeatHeader!==undefined){model.repeatHeaderRows??=Array(rows.length).fill(null);model.repeatHeaderRows[r.index]=r.repeatHeader;names.add('w:tblHeader')}}
 for(const c of patch.cells??[]){const owner=s.columnWidthCells!.find(o=>o.top===c.row&&o.left===c.column);if(!owner)fail();for(let ri=owner.top;ri<owner.bottom;ri++){let logical=0;const ci=model.rows[ri].findIndex(cell=>{const at=logical;logical+=cell.colSpan??1;return at===owner.left});if(ci<0)fail();const cell=model.rows[ri][ci],names=new Set<string>();cellNames.set(ri+':'+ci,names);if(c.vAlign!==undefined){cell.vAlign=c.vAlign==='top'?undefined:c.vAlign;names.add('w:vAlign')};if(c.noWrap!==undefined){cell.noWrap=c.noWrap;names.add('w:noWrap')};if(c.margins!==undefined){cell.cellMarTwips=c.margins??undefined;names.add('w:tcMar')};cell.tcPrEdited=true}}
 if(patch.alt){model.caption=patch.alt.title;model.description=patch.alt.description;tableNames.add('w:tblCaption');tableNames.add('w:tblDescription')}
 const generatedBase=generateTableModelXml(model,original),generated=patch.alt?graft(generatedBase,editTableAltText(block,patch.alt).xml,'w:tblPr',new Set(['w:tblCaption','w:tblDescription'])):generatedBase,generatedRows=children(generated).filter(n=>n.name==='w:tr')
 let xml=original
 for(let ri=rows.length-1;ri>=0;ri--){const row=rows[ri],fresh=generatedRows[ri];let rowXml=row.xml;const cells=children(row.xml).filter(n=>n.name==='w:tc'),newCells=children(fresh.xml).filter(n=>n.name==='w:tc');if(cells.length!==newCells.length)fail();for(let ci=cells.length-1;ci>=0;ci--){const names=cellNames.get(ri+':'+ci)??new Set<string>();if(patch.widthsTwips)names.add('w:tcW');if(names.size){const cell=cells[ci],next=graft(cell.xml,newCells[ci].xml,'w:tcPr',names);rowXml=rowXml.slice(0,cell.start)+next+rowXml.slice(cell.start+cell.xml.length)}}if(rowNames.has(ri))rowXml=graft(rowXml,fresh.xml,'w:trPr',rowNames.get(ri)!);xml=xml.slice(0,row.start)+rowXml+xml.slice(row.start+row.xml.length)}
 if(patch.widthsTwips){const old=one(xml,'w:tblGrid')!,next=one(generated,'w:tblGrid')!;xml=xml.slice(0,old.start)+next.xml+xml.slice(old.start+old.xml.length)}
 if(tableNames.size)xml=graft(xml,generated,'w:tblPr',tableNames)
 return{xml,patch}
}
export function verifyTablePropertiesResult(block:Block,result:ReturnType<typeof editTableProperties>){if(block.originalXml!==result.xml||!block.table)fail()}
