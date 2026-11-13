/** 单事务投影精确的 REF 缓存；草稿仅携带源绑定意图，不接受 XML 或缓存输入。 */
import {Node,type Editor} from '@tiptap/core'
import {closeHistory} from '@tiptap/pm/history'
import type {DocxPmNode} from './docx-operations'
import type {NativeOperation} from './native-draft'
import {verifiedDocxBookmarksModel,type DocxBookmarksModel} from './docx-bookmarks'
export type DocxCrossReferencesModel=DocxBookmarksModel
export interface DocxCrossReferenceOperation extends Record<string, unknown> {kind:'insertCrossReference';sourceId:string;bookmarkId:string;targetId:string;expectedParagraphSha256:string;offset:number}
const intent='nativeCrossReferenceOperations',nodeType='docxCrossReference',copy=<T>(v:T):T=>structuredClone(v)
function fail():never{throw new Error('交叉引用或光标与可信来源不一致，请重新选择')}
const boundary=(t:string,n:unknown):n is number=>typeof n==='number'&&Number.isSafeInteger(n)&&n>=0&&n<=t.length&&!(n>0&&n<t.length&&t.charCodeAt(n-1)>=0xd800&&t.charCodeAt(n-1)<=0xdbff&&t.charCodeAt(n)>=0xdc00&&t.charCodeAt(n)<=0xdfff)
const validName=(n:string)=>n.length<=40&&/^[A-Za-z_一-鿿][A-Za-z_0-9一-鿿]*$/.test(n)
export const NativeDocxCrossReference=Node.create({name:nodeType,inline:true,group:'inline',atom:true,selectable:false,
 addGlobalAttributes:()=>[{types:['doc'],attributes:{[intent]:{default:null,rendered:false}}}],
 addAttributes:()=>({bookmarkId:{default:null},name:{default:null},text:{default:null}}),
 renderHTML:({node})=>['span',{'data-native-cross-reference':node.attrs.bookmarkId,contenteditable:'false',title:'REF '+node.attrs.name+'；缓存不自动更新，可在 Word 中更新'},node.attrs.text],
 renderText:({node})=>node.attrs.text,
})
export function verifiedDocxCrossReferenceModel(m:DocxCrossReferencesModel,expectedSha:string){
 const verified=verifiedDocxBookmarksModel(m,expectedSha),names=new Set<string>()
 for(const b of verified.bookmarks){if(names.has(b.name)&&!verified.readOnlyReason)fail();names.add(b.name)
  if(!verified.readOnlyReason&&!b.readOnlyReason){if(!validName(b.name)||b.ranges.length!==1||!b.ranges[0].text)fail();const r=b.ranges[0],t=verified.targets.find(t=>t.targetId===r.targetId);if(!t||!boundary(t.text,r.from)||!boundary(t.text,r.to)||r.from>=r.to||t.text.slice(r.from,r.to)!==r.text)fail()}
 }return verified
}
function checked(v:unknown,m:DocxCrossReferencesModel):DocxCrossReferenceOperation[]{
 verifiedDocxCrossReferenceModel(m,m.sourceSha256);if(!Array.isArray(v)||v.length>1||v.length&&(!m.sourceId||m.readOnlyReason))fail()
 for(const op of v){if(!op||typeof op!=='object'||Array.isArray(op)||Object.keys(op).sort().join('|')!==['kind','sourceId','bookmarkId','targetId','expectedParagraphSha256','offset'].sort().join('|')||op.kind!=='insertCrossReference'||op.sourceId!==m.sourceId)fail()
  const t=m.targets.find(t=>t.targetId===op.targetId),b=m.bookmarks.find(b=>b.bookmarkId===op.bookmarkId)
  if(!t||t.readOnlyReason||t.expectedParagraphSha256!==op.expectedParagraphSha256||!boundary(t.text,op.offset)||!b||b.readOnlyReason||b.ranges.length!==1||!b.ranges[0].text||!validName(b.name))fail()
  if(m.bookmarks.some(b=>b.ranges.some(r=>r.targetId===t.targetId)))throw new Error('插入段落含有书签，无法安全判断书签端点或自引用，请选择其它普通正文段落')
 }return copy(v)
}
export function assertDocxCrossReferencesBatch(ops:readonly {kind?:unknown}[]){if(ops.some(o=>o.kind==='insertCrossReference')&&ops.length!==1)throw new Error('交叉引用需独立保存，每次仅插入一个；请先保存或撤销其它修改')}
export function docxCrossReferencesOf(doc:DocxPmNode,m?:DocxCrossReferencesModel):DocxCrossReferenceOperation[]{const value=doc.attrs?.[intent];if(value==null)return[];if(!m)fail();return checked(value,m!)}
function project(doc:DocxPmNode,op:DocxCrossReferenceOperation,m:DocxCrossReferencesModel){
 const current=copy(doc),t=m.targets.find(t=>t.targetId===op.targetId)!,b=m.bookmarks.find(b=>b.bookmarkId===op.bookmarkId)!,indices=(current.content??[]).flatMap((n,i)=>n.attrs?.docxIndex===t.blockIndex?[i]:[])
 if(indices.length!==1)fail();const i=indices[0],paragraph=current.content![i],parts=paragraph.content??[]
 if(!['docParagraph','docHeading'].includes(paragraph.type)||parts.some(n=>n.type!=='text')||parts.map(n=>n.text??'').join('')!==t.text)fail()
 const field:DocxPmNode={type:nodeType,attrs:{bookmarkId:b.bookmarkId,name:b.name,text:b.ranges[0].text}},output:DocxPmNode[]=[];let at=0,inserted=false
 for(const n of parts){const text=n.text??'',end=at+text.length;if(!inserted&&op.offset>=at&&op.offset<=end){const cut=op.offset-at;if(cut)output.push({...n,text:text.slice(0,cut)});output.push(field);if(cut<text.length)output.push({...n,text:text.slice(cut)});inserted=true}else output.push(n);at=end}
 if(!inserted){if(t.text||op.offset!==0)fail();output.push(field)}
 paragraph.content=output;return{current,index:i}
}
function scan(doc:DocxPmNode,allowField:boolean){const walk=(n:DocxPmNode,root=false)=>{if(!root&&n.attrs?.[intent]!=null||!allowField&&n.type===nodeType)fail();n.content?.forEach(c=>walk(c))};walk(doc,true)}
export function normalizeDocxCrossReferences(baseline:DocxPmNode,live:DocxPmNode,m?:DocxCrossReferencesModel){
 const operations=docxCrossReferencesOf(live,m);scan(live,operations.length>0);if(baseline.attrs?.[intent]!=null)fail()
 if(!operations.length)return{current:copy(live),operations}
 if(!m)fail();const {current:expected,index}=project(baseline,operations[0],m!),current=copy(live)
 if(JSON.stringify(current.content?.[index])!==JSON.stringify(expected.content?.[index]))fail()
 for(const [i,n]of(current.content??[]).entries())if(i!==index)scan(n,false)
 current.content![index]=copy(baseline.content![index]);current.attrs={...current.attrs,[intent]:baseline.attrs?.[intent]??null};return{current,operations}
}
export function replayDocxCrossReferences(doc:DocxPmNode,operations:readonly NativeOperation[],m:DocxCrossReferencesModel):DocxPmNode{
 assertDocxCrossReferencesBatch(operations);const ops=operations.filter(o=>o.kind==='insertCrossReference');if(!ops.length)return copy(doc)
 scan(doc,false);const valid=checked(ops,m),{current}=project(doc,valid[0],m);current.attrs={...current.attrs,[intent]:valid};return current
}
interface Options {editor:Editor;container:HTMLElement;model?:DocxCrossReferencesModel;collectOperations:(doc:DocxPmNode)=>NativeOperation[];readOnlyReason:()=>string|null;onError:(e:unknown)=>void}
export function createDocxCrossReferenceControls(options:Options){
 const {editor,model:m}=options,panel=document.createElement('section');panel.className='docx-comment-panel docx-cross-references';panel.hidden=true;panel.setAttribute('aria-label','交叉引用')
 panel.innerHTML='<h2>交叉引用</h2><p>插入已保存单段书签的 REF 域；缓存不自动更新，可在 Word 中更新。每次插入一个并独立保存。</p><button type="button" data-cross-reference-close>关闭交叉引用</button><p role="status" aria-live="polite"></p><ul data-cross-reference-list></ul>';options.container.append(panel)
 const status=panel.querySelector<HTMLElement>('[role=status]')!;let disposed=false
 const reason=()=>options.readOnlyReason()??(!editor.isEditable?'当前文档不可编辑或正在保存':null)??m?.readOnlyReason??(!m?.sourceId?'当前来源未提供交叉引用能力':null)??(docxCrossReferencesOf(editor.getJSON(),m).length?'请先保存或撤销当前交叉引用':null)
 const show=(e:unknown)=>{status.textContent=e instanceof Error?e.message:String(e);options.onError(e)}
 const insert=(bookmarkId:string)=>{if(reason())throw new Error(reason()!);if(!m)fail();if(options.collectOperations(editor.getJSON()).length)throw new Error('交叉引用需独立保存，请先保存或撤销其它修改')
  const {empty,$from}=editor.state.selection;if(!empty||$from.depth!==1)throw new Error('请把光标放在普通正文或标题段落中')
  const t=m!.targets.find(t=>t.blockIndex===$from.parent.attrs.docxIndex);if(!t||t.text!==$from.parent.textContent)fail()
  const operations=checked([{kind:'insertCrossReference',sourceId:m!.sourceId,bookmarkId,targetId:t!.targetId,expectedParagraphSha256:t!.expectedParagraphSha256,offset:$from.parentOffset}],m!),book=m!.bookmarks.find(b=>b.bookmarkId===bookmarkId)!
  const field=editor.schema.nodeFromJSON({type:nodeType,attrs:{bookmarkId,name:book.name,text:book.ranges[0].text}}),tr=closeHistory(editor.state.tr.insert($from.pos,field).setDocAttribute(intent,operations));options.collectOperations(tr.doc.toJSON());editor.view.dispatch(tr);if(!editor.state.doc.eq(tr.doc))fail();status.textContent='交叉引用已加入草稿，可撤销和重做';editor.view.focus()
 }
 const refresh=()=>{if(disposed)return;const blocked=reason(),list=panel.querySelector('[data-cross-reference-list]')!;list.replaceChildren();if(!m){status.textContent=blocked;return}
  for(const b of m.bookmarks){const li=document.createElement('li'),button=document.createElement('button');button.type='button';button.dataset.crossReferenceInsert=b.bookmarkId;button.textContent=b.name;button.disabled=!!blocked||!!b.readOnlyReason;button.addEventListener('mousedown',e=>e.preventDefault());button.addEventListener('click',()=>{try{insert(b.bookmarkId)}catch(e){show(e)}});li.append(button,document.createTextNode('：'+(b.readOnlyReason??b.ranges[0]?.text??'')));list.append(li)}
  if(blocked)status.textContent=blocked;else if(status.dataset.blocked==='true')status.textContent='';status.dataset.blocked=String(!!blocked)
 }
 panel.querySelector('[data-cross-reference-close]')!.addEventListener('click',()=>{panel.hidden=true});editor.on('transaction',refresh)
 return{open(){panel.hidden=false;refresh();panel.scrollIntoView?.({block:'nearest'})},refresh,dispose(){disposed=true;editor.off('transaction',refresh);panel.remove()}}
}
