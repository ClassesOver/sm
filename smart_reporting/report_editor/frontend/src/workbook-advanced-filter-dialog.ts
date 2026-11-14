import {createModal} from './modal'
import type {AdvancedFilterInput,AdvancedFilterOperator,AdvancedFilterTarget} from './workbook-advanced-filter'

export function createAdvancedFilterDialog(root:HTMLElement,apply:(target:AdvancedFilterTarget,input:AdvancedFilterInput)=>Promise<unknown>){
 let target:AdvancedFilterTarget|undefined,busy=false,disposed=false
 const modal=createModal({root,label:'高级筛选',closeLabel:'关闭高级筛选',overlayClass:'workbook-ribbon-format-overlay',cardClass:'workbook-ribbon-format-dialog workbook-advanced-filter-dialog',onRequestClose:()=>{if(!busy)modal.close()},content:`<header><h2>高级筛选</h2></header><form class="workbook-ribbon-format-form"><div class="workbook-advanced-filter-body">
 <label>字段<select aria-label="高级筛选字段"></select></label>
 <label class="workbook-advanced-filter-condition">第一条件<select aria-label="第一条件运算符"></select><input aria-label="第一条件值" maxlength="32767"></label>
 <label>连接<select aria-label="条件连接"><option value="and">并且（AND）</option><option value="or">或者（OR）</option></select></label>
 <label class="workbook-advanced-filter-condition">第二条件（可选）<select aria-label="第二条件运算符"></select><input aria-label="第二条件值" maxlength="32767"></label>
 <p role="region" aria-label="高级筛选说明" tabindex="0">对同一列设置一至两个条件，保留其它列的筛选条件。首行为表头；数据保持原位。</p><p data-target role="region" aria-label="高级筛选范围" tabindex="0"></p><p role="status" aria-live="polite" aria-label="高级筛选状态" tabindex="0"></p><p class="workbook-ribbon-format-error" role="alert" aria-label="高级筛选错误" tabindex="0"></p>
 </div><footer class="workbook-ribbon-format-actions"><button type="button" data-action="cancel">取消</button><button type="submit">确定</button></footer></form>`})
 const select=(label:string)=>modal.card.querySelector<HTMLSelectElement>(`[aria-label="${label}"]`)!,input=(label:string)=>modal.card.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!
 const field=select('高级筛选字段'),operator1=select('第一条件运算符'),operator2=select('第二条件运算符'),value1=input('第一条件值'),value2=input('第二条件值'),join=select('条件连接')
 const error=modal.card.querySelector<HTMLElement>('[role="alert"]')!,submit=modal.card.querySelector<HTMLButtonElement>('[type="submit"]')!,cancel=modal.card.querySelector<HTMLButtonElement>('[data-action="cancel"]')!
 const status=modal.card.querySelector<HTMLElement>('[role="status"]')!
 const showError=(message:string)=>{const readingStatus=document.activeElement===status;error.textContent=message;status.textContent='';error.scrollIntoView?.({block:'nearest'});if(readingStatus)error.focus({preventScroll:true})}
 for(const operator of [operator1,operator2])operator.replaceChildren(...[['equal','等于'],['notEqual','不等于'],['greaterThan','大于'],['greaterThanOrEqual','大于或等于'],['lessThan','小于'],['lessThanOrEqual','小于或等于']].map(([value,label])=>{const option=document.createElement('option');option.value=value;option.textContent=label;return option}))
 const refresh=()=>{modal.overlay.setAttribute('aria-busy',String(busy));for(const element of [field,operator1,operator2,value1,value2,join,submit,cancel])element.disabled=busy;if(modal.closeButton)modal.closeButton.disabled=busy}
 cancel.addEventListener('click',()=>{if(!busy)modal.close()})
 modal.card.querySelector('form')!.addEventListener('submit',async event=>{
  event.preventDefault();if(!target||busy||disposed)return
  error.textContent='';if(value1.value===''){showError('请填写第一筛选条件');return}
  busy=true;status.textContent='正在筛选，请稍候。';refresh();status.scrollIntoView?.({block:'nearest'});status.focus({preventScroll:true})
  try{
   await apply(target,{colId:Number(field.value),operator1:operator1.value as AdvancedFilterOperator,value1:value1.value,operator2:operator2.value as AdvancedFilterOperator,value2:value2.value,and:join.value==='and'})
   if(!disposed)modal.close()
  }catch(cause){if(!disposed)showError(cause instanceof Error?cause.message:String(cause))}finally{busy=false;if(!disposed)refresh()}
 })
 return {
  open(captured:AdvancedFilterTarget){
   if(busy||disposed)return
   target={...captured,range:{...captured.range},fields:captured.fields.map(entry=>({...entry}))}
   field.replaceChildren(...target.fields.map(entry=>{const option=document.createElement('option');option.value=String(entry.colId);option.textContent=entry.label;return option}))
   operator1.value='equal';operator2.value='equal';value1.value='';value2.value='';join.value='and';error.textContent='';status.textContent=''
   modal.card.querySelector<HTMLElement>('[data-target]')!.textContent=`筛选范围：第 ${target.range.startRow+1}–${target.range.endRow+1} 行。确认后筛选结果将随文件保存。`
   refresh();modal.open(field)
  },
  dispose(){disposed=true;modal.remove()},
 }
}
