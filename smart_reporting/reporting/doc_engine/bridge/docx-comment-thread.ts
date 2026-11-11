/** 删除与解决仅修改已核验的源 XML 片段，保留其他批注、锚点和包内容。 */
import {createHash} from 'node:crypto'
import {attrsOf,childrenOf,nameOf,xmlParser,type XNode} from '../packages/docx-engine/src/xml-utils.ts'
import {resolveRelationshipTargetPath} from '../packages/docx-engine/src/parse-package.ts'
import {commentCreationXml as x,commentPackageIdentities} from './docx-comment-create.ts'
import {parseCommentSourceXml,readTrustedDocxComments} from './docx-comment-source.ts'
import type {CommentTextTarget} from './docx-comments.ts'

const MAIN='word/document.xml',COMMENTS='word/comments.xml',RELS='word/_rels/document.xml.rels',TYPES='[Content_Types].xml'
const W14='http://schemas.microsoft.com/office/word/2010/wordml'
const schemas={
 ex:{file:'commentsExtended.xml',rel:'2011/relationships/commentsExtended',type:'application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml',prefix:'w15',ns:'2012/wordml',root:'commentsEx',row:'commentEx'},
 ids:{file:'commentsIds.xml',rel:'2016/09/relationships/commentsIds',type:'application/vnd.ms-word.commentsIds+xml',prefix:'w16cid',ns:'2016/wordml/cid',root:'commentsIds',row:'commentId'},
 ext:{file:'commentsExtensible.xml',rel:'2018/08/relationships/commentsExtensible',type:'application/vnd.ms-word.commentsExtensible+xml',prefix:'w16cex',ns:'2018/wordml/cex',root:'commentsExtensible',row:'commentExtensible'},
}
const office='http://schemas.microsoft.com/office/'
const relType=(schema:typeof schemas.ex)=>office+schema.rel
const fail=(reason:string):never=>{throw new Error('docx_comment_thread_'+reason)}
const hex=(value:string|undefined)=>value&&/^[\da-f]{8}$/i.test(value)?value.toUpperCase():fail('metadata_identity')
const fragment=(raw:string)=>(xmlParser.parse(raw) as XNode[])[0]!
const namedChildren=(n:XNode)=>childrenOf(n).filter(child=>nameOf(child))
type Slice=ReturnType<typeof x.rootSlice>
type Edit={slice:Slice;value:string}
const remove=(slice:Slice):Edit=>({slice,value:''})

export interface CommentThreadTarget extends CommentTextTarget {
 parentId:string|null;done:boolean;canDelete:boolean;canResolve:boolean;threadReadOnlyReason:string|null
}
export interface CommentThreadModel {sourceSha256:string;sourceId:string|null;targets:CommentThreadTarget[];readOnlyReason:string|null}
type Identity=Pick<CommentTextTarget,'sourceId'|'targetId'|'expectedCommentsSha256'|'expectedObjectSha256'>
export type CommentThreadOperation=Identity&({kind:'deleteComment'}|{kind:'resolveComment';done:boolean})

