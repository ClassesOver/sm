/** 整表对齐只补直属tblPr/jc；浮动定位、宽度、缩进和所有物理格内容保持原字节。 */
import type {Block} from '@genoffice/docx-engine'
import {XMLValidator} from 'fast-xml-parser'
import {splitXmlChildren} from '../packages/docx-engine/src/generate'
import type {TableAlignment,TableAlignmentSource} from '../../../report_editor/frontend/src/docx-table-alignment-core'
interface Element {name:string;xml:string;start:number}
function fail():never{throw new Error('docx_table_alignment_unsupported')}
const openOf=(n:Element)=>n.xml.match(/^<[\w:.-]+\b(?:[^>"']|"[^"]*"|'[^']*')*>/)?.[0]??fail()
function children(n:Element):Element[]{const open=openOf(n);if(open.endsWith('/>'))return[];const inner=n.xml.slice(open.length,n.xml.lastIndexOf('</')),parts=splitXmlChildren(inner);if(inner.replace(/\s/g,'')!==parts.map(p=>p.xml).join('').replace(/\s/g,''))fail();let cursor=open.length;return parts.map(p=>{const at=n.xml.indexOf(p.xml,cursor);cursor=at+p.xml.length;return{...p,start:n.start+at}})}
function attrs(n:Element){const result:Record<string,string>={};for(const m of openOf(n).matchAll(/([^\s=<>]+)\s*=\s*(["'])([\s\S]*?)\2/g)){if(Object.hasOwn(result,m[1]))fail();result[m[1]]=m[3]}return result}
function one(parts:Element[],name:string,required=false){const matches=parts.filter(p=>p.name===name);if(matches.length>1||required&&!matches.length)fail();return matches[0]}
function leaf(n:Element,allowed:string[],required:string[]=allowed){const a=attrs(n);if(Object.keys(a).some(k=>!allowed.includes(k))||required.some(k=>!Object.hasOwn(a,k))||children(n).length)fail();return a}
function sourceOf(block:Block){
 const xml=block.originalXml
 if(block.type!=='table'||!block.table||!xml||xml.length>1024*1024||XMLValidator.validate(xml)!==true||!/^<w:tbl(?:\s|>)/.test(xml)||/<!DOCTYPE|<!ENTITY|\sxmlns(?::\w+)?\s*=|<w:(?:hMerge|gridBefore|gridAfter|trPrChange|tblPrChange|tblGridChange|tcPrChange|tblPrExChange|cellMerge|cellIns|cellDel)\b/.test(xml))fail()
 const root:Element={name:'w:tbl',xml,start:0},parts=children(root),grid=one(parts,'w:tblGrid',true)!,columns=children(grid)
 const props=one(parts,'w:tblPr'),pr=props?children(props):[],target=one(pr,'w:jc'),indent=one(pr,'w:tblInd'),width=one(pr,'w:tblW'),float=one(pr,'w:tblpPr')
 if(props&&Object.keys(attrs(props)).length||pr.some(p=>p!==target&&/<w:jc\b/.test(p.xml)))fail()
 let alignment:TableAlignmentSource['alignment']=null
 if(target){const value=leaf(target,['w:val'])['w:val'];if(!['left','start','center','right','end'].includes(value))fail();alignment=value==='center'?'center':value==='right'||value==='end'?'right':null}
 if((block.table.align??null)!==alignment)fail()
 if(parts.some(p=>!['w:tblPr','w:tblGrid','w:tr'].includes(p.name))||Object.keys(attrs(grid)).length||!columns.length||columns.length>30)fail()
 for(const col of columns){if(col.name!=='w:gridCol')fail();const a=leaf(col,['w:w']);if(!/^\d+$/.test(a['w:w'])||Number(a['w:w'])<1||Number(a['w:w'])>31680)fail()}
 const rows=parts.filter(p=>p.name==='w:tr'),cells:TableAlignmentSource['cells']=[]
 if(!rows.length||rows.length>100||rows.length*columns.length>1000||rows.length!==block.table.rows.length)fail()
 let active=new Map<number,number>()
 rows.forEach((row,r)=>{const rp=children(row);one(rp,'w:tblPrEx');if(rp.some(p=>!['w:trPr','w:tblPrEx','w:tc'].includes(p.name)))fail()
  const tc=rp.filter(p=>p.name==='w:tc'),next=new Map<number,number>();if(!tc.length||tc.length!==block.table!.rows[r].length)fail();let col=0
  tc.forEach((node,c)=>{const cp=children(node),props=one(cp,'w:tcPr'),pr=props?children(props):[],spanNode=one(pr,'w:gridSpan'),mergeNode=one(pr,'w:vMerge')
   if(cp.some(p=>!['w:tcPr','w:p','w:tbl','w:sdt'].includes(p.name))||pr.some(p=>p!==spanNode&&p!==mergeNode&&/<w:(?:gridSpan|vMerge)\b/.test(p.xml)))fail()
   const rawSpan=spanNode?leaf(spanNode,['w:val'])['w:val']:'1',span=/^\d+$/.test(rawSpan)?Number(rawSpan):0,merge=mergeNode?leaf(mergeNode,['w:val'],[])['w:val']??'continue':undefined,model=block.table!.rows[r][c]
   if(!Number.isSafeInteger(span)||span<1||col+span>columns.length||merge&&!['restart','continue'].includes(merge)||(model.colSpan??1)!==span||model.vMerge!==merge||model.gridGap||model.hMerge)fail()
   if(merge==='continue'){const prior=active.get(col);if(prior===undefined||cells[prior].right!==col+span)fail();cells[prior].bottom=r+1;next.set(col,prior)}else{const owner=cells.length;cells.push({top:r,left:col,bottom:r+1,right:col+span});if(merge==='restart')next.set(col,owner)}col+=span
  });if(col!==columns.length)fail();active=next
 })
 return{xml,root,props,pr,target,source:{cells,alignment,raw:target?.xml??null,rawIndent:indent?.xml??null,rawWidth:width?.xml??null,bidiVisual:block.table.bidiVisual??false,positioning:float?'floating' as const:'inline' as const} satisfies TableAlignmentSource}
}
export function tableAlignmentAvailability(block:Block){
 try{const s=sourceOf(block);return{tableAlignmentEditable:true,tableAlignmentReadOnlyReason:null,tableAlignmentSource:s.source}}
 catch(e){return{tableAlignmentEditable:false,tableAlignmentReadOnlyReason:e instanceof Error?e.message:'docx_table_alignment_unsupported'}}
}
export function editTableAlignment(block:Block,value:TableAlignment){
 if(!['left','center','right'].includes(value))fail()
 const s=sourceOf(block),alignment=value==='left'?null:value,tag=alignment?`<w:jc w:val="${alignment}"/>`:''
 let start=0,end=0,replacement=''
 if(s.target){start=s.target.start;end=start+s.target.xml.length;replacement=tag}
 else if(tag){if(!s.props){start=openOf(s.root).length;end=start;replacement=`<w:tblPr>${tag}</w:tblPr>`}else if(openOf(s.props).endsWith('/>')){start=s.props.start+s.props.xml.length-2;end=start+2;replacement=`>${tag}</w:tblPr>`}else{const next=s.pr.find(n=>['w:tblCellSpacing','w:tblInd','w:tblBorders','w:shd','w:tblLayout','w:tblCellMar','w:tblLook','w:tblCaption','w:tblDescription','w:tblPrChange'].includes(n.name));start=next?.start??s.props.start+s.props.xml.lastIndexOf('</');end=start;replacement=tag}}
 return{xml:s.xml.slice(0,start)+replacement+s.xml.slice(end),alignment,source:s.source}
}
export function verifyTableAlignmentResult(block:Block,result:ReturnType<typeof editTableAlignment>){
 const s=sourceOf(block),before={...result.source,alignment:result.alignment,raw:s.source.raw}
 if(block.originalXml!==result.xml||JSON.stringify(s.source)!==JSON.stringify(before))fail()
}
