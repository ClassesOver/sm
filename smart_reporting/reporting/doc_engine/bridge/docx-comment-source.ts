/** 已授权原 bytes 的批注来源校验。文件/版本/scope 授权仍由调用宿主负责。
 * 不接受客户端 XML、part、保护声明；只支持标准布局，未知来源保守只读。
 */
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {XMLValidator} from 'fast-xml-parser'
import {assertZipInflatesWithinLimits,loadDocxZip} from '../packages/docx-engine/src/zip-load'
import {resolveRelationshipTargetPath} from '../packages/docx-engine/src/parse-package'
import {attrsOf,childrenOf,nameOf,xmlParser,type XNode} from '../packages/docx-engine/src/xml-utils'
import {inspectCommentText,resolveCommentText,type CommentTextOperation,type CommentTextTarget,type CommentTextSource} from './docx-comments'

const W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
const R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const P='http://schemas.openxmlformats.org/package/2006/relationships'
const CT='http://schemas.openxmlformats.org/package/2006/content-types'
const MAIN='word/document.xml',COMMENTS='word/comments.xml',SETTINGS='word/settings.xml'
const DOCRELS='word/_rels/document.xml.rels',COMMENTRELS='word/_rels/comments.xml.rels'
const hash=(value:string|Uint8Array)=>createHash('sha256').update(value).digest('hex')
const fail:(reason:string)=>never=(reason)=>{throw new Error('docx_comment_source_'+reason)}
const utf8=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true})
interface Rel {id:string;type:string;target:string;mode?:string}
export interface DocxCommentSourceInspection {
 sourceSha256:string;sourceId:string|null;commentTargets:CommentTextTarget[];commentReadOnlyReason:string|null
}

/** zip-gate 的扫描器未导出：这里只检查身份元数据，不复制解压器或 XML 框架。
 * 源 gate 先核验压缩/解压预算；本层收窄 ZIP32、唯一原 header 名、无 Unicode alias。
 */
