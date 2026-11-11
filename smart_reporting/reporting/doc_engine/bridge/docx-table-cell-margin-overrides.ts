/** 只补直属tcMar；真实parser生成reset继承基线，不重建PM表或隐藏续格段落。 */
import type {Block,ParsedDocFull} from '@genoffice/docx-engine'
import {parseDocx,saveDocx} from '../packages/docx-engine/src/index.ts'
import {XMLValidator} from 'fast-xml-parser'
import {splitXmlChildren} from '../packages/docx-engine/src/generate.ts'
import {replayTableCellMarginOverrides,type TableCellMarginOverridesSource,type TableCellMarginOverrideCell,type TableCellMarginOverrideStep} from '../../../report_editor/frontend/src/docx-table-cell-margin-overrides-core.ts'
import {normalizeTableCellMargins,type PartialTableCellMargins,type TableCellMargins} from '../../../report_editor/frontend/src/docx-table-cell-margins-core.ts'
interface Element {name:string;xml:string;start:number}
interface Physical {owner:number;node:Element;props?:Element;target?:Element;raw:PartialTableCellMargins|null}
function fail():never{throw new Error('docx_table_cell_margin_overrides_unsupported')}
const openOf=(n:Element)=>n.xml.match(/^<[\w:.-]+\b(?:[^>"']|"[^"]*"|'[^']*')*>/)?.[0]??fail()
function children(n:Element):Element[]{const open=openOf(n);if(open.endsWith('/>'))return[];const inner=n.xml.slice(open.length,n.xml.lastIndexOf('</')),parts=splitXmlChildren(inner);if(inner.replace(/\s/g,'')!==parts.map(p=>p.xml).join('').replace(/\s/g,''))fail();let cursor=open.length;return parts.map(p=>{const at=n.xml.indexOf(p.xml,cursor);cursor=at+p.xml.length;return{...p,start:n.start+at}})}
function attrs(n:Element){const result:Record<string,string>={};for(const m of openOf(n).matchAll(/([^\s=<>]+)\s*=\s*(["'])([\s\S]*?)\2/g)){if(Object.hasOwn(result,m[1]))fail();result[m[1]]=m[3]}return result}
function one(parts:Element[],name:string,required=false){const matches=parts.filter(p=>p.name===name);if(matches.length>1||required&&!matches.length)fail();return matches[0]}
function leaf(n:Element,allowed:string[],required:string[]=allowed){const a=attrs(n);if(Object.keys(a).some(k=>!allowed.includes(k))||required.some(k=>!Object.hasOwn(a,k))||children(n).length)fail();return a}
function marginOf(n:Element):PartialTableCellMargins|null{
 if(Object.keys(attrs(n)).length)fail();const value:PartialTableCellMargins={},names:Record<string,keyof TableCellMargins>={'w:top':'top','w:right':'right','w:bottom':'bottom','w:left':'left','w:start':'left','w:end':'right'}
 for(const p of children(n)){const side=names[p.name],a=leaf(p,['w:w','w:type'],['w:w']);if(!side||Object.hasOwn(value,side)||!/^\d+$/.test(a['w:w'])||a['w:type']!==undefined&&a['w:type']!=='dxa')fail();value[side]=Number(a['w:w'])}
 return normalizeTableCellMargins(value)
}
function sourceOf(block:Block){
 const xml=block.originalXml
 if(block.type!=='table'||!block.table||!xml||xml.length>1024*1024||XMLValidator.validate(xml)!==true||!/^<w:tbl(?:\s|>)/.test(xml)||/<!DOCTYPE|<!ENTITY|\sxmlns(?::\w+)?\s*=|<w:(?:hMerge|gridBefore|gridAfter|trPrChange|tblPrChange|tblGridChange|tcPrChange|tblPrExChange|cellMerge|cellIns|cellDel)\b/.test(xml))fail()
 const root:Element={name:'w:tbl',xml,start:0},parts=children(root),grid=one(parts,'w:tblGrid',true)!,columns=children(grid)
 one(parts,'w:tblPr')
 if(parts.some(p=>!['w:tblPr','w:tblGrid','w:tr'].includes(p.name))||Object.keys(attrs(grid)).length||!columns.length||columns.length>30)fail()
 for(const col of columns){if(col.name!=='w:gridCol')fail();const a=leaf(col,['w:w']);if(!/^\d+$/.test(a['w:w'])||Number(a['w:w'])<1||Number(a['w:w'])>31680)fail()}
 const rows=parts.filter(p=>p.name==='w:tr'),cells:TableCellMarginOverrideCell[]=[],physical:Physical[]=[]
 if(!rows.length||rows.length>100||rows.length*columns.length>1000||rows.length!==block.table.rows.length)fail()
 let active=new Map<number,number>()
 rows.forEach((row,r)=>{const rp=children(row);one(rp,'w:trPr');one(rp,'w:tblPrEx');if(rp.some(p=>!['w:trPr','w:tblPrEx','w:tc'].includes(p.name)))fail();const tc=rp.filter(p=>p.name==='w:tc'),next=new Map<number,number>();if(!tc.length||tc.length!==block.table!.rows[r].length)fail();let col=0
  tc.forEach((node,c)=>{const cp=children(node),props=one(cp,'w:tcPr'),pr=props?children(props):[],target=one(pr,'w:tcMar'),spanNode=one(pr,'w:gridSpan'),mergeNode=one(pr,'w:vMerge')
   if(props&&Object.keys(attrs(props)).length||cp.some(p=>!['w:tcPr','w:p','w:tbl','w:sdt'].includes(p.name))||pr.some(p=>p!==target&&/<w:tcMar\b/.test(p.xml))||pr.some(p=>p!==spanNode&&p!==mergeNode&&/<w:(?:gridSpan|vMerge)\b/.test(p.xml)))fail()
   const rawSpan=spanNode?leaf(spanNode,['w:val'])['w:val']:'1',span=/^\d+$/.test(rawSpan)?Number(rawSpan):0,merge=mergeNode?leaf(mergeNode,['w:val'],[])['w:val']??'continue':undefined,model=block.table!.rows[r][c]
   if(!Number.isSafeInteger(span)||span<1||col+span>columns.length||merge&&!['restart','continue'].includes(merge)||(model.colSpan??1)!==span||model.vMerge!==merge||model.gridGap||model.hMerge)fail()
   const raw=target?marginOf(target):null,effective=normalizeTableCellMargins(model.cellMarTwips)
   if(raw&&Object.entries(raw).some(([side,n])=>effective?.[side as keyof TableCellMargins]!==n))fail()
   let owner:number
   if(merge==='continue'){const prior=active.get(col);if(prior===undefined||cells[prior].right!==col+span)fail();owner=prior;cells[owner].bottom=r+1;next.set(col,owner)}else{owner=cells.length;cells.push({top:r,left:col,bottom:r+1,right:col+span,rawPresent:!!target,hasPhysicalOverrides:!!target,raw,effective,resetEffective:null});if(merge==='restart')next.set(col,owner)}
   if(target)cells[owner].hasPhysicalOverrides=true;physical.push({owner,node,props,target,raw});col+=span
  });if(col!==columns.length)fail();active=next
 })
 return{xml,cells,physical}
}
function patch(s:ReturnType<typeof sourceOf>,values:(TableCellMargins|null|undefined)[]){
 const edits:{start:number;end:number;value:string}[]=[]
 s.physical.forEach(p=>{const value=values[p.owner];if(value===undefined)return;const tag=value?'<w:tcMar>'+(['top','left','bottom','right'] as const).map(side=>`<w:${side} w:w="${value[side]}" w:type="dxa"/>`).join('')+'</w:tcMar>':''
  if(p.target)edits.push({start:p.target.start,end:p.target.start+p.target.xml.length,value:tag})
  else if(tag){if(!p.props){const at=p.node.start+openOf(p.node).length;edits.push({start:at,end:at,value:`<w:tcPr>${tag}</w:tcPr>`})}else if(openOf(p.props).endsWith('/>')){const at=p.props.start+p.props.xml.length-2;edits.push({start:at,end:at+2,value:`>${tag}</w:tcPr>`})}else{const after=children(p.props).find(n=>['w:textDirection','w:tcFitText','w:vAlign','w:hideMark','w:headers','w:tcPrChange'].includes(n.name)),at=after?.start??p.props.start+p.props.xml.lastIndexOf('</');edits.push({start:at,end:at,value:tag})}}
 });let xml=s.xml;for(const e of edits.sort((a,b)=>b.start-a.start))xml=xml.slice(0,e.start)+e.value+xml.slice(e.end);return xml
}
const resetCache=new WeakMap<ParsedDocFull,Promise<Map<number,Block>>>()
/** 每份原包一次批量重解析，避免inspect每张表重复完整save/parse。 */
function resetBlocks(parsed:ParsedDocFull){
 let cached=resetCache.get(parsed)
 if(!cached){cached=(async()=>{const replacements=new Map<number,string>();for(const b of parsed.blocks){if(b.type!=='table'||b.docxIndex==null)continue;try{const s=sourceOf(b);replacements.set(b.docxIndex,patch(s,s.cells.map(()=>null)))}catch{ /* 不支持的表保持原样，不影响其他候选表。 */ }}
  const blocks=parsed.blocks.filter(b=>!b.hidden).map(b=>replacements.has(b.docxIndex!)?{kind:'xml' as const,docxIndex:b.docxIndex!,xml:replacements.get(b.docxIndex!)!}:{kind:'original' as const,docxIndex:b.docxIndex!})
  const read=await parseDocx(await saveDocx(parsed,blocks));return new Map(read.blocks.filter(b=>b.type==='table').map(b=>[b.docxIndex!,b]))
 })();resetCache.set(parsed,cached)}return cached
}
async function trustedSource(block:Block,parsed:ParsedDocFull){
 if(!parsed||block.docxIndex==null||!parsed.blocks.some(b=>b===block))fail()
 const s=sourceOf(block),reset=(await resetBlocks(parsed)).get(block.docxIndex!)
 if(!reset)fail();const inherited=sourceOf(reset)
 if(JSON.stringify(s.cells.map(({top,left,bottom,right})=>({top,left,bottom,right})))!==JSON.stringify(inherited.cells.map(({top,left,bottom,right})=>({top,left,bottom,right}))))fail()
 const source:TableCellMarginOverridesSource={cells:s.cells.map((c,i)=>({...c,resetEffective:inherited.cells[i].effective}))}
 return{s,source}
}
export async function tableCellMarginOverridesAvailability(block:Block,parsed:ParsedDocFull){
 try{const{source}=await trustedSource(block,parsed);return{tableCellMarginOverridesEditable:true,tableCellMarginOverridesReadOnlyReason:null,tableCellMarginOverridesSource:source}}
 catch(e){return{tableCellMarginOverridesEditable:false,tableCellMarginOverridesReadOnlyReason:e instanceof Error?e.message:'docx_table_cell_margin_overrides_unsupported'}}
}
export async function editTableCellMarginOverrides(block:Block,steps:readonly TableCellMarginOverrideStep[],parsed:ParsedDocFull){
 const{s,source}=await trustedSource(block,parsed),result=replayTableCellMarginOverrides(source,steps),values=result.raw.map((m,i)=>result.touched[i]?m as TableCellMargins|null:undefined)
 return{xml:patch(s,values),cells:source.cells,margins:result.margins,physicalMargins:s.physical.map(p=>values[p.owner]===undefined?p.raw:values[p.owner])}
}
export function verifyTableCellMarginOverridesResult(block:Block,result:Awaited<ReturnType<typeof editTableCellMarginOverrides>>){
 const s=sourceOf(block),rects=(cells:TableCellMarginOverrideCell[])=>cells.map(({top,left,bottom,right})=>({top,left,bottom,right}))
 if(block.originalXml!==result.xml||JSON.stringify(rects(s.cells))!==JSON.stringify(rects(result.cells))||JSON.stringify(s.cells.map(c=>c.effective))!==JSON.stringify(result.margins)||JSON.stringify(s.physical.map(p=>p.raw))!==JSON.stringify(result.physicalMargins))fail()
}
