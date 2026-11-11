/** 现有根线程回复：沿用原 bytes 身份与范围，commentsEx 保存真实父关联。 */
import {createHash} from 'node:crypto'
import {attrsOf,childrenOf,nameOf,xmlParser,type XNode} from '../packages/docx-engine/src/xml-utils.ts'
import {resolveRelationshipTargetPath} from '../packages/docx-engine/src/parse-package.ts'
import {parseCommentSourceXml,readTrustedDocxComments} from './docx-comment-source.ts'
import type {CommentTextTarget} from './docx-comments.ts'
import {commentCreationXml as x,commentPackageIdentities,patchDocxCommentCreation,readDocxCommentCreationSource,type CommentCreationRange} from './docx-comment-create.ts'
const W14='http://schemas.microsoft.com/office/word/2010/wordml',W15='http://schemas.microsoft.com/office/word/2012/wordml'
const EX='word/commentsExtended.xml',COMMENTS='word/comments.xml',RELS='word/_rels/document.xml.rels'
const EX_REL='http://schemas.microsoft.com/office/2011/relationships/commentsExtended',EX_TYPE='application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml'
const hash=(v:Uint8Array)=>createHash('sha256').update(v).digest('hex')
const fail=(reason:string):never=>{throw new Error('docx_comment_reply_'+reason)}
const fragment=(raw:string)=>(xmlParser.parse(raw) as XNode[])[0]
const hex=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{8}$/i.test(v)
export interface CommentReplyTarget extends CommentTextTarget {parentId:string|null;canReply:boolean;replyReadOnlyReason:string|null}
export interface CommentReplyModel {sourceSha256:string;sourceId:string|null;targets:CommentReplyTarget[];readOnlyReason:string|null}
export interface CommentReplyOperation {kind:'replyComment';sourceId:string;targetId:string;expectedCommentsSha256:string;expectedObjectSha256:string;clientId:string;author:string;date:string;text:string}
async function context(bytes:Uint8Array){
 const s=await readDocxCommentCreationSource(bytes),comments=x.children(x.rootSlice(s.source.commentsXml,'w:comments')).filter(n=>n.name==='w:comment')
 const allRels=childrenOf(parseCommentSourceXml(await s.zip.file(RELS)!.async('string')))
 if(allRels.some(n=>{const a=attrsOf(n);return a.TargetMode!=='External'&&a.Target&&resolveRelationshipTargetPath('word/document.xml',a.Target)===EX&&a.Type!==EX_REL}))fail('extended_part_identity')
 const rels=allRels.filter(n=>attrsOf(n).Type===EX_REL)
 const types=childrenOf(parseCommentSourceXml(await s.zip.file('[Content_Types].xml')!.async('string'))).filter(n=>attrsOf(n).PartName==='/'+EX)
 const part=s.zip.file(EX)
 if(rels.length>1||types.length>1||!!part!==!!rels.length||!!part!==!!types.length||part&&(attrsOf(rels[0]).Target!=='commentsExtended.xml'||attrsOf(rels[0]).TargetMode==='External'||attrsOf(types[0]).ContentType!==EX_TYPE))fail('extended_part_identity')
 const byPara=new Map<string,CommentTextTarget>(),paraIds=new Map<string,string>(),parents=new Map<string,string>()
 for(const target of s.inspection.commentTargets){
  const last=x.children(comments[target.ordinal]).filter(n=>n.name==='w:p').at(-1)
  const pid=last?attrsOf(fragment(last.xml))['w14:paraId']:undefined
  if(pid){if(!hex(pid)||byPara.has(pid.toUpperCase()))fail('parent_identity');byPara.set(pid.toUpperCase(),target);paraIds.set(target.originalCommentId,pid)}
 }
 const records=new Map<string,XNode>()
 if(part){
  const root=parseCommentSourceXml(await part.async('string'))
  if(nameOf(root)!=='w15:commentsEx'||attrsOf(root)['xmlns:w15']!==W15)fail('extended_schema')
  for(const record of childrenOf(root).filter(n=>nameOf(n)==='w15:commentEx')){
   const a=attrsOf(record),pid=a['w15:paraId'],parent=a['w15:paraIdParent']
   if(!hex(pid)||records.has(pid.toUpperCase())||!byPara.has(pid.toUpperCase())||childrenOf(record).some(n=>nameOf(n))||parent!==undefined&&(!hex(parent)||!byPara.has(parent.toUpperCase()))||a['w15:done']!==undefined&&!['0','1','true','false'].includes(a['w15:done']))fail('extended_parent_ambiguous')
   records.set(pid.toUpperCase(),record)
   if(parent!==undefined)parents.set(byPara.get(pid.toUpperCase())!.originalCommentId,byPara.get(parent.toUpperCase())!.originalCommentId)
  }
  for(const id of parents.keys()){const seen=new Set<string>();let current:string|undefined=id;while(current!==undefined){if(seen.has(current))fail('extended_parent_cycle');seen.add(current);current=parents.get(current)}}
 }
 function rangesOf(id:string):CommentCreationRange[]{
  let active=false,started=false,ended=false
  const ranges:CommentCreationRange[]=[]
  for(const p of s.paragraphs){
   let offset=0,from=active?0:undefined,to:number|undefined
   for(const child of x.children(p.slice)){
    const a=attrsOf(fragment(child.xml))
    if(a['w:id']===id&&child.name==='w:commentRangeStart'){if(started||active)fail('parent_anchor');started=true;active=true;from=offset}
    if(a['w:id']===id&&child.name==='w:commentRangeEnd'){if(!active||ended)fail('parent_anchor');ended=true;active=false;to=offset}
    const run=p.runs.find(r=>r.slice.start===child.start);if(run)offset=run.to
   }
   if(from!==undefined){if(p.readOnlyReason)fail('complex_parent_anchor');ranges.push({targetId:p.targetId,expectedParagraphSha256:p.expectedParagraphSha256,from,to:to??p.text.length,text:p.text.slice(from,to??p.text.length)})}
  }
  while(ranges[0]?.text.length===0)ranges.shift();while(ranges.at(-1)?.text.length===0)ranges.pop()
  if(!started||!ended||active||!ranges.length)fail('parent_anchor')
  return ranges
 }
 const ranges=new Map<string,CommentCreationRange[]>()
 const targets=s.inspection.commentTargets.map(target=>{
  const parentId=parents.get(target.originalCommentId)??null
  let reason=target.readOnlyReason
  if(parentId!==null)reason='请回复根批注线程；暂不创建嵌套回复'
  if(!reason)try{ranges.set(target.targetId,rangesOf(target.originalCommentId))}catch(e){reason=e instanceof Error?e.message:'docx_comment_reply_parent_anchor'}
  return{...target,parentId,canReply:!reason,replyReadOnlyReason:reason}
 })
 return{...s,comments,paraIds,records,targets,ranges}
}
export async function inspectDocxCommentReplies(bytes:Uint8Array):Promise<CommentReplyModel>{
 try{const s=await context(bytes);return{sourceSha256:s.sourceSha256,sourceId:s.sourceId,targets:s.targets,readOnlyReason:null}}
 catch(e){return{sourceSha256:hash(bytes),sourceId:null,targets:[],readOnlyReason:e instanceof Error?e.message:'docx_comment_reply_invalid'}}
}
export async function patchDocxCommentReplies(bytes:Uint8Array,operations:readonly CommentReplyOperation[]):Promise<Uint8Array>{
 const s=await context(bytes)
 if(!Array.isArray(operations)||!operations.length||operations.length>100)fail('operations')
 const plans=operations.map(op=>{
  if(!op||typeof op!=='object'||Object.keys(op).sort().join('|')!==['kind','sourceId','targetId','expectedCommentsSha256','expectedObjectSha256','clientId','author','date','text'].sort().join('|')||op.kind!=='replyComment'||op.sourceId!==s.sourceId)fail('operation')
  const parent=s.targets.find(t=>t.targetId===op.targetId)
  if(!parent?.canReply||parent.parentId!==null||op.expectedCommentsSha256!==parent.expectedCommentsSha256||op.expectedObjectSha256!==parent.expectedObjectSha256)fail('parent_identity')
  return{op,parent}
 })
 const created=await patchDocxCommentCreation(bytes,plans.map(({op,parent})=>({kind:'createComment',sourceId:op.sourceId,clientId:op.clientId,author:op.author,date:op.date,text:op.text,ranges:s.ranges.get(parent.targetId)!})))
 const output=await readTrustedDocxComments(created),{usedHex}=await commentPackageIdentities(output.zip)
 let comments=output.source.commentsXml,nextHex=1
 const parentParaIds=new Map(s.paraIds),patches:{start:number;length:number;value:string}[]=[]
 for(const {parent} of plans)if(!parentParaIds.has(parent.originalCommentId)){
  while(usedHex.has(nextHex.toString(16).padStart(8,'0').toUpperCase()))nextHex++
  const pid=nextHex++.toString(16).padStart(8,'0').toUpperCase();usedHex.add(pid);parentParaIds.set(parent.originalCommentId,pid)
  const comment=x.children(x.rootSlice(comments,'w:comments')).filter(n=>n.name==='w:comment')[parent.ordinal],last=x.children(comment).filter(n=>n.name==='w:p').at(-1)!
  const old=x.open(last),replacement=x.xml([x.node('w:p',{...attrsOf(fragment(last.xml)),'w14:paraId':pid})]).replace(/\/>$/,'>')
  patches.push({start:last.start,length:old.length,value:replacement})
 }
 for(const p of patches.sort((a,b)=>b.start-a.start))comments=comments.slice(0,p.start)+p.value+comments.slice(p.start+p.length)
 comments=x.rootNamespace(comments,'w:comments','w14',W14)
 const all=x.children(x.rootSlice(comments,'w:comments')).filter(n=>n.name==='w:comment'),newComments=all.slice(s.targets.length)
 if(newComments.length!==plans.length)fail('output_identity')
 let extended=output.zip.file(EX)?await output.zip.file(EX)!.async('string'):x.xml([x.node('w15:commentsEx',{'xmlns:w15':W15})])
 const recordSlices=()=>x.children(x.rootSlice(extended,'w15:commentsEx')).filter(n=>n.name==='w15:commentEx')
 for(const [i,{parent}] of plans.entries()){
  const pid=attrsOf(fragment(x.children(newComments[i]).filter(n=>n.name==='w:p').at(-1)!.xml))['w14:paraId'],parentPid=parentParaIds.get(parent.originalCommentId)!
  const existing=recordSlices().find(n=>attrsOf(fragment(n.xml))['w15:paraId']?.toUpperCase()===pid.toUpperCase())
  const addition=x.xml([x.node('w15:commentEx',{'w15:paraId':pid,'w15:paraIdParent':parentPid,'w15:done':'0'})])
  if(existing)extended=extended.slice(0,existing.start)+addition+extended.slice(existing.start+existing.xml.length)
  else extended=x.append(extended,'w15:commentsEx',addition)
  if(!recordSlices().some(n=>attrsOf(fragment(n.xml))['w15:paraId']?.toUpperCase()===parentPid.toUpperCase()))extended=x.append(extended,'w15:commentsEx',x.xml([x.node('w15:commentEx',{'w15:paraId':parentPid,'w15:done':'0'})]))
 }
 const changed=new Map([[COMMENTS,comments],[EX,extended]])
 if(!s.zip.file(EX)){
  let rel=await output.zip.file(RELS)!.async('string');const ids=new Set(childrenOf(parseCommentSourceXml(rel)).map(n=>attrsOf(n).Id));let id=1;while(ids.has('rId'+id))id++
  rel=x.append(rel,'Relationships',x.xml([x.node('Relationship',{Id:'rId'+id,Type:EX_REL,Target:'commentsExtended.xml'})]));changed.set(RELS,rel)
  const types=await output.zip.file('[Content_Types].xml')!.async('string');changed.set('[Content_Types].xml',x.append(types,'Types',x.xml([x.node('Override',{PartName:'/'+EX,ContentType:EX_TYPE})])))
 }
 for(const [path,raw] of changed){parseCommentSourceXml(raw);output.zip.file(path,raw,{createFolders:false})}
 const result=await output.zip.generateAsync({type:'uint8array',compression:'DEFLATE'}),reopened=await inspectDocxCommentReplies(result)
 if(reopened.readOnlyReason||plans.some(({parent},i)=>reopened.targets[s.targets.length+i]?.parentId!==parent.originalCommentId))fail('output_parent_identity')
 return result
}
