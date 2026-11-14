/** Server-authorized non-body revisions, suitable for the review pane and draft restore. */
export interface DocxStoryRevisionTarget {
 targetId:string;partPath:string;expectedPartSha256:string;expectedWrapperSha256:string;originalRevisionId:string
 kind:'footnote'|'endnote'|'header'|'footer';noteId?:string;type:'insertion'|'deletion';author:string;date:string|null;text:string
}
export interface DocxStoryRevisionDraft {
 [key:string]:unknown
 kind:'resolveStoryRevision';targetId:string;expectedPartSha256:string;expectedWrapperSha256:string;action:'accept'|'reject'
}
function invalid():never{throw new Error('非正文修订来源已变化或草稿无效，请重新打开原文件')}
export function storyRevisionDraft(target:DocxStoryRevisionTarget,action:'accept'|'reject'):DocxStoryRevisionDraft{
 return{kind:'resolveStoryRevision',targetId:target.targetId,expectedPartSha256:target.expectedPartSha256,expectedWrapperSha256:target.expectedWrapperSha256,action}
}
export function validatedStoryRevisionDrafts(value:unknown,targets:readonly DocxStoryRevisionTarget[]):DocxStoryRevisionDraft[]{
 if(!Array.isArray(value)||value.length>500)invalid()
 const seen=new Set<string>()
 return value.map(op=>{
  if(!op||typeof op!=='object'||Array.isArray(op)||Object.keys(op).sort().join(',')!=='action,expectedPartSha256,expectedWrapperSha256,kind,targetId'||op.kind!=='resolveStoryRevision'||!['accept','reject'].includes(op.action)||seen.has(op.targetId))invalid()
  const target=targets.find(t=>t.targetId===op.targetId)
  if(!target||op.expectedPartSha256!==target.expectedPartSha256||op.expectedWrapperSha256!==target.expectedWrapperSha256)invalid()
  seen.add(op.targetId);return{...op} as DocxStoryRevisionDraft
 })
}
const labels={footnote:'脚注',endnote:'尾注',header:'页眉',footer:'页脚'}
export function storyRevisionItems(targets:readonly DocxStoryRevisionTarget[],drafts:readonly DocxStoryRevisionDraft[]=[]){
 const valid=validatedStoryRevisionDrafts(drafts,targets)
 return targets.map(target=>({...target,location:labels[target.kind]+(target.noteId?` ${target.noteId}`:''),pendingAction:valid.find(d=>d.targetId===target.targetId)?.action??null}))
}
