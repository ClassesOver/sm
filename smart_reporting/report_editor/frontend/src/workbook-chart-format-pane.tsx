/** 固定源 ChartPanels.ChartFormatPane 的完整宿主适配；写入仍由授权图表目标执行。 */
import {createElement} from 'react'
import {createRoot,type Root} from 'react-dom/client'
import {flushSync} from 'react-dom'
import {parseRange,type ChartReadSpec,type ChartEditLean} from '@sheets-web/xlsx-engine'
import {ColorDropdown} from './vendor/genoffice-sheets-format/ColorDropdown'
import {chartPointColor} from './workbook-vendor/grid/chart-legend'
import './workbook-chart-format-pane.css'
import type {WorkbookChartElement} from './workbook-chart-element-hit'
export type {WorkbookChartElement} from './workbook-chart-element-hit'
export function createWorkbookChartFormatPane(host:HTMLElement,options:{apply(edit:ChartEditLean):Promise<ChartReadSpec>;editable():boolean;hydrate?(chart:ChartReadSpec):ChartReadSpec;onClose?():void}){
 const pane=document.createElement('section');pane.className='workbook-chart-format-pane';pane.setAttribute('aria-label','设置图表格式');pane.hidden=true;host.append(pane)
 let chart:ChartReadSpec|undefined,element:WorkbookChartElement={kind:'chart'},busy=false,disposed=false,generation=0,palettes:Root[]=[]
 const clearPalettes=()=>{for(const root of palettes)root.unmount();palettes=[]}
 const close=()=>{if(busy)return;generation++;pane.hidden=true;clearPalettes();options.onClose?.()}
 async function apply(edit:ChartEditLean){
  if(busy||disposed||pane.hidden)return
  const alert=pane.querySelector<HTMLElement>('[role=alert]')!
  if(!options.editable()){alert.textContent='当前工作簿不可编辑或正在保存';return}
  if(edit.dataLabels==='none'&&chart?.design?.dataLabelsOffUnavailable){alert.textContent='首个系列保留了值标签，关闭图表标签后仍会显示；当前保留来源系列设置。';return}
  const token=++generation;busy=true;pane.setAttribute('aria-busy','true');pane.querySelectorAll<HTMLInputElement|HTMLSelectElement|HTMLButtonElement>('input,select,button').forEach(c=>c.disabled=true)
  try{const next=await options.apply(edit);if(!disposed&&token===generation){chart=options.hydrate?.(next)??next;busy=false;render()}}
  catch(error){if(!disposed&&token===generation){busy=false;render();pane.querySelector('[role=alert]')!.textContent=(error as Error).message}}
  finally{if(!disposed&&token===generation){busy=false;pane.removeAttribute('aria-busy')}}
 }
 function render(){
  if(!chart||disposed)return
  clearPalettes();pane.replaceChildren();const c=chart,isPie=['pie','doughnut'].includes(c.kind),hasAxes=!isPie,bar=['column','bar','combo'].includes(c.kind),canLabel=c.kind!=='radar'
  const header=document.createElement('header'),title=document.createElement('strong'),closeButton=document.createElement('button');title.textContent='设置图表格式';closeButton.textContent='×';closeButton.setAttribute('aria-label','关闭图表格式');closeButton.onclick=close;header.append(title,closeButton);pane.append(header)
  const body=document.createElement('div');body.className='workbook-chart-format-body';pane.append(body)
  const section=(text:string)=>{const s=document.createElement('section'),h=document.createElement('strong');s.className='pane-section';h.textContent=text;s.append(h);body.append(s);return s}
  const label=(parent:HTMLElement,text:string)=>{const row=document.createElement('label');row.append(text);parent.append(row);return row}
  const select=(parent:HTMLElement,text:string,value:string,choices:[string,string][],commit:(value:string)=>void)=>{const input=document.createElement('select');input.setAttribute('aria-label',text);for(const [v,t]of choices){const option=document.createElement('option');option.value=v;option.textContent=t;input.append(option)}if(!choices.some(([v])=>v===value)){const option=document.createElement('option');option.value='';option.textContent='保留来源设置';input.prepend(option)}input.value=value;input.onchange=()=>{if(input.value)commit(input.value)};label(parent,text).append(input);return input}
  const text=(parent:HTMLElement,title:string,value:string,max:number,commit:(value:string)=>void)=>{const input=document.createElement('input');input.type='text';input.setAttribute('aria-label',title);input.value=value;input.maxLength=max;input.onblur=()=>{if(input.value!==value)commit(input.value)};input.onkeydown=e=>{if(e.key==='Enter'&&!e.isComposing&&e.keyCode!==229){e.preventDefault();input.blur()}};label(parent,title).append(input);return input}
  const numeric=(parent:HTMLElement,title:string,value:number|undefined,commit:(value:number|null)=>void)=>{const input=document.createElement('input');input.type='number';input.setAttribute('aria-label',title);input.value=value===undefined?'':String(value);input.placeholder='自动';input.onblur=()=>{const raw=input.value.trim(),next=raw===''?null:Number(raw);if((next===null?value!==undefined:Number.isFinite(next)&&next!==value))commit(next)};input.onkeydown=e=>{if(e.key==='Enter'&&!e.isComposing&&e.keyCode!==229){e.preventDefault();input.blur()}};label(parent,title).append(input)}
  const range=(parent:HTMLElement,title:string,min:number,max:number,step:number,value:number,commit:(value:number)=>void)=>{const row=label(parent,title),input=document.createElement('input'),output=document.createElement('output');input.type='range';input.min=String(min);input.max=String(max);input.step=String(step);input.value=String(value);input.setAttribute('aria-label',title);output.textContent=String(value);let committed=Number(input.value);if(value<min||value>max){output.textContent=`来源 ${value}（保留）`;input.title='来源值超出此控件范围，只有主动调整才替换'}const run=()=>{const next=Number(input.value);if(Number.isFinite(next)&&next!==committed){committed=next;commit(next)}};input.oninput=()=>output.textContent=input.value;input.onpointerup=run;input.onblur=run;row.append(input,output)}
  const targets:[string,string][]=[['chart','图表区'],['title','图表标题'],['legend','图例']];if(hasAxes)targets.push(['category-axis','分类轴'],['value-axis','数值轴'])
  c.series.forEach((series,si)=>{targets.push(['series:'+si,'系列「'+(series.nameCache??series.name??String(si+1))+'」']);let sourceCount=0;try{const ref=parseRange(series.valuesRef.slice(series.valuesRef.lastIndexOf('!')+1));sourceCount=(ref.endRow-ref.startRow+1)*(ref.endColumn-ref.startColumn+1)}catch{/* 文字常量系列以实际缓存长度为准。 */}const count=Math.min(1_000,Math.max(sourceCount,series.values?.length??0,series.categories?.length??0,...Object.keys(series.pointColors??{}).map(i=>Number(i)+1)));for(let pi=0;pi<count;pi++)targets.push(['point:'+si+':'+pi,'数据点「'+(series.categories?.[pi]??String(pi+1))+'」（系列'+(si+1)+'）'])})
  const key=element.kind==='series'?'series:'+element.seriesIndex:element.kind==='point'?'point:'+element.seriesIndex+':'+element.pointIndex:element.kind
  select(body,'图表元素',key,targets,value=>{const [kind,si,pi]=value.split(':');element=kind==='point'?{kind,seriesIndex:Number(si),pointIndex:Number(pi)}:kind==='series'?{kind,seriesIndex:Number(si)}:{kind:kind as 'chart'};render()})
  if(element.kind==='series'||element.kind==='point'){
   const selected=element,series=c.series[selected.seriesIndex]
   if(series){const s=section(selected.kind==='series'?'系列':'数据点'),colorHost=document.createElement('span');label(s,'填充颜色').append(colorHost);const root=createRoot(colorHost);palettes.push(root);flushSync(()=>root.render(createElement(ColorDropdown,{label:'填充颜色',value:selected.kind==='point'?chartPointColor(c,selected.seriesIndex,selected.pointIndex):series.color??chartPointColor(c,selected.seriesIndex,0),portal:true,onPick:color=>{if(color)void apply(selected.kind==='series'?{seriesColors:{[String(selected.seriesIndex)]:color}}:{pointColors:{[String(selected.seriesIndex)]:{[String(selected.pointIndex)]:color}}})}})))
    if(isPie&&selected.kind==='point'&&selected.seriesIndex===0)range(s,'数据点分离度',0,100,5,series.pointExplosions?.[selected.pointIndex]??series.explosionPct??0,next=>void apply({pointExplosions:{[String(selected.pointIndex)]:next}}))
   }
  }
  text(section('标题'),'图表标题',c.title??'',255,next=>void apply({title:next}))
  const labels=section('图例和标签');select(labels,'图例位置',c.legend?.position??c.design?.legend??'none',[['right','右侧'],['bottom','底部'],['top','顶部'],['left','左侧'],['none','无']],next=>void apply({legend:next as ChartEditLean['legend']}))
  const dataLabels=c.design?.dataLabels,choices:[string,string][]=[['none','无'],['value','值'],...(isPie?[['percent','百分比'],['category-percent','分类和百分比']]as[string,string][]:[])]
  if(canLabel){const control=select(labels,'数据标签',dataLabels??'',choices,next=>void apply({dataLabels:next as ChartEditLean['dataLabels']}));if(c.design?.dataLabelsOffUnavailable){control.querySelector<HTMLOptionElement>('option[value="none"]')!.disabled=true;const notice=document.createElement('p');notice.textContent='首个系列保留了值标签，关闭图表标签后仍会显示；当前保留来源系列设置。';control.setAttribute('aria-description',notice.textContent);labels.append(notice)};if(dataLabels&&dataLabels!=='none'){if(bar||isPie)select(labels,'标签位置',c.dataLabels?.position??'',[['outside-end','外侧末端'],['inside-end','内侧末端'],['center','居中']],next=>void apply({dataLabelPosition:next as ChartEditLean['dataLabelPosition']}));if(c.kind!=='scatter')text(labels,'标签数字格式',c.dataLabels?.numberFormat??'',64,next=>{if(next.trim())void apply({dataLabelFormat:next.trim()})})}}
  if(hasAxes){const s=section('数值轴'),checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=c.design?.gridlines!==false;checkbox.indeterminate=c.design?.gridlines===undefined;checkbox.setAttribute('aria-label','显示主网格线');checkbox.onchange=()=>void apply({gridlines:checkbox.checked});label(s,'显示主网格线').append(checkbox);numeric(s,'最小值',c.axes?.value.scaling?.min,next=>void apply({valueAxis:{min:next}}));numeric(s,'最大值',c.axes?.value.scaling?.max,next=>void apply({valueAxis:{max:next}}))}
  if(['column','bar','line','area'].includes(c.kind))select(section('分组'),'图表分组',c.design?.grouping??'',[['clustered','簇状'],['stacked','堆积'],['percentStacked','百分比堆积']],next=>void apply({grouping:next as ChartEditLean['grouping']}))
  if(bar)range(section('柱形图'),'分类间距',0,500,10,c.gapWidthPct??150,next=>void apply({gapWidthPct:next}))
  if(isPie){const s=section(c.kind==='doughnut'?'圆环图':'饼图');range(s,'饼图分离度',0,100,5,c.series[0]?.explosionPct??0,next=>void apply({explosionPct:next}));if(c.kind==='doughnut')range(s,'圆环内径',10,90,5,c.holeSizePct??50,next=>void apply({holeSizePct:next}))}
  const alert=document.createElement('p');alert.setAttribute('role','alert');pane.append(alert);if(!options.editable())pane.querySelectorAll<HTMLInputElement|HTMLSelectElement|HTMLButtonElement>('input,select,button').forEach(c=>{if(c!==closeButton)c.disabled=true})
 }
 pane.addEventListener('keydown',event=>{if(event.key==='Escape'&&!event.isComposing){event.preventDefault();event.stopPropagation();close()}})
 return {element:pane,open(next:ChartReadSpec,selected:WorkbookChartElement={kind:'chart'}){if(disposed||busy)return;chart=options.hydrate?.(next)??next;element=selected;pane.hidden=false;render()},selectElement(selected:WorkbookChartElement){if(disposed||busy||pane.hidden)return;element=selected;render()},close,isOpen:()=>!pane.hidden,isBusy:()=>busy,dispose(){disposed=true;generation++;clearPalettes();pane.remove()}}
}
