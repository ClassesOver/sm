/** 服务端原 XML wrapper 贡献的 UTF-16 范围，只用于预览，不作为保存授权输入。 */
export interface DocxTextRevisionSourceRange { from:number; to:number; text:string }
export interface DocxTextRevisionTarget {
 blockId:string; expectedObjectSha256:string; revisionId:string; originalRevisionId:string
 type:'insertion'|'deletion'; author:string; date:string|null
 sourceRange?:DocxTextRevisionSourceRange
}
export interface DocxTextRevisionAnchor {
 docxIndex:number; blockId:string; expectedObjectSha256:string
 reviewTargets?:DocxTextRevisionTarget[]; revisionReadOnlyReason?:string|null
}
export interface DocxTextRevisionMappedTarget extends DocxTextRevisionTarget { from:number; to:number; text:string }
export interface DocxTextRevisionOperation {
 [key:string]:unknown
 kind:'resolveTextRevision'; blockId:string; expectedObjectSha256:string; revisionId:string; action:'accept'|'reject'
}
export function failDocxTextRevision():never{throw new Error('正文修订来源、映射或草稿无效；不能与同段其他修改混用')}
export function validatedDocxTextRevisionOperations(value:unknown,anchor:DocxTextRevisionAnchor):DocxTextRevisionOperation[]{
 if(!Array.isArray(value)||!value.length||value.length>500)failDocxTextRevision()
 const seen=new Set<string>()
 return value.map(op=>{
  if(!op||typeof op!=='object'||Array.isArray(op)||Object.keys(op).length!==5||Object.keys(op).some(key=>!['kind','blockId','expectedObjectSha256','revisionId','action'].includes(key))||op.kind!=='resolveTextRevision'||op.blockId!==anchor.blockId||op.expectedObjectSha256!==anchor.expectedObjectSha256||typeof op.revisionId!=='string'||seen.has(op.revisionId)||!anchor.reviewTargets?.some(target=>target.revisionId===op.revisionId)||!['accept','reject'].includes(op.action))failDocxTextRevision()
  seen.add(op.revisionId)
  return {...op} as DocxTextRevisionOperation
 })
}
/** 对整批先校验互斥；修订段的相邻插入/节边界也不与修订决策混用。 */
export function assertDocxTextRevisionBatch(operations:readonly Record<string,unknown>[]){
 const blocks=new Set(operations.filter(op=>op.kind==='resolveTextRevision').map(op=>op.blockId))
 if(blocks.size&&operations.some(op=>op.kind==='setSectionLayout'||op.kind==='insertSectionBreak'))failDocxTextRevision()
 for(const op of operations)if(op.kind!=='resolveTextRevision'&&['blockId','afterBlockId','beforeBlockId'].some(key=>typeof op[key]==='string'&&blocks.has(op[key])))failDocxTextRevision()
}
