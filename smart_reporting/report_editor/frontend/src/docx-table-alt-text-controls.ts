import {createModal} from './modal'
import {buttonClasses} from './button'
import {normalizeTableAltText,type TableAltText} from './docx-table-alt-text-core'
export function openDocxTableAltTextDialog(root:HTMLElement,initial:TableAltText,apply:(value:TableAltText)=>void){
 const modal=createModal({root,label:'标题/说明',cardClass:'docx-table-property-dialog',closeLabel:'关闭标题/说明',onRequestClose:()=>modal.remove(),content:`<h2>标题/说明</h2><form><label>标题<input type="text" aria-label="标题"></label><label>说明<textarea aria-label="说明" rows="5"></textarea></label><p>为无法看到表格的读者描述表格内容。此处保存表格的替代文字。</p><p role="alert"></p><button type="button" data-action="cancel" class="${buttonClasses('secondary')}">取消</button><button type="submit" class="${buttonClasses('primary')}">确定</button></form>`})
 const title=modal.card.querySelector<HTMLInputElement>('input')!,description=modal.card.querySelector<HTMLTextAreaElement>('textarea')!;title.value=initial.title;description.value=initial.description
 // textarea按HTML规则将原始CR/CRLF规范为LF；未改值时保留原始来源。
 const initialTitle=title.value,initialDescription=description.value
 modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click',modal.remove)
 modal.card.querySelector('form')!.addEventListener('submit',event=>{event.preventDefault();try{apply(title.value===initialTitle&&description.value===initialDescription?initial:normalizeTableAltText({title:title.value,description:description.value}));modal.remove()}catch(error){modal.card.querySelector('[role="alert"]')!.textContent=error instanceof Error?error.message:String(error)}})
 modal.open(title)
}
export function attachDocxTableAltTextNavigation(root:Document,reason:string|null,open:()=>void){
 const dialog=root.querySelector<HTMLElement>('[role="dialog"][aria-label="单元格边距"], [role="dialog"][aria-label="表格属性选项"]');if(!dialog)return
 const button=root.createElement('button');button.type='button';button.dataset.action='table-alt-text';button.textContent='标题/说明';button.disabled=reason!==null;button.title=reason??''
 button.addEventListener('click',()=>{try{open();(dialog.querySelector<HTMLButtonElement>('[data-action="cancel"]')??dialog.querySelector<HTMLButtonElement>('.modal-close'))?.click();root.querySelector<HTMLInputElement>('[role="dialog"][aria-label="标题/说明"] input')?.focus()}catch(error){const alert=dialog.querySelector('[role="alert"]');if(alert)alert.textContent=error instanceof Error?error.message:String(error)}})
 dialog.querySelector('h2')?.after(button)
}
