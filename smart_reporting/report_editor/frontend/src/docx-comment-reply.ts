import type {Editor} from '@tiptap/core'
import {closeHistory} from '@tiptap/pm/history'
import type {DocxPmNode} from './docx-operations'
import type {NativeOperation} from './native-draft'
import {verifiedDocxCommentTextModel,type DocxCommentTextTarget} from './docx-comment-text'
import {authorName} from './vendor/genoffice-docs/apps/docs/src/renderer/author-name'
export interface DocxCommentReplyTarget extends DocxCommentTextTarget {parentId:string|null;canReply:boolean;replyReadOnlyReason:string|null}
export interface DocxCommentReplyModel {sourceSha256:string;sourceId:string|null;targets:DocxCommentReplyTarget[];readOnlyReason:string|null}
export type DocxCommentReplyOperation={kind:'replyComment';sourceId:string;targetId:string;expectedCommentsSha256:string;expectedObjectSha256:string;clientId:string;author:string;date:string;text:string}
const intent='nativeCommentReplyOperations',copy=<T>(v:T):T=>structuredClone(v)
function fail():never{throw new Error('批注回复或父线程与当前服务端来源不一致；请保留输入后重新打开')}
function text(v:unknown,max:number):v is string{return typeof v==='string'&&v.length<=max&&[...v].every(c=>{const n=c.codePointAt(0)!;return n===9||n===10||n>=32&&n<=0xd7ff||n>=0xe000&&n<=0xfffd||n>=0x10000&&n<=0x10ffff})}
function checkedModel(model:DocxCommentReplyModel,expectedSha=model.sourceSha256){
 if(!model||!Array.isArray(model.targets)||!(model.readOnlyReason===null||typeof model.readOnlyReason==='string'))fail()
 const parsed=model.targets.map(t=>({id:t.originalCommentId,author:t.author,text:t.text,date:t.date??undefined,initials:t.initials??undefined}))
 verifiedDocxCommentTextModel({sourceSha256:model.sourceSha256,sourceId:model.sourceId,commentTargets:model.targets,commentReadOnlyReason:model.readOnlyReason},expectedSha,parsed)
 for(const t of model.targets){if(!(t.parentId===null||typeof t.parentId==='string')||typeof t.canReply!=='boolean'||!(t.replyReadOnlyReason===null||typeof t.replyReadOnlyReason==='string')||t.canReply&&(t.parentId!==null||t.replyReadOnlyReason!==null||!t.editableText||t.readOnlyReason!==null))fail()}
 return model
}
export function verifiedDocxCommentReplyModel(model:DocxCommentReplyModel,expectedSha:string,parsed:readonly {id:string;author:string;text:string;date?:string;initials?:string;parentId?:string}[]){
 const result=copy(checkedModel(model,expectedSha)),verified=verifiedDocxCommentTextModel({sourceSha256:model.sourceSha256,sourceId:model.sourceId,commentTargets:model.targets,commentReadOnlyReason:model.readOnlyReason},expectedSha,parsed)
 for(const [i,target] of result.targets.entries()){
  const actual=parsed.filter(c=>c.id===target.originalCommentId)
  if(!verified.commentTargets[i].editableText||actual.length!==1||(actual[0].parentId??null)!==target.parentId){target.canReply=false;target.replyReadOnlyReason='批注线程显示与服务端来源不一致，仅可查看原文'}
 }
 return result
}
function checked(value:unknown,model:DocxCommentReplyModel):DocxCommentReplyOperation[]{
 checkedModel(model);if(!Array.isArray(value)||value.length>100)fail()
 const seen=new Set<string>()
 for(const op of value){
  if(!op||typeof op!=='object'||Array.isArray(op)||Object.keys(op).sort().join('|')!==['kind','sourceId','targetId','expectedCommentsSha256','expectedObjectSha256','clientId','author','date','text'].sort().join('|'))fail()
  const target=model.targets.find(t=>t.targetId===op.targetId)
  if(op.kind!=='replyComment'||model.readOnlyReason||!target?.canReply||target.parentId!==null||op.sourceId!==model.sourceId||op.expectedCommentsSha256!==target.expectedCommentsSha256||op.expectedObjectSha256!==target.expectedObjectSha256||typeof op.clientId!=='string'||!/^[-\w]{1,128}$/.test(op.clientId)||seen.has(op.clientId)||!text(op.author,255)||!op.author.trim()||!text(op.text,65536)||!op.text.trim()||typeof op.date!=='string'||!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(op.date)||!Number.isFinite(Date.parse(op.date))||new Date(op.date).toISOString().replace(/\.\d{3}Z$/,'Z')!==op.date)fail()
  seen.add(op.clientId)
 }
 return copy(value) as DocxCommentReplyOperation[]
}
export function docxCommentRepliesOf(doc:DocxPmNode,model?:DocxCommentReplyModel):DocxCommentReplyOperation[]{const value=doc.attrs?.[intent];if(value==null)return[];if(!model)fail();return checked(value,model)}
export function normalizeDocxCommentReplies(baseline:DocxPmNode,live:DocxPmNode,model?:DocxCommentReplyModel){
 const current=copy(live),operations=docxCommentRepliesOf(current,model)
 const visit=(n:DocxPmNode,root=false)=>{if(!root&&n.attrs?.[intent]!=null)fail();n.content?.forEach(c=>visit(c))};visit(current,true)
 current.attrs={...current.attrs};delete current.attrs[intent];if(!Object.keys(current.attrs).length)delete current.attrs
 if(baseline.attrs?.[intent]!=null)fail();return{current,operations}
}
export function replayDocxCommentReplies(doc:DocxPmNode,operations:readonly NativeOperation[],model:DocxCommentReplyModel):DocxPmNode{const result=copy(doc),valid=checked(operations,model);result.attrs={...result.attrs,[intent]:valid.length?valid:null};return result}
export function assertDocxCommentReplyBatch(operations:readonly {kind?:unknown}[]){if(operations.some(o=>o.kind==='replyComment')&&operations.some(o=>o.kind!=='replyComment'))throw new Error('批注回复需独立保存，请先保存或撤销正文及其他修改')}
interface Options {editor:Editor;container:HTMLElement;model?:DocxCommentReplyModel;collectOperations:(doc:DocxPmNode)=>NativeOperation[];readOnlyReason:()=>string|null;onError:(e:unknown)=>void;clientId?:()=>string;now?:()=>Date}
export function createDocxCommentReplyControls(options:Options){
 const {editor,model}=options,panel=document.createElement('section');panel.className='docx-comment-panel docx-comment-reply';panel.hidden=true;panel.setAttribute('aria-label','回复已有批注')
 panel.innerHTML='<header><h2>回复已有批注</h2><button type="button" data-comment-reply-close aria-label="取消并关闭批注回复">×</button></header><div class="docx-comment-reply-body"><div class="docx-comment-reply-composer"><p class="docx-comment-reply-help">回复绑定当前根线程的原文字范围，需独立保存。</p><blockquote data-comment-reply-parent role="region" aria-label="回复的根批注" tabindex="0"></blockquote><label>回复文字<textarea data-comment-reply-text aria-label="批注回复文字" rows="5" maxlength="65536"></textarea></label><div class="docx-comment-reply-actions"><button type="button" data-comment-reply-submit>添加回复</button><button type="button" data-comment-reply-cancel>取消回复</button></div><p role="status" aria-live="polite"></p></div><section class="docx-comment-reply-drafts" aria-label="批注回复草稿"><h3>待保存的批注回复</h3><p data-comment-reply-empty>暂无待保存的回复</p><ul data-comment-reply-list aria-label="待保存的批注回复" tabindex="0" hidden></ul></section></div>'
 options.container.append(panel)
 const input=panel.querySelector<HTMLTextAreaElement>('[data-comment-reply-text]')!,status=panel.querySelector<HTMLElement>('[role=status]')!,submit=panel.querySelector<HTMLButtonElement>('[data-comment-reply-submit]')!
 const list=panel.querySelector<HTMLUListElement>('[data-comment-reply-list]')!,cancel=panel.querySelector<HTMLButtonElement>('[data-comment-reply-cancel]')!
 let opener:HTMLElement|null=null
 let pending:{targetId:string;snapshot:typeof editor.state.doc}|undefined,disposed=false
 let message='回复将在添加或保存时加入草稿'
 const reason=()=>options.readOnlyReason()??(!editor.isEditable?'当前文档不可编辑或正在保存':null)??(!model?.sourceId?model?.readOnlyReason??'当前来源未提供批注回复能力':null)
 const refresh=()=>{if(disposed)return;const blocked=reason(),listFocused=document.activeElement===list;input.disabled=!!blocked;submit.disabled=!!blocked;const operations=docxCommentRepliesOf(editor.getJSON(),model);list.replaceChildren(...operations.map(op=>{const li=document.createElement('li'),meta=document.createElement('div'),author=document.createElement('strong'),time=document.createElement('time'),body=document.createElement('p'),parent=model?.targets.find(t=>t.targetId===op.targetId);author.textContent=op.author+' · 回复 '+(parent?.author??'');time.dateTime=op.date;time.textContent=op.date;body.textContent=op.text;meta.append(author,time);li.append(meta,body);return li}));list.hidden=!operations.length;panel.querySelector<HTMLElement>('[data-comment-reply-empty]')!.hidden=!!operations.length;status.textContent=blocked??message;if(list.hidden&&listFocused&&!panel.hidden)(input.disabled?cancel:input).focus({preventScroll:true})}
 const flush=()=>{
  if(!pending||!input.value.trim())return
  const blocked=reason();if(blocked)throw new Error(blocked)
  if(!model||editor.state.doc!==pending.snapshot)fail()
  const target=model.targets.find(t=>t.targetId===pending!.targetId);if(!target?.canReply)fail()
  const op:DocxCommentReplyOperation={kind:'replyComment',sourceId:target.sourceId,targetId:target.targetId,expectedCommentsSha256:target.expectedCommentsSha256,expectedObjectSha256:target.expectedObjectSha256,clientId:options.clientId?.()??crypto.randomUUID(),author:authorName(),date:(options.now?.()??new Date()).toISOString().replace(/\.\d{3}Z$/,'Z'),text:input.value}
  const operations=checked([...docxCommentRepliesOf(editor.getJSON(),model),op],model),tr=closeHistory(editor.state.tr).setDocAttribute(intent,operations)
  options.collectOperations(tr.doc.toJSON());editor.view.dispatch(tr);if(!editor.state.doc.eq(tr.doc))throw new Error('批注回复未被编辑器接受；输入已保留')
  pending=undefined;input.value='';message='回复已加入草稿，可撤销和重做；保存后写入新修订';refresh()
 }
 const show=(e:unknown)=>{message=e instanceof Error?e.message:String(e);status.textContent=message;options.onError(e)}
 submit.addEventListener('click',()=>{try{flush()}catch(e){show(e)}})
 const close=()=>{pending=undefined;input.value='';panel.hidden=true;if(opener?.isConnected)opener.focus({preventScroll:true})}
 cancel.addEventListener('click',close);panel.querySelector('[data-comment-reply-close]')!.addEventListener('click',close)
 input.addEventListener('focus',()=>input.scrollIntoView?.({block:'nearest'}))
 editor.on('transaction',refresh)
 return{openFor(targetId:string){try{const blocked=reason();if(blocked)throw new Error(blocked);const target=model?.targets.find(t=>t.targetId===targetId);if(!target?.canReply||target.parentId!==null)throw new Error(target?.replyReadOnlyReason??'此批注未提供可信根线程回复能力');if(pending&&pending.targetId!==targetId&&input.value.trim())throw new Error('请先添加或取消当前回复，输入已保留');if(!pending||pending.targetId!==targetId){pending={targetId,snapshot:editor.state.doc};input.value='';message='回复将在添加或保存时加入草稿'}if(panel.hidden)opener=document.activeElement instanceof HTMLElement?document.activeElement:null;panel.hidden=false;panel.querySelector('[data-comment-reply-parent]')!.textContent=target.author+'：'+target.text;refresh();panel.scrollIntoView?.({block:'nearest'});input.focus({preventScroll:true})}catch(e){show(e)}},flush,refresh,get hasPendingInput(){return !!pending&&!!input.value.trim()},dispose(){disposed=true;editor.off('transaction',refresh);panel.remove()}}
}
