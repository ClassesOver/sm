import {createElement,MessageCircle,Sparkles} from 'lucide'
import type {Editor} from '@tiptap/core'
import {closeHistory} from '@tiptap/pm/history'
import type {NativeOperation} from './native-draft'
import type {DocxPmNode} from './docx-operations'
import {commentTextOperationsOf,editDocxCommentTextOperations,projectedDocxCommentTexts,type DocxCommentTextModel} from './docx-comment-text'
import {docxCommentThreadOperationsOf,projectedDocxCommentThreads,updateDocxCommentThreadOperations,type DocxCommentThreadModel} from './docx-comment-thread'
import {commentAnchors,commentIdsAt} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/comments'
import {TextSelection} from '@tiptap/pm/state'

interface Options {
 editor:Editor;container:HTMLElement;model?:DocxCommentTextModel
 collectOperations:(doc:DocxPmNode)=>NativeOperation[]
 readOnlyReason:()=>string|null;onError:(error:unknown)=>void
 onReply?:(targetId:string)=>void;replyReadOnlyReason?:(targetId:string)=>string|null;parentIdOf?:(targetId:string)=>string|null
 onReviewAI?:(selection:{sourceId:string;targetId:string},instruction?:string)=>void
 thread?:{model:DocxCommentThreadModel;readOnlyReason:()=>string|null}
}
/** 已有批注的文字面板；仅doc属性进历史，正文marks与target身份从不由面板改写。 */
export function createDocxCommentControls(options:Options){
 const {editor,model}=options,panel=document.createElement('section')
 panel.className='docx-comment-panel docx-comment-editor';panel.hidden=true;panel.setAttribute('aria-label','已有批注文字')
 panel.innerHTML='<header><h2>已有批注文字</h2><button type="button" data-comment-title-close aria-label="应用并关闭已有批注">×</button></header><div class="docx-comment-editor-body"><div class="docx-comment-editor-content"><p class="docx-comment-editor-help">仅编辑服务端清单中的已有批注文字；批注修改需独立保存。</p><label>选择批注<select data-comment-target aria-label="选择已有批注"></select></label><div class="docx-comment-editor-meta"><p data-comment-author></p><p data-comment-thread></p></div><label>批注文字<textarea data-comment-text aria-label="批注文字" rows="6" maxlength="65536"></textarea></label><p role="status" aria-live="polite"></p></div><section class="docx-comment-editor-actions" aria-label="批注操作"><h3>批注操作</h3><button type="button" data-comment-apply>应用文字</button><button type="button" data-comment-reply>回复此批注</button><button type="button" data-comment-resolve hidden>解决线程</button><button type="button" data-comment-delete hidden>删除批注</button><button type="button" data-comment-reload hidden>放弃未应用输入并重新载入</button><button type="button" data-comment-close>关闭批注</button></section></div>'
 options.container.append(panel)
 const select=panel.querySelector<HTMLSelectElement>('[data-comment-target]')!,input=panel.querySelector<HTMLTextAreaElement>('[data-comment-text]')!
 const apply=panel.querySelector<HTMLButtonElement>('[data-comment-apply]')!,status=panel.querySelector<HTMLElement>('[role="status"]')!
 const reload=panel.querySelector<HTMLButtonElement>('[data-comment-reload]')!
 const reply=panel.querySelector<HTMLButtonElement>('[data-comment-reply]')!
 const resolve=panel.querySelector<HTMLButtonElement>('[data-comment-resolve]')!,remove=panel.querySelector<HTMLButtonElement>('[data-comment-delete]')!
 const aiReply=document.createElement('button'),aiResolve=document.createElement('button')
 for(const [button,key,label,icon] of [[aiReply,'reply','AI 回复批注',MessageCircle],[aiResolve,'resolve','AI 处理批注',Sparkles]] as const){button.type='button';button.dataset.commentAi=key;button.hidden=!options.onReviewAI;button.append(createElement(icon,{'aria-hidden':'true',width:18,height:18}),document.createTextNode(label));panel.querySelector('.docx-comment-editor-actions')!.append(button)}
 const threadModel=options.thread?.model
 resolve.hidden=remove.hidden=!threadModel
 let opener:HTMLElement|null=null
 let selectedId=model?.commentTargets[0]?.targetId,dirty=false,disposed=false,snapshot=editor.state.doc
 const threadEntries=()=>threadModel?projectedDocxCommentThreads(threadModel.targets.map(t=>({...t,id:t.originalCommentId})),editor.getJSON(),threadModel):[]
 const navigableComments=()=>{
  if(!model||!threadModel||model.sourceId!==threadModel.sourceId)return[]
  const byOriginalId=new Map<string,typeof model.commentTargets>()
  for(const target of model.commentTargets){const values=byOriginalId.get(target.originalCommentId)??[];values.push(target);byOriginalId.set(target.originalCommentId,values)}
  const anchors=commentAnchors(editor.state.doc),threads=threadEntries()
  return threadModel.targets.filter(target=>target.parentId===null&&!target.done&&threads.some(thread=>thread.id===target.originalCommentId&&!thread.done))
   .flatMap(target=>{
    const textTargets=byOriginalId.get(target.originalCommentId)??[],anchorMatches=anchors.filter(anchor=>anchor.id===target.originalCommentId)
    return textTargets.length===1&&anchorMatches.length===1?[{target,anchor:anchorMatches[0]}]:[]
   }).sort((a,b)=>a.anchor.from-b.anchor.from)
 }
 const navigationReason=()=>disposed||editor.isDestroyed?'批注导航已关闭':navigableComments().length?'':'当前没有可定位的可信未解决批注'
 const navigate=(dir:1|-1,event?:{currentTarget:EventTarget|null})=>{
  if(navigationReason())return false
  const anchors=navigableComments(),from=editor.state.selection.from
  const target=dir===1?(anchors.find(item=>item.anchor.from>from)??anchors[0]):([...anchors].reverse().find(item=>item.anchor.to<=from&&item.anchor.from<from)??anchors[anchors.length-1])
  const tr=editor.state.tr.setSelection(TextSelection.between(editor.state.doc.resolve(target.anchor.from),editor.state.doc.resolve(target.anchor.to))).setMeta('addToHistory',false).scrollIntoView()
  editor.view.dispatch(tr);editor.view.focus();selectedId=target.target.targetId;open(event);return true
 }
 const entries=()=>{
  if(!model)return[]
  const entries=projectedDocxCommentTexts(model,commentTextOperationsOf(editor.getJSON(),model))
  if(!threadModel)return entries
  const visible=new Set(threadEntries().map(t=>t.targetId))
  return entries.filter(entry=>!threadModel.targets.some(t=>t.targetId===entry.targetId)||visible.has(entry.targetId))
 }
 const selected=()=>entries().find(entry=>entry.targetId===selectedId)
 const reason=()=>options.readOnlyReason()??(!editor.isEditable?'当前文档不可编辑或正在保存':null)
 const threadReason=()=>options.thread?.readOnlyReason()??(!editor.isEditable?'当前文档不可编辑或正在保存':null)??threadModel?.readOnlyReason
 const deleteTargetAtCaret=()=>{
  if(!model||!threadModel||model.sourceId!==threadModel.sourceId)return null
  for(const id of commentIdsAt(editor.state,editor.state.selection.from)){
   const projected=threadEntries(),hit=projected.find(target=>target.originalCommentId===id)
   if(!hit)continue
   const rootId=hit.parentId??hit.originalCommentId
   const root=projected.find(target=>target.originalCommentId===rootId)
   if(root)return root
  }
  return null
 }
 const deleteAtCaretReason=()=>{
  const blocked=threadReason();if(blocked)return blocked
  const target=deleteTargetAtCaret()
  return !target?'当前没有可删除的可信批注':target.canDelete?null:target.threadReadOnlyReason??'当前批注不能删除'
 }
 const deleteAllTargets=(resolvedOnly:boolean)=>{
  if(!threadModel||!model||model.sourceId!==threadModel.sourceId)return[]
  const projected=threadEntries(),visible=new Set(projected.map(target=>target.originalCommentId))
  const roots=threadModel.targets.filter(target=>target.parentId===null&&visible.has(target.originalCommentId))
   .filter(target=>!resolvedOnly||projected.find(item=>item.originalCommentId===target.originalCommentId)?.done)
  return roots
 }
 const deleteAllReason=(resolvedOnly:boolean)=>{
  const blocked=threadReason();if(blocked)return blocked
  const roots=deleteAllTargets(resolvedOnly)
  if(!roots.length)return resolvedOnly?'当前没有可删除的可信已解决批注':'当前没有可删除的可信批注'
  for(const root of roots){
   const members=threadModel!.targets.filter(target=>target.originalCommentId===root.originalCommentId||target.parentId===root.originalCommentId)
   if(!members.length||members.some(member=>!member.canDelete))return root.threadReadOnlyReason??members.find(member=>member.threadReadOnlyReason)?.threadReadOnlyReason??'所选批注线程不能删除'
  }
  return null
 }
 const deleteAll=(resolvedOnly:boolean)=>{
  try{
   const unavailable=deleteAllReason(resolvedOnly);if(unavailable)return false
   flush()
   const roots=deleteAllTargets(resolvedOnly)
   if(!roots.length)return false
   if(model&&commentTextOperationsOf(editor.getJSON(),model).length)throw new Error('批注线程修改需独立保存，请先保存批注文字')
   if(!window.confirm(resolvedOnly?'删除所有已解决的批注？':'删除文档中的所有批注？'))return false
   let operations=docxCommentThreadOperationsOf(editor.getJSON(),threadModel)
   for(const target of roots)operations=updateDocxCommentThreadOperations(threadModel!,operations,target.targetId)
   const tr=closeHistory(editor.state.tr).setDocAttribute('nativeCommentThreadOperations',operations.length?operations:null)
   options.collectOperations(tr.doc.toJSON());editor.view.dispatch(tr)
   if(!editor.state.doc.eq(tr.doc))throw new Error('批注线程修改未被编辑器接受')
   refresh();return true
  }catch(error){showError(error);return false}
 }
 const showError=(error:unknown)=>{status.textContent=error instanceof Error?error.message:String(error);options.onError(error)}
 const refresh=()=>{
  if(disposed||editor.isDestroyed)return
  try{
   const list=entries()
   if(!dirty&&!list.some(item=>item.targetId===selectedId))selectedId=list[0]?.targetId
   const entry=list.find(item=>item.targetId===selectedId),target=threadEntries().find(t=>t.targetId===selectedId)
   select.replaceChildren(...list.map(item=>{const option=document.createElement('option');option.value=item.targetId;option.textContent=(item.ordinal+1)+' · '+(item.author||'未知作者')+'：'+item.text.slice(0,40);return option}))
   select.value=selectedId??'';select.disabled=!list.length
   if(!dirty){input.value=entry?.text??'';snapshot=editor.state.doc}
   reload.hidden=!dirty
   const blocked=reason()??model?.commentReadOnlyReason??entry?.readOnlyReason??(!entry?'当前来源未提供可编辑的已有批注':null)
   input.disabled=!!blocked||!entry?.editableText;apply.disabled=input.disabled
   const parentId=target?.parentId??(selectedId?options.parentIdOf?.(selectedId):null)
   panel.querySelector<HTMLElement>('[data-comment-thread]')!.textContent=[parentId?'回复根批注 #'+parentId:'',target?.done?'线程已解决':''].filter(Boolean).join(' · ')
   const threadBlocked=threadReason(),unavailable=threadBlocked??target?.threadReadOnlyReason??'当前批注操作不可用'
   resolve.disabled=!!threadBlocked||!target?.canResolve;resolve.title=resolve.disabled?unavailable:''
   remove.disabled=!!threadBlocked||!target?.canDelete;remove.title=remove.disabled?unavailable:''
   aiResolve.disabled=!options.onReviewAI||!!threadBlocked||!target?.canResolve||!!parentId
   resolve.textContent=target?.done?'重新打开线程':'解决线程'
   remove.textContent=target?.parentId?'删除回复':'删除批注'
   const replyBlocked=!entry?'请选择可信根批注':options.replyReadOnlyReason?.(entry.targetId)
   aiReply.disabled=!options.onReviewAI||!!reason()||!!replyBlocked||!!parentId
   reply.hidden=!options.onReply;reply.disabled=!options.onReply||!!replyBlocked;reply.title=replyBlocked??'回复此根批注'
   panel.querySelector<HTMLElement>('[data-comment-author]')!.textContent=entry?entry.author+(entry.date?' · '+entry.date:''):''
   const threadPending=docxCommentThreadOperationsOf(editor.getJSON(),threadModel).length>0
   status.textContent=threadPending?'已加入草稿，可撤销或重做；保存后写入新修订':blocked??(dirty?'批注文字尚未应用，将在保存前应用':entry?.pending?'此批注有未保存修改':'修改可使用撤销和重做恢复')
  }catch(error){input.disabled=true;apply.disabled=true;resolve.disabled=true;remove.disabled=true;showError(error)}
 }
 const applyThread=(deleting:boolean)=>{
  const blocked=threadReason();if(blocked)throw new Error(blocked)
  flush()
  const target=threadEntries().find(t=>t.targetId===selectedId)
  if(!threadModel||!target||(deleting?!target.canDelete:!target.canResolve))throw new Error(target?.threadReadOnlyReason??'当前批注操作不可用')
  if(deleting&&model&&commentTextOperationsOf(editor.getJSON(),model).length)throw new Error('批注线程修改需独立保存，请先保存批注文字')
  if(deleting&&!window.confirm(target.parentId?'删除这条回复？':'删除此批注及其回复？'))return
  const operations=updateDocxCommentThreadOperations(threadModel,docxCommentThreadOperationsOf(editor.getJSON(),threadModel),target.targetId,deleting?undefined:!target.done)
  const tr=closeHistory(editor.state.tr).setDocAttribute('nativeCommentThreadOperations',operations.length?operations:null)
  options.collectOperations(tr.doc.toJSON());editor.view.dispatch(tr)
  if(!editor.state.doc.eq(tr.doc))throw new Error('批注线程修改未被编辑器接受')
  refresh()
 }
 const deleteAtCaret=()=>{
  try{
   if(deleteAtCaretReason())return false
   const target=deleteTargetAtCaret();if(!target)return false
   if(target.targetId!==selectedId)flush()
   selectedId=target.targetId
   applyThread(true)
   return true
  }catch(error){showError(error);return false}
 }
 resolve.addEventListener('click',()=>{try{applyThread(false)}catch(error){showError(error)}})
 remove.addEventListener('click',()=>{try{applyThread(true)}catch(error){showError(error)}})
 const flush=()=>{
  if(!dirty)return
  const blocked=reason();if(blocked)throw new Error(blocked)
  if(!model||!selectedId||editor.state.doc!==snapshot)throw new Error('文档或批注来源已经变化，请保留输入并重新打开批注')
  const entry=selected();if(!entry?.editableText)throw new Error(entry?.readOnlyReason??'此批注仅可查看')
  const operations=editDocxCommentTextOperations(model,commentTextOperationsOf(editor.getJSON(),model),selectedId,input.value)
  const current=commentTextOperationsOf(editor.getJSON(),model)
  if(JSON.stringify(current)===JSON.stringify(operations)){dirty=false;refresh();return}
  const tr=closeHistory(editor.state.tr).setDocAttribute('nativeCommentTextOperations',operations.length?operations:null)
  options.collectOperations(tr.doc.toJSON())
  dirty=false;editor.view.dispatch(tr)
  if(!editor.state.doc.eq(tr.doc)){dirty=true;throw new Error('批注文字未被编辑器接受；输入已保留')}
  refresh()
 }
 const openAI=(replying:boolean)=>{try{
  flush()
  const target=selected(),thread=threadEntries().find(t=>t.targetId===selectedId)
  if(!target || (thread?.parentId??options.parentIdOf?.(target.targetId)))throw new Error('请选择可信根批注')
  const blocked=replying?options.replyReadOnlyReason?.(target.targetId):threadReason()
  if(blocked)throw new Error(blocked)
  if(!replying&&!thread?.canResolve)throw new Error('当前批注不能处理线程状态')
  options.onReviewAI?.({sourceId:target.sourceId,targetId:target.targetId},'')
 }catch(error){showError(error)}}
 aiReply.addEventListener('click',()=>openAI(true));aiResolve.addEventListener('click',()=>openAI(false))
 reply.addEventListener('click',()=>{try{flush();if(selectedId)options.onReply?.(selectedId)}catch(error){showError(error)}})
 input.addEventListener('focus',()=>input.scrollIntoView?.({block:'nearest'}))
 input.addEventListener('input',()=>{if(!dirty)snapshot=editor.state.doc;dirty=true;reload.hidden=false;status.textContent='批注文字尚未应用，将在保存前应用'})
 reload.addEventListener('click',()=>{dirty=false;snapshot=editor.state.doc;refresh()})
 input.addEventListener('blur',event=>{if(event.relatedTarget===reload)return;try{flush()}catch(error){showError(error)}})
 apply.addEventListener('click',()=>{try{flush()}catch(error){showError(error)}})
 select.addEventListener('change',()=>{const next=select.value;try{flush();selectedId=next;refresh()}catch(error){select.value=selectedId??'';showError(error)}})
 const close=()=>{try{flush();panel.hidden=true;if(opener?.isConnected)opener.focus({preventScroll:true})}catch(error){showError(error)}}
 panel.querySelector<HTMLButtonElement>('[data-comment-close]')!.addEventListener('click',close)
 panel.querySelector<HTMLButtonElement>('[data-comment-title-close]')!.addEventListener('click',close)
 editor.on('transaction',refresh)
 const open=(event?:{currentTarget:EventTarget|null})=>{if(disposed)return;if(panel.hidden)opener=event?.currentTarget instanceof HTMLElement?event.currentTarget:document.activeElement instanceof HTMLElement?document.activeElement:null;panel.hidden=false;refresh();panel.scrollIntoView?.({block:'nearest'});if(!input.disabled)input.focus({preventScroll:true});else if(!select.disabled)select.focus({preventScroll:true});else panel.querySelector<HTMLButtonElement>('[data-comment-title-close]')!.focus({preventScroll:true})}
 const toggle=(event?:{currentTarget:EventTarget|null})=>{if(disposed)return;if(panel.hidden)open(event);else close()}
 return {open,toggle,navigate,navigationReason,deleteAtCaret,deleteAtCaretReason,deleteAll,deleteAllReason,get visible(){return !disposed&&!panel.hidden},refresh,flush,get hasPendingInput(){return dirty},
  dispose(){disposed=true;editor.off('transaction',refresh);panel.remove()}}
}
