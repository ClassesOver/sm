/** Source text translation uses immutable object identity and a pure movement draft. */
import type {NativeDraft,NativeOperation} from './native-draft'
import type {PdfPageIdentity} from './pdf-operations'
export const PDF_MOVE_TEXT_ALONE_REASON='原文移动须单独保存，请先保存或撤销其他类型修改'
export function validatePdfTextMoves(pages:PdfPageIdentity[],operations:NativeOperation[]){
 if(!operations.some(op=>op.kind==='moveText'))return
 if(operations.length>500||operations.some(op=>op.kind!=='moveText'))throw Error(PDF_MOVE_TEXT_ALONE_REASON)
 const used=new Set<string>()
 for(const op of operations){
  if(Object.keys(op).some(key=>!['kind','sourceSha256','pageId','objectId','expectedTextSha256','delta'].includes(key)))throw Error('原文移动参数无效')
  const page=pages.find(page=>page.pageId===op.pageId),target=page?.textObjects?.find(item=>item.objectId===op.objectId&&item.expectedTextSha256===op.expectedTextSha256)
  if(!page||page.blank||!target||!target.text.trim()||typeof op.sourceSha256!=='string'||!/^[a-f0-9]{64}$/.test(op.sourceSha256)||!page.pageId.startsWith(`sha256:${op.sourceSha256}:page:`)||used.has(target.objectId))throw Error('移动文字对象身份无效、已变化或重复')
  used.add(target.objectId)
  if(!Array.isArray(op.delta)||op.delta.length!==2||op.delta.some(value=>typeof value!=='number'||!Number.isFinite(value)))throw Error('文字位移须为有限数值')
  const [dx,dy]=op.delta as number[],box=page.cropBox,[x1,y1,x2,y2]=target.rect
  if(x1+dx!<box.x||y1+dy!<box.y||x2+dx!>box.x+box.width||y2+dy!>box.y+box.height)throw Error('移动后的文字超出页面裁切范围')
 }
}
export function stagePdfTextMove(pages:PdfPageIdentity[],operations:NativeOperation[],sourceSha256:string,pageId:string,objectId:string,delta:[number,number]){
 if(operations.some(op=>op.kind!=='moveText'))throw Error(PDF_MOVE_TEXT_ALONE_REASON)
 const target=pages.find(page=>page.pageId===pageId)?.textObjects?.find(item=>item.objectId===objectId)
 if(!target)throw Error('移动文字对象已变化')
 const result=operations.filter(op=>!(op.pageId===pageId&&op.objectId===objectId))
 const operation={kind:'moveText',sourceSha256,pageId,objectId,expectedTextSha256:target.expectedTextSha256,delta}
 validatePdfTextMoves(pages,[...result,operation])
 if(delta[0]!==0||delta[1]!==0)result.push(operation)
 return structuredClone(result)
}
export function bindPdfTextMove(options:{root:HTMLElement;draft:NativeDraft;pages:()=>PdfPageIdentity[];target:()=>{pageId:string;objectId:string}|null;unavailable:()=>string|null;refresh:()=>Promise<void>;status:(text:string)=>void}){
 const owner=options.root.ownerDocument,section=owner.createElement('fieldset'),legend=owner.createElement('legend');legend.textContent='移动原文（保留字形）';section.append(legend)
 const hint=owner.createElement('p');hint.textContent='按原 PDF 坐标设置相对原位置的位移（pt）：X 向右、Y 向上；0 恢复原位置。仅移动整文字对象，暂存后请核对实际预览。';section.append(hint)
 function coordinate(name:string){const label=owner.createElement('label');label.textContent=name;const input=owner.createElement('input');input.type='number';input.step='any';input.value='0';input.setAttribute('aria-label',`原文位移 ${name}`);label.append(input);section.append(label);return input}
 const x=coordinate('X'),y=coordinate('Y'),submit=owner.createElement('button');submit.type='button';submit.textContent='暂存原文移动';submit.dataset.pdfMoveText='true'
 section.append(submit);options.root.append(section)
 let disposed=false,snapshot='',selected='',initial:[number,number]=[0,0]
 function update(){
  if(disposed)return
  const target=options.target(),key=target?JSON.stringify(target):'',next=JSON.stringify(options.draft.operations)
  if(key!==selected||next!==snapshot){selected=key;snapshot=next;const pending=target?options.draft.operations.find(op=>op.kind==='moveText'&&op.pageId===target.pageId&&op.objectId===target.objectId):undefined;initial=pending?.delta as [number,number]??[0,0];x.value=String(initial[0]);y.value=String(initial[1])}
  const blocked=options.unavailable();section.disabled=!!blocked||!target;submit.title=blocked??(!target?'请先选择原文字对象':'暂存位移并核对实际 PDF 预览')
 }
 submit.addEventListener('click',()=>{
  if(disposed)return
  const target=options.target(),blocked=options.unavailable()
  if(blocked||!target||selected!==JSON.stringify(target)||snapshot!==JSON.stringify(options.draft.operations)){options.status(blocked??'文字对象或草稿已变化，请重新选择');return}
  if(!x.value.trim()||!y.value.trim()){options.status('请输入原文位移 X 和 Y');return}
  try{const result=stagePdfTextMove(options.pages(),options.draft.operations,options.draft.identity.sourceSha256,target.pageId,target.objectId,[Number(x.value),Number(y.value)]);options.draft.setOperations(result);update();options.status('原文移动已加入草稿，请核对实际 PDF 预览');void options.refresh().catch(cause=>options.status(`原文移动已加入草稿，但刷新失败：${cause instanceof Error?cause.message:String(cause)}`))}catch(cause){options.status(cause instanceof Error?cause.message:String(cause))}
 })
 update()
 return {update,cancel(){selected='';update()},incompleteReason(){return !disposed&&options.target()&&(!x.value.trim()||!y.value.trim()||Number(x.value)!==initial[0]||Number(y.value)!==initial[1])?'请先暂存原文移动或将位移恢复为当前草稿值':null},dispose(){if(disposed)return;disposed=true;section.remove()}}
}
