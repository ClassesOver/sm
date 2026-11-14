import type {Schema} from '@tiptap/pm/model'
import type {DocxAnchor,DocxPmNode} from './docx-operations'

type RecordTextRevision={kind:'recordTextRevision';blockId:string;expectedObjectSha256:string;from:number;to:number;text:string}
const same=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b)
const fail=():never=>{throw new Error('正文跟踪修订需要来源一致、按顺序且互不重叠的文本变更')}
const top=(doc:DocxPmNode,index:number)=>{
 const found=(doc.content??[]).filter(node=>node.attrs?.docxIndex===index)
 if(found.length!==1)fail()
 return found[0]
}
const hasTrackedMark=(node:DocxPmNode):boolean=>(node.marks??[]).some(mark=>mark.type==='ins'||mark.type==='del')||(node.content??[]).some(hasTrackedMark)
const textContent=(node:DocxPmNode)=>{
 if(!['docParagraph','docHeading','docListItem'].includes(node.type)||!(node.content??[]).length)return fail()
 for(const child of node.content??[])if(child.type!=='text'||typeof child.text!=='string'||!child.text.isWellFormed()||/[￾￿]/.test(child.text)||child.marks?.some(mark=>['ins','del'].includes(mark.type)))fail()
 return (node.content??[]).map(child=>child.text??'').join('')
}
function operationShape(value:unknown,anchor:DocxAnchor):RecordTextRevision{
 if(!value||typeof value!=='object'||Array.isArray(value))return fail()
 const op=value as Record<string,unknown>
 if(Object.keys(op).sort().join(',')!=='blockId,expectedObjectSha256,from,kind,text,to'||op.kind!=='recordTextRevision'||op.blockId!==anchor.blockId||op.expectedObjectSha256!==anchor.expectedObjectSha256||!Number.isSafeInteger(op.from)||!Number.isSafeInteger(op.to)||Number(op.from)<0||Number(op.to)<Number(op.from)||typeof op.text!=='string'||!op.text.isWellFormed()||/[\u0000-\u0008\u000B-\u001F\uFFFE\uFFFF]/.test(op.text))return fail()
 return op as RecordTextRevision
}
const boundary=(text:string,at:number)=>at<=text.length&&!(at>0&&at<text.length&&/[\uD800-\uDBFF]/.test(text[at-1]!)&&/[\uDC00-\uDFFF]/.test(text[at]!))

/** Converts recorder marks into source-anchored operations and removes them from ordinary diff input. */
export function normalizeDocxTrackedChanges(baseline:DocxPmNode,live:DocxPmNode,anchors:readonly DocxAnchor[]){
 const current=structuredClone(live),operations:RecordTextRevision[]=[]
 for(const anchor of anchors){
  const source=top(baseline,anchor.docxIndex),node=top(current,anchor.docxIndex)
  if(same(source,node))continue
  // 来源修订决策由下一步 normalizeDocxTextRevisions 严格核验完整投影与签发身份。
  if(anchor.reviewTargets?.length&&node.attrs?.nativeTextRevisionOperations!=null)continue
  const marked=hasTrackedMark(node)
  if(!marked)continue
  if(!anchor.editable||anchor.reviewTargets?.length||anchor.revisionReadOnlyReason)fail()
  const before=textContent(source),children=node.content??[]
  if(!children.length||children.some(child=>child.type!=='text'||typeof child.text!=='string'||!child.text!.isWellFormed()||/[￾￿]/.test(child.text!)))fail()
  let offset=0,change:{from:number;to:number;text:string}|undefined
  const finish=()=>{
   if(!change)return
   if(!boundary(before,change.from)||!boundary(before,change.to)||change.from===change.to&&!change.text)fail()
   operations.push({kind:'recordTextRevision',blockId:anchor.blockId,expectedObjectSha256:anchor.expectedObjectSha256,...change})
   change=undefined
  }
  for(const child of children){
   const revisions=(child.marks??[]).filter(mark=>mark.type==='ins'||mark.type==='del')
   // 原生 recorder 同时标记 ins/del 的文字从未存在于来源，也不属于最终正文。
   if(revisions.length===2&&revisions[0].type!==revisions[1].type)continue
   if(revisions.length>1)fail()
   const revision=revisions[0],value=child.text??''
   if(!revision){
    finish()
    if(before.slice(offset,offset+value.length)!==value)fail()
    offset+=value.length
   }else{
    change??={from:offset,to:offset,text:''}
    if(revision.type==='del'){
     if(before.slice(offset,offset+value.length)!==value)fail()
     offset+=value.length;change.to=offset
    }else change.text+=value
   }
  }
  finish()
  if(offset!==before.length)fail()
  current.content![current.content!.indexOf(node)]=structuredClone(source)
 }
 return{baseline:structuredClone(baseline),current,operations}
}

