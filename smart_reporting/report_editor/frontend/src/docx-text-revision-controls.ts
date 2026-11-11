import {createElement,Sparkles} from 'lucide'
import type {Editor} from '@tiptap/core'
import {closeHistory} from '@tiptap/pm/history'
import {TextSelection} from '@tiptap/pm/state'
import type {DocxPmNode} from './docx-operations'
import {createModal} from './modal'
import {buttonClasses} from './button'
import {TRACK_IGNORE} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/revisions'
import {getDocxTextRevisionTargets,normalizeDocxTextRevisions,projectDocxTextRevisions,type DocxTextRevisionAnchor,type DocxTextRevisionMappedTarget,type DocxTextRevisionOperation} from './docx-text-revisions'
import {failDocxTextRevision,validatedDocxTextRevisionOperations} from './docx-text-revisions-core'
interface Options {
 editor:Editor; baseline:DocxPmNode; anchors:readonly DocxTextRevisionAnchor[]; container:HTMLElement
 onReviewAI?:(selection:{blockId:string;revisionId:string},instruction?:string)=>void
 readOnlyReason?:()=>string|null; onError:(error:unknown)=>void
}
interface Entry {anchor:DocxTextRevisionAnchor;source:DocxPmNode;target:DocxTextRevisionMappedTarget}
/** 只列出服务器明确授权的源目标，不把 PM 合并后的 mark 范围当成一个 XML wrapper。 */
export function createDocxTextRevisionControls(options:Options){
 const {editor,anchors}=options,baseline=structuredClone(options.baseline)
 let modal:ReturnType<typeof createModal>|undefined,selectedId:string|undefined,disposed=false
 const locked=()=>options.readOnlyReason?.()??(!editor.isEditable?'当前文档只读':null)
 const sourceOf=(anchor:DocxTextRevisionAnchor)=>{
  const nodes=(baseline.content??[]).filter(node=>node.attrs?.docxIndex===anchor.docxIndex)
  if(nodes.length!==1)failDocxTextRevision()
  return nodes[0]
 }
 const liveOf=(anchor:DocxTextRevisionAnchor)=>{
  const matches:{node:ReturnType<typeof editor.state.doc.child>;pos:number}[]=[]
  editor.state.doc.forEach((node,pos)=>{if(node.attrs.docxIndex===anchor.docxIndex)matches.push({node,pos})})
  if(matches.length!==1)failDocxTextRevision()
  return matches[0]
 }
 const pendingOf=(node:DocxPmNode,anchor:DocxTextRevisionAnchor)=>node.attrs?.nativeTextRevisionOperations==null?[]:validatedDocxTextRevisionOperations(node.attrs.nativeTextRevisionOperations,anchor)
 const verified=(entry:Entry)=>{
  normalizeDocxTextRevisions(baseline,editor.getJSON(),anchors,editor.schema)
  const live=liveOf(entry.anchor),pending=pendingOf(live.node.toJSON(),entry.anchor)
  const expected=pending.length?projectDocxTextRevisions(entry.source,entry.anchor,pending,editor.schema):entry.source
  if(!live.node.eq(editor.schema.nodeFromJSON(expected)))failDocxTextRevision()
  return {...live,pending}
 }
 const navigate=(entry:Entry)=>{
  try{
   const live=verified(entry),targets=getDocxTextRevisionTargets(entry.source,entry.anchor),byId=new Map(live.pending.map(op=>[op.revisionId,op]))
   let from=entry.target.from,length=entry.target.to-entry.target.from
   for(const target of targets){
    const op=byId.get(target.revisionId),removed=op&&((target.type==='insertion')===(op.action==='reject'))
    if(removed&&target.to<=entry.target.from)from-=target.to-target.from
    if(removed&&target.revisionId===entry.target.revisionId)length=0
   }
   const start=live.pos+1+from
   editor.view.dispatch(editor.state.tr.setSelection(TextSelection.create(editor.state.doc,start,start+length)).setMeta('addToHistory',false).scrollIntoView())
   selectedId=entry.target.revisionId
   editor.view.focus()
  }catch(error){options.onError(error)}
 }
 const apply=(entry:Entry,action:'accept'|'reject')=>{
  try{
   const reason=locked();if(reason)throw new Error(reason)
   const live=verified(entry)
   if(live.pending.some(op=>op.revisionId===entry.target.revisionId))throw new Error('此来源修订已有决策，请使用撤销调整')
   const operation:DocxTextRevisionOperation={kind:'resolveTextRevision',blockId:entry.anchor.blockId,expectedObjectSha256:entry.anchor.expectedObjectSha256,revisionId:entry.target.revisionId,action}
   const next=projectDocxTextRevisions(entry.source,entry.anchor,[...live.pending,operation],editor.schema),node=editor.schema.nodeFromJSON(next)
   const tr=closeHistory(editor.state.tr).replaceWith(live.pos,live.pos+live.node.nodeSize,node).setMeta(TRACK_IGNORE,true)
   editor.view.dispatch(tr)
   if(!liveOf(entry.anchor).node.eq(node))throw new Error('当前修订决策未被编辑器接受，请重新打开列表')
   selectedId=entry.target.revisionId
  }catch(error){options.onError(error)}
 }
 // 先完成整批授权和投影校验，再构造一个事务；既有决策保持原样。
 const batchPlan=(action:'accept'|'reject')=>{
  const reason=locked();if(reason)throw new Error(reason)
  normalizeDocxTextRevisions(baseline,editor.getJSON(),anchors,editor.schema)
  const seen=new Set<number>(),plans=[]
  for(const anchor of anchors){
   if(!anchor.reviewTargets?.length)continue
   if(seen.has(anchor.docxIndex))failDocxTextRevision()
   seen.add(anchor.docxIndex)
   const source=sourceOf(anchor),targets=getDocxTextRevisionTargets(source,anchor)
   if(!targets.length)continue
   const live=verified({source,anchor,target:targets[0]})
   const pendingIds=new Set(live.pending.map(op=>op.revisionId))
   const additions:DocxTextRevisionOperation[]=targets.filter(target=>!pendingIds.has(target.revisionId)).map(target=>({kind:'resolveTextRevision',blockId:anchor.blockId,expectedObjectSha256:anchor.expectedObjectSha256,revisionId:target.revisionId,action}))
   if(!additions.length)continue
   const next=projectDocxTextRevisions(source,anchor,[...live.pending,...additions],editor.schema)
   plans.push({...live,anchor,next:editor.schema.nodeFromJSON(next)})
  }
  if(!plans.length)throw new Error('没有待处理的受支持正文修订')
  return plans
 }
 const batchReason=()=>{try{batchPlan('accept');return null}catch(error){return error instanceof Error?error.message:String(error)}}
 const applyAll=(action:'accept'|'reject')=>{
  try{
   const plans=batchPlan(action),tr=closeHistory(editor.state.tr).setMeta(TRACK_IGNORE,true)
   for(const plan of plans.sort((a,b)=>b.pos-a.pos))tr.replaceWith(plan.pos,plan.pos+plan.node.nodeSize,plan.next)
   normalizeDocxTextRevisions(baseline,tr.doc.toJSON(),anchors,editor.schema)
   editor.view.dispatch(tr)
   if(!editor.state.doc.eq(tr.doc))throw new Error('批量修订决策未被编辑器接受，请重新打开列表')
  }catch(error){options.onError(error)}
 }
 const refresh=()=>{
  if(!modal||disposed||editor.isDestroyed)return
  const list=modal.card.querySelector<HTMLElement>('[data-revision-list]')!,status=modal.card.querySelector<HTMLElement>('[role="status"]')!
  list.replaceChildren()
  const entries:Entry[]=[],reasons:string[]=[]
  let validationReason:string|null=null
  try{normalizeDocxTextRevisions(baseline,editor.getJSON(),anchors,editor.schema)}catch(error){validationReason=error instanceof Error?error.message:String(error)}
  for(const anchor of anchors){
   if(!anchor.reviewTargets?.length){if(anchor.revisionReadOnlyReason)reasons.push(anchor.revisionReadOnlyReason);continue}
   try{
    const source=sourceOf(anchor),targets=getDocxTextRevisionTargets(source,anchor)
    for(const target of targets)entries.push({source,anchor,target})
   }catch(error){reasons.push(error instanceof Error?error.message:String(error))}
  }
  let resolved=0
  for(const entry of entries){
   let pending:DocxTextRevisionOperation[]=[],reason=validationReason
   try{pending=verified(entry).pending}catch(error){reason=error instanceof Error?error.message:String(error)}
   const decision=pending.find(op=>op.revisionId===entry.target.revisionId)
   if(decision)resolved++
   const row=document.createElement('li');row.dataset.revisionId=entry.target.revisionId
   const description=document.createElement('p')
   description.textContent=`${entry.target.type==='insertion'?'插入':'删除'} · ${entry.target.author||'未知作者'}${entry.target.date?` · ${entry.target.date}`:''}：${entry.target.text}${decision?`（${decision.action==='accept'?'已接受':'已拒绝'}）`:''}`
   row.append(description)
   for(const [action,label] of [['locate','定位'],['accept','接受'],['reject','拒绝']] as const){
    const button=document.createElement('button');button.type='button';button.dataset.action=action;button.textContent=label;button.className=buttonClasses('secondary')
    const unavailable=reason??(action==='locate'?null:decision?'此来源修订已有决策，请使用撤销调整':locked())
    button.disabled=!!unavailable;button.title=unavailable??''
    button.addEventListener('click',()=>action==='locate'?navigate(entry):apply(entry,action))
    row.append(button)
   }
   if(options.onReviewAI){
    const button=document.createElement('button');button.type='button';button.dataset.action='ai-review-revision';button.className=buttonClasses('secondary')
    button.append(createElement(Sparkles,{'aria-hidden':'true',width:18,height:18}),document.createTextNode('AI 审阅修订'))
    const unavailable=reason??(decision?'此来源修订已有决策，请先保存或撤销':locked());button.disabled=!!unavailable;button.title=unavailable??''
    button.onclick=()=>{try{const blocked=locked();if(blocked)throw new Error(blocked);verified(entry);options.onReviewAI?.({blockId:entry.anchor.blockId,revisionId:entry.target.revisionId},'');modal?.close()}catch(error){options.onError(error)}}
    row.append(button)
   }
   list.append(row)
   if(reason&&!reasons.includes(reason))reasons.push(reason)
  }
  const unavailableBatch=batchReason()
  for(const action of ['accept','reject'] as const){
   const button=modal.card.querySelector<HTMLButtonElement>(`[data-action="${action}-all"]`)!
   button.disabled=!!unavailableBatch;button.title=unavailableBatch??'';button.onclick=()=>applyAll(action)
  }
  status.textContent=[`支持的正文修订：${entries.length} 条，已决策 ${resolved} 条。`,locked(),...new Set(reasons)].filter(Boolean).join(' ')
  const next=modal.card.querySelector<HTMLButtonElement>('[data-action="next"]')!
  const unresolved=entries.filter(entry=>{try{return !verified(entry).pending.some(op=>op.revisionId===entry.target.revisionId)}catch{return false}})
  next.disabled=!unresolved.length||!!validationReason
  next.onclick=()=>{const index=unresolved.findIndex(entry=>entry.target.revisionId===selectedId);navigate(unresolved[(index+1)%unresolved.length])}
 }
 const close=()=>{modal?.remove();modal=undefined}
 const open=()=>{
  if(disposed||editor.isDestroyed)return
  if(!modal)modal=createModal({root:options.container,label:'正文修订列表',closeLabel:'关闭正文修订列表',onRequestClose:close,content:'<h2>正文修订列表</h2><p>仅处理列表中受支持的简单正文插入和删除修订；复杂修订和页眉、页脚、脚注等其他故事中的修订均保留。批量操作只处理尚未决策的目标，可一次撤销整批操作。</p><p role="status" aria-live="polite"></p><button type="button" data-action="next">下一条待处理</button><button type="button" data-action="accept-all">接受所有支持的正文修订</button><button type="button" data-action="reject-all">拒绝所有支持的正文修订</button><ol data-revision-list></ol>'})
  refresh();modal.open()
 }
 editor.on('transaction',refresh)
 return {open,refresh,applyAll,batchReason,dispose(){disposed=true;editor.off('transaction',refresh);close()}}
}
