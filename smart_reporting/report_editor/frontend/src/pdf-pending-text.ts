/** Manage uncommitted text inserts by exact draft snapshot and operation index. */
import type {NativeDraft} from './native-draft'
import type {PdfPageIdentity} from './pdf-operations'
import {validatePdfStaticText} from './pdf-static-text'

export function bindPdfPendingText(options:{
 root:HTMLElement;draft:NativeDraft;pages:()=>PdfPageIdentity[];unavailable:()=>string|null
 edit:(index:number)=>void;refresh:()=>Promise<void>;status:(message:string)=>void
}){
 const owner=options.root.ownerDocument,dialog=owner.createElement('dialog')
 dialog.className='pdf-layout-dialog';dialog.setAttribute('aria-label','管理插入文字')
 const title=owner.createElement('h3');title.textContent='管理插入文字'
 const hint=owner.createElement('p');hint.textContent='选择待保存的文字修改内容、样式或同页位置；删除后可撤销。'
 const list=owner.createElement('div');list.style.cssText='max-height:50vh;overflow:auto;overflow-wrap:anywhere'
 const error=owner.createElement('p');error.setAttribute('role','alert')
 const close=owner.createElement('button');close.type='button';close.textContent='关闭'
 close.addEventListener('click',()=>dialog.close())
 dialog.append(title,hint,list,error,close);options.root.append(dialog)
 let disposed=false,snapshot='',generation=0
 const current=()=>!disposed&&dialog.open&&!options.draft.closed&&!options.draft.saving&&!options.unavailable()&&snapshot===JSON.stringify(options.draft.operations)
 function guard(expectedGeneration:number){
  if(expectedGeneration===generation&&current())return true
  if(!disposed){error.textContent=options.unavailable()??'草稿已变化，请关闭后重新打开管理列表';options.status(error.textContent)}
  return false
 }
 function render(){
  list.replaceChildren();const operations=options.draft.operations;snapshot=JSON.stringify(operations);const renderGeneration=++generation
  operations.forEach((operation,index)=>{
   if(operation.kind!=='insertText')return
   const row=owner.createElement('div');row.dataset.pdfPendingTextRow=String(index)
   const summary=owner.createElement('p'),page=options.pages().find(page=>page.pageId===operation.pageId)
   summary.textContent=`第 ${(page?.index??-1)+1} 页 · ${(operation.origin as number[]).join(', ')} · ${String(operation.text)}`
   const actions=owner.createElement('div');actions.className='pdf-layout-actions'
   const edit=owner.createElement('button');edit.type='button';edit.textContent='编辑内容与位置';edit.dataset.pdfPendingTextEdit=String(index)
   edit.addEventListener('click',()=>{if(!guard(renderGeneration))return;dialog.close();options.edit(index)})
   const remove=owner.createElement('button');remove.type='button';remove.textContent='删除';remove.dataset.pdfPendingTextDelete=String(index)
   remove.addEventListener('click',()=>{
    if(!guard(renderGeneration))return
    const remaining=options.draft.operations.filter((_,position)=>position!==index)
    try{validatePdfStaticText(options.pages(),remaining);options.draft.setOperations(remaining)}catch(cause){error.textContent=cause instanceof Error?cause.message:String(cause);return}
    render();if(!remaining.length)dialog.close();options.status('已删除待保存文字，可撤销')
    void options.refresh().catch(cause=>options.status(`待保存文字已删除，但刷新失败：${cause instanceof Error?cause.message:String(cause)}`))
   })
   actions.append(edit,remove);row.append(summary,actions);list.append(row)
  })
  if(!list.childElementCount){const empty=owner.createElement('p');empty.textContent='没有待保存的插入文字';list.append(empty)}
 }
 return {
  open(){
   if(disposed)return
   const blocked=options.unavailable();if(blocked){options.status(blocked);return}
   try{validatePdfStaticText(options.pages(),options.draft.operations)}catch(cause){options.status(cause instanceof Error?cause.message:String(cause));return}
   error.textContent='';render();dialog.showModal();close.focus()
  },
  refresh(){if(!disposed&&dialog.open&&!current())dialog.close()},
  dispose(){if(disposed)return;disposed=true;if(dialog.open)dialog.close();dialog.remove()},
 }
}
