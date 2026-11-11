/** 已有批注文字的纯 core：不读写文件、不核验宿主授权/实际 part/关系/锚点。
 * 宿主必须从授权版本取得原始 comments.xml，绑定 sourceId，并核验保护、命名空间、
 * comments relationship/实际 part 与 hyperlink r:id。不得把解析/规范化后的 XML 冒充原字节。
 * 输出只替换该 part 的受权片段；不要传 saveDocx(options.comments) 重建整族。
 */
import {createHash} from 'node:crypto'
import {XMLParser,XMLValidator} from 'fast-xml-parser'
import {splitXmlChildren} from '../packages/docx-engine/src/generate'
import {patchParagraphTexts} from '../packages/docx-engine/src/text-patch'

export interface CommentTextSource {sourceId:string;commentsXml:string;protectedDocument:boolean}
export interface CommentTextTarget {
 sourceId:string;targetId:string;expectedCommentsSha256:string;expectedObjectSha256:string
 originalCommentId:string;ordinal:number;author:string;date:string|null;initials:string|null;text:string
 relationshipIds:string[];editableText:boolean;readOnlyReason:string|null
}
export interface CommentTextOperation {
 kind:'editCommentText';sourceId:string;targetId:string;expectedCommentsSha256:string;expectedObjectSha256:string;text:string
}
interface Element {name:string;xml:string;start:number}
const W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
const NS:Record<string,string>={w:W,w14:'http://schemas.microsoft.com/office/word/2010/wordml',r:'http://schemas.openxmlformats.org/officeDocument/2006/relationships',xml:'http://www.w3.org/XML/1998/namespace'}
const parser=new XMLParser({ignoreAttributes:false,attributeNamePrefix:'',parseAttributeValue:false,parseTagValue:false,trimValues:false,htmlEntities:true})
const hash=(s:string)=>createHash('sha256').update(s).digest('hex')
function fail(reason:string):never{throw new Error(reason)}
function opening(n:Element){return n.xml.match(/^<[\w:.-]+\b(?:[^>"']|"[^"]*"|'[^']*')*>/)?.[0]??fail('docx_comment_xml_unsupported')}
function attributes(n:Element):Record<string,string>{return parser.parse(opening(n).replace(/\/?>$/,'/>'))[n.name]??{}}
function children(n:Element):Element[]{
 const open=opening(n);if(open.endsWith('/>'))return[]
 const inner=n.xml.slice(open.length,n.xml.lastIndexOf('</')),parts=splitXmlChildren(inner)
 if(inner.replace(/\s/g,'')!==parts.map(p=>p.xml).join('').replace(/\s/g,''))fail('docx_comment_structure_unsupported')
 let cursor=open.length
 return parts.map(p=>{const at=n.xml.indexOf(p.xml,cursor);cursor=at+p.xml.length;return{...p,start:n.start+at}})
}
function textOf(n:Element):string{
 const value=parser.parse(n.xml)[n.name]
 return typeof value==='object'?String(value?.['#text']??''):String(value??'')
}
const properties=new Set(['b','bCs','i','iCs','u','strike','dstrike','color','highlight','rFonts','sz','szCs','vertAlign','rStyle','lang','caps','smallCaps','spacing','kern','position','noProof','vanish','rtl','cs','keepNext','keepLines','widowControl','pStyle','jc','ind','contextualSpacing','suppressAutoHyphens','shd','snapToGrid'].map(n=>'w:'+n))
function inspectStructure(comment:Element,rootAttrs:Record<string,string>){
 const paras=children(comment),relationships=new Set<string>()
 if(!paras.length||paras.some(p=>p.name!=='w:p'))fail('docx_comment_structure_unsupported')
 function check(n:Element){
  const a=attributes(n)
  for(const [key,value] of Object.entries(a)){
   if(key==='xmlns'||key.startsWith('xmlns:'))fail('docx_comment_namespace_unsupported')
   if(key.includes(':')){const prefix=key.split(':')[0];if(!NS[prefix]||prefix!=='xml'&&rootAttrs['xmlns:'+prefix]!==NS[prefix])fail('docx_comment_namespace_unsupported')}
   if(/[<>]/.test(value))fail('docx_comment_payload_unsupported')
  }
  if(!['w:comment','w:p','w:pPr','w:r','w:rPr','w:hyperlink','w:t'].includes(n.name)&&!properties.has(n.name))fail('docx_comment_structure_unsupported')
  if(n.name==='w:t'){
   if(Object.keys(a).some(k=>k!=='xml:space')||!/^<w:t(?:\s[^>]*)?>[^<]*<\/w:t>$/.test(n.xml))fail('docx_comment_text_anchor_unsupported')
   return
  }
  const parts=children(n)
  const allowed=n.name==='w:comment'?['w:p']:n.name==='w:p'?['w:pPr','w:r','w:hyperlink']:n.name==='w:hyperlink'?['w:r']:n.name==='w:r'?['w:rPr','w:t']:null
  if(allowed&&parts.some(p=>!allowed.includes(p.name)))fail('docx_comment_structure_unsupported')
  if(n.name==='w:pPr'||n.name==='w:rPr'){if(parts.some(p=>!properties.has(p.name)))fail('docx_comment_structure_unsupported')}
  else if(!allowed&&parts.length)fail('docx_comment_structure_unsupported')
  if(n.name==='w:p'||n.name==='w:r'){
   const prop=n.name==='w:p'?'w:pPr':'w:rPr',at=parts.findIndex(p=>p.name===prop)
   if(at>0||parts.filter(p=>p.name===prop).length>1)fail('docx_comment_structure_unsupported')
  }
  if(n.name==='w:hyperlink'&&a['r:id'])relationships.add(a['r:id'])
  parts.forEach(check)
 }
 check(comment)
 const text=paras.map(p=>{
  const ts=[...p.xml.matchAll(/<w:t(?:\s[^>]*)?>[^<]*<\/w:t>/g)]
  if(!ts.length)fail('docx_comment_text_anchor_unsupported')
  const parts=ts.map(t=>textOf({name:'w:t',xml:t[0],start:0}))
  if(parts.some(text=>/[\r\n]/.test(text)))fail('docx_comment_inline_break_unsupported')
  return parts.join('')
 }).join('\n')
 return{text,relationshipIds:[...relationships]}
}
function readSource(source:CommentTextSource){
 if(!source||typeof source.sourceId!=='string'||!source.sourceId||source.sourceId.length>1024||typeof source.commentsXml!=='string'||typeof source.protectedDocument!=='boolean')fail('docx_comment_source_invalid')
 if(source.protectedDocument)fail('docx_comment_protected')
 const xml=source.commentsXml
 if(xml.length>4*1024*1024||!validXmlCharacters(xml)||!validEntities(xml)||XMLValidator.validate(xml)!==true||/<!|<\?(?!xml\s)/.test(xml))fail('docx_comment_xml_unsupported')
 const start=xml.indexOf('<w:comments'),root:Element={name:'w:comments',xml:xml.slice(start),start}
 if(start<0||!/^<w:comments(?:\s|>)/.test(root.xml))fail('docx_comment_namespace_unsupported')
 const rootAttrs=attributes(root)
 if(rootAttrs['xmlns:w']!==W)fail('docx_comment_namespace_unsupported')
 const comments=children(root).filter(n=>n.name==='w:comment'),ids=new Set<string>(),paraIds=new Set<string>(),expectedCommentsSha256=hash(xml)
 // 所有 comment 先做全局身份检查；复杂目标保留但不授权，重复身份不分配任何目标。
 for(const comment of comments){
  const id=attributes(comment)['w:id'];if(typeof id!=='string'||!/^(0|[1-9]\d{0,9})$/.test(id)||Number(id)>2147483647||ids.has(id))fail('docx_comment_id_ambiguous')
  ids.add(id)
  for(const match of comment.xml.matchAll(/\bw14:paraId\s*=\s*(?:"([^"]*)"|'([^']*)')/g)){
   const pid=(match[1]??match[2]).toUpperCase();if(!/^[0-9A-F]{8}$/.test(pid)||paraIds.has(pid))fail('docx_comment_para_id_ambiguous');paraIds.add(pid)
  }
 }
 const targets=comments.map((element,ordinal)=>{
  const a=attributes(element),expectedObjectSha256=hash(element.xml)
  let text='',relationshipIds:string[]=[],readOnlyReason:string|null=null
  try{({text,relationshipIds}=inspectStructure(element,rootAttrs))}catch(error){readOnlyReason=error instanceof Error?error.message:'docx_comment_structure_unsupported'}
  const target:CommentTextTarget={sourceId:source.sourceId,targetId:hash(JSON.stringify([source.sourceId,expectedCommentsSha256,ordinal,element.xml])),expectedCommentsSha256,expectedObjectSha256,originalCommentId:a['w:id'],ordinal,author:a['w:author']??'',date:a['w:date']??null,initials:a['w:initials']??null,text,relationshipIds,editableText:readOnlyReason===null,readOnlyReason}
  return{element,target}
 })
 return{xml,targets}
}
export function inspectCommentText(source:CommentTextSource):{commentTargets:CommentTextTarget[];commentReadOnlyReason:string|null}{
 try{return{commentTargets:readSource(source).targets.map(t=>t.target),commentReadOnlyReason:null}}
 catch(error){return{commentTargets:[],commentReadOnlyReason:error instanceof Error?error.message:'docx_comment_source_invalid'}}
}
function validXmlCharacters(text:string):boolean{
 for(const ch of text){const n=ch.codePointAt(0)!;if(!(n===9||n===10||n===13||n>=32&&n<=0xD7FF||n>=0xE000&&n<=0xFFFD||n>=0x10000&&n<=0x10FFFF))return false}
 return true
}
function validEntities(xml:string):boolean{
 let valid=true
 const stripped=xml.replace(/&([^;]*);/g,(_,entity:string)=>{
  if(['amp','lt','gt','quot','apos'].includes(entity))return ''
  const n=/^#x[0-9A-Fa-f]+$/.test(entity)?Number.parseInt(entity.slice(2),16):/^#[0-9]+$/.test(entity)?Number(entity.slice(1)):NaN
  if(!Number.isSafeInteger(n)||n<0||n>0x10FFFF||!validXmlCharacters(String.fromCodePoint(n)))valid=false
  return ''
 })
 return valid&&!stripped.includes('&')
}
function validText(text:unknown):text is string{
 return typeof text==='string'&&text.length<=65536&&!text.includes('\r')&&validXmlCharacters(text)
}
/** 整批身份/结构/文字先验证，再调用固定源文字 patch；绝不返回半份结果或修改 source。 */
export function resolveCommentText(source:CommentTextSource,operations:readonly CommentTextOperation[]):{xml:string}{
 const current=readSource(source),seen=new Set<string>()
 if(!Array.isArray(operations)||!operations.length||operations.length>200)fail('docx_comment_operations_invalid')
 const planned=operations.map(op=>{
  if(!op||Object.keys(op).sort().join(',')!=='expectedCommentsSha256,expectedObjectSha256,kind,sourceId,targetId,text'||op.kind!=='editCommentText'||op.sourceId!==source.sourceId||op.expectedCommentsSha256!==hash(current.xml)||!validText(op.text))fail('docx_comment_operation_invalid')
  const found=current.targets.find(t=>t.target.targetId===op.targetId)
  if(!found||found.target.expectedObjectSha256!==op.expectedObjectSha256||seen.has(op.targetId))fail('docx_comment_target_invalid')
  seen.add(op.targetId)
  if(!found.target.editableText)fail(found.target.readOnlyReason!)
  if(op.text.split('\n').length!==found.target.text.split('\n').length)fail('docx_comment_paragraph_count_unsupported')
  return{...found,text:op.text}
 })
 const patches=planned.map(p=>{const xml=patchParagraphTexts(p.element.xml,p.text);if(xml===null)fail('docx_comment_text_patch_unsupported');return{...p,xml}}).sort((a,b)=>b.element.start-a.element.start)
 let xml=current.xml
 for(const p of patches)xml=xml.slice(0,p.element.start)+p.xml+xml.slice(p.element.start+p.element.xml.length)
 return{xml}
}
