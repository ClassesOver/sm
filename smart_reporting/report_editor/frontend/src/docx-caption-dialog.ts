import type {Editor} from '@tiptap/core'
import type {CaptionLabel,DocxCaptionControls} from './docx-caption'
import {createModal} from './modal'
import {buttonClasses} from './button'
export function createDocxCaptionDialog(options:{editor:Editor;container:HTMLElement;controls:DocxCaptionControls;readOnlyReason:()=>string|null;onError:(error:unknown)=>void}) {
 const {editor,controls}=options
 const modal=createModal({root:options.container,label:'插入题注',cardClass:'docx-settings-dialog docx-caption-dialog',closeLabel:'关闭题注',content:`<header><h2>插入题注</h2></header><div class="docx-caption-body"><p role="region" aria-label="题注保存说明" tabindex="0">插入真实 SEQ 域，缓存编号由来源推导。请在该标签最后一个题注之后插入并独立保存；可在 Word 中更新域。</p><label>标签 <select data-caption-label aria-label="题注标签"><option>图</option><option>表</option><option>公式</option></select></label><label>描述 <input data-caption-text aria-label="题注描述" maxlength="1000"></label><fieldset><legend>预览</legend><p data-caption-preview role="region" aria-label="题注预览" tabindex="0"></p></fieldset></div><footer><p role="status" aria-live="polite" aria-label="题注状态" tabindex="0"></p><div class="docx-setting-actions"><button type="button" data-caption-cancel class="${buttonClasses()}">取消</button><button type="button" data-caption-confirm class="${buttonClasses('primary')}">插入题注</button></div></footer>`})
 const label=modal.card.querySelector<HTMLSelectElement>('[data-caption-label]')!,input=modal.card.querySelector<HTMLInputElement>('[data-caption-text]')!,preview=modal.card.querySelector<HTMLElement>('[data-caption-preview]')!,status=modal.card.querySelector<HTMLElement>('[role=status]')!,confirm=modal.card.querySelector<HTMLButtonElement>('[data-caption-confirm]')!
 let source=editor.state.doc,selection=editor.state.selection
 const reason=()=>options.readOnlyReason()??(source!==editor.state.doc||!selection.eq(editor.state.selection)?'文档或光标已变化，请重新打开题注。':null)??controls.reason(label.value as CaptionLabel,input.value)
 const refresh=()=>{if(modal.overlay.hidden)return;const confirmationFocused=document.activeElement===confirm;try{const blocked=reason();confirm.disabled=!!blocked;status.textContent=blocked??'';preview.textContent=blocked?'':controls.preview(label.value as CaptionLabel,input.value).display}catch(error){confirm.disabled=true;status.textContent=error instanceof Error?error.message:String(error);preview.textContent=''}if(confirmationFocused&&confirm.disabled)status.focus()}
 label.addEventListener('change',refresh);input.addEventListener('input',refresh)
 modal.card.querySelector<HTMLButtonElement>('[data-caption-cancel]')!.addEventListener('click',modal.close)
 confirm.addEventListener('click',()=>{try{const blocked=reason();if(blocked)throw new Error(blocked);const before=editor.state.doc;controls.run(label.value as CaptionLabel,input.value);if(editor.state.doc!==before)modal.close();else refresh()}catch(error){status.textContent=error instanceof Error?error.message:String(error);options.onError(error)}})
 editor.on('transaction',refresh)
 return{open(event?:{currentTarget:EventTarget|null}){if(event?.currentTarget instanceof HTMLElement)event.currentTarget.focus();source=editor.state.doc;selection=editor.state.selection;input.value='';modal.open(input);refresh()},refresh,dispose(){editor.off('transaction',refresh);modal.remove()}}
}
