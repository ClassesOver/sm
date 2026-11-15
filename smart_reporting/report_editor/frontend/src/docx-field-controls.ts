import type {Editor} from '@tiptap/core'
import {closeHistory} from '@tiptap/pm/history'
import type {NativeOperation} from './native-draft'
import {createDocxChartFields,type DocxFieldTarget} from './docx-chart-fields'
import {planDocxFieldEdit,supportedDocxFieldInstruction} from './docx-field-edit'
import {collectFields,fieldRangeAt,toggleAllFieldCodes,toggleFieldCodes} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/field-codes'
/** Instruction editor captures document identity before focus leaves the editor. */
export function createDocxFieldControls({root,editor,fields,pending,reportError,value}:{root:HTMLElement;editor:Editor;fields:readonly DocxFieldTarget[];pending:()=>readonly NativeOperation[];reportError:(e:unknown)=>void;value:(instruction:string)=>string}){
 let modal:HTMLElement|undefined
 const selected=()=>{
  const range=fieldRangeAt(editor.state,editor.state.selection.from);if(!range||editor.state.selection.to>range.to)throw new Error('请先选择正文中的受支持域')
  const $pos=editor.state.doc.resolve(range.from);if($pos.depth!==1)throw new Error('暂不支持此位置的域')
  const target=fields.find(t=>t.docxIndex===$pos.parent.attrs.docxIndex),ranges=collectFields(editor.state.doc).filter(r=>editor.state.doc.resolve(r.from).parent===$pos.parent&&/^(DATE|TIME|PAGE|NUMPAGES|FILENAME)(?:\s|$)/i.test(r.instr.trim())),index=ranges.findIndex(r=>r.from===range.from&&r.to===range.to),field=target?.fields[index]
  if(!target||!field||!supportedDocxFieldInstruction(field.instruction)||ranges.length!==target.fields.length||range.instr.trim()!==field.instruction.trim()||editor.state.doc.textBetween(range.from,range.to,'')!==field.result)throw new Error('该域来源不受支持或已变化')
  return {range,target,field}
 }
 const close=()=>{modal?.remove();modal=undefined}
 const openEdit=()=>{try{
  if(!editor.isEditable||pending().length)throw new Error('请先保存当前修改')
  const {target,field}=selected(),captured=editor.state.doc
  close();modal=document.createElement('div');modal.className='modal-backdrop';modal.setAttribute('role','dialog');modal.setAttribute('aria-label','编辑域')
  const form=document.createElement('form');form.className='modal';const title=document.createElement('h2');title.textContent='编辑域';const label=document.createElement('label');label.textContent='域代码';const input=document.createElement('input');input.value=field.instruction.trim();input.spellcheck=false;input.setAttribute('aria-label','域代码');label.append(input)
  const hint=document.createElement('p');hint.textContent='支持 DATE、TIME、PAGE、NUMPAGES、FILENAME，可带 \\* MERGEFORMAT。';const cancel=document.createElement('button');cancel.type='button';cancel.textContent='取消';cancel.onclick=close;const ok=document.createElement('button');ok.type='submit';ok.textContent='确定';form.append(title,label,hint,cancel,ok);modal.append(form);root.append(modal)
  modal.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();close()}});modal.addEventListener('mousedown',e=>{if(e.target===modal)close()})
  form.addEventListener('submit',e=>{e.preventDefault();try{
   if(!editor.isEditable||pending().length||editor.state.doc!==captured)throw new Error('域编辑来源已变化，请重新打开')
   const newInstruction=input.value.trim(),op={kind:'editField',blockId:target.blockId,expectedObjectSha256:target.expectedObjectSha256,...field,newInstruction,newResult:value(newInstruction)}
   const p=planDocxFieldEdit(editor.getJSON(),op,fields,editor.schema)
   editor.view.dispatch(closeHistory(editor.state.tr.replaceWith(0,editor.state.doc.content.size,p.node.content).setDocAttribute('nativeChartFieldOperation',op)));close();editor.view.focus()
  }catch(error){reportError(error)}});input.focus();input.select()
 }catch(error){reportError(error)}}
 const updateSelected=()=>{try{
  if(!editor.isEditable||pending().length)throw new Error('请先保存当前修改')
  const {target,field}=selected(),result=value(field.instruction)
  if(result===field.result)return
  const op={kind:'updateFields',updates:[{blockId:target.blockId,expectedObjectSha256:target.expectedObjectSha256,fields:[{fieldIndex:field.fieldIndex,instruction:field.instruction,result}]}]},projection=createDocxChartFields([],[],fields).planFields(editor.getJSON(),op,editor.schema)
  editor.view.dispatch(closeHistory(editor.state.tr.replaceWith(0,editor.state.doc.content.size,projection.node.content).setDocAttribute('nativeChartFieldOperation',op)));editor.view.focus()
 }catch(error){reportError(error)}}
 const selectionReason=()=>{try{if(!editor.isEditable)return '当前文档不可编辑';if(pending().length)return '请先保存当前修改';selected();return null}catch(error){return error instanceof Error?error.message:String(error)}}
 return {openEdit,updateSelected,selectionReason,toggleSelectedCode:()=>{try{const range=fieldRangeAt(editor.state,editor.state.selection.from);if(range)toggleFieldCodes(editor.view,range);else throw new Error('请选择域')}catch(e){reportError(e)}},toggleAllCodes:()=>toggleAllFieldCodes(editor.view),handleKey:(e:KeyboardEvent)=>{if(e.defaultPrevented||e.isComposing||e.keyCode===229||(e.target instanceof Element&&e.target.closest('[role=dialog]')))return false;if(e.key!=='F9'||!e.altKey||e.ctrlKey||e.metaKey)return false;e.preventDefault();toggleAllFieldCodes(editor.view);return true},dispose:close}
}
