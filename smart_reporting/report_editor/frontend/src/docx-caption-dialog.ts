import type {Editor} from '@tiptap/core'
import type {CaptionLabel,DocxCaptionControls} from './docx-caption'
import {createModal} from './modal'
export function createDocxCaptionDialog(options:{editor:Editor;container:HTMLElement;controls:DocxCaptionControls;readOnlyReason:()=>string|null;onError:(error:unknown)=>void}) {
 const {editor,controls}=options
 const modal=createModal({root:options.container,label:'插入题注',closeLabel:'关闭题注',content:'<h2>插入题注</h2><p>插入真实 SEQ 域，缓存编号由来源推导。请在该标签最后一个题注之后插入并独立保存；可在 Word 中更新域。</p><label>标签 <select data-caption-label><option>图</option><option>表</option><option>公式</option></select></label><label>描述 <input data-caption-text maxlength="1000"></label><p data-caption-preview></p><p role="status" aria-live="polite"></p><button type="button" data-caption-confirm>插入题注</button>'})
 const label=modal.card.querySelector<HTMLSelectElement>('[data-caption-label]')!,input=modal.card.querySelector<HTMLInputElement>('[data-caption-text]')!,preview=modal.card.querySelector<HTMLElement>('[data-caption-preview]')!,status=modal.card.querySelector<HTMLElement>('[role=status]')!,confirm=modal.card.querySelector<HTMLButtonElement>('[data-caption-confirm]')!
 let source=editor.state.doc,selection=editor.state.selection
 const reason=()=>options.readOnlyReason()??(source!==editor.state.doc||!selection.eq(editor.state.selection)?'文档或光标已变化，请重新打开题注。':null)??controls.reason(label.value as CaptionLabel,input.value)
 const refresh=()=>{if(modal.overlay.hidden)return;try{const blocked=reason();confirm.disabled=!!blocked;status.textContent=blocked??'';preview.textContent=blocked?'':controls.preview(label.value as CaptionLabel,input.value).display}catch(error){confirm.disabled=true;status.textContent=error instanceof Error?error.message:String(error);preview.textContent=''}}
 label.addEventListener('change',refresh);input.addEventListener('input',refresh)
 confirm.addEventListener('click',()=>{try{const blocked=reason();if(blocked)throw new Error(blocked);const before=editor.state.doc;controls.run(label.value as CaptionLabel,input.value);if(editor.state.doc!==before)modal.close();else refresh()}catch(error){status.textContent=error instanceof Error?error.message:String(error);options.onError(error)}})
 editor.on('transaction',refresh)
 return{open(){source=editor.state.doc;selection=editor.state.selection;input.value='';modal.open(input);refresh()},refresh,dispose(){editor.off('transaction',refresh);modal.remove()}}
}
