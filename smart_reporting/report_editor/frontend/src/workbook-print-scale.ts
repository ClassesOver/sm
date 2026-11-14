import {createModal} from './modal'
export interface PrintScaleState {scale:number;fitToPage:boolean}
type PageSetup={scale?:number;fitToPage?:boolean}
export interface PrintScaleTarget {book:object;sheet:object;sheetId:string}
export function parsePrintScale(raw:string):number {
 const value=Number(raw)
 if(!raw.trim()||!Number.isInteger(value)||value<10||value>400)throw new Error('打印缩放比例须为 10–400 之间的整数')
 return value
}
export function printScaleState(baseline:PageSetup|undefined,patch:PageSetup|undefined):PrintScaleState {
 return{scale:patch?.scale??baseline?.scale??100,fitToPage:patch?.fitToPage??baseline?.fitToPage??false}
}
export function printScalePatch(baseline:PageSetup|undefined,patch:Record<string,unknown>|undefined,scale:number):Record<string,unknown>|undefined {
 parsePrintScale(String(scale))
 const current=printScaleState(baseline,patch)
 return current.scale===scale&&!current.fitToPage?undefined:{...patch,scale,fitToPage:false}
}
// 独立百分比入口；复用既有页面设置日志，不冒称完整源打印对话框。
export function createPrintScaleDialog(root:HTMLElement,apply:(scale:number,target:PrintScaleTarget)=>void){
 let target:PrintScaleTarget|undefined,disposed=false
 const modal=createModal({root,label:'打印缩放比例',overlayClass:'workbook-print-scale-overlay',cardClass:'workbook-ribbon-format-dialog workbook-print-scale-dialog',content:`<h2>打印缩放比例</h2><form class="workbook-ribbon-format-form" novalidate><label>打印比例<span class="workbook-ribbon-format-unit"><input data-print-scale-input type="number" min="10" max="400" step="1" aria-label="打印缩放比例"><span>%</span></span></label><p>仅设置当前工作表的打印比例，不改变网格缩放。确认后将关闭按页数调整为合适大小。</p><p data-print-scale-mode></p><p class="workbook-ribbon-format-error" role="alert"></p><div class="workbook-ribbon-format-actions"><button type="button" data-print-scale-cancel>取消</button><button type="submit" data-print-scale-apply>确定</button></div></form>`})
 const input=modal.card.querySelector<HTMLInputElement>('input')!,error=modal.card.querySelector<HTMLElement>('[role="alert"]')!
 input.addEventListener('input',()=>{error.textContent='';input.removeAttribute('aria-invalid')})
 modal.card.querySelector('[data-print-scale-cancel]')!.addEventListener('click',modal.close)
 modal.card.querySelector('form')!.addEventListener('submit',event=>{event.preventDefault();if(disposed||!target)return;try{apply(parsePrintScale(input.value),target);modal.close()}catch(cause){error.textContent=(cause as Error).message;input.setAttribute('aria-invalid','true')}})
 return{
  open(state:PrintScaleState,captured:PrintScaleTarget){if(disposed)return;target=captured;input.value=String(state.scale);error.textContent='';input.removeAttribute('aria-invalid');modal.card.querySelector('[data-print-scale-mode]')!.textContent=state.fitToPage?'当前按页数调整为合适大小；此比例暂未生效。':'';modal.open(input)},
  dispose(){disposed=true;target=undefined;modal.remove()},
 }
}