async function context(bytes:Uint8Array){
 const s=await readTrustedDocxComments(bytes,true)
 const relXml=await s.zip.file(RELS)!.async('string'),typesXml=await s.zip.file(TYPES)!.async('string')
 const rels=namedChildren(parseCommentSourceXml(relXml)).map(attrsOf),types=namedChildren(parseCommentSourceXml(typesXml)).map(attrsOf)
 async function part(schema:typeof schemas.ex){
  const path='word/'+schema.file,matching=rels.filter(a=>a.Type===relType(schema)),declared=types.filter(a=>a.PartName==='/'+path||a.ContentType===schema.type)
  const aliases=rels.some(a=>a.Type!==relType(schema)&&(a.Type.endsWith('/'+schema.file.slice(0,-4))||a.TargetMode!=='External'&&resolveRelationshipTargetPath(MAIN,a.Target)===path))
  const file=s.zip.file(path)
  if(aliases||matching.length>1||declared.length>1||!!file!==!!matching.length||!!file!==!!declared.length||
    file&&(matching[0].TargetMode==='External'||/[?#]/.test(matching[0].Target)||resolveRelationshipTargetPath(MAIN,matching[0].Target)!==path||declared[0].PartName!=='/'+path||declared[0].ContentType!==schema.type))fail('metadata_part_identity')
  const name=schema.prefix+':'+schema.root
  if(!file)return{path,name,raw:null,rows:[] as Slice[]}
  const raw=await file.async('string'),root=parseCommentSourceXml(raw),rowName=schema.prefix+':'+schema.row
  const rootAttrs=attrsOf(root),namespace=office+'word/'+schema.ns
  if(nameOf(root)!==name||rootAttrs['xmlns:'+schema.prefix]!==namespace)fail('metadata_schema')
  const checkForeign=(node:XNode,inherited:Record<string,string>)=>{
   const attrs={...inherited,...attrsOf(node)},q=nameOf(node)!,colon=q.indexOf(':')
   const ns=attrs[colon<0?'xmlns':'xmlns:'+q.slice(0,colon)]??''
   if(!ns||ns===namespace||ns.includes('/wordml')||ns.includes('/wordprocessingml')||ns.includes('/markup-compatibility/'))fail('metadata_schema')
   for(const key of Object.keys(attrsOf(node))){
    if(/(?:paraId|paraIdParent|durableId)$/.test(key))fail('metadata_schema')
   }
   for(const child of namedChildren(node))checkForeign(child,attrs)
  }
  for(const child of namedChildren(root))if(nameOf(child)!==rowName)checkForeign(child,rootAttrs)
  return{path,name,raw,rows:x.children(x.rootSlice(raw,name)).filter(n=>n.name===rowName)}
 }
 const [ex,ids,ext]=await Promise.all([part(schemas.ex),part(schemas.ids),part(schemas.ext)])
 const comments=x.children(x.rootSlice(s.source.commentsXml,'w:comments'))
 // A different Word prefix or unknown direct node may conceal a comment identity.
 if(comments.some(n=>n.name!=='w:comment')||comments.length!==s.inspection.commentTargets.length)fail('comment_schema')
 const byPara=new Map<string,string>(),paras=new Map<string,{slice:Slice;id:string|null}>()
 const rootAttrs=attrsOf(parseCommentSourceXml(s.source.commentsXml))
 for(const target of s.inspection.commentTargets){
  const last=x.children(comments[target.ordinal]).filter(n=>n.name==='w:p').at(-1)
  if(!last)continue
  const parentAttrs=attrsOf(fragment(comments[target.ordinal].xml)),a=attrsOf(fragment(last.xml))
  const ns={...rootAttrs,...parentAttrs,...a}
  const keys=Object.keys(a).filter(k=>k.endsWith(':paraId')&&ns['xmlns:'+k.split(':')[0]]===W14)
  if(keys.length>1||keys.length===1&&keys[0]!=='w14:paraId'||a['w14:paraId']!==undefined&&ns['xmlns:w14']!==W14)fail('paragraph_identity')
  const id=a['w14:paraId']===undefined?null:hex(a['w14:paraId'])
  if(id){if(byPara.has(id))fail('paragraph_identity');byPara.set(id,target.originalCommentId)}
  paras.set(target.originalCommentId,{slice:last,id})
 }
 const records=new Map<string,{slice:Slice;parentId:string|null;done:boolean}>()
 for(const slice of ex.rows){
  const node=fragment(slice.xml),a=attrsOf(node),id=byPara.get(hex(a['w15:paraId']))
  const parent=a['w15:paraIdParent']===undefined?null:byPara.get(hex(a['w15:paraIdParent']))
  const done=a['w15:done']
  if(!id||records.has(id)||parent===undefined||parent===id||namedChildren(node).length||done!==undefined&&!['0','1','true','false','on','off'].includes(done))fail('parent_identity')
  records.set(id!,{slice,parentId:parent!,done:['1','true','on'].includes(done)})
 }
 // GenOffice 只建根和直接回复；嵌套与循环不能可靠投影为同一线程。
 for(const {parentId} of records.values())if(parentId!==null&&records.get(parentId)?.parentId)fail('parent_identity')
 const durable=new Map<string,{id:string;slice:Slice}>(),idRows=new Map<string,Slice>()
 for(const slice of ids.rows){
  const node=fragment(slice.xml),a=attrsOf(node),id=byPara.get(hex(a['w16cid:paraId'])),key=hex(a['w16cid:durableId'])
  if(!id||durable.has(key)||idRows.has(id)||namedChildren(node).length)fail('durable_identity')
  durable.set(key,{id:id!,slice});idRows.set(id!,slice)
 }
 const extRows=new Map<string,Slice>()
 for(const slice of ext.rows){
  const entry=durable.get(hex(attrsOf(fragment(slice.xml))['w16cex:durableId']))
  if(!entry||extRows.has(entry.id))fail('durable_identity')
  extRows.set(entry!.id,slice)
 }
 const anchorValid=(id:string)=>{
  const marks=s.anchors.get(id)?.map(m=>m.kind).join(',')??''
  return marks==='commentRangeStart,commentRangeEnd,commentReference'||marks==='commentReference'||!marks&&!!records.get(id)?.parentId
 }
 const replies=new Map<string,string[]>()
 for(const [id,{parentId}] of records)if(parentId!==null){
  const children=replies.get(parentId)??[];children.push(id);replies.set(parentId,children)
 }
 const thread=(id:string)=>[id,...replies.get(id)??[]]
 const targets:CommentThreadTarget[]=s.inspection.commentTargets.map(target=>{
  const id=target.originalCommentId,record=records.get(id),parentId=record?.parentId??null
  const anchor=thread(parentId??id).every(anchorValid)
  const para=paras.get(id)
  const resolve=anchor&&parentId===null&&!!para&&(!rootAttrs['xmlns:w14']||rootAttrs['xmlns:w14']===W14)
  return {...target,parentId,done:record?.done??false,canDelete:anchor,canResolve:resolve,
   threadReadOnlyReason:!anchor?'docx_comment_thread_anchor_ambiguous':parentId!==null?'请在根批注上解决或重新打开线程':!resolve?'docx_comment_thread_paragraph_unsupported':null}
 })
 return{...s,targets,ex,ids,ext,comments,records,paras,thread,relXml,rels,typesXml,idRows,extRows,rootAttrs}
}

export async function inspectDocxCommentThreads(bytes:Uint8Array):Promise<CommentThreadModel>{
 try{const s=await context(bytes);return{sourceSha256:s.sourceSha256,sourceId:s.sourceId,targets:s.targets,readOnlyReason:null}}
 catch(error){return{sourceSha256:createHash('sha256').update(bytes).digest('hex'),sourceId:null,targets:[],readOnlyReason:error instanceof Error?error.message:'docx_comment_thread_invalid'}}
}

function attribute(slice:Slice,key:string,value:string):Edit{
 const open=x.open(slice)
 // Lex the opening tag so an attribute-like string inside another quoted value is never edited.
 const attrs=/([^\s=<>]+)\s*=\s*(["'])(.*?)\2/gs
 for(const match of open.matchAll(attrs))if(match[1]===key){
  const offset=match.index!+match[0].indexOf(match[2])+1
  return {slice:{...slice,start:slice.start+offset,xml:match[3]},value}
 }
 const at=open.length-(open.endsWith('/>')?2:1)
 return {slice:{...slice,start:slice.start+at,xml:''},value:' '+key+'="'+value+'"'}
}
function apply(raw:string,edits:Edit[]){
 let end=raw.length
 for(const {slice,value} of edits.sort((a,b)=>b.slice.start-a.slice.start)){
  const {start,xml}=slice
  if(start+xml.length>end||raw.slice(start,start+xml.length)!==xml)fail('slice_identity')
  raw=raw.slice(0,start)+value+raw.slice(start+xml.length);end=start
 }
 return raw
}
function anchorEdits(raw:string,victims:Set<string>,anchors:Awaited<ReturnType<typeof context>>['anchors']):Edit[]{
 if(!victims.size)return[]
 const edits:Edit[]=[],counts=new Map<string,number>()
 const walk=(slice:Slice)=>{
  for(const child of x.children(slice)){
   if(['w:commentRangeStart','w:commentRangeEnd','w:commentReference'].includes(child.name)){
    const id=attrsOf(fragment(child.xml))['w:id']
    if(victims.has(id)){edits.push(remove(child));counts.set(id,(counts.get(id)??0)+1)}
   }else if(['w:body','w:tbl','w:tr','w:tc','w:p','w:r'].includes(child.name))walk(child)
  }
 }
 walk(x.rootSlice(raw,'w:document'))
 for(const id of victims)if((counts.get(id)??0)!==(anchors.get(id)?.length??0))fail('anchor_identity')
 return edits
}
export async function patchDocxCommentThreads(bytes:Uint8Array,operations:readonly CommentThreadOperation[]):Promise<Uint8Array>{
 const s=await context(bytes)
 if(!Array.isArray(operations)||!operations.length||operations.length>200)fail('operations')
 const targets=new Map(s.targets.map(t=>[t.targetId,t])),seen=new Set<string>(),deleted=new Set<string>(),resolved=new Map<string,boolean>()
 for(const op of operations){
  const keys=['kind','sourceId','targetId','expectedCommentsSha256','expectedObjectSha256']
  if(op?.kind==='resolveComment')keys.push('done')
  if(!op||typeof op!=='object'||Object.keys(op).sort().join('|')!==keys.sort().join('|')||op.sourceId!==s.sourceId||
     !(op.kind==='deleteComment'||op.kind==='resolveComment'&&typeof op.done==='boolean'))fail('operation')
  const target=targets.get(op.targetId)
  if(!target||op.expectedCommentsSha256!==target.expectedCommentsSha256||op.expectedObjectSha256!==target.expectedObjectSha256||
     (op.kind==='deleteComment'?!target.canDelete:!target.canResolve))fail('target_identity')
  for(const id of s.thread(target!.originalCommentId)){
   if(seen.has(id))fail('overlap')
   seen.add(id)
   if(op.kind==='deleteComment')deleted.add(id)
   else resolved.set(id,op.done)
  }
 }

 const commentEdits=s.targets.filter(t=>deleted.has(t.originalCommentId)).map(t=>remove(s.comments[t.ordinal]))
 const exEdits=[...deleted].flatMap(id=>s.records.has(id)?[remove(s.records.get(id)!.slice)]:[])
 const idEdits=[...deleted].flatMap(id=>s.idRows.has(id)?[remove(s.idRows.get(id)!)]:[])
 const extEdits=[...deleted].flatMap(id=>s.extRows.has(id)?[remove(s.extRows.get(id)!)]:[])
 let additions='',addedPara=false
 let usedHex:Set<string>|undefined,nextPara=1
 for(const [id,done] of resolved){
  const record=s.records.get(id)
  if(record){if(record.done!==done)exEdits.push(attribute(record.slice,'w15:done',done?'1':'0'));continue}
  if(!done)continue
  const p=s.paras.get(id)!
  let paraId=p.id
  if(!paraId){
   usedHex??=(await commentPackageIdentities(s.zip)).usedHex
   do{paraId=(nextPara++).toString(16).padStart(8,'0').toUpperCase()}while(usedHex.has(paraId))
   usedHex.add(paraId);addedPara=true
   commentEdits.push(attribute(p.slice,'w14:paraId',paraId))
  }
  additions+=x.xml([x.node('w15:commentEx',{'w15:paraId':paraId,'w15:done':'1'})])
 }
 const changed=new Map<string,string>()
 const update=(path:string,raw:string,edits:Edit[])=>{if(edits.length)changed.set(path,apply(raw,edits))}
 update(MAIN,s.documentXml,anchorEdits(s.documentXml,deleted,s.anchors))
 update(COMMENTS,s.source.commentsXml,commentEdits)
 if(addedPara&&!s.rootAttrs['xmlns:w14']){
  const current=changed.get(COMMENTS)!
  changed.set(COMMENTS,apply(current,[attribute(x.rootSlice(current,'w:comments'),'xmlns:w14',W14)]))
 }
 if(s.ex.raw)update(s.ex.path,s.ex.raw,exEdits)
 if(s.ids.raw)update(s.ids.path,s.ids.raw,idEdits)
 if(s.ext.raw)update(s.ext.path,s.ext.raw,extEdits)
 if(additions){
  const current=changed.get(s.ex.path)??s.ex.raw??x.xml([x.node(s.ex.name,{'xmlns:w15':office+'word/'+schemas.ex.ns})])
  changed.set(s.ex.path,x.append(current,s.ex.name,additions))
  if(!s.ex.raw){
   const ids=new Set(s.rels.map(r=>r.Id));let n=1;while(ids.has('rId'+n))n++
   changed.set(RELS,x.append(s.relXml,'Relationships',x.xml([x.node('Relationship',{Id:'rId'+n,Type:relType(schemas.ex),Target:schemas.ex.file})])))
   changed.set(TYPES,x.append(s.typesXml,'Types',x.xml([x.node('Override',{PartName:'/'+s.ex.path,ContentType:schemas.ex.type})])))
  }
 }
 if(!changed.size)return s.original
 for(const [path,raw] of changed){parseCommentSourceXml(raw);s.zip.file(path,raw,{createFolders:false})}
 const result=await s.zip.generateAsync({type:'uint8array',compression:'DEFLATE'}),after=await context(result)
 if(after.targets.length!==s.targets.length-deleted.size||after.targets.some(target=>deleted.has(target.originalCommentId))||
   s.targets.some(before=>!deleted.has(before.originalCommentId)&&!after.targets.some(target=>
    target.originalCommentId===before.originalCommentId&&target.parentId===before.parentId&&target.done===(resolved.get(before.originalCommentId)??before.done))))fail('output_identity')
 return result
}
