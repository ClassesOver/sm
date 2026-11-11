/** 行跨页只补直属trPr/cantSplit，保留全部物理格及隐藏段落XML。 */
import type {Block} from '@genoffice/docx-engine'
import {XMLValidator} from 'fast-xml-parser'
import {splitXmlChildren} from '../packages/docx-engine/src/generate.ts'
import {replayTableRowBreakSteps,type TableRowBreakStep,type TableRowBreakCell,type TableRowBreakSource} from '../../../report_editor/frontend/src/docx-table-row-breaks-core.ts'
interface Element {name:string;xml:string;start:number}
function fail():never{throw new Error('docx_table_row_breaks_unsupported')}
const openOf=(n:Element)=>n.xml.match(/^<[\w:.-]+\b(?:[^>"']|"[^"]*"|'[^']*')*>/)?.[0]??fail()
function children(n:Element):Element[]{const open=openOf(n);if(open.endsWith('/>'))return[];const inner=n.xml.slice(open.length,n.xml.lastIndexOf('</')),parts=splitXmlChildren(inner);if(inner.replace(/\s/g,'')!==parts.map(p=>p.xml).join('').replace(/\s/g,''))fail();let cursor=open.length;return parts.map(p=>{const at=n.xml.indexOf(p.xml,cursor);cursor=at+p.xml.length;return{...p,start:n.start+at}})}
function attrs(n:Element){const result:Record<string,string>={};for(const m of openOf(n).matchAll(/([^\s=<>]+)\s*=\s*(["'])([\s\S]*?)\2/g)){if(Object.hasOwn(result,m[1]))fail();result[m[1]]=m[3]}return result}
function one(parts:Element[],name:string,required=false){const matches=parts.filter(p=>p.name===name);if(matches.length>1||required&&!matches.length)fail();return matches[0]}
function leaf(n:Element,allowed:string[],required:string[]=allowed){const a=attrs(n);if(Object.keys(a).some(k=>!allowed.includes(k))||required.some(k=>!Object.hasOwn(a,k))||children(n).length)fail();return a}
function sourceOf(block:Block){
 const xml=block.originalXml
 if(block.type!=='table'||!block.table||!xml||xml.length>1024*1024||XMLValidator.validate(xml)!==true||!/^<w:tbl(?:\s|>)/.test(xml)||/<!DOCTYPE|<!ENTITY|\sxmlns(?::\w+)?\s*=|<w:(?:hMerge|gridBefore|gridAfter|trPrChange|tblPrChange|tblGridChange|tcPrChange|tblPrExChange|cellMerge|cellIns|cellDel)\b/.test(xml))fail()
 const root:Element={name:'w:tbl',xml,start:0},parts=children(root),grid=one(parts,'w:tblGrid',true)!,columns=children(grid)
 one(parts,'w:tblPr')
 if(parts.some(p=>!['w:tblPr','w:tblGrid','w:tr'].includes(p.name))||Object.keys(attrs(grid)).length||!columns.length||columns.length>30)fail()
 for(const col of columns){if(col.name!=='w:gridCol')fail();const a=leaf(col,['w:w']);if(!/^\d+$/.test(a['w:w'])||Number(a['w:w'])<1||Number(a['w:w'])>31680)fail()}
 const rows=parts.filter(p=>p.name==='w:tr'),cells:TableRowBreakCell[]=[],rowInfo:{node:Element;props?:Element;target?:Element}[]=[],flags:{cantSplit:boolean;raw:string|null}[]=[]
 if(!rows.length||rows.length>100||rows.length*columns.length>1000||rows.length!==block.table.rows.length)fail()
 let active=new Map<number,number>()
 rows.forEach((row,r)=>{const rp=children(row);one(rp,'w:tblPrEx');if(rp.some(p=>!['w:trPr','w:tblPrEx','w:tc'].includes(p.name)))fail()
  const props=one(rp,'w:trPr'),pr=props?children(props):[],target=one(pr,'w:cantSplit')
  if(props&&Object.keys(attrs(props)).length||pr.some(p=>p!==target&&/<w:cantSplit\b/.test(p.xml)))fail()
  let cantSplit=false
  if(target){const a=leaf(target,['w:val'],[]),v=a['w:val']?.toLowerCase();if(v!==undefined&&!['0','1','true','false','on','off','none'].includes(v))fail();cantSplit=v===undefined||['1','true','on'].includes(v)}
  if((block.table!.rowCantSplit?.[r]??false)!==cantSplit)fail()
  flags.push({cantSplit,raw:target?.xml??null});rowInfo.push({node:row,props,target})
  const tc=rp.filter(p=>p.name==='w:tc'),next=new Map<number,number>();if(!tc.length||tc.length!==block.table!.rows[r].length)fail();let col=0
  tc.forEach((node,c)=>{const cp=children(node),props=one(cp,'w:tcPr'),pr=props?children(props):[],spanNode=one(pr,'w:gridSpan'),mergeNode=one(pr,'w:vMerge')
   if(cp.some(p=>!['w:tcPr','w:p','w:tbl','w:sdt'].includes(p.name))||pr.some(p=>p!==spanNode&&p!==mergeNode&&/<w:(?:gridSpan|vMerge)\b/.test(p.xml)))fail()
   const rawSpan=spanNode?leaf(spanNode,['w:val'])['w:val']:'1',span=/^\d+$/.test(rawSpan)?Number(rawSpan):0,merge=mergeNode?leaf(mergeNode,['w:val'],[])['w:val']??'continue':undefined,model=block.table!.rows[r][c]
   if(!Number.isSafeInteger(span)||span<1||col+span>columns.length||merge&&!['restart','continue'].includes(merge)||(model.colSpan??1)!==span||model.vMerge!==merge||model.gridGap||model.hMerge)fail()
   if(merge==='continue'){const prior=active.get(col);if(prior===undefined||cells[prior].right!==col+span)fail();cells[prior].bottom=r+1;next.set(col,prior)}else{const owner=cells.length;cells.push({top:r,left:col,bottom:r+1,right:col+span});if(merge==='restart')next.set(col,owner)}col+=span
  });if(col!==columns.length)fail();active=next
 })
 return{xml,rowInfo,source:{cells,rows:flags} satisfies TableRowBreakSource}
}
export function tableRowBreakAvailability(block:Block){
 try{const s=sourceOf(block);return{rowBreakEditable:true,rowBreakReadOnlyReason:null,rowBreakSource:s.source}}
 catch(e){return{rowBreakEditable:false,rowBreakReadOnlyReason:e instanceof Error?e.message:'docx_table_row_breaks_unsupported'}}
}
export function editTableRowBreaks(block:Block,steps:readonly TableRowBreakStep[]){
 const s=sourceOf(block),r=replayTableRowBreakSteps(s.source.rows.map(row=>row.cantSplit),steps),edits:{start:number;end:number;value:string}[]=[]
 s.rowInfo.forEach((info,i)=>{if(!r.touched[i])return;const tag=r.cantSplit[i]?'<w:cantSplit/>':''
  if(info.target)edits.push({start:info.target.start,end:info.target.start+info.target.xml.length,value:tag})
  else if(tag){if(!info.props){const exception=one(children(info.node),'w:tblPrEx'),at=exception?exception.start+exception.xml.length:info.node.start+openOf(info.node).length;edits.push({start:at,end:at,value:`<w:trPr>${tag}</w:trPr>`})}else if(openOf(info.props).endsWith('/>')){const at=info.props.start+info.props.xml.length-2;edits.push({start:at,end:at+2,value:`>${tag}</w:trPr>`})}else{const after=children(info.props).find(n=>['w:trHeight','w:tblHeader','w:tblCellSpacing','w:jc','w:hidden','w:ins','w:del','w:trPrChange'].includes(n.name)),at=after?.start??info.props.start+info.props.xml.lastIndexOf('</');edits.push({start:at,end:at,value:tag})}}
 });let xml=s.xml;for(const e of edits.sort((a,b)=>b.start-a.start))xml=xml.slice(0,e.start)+e.value+xml.slice(e.end)
 return{xml,source:s.source,cantSplit:r.cantSplit}
}
export function verifyTableRowBreakResult(block:Block,result:ReturnType<typeof editTableRowBreaks>){
 const s=sourceOf(block)
 if(block.originalXml!==result.xml||JSON.stringify(s.source.cells)!==JSON.stringify(result.source.cells)||JSON.stringify(s.source.rows.map(r=>r.cantSplit))!==JSON.stringify(result.cantSplit))fail()
}
