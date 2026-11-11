import {createModal} from './modal'
import type {SubtotalInput,SubtotalTarget} from './workbook-subtotal'

/** 固定来源选区；绝对列号不随对话框展示顺序改变。 */
export function createSubtotalDialog(root:HTMLElement,apply:(target:SubtotalTarget,input:SubtotalInput)=>Promise<unknown>){
 let target:SubtotalTarget|undefined,busy=false,disposed=false
 const modal=createModal({root,label:'分类汇总',closeLabel:'关闭分类汇总',overlayClass:'workbook-ribbon-format-overlay',cardClass:'workbook-ribbon-format-dialog',
  onRequestClose:()=>{if(!busy)modal.close()},content:`<h2>分类汇总</h2><form class="workbook-ribbon-format-form">
  <label>分组列<select aria-label="分组列"></select></label><label>汇总方式<select aria-label="汇总方式"><option value="sum">求和</option><option value="count">计数</option><option value="average">平均值</option></select></label>
  <label>汇总列<select aria-label="汇总列"></select></label><p>所选区域首行为标题，按相邻相同值分组。在各组及区域底部插入汇总行；计数统计非空单元格。需要合并分散的同类数据时，请先排序。</p>
  <p data-target></p><p class="workbook-ribbon-format-error" role="alert"></p><div class="workbook-ribbon-format-actions"><button type="button" data-action="cancel">取消</button><button type="submit">确定</button></div></form>`})
 const group=modal.card.querySelector<HTMLSelectElement>('[aria-label="分组列"]')!,value=modal.card.querySelector<HTMLSelectElement>('[aria-label="汇总列"]')!,agg=modal.card.querySelector<HTMLSelectElement>('[aria-label="汇总方式"]')!
 const error=modal.card.querySelector<HTMLElement>('[role="alert"]')!,submit=modal.card.querySelector<HTMLButtonElement>('[type="submit"]')!,cancel=modal.card.querySelector<HTMLButtonElement>('[data-action="cancel"]')!
 const refresh=()=>{
  modal.overlay.setAttribute('aria-busy',String(busy))
  for(const field of [group,value,agg,submit,cancel])field.disabled=busy
  if(modal.closeButton)modal.closeButton.disabled=busy
 }
 cancel.addEventListener('click',()=>{if(!busy)modal.close()})
 modal.card.querySelector('form')!.addEventListener('submit',async event=>{
  event.preventDefault();if(!target||busy||disposed)return
  error.textContent=''
  if(group.value===value.value){error.textContent='分组列与汇总列不能相同';return}
  busy=true;refresh()
  try{
   await apply(target,{groupCol:Number(group.value),valueCol:Number(value.value),agg:agg.value as SubtotalInput['agg']})
   if(!disposed)modal.close()
  }catch(cause){if(!disposed)error.textContent=cause instanceof Error?cause.message:String(cause)}
  finally{busy=false;if(!disposed)refresh()}
 })
 return {
  open(captured:SubtotalTarget){
   if(busy||disposed)return
   target={...captured,range:{...captured.range},fields:captured.fields.map(field=>({...field}))}
   for(const select of [group,value])select.replaceChildren(...target.fields.map(field=>{
    const option=document.createElement('option');option.value=String(field.column);option.textContent=field.label;return option
   }))
   group.value=String(target.fields[0]?.column);value.value=String(target.fields[1]?.column);agg.value='sum'
   modal.card.querySelector<HTMLElement>('[data-target]')!.textContent=`选区：第 ${target.range.startRow+1}–${target.range.endRow+1} 行。汇总结果与分组将随文件保存。`
   error.textContent='';refresh();modal.open(group)
  },
  dispose(){disposed=true;modal.remove()},
 }
}
