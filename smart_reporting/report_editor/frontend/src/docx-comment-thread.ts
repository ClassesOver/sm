import type {DocxPmNode} from './docx-operations'
import {verifiedDocxCommentTextModel,type DocxCommentTextTarget} from './docx-comment-text'

export interface DocxCommentThreadTarget extends DocxCommentTextTarget {
 parentId:string|null;done:boolean;canDelete:boolean;canResolve:boolean;threadReadOnlyReason:string|null
}
export interface DocxCommentThreadModel {sourceSha256:string;sourceId:string|null;targets:DocxCommentThreadTarget[];readOnlyReason:string|null}
type Identity=Pick<DocxCommentTextTarget,'sourceId'|'targetId'|'expectedCommentsSha256'|'expectedObjectSha256'>
export type DocxCommentThreadOperation=Identity&({kind:'deleteComment'}|{kind:'resolveComment';done:boolean})
type Display={id:string;author:string;text:string;date?:string;initials?:string;parentId?:string;done?:boolean}
const intent='nativeCommentThreadOperations'
const copy=<T>(value:T):T=>structuredClone(value)
const fail=():never=>{throw new Error('批注线程与当前文档来源不一致，请重新打开文档')}
const members=(model:DocxCommentThreadModel,id:string)=>model.targets.filter(t=>t.originalCommentId===id||t.parentId===id)
export const isDocxCommentThreadOperation=(op:{kind?:unknown})=>op.kind==='deleteComment'||op.kind==='resolveComment'

export function verifiedDocxCommentThreadModel(model:DocxCommentThreadModel,expectedSha:string,parsed:readonly Display[]):DocxCommentThreadModel{
 if(!model||!Array.isArray(model.targets)||!(model.readOnlyReason===null||typeof model.readOnlyReason==='string'))fail()
 verifiedDocxCommentTextModel({sourceSha256:model.sourceSha256,sourceId:model.sourceId,commentTargets:model.targets,commentReadOnlyReason:model.readOnlyReason},expectedSha,parsed)
 const result=copy(model),byId=new Map(result.targets.map(t=>[t.originalCommentId,t]))
 if(byId.size!==result.targets.length)fail()
 const bad=new Set<string>()
 for(const t of result.targets){
  if(!(t.parentId===null||typeof t.parentId==='string'&&byId.get(t.parentId)?.parentId===null)||
    typeof t.done!=='boolean'||typeof t.canDelete!=='boolean'||typeof t.canResolve!=='boolean'||t.canResolve&&(!t.canDelete||t.parentId!==null)||
    !(t.threadReadOnlyReason===null||typeof t.threadReadOnlyReason==='string'))fail()
  const actual=parsed[t.ordinal]
  if(!actual||parsed.filter(p=>p.id===t.originalCommentId).length!==1||actual.id!==t.originalCommentId||actual.author!==t.author||
    (t.editableText&&actual.text!==t.text)||(actual.date??null)!==t.date||(actual.initials??null)!==t.initials||
    (actual.parentId??null)!==t.parentId||(actual.done??false)!==t.done){
   bad.add(t.parentId??t.originalCommentId)
   if(actual?.parentId)bad.add(actual.parentId)
  }
 }
 for(const t of result.targets)if(bad.has(t.parentId??t.originalCommentId)){
  t.canDelete=false;t.canResolve=false;t.threadReadOnlyReason='批注显示与服务端线程不一致，仅可查看原文'
 }
 return result
}

