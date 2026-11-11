/** 仅为固定源经典批注补来源校验；部件读写仍委托原引擎。 */
import {XMLParser, XMLValidator} from 'fast-xml-parser'
import {addSlideComment, deleteSlideComment, getSlideComments, type OpenedPptx, type SlideComment} from '@genoffice/pptx-engine'
import {relsPathFor, resolveTarget, type PackageArchive} from '../packages/pptx-engine/src/zip.ts'
import {unescapeXml} from '../packages/pptx-engine/src/notes.ts'

const base='http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
const commentsType=base+'comments', authorsType=base+'commentAuthors'
const ns='http://schemas.openxmlformats.org/presentationml/2006/main'
const authorsPath='ppt/commentAuthors.xml'
const parser=new XMLParser({ignoreAttributes:false,parseTagValue:false,parseAttributeValue:false,trimValues:false,processEntities:false})
const list=(value:any):any[]=>value===undefined?[]:Array.isArray(value)?value:[value]
const integer=(value:unknown):value is number=>typeof value==='number'&&Number.isSafeInteger(value)&&value>=0
const numeric=(value:unknown):boolean=>typeof value==='string'&&/^\d+$/.test(value)&&integer(Number(value))
function xmlRoot(xml:string|null,name:string):any {
 if(!xml||/<!DOCTYPE|<!ENTITY/.test(xml)||XMLValidator.validate(xml)!==true)throw Error('批注相关 XML 损坏或含不支持的实体声明')
 const doc=parser.parse(xml),root=doc[name]
 if(!root||typeof root!=='object'||Array.isArray(root))throw Error('批注相关 XML 根结构无法可靠识别')
 return root
}
function classicXmlSafe(xml:string){
 if(/<!--|<!\[CDATA\[/.test(xml)||[...xml.matchAll(/xmlns:p\s*=\s*["']([^"']*)["']/g)].some(match=>match[1]!==ns))throw Error('经典批注含命名空间重绑定或原引擎无法安全读取的 XML 结构')
}
function relationships(archive:PackageArchive,path:string){
 const xml=archive.readText(relsPathFor(path));if(xml===null)return []
 const root=xmlRoot(xml,'Relationships')
 if(root['@_xmlns']!=='http://schemas.openxmlformats.org/package/2006/relationships'||[...xml.matchAll(/xmlns\s*=\s*["']([^"']*)["']/g)].some(match=>match[1]!==root['@_xmlns']))throw Error('批注关系命名空间无法可靠识别')
 if(!xml.includes('</Relationships>'))throw Error('来源关系容器暂不支持原引擎安全追加批注')
 const rels=list(root.Relationship),ids=new Set<string>()
 for(const r of rels){if(!r||typeof r!=='object'||typeof r['@_Id']!=='string'||!r['@_Id']||ids.has(r['@_Id'])||typeof r['@_Type']!=='string'||typeof r['@_Target']!=='string'||!r['@_Target'])throw Error('批注来源含损坏或重复的关系身份');ids.add(r['@_Id'])}
 return rels
}
function classicTarget(path:string,rel:any){
 if(rel['@_TargetMode']!==undefined)throw Error('批注来源使用外部或不支持的关系模式')
 const target=resolveTarget(path,rel['@_Target'])
 if(!target||target.startsWith('/')||target.split('/').includes('..')||/[?#\\]/.test(target))throw Error('批注关系目标路径无法核验')
 return target
}
export interface ClassicComments {items:SlideComment[];readOnlyReason:string|null}
export type ClassicCommentEdit={slideIndex:number;kind:'add';clientId:string;text:string}|{slideIndex:number;kind:'delete';authorId:number;idx:number}

/** 宽松源读取不能把未知来源当空列表；只有完整证明原引擎能原样寻址时开放修改。 */
export function inspectClassicComments(opened:OpenedPptx):ClassicComments[]{
 const {archive}=opened,output:ClassicComments[]=opened.deck.slides.map(()=>({items:[],readOnlyReason:null}))
 const rejectAll=(reason:string)=>output.forEach(item=>{item.readOnlyReason??=reason})
 try{
  const presentationRels=relationships(archive,'ppt/presentation.xml')
  const types=xmlRoot(archive.readText('[Content_Types].xml'),'Types'),overrides=list(types.Override)
  if(types['@_xmlns']!=='http://schemas.openxmlformats.org/package/2006/content-types')throw Error('批注内容类型命名空间无法核验')
  const modern=overrides.some(r=>/comment|person/i.test(String(r['@_ContentType']))&&!['application/vnd.openxmlformats-officedocument.presentationml.comments+xml','application/vnd.openxmlformats-officedocument.presentationml.commentAuthors+xml'].includes(r['@_ContentType']))
  if(modern||presentationRels.some(r=>/comment|person/i.test(r['@_Type'])&&r['@_Type']!==authorsType))rejectAll('来源含现代或未知批注格式，经典批注暂仅可查看')
  const authorRels=presentationRels.filter(r=>r['@_Type']===authorsType),authors=new Map<number,{name:string;initials:string;lastIdx:number}>()
  if(!authorRels.length&&overrides.some(r=>r['@_ContentType']==='application/vnd.openxmlformats-officedocument.presentationml.commentAuthors+xml'))throw Error('批注作者内容类型存在但作者关系缺失')
  if(authorRels.length||archive.has(authorsPath)){
   if(authorRels.length!==1||classicTarget('ppt/presentation.xml',authorRels[0])!==authorsPath)throw Error('批注作者关系缺失、重复或目标不受支持')
   const xml=archive.readText(authorsPath),root=xmlRoot(xml,'p:cmAuthorLst')
   classicXmlSafe(xml!)
   if(root['@_xmlns:p']!==ns||!xml!.includes('</p:cmAuthorLst>'))throw Error('经典批注作者表结构暂不支持安全修改')
   const definitions=[...xml!.matchAll(/<p:cmAuthor\b([^>]*)\/>/g)],entries=list(root['p:cmAuthor'])
   if(entries.length!==definitions.length)throw Error('经典批注作者表含无法完整读取的定义')
   for(const [index,entry] of entries.entries()){
    const raw=definitions[index]![1]!,id=entry['@_id'],last=entry['@_lastIdx']
    if(!numeric(id)||!numeric(last)||Number(id)>=Number.MAX_SAFE_INTEGER||Number(last)>Number.MAX_SAFE_INTEGER-500||authors.has(Number(id))||typeof entry['@_name']!=='string'||typeof entry['@_initials']!=='string'||!raw.includes('id="'+id+'"')||!raw.includes('lastIdx="'+last+'"')||unescapeXml(/\bname="([^"]*)"/.exec(raw)?.[1]??'')!==unescapeXml(entry['@_name'])||unescapeXml(/\binitials="([^"]*)"/.exec(raw)?.[1]??'')!==unescapeXml(entry['@_initials']))throw Error('经典批注作者身份重复、损坏或原引擎无法完整读取')
    authors.set(Number(id),{name:unescapeXml(entry['@_name']),initials:unescapeXml(entry['@_initials']),lastIdx:Number(last)})
   }
  }
  const ownerPaths=new Map<string,number[]>(),usedParts=new Set<string>()
  const contentType=(path:string,type:string)=>overrides.filter(r=>r['@_PartName']==='/'+path&&r['@_ContentType']===type).length===1&&overrides.filter(r=>r['@_PartName']==='/'+path).length===1
  if(authorRels.length&&!contentType(authorsPath,'application/vnd.openxmlformats-officedocument.presentationml.commentAuthors+xml'))throw Error('经典批注作者内容类型缺失或歧义')
  for(const [index,slide] of opened.deck.slides.entries()){
   const item=output[index]!
   try{
    const rels=relationships(archive,slide.path),classic=rels.filter(r=>r['@_Type']===commentsType)
    if(rels.some(r=>/comment/i.test(r['@_Type'])&&r['@_Type']!==commentsType))item.readOnlyReason??='此页含现代或未知批注关系，暂仅可查看'
    if(classic.length>1)throw Error('此页经典批注关系重复，无法唯一定位来源')
    if(!classic.length)continue
    const path=classicTarget(slide.path,classic[0]);usedParts.add(path);ownerPaths.set(path,[...(ownerPaths.get(path)??[]),index])
    if(!contentType(path,'application/vnd.openxmlformats-officedocument.presentationml.comments+xml'))throw Error('经典批注部件内容类型缺失或歧义')
    const xml=archive.readText(path),root=xmlRoot(xml,'p:cmLst')
    classicXmlSafe(xml!)
    if(root['@_xmlns:p']!==ns||!xml!.includes('</p:cmLst>'))throw Error('经典批注容器结构暂不支持安全修改')
    const definitions=[...xml!.matchAll(/<p:cm\b([^>]*)>([\s\S]*?)<\/p:cm>/g)],entries=list(root['p:cm']),read=getSlideComments(archive,slide.path),seen=new Set<string>()
    if(entries.length!==definitions.length||entries.length!==read.length)throw Error('经典批注包含无法完整读取的条目')
    for(const [offset,entry] of entries.entries()){
     const cm=read[offset]!,raw=definitions[offset]![1]!,a=authors.get(cm.authorId),key=cm.authorId+':'+cm.idx
     if(!numeric(entry['@_authorId'])||!numeric(entry['@_idx'])||!raw.includes('authorId="'+entry['@_authorId']+'"')||!raw.includes('idx="'+entry['@_idx']+'"')||!a||seen.has(key)||cm.authorId!==Number(entry['@_authorId'])||cm.idx!==Number(entry['@_idx'])||cm.idx>a.lastIdx||typeof entry['p:text']!=='string'||unescapeXml(entry['p:text'])!==cm.text||typeof entry['@_dt']!=='string'||entry['@_dt']!==cm.dt||!Number.isFinite(Date.parse(cm.dt))||cm.author!==a.name||cm.initials!==a.initials)throw Error('经典批注作者、索引、时间或正文损坏或存在歧义')
     seen.add(key);item.items.push(cm)
    }
    if(Object.keys(root).some(k=>!k.startsWith('@_')&&!['p:cm','#text'].includes(k)))item.readOnlyReason??='经典批注容器含未知扩展，暂仅可查看以保留原始 XML'
   }catch(error){item.readOnlyReason=error instanceof Error?error.message:'此页批注无法完整读取'}
  }
  for(const owners of ownerPaths.values())if(owners.length>1)for(const index of owners)output[index]!.readOnlyReason='经典批注部件被多页共享，无法唯一定位来源'
  if(overrides.some(r=>r['@_ContentType']==='application/vnd.openxmlformats-officedocument.presentationml.comments+xml'&&!usedParts.has(String(r['@_PartName']).slice(1)))||[...archive.entries.keys()].some(path=>/^ppt\/comments\/.*\.xml$/.test(path)&&!usedParts.has(path)))rejectAll('来源含未能归属页面的批注部件，暂仅可查看')
 }catch(error){rejectAll(error instanceof Error?error.message:'批注来源无法完整读取')}
 return output
}

export function validateClassicCommentEdits(opened:OpenedPptx,raw:unknown,author:unknown,deletedSlides:unknown=[]):ClassicCommentEdit[]{
 if(raw===undefined)return []
 if(!Array.isArray(raw)||raw.length>500)throw Error('comment_edits_invalid')
 const source=inspectClassicComments(opened),ids=new Set<string>(),deletions=new Set<string>(),deleted=new Set(Array.isArray(deletedSlides)?deletedSlides:[])
 for(const op of raw){
  if(!op||typeof op!=='object'||Array.isArray(op)||!integer(op.slideIndex)||op.slideIndex>=source.length||deleted.has(op.slideIndex))throw Error('comment_slide_source_invalid')
  if(source[op.slideIndex]!.readOnlyReason)throw Error(source[op.slideIndex]!.readOnlyReason!)
  if(op.kind==='add'){
   if(Object.keys(op).sort().join()!=='clientId,kind,slideIndex,text'||author!=='用户'||typeof op.clientId!=='string'||!/^[A-Za-z0-9_-]{1,128}$/.test(op.clientId)||ids.has(op.clientId)||typeof op.text!=='string'||!op.text.trim()||op.text.length>10000||[...op.text].some(c=>{const n=c.codePointAt(0)!;return !(n===9||n===10||n===13||n>=32&&n<=0xd7ff||n>=0xe000&&n<=0xfffd||n>=0x10000&&n<=0x10ffff)}))throw Error('comment_add_invalid')
   ids.add(op.clientId)
  }else if(op.kind==='delete'){
   const key=op.slideIndex+':'+op.authorId+':'+op.idx
   if(Object.keys(op).sort().join()!=='authorId,idx,kind,slideIndex'||!integer(op.authorId)||!integer(op.idx)||deletions.has(key)||source[op.slideIndex]!.items.filter(cm=>cm.authorId===op.authorId&&cm.idx===op.idx).length!==1)throw Error('comment_delete_source_invalid')
   deletions.add(key)
  }else throw Error('comment_edit_kind_invalid')
 }
 return structuredClone(raw)
}

export function applyClassicCommentEdits(opened:OpenedPptx,edits:ClassicCommentEdit[],sourcePaths:readonly string[],author:unknown){
 for(const op of edits){
  const index=opened.deck.slides.findIndex(slide=>slide.path===sourcePaths[op.slideIndex])
  if(index<0)throw Error('comment_source_slide_missing')
  if(op.kind==='add'){const result=addSlideComment(opened,index,{author:author as string,text:op.text});if(!result||!integer(result.authorId)||!integer(result.idx))throw Error('comment_add_failed')}
  else if(!deleteSlideComment(opened,index,op))throw Error('comment_delete_failed')
 }
}