/** Replays reviewed edits from the frozen paragraph snapshot using server context for display marks. */
export function replayDocxTrackedChanges(baseline:DocxPmNode,value:unknown,anchors:readonly DocxAnchor[],schema:Schema,author:string,date:string|null):DocxPmNode{
 if(!Array.isArray(value))fail()
 const operations=value as unknown[]
 if(operations.length>500||!author||typeof author!=='string'||date!==null&&(!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(date)||!Number.isFinite(Date.parse(date))))fail()
 const result=structuredClone(baseline),byBlock=new Map<string,{anchor:DocxAnchor;ops:RecordTextRevision[]}>()
 for(const raw of operations){
  const match=anchors.filter(anchor=>anchor.blockId===(raw as Record<string,unknown>)?.blockId)
  if(match.length!==1||!match[0].editable||match[0].reviewTargets?.length||match[0].revisionReadOnlyReason)fail()
  const anchor=match[0],op=operationShape(raw,anchor),group=byBlock.get(anchor.blockId)??{anchor,ops:[]}
  group.ops.push(op);byBlock.set(anchor.blockId,group)
 }
 for(const {anchor,ops} of byBlock.values()){
  const source=top(result,anchor.docxIndex),plain=textContent(source),ordered=ops
  let cursor=-1
  for(const op of ordered)if(op.from<=cursor||op.to>plain.length||!boundary(plain,op.from)||!boundary(plain,op.to)||op.from===op.to&&!op.text)fail();else cursor=op.to
  const output:DocxPmNode[]=[]
  const addSource=(from:number,to:number,revision:'ins'|'del'|null)=>{
   let offset=0
   for(const child of source.content??[]){
    const start=offset,end=offset+=(child.text??'').length
    if(from>=to||start>=to||end<=from)continue
    const piece={...structuredClone(child),text:child.text!.slice(Math.max(from,start)-start,Math.min(to,end)-start)}
    if(revision){const mark=schema.marks[revision];if(!mark)fail();piece.marks=[...(piece.marks??[]).filter(item=>item.type!=='ins'&&item.type!=='del'),mark.create({author,date}).toJSON()]}
    output.push(piece)
   }
  }
  const addInsertion=(at:number,text:string)=>{
   const children=source.content??[],offsets:number[]=[];let offset=0
   for(const child of children){offsets.push(offset);offset+=(child.text??'').length}
   const index=children.findIndex((child,i)=>offsets[i]!<=at&&offsets[i]!+(child.text??'').length>=at),template=children[Math.max(0,index)]
   if(!text)return
   if(!template)return fail()
   const mark=schema.marks.ins;if(!mark)fail()
   output.push({...structuredClone(template),text,marks:[...(template.marks??[]).filter(item=>item.type!=='ins'&&item.type!=='del'),mark.create({author,date}).toJSON()]})
  }
  cursor=0
  for(const op of ordered){addSource(cursor,op.from,null);if(op.to>op.from)addSource(op.from,op.to,'del');addInsertion(op.from,op.text);cursor=op.to}
  addSource(cursor,plain.length,null)
  source.content=output
 }
 return result
}

export function assertDocxTrackedChangesBatch(operations:readonly Record<string,unknown>[]){
 const blocks=new Set(operations.filter(op=>op.kind==='recordTextRevision').map(op=>op.blockId))
 const previous=new Map<unknown,{to:number;hash:unknown}>()
 for(const op of operations){
  if(op.kind==='recordTextRevision'){
   const last=previous.get(op.blockId)
   if(!Number.isSafeInteger(op.from)||!Number.isSafeInteger(op.to)||Number(op.from)<0||Number(op.to)<Number(op.from)||
    last&&(Number(op.from)<=last.to||op.expectedObjectSha256!==last.hash))fail()
   previous.set(op.blockId,{to:Number(op.to),hash:op.expectedObjectSha256})
  }
  if(op.kind!=='recordTextRevision'&&blocks.has(op.blockId))fail()
 }
 if(blocks.size&&operations.some(op=>op.kind==='setSectionLayout'||op.kind==='insertSectionBreak'))fail()
}
