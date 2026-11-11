import type {Editor} from '@tiptap/core'
import {closeHistory} from '@tiptap/pm/history'
import type {DocxPmNode} from './docx-operations'
import type {NativeOperation} from './native-draft'
import {wordRangeAtCaret} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/comments'
import {authorName} from './vendor/genoffice-docs/apps/docs/src/renderer/author-name'
export interface DocxCommentCreationTarget {targetId:string;blockIndex:number;paragraphOrdinal:number;expectedParagraphSha256:string;text:string;readOnlyReason:string|null}
export interface DocxCommentCreationModel {sourceSha256:string;sourceId:string|null;targets:DocxCommentCreationTarget[];readOnlyReason:string|null}
export interface DocxCommentCreationRange {targetId:string;expectedParagraphSha256:string;from:number;to:number;text:string}
export type DocxCommentCreationOperation = {kind:'createComment';sourceId:string;clientId:string;author:string;date:string;text:string;ranges:DocxCommentCreationRange[]}
const intent='nativeCommentCreationOperations',copy=<T>(v:T):T=>structuredClone(v)
const sha=(v:unknown):v is string=>typeof v==='string'&&/^[a-f\d]{64}$/.test(v)
function fail():never{throw new Error('新批注选区或草稿与当前服务端来源不一致；请保留输入并重新选择')}
const exactKeys=(v:unknown,keys:string[]):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join('|')===keys.sort().join('|')
function text(v:unknown,max:number):v is string{return typeof v==='string'&&v.length<=max&&[...v].every(c=>{const n=c.codePointAt(0)!;return n===9||n===10||n>=32&&n<=0xd7ff||n>=0xe000&&n<=0xfffd||n>=0x10000&&n<=0x10ffff})}
const boundary=(t:string,n:unknown):n is number=>typeof n==='number'&&Number.isSafeInteger(n)&&n>=0&&n<=t.length&&!(n>0&&n<t.length&&/[\uD800-\uDBFF]/.test(t[n-1])&&/[\uDC00-\uDFFF]/.test(t[n]))
export function verifiedDocxCommentCreationModel(value:DocxCommentCreationModel,expectedSha:string){
 if(!value||value.sourceSha256!==expectedSha||!sha(value.sourceSha256)||!(value.sourceId===null||sha(value.sourceId))||!Array.isArray(value.targets)||value.targets.length>100000||!(value.readOnlyReason===null||typeof value.readOnlyReason==='string'))fail()
 const seen=new Set<string>()
 for(const t of value.targets){if(!sha(t.targetId)||!sha(t.expectedParagraphSha256)||!Number.isSafeInteger(t.blockIndex)||t.blockIndex<0||!Number.isSafeInteger(t.paragraphOrdinal)||t.paragraphOrdinal<0||typeof t.text!=='string'||!(t.readOnlyReason===null||typeof t.readOnlyReason==='string')||seen.has(t.targetId))fail();seen.add(t.targetId)}
 return copy(value)
}
function checked(value:unknown,model:DocxCommentCreationModel):DocxCommentCreationOperation[]{
 verifiedDocxCommentCreationModel(model,model.sourceSha256)
 if(!Array.isArray(value)||value.length>100)fail()
 const seen=new Set<string>()
 for(const op of value){
  if(!exactKeys(op,['kind','sourceId','clientId','author','date','text','ranges'])||op.kind!=='createComment'||!model.sourceId||model.readOnlyReason||op.sourceId!==model.sourceId||typeof op.clientId!=='string'||!/^[-\w]{1,128}$/.test(op.clientId)||seen.has(op.clientId)||!text(op.author,255)||!op.author.trim()||!text(op.text,65536)||!op.text.trim()||typeof op.date!=='string'||!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(op.date)||!Number.isFinite(Date.parse(op.date))||new Date(op.date).toISOString().replace(/\.\d{3}Z$/,'Z')!==op.date||!Array.isArray(op.ranges)||!op.ranges.length||op.ranges.length>500)fail()
  seen.add(op.clientId);let previous=-1
  for(const [i,r] of op.ranges.entries()){
   if(!exactKeys(r,['targetId','expectedParagraphSha256','from','to','text']))fail()
   const index=model.targets.findIndex(t=>t.targetId===r.targetId),t=model.targets[index]
   if(!t||t.readOnlyReason||r.expectedParagraphSha256!==t.expectedParagraphSha256||!boundary(t.text,r.from)||!boundary(t.text,r.to)||(r.from>r.to||r.from===r.to&&!(t.text.length===0&&i>0&&i<op.ranges.length-1))||r.text!==t.text.slice(r.from,r.to)||i&&(index!==previous+1||r.from!==0||op.ranges[i-1].to!==model.targets[previous].text.length))fail()
   previous=index
  }
 }
 return copy(value) as DocxCommentCreationOperation[]
}
export function docxCommentCreationsOf(doc:DocxPmNode,model?:DocxCommentCreationModel):DocxCommentCreationOperation[]{
 const value=doc.attrs?.[intent];if(value==null)return[];if(!model)fail();return checked(value,model)
}
export function normalizeDocxCommentCreation(baseline:DocxPmNode,live:DocxPmNode,model?:DocxCommentCreationModel){
 const current=copy(live),operations=docxCommentCreationsOf(current,model)
 const walk=(n:DocxPmNode,root=false)=>{if(!root&&n.attrs?.[intent]!=null)fail();n.content?.forEach(c=>walk(c))};walk(current,true)
 current.attrs={...current.attrs};delete current.attrs[intent];if(!Object.keys(current.attrs).length)delete current.attrs
 if(baseline.attrs?.[intent]!=null)fail()
 return{current,operations}
}
export function replayDocxCommentCreation(doc:DocxPmNode,operations:readonly NativeOperation[],model:DocxCommentCreationModel):DocxPmNode{
 const current=copy(doc),valid=checked(operations,model);current.attrs={...current.attrs,[intent]:valid.length?valid:null};return current
}
export function assertDocxCommentCreationBatch(operations:readonly {kind?:unknown}[]){if(operations.some(o=>o.kind==='createComment')&&operations.some(o=>o.kind!=='createComment'))throw new Error('新建批注需独立保存，请先保存或撤销正文及其他修改')}
/** 与固定源相同：选区按 text node 的 UTF16 边界；空光标使用原 wordRangeAtCaret。 */
export function selectedDocxCommentRanges(editor:Editor,model:DocxCommentCreationModel):DocxCommentCreationRange[]{
 if(model.readOnlyReason||!model.sourceId)throw new Error(model.readOnlyReason??'当前来源不支持新建批注')
 if(editor.state.selection.empty){const word=wordRangeAtCaret(editor);if(!word)throw new Error('请选择要批注的文字，或将光标放在词语内');editor.commands.setTextSelection(word)}
 const {from,to}=editor.state.selection,ranges:DocxCommentCreationRange[]=[]
 editor.state.doc.forEach((block,blockPos)=>{
  let ordinal=0
  const visit=(n:typeof block,pos:number)=>{
   if(!n.isTextblock)return
   const paragraphOrdinal=ordinal++,start=pos+1,end=start+n.content.size
   if(from>=end||to<=start)return false
   const target=model.targets.find(t=>t.blockIndex===block.attrs.docxIndex&&t.paragraphOrdinal===paragraphOrdinal)
   if(!target||target.text!==n.textContent||target.readOnlyReason||Array.from({length:n.childCount},(_,i)=>n.child(i)).some(c=>!c.isText))throw new Error(target?.readOnlyReason??'此选区包含复杂或未核验的正文对象，暂不支持精确批注')
   const a=Math.max(0,from-start),b=Math.min(n.content.size,to-start)
   if(a<b||n.content.size===0)ranges.push({targetId:target.targetId,expectedParagraphSha256:target.expectedParagraphSha256,from:a,to:b,text:target.text.slice(a,b)})
   return false
  }
  if(block.isTextblock)visit(block,blockPos);else block.descendants((n,pos)=>visit(n,blockPos+1+pos))
 })
 while(ranges[0]?.text.length===0)ranges.shift()
 while(ranges.at(-1)?.text.length===0)ranges.pop()
 if(!ranges.length)throw new Error('选区没有可批注的文字')
 checked([{kind:'createComment',sourceId:model.sourceId,clientId:'selection-check',author:'用户',date:'2026-01-01T00:00:00Z',text:'校验',ranges}],model)
 return ranges
}
interface Options {editor:Editor;container:HTMLElement;model?:DocxCommentCreationModel;collectOperations:(doc:DocxPmNode)=>NativeOperation[];readOnlyReason:()=>string|null;onError:(e:unknown)=>void;clientId?:()=>string;now?:()=>Date}
export function createDocxCommentCreationControls(options:Options){
 const {editor,model}=options,panel=document.createElement('section');panel.className='docx-comment-panel docx-comment-create';panel.hidden=true;panel.setAttribute('aria-label','新建批注')
 panel.innerHTML='<h2>新建批注</h2><p>批注绑定所选文字；新建批注需独立保存。复杂锚点会明确提示。</p><blockquote data-new-comment-selection></blockquote><label>批注文字<textarea data-new-comment-text aria-label="新批注文字" rows="5" maxlength="65536"></textarea></label><button type="button" data-new-comment-submit>添加批注</button><button type="button" data-new-comment-cancel>取消新建</button><p role="status" aria-live="polite"></p><ul data-new-comment-list></ul>'
 options.container.append(panel);const input=panel.querySelector<HTMLTextAreaElement>('[data-new-comment-text]')!,status=panel.querySelector<HTMLElement>('[role=status]')!,submit=panel.querySelector<HTMLButtonElement>('[data-new-comment-submit]')!
 let pending:{ranges:DocxCommentCreationRange[];snapshot:typeof editor.state.doc}|undefined,disposed=false
 const reason=()=>options.readOnlyReason()??(!editor.isEditable?'当前文档不可编辑或正在保存':null)??(!model?.sourceId?model?.readOnlyReason??'当前来源未提供新建批注能力':null)
 const refresh=()=>{if(disposed)return;const blocked=reason();input.disabled=!!blocked;submit.disabled=!!blocked;const list=panel.querySelector('[data-new-comment-list]')!;list.replaceChildren(...docxCommentCreationsOf(editor.getJSON(),model).map(op=>{const li=document.createElement('li');li.textContent=op.author+' · '+op.date+'：'+op.text;return li}));if(blocked)status.textContent=blocked}
 const flush=()=>{
  if(!pending||!input.value.trim())return
  const blocked=reason();if(blocked)throw new Error(blocked)
  if(!model||editor.state.doc!==pending.snapshot)fail()
  const operations=docxCommentCreationsOf(editor.getJSON(),model),op:DocxCommentCreationOperation={kind:'createComment',sourceId:model.sourceId!,clientId:options.clientId?.()??crypto.randomUUID(),author:authorName(),date:(options.now?.()??new Date()).toISOString().replace(/\.\d{3}Z$/,'Z'),text:input.value,ranges:pending.ranges}
  const valid=checked([...operations,op],model),tr=closeHistory(editor.state.tr).setDocAttribute(intent,valid);options.collectOperations(tr.doc.toJSON())
  editor.view.dispatch(tr);if(!editor.state.doc.eq(tr.doc))throw new Error('新批注未被编辑器接受；输入已保留')
  pending=undefined;input.value='';panel.querySelector('[data-new-comment-selection]')!.textContent='';status.textContent='批注已加入草稿，可撤销和重做；保存后写入新修订';refresh()
 }
 const show=(e:unknown)=>{status.textContent=e instanceof Error?e.message:String(e);options.onError(e)}
 submit.addEventListener('click',()=>{try{flush()}catch(e){show(e)}})
 panel.querySelector('[data-new-comment-cancel]')!.addEventListener('click',()=>{pending=undefined;input.value='';panel.hidden=true})
 editor.on('transaction',refresh)
 return{openNew(){try{const blocked=reason();if(blocked)throw new Error(blocked);if(!model)return;if(!pending){const ranges=selectedDocxCommentRanges(editor,model);pending={ranges,snapshot:editor.state.doc};input.value='';panel.querySelector('[data-new-comment-selection]')!.textContent=ranges.map(r=>r.text).join('\n')}panel.hidden=false;status.textContent='输入后点击添加批注，或在保存前自动加入草稿；取消不保存';refresh();panel.scrollIntoView?.({block:'nearest'});input.focus({preventScroll:true})}catch(e){show(e)}},flush,refresh,get hasPendingInput(){return !!pending&&!!input.value.trim()},dispose(){disposed=true;editor.off('transaction',refresh);panel.remove()}}
}
