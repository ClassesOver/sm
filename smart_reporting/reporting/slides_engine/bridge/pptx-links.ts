/** 对象超链接的保守来源校验；关系及OOXML修改完全交给固定源setElementLink。 */
import {XMLParser,XMLValidator} from 'fast-xml-parser'
import {elementSpid,getElementLink,isConnectorXml,setElementLink,type LinkTarget,type OpenedPptx,type SlideElement} from '@genoffice/pptx-engine'
import {relsPathFor,resolveTarget} from '../packages/pptx-engine/src/zip.ts'
export type LinkEdit={slideIndex:number;elementId:string;target:{kind:'url';url:string}|{kind:'slide';slideIndex:number}|null}
export type PreparedLinkEdit={sourcePath:string;spid:number;sourceType:SlideElement['type'];target:{kind:'url';url:string}|{kind:'slide';targetPath:string}|null}
export type LinkCapabilities={elementLink:LinkTarget|null;linkEditable:boolean;linkReason:string|null}
type Conflicts={deletedSlides?:readonly number[];deletions?:readonly {slideIndex:number;elementId:string}[];groupEdits?:readonly {slideIndex:number}[];newSlides?:readonly {duplicateOf?:number;layoutFrom?:number;withLayout?:string}[]}
const parser=new XMLParser({ignoreAttributes:false,parseTagValue:false,parseAttributeValue:false,trimValues:false})
const base='http://schemas.openxmlformats.org/officeDocument/2006/relationships/',slideAction='ppaction://hlinksldjump'
const namespaces={p:'http://schemas.openxmlformats.org/presentationml/2006/main',a:'http://schemas.openxmlformats.org/drawingml/2006/main',r:base.slice(0,-1)}
const record=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
function fail(reason:string):never{throw Error(reason)}
function fields(v:unknown,keys:string[]):asserts v is Record<string,unknown>{if(!record(v)||Object.keys(v).sort().join()!==[...keys].sort().join())fail('链接字段结构无效')}
function url(value:unknown):string{
 if(typeof value!=='string'||!value.trim()||value.trim().length>2048||/[\u0000-\u001f\u007f-\u009f\\]/.test(value))fail('链接网址无效或超过2048字符')
 const text=value.trim();if(/\s/.test(text))fail('链接网址不能包含空白字符')
 let parsed:URL;try{parsed=new URL(text)}catch{return fail('链接网址必须是完整的HTTP、HTTPS或mailto地址')}
 if(!['http:','https:','mailto:'].includes(parsed.protocol)||(['http:','https:'].includes(parsed.protocol)&&!/^https?:\/\//i.test(text))||(parsed.protocol==='mailto:'&&!parsed.pathname))fail('链接仅支持HTTP、HTTPS或mailto地址')
 return text
}
function xmlRoot(xml:string|null,name:string):any{
 if(!xml||/<!DOCTYPE|<!ENTITY|<!--|<!\[CDATA\[|<mc:AlternateContent\b/.test(xml)||XMLValidator.validate(xml)!==true)fail('链接来源XML无法完整识别')
 for(const match of xml.matchAll(/xmlns:(p|a|r)\s*=\s*['"]([^'"]*)['"]/g))if(namespaces[match[1] as keyof typeof namespaces]!==match[2])fail('链接来源命名空间无法核验')
 const node=parser.parse(xml)[name];if(!record(node))fail('链接来源XML根结构无法识别');return node
}
function uniqueSlide(opened:OpenedPptx,path:string):number{
 const matches=opened.deck.slides.flatMap((slide,i)=>slide.path===path?[i]:[])
 if(!/^ppt\/slides\/[^/]+[.]xml$/.test(path)||matches.length!==1||!opened.archive.readBytes(path))fail('链接来源或目标页面身份不唯一')
 return matches[0]!
}
function relationships(opened:OpenedPptx,path:string):Map<string,any>{
 const xml=opened.archive.readText(relsPathFor(path)),node=xmlRoot(xml,'Relationships'),ns='http://schemas.openxmlformats.org/package/2006/relationships'
 if(node['@_xmlns']!==ns||!xml!.includes('</Relationships>')||[...xml!.matchAll(/xmlns\s*=\s*['"]([^'"]*)['"]/g)].some(m=>m[1]!==ns)||Object.keys(node).some(k=>!['@_xmlns','Relationship'].includes(k)))fail('链接来源关系容器不支持安全追加')
 const rows=node.Relationship===undefined?[]:Array.isArray(node.Relationship)?node.Relationship:[node.Relationship],map=new Map<string,any>(),engine=opened.archive.readRels(path)
 for(const row of rows){
  if(!record(row)||typeof row['@_Id']!=='string'||!row['@_Id']||map.has(row['@_Id'])||typeof row['@_Type']!=='string'||!row['@_Type']||typeof row['@_Target']!=='string'||!row['@_Target']||Object.keys(row).some(k=>!['@_Id','@_Type','@_Target','@_TargetMode'].includes(k)))fail('链接来源关系重复或无法完整读取')
  const parsed=engine.get(row['@_Id']);if(!parsed||parsed.type!==row['@_Type']||parsed.target!==row['@_Target']||parsed.targetMode!==row['@_TargetMode'])fail('链接关系与原引擎读取结果不一致')
  map.set(row['@_Id'],row)
 }
 return map
}
function source(opened:OpenedPptx,slideIndex:number,elementId:string):{element:SlideElement;link:LinkTarget|null}{
 const slide=opened.deck.slides[slideIndex];if(!Number.isInteger(slideIndex)||slideIndex<0||!slide)fail('链接来源页不存在')
 uniqueSlide(opened,slide.path)
 if(xmlRoot(slide.originalXml,'p:sld')['@_xmlns:p']!==namespaces.p)fail('链接来源页面命名空间无法核验')
 const elements=slide.elements.filter(e=>e.id===elementId);if(elements.length!==1)fail('链接来源对象身份不唯一')
 const element=elements[0]!,xml=element.anchor.originalXml
 if(!['text','shape','picture'].includes(element.type)||element.placeholder||isConnectorXml(xml)||/<p:ph\b|<a:(?:videoFile|audioFile|scene3d|sp3d)\b|model3d|svgBlip/.test(xml)||(element.type==='picture'&&(element.media||element.model3d)))fail('仅普通顶层文字、形状和静态图片可编辑对象链接')
 const node=xmlRoot(xml,element.type==='picture'?'p:pic':'p:sp'),nv=node[element.type==='picture'?'p:nvPicPr':'p:nvSpPr'],own=nv?.['p:cNvPr'],spid=elementSpid(element)
 if(!record(own)||!Number.isSafeInteger(spid)||spid!<=0||String(spid)!==own['@_id']||slide.elements.filter(e=>elementSpid(e)===spid).length!==1||(xml.match(/<p:cNvPr\b/g)??[]).length!==1)fail('链接来源对象标识无法唯一核验')
 const click=own['a:hlinkClick'],count=(xml.match(/<a:hlinkClick\b/g)??[]).length
 if(count!==(click===undefined?0:1))fail('对象含段内或歧义链接，暂仅可读')
 const rels=relationships(opened,slide.path)
 if(click===undefined)return {element,link:null}
 if(!record(click)||Object.keys(click).some(k=>!['@_xmlns:r','@_r:id','@_action','@_tooltip'].includes(k))||typeof click['@_r:id']!=='string'||!/^rId\d+$/.test(click['@_r:id']))fail('来源链接含命名动作、声音或不支持的属性')
 const rel=rels.get(click['@_r:id']);if(!rel)fail('来源链接关系缺失')
 if(rel['@_Type']===base+'hyperlink'){
  if(rel['@_TargetMode']!=='External'||click['@_action']!==undefined)fail('来源网址链接关系或动作无效')
  url(rel['@_Target'])
 }else if(rel['@_Type']===base+'slide'){
  if(rel['@_TargetMode']!==undefined||click['@_action']!==slideAction||/[?#\\]/.test(rel['@_Target']))fail('来源页跳转关系或动作无效')
  uniqueSlide(opened,resolveTarget(slide.path,rel['@_Target']))
 }else fail('来源链接关系类型暂不支持')
 const link=getElementLink(opened,slideIndex,elementId);if(!link)fail('来源链接无法由原引擎完整读取')
 return {element,link}
}
export function inspectLinkCapabilities(opened:OpenedPptx,slideIndex:number,elementId:string):LinkCapabilities{
 try{return {elementLink:source(opened,slideIndex,elementId).link,linkEditable:true,linkReason:null}}
 catch(cause){return {elementLink:null,linkEditable:false,linkReason:cause instanceof Error?cause.message:'来源链接无法安全编辑'}}
}
export function prepareLinkEdits(opened:OpenedPptx,input:unknown,conflicts:Conflicts={}):PreparedLinkEdit[]{
 if(input===undefined)return []
 if(!Array.isArray(input)||input.length>50)fail('链接修改批次无效或超过50项')
 const seen=new Set<string>(),result:PreparedLinkEdit[]=[]
 for(const item of input){
  fields(item,['slideIndex','elementId','target'])
  if(typeof item.slideIndex!=='number'||!Number.isInteger(item.slideIndex)||item.slideIndex<0||item.slideIndex>=opened.deck.slides.length||typeof item.elementId!=='string'||!item.elementId.length||item.elementId.length>200)fail('链接来源对象无效')
  const index=item.slideIndex,key=index+':'+item.elementId
  if(seen.has(key)||conflicts.deletedSlides?.includes(index)||conflicts.deletions?.some(d=>d.slideIndex===index&&d.elementId===item.elementId)||conflicts.groupEdits?.some(g=>g.slideIndex===index)||conflicts.newSlides?.some(s=>s.duplicateOf===index))fail('链接来源重复、被删除、组合或复制冲突')
  seen.add(key)
  const current=source(opened,index,item.elementId),sourcePath=opened.deck.slides[index]!.path
  let target:PreparedLinkEdit['target']=null
  if(item.target!==null){
   if(!record(item.target))fail('链接目标无效')
   if(item.target.kind==='url'){fields(item.target,['kind','url']);target={kind:'url',url:url(item.target.url)}}
   else if(item.target.kind==='slide'){
    fields(item.target,['kind','slideIndex']);const to=item.target.slideIndex
    if(typeof to!=='number'||!Number.isInteger(to)||to<0||to>=opened.deck.slides.length||conflicts.deletedSlides?.includes(to)||conflicts.newSlides?.some(s=>s.duplicateOf===to))fail('链接跳转目标页不存在、已删除或复制冲突')
    const targetPath=opened.deck.slides[to]!.path;uniqueSlide(opened,targetPath);target={kind:'slide',targetPath}
   }else fail('链接仅支持网址、页跳转或清除')
  }
  result.push({sourcePath,spid:elementSpid(current.element)!,sourceType:current.element.type,target})
 }
 return result
}
function resolvePrepared(opened:OpenedPptx,item:PreparedLinkEdit){
 const slideIndex=uniqueSlide(opened,item.sourcePath),elements=opened.deck.slides[slideIndex]!.elements.filter(e=>elementSpid(e)===item.spid)
 if(elements.length!==1||elements[0]!.type!==item.sourceType)fail('链接来源对象在编辑后发生变化')
 const current=source(opened,slideIndex,elements[0]!.id),target:LinkEdit['target']=item.target?.kind==='slide'?{kind:'slide',slideIndex:uniqueSlide(opened,item.target.targetPath)}:item.target
 return {slideIndex,element:current.element,link:current.link,target}
}
export function applyLinkEdits(opened:OpenedPptx,prepared:readonly PreparedLinkEdit[]):void{
 // 先核验全部当前身份；首项不能因后项身份失效而先行修改。
 for(const item of prepared)resolvePrepared(opened,item)
 for(const item of prepared){
  const current=resolvePrepared(opened,item),a=current.link,b=current.target
  if(a===null&&b===null||(a?.kind==='url'&&b?.kind==='url'&&a.url===b.url)||(a?.kind==='slide'&&b?.kind==='slide'&&a.slideIndex===b.slideIndex))continue
  if(!setElementLink(opened,current.slideIndex,current.element.id,b))fail('原引擎未能应用链接修改')
 }
}