function checked(value:unknown,model:DocxCommentThreadModel):DocxCommentThreadOperation[]{
 if(!Array.isArray(value)||value.length>200)fail()
 const seen=new Set<string>()
 for(const raw of value as unknown[]){
  if(!raw||typeof raw!=='object'||Array.isArray(raw))fail()
  const op=raw as DocxCommentThreadOperation,target=model.targets.find(t=>t.targetId===op.targetId)
  const keys=['kind','sourceId','targetId','expectedCommentsSha256','expectedObjectSha256']
  if(op.kind==='resolveComment')keys.push('done')
  if(Object.keys(op).sort().join('|')!==keys.sort().join('|')||model.readOnlyReason||!model.sourceId||!target||op.sourceId!==model.sourceId||
    op.sourceId!==target.sourceId||op.expectedCommentsSha256!==target.expectedCommentsSha256||op.expectedObjectSha256!==target.expectedObjectSha256||
    !(op.kind==='deleteComment'&&target.canDelete||op.kind==='resolveComment'&&target.canResolve&&typeof op.done==='boolean'))fail()
  for(const t of members(model,target!.originalCommentId)){
   if(seen.has(t.originalCommentId))fail()
   seen.add(t.originalCommentId)
  }
 }
 return copy(value) as DocxCommentThreadOperation[]
}

export function docxCommentThreadOperationsOf(doc:DocxPmNode,model?:DocxCommentThreadModel):DocxCommentThreadOperation[]{
 const value=doc.attrs?.[intent]
 if(value==null)return[]
 return model?checked(value,model):fail()
}
export function normalizeDocxCommentThreads(baseline:DocxPmNode,live:DocxPmNode,model?:DocxCommentThreadModel){
 if(baseline.attrs?.[intent]!=null)fail()
 if(!Object.hasOwn(live.attrs??{},intent))return{current:live,operations:[]}
 const operations=docxCommentThreadOperationsOf(live,model)
 const current:DocxPmNode={...live},attrs={...live.attrs}
 delete attrs[intent]
 if(Object.keys(attrs).length)current.attrs=attrs
 else delete current.attrs
 return{current,operations}
}
export function replayDocxCommentThreads(doc:DocxPmNode,operations:readonly unknown[],model:DocxCommentThreadModel):DocxPmNode{
 const result=copy(doc),valid=checked(operations,model)
 result.attrs={...result.attrs,[intent]:valid.length?valid:null}
 return result
}
export function assertDocxCommentThreadBatch(operations:readonly {kind?:unknown}[]){
 if(operations.some(isDocxCommentThreadOperation)&&operations.some(op=>!isDocxCommentThreadOperation(op)))throw new Error('删除、解决或重新打开批注需独立保存，请先保存或撤销其他修改')
}
export function updateDocxCommentThreadOperations(model:DocxCommentThreadModel,operations:readonly DocxCommentThreadOperation[],targetId:string,done?:boolean){
 const current=checked(operations,model),target=model.targets.find(t=>t.targetId===targetId)
 if(!target||(done===undefined?!target.canDelete:!target.canResolve))return fail()
 const affected=members(model,target.originalCommentId)
 const next=current.filter(op=>op.targetId!==targetId&&!(done===undefined&&affected.some(t=>t.targetId===op.targetId)))
 if(done!==undefined&&affected.every(t=>t.done===done))return next
 const {sourceId,expectedCommentsSha256,expectedObjectSha256}=target
 const identity={sourceId,targetId,expectedCommentsSha256,expectedObjectSha256}
 return checked([...next,done===undefined?{kind:'deleteComment',...identity}:{kind:'resolveComment',...identity,done}],model)
}
function changes(doc:DocxPmNode,model?:DocxCommentThreadModel){
 const removed=new Set<string>(),done=new Map<string,boolean>()
 for(const op of docxCommentThreadOperationsOf(doc,model)){
  const target=model!.targets.find(t=>t.targetId===op.targetId)!
  for(const member of members(model!,target.originalCommentId)){
   if(op.kind==='deleteComment')removed.add(member.originalCommentId)
   else done.set(member.originalCommentId,op.done)
  }
 }
 return{removed,done}
}
export function hiddenDocxCommentIds(doc:DocxPmNode,model?:DocxCommentThreadModel){return changes(doc,model).removed}
export function projectedDocxCommentThreads<T extends {id:string;done?:boolean}>(comments:readonly T[],doc:DocxPmNode,model?:DocxCommentThreadModel):(T & {done?:boolean})[]{
 const {removed,done}=changes(doc,model)
 return comments.filter(comment=>!removed.has(comment.id)).map(comment=>done.has(comment.id)?{...comment,done:done.get(comment.id)!}:comment)
}
