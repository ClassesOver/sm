/** 可信书签范围只保存原生意图；PM doc attr 提供实际 Undo/Redo，不改变正文节点。 */
import type {Editor} from '@tiptap/core'
import {closeHistory} from '@tiptap/pm/history'
import type {DocxPmNode} from './docx-operations'
import type {NativeOperation} from './native-draft'
export interface DocxBookmarkRange {targetId:string;expectedParagraphSha256:string;from:number;to:number;text:string}
export interface DocxBookmarkTarget {targetId:string;blockIndex:number;paragraphOrdinal:0;expectedParagraphSha256:string;text:string;readOnlyReason:string|null}
export interface DocxBookmarkEntry {bookmarkId:string;name:string;ranges:DocxBookmarkRange[];readOnlyReason:string|null}
export interface DocxBookmarksModel {sourceSha256:string;sourceId:string|null;targets:DocxBookmarkTarget[];bookmarks:DocxBookmarkEntry[];readOnlyReason:string|null}
export type DocxBookmarkOperation = {kind:'createBookmark';sourceId:string;name:string;ranges:DocxBookmarkRange[]}|{kind:'deleteBookmark';sourceId:string;bookmarkId:string}
const intent='nativeBookmarkOperations',copy=<T>(v:T):T=>structuredClone(v),sha=(v:unknown):v is string=>typeof v==='string'&&/^[a-f\d]{64}$/.test(v)
function fail():never{throw new Error('书签选区或草稿与可信来源不一致，请重新选择')}
const exact=(o:unknown,keys:string[]):o is Record<string,unknown>=>!!o&&typeof o==='object'&&!Array.isArray(o)&&Object.keys(o).sort().join('|')===keys.sort().join('|')
const validName=(n:unknown):n is string=>typeof n==='string'&&n.length<=40&&/^[A-Za-z_一-鿿][\w一-鿿]*$/.test(n)
const boundary=(t:string,n:unknown):n is number=>typeof n==='number'&&Number.isSafeInteger(n)&&n>=0&&n<=t.length&&!(n>0&&n<t.length&&/[\uD800-\uDBFF]/.test(t[n-1])&&/[\uDC00-\uDFFF]/.test(t[n]))
function rangesOf(v:unknown,m:DocxBookmarksModel,creating=true):DocxBookmarkRange[]{
 if(!Array.isArray(v)||!v.length||v.length>500)fail()
 for(const [i,r]of v.entries()){
  if(!exact(r,['targetId','expectedParagraphSha256','from','to','text']))fail()
  const t=m.targets.find(t=>t.targetId===r.targetId)
  if(!t||t.readOnlyReason||r.expectedParagraphSha256!==t.expectedParagraphSha256||!boundary(t.text,r.from)||!boundary(t.text,r.to)||r.from>r.to||creating&&r.from===r.to&&!(t.text.length===0&&i>0&&i<v.length-1)||r.text!==t.text.slice(r.from,r.to))fail()
  if(i){const prev=v[i-1],p=m.targets.find(t=>t.targetId===prev.targetId)!;if(t.blockIndex!==p.blockIndex+1||r.from!==0||prev.to!==p.text.length)fail()}
 }
 return copy(v)
}
export function verifiedDocxBookmarksModel(m:DocxBookmarksModel,expectedSha:string){
 if(!m||m.sourceSha256!==expectedSha||!sha(m.sourceSha256)||!(m.sourceId===null||sha(m.sourceId))||!Array.isArray(m.targets)||m.targets.length>100000||!Array.isArray(m.bookmarks)||m.bookmarks.length>100000||!(m.readOnlyReason===null||typeof m.readOnlyReason==='string'))fail()
 const targets=new Set<string>(),blocks=new Set<number>(),books=new Set<string>()
 for(const t of m.targets){if(!sha(t.targetId)||!sha(t.expectedParagraphSha256)||!Number.isSafeInteger(t.blockIndex)||t.blockIndex<0||t.paragraphOrdinal!==0||typeof t.text!=='string'||!(t.readOnlyReason===null||typeof t.readOnlyReason==='string')||targets.has(t.targetId)||blocks.has(t.blockIndex))fail();targets.add(t.targetId);blocks.add(t.blockIndex)}
 for(const b of m.bookmarks){if(!sha(b.bookmarkId)||typeof b.name!=='string'||!(b.readOnlyReason===null||typeof b.readOnlyReason==='string')||!Array.isArray(b.ranges)||books.has(b.bookmarkId))fail();books.add(b.bookmarkId);if(!m.readOnlyReason&&!b.readOnlyReason)rangesOf(b.ranges,m,false)}
 return copy(m)
}
function checked(v:unknown,m:DocxBookmarksModel):DocxBookmarkOperation[]{
 verifiedDocxBookmarksModel(m,m.sourceSha256);if(!Array.isArray(v)||v.length>100||v.length&&(!m.sourceId||m.readOnlyReason))fail()
 const names=new Set(m.bookmarks.map(b=>b.name)),deleted=new Set<string>()
 for(const op of v){if(op?.sourceId!==m.sourceId)fail()
  if(op.kind==='createBookmark'){if(!exact(op,['kind','sourceId','name','ranges'])||!validName(op.name)||names.has(op.name))fail();names.add(op.name);rangesOf(op.ranges,m)}
  else if(op.kind==='deleteBookmark'){if(!exact(op,['kind','sourceId','bookmarkId'])||typeof op.bookmarkId!=='string')fail();const id=op.bookmarkId,b=m.bookmarks.find(b=>b.bookmarkId===id);if(!b||b.readOnlyReason||deleted.has(id))fail();deleted.add(id)}
  else fail()
 }
 return copy(v)
}
export function docxBookmarksOf(doc:DocxPmNode,model?:DocxBookmarksModel):DocxBookmarkOperation[]{const value=doc.attrs?.[intent];if(value==null)return[];if(!model)fail();return checked(value,model)}
export function normalizeDocxBookmarks(baseline:DocxPmNode,live:DocxPmNode,model?:DocxBookmarksModel){
 const current=copy(live),operations=docxBookmarksOf(current,model)
 const walk=(n:DocxPmNode,root=false)=>{if(!root&&n.attrs?.[intent]!=null)fail();n.content?.forEach(c=>walk(c))};walk(current,true)
 current.attrs={...current.attrs};delete current.attrs[intent];if(!Object.keys(current.attrs).length)delete current.attrs
 if(baseline.attrs?.[intent]!=null)fail();return{current,operations}
}
export function replayDocxBookmarks(doc:DocxPmNode,operations:readonly NativeOperation[],model:DocxBookmarksModel){const current=copy(doc),valid=checked(operations,model);current.attrs={...current.attrs,[intent]:valid.length?valid:null};return current}
export function assertDocxBookmarksBatch(ops:readonly {kind?:unknown}[]){if(ops.some(op=>['createBookmark','deleteBookmark'].includes(String(op.kind)))&&ops.some(op=>!['createBookmark','deleteBookmark'].includes(String(op.kind))))throw new Error('书签修改需独立保存，请先保存或撤销其它修改')}
/** 普通顶层正文按原段落 UTF16 选区；不把光标扩展为词或整个段落。 */
export function selectedDocxBookmarkRanges(editor:Editor,m:DocxBookmarksModel):DocxBookmarkRange[]{
 if(m.readOnlyReason||!m.sourceId)throw new Error(m.readOnlyReason??'当前来源不支持书签')
 const {from,to,empty}=editor.state.selection;if(empty)throw new Error('请选择要添加书签的正文文字')
 const ranges:DocxBookmarkRange[]=[]
 editor.state.doc.forEach((n,pos)=>{
  if(from>=pos+n.nodeSize-1||to<=pos+1)return
  const t=m.targets.find(t=>t.blockIndex===n.attrs.docxIndex)
  if(!n.isTextblock||!t||t.readOnlyReason||t.text!==n.textContent||Array.from({length:n.childCount},(_,i)=>n.child(i)).some(c=>!c.isText))throw new Error(t?.readOnlyReason??'选区包含复杂或未核验的正文对象')
  const a=Math.max(0,from-pos-1),b=Math.min(n.content.size,to-pos-1);if(a<b||!n.content.size)ranges.push({targetId:t.targetId,expectedParagraphSha256:t.expectedParagraphSha256,from:a,to:b,text:t.text.slice(a,b)})
 })
 while(ranges[0]?.text==='')ranges.shift();while(ranges.at(-1)?.text==='')ranges.pop();return rangesOf(ranges,m)
}
interface Options {editor:Editor;container:HTMLElement;model?:DocxBookmarksModel;collectOperations:(doc:DocxPmNode)=>NativeOperation[];readOnlyReason:()=>string|null;onError:(e:unknown)=>void}
export function createDocxBookmarksControls(options:Options){
 const {editor,model:m}=options,panel=document.createElement('section');panel.className='docx-comment-panel docx-bookmarks';panel.hidden=true;panel.setAttribute('aria-label','书签')
 panel.innerHTML='<h2>书签</h2><p>书签绑定所选普通正文；书签修改需独立保存。</p><label>书签名称<input data-bookmark-name aria-label="书签名称" maxlength="40"></label><button type="button" data-bookmark-add>添加书签</button><button type="button" data-bookmark-close>关闭书签</button><p role="status" aria-live="polite"></p><ul data-bookmark-list></ul>'
 options.container.append(panel);const input=panel.querySelector<HTMLInputElement>('[data-bookmark-name]')!,add=panel.querySelector<HTMLButtonElement>('[data-bookmark-add]')!,status=panel.querySelector<HTMLElement>('[role=status]')!
 let disposed=false
 const reason=()=>options.readOnlyReason()??(!editor.isEditable?'当前文档不可编辑或正在保存':null)??m?.readOnlyReason??(!m?.sourceId?'当前来源未提供书签能力':null)
 const show=(e:unknown)=>{status.textContent=e instanceof Error?e.message:String(e);options.onError(e)}
 const commit=(ops:DocxBookmarkOperation[])=>{if(reason())throw new Error(reason()!);if(!m)fail();const valid=checked(ops,m),tr=closeHistory(editor.state.tr).setDocAttribute(intent,valid.length?valid:null);options.collectOperations(tr.doc.toJSON());editor.view.dispatch(tr);if(!editor.state.doc.eq(tr.doc))fail();refresh()}
 const locate=(ranges:DocxBookmarkRange[])=>{if(!m)fail();rangesOf(ranges,m,false);const positions:{from:number;to:number}[]=[]
  for(const r of ranges){const t=m.targets.find(t=>t.targetId===r.targetId)!;let found=false;editor.state.doc.forEach((n,pos)=>{if(n.attrs.docxIndex!==t.blockIndex)return;if(found||!n.isTextblock||n.textContent!==t.text)fail();found=true;positions.push({from:pos+1+r.from,to:pos+1+r.to})});if(!found)fail()}
  editor.commands.setTextSelection({from:positions[0].from,to:positions.at(-1)!.to});editor.commands.focus();editor.commands.scrollIntoView()
 }
 const refresh=()=>{if(disposed)return;const blocked=reason();input.disabled=add.disabled=!!blocked;const list=panel.querySelector('[data-bookmark-list]')!;list.replaceChildren();if(!m){status.textContent=blocked;return}
  const ops=docxBookmarksOf(editor.getJSON(),m),deleted=new Set(ops.filter(o=>o.kind==='deleteBookmark').map(o=>o.bookmarkId)),entries=[...m.bookmarks.filter(b=>!deleted.has(b.bookmarkId)),...ops.filter(o=>o.kind==='createBookmark').map(o=>({bookmarkId:'pending:'+o.name,name:o.name,ranges:o.ranges,readOnlyReason:null}))]
  for(const b of entries){const li=document.createElement('li'),go=document.createElement('button'),remove=document.createElement('button');go.type=remove.type='button';go.addEventListener('mousedown',e=>e.preventDefault());remove.addEventListener('mousedown',e=>e.preventDefault());go.dataset.bookmarkGo=b.bookmarkId;go.textContent=b.name;go.disabled=!!b.readOnlyReason||!b.ranges.length;go.addEventListener('click',()=>{try{locate(b.ranges)}catch(e){show(e)}})
   remove.dataset.bookmarkDelete=b.bookmarkId;remove.textContent='删除书签';remove.disabled=!!blocked||!!b.readOnlyReason;remove.addEventListener('click',()=>{try{commit(b.bookmarkId.startsWith('pending:')?ops.filter(o=>o.kind!=='createBookmark'||o.name!==b.name):[...ops,{kind:'deleteBookmark',sourceId:m.sourceId!,bookmarkId:b.bookmarkId}])}catch(e){show(e)}});li.append(go,remove);if(b.readOnlyReason)li.append(document.createTextNode('：'+b.readOnlyReason));list.append(li)
  }
  if(blocked)status.textContent=blocked
  else if(status.dataset.blocked==='true')status.textContent=''
  status.dataset.blocked=String(!!blocked)
 }
 // 按钮保持原正文选区；在名称输入框内输入不会改变 PM selection。
 add.addEventListener('mousedown',e=>e.preventDefault());add.addEventListener('click',()=>{try{if(!m)fail();if(!validName(input.value))throw new Error('书签名称须以字母、中文或下划线开头，仅含字母、数字、中文或下划线，最长40字');commit([...docxBookmarksOf(editor.getJSON(),m),{kind:'createBookmark',sourceId:m.sourceId!,name:input.value,ranges:selectedDocxBookmarkRanges(editor,m)}]);input.value='';status.textContent='书签已加入草稿，可撤销和重做'}catch(e){show(e)}})
 panel.querySelector('[data-bookmark-close]')!.addEventListener('click',()=>{panel.hidden=true});editor.on('transaction',refresh)
 return{open(){panel.hidden=false;refresh();panel.scrollIntoView?.({block:'nearest'})},refresh,dispose(){disposed=true;editor.off('transaction',refresh);panel.remove()}}
}
