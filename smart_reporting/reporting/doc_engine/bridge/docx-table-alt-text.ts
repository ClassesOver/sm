/** 只补表格直属替代文字；保留单元格、隐藏续格、布局及所有非目标XML。 */
import type {Block} from '@genoffice/docx-engine'
import {XMLParser,XMLValidator} from 'fast-xml-parser'
import {splitXmlChildren} from '../packages/docx-engine/src/generate'
import {normalizeTableAltText,type TableAltText,type TableAltTextSource} from '../../../report_editor/frontend/src/docx-table-alt-text-core'
interface Element {name:string;xml:string;start:number}
function fail():never{throw new Error('docx_table_alt_text_unsupported')}
const openOf=(n:Element)=>n.xml.match(/^<[\w:.-]+\b(?:[^>"']|"[^"]*"|'[^']*')*>/)?.[0]??fail()
function children(n:Element):Element[]{const open=openOf(n);if(open.endsWith('/>'))return[];const inner=n.xml.slice(open.length,n.xml.lastIndexOf('</')),parts=splitXmlChildren(inner);if(inner.replace(/\s/g,'')!==parts.map(p=>p.xml).join('').replace(/\s/g,''))fail();let cursor=open.length;return parts.map(p=>{const at=n.xml.indexOf(p.xml,cursor);cursor=at+p.xml.length;return{...p,start:n.start+at}})}
function attrs(n:Element){const result:Record<string,string>={};for(const m of openOf(n).matchAll(/([^\s=<>]+)\s*=\s*(["'])([\s\S]*?)\2/g)){if(Object.hasOwn(result,m[1]))fail();result[m[1]]=m[3]}return result}
function one(parts:Element[],name:string){const matches=parts.filter(p=>p.name===name);if(matches.length>1)fail();return matches[0]}
const parser=new XMLParser({ignoreAttributes:false,attributeNamePrefix:'',parseAttributeValue:false,trimValues:false,htmlEntities:true})
function textOf(n:Element|undefined){if(!n)return'';const a=attrs(n);if(Object.keys(a).length!==1||!Object.hasOwn(a,'w:val')||children(n).length)fail();const value=parser.parse(n.xml)[n.name]['w:val'];if(typeof value!=='string')fail();return value}
function sourceOf(block:Block){
 const xml=block.originalXml
 if(block.type!=='table'||!block.table||!xml||xml.length>1024*1024||XMLValidator.validate(xml)!==true||!/^<w:tbl(?:\s|>)/.test(xml)||/<!DOCTYPE|<!ENTITY|\sxmlns(?::\w+)?\s*=|<w:(?:tblPrChange|tblGridChange|trPrChange|tcPrChange|tblPrExChange|cellMerge|cellIns|cellDel)\b/.test(xml))fail()
 const root:Element={name:'w:tbl',xml,start:0},props=one(children(root),'w:tblPr'),pr=props?children(props):[],title=one(pr,'w:tblCaption'),description=one(pr,'w:tblDescription')
 if(props&&Object.keys(attrs(props)).length||pr.some(p=>p!==title&&p!==description&&/<w:tbl(?:Caption|Description)\b/.test(p.xml)))fail()
 const source:TableAltTextSource={title:textOf(title),description:textOf(description),rawTitle:title?.xml??null,rawDescription:description?.xml??null}
 if((block.table.caption??'')!==source.title||(block.table.description??'')!==source.description)fail()
 return{xml,root,props,pr,title,description,source}
}
function escape(value:string){return value.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/\r/g,'&#13;').replace(/\n/g,'&#10;').replace(/\t/g,'&#9;')}
export function tableAltTextAvailability(block:Block){try{return{tableAltTextEditable:true,tableAltTextReadOnlyReason:null,tableAltTextSource:sourceOf(block).source}}catch(error){return{tableAltTextEditable:false,tableAltTextReadOnlyReason:error instanceof Error?error.message:'docx_table_alt_text_unsupported'}}}
export function editTableAltText(block:Block,value:TableAltText){
 const next=normalizeTableAltText(value),initial=sourceOf(block)
 let xml=initial.xml
 // 逐个在最新XML定位；caption先插在description前，description跟在caption之后。
 for(const [key,name] of [['title','w:tblCaption'],['description','w:tblDescription']] as const){
  const root:Element={name:'w:tbl',xml,start:0},props=one(children(root),'w:tblPr'),pr=props?children(props):[],target=one(pr,name),tag=next[key]?`<${name} w:val="${escape(next[key])}"/>`:''
  let start=0,end=0,replacement=''
  if(target){start=target.start;end=start+target.xml.length;replacement=tag}
  else if(tag){if(!props){start=openOf(root).length;end=start;replacement=`<w:tblPr>${tag}</w:tblPr>`}else if(openOf(props).endsWith('/>')){start=props.start+props.xml.length-2;end=start+2;replacement=`>${tag}</w:tblPr>`}else{const after=key==='title'?one(pr,'w:tblDescription'):undefined;start=after?.start??props.start+props.xml.lastIndexOf('</');end=start;replacement=tag}}
  xml=xml.slice(0,start)+replacement+xml.slice(end)
 }
 return{xml,value:next,source:initial.source}
}
export function verifyTableAltTextResult(block:Block,result:ReturnType<typeof editTableAltText>){const s=sourceOf(block);if(block.originalXml!==result.xml||s.source.title!==result.value.title||s.source.description!==result.value.description)fail()}
