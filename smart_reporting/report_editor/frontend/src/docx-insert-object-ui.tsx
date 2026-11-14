import {closeHistory} from '@tiptap/pm/history'
import type {Editor} from '@tiptap/core'
import {createModal} from './modal'
import {insertDocxObject,projectNewDocxObject,DOCX_OBJECT_SHAPES,WORDART_PRESETS,normalizeDocxInsertObject,type DocxInsertObject} from './docx-insert-object'
/** Pending object controller. Changes dispatch a single history transaction. */
export function createDocxInsertObjectControls(options:{editor:Editor;root:HTMLElement;editable():boolean;onError?(error:unknown):void}) {
 let disposeDialog:(()=>void)|undefined
 function open(type:DocxInsertObject['type']) {
  disposeDialog?.()
  const {editor}=options
  let selectedPos:number|undefined
  const selected=editor.state.selection as unknown as {node?:{attrs:Record<string,unknown>};from:number}
  if(selected.node?.attrs.nativeObjectInsert!=null)selectedPos=selected.from
  const initial=selectedPos===undefined?{type,preset:type==='shape'?'rect':type==='wordArt'?'blue':undefined}:normalizeDocxInsertObject(selected.node!.attrs.nativeObjectInsert)
  type=initial.type
  const modal=createModal({root:options.root,label:type==='textbox'?'文本框':type==='shape'?'形状':'艺术字',cardClass:'docx-settings-dialog',closeLabel:'关闭对象设置',onRequestClose:()=>disposeDialog?.(),content:`<header><h2>${type==='textbox'?'文本框':type==='shape'?'形状':'艺术字'}</h2></header><form><label>预设<select aria-label="对象预设"></select></label><label>文字<textarea aria-label="对象文字"></textarea></label><label>宽度（厘米）<input aria-label="对象宽度" type="number" min="0.1" max="55.88" step="0.1"></label><label>高度（厘米）<input aria-label="对象高度" type="number" min="0.1" max="55.88" step="0.1"></label><p role="alert"></p><footer><button type="button" data-action="remove">删除待保存对象</button><button type="submit">${selectedPos===undefined?'插入':'应用'}</button></footer></form>`})
  disposeDialog=()=>{modal.remove();disposeDialog=undefined}
  const preset=modal.card.querySelector('select')!,text=modal.card.querySelector('textarea')!,inputs=modal.card.querySelectorAll('input'),width=inputs[0],height=inputs[1],error=modal.card.querySelector('[role=alert]')!
  const presets=type==='shape'?DOCX_OBJECT_SHAPES:type==='wordArt'?WORDART_PRESETS.map(p=>p.id):[]
  presets.forEach(id=>{const option=document.createElement('option');option.value=id;option.textContent=id;preset.append(option)})
  preset.closest('label')!.hidden=type==='textbox';preset.value=initial.preset??''
  text.value=initial.text??(type==='wordArt'?'艺术字':'')
  width.value=String((initial.widthEmu??(type==='wordArt'?2700000:1800000))/360000)
  height.value=String((initial.heightEmu??(type==='wordArt'?720000:1080000))/360000)
  const remove=modal.card.querySelector<HTMLButtonElement>('[data-action=remove]')!;remove.hidden=selectedPos===undefined
  const ensure=()=>{if(!options.editable()||!editor.isEditable)throw new Error('当前文档不可编辑或正在保存');if(selectedPos!==undefined&&editor.state.doc.nodeAt(selectedPos)?.attrs.nativeObjectInsert!==selected.node!.attrs.nativeObjectInsert)throw new Error('对象位置已变化，请重新选择对象')}
  remove.onclick=()=>{try{ensure();const node=editor.state.doc.nodeAt(selectedPos!)!;const previous=editor.state.doc;editor.view.dispatch(closeHistory(editor.state.tr).delete(selectedPos!,selectedPos!+node.nodeSize));if(editor.state.doc===previous)throw new Error('对象删除未通过保存校验');disposeDialog?.()}catch(e){error.textContent=String(e)}}
  modal.card.querySelector('form')!.onsubmit=event=>{event.preventDefault();try{
   ensure();const value=normalizeDocxInsertObject({type,...(type!=='textbox'?{preset:preset.value}:{}),text:text.value,widthEmu:Math.round(Number(width.value)*360000),heightEmu:Math.round(Number(height.value)*360000)})
   if(selectedPos===undefined)insertDocxObject(editor,value)
   else {const node=editor.state.doc.nodeAt(selectedPos)!,previous=editor.state.doc;const replacement=editor.schema.nodeFromJSON(projectNewDocxObject(value,editor.schema));if(!replacement.eq(node)){editor.view.dispatch(closeHistory(editor.state.tr).replaceWith(selectedPos,selectedPos+node.nodeSize,replacement));if(editor.state.doc===previous)throw new Error('对象修改未通过保存校验')}}
   disposeDialog?.()
  }catch(e){error.textContent=e instanceof Error?e.message:String(e);options.onError?.(e)}}
  modal.open(text)
 }
 return {open,dispose:()=>disposeDialog?.()}
}