export function assertZipIdentity(bytes:Uint8Array):void{
 const v=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength)
 const u16=(p:number)=>v.getUint16(p,true),u32=(p:number)=>v.getUint32(p,true)
 let end=-1
 for(let p=bytes.length-22;p>=Math.max(0,bytes.length-22-65535);p--)if(u32(p)===0x06054b50&&p+22+u16(p+20)===bytes.length){end=p;break}
 if(end<0||u16(end+4)||u16(end+6)||u16(end+8)!==u16(end+10))fail('zip_identity')
 const count=u16(end+10),offset=u32(end+16),size=u32(end+12),names=new Set<string>()
 if(count===65535||offset+size!==end)fail('zip_identity')
 const extras=(start:number,length:number)=>{
  const stop=start+length;if(stop>bytes.length)fail('zip_identity')
  for(let p=start;p<stop;){if(p+4>stop)fail('zip_identity');const id=u16(p),n=u16(p+2);if(id===0x7075||id===1||p+4+n>stop)fail('zip_alias_unsupported');p+=4+n}
 }
 let p=offset
 for(let i=0;i<count;i++){
  if(p+46>end||u32(p)!==0x02014b50)fail('zip_identity')
  const flags=u16(p+8),n=u16(p+28),extra=u16(p+30),comment=u16(p+32),local=u32(p+42),stop=p+46+n+extra+comment
  if(stop>end||local+30>offset||u32(local)!==0x04034b50||u16(p+34))fail('zip_identity')
  const raw=bytes.subarray(p+46,p+46+n)
  if(!(flags&0x800)&&raw.some(b=>b>=128))fail('zip_name_encoding')
  let name:string;try{name=utf8.decode(raw)}catch{fail('zip_name_encoding')}
  if(!name!||/[\\%:\x00-\x1f\x7f]/.test(name!)||name!.startsWith('/')||name!.split('/').some((s,index,all)=>s==='.'||s==='..'||!s&&index!==all.length-1)||names.has(name!.toLowerCase()))fail('zip_name_ambiguous')
  names.add(name!.toLowerCase())
  const ln=u16(local+26),le=u16(local+28)
  if(local+30+ln+le>offset||ln!==n||u16(local+6)!==flags||u16(local+8)!==u16(p+10)||!Buffer.from(raw).equals(Buffer.from(bytes.subarray(local+30,local+30+ln))))fail('zip_header_identity')
  extras(p+46+n,extra);extras(local+30+ln,le);p=stop
 }
 if(p!==end)fail('zip_identity')
}
function validCharacters(value:string):boolean{
 for(const c of value){const n=c.codePointAt(0)!;if(!(n===9||n===10||n===13||n>=32&&n<=0xd7ff||n>=0xe000&&n<=0xfffd||n>=0x10000&&n<=0x10ffff))return false}
 return true
}
export function parseCommentSourceXml(xml:string):XNode{
 if(!validCharacters(xml)||/<!|<\?(?!xml\s)/.test(xml)||XMLValidator.validate(xml)!==true)fail('xml_invalid')
 const entities=xml.replace(/&([^;]*);/g,(_,e:string)=>{
  if(['amp','lt','gt','quot','apos'].includes(e))return ''
  const n=/^#x[\da-f]+$/i.test(e)?parseInt(e.slice(2),16):/^#\d+$/.test(e)?Number(e.slice(1)):NaN
  if(!Number.isSafeInteger(n)||n>0x10ffff||!validCharacters(String.fromCodePoint(n)))fail('xml_entity_invalid')
  return ''
 });if(entities.includes('&'))fail('xml_entity_invalid')
 // 非 UTF-8 声明不能与原 UTF-8 bytes 身份混用。
 const encoding=xml.match(/^\uFEFF?\s*<\?xml\b[^?]*\bencoding\s*=\s*["']([^"']+)/i)?.[1]
 if(encoding&&!/^utf-8$/i.test(encoding))fail('xml_encoding')
 const roots=(xmlParser.parse(xml) as XNode[]).filter(n=>nameOf(n)&&!nameOf(n)!.startsWith('?'))
 if(roots.length!==1)fail('xml_invalid')
 const root=roots[0]!
 const visit=(node:XNode,inherited:Record<string,string>,depth:number)=>{
  if(depth>100)fail('xml_depth')
  const attrs=attrsOf(node),ns={...inherited}
  for(const [k,value] of Object.entries(attrs))if(k==='xmlns'||k.startsWith('xmlns:')){
   const prefix=k==='xmlns'?'':k.slice(6)
   if(depth&&prefix in inherited&&inherited[prefix]!==value)fail('namespace_rebound')
   if(prefix==='xml'&&value!=='http://www.w3.org/XML/1998/namespace')fail('namespace_invalid')
   ns[prefix]=value
  }
  const check=(q:string,attribute=false)=>{
   const parts=q.split(':');if(parts.length>2||parts.length===2&&!ns[parts[0]]&&parts[0]!=='xml')fail('namespace_invalid')
   if(attribute&&q==='xmlns')return
  }
  if(nameOf(node))check(nameOf(node)!)
  const expanded=new Set<string>()
  for(const k of Object.keys(attrs))if(k!=='xmlns'&&!k.startsWith('xmlns:')){
   check(k,true)
   const [prefix,local]=k.includes(':')?k.split(':'):['',k]
   const identity=JSON.stringify([prefix==='xml'?'http://www.w3.org/XML/1998/namespace':prefix?ns[prefix]:'',local])
   if(expanded.has(identity))fail('attribute_ambiguous')
   expanded.add(identity)
  }
  childrenOf(node).forEach(c=>{if(nameOf(c))visit(c,ns,depth+1)})
 }
 visit(root,{},0);return root
}
const parse=parseCommentSourceXml
function requireRoot(node:XNode,name:string,ns:string):void{
 if(nameOf(node)!==name||attrsOf(node)[name.includes(':')?'xmlns:'+name.split(':')[0]:'xmlns']!==ns)fail('namespace_unsupported')
}
function parseRelationships(xml:string):Rel[]{
 const root=parse(xml);requireRoot(root,'Relationships',P)
 const ids=new Set<string>()
 return childrenOf(root).filter(n=>nameOf(n)).map(node=>{
  const a=attrsOf(node)
  if(nameOf(node)!=='Relationship'||childrenOf(node).some(c=>nameOf(c))||Object.keys(a).some(k=>!['Id','Type','Target','TargetMode'].includes(k))||!a.Id||!a.Type||!a.Target||ids.has(a.Id)||a.TargetMode!==undefined&&!['Internal','External'].includes(a.TargetMode))fail('relationship_invalid')
  ids.add(a.Id);return{id:a.Id,type:a.Type,target:a.Target,mode:a.TargetMode}
 })
}
function onePart(rels:Rel[],type:string,source:string,path:string,optional=false):void{
 const matches=rels.filter(r=>r.type===R+'/'+type)
 if(optional&&!matches.length)return
 if(matches.length!==1||matches[0].mode==='External'||/[?#]/.test(matches[0].target)||resolveRelationshipTargetPath(source,matches[0].target)!==path)fail('relationship_part_ambiguous')
}
function safeLinkHref(value:string):boolean{
 // 与 edit-docx.ts 的既有规则保持一致；该脚本非可导入模块，不能从它 import。
 if(!value||value.length>4096||/[\s\x00-\x1f\x7f]/u.test(value))return false
 try{const u=new URL(value);if(u.protocol==='http:'||u.protocol==='https:')return /^https?:\/\//i.test(value)&&!!u.hostname&&!u.username&&!u.password;return u.protocol==='mailto:'&&!!u.pathname&&!value.slice(7).startsWith('//')}catch{return false}
}
export async function readTrustedDocxComments(bytes:Uint8Array,allowMissingComments=false){
 if(!(bytes instanceof Uint8Array)||!bytes.length||bytes.length>24*1024*1024)fail('bytes_invalid')
 const original=new Uint8Array(bytes)
 await assertZipInflatesWithinLimits(original,{maxParts:2000,maxPartBytes:8*1024*1024,maxTotalBytes:64*1024*1024})
 assertZipIdentity(original)
 const zip=await JSZip.loadAsync(original,{checkCRC32:true}),normalized=await loadDocxZip(original)
 const read=async(path:string)=>{
  const f=zip.file(path);if(!f)fail('part_missing')
  const raw=await f!.async('uint8array');if(raw.length>4*1024*1024)fail('xml_size')
  try{return utf8.decode(raw)}catch{fail('xml_encoding')}
 }
 for(const [path,file] of Object.entries(zip.files))if(!file.dir){
  const actual=await file.async('uint8array'),loaded=await normalized.file(path)?.async('uint8array')
  if(!loaded||!Buffer.from(actual).equals(Buffer.from(loaded)))fail('normalization_required')
 }
 const packageRels=parseRelationships(await read('_rels/.rels')),documentRels=parseRelationships(await read(DOCRELS))
 onePart(packageRels,'officeDocument','',MAIN);onePart(documentRels,'comments',MAIN,COMMENTS,allowMissingComments)
 const hasComments=!!zip.file(COMMENTS)
 if(hasComments!==documentRels.some(r=>r.type===R+'/comments'))fail('comments_ambiguous')
 const settingsRels=documentRels.filter(r=>r.type===R+'/settings')
 onePart(documentRels,'settings',MAIN,SETTINGS,true)
 if(!!zip.file(SETTINGS)!==!!settingsRels.length)fail('settings_ambiguous')
 // 所有实际关系文件都先做重复 Id / namespace / DTD / TargetMode 检查，不能让 Map 覆盖身份。
 for(const file of Object.values(zip.files))if(!file.dir&&file.name.endsWith('.rels'))parseRelationships(await read(file.name))
 const types=parse(await read('[Content_Types].xml'));requireRoot(types,'Types',CT)
 const overrides=new Map<string,string>(),defaults=new Map<string,string>()
 for(const node of childrenOf(types).filter(n=>nameOf(n))){
  const a=attrsOf(node),name=nameOf(node)
  if(name==='Override'){
   if(Object.keys(a).some(k=>!['PartName','ContentType'].includes(k))||!a.PartName?.startsWith('/')||!a.ContentType||overrides.has(a.PartName))fail('content_type_ambiguous')
   overrides.set(a.PartName,a.ContentType)
  }else if(name==='Default'){
   if(Object.keys(a).some(k=>!['Extension','ContentType'].includes(k))||!a.Extension||!a.ContentType||defaults.has(a.Extension.toLowerCase()))fail('content_type_ambiguous')
   defaults.set(a.Extension.toLowerCase(),a.ContentType)
  }else fail('content_type_invalid')
 }
 if(!hasComments&&overrides.has('/'+COMMENTS))fail('comments_ambiguous')
 for(const [path,kind] of [[MAIN,'document.main'],...(hasComments?[[COMMENTS,'comments']]:[]),...(settingsRels.length?[[SETTINGS,'settings']]:[])])if(overrides.get('/'+path)!=='application/vnd.openxmlformats-officedocument.wordprocessingml.'+kind+'+xml')fail('content_type_invalid')
 if(settingsRels.length){
  const settings=parse(await read(SETTINGS)),a=attrsOf(settings),q=nameOf(settings)!.split(':'),ns=q.length===2?a['xmlns:'+q[0]]:a.xmlns
  if(q.at(-1)!=='settings'||ns!==W)fail('settings_invalid')
  const walk=(node:XNode,inherited:Record<string,string>)=>{
   const attrs=attrsOf(node),namespaces={...inherited}
   for(const [k,v] of Object.entries(attrs))if(k==='xmlns'||k.startsWith('xmlns:'))namespaces[k==='xmlns'?'':k.slice(6)]=v
   const parts=(nameOf(node)??'').split(':'),prefix=parts.length===2?parts[0]:'',local=parts.at(-1)
   if(local==='documentProtection'){
    if(namespaces[prefix]!==W)fail('settings_invalid')
    const enforcement=Object.entries(attrs).find(([k])=>k.includes(':')&&k.split(':')[1]==='enforcement'&&namespaces[k.split(':')[0]]===W)?.[1]
    if(!enforcement||!['0','false','off'].includes(enforcement))fail('protected')
   }
   childrenOf(node).filter(c=>nameOf(c)).forEach(c=>walk(c,namespaces))
  };walk(settings,{})
 }
 const commentsXml=hasComments?await read(COMMENTS):'<w:comments xmlns:w="'+W+'"/>',documentXml=await read(MAIN),document=parse(documentXml)
 requireRoot(document,'w:document',W)
 const bodies=childrenOf(document).filter(n=>nameOf(n)==='w:body');if(bodies.length!==1)fail('anchor_story_ambiguous')
 const anchors=new Map<string,{kind:string;ordinal:number}[]>();let ordinal=0
 const scan=(node:XNode,path:string[],namespaces:Record<string,string>)=>{
  const a=attrsOf(node),ns={...namespaces},name=nameOf(node)??''
  for(const [k,v] of Object.entries(a))if(k==='xmlns'||k.startsWith('xmlns:'))ns[k==='xmlns'?'':k.slice(6)]=v
  const local=name.split(':').at(-1)!
  if(['commentRangeStart','commentRangeEnd','commentReference'].includes(local)){
   if(name!=='w:'+local||ns.w!==W||path.at(-1)!==(local==='commentReference'?'w:r':'w:p')||local==='commentReference'&&path.at(-2)!=='w:p'||childrenOf(node).length||!path.includes('w:body')||path.some(n=>!['w:document','w:body','w:p','w:r','w:tbl','w:tr','w:tc'].includes(n))||!/^\d+$/.test(a['w:id']??'')||Object.keys(a).some(k=>k!=='w:id'))fail('anchor_invalid')
   const id=a['w:id'],list=anchors.get(id)??[];list.push({kind:local,ordinal:ordinal++});anchors.set(id,list)
  }
  childrenOf(node).filter(c=>nameOf(c)).forEach(c=>scan(c,[...path,name],ns))
 };scan(document,[],{})
 // 不按路径或前缀拼写猜 story：其它 XML 中实际 Word namespace 的 marks 均只读。
 // content type 也覆盖不使用 .xml 扩展名的合法 XML part；未知扩展 XML 原字节保留。
 const storyPaths=new Set(documentRels.filter(rel=>rel.mode!=='External'&&['header','footer','footnotes','endnotes','glossaryDocument'].some(kind=>rel.type===R+'/'+kind)).map(rel=>resolveRelationshipTargetPath(MAIN,rel.target)))
 const hasWordMarker=(node:XNode,inherited:Record<string,string>):boolean=>{
  const namespaces={...inherited}
  for(const [key,value] of Object.entries(attrsOf(node)))if(key==='xmlns'||key.startsWith('xmlns:'))namespaces[key==='xmlns'?'':key.slice(6)]=value
  const qualified=nameOf(node)??'',split=qualified.indexOf(':'),prefix=split<0?'':qualified.slice(0,split),local=qualified.slice(split+1)
  if(namespaces[prefix]===W&&['commentRangeStart','commentRangeEnd','commentReference'].includes(local))return true
  return childrenOf(node).some(child=>hasWordMarker(child,namespaces))
 }
 for(const file of Object.values(zip.files))if(!file.dir&&![MAIN,COMMENTS,SETTINGS].includes(file.name)){
  const type=overrides.get('/'+file.name)??defaults.get(file.name.split('.').at(-1)!.toLowerCase())
  if(!storyPaths.has(file.name)&&!/\.xml$/i.test(file.name)&&type!=='application/xml'&&!type?.endsWith('+xml'))continue
  if(hasWordMarker(parse(await read(file.name)),{}))fail('anchor_story_ambiguous')
 }
 const commentRels=zip.file(COMMENTRELS)?parseRelationships(await read(COMMENTRELS)):[]
 const commentsRoot=parse(commentsXml)
 const hasUnsupportedLink=(node:XNode):boolean=>{
  const a=attrsOf(node)
  if(nameOf(node)==='w:hyperlink'&&(!a['r:id']||Object.keys(a).some(k=>!['r:id','w:history','w:tooltip','w:tgtFrame'].includes(k))))return true
  return childrenOf(node).some(hasUnsupportedLink)
 }
 const sourceSha256=hash(original),sourceId=hash(JSON.stringify([sourceSha256,COMMENTS,hash(await read(DOCRELS)),hash(zip.file(COMMENTRELS)?await read(COMMENTRELS):''),hash(documentXml),[...anchors]]))
 const source:CommentTextSource={sourceId,commentsXml,protectedDocument:false},inspection=inspectCommentText(source)
 if(inspection.commentReadOnlyReason)fail(inspection.commentReadOnlyReason)
 const commentNodes=childrenOf(commentsRoot).filter(n=>nameOf(n)==='w:comment')
 for(const target of inspection.commentTargets){
  const marks=anchors.get(target.originalCommentId)
  let reason:string|null=null
  if(!marks||marks.map(m=>m.kind).join(',')!=='commentRangeStart,commentRangeEnd,commentReference')reason='docx_comment_source_anchor_ambiguous'
  else if(hasUnsupportedLink(commentNodes[target.ordinal]))reason='docx_comment_source_internal_link_unsupported'
  else for(const id of target.relationshipIds){const rel=commentRels.find(r=>r.id===id);if(!rel||rel.type!==R+'/hyperlink'||rel.mode!=='External'||!safeLinkHref(rel.target)){reason='docx_comment_source_hyperlink_invalid';break}}
  if(reason){target.editableText=false;target.readOnlyReason=reason}
 }
 if([...anchors.keys()].some(id=>!inspection.commentTargets.some(t=>t.originalCommentId===id)))fail('anchor_orphan')
 return{zip,source,inspection,sourceSha256,sourceId,original,documentXml,anchors}
}

export async function inspectDocxCommentSource(authorizedBytes:Uint8Array):Promise<DocxCommentSourceInspection>{
 const sourceSha256=authorizedBytes instanceof Uint8Array?hash(authorizedBytes):''
 try{const s=await readTrustedDocxComments(authorizedBytes);return{sourceSha256:s.sourceSha256,sourceId:s.sourceId,...s.inspection}}
 catch(error){return{sourceSha256,sourceId:null,commentTargets:[],commentReadOnlyReason:error instanceof Error?error.message:'docx_comment_source_invalid'}}
}
/** 只返回内存输出；整批拒绝不会写文件，也不会修改调用者 bytes。 */
export async function patchDocxCommentSource(authorizedBytes:Uint8Array,operations:readonly CommentTextOperation[]):Promise<Uint8Array>{
 const s=await readTrustedDocxComments(authorizedBytes)
 if(!Array.isArray(operations))fail('operations_invalid')
 for(const op of operations){const target=s.inspection.commentTargets.find(t=>t.targetId===op?.targetId);if(!target?.editableText)fail(target?.readOnlyReason??'target_invalid')}
 const result=resolveCommentText(s.source,operations)
 if(result.xml===s.source.commentsXml)return s.original
 const before=new Map(await Promise.all(Object.values(s.zip.files).filter(f=>!f.dir).map(async f=>[f.name,await f.async('uint8array')] as const)))
 const originalParts=Object.keys(s.zip.files).sort().join('\n')
 s.zip.file(COMMENTS,result.xml,{createFolders:false})
 const bytes=await s.zip.generateAsync({type:'uint8array',compression:'DEFLATE'}),output=await JSZip.loadAsync(bytes,{checkCRC32:true})
 if(Object.keys(output.files).sort().join('\n')!==originalParts)fail('output_parts_changed')
 for(const [path,raw] of before){const actual=await output.file(path)!.async('uint8array'),expected=path===COMMENTS?Buffer.from(result.xml):raw;if(!Buffer.from(actual).equals(Buffer.from(expected)))fail('output_part_changed')}
 return bytes
}
