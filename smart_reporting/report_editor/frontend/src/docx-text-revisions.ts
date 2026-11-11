import type {Schema} from '@tiptap/pm/model'
import type {DocxPmNode} from './docx-operations'
import {assertDocxTextRevisionBatch,failDocxTextRevision,validatedDocxTextRevisionOperations,type DocxTextRevisionAnchor,type DocxTextRevisionMappedTarget,type DocxTextRevisionOperation} from './docx-text-revisions-core'
export type {DocxTextRevisionAnchor,DocxTextRevisionMappedTarget,DocxTextRevisionOperation,DocxTextRevisionTarget} from './docx-text-revisions-core'
const kinds=new Set(['docParagraph','docHeading','docListItem'])
const same=(a:unknown,b:unknown):boolean=>{
 if(a===b)return true
 if(!a||!b||typeof a!=='object'||typeof b!=='object')return false
 if(Array.isArray(a)!==Array.isArray(b))return false
 const ak=Object.keys(a),bk=Object.keys(b)
 return ak.length===bk.length&&ak.every(key=>Object.hasOwn(b,key)&&same((a as Record<string,unknown>)[key],(b as Record<string,unknown>)[key]))
}
const breakText=(node:DocxPmNode)=>node.attrs?.pageBreak?'\f':node.attrs?.colBreak?'\v':node.attrs?.wrapBreak?'\u001e':'\n'
function inlineText(node:DocxPmNode):string{
 if(node.type==='text'&&typeof node.text==='string'&&!node.content)return node.text
 if(node.type==='hardBreak'&&!node.content)return breakText(node)
 return failDocxTextRevision()
}
const hasOtherIntent=(node:DocxPmNode)=>Object.entries(node.attrs??{}).some(([key,value])=>key.startsWith('native')&&key!=='nativeTextRevisionOperations'&&value!==null&&value!==undefined&&value!==false)
const splitSurrogate=(text:string,offset:number)=>offset>0&&offset<text.length&&/[\uD800-\uDBFF]/.test(text[offset-1])&&/[\uDC00-\uDFFF]/.test(text[offset])
/** 范围由服务端来源贡献签发。这里核验整个段落，不从 RevisionRange、作者或重复 w:id 猜身份。 */
export function getDocxTextRevisionTargets(source:DocxPmNode,anchor:DocxTextRevisionAnchor):DocxTextRevisionMappedTarget[]{
 if(!kinds.has(source.type)||source.attrs?.docxIndex!==anchor.docxIndex||anchor.revisionReadOnlyReason||hasOtherIntent(source)||source.attrs?.nativeTextRevisionOperations)failDocxTextRevision()
 const content=source.content??[],text=content.map(inlineText).join(''),seen=new Set<string>()
 const targets=(anchor.reviewTargets??[]).map(target=>{
  const range=target.sourceRange
  if(target.blockId!==anchor.blockId||target.expectedObjectSha256!==anchor.expectedObjectSha256||typeof target.revisionId!=='string'||!target.revisionId||seen.has(target.revisionId)||!['insertion','deletion'].includes(target.type)||typeof target.author!=='string'||!(target.date===null||typeof target.date==='string')||!range||!Number.isSafeInteger(range.from)||!Number.isSafeInteger(range.to)||range.from<0||range.to<=range.from||range.to>text.length||typeof range.text!=='string'||text.slice(range.from,range.to)!==range.text||splitSurrogate(text,range.from)||splitSurrogate(text,range.to))failDocxTextRevision()
  seen.add(target.revisionId)
  return {...structuredClone(target),from:range.from,to:range.to,text:range.text}
 }).sort((a,b)=>a.from-b.from)
 if(!targets.length||targets.some((target,i)=>i>0&&target.from<targets[i-1].to))failDocxTextRevision()
 let offset=0
 for(const node of content){
  const from=offset,to=offset+=inlineText(node).length,marks=(node.marks??[]).filter(mark=>mark.type==='ins'||mark.type==='del')
  const touching=targets.filter(target=>target.from<to&&target.to>from)
  if(!touching.length){if(marks.length)failDocxTextRevision();continue}
  if(marks.length!==1||touching[0].from>from||touching[touching.length-1].to<to||touching.some((target,i)=>i>0&&target.from!==touching[i-1].to))failDocxTextRevision()
  const mark=marks[0]
  for(const target of touching)if(mark.type!==(target.type==='insertion'?'ins':'del')||(mark.attrs?.author??'')!==target.author||(mark.attrs?.date??null)!==target.date||mark.attrs?.move)failDocxTextRevision()
 }
 return targets
}
function canonical(node:DocxPmNode,schema?:Schema):DocxPmNode{
 if(schema)return schema.nodeFromJSON(node).toJSON() as DocxPmNode
 const result=structuredClone(node),content:DocxPmNode[]=[]
 for(const child of result.content??[]){
  const previous=content.at(-1)
  if(previous?.type==='text'&&child.type==='text'&&same(previous.marks??[],child.marks??[])&&same(previous.attrs??{},child.attrs??{}))previous.text=(previous.text??'')+(child.text??'')
  else content.push(child)
 }
 if(content.length)result.content=content;else delete result.content
 return result
}
/** 整批始终投影到原 baseline；不逐条变更身份，也不放宽普通段落权限。 */
export function projectDocxTextRevisions(source:DocxPmNode,anchor:DocxTextRevisionAnchor,value:unknown,schema?:Schema):DocxPmNode{
 const targets=getDocxTextRevisionTargets(source,anchor),operations=validatedDocxTextRevisionOperations(value,anchor),byId=new Map(operations.map(op=>[op.revisionId,op])),result=structuredClone(source),content:DocxPmNode[]=[]
 let offset=0
 for(const node of source.content??[]){
  const from=offset,to=offset+=inlineText(node).length
  const cuts=[...new Set([from,to,...targets.flatMap(target=>[target.from,target.to]).filter(cut=>cut>from&&cut<to)])].sort((a,b)=>a-b)
  for(let i=0;i<cuts.length-1;i++){
   const start=cuts[i],end=cuts[i+1],target=targets.find(target=>target.from<=start&&target.to>=end),operation=target&&byId.get(target.revisionId)
   if(operation&&((target!.type==='insertion')===(operation.action==='reject')))continue
   const piece=structuredClone(node)
   if(piece.type==='text')piece.text=node.text!.slice(start-from,end-from)
   if(operation){piece.marks=piece.marks?.filter(mark=>mark.type!=='ins'&&mark.type!=='del');if(!piece.marks?.length)delete piece.marks}
   content.push(piece)
  }
 }
 result.content=content
 result.attrs={...result.attrs,nativeTextRevisionOperations:operations}
 return canonical(result,schema)
}
const find=(doc:DocxPmNode,index:number)=>{
 const matches=(doc.content??[]).filter(node=>node.attrs?.docxIndex===index)
 if(matches.length!==1)failDocxTextRevision()
 return matches[0]
}
/** 先验证严格等于 baseline + 决策，再还原普通 diff 输入，避免被降为 replaceParagraph。 */
export function normalizeDocxTextRevisions(baseline:DocxPmNode,live:DocxPmNode,anchors:readonly DocxTextRevisionAnchor[],schema?:Schema){
 const current=structuredClone(live),operations:DocxTextRevisionOperation[]=[]
 const visit=(node:DocxPmNode,top:boolean)=>{
  const intent=node.attrs?.nativeTextRevisionOperations
  if(intent!==undefined&&intent!==null){
   if(!top)failDocxTextRevision()
   const candidates=anchors.filter(anchor=>anchor.docxIndex===node.attrs?.docxIndex)
   if(candidates.length!==1)failDocxTextRevision()
   const anchor=candidates[0],source=find(baseline,anchor.docxIndex)
   if(find(current,anchor.docxIndex)!==node)failDocxTextRevision()
   const ops=validatedDocxTextRevisionOperations(intent,anchor),projected=projectDocxTextRevisions(source,anchor,ops,schema)
   // schema 只用于构造期规范化；当前 JSON 必须逐字段相等，不允许吞掉未声明 attrs。
   if(!same(node,projected))failDocxTextRevision()
   operations.push(...ops)
   const index=current.content!.indexOf(node);current.content![index]=structuredClone(source)
   return
  }
  for(const child of node.content??[])visit(child,false)
 }
 if(current.attrs?.nativeTextRevisionOperations!==undefined&&current.attrs.nativeTextRevisionOperations!==null)failDocxTextRevision()
 for(const node of current.content??[])visit(node,true)
 return {baseline,current,operations}
}
/** 宿主可在跨段普通重放后调用；修订段必须仍为原 baseline。 */
export function replayDocxTextRevisions(baseline:DocxPmNode,operations:readonly Record<string,unknown>[],anchors:readonly DocxTextRevisionAnchor[],schema?:Schema):DocxPmNode{
 assertDocxTextRevisionBatch(operations)
 const result=structuredClone(baseline),groups=new Map<string,Record<string,unknown>[]>()
 for(const op of operations)if(op.kind==='resolveTextRevision'){
  if(typeof op.blockId!=='string')failDocxTextRevision()
  const group=groups.get(op.blockId)??[];group.push(op);groups.set(op.blockId,group)
 }
 // 在替换任何节点前规划全部组；失败不会暴露部分结果或修改入参。
 const plans=[...groups].map(([blockId,ops])=>{
  const matches=anchors.filter(anchor=>anchor.blockId===blockId)
  if(matches.length!==1)failDocxTextRevision()
  const anchor=matches[0],source=find(result,anchor.docxIndex)
  return {source,projected:projectDocxTextRevisions(source,anchor,ops,schema)}
 })
 for(const {source,projected} of plans)result.content![result.content!.indexOf(source)]=projected
 return result
}
