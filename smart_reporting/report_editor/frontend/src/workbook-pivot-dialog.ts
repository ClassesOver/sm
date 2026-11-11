import './workbook-pivot.css'
import { readWorkbook, parseRange, formatAddress } from '@sheets-web/xlsx-engine'
import { createModal } from './modal'
import type { PivotConfig, PivotValue, WorkbookPivot } from './workbook-pivot'

type Input = {bytes:Uint8Array;sourceSheetName:string;sourceRange:string;targetCell:string;pivots?:WorkbookPivot[];selectedTablePath?:string}
const aggregations=[['sum','求和'],['count','计数'],['average','平均值'],['max','最大值'],['min','最小值']]
/** 字段配置仅在确定时提交；关闭、取消和无效来源都不修改草稿。 */
export function createPivotDialog(root:HTMLElement,apply:(config:PivotConfig,tablePath?:string)=>Promise<void>){
 let input:Input,config:PivotConfig,fields:string[]=[],busy=false,epoch=0,selected:WorkbookPivot|undefined
 let sourceTables:{sheet:string;range:string;label:string;name:string}[]=[],members:Record<string,string[]>={}
 const modal=createModal({root,label:'数据透视表',closeLabel:'关闭数据透视表',variant:'wide',overlayClass:'workbook-ribbon-format-overlay',cardClass:'workbook-ribbon-format-dialog workbook-pivot-dialog',onRequestClose:()=>{if(!busy){epoch++;modal.close()}},content:
 '<h2>数据透视表</h2><form class="workbook-ribbon-format-form"><label data-existing>选择透视表<select aria-label="选择透视表"></select></label><label>名称<input aria-label="透视表名称"></label><label>来源表<select aria-label="来源表"><option value="">使用单元格区域</option></select></label><label>来源工作表<select aria-label="来源工作表"></select></label><label>来源区域<input aria-label="来源区域" placeholder="A1:E100"></label><button type="button" data-action="fields">读取来源字段</button><p data-fields></p><div data-axes></div><label>目标工作表<select aria-label="目标工作表"></select></label><label>目标起点<input aria-label="目标起点" placeholder="H1"></label><p>来源首行为唯一、非空字段名，最多10000条数据、200列。选择来源表后，刷新会跟随表区域变化（不含合计行）。至少一个行字段；值字段最多8个，列字段支持多个值。纯数值及日期序列分组可写入标准 Excel 分组；文本、空值或不可表达的日期使用兼容分组，桌面 Excel 刷新可能恢复原值。切片器/时间线另设筛选入口。</p><p class="workbook-ribbon-format-error" role="alert"></p><div class="workbook-ribbon-format-actions"><button type="button" data-action="cancel">取消</button><button type="submit" class="workbook-ribbon-format-apply">确定</button></div></form>'})
 const find=<T extends HTMLElement>(selector:string)=>modal.card.querySelector<T>(selector)!
 const source=find<HTMLSelectElement>('[aria-label="来源工作表"]'),range=find<HTMLInputElement>('[aria-label="来源区域"]'),target=find<HTMLSelectElement>('[aria-label="目标工作表"]'),anchor=find<HTMLInputElement>('[aria-label="目标起点"]'),name=find<HTMLInputElement>('[aria-label="透视表名称"]'),existing=find<HTMLSelectElement>('[aria-label="选择透视表"]'),error=find<HTMLElement>('[role="alert"]'),axes=find<HTMLElement>('[data-axes]')
 const option=(value:string,label=value)=>{const element=document.createElement('option');element.value=value;element.textContent=label;return element}
 const button=(label:string,action:()=>void)=>{const element=document.createElement('button');element.type='button';element.textContent=label;element.addEventListener('click',action);return element}
 const render=()=>{
  axes.replaceChildren()
  for(const [key,label] of [['rows','行字段'],['columns','列字段'],['values','值字段']] as const){
   const section=document.createElement('fieldset'),legend=document.createElement('legend');legend.textContent=label
   const chooser=document.createElement('select');chooser.dataset.field=key;chooser.setAttribute('aria-label','添加'+label);chooser.append(...fields.map(field=>option(field)))
   const items=key==='rows'?config.rowFields:key==='columns'?config.columnFields:config.values
   const add=button('添加'+label,()=>{if(!chooser.value)return;if(key==='values')config.values.push({field:chooser.value,agg:'sum'});else if(!items.includes(chooser.value as never))(items as string[]).push(chooser.value);render()});add.dataset.add=key
   section.append(legend,chooser,add)
   items.forEach((item,index)=>{
    const row=document.createElement('div');row.dataset.axisItem=key
    const text=document.createElement('span');text.textContent=typeof item==='string'?item:item.field;row.append(text)
    if(typeof item!=='string'){
     const aggregation=document.createElement('select');aggregation.setAttribute('aria-label',item.field+' 聚合方式');aggregation.append(...aggregations.map(([value,label])=>option(value!,label!)));aggregation.value=item.agg;aggregation.addEventListener('change',()=>{item.agg=aggregation.value as PivotValue['agg']})
     const mode=document.createElement('select');mode.setAttribute('aria-label',item.field+' 显示方式');mode.append(option('','普通值'),option('percentOfTotal','占总计百分比'),option('percentOfRow','占行总计百分比'),option('percentOfCol','占列总计百分比'));mode.value=item.showDataAs??'';mode.addEventListener('change',()=>{if(mode.value)item.showDataAs=mode.value as PivotValue['showDataAs'];else delete item.showDataAs})
     const fmt=document.createElement('input');fmt.setAttribute('aria-label',item.field+' 数字格式');fmt.placeholder='常用格式，例如 0.00';fmt.value=item.numFmt??'';fmt.addEventListener('input',()=>{if(fmt.value)item.numFmt=fmt.value;else delete item.numFmt})
     row.append(aggregation,mode,fmt)
     if(item.formula!==undefined){aggregation.disabled=true;const formula=document.createElement('input');formula.setAttribute('aria-label',item.field+' 公式');formula.value=item.formula;formula.addEventListener('input',()=>{item.formula=formula.value});row.append(formula)}
    }
    if(typeof item==='string'){
     const grouping=document.createElement('select');grouping.setAttribute('aria-label',item+' 分组');grouping.append(option('','不分组'),option('year','按年'),option('quarter','按季度'),option('month','按月'),option('range','数值区间'))
     const rule=config.groupings?.find(rule=>rule.field===item);grouping.value=rule?.kind==='date'?rule.dateUnit:rule?.kind??''
     grouping.addEventListener('change',()=>{config.groupings=(config.groupings??[]).filter(rule=>rule.field!==item);if(grouping.value)config.groupings=[...config.groupings,grouping.value==='range'?{field:item,kind:'range',rangeStep:10}:{field:item,kind:'date',dateUnit:grouping.value as 'year'|'quarter'|'month'}];render()});row.append(grouping)
     if(rule?.kind==='range')for(const [key,label] of [['rangeStep','分组间距'],['rangeStart','分组起点']] as const){const number=document.createElement('input');number.type='number';number.setAttribute('aria-label',item+' '+label);number.value=String(rule[key]??0);number.addEventListener('input',()=>{config.groupings=(config.groupings??[]).map(entry=>entry.field===item?{...entry,[key]:Number(number.value)}:entry)});row.append(number)}
    }
    row.append(button('上移',()=>{if(index){const previous=items[index-1]!;(items as unknown[])[index-1]=item;(items as unknown[])[index]=previous;render()}}),button('下移',()=>{if(index+1<items.length){const next=items[index+1]!;(items as unknown[])[index+1]=item;(items as unknown[])[index]=next;render()}}),button('移除',()=>{items.splice(index,1);render()}));section.append(row)
   });axes.append(section)
  }
  const calculated=document.createElement('fieldset'),calcLegend=document.createElement('legend');calcLegend.textContent='计算字段';calculated.append(calcLegend)
  const calcName=document.createElement('input'),calcFormula=document.createElement('input');calcName.setAttribute('aria-label','计算字段名称');calcFormula.setAttribute('aria-label','计算字段公式');calcFormula.placeholder='例如 收入/数量'
  const addCalculated=button('添加计算字段',()=>{if(!calcName.value.trim()||!calcFormula.value.trim())return;config.values.push({field:calcName.value.trim(),agg:'sum',formula:calcFormula.value.trim()});render()});addCalculated.dataset.add='calculated';calculated.append(calcName,calcFormula,addCalculated);axes.append(calculated)
  const pages=document.createElement('fieldset'),pageLegend=document.createElement('legend');pageLegend.textContent='报告筛选';pages.append(pageLegend)
  const pageChooser=document.createElement('select');pageChooser.dataset.field='pages';pageChooser.setAttribute('aria-label','添加报告筛选');pageChooser.append(...fields.map(field=>option(field)))
  const addPage=button('添加报告筛选',()=>{if(!pageChooser.value||(config.pageFilters??[]).some(filter=>filter.field===pageChooser.value))return;config.pageFilters=[...(config.pageFilters??[]),{field:pageChooser.value}];render()});addPage.dataset.add='pages';pages.append(pageChooser,addPage)
  ;(config.pageFilters??[]).forEach((filter,index)=>{const row=document.createElement('div'),label=document.createElement('span'),select=document.createElement('select');label.textContent=filter.field;select.multiple=true;select.setAttribute('aria-label',filter.field+' 报告筛选成员');select.append(...(members[filter.field]??[]).map(value=>option(value)));for(const option of select.options)option.selected=!filter.selected||filter.selected.includes(option.value);select.addEventListener('change',()=>{const selected=Array.from(select.selectedOptions,option=>option.value);config.pageFilters=(config.pageFilters??[]).map((entry,i)=>i===index?{field:entry.field,selected}:entry)});row.append(label,select,button('移除',()=>{config.pageFilters=(config.pageFilters??[]).filter((_,i)=>i!==index);render()}));pages.append(row)})
  axes.append(pages)
 }
 const readFields=async()=>{
  const generation=++epoch
  try{const workbook=await readWorkbook(input.bytes),sheet=workbook.sheets.find(sheet=>sheet.name===source.value);if(!sheet)throw new Error('来源工作表不存在');const area=parseRange(range.value);if(area.endColumn-area.startColumn>=200||area.endRow-area.startRow>10000)throw new Error('透视表来源最多10000条数据、200列');const next=[];for(let column=area.startColumn;column<=area.endColumn;column++)next.push(String(sheet.cells[formatAddress(area.startRow,column)]?.value??'').trim());if(next.some(field=>!field)||new Set(next.map(field=>field.toLowerCase())).size!==next.length)throw new Error('来源首行字段必须非空且唯一');if(generation!==epoch)return;fields=next;members=Object.fromEntries(next.map((field,offset)=>[field,Array.from({length:area.endRow-area.startRow},(_,i)=>String(sheet.cells[formatAddress(area.startRow+i+1,area.startColumn+offset)]?.value??'')).filter((value,index,all)=>all.indexOf(value)===index)]));find('[data-fields]').textContent='可用字段：'+fields.join('、');error.textContent='';render()}catch(cause){if(generation===epoch){fields=[];axes.replaceChildren();error.textContent=(cause as Error).message}}
 }
 const populate=async(pivot?:WorkbookPivot)=>{
  selected=pivot;config=pivot?structuredClone(pivot):{name:'数据透视表'+Date.now(),sourceSheetName:input.sourceSheetName,sourceRange:input.sourceRange,targetSheetName:input.sourceSheetName,targetCell:input.targetCell,rowFields:[],columnFields:[],values:[]}
  find<HTMLSelectElement>('[aria-label="来源表"]').value=config.sourceTableName?String(sourceTables.findIndex(table=>table.name===config.sourceTableName)):'';
  name.value=config.name;source.value=config.sourceSheetName;range.value=config.sourceRange;target.value=config.targetSheetName;anchor.value=config.targetCell
  name.disabled=target.disabled=anchor.disabled=Boolean(pivot)
  await readFields();if(pivot?.readonlyReason)error.textContent=pivot.readonlyReason
 }
 find<HTMLSelectElement>('[aria-label="来源表"]').addEventListener('change',event=>{const value=(event.target as HTMLSelectElement).value,table=value===''?undefined:sourceTables[Number(value)];if(table){config.sourceTableName=table.name;source.value=table.sheet;range.value=table.range;void readFields()}else delete config.sourceTableName})
 existing.addEventListener('change',()=>{void populate(input.pivots?.find(pivot=>pivot.tablePath===existing.value))})
 find('[data-action="fields"]').addEventListener('click',()=>{void readFields()})
 find('[data-action="cancel"]').addEventListener('click',()=>{if(!busy){epoch++;modal.close()}})
 find('form').addEventListener('submit',event=>{
  event.preventDefault();if(busy)return
  if(selected?.readonlyReason){error.textContent=selected.readonlyReason;return}
  if(!fields.length){error.textContent='请先读取有效来源字段';return}
  busy=true;modal.card.querySelectorAll<HTMLButtonElement>('button').forEach(button=>{button.disabled=true})
  void apply({...config,name:name.value.trim(),sourceSheetName:source.value,sourceRange:range.value.trim(),targetSheetName:target.value,targetCell:anchor.value.trim()},selected?.tablePath).then(()=>{epoch++;modal.close()},cause=>{error.textContent=(cause as Error).message}).finally(()=>{busy=false;modal.card.querySelectorAll<HTMLButtonElement>('button').forEach(button=>{button.disabled=false})})
 })
 return {async open(value:Input){input=value;const workbook=await readWorkbook(value.bytes);sourceTables=workbook.sheets.flatMap(sheet=>(sheet.tables??[]).filter(table=>table.headerRowCount>0).map(table=>({sheet:sheet.name,label:table.displayName+' · '+sheet.name,name:table.name,range:formatAddress(table.range.startRow,table.range.startColumn)+':'+formatAddress(table.range.endRow-table.totalsRowCount,table.range.endColumn)})));find<HTMLSelectElement>('[aria-label="来源表"]').replaceChildren(option('','使用单元格区域'),...sourceTables.map((table,index)=>option(String(index),table.label)));source.replaceChildren(...workbook.sheets.map(sheet=>option(sheet.name)));target.replaceChildren(...workbook.sheets.map(sheet=>option(sheet.name)));existing.replaceChildren(...(value.pivots??[]).map(pivot=>option(pivot.tablePath,pivot.name+' · '+pivot.targetSheetName+'!'+pivot.targetCell)));find('[data-existing]').hidden=!value.pivots;const pivot=value.pivots?.find(pivot=>pivot.tablePath===value.selectedTablePath)??value.pivots?.[0];if(pivot)existing.value=pivot.tablePath;await populate(pivot);modal.open(name)},dispose:modal.remove}
}
