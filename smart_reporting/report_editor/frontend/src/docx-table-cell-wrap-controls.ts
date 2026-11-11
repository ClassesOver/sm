import {createModal} from './modal'
import {buttonClasses} from './button'
/** null 为混合；未触碰回 undefined，仍由宿主验证来源/选区未过期。 */
export function openDocxCellWrapDialog(root:HTMLElement,initial:boolean|null,apply:(wrap:boolean|undefined)=>void){
 const modal=createModal({root,label:'自动换行',closeLabel:'关闭自动换行',onRequestClose:()=>modal.remove(),content:`<h2>自动换行</h2><form><label><input type="checkbox" aria-label="自动换行">自动换行</label><p data-mixed></p><p>仅调整所选单元格的直属换行属性。固定布局或超宽表格仍可能按可用宽度换行；此设置不改变列宽或适应文字。</p><p role="alert"></p><button type="button" data-action="cancel" class="${buttonClasses('secondary')}">取消</button><button type="submit" class="${buttonClasses('primary')}">确定</button></form>`})
 const input=modal.card.querySelector<HTMLInputElement>('input')!;input.checked=initial??false;input.indeterminate=initial===null;input.setAttribute('aria-checked',initial===null?'mixed':String(initial));let touched=false
 modal.card.querySelector('[data-mixed]')!.textContent=initial===null?'所选单元格包含多个值；未修改时保持各自设置。':''
 input.addEventListener('change',()=>{touched=true;input.indeterminate=false;input.setAttribute('aria-checked',String(input.checked))})
 modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click',modal.remove)
 modal.card.querySelector('form')!.addEventListener('submit',event=>{event.preventDefault();try{apply(!touched||input.checked===initial?undefined:input.checked);modal.remove()}catch(error){modal.card.querySelector('[role="alert"]')!.textContent=error instanceof Error?error.message:String(error)}})
 modal.open(input)
}
/** 复用现有属性页导航，不开放通用属性写入。 */
export function attachDocxCellWrapNavigation(root:Document,reason:string|null,open:()=>void){
 const dialog=root.querySelector<HTMLElement>('[role="dialog"][aria-label="单元格边距"], [role="dialog"][aria-label="表格属性选项"]')
 if(!dialog)return
 const button=root.createElement('button');button.type='button';button.dataset.action='cell-wrap';button.textContent='自动换行';button.disabled=reason!==null;button.title=reason??''
 button.addEventListener('click',()=>{try{open();(dialog.querySelector<HTMLButtonElement>('[data-action="cancel"]')??dialog.querySelector<HTMLButtonElement>('.modal-close'))?.click();root.querySelector<HTMLInputElement>('[aria-label="自动换行"] input')?.focus()}catch(error){const alert=dialog.querySelector('[role="alert"]');if(alert)alert.textContent=error instanceof Error?error.message:String(error)}})
 dialog.querySelector('h2')?.after(button)
}
