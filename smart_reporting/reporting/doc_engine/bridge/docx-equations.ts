/** 公式只接受 LaTeX 意图；按原始段落切片修改，不重建其他 XML。 */
import {createHash} from 'node:crypto'
import {loadDocxZip} from '../packages/docx-engine/src/zip-load.ts'
import {XMLParser} from 'fast-xml-parser'
import {splitXmlChildren} from '../packages/docx-engine/src/generate.ts'
import {parseDocx} from '../packages/docx-engine/src/parse.ts'
import {latexToOmml,ommlToLatex} from '../packages/docx-engine/src/math.ts'
import {textOf,type XNode} from '../packages/docx-engine/src/xml-utils.ts'
import {assertZipIdentity,parseCommentSourceXml} from './docx-comment-source.ts'
const MAIN='word/document.xml',M='http://schemas.openxmlformats.org/officeDocument/2006/math'
const hash=(v:string|Uint8Array)=>createHash('sha256').update(v).digest('hex')
const fail=(v:string):never=>{throw new Error('docx_equation_'+v)}
interface Slice {name:string;xml:string;start:number}
function opening(s:Slice){let q='';for(let i=0;i<s.xml.length;i++){const c=s.xml[i];if(q){if(c===q)q=''}else if(c==='"'||c==="'")q=c;else if(c==='>')return s.xml.slice(0,i+1)}return fail('xml_slice')}
function children(s:Slice):Slice[]{const o=opening(s);if(o.endsWith('/>'))return[];let at=o.length;return splitXmlChildren(s.xml.slice(at,s.xml.lastIndexOf('</'))).map(p=>{const i=s.xml.indexOf(p.xml,at);if(i<0)fail('xml_slice');at=i+p.xml.length;return {...p,start:s.start+i}})}
const parser=new XMLParser({preserveOrder:true,ignoreAttributes:false,attributeNamePrefix:'',trimValues:false,parseTagValue:false,parseAttributeValue:false,htmlEntities:true})
const decoded=(s:Slice)=>textOf((parser.parse(s.xml) as XNode[])[0])
const escape=(v:string)=>v.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')
import type {EquationFormula,EquationTarget,DocxEquationsModel,EquationStep,EquationOperation} from './docx-equations-core.ts'
export type {EquationFormula,EquationTarget,DocxEquationsModel,EquationStep,EquationOperation} from './docx-equations-core.ts'
interface Token {slice:Slice;size:number;value?:string;formulaId?:string;display?:boolean}
function tokens(p:Slice,targetId:string):{tokens:Token[];reason?:string}{
 const out:Token[]=[];let ordinal=0,reason:string|undefined
 for(const s of children(p)){
  if(s.name==='w:pPr'){out.push({slice:s,size:0});continue}
  if(s.name==='m:oMath'||s.name==='m:oMathPara'){out.push({slice:s,size:1,formulaId:hash(targetId+':'+ordinal++),display:s.name==='m:oMathPara'});continue}
  if(s.name==='w:r'){
   const parts=children(s),ts=parts.filter(t=>t.name==='w:t')
   if(ts.length===1&&parts.every(t=>t.name==='w:t'||t.name==='w:rPr')){const value=decoded(ts[0]);out.push({slice:s,size:value.length,value});continue}
  }
  reason='段落含字段、书签、修订或未知内联结构，公式修改仅供查看';out.push({slice:s,size:0})
 }
 return {tokens:out,reason}
}
async function source(bytes:Uint8Array){
 assertZipIdentity(bytes);const zip=await loadDocxZip(bytes),file=zip.file(MAIN);if(!file)fail('document_missing')
 const xml=await file!.async('string');parseCommentSourceXml(xml)
 const start=xml.indexOf('<w:document');if(start<0)fail('namespace');const root:Slice={name:'w:document',start,xml:xml.slice(start)}
 if(!/xmlns:w=["']http:\/\/schemas.openxmlformats.org\/wordprocessingml\/2006\/main["']/.test(opening(root)))fail('namespace')
 for(const [prefix,namespace] of [['w','http://schemas.openxmlformats.org/wordprocessingml/2006/main'],['m',M]]){const declarations=[...xml.matchAll(new RegExp('xmlns:'+prefix+'=[\"\']([^\"\']*)[\"\']','g'))];if(declarations.some(d=>d[1]!==namespace))fail('namespace_shadow')}
 const body=children(root).find(s=>s.name==='w:body');if(!body)fail('body')
 const parsed=await parseDocx(bytes),spans:{index:number;start:number;end:number}[]=[];let cursor=0
 for(const block of parsed.blocks){if(!block.originalXml)continue;const at=xml.indexOf(block.originalXml,cursor);if(at<0)continue;spans.push({index:block.docxIndex,start:at,end:at+block.originalXml.length});cursor=at+block.originalXml.length}
 const sourceId=hash(bytes),targets:EquationTarget[]=[],slices=new Map<string,Slice>()
 const visit=(s:Slice,blockIndex:number,ordinal:{n:number},unsupported=false,inTable=false)=>{
  if(s.name==='w:p'){
   const span=spans.find(r=>s.start>=r.start&&s.start+s.xml.length<=r.end),targetId=hash(sourceId+':'+s.start+':'+hash(s.xml)),t=tokens(s,targetId);if(!span)unsupported=true;let offset=0,text='';const formulas:EquationFormula[]=[]
   for(const token of t.tokens){if(token.formulaId){const latex=ommlToLatex(token.slice.xml);formulas.push({formulaId:token.formulaId,offset,display:!!token.display,latex,omml:token.slice.xml,...(latex===null?{readOnlyReason:'原公式无法无损反编译，保留原 OMML'}:{})})}else text+=token.value??'';offset+=token.size}
   targets.push({targetId,blockIndex:span?.index??blockIndex,paragraphOrdinal:ordinal.n++,container:inTable?'table':'body',text,expectedParagraphSha256:hash(s.xml),formulas,...(unsupported||t.reason?{readOnlyReason:unsupported?'当前容器尚不能独立核验公式投影':t.reason}:{})});slices.set(targetId,s);return
  }
  for(const c of children(s))visit(c,blockIndex,ordinal,unsupported||s.name==='w:sdt'&&/<w:lock\b/.test(s.xml)||!['w:tbl','w:tr','w:tc','w:sdt','w:sdtContent'].includes(s.name),inTable||s.name==='w:tbl')
 }
 children(body!).forEach((s,i)=>{if(s.name==='w:p'||s.name==='w:tbl'||s.name==='w:sdt')visit(s,i,{n:0})})
 const model:DocxEquationsModel={sourceId,targets}
 const settings=zip.file('word/settings.xml');if(settings&&/<w:(?:documentProtection|writeProtection)\b/.test(await settings.async('string')))model.readOnlyReason='受保护文档中的公式仅供查看'
 return {zip,xml,model,slices,root}
}
export async function inspectDocxEquations(bytes:Uint8Array):Promise<DocxEquationsModel>{return (await source(bytes)).model}
function keys(v:object,wanted:string[]){return Object.keys(v).sort().join('|')===wanted.sort().join('|')}
function formula(latex:unknown,display:boolean){if(typeof latex!=='string'||!latex.trim()||latex.length>20000)fail('latex');try{const xml='<m:oMath>'+latexToOmml((latex as string).trim())+'</m:oMath>';return display?'<m:oMathPara><m:oMathParaPr><m:jc m:val="center"/></m:oMathParaPr>'+xml+'</m:oMathPara>':xml}catch{return fail('latex_unsupported')}}
export async function patchDocxEquations(bytes:Uint8Array,op:EquationOperation):Promise<Uint8Array>{
 const s=await source(bytes),{model}=s
 if(!op||typeof op!=='object'||!keys(op,['kind','sourceId','steps'])||op.kind!=='editEquations'||op.sourceId!==model.sourceId||model.readOnlyReason||!Array.isArray(op.steps)||!op.steps.length||op.steps.length>500)fail('operation_identity')
 const changed=new Map<string,Token[]>()
 for(const [index,step] of op.steps.entries()){
  if(!step||typeof step!=='object'||!keys(step,step.action==='insert'?['targetId','action','offset','display','latex']:step.action==='update'?['targetId','action','formulaId','latex']:['targetId','action','formulaId']))fail('step_fields')
  const target=model.targets.find(t=>t.targetId===step.targetId);if(!target||target.readOnlyReason)return fail('target_identity')
  let list=changed.get(target.targetId);if(!list){list=tokens(s.slices.get(target.targetId)!,target.targetId).tokens;changed.set(target.targetId,list)}
  if(step.action==='insert'){
   if(!Number.isSafeInteger(step.offset)||step.offset<0||typeof step.display!=='boolean')fail('offset')
   const xml=formula(step.latex,step.display),token:Token={slice:{name:step.display?'m:oMathPara':'m:oMath',xml,start:0},size:1,formulaId:'insert:'+index,display:step.display};let at=0,done=false
   for(let i=0;i<list.length;i++){const t=list[i];if(t.size===0)continue
    if(step.offset===at){list.splice(i,0,token);done=true;break}
    if(step.offset>at&&step.offset<at+t.size){if(t.value===undefined)fail('offset');const cut=step.offset-at,v=t.value!;if(/[\uD800-\uDBFF]/.test(v[cut-1])&&/[\uDC00-\uDFFF]/.test(v[cut]))fail('offset_surrogate')
     const ts=children(t.slice).find(x=>x.name==='w:t')!,rel=ts.start-t.slice.start,part=(value:string):Token=>({slice:{...t.slice,xml:t.slice.xml.slice(0,rel)+'<w:t xml:space="preserve">'+escape(value)+'</w:t>'+t.slice.xml.slice(rel+ts.xml.length)},size:value.length,value});list.splice(i,1,part(v.slice(0,cut)),token,part(v.slice(cut)));done=true;break}at+=t.size
   }if(!done){if(step.offset!==at)fail('offset');list.push(token)}
  }else if(step.action==='update'||step.action==='delete'){
   const at=list.findIndex(t=>t.formulaId===step.formulaId);if(at<0)fail('formula_identity')
   if(step.action==='delete')list.splice(at,1);else{if(ommlToLatex(list[at].slice.xml)===null)fail('formula_readonly');list[at]={...list[at],slice:{...list[at].slice,xml:formula(step.latex,!!list[at].display)}}}
  }else fail('action')
 }
 let xml=s.xml
 for(const [id,list] of [...changed].sort((a,b)=>s.slices.get(b[0])!.start-s.slices.get(a[0])!.start)){
  const p=s.slices.get(id)!,o=opening(p),open=o.endsWith('/>')?o.slice(0,-2)+'>':o,target=model.targets.find(t=>t.targetId===id)!,pPr=list.find(t=>t.slice.name==='w:pPr')?.slice.xml??'';let replacement:string
  if(target.container==='body'&&list.some(t=>t.display)){const groups:string[]=[];let current='';for(const t of list){if(t.slice.name==='w:pPr')continue;if(t.display){if(current)groups.push(open+pPr+current+'</w:p>');groups.push(open+pPr+t.slice.xml+'</w:p>');current=''}else current+=t.slice.xml}if(current)groups.push(open+pPr+current+'</w:p>');replacement=groups.join('')}else replacement=open+list.map(t=>t.slice.xml).join('')+'</w:p>';xml=xml.slice(0,p.start)+replacement+xml.slice(p.start+p.xml.length)
 }
 if(!opening(s.root).includes('xmlns:m=')){const at=xml.indexOf('>',s.root.start);xml=xml.slice(0,at)+' xmlns:m="'+M+'"'+xml.slice(at)}
 parseCommentSourceXml(xml);s.zip.file(MAIN,xml,{createFolders:false});return s.zip.generateAsync({type:'uint8array',compression:'DEFLATE'})
}
