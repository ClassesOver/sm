import './workbook-pivot.css'
import { readWorkbook, parseRange, formatAddress } from '@sheets-web/xlsx-engine'
import { formatCodeFor } from '@sheets-web/xlsx-engine/style-read'
import { isCalendarDatePattern } from './vendor/genoffice-sheets-pivot/calendar-date-pattern'
import { createModal } from './modal'
import type { PivotConfig, WorkbookPivot } from './workbook-pivot'
import { createPivotPane, pivotPaneModel, pivotPaneConfig } from './workbook-pivot-pane'
import type { PivotField } from './vendor/genoffice-sheets-pivot/pivot-field-model'

type Input = {bytes:Uint8Array;sourceSheetName:string;sourceRange:string;targetCell:string;pivots?:WorkbookPivot[];selectedTablePath?:string}
/** 固定源字段窗格；现有透视表即时更新，推迟布局更新时保留待提交状态。 */
export function createPivotDialog(root:HTMLElement,apply:(config:PivotConfig,tablePath?:string)=>Promise<void>){
 let input:Input,config:PivotConfig,fields:string[]=[],paneFields:PivotField[]=[],busy=false,deferred=false,fieldDirty=false,editVersion=0,commitGeneration=0,commitQueue=Promise.resolve(),epoch=0,selected:WorkbookPivot|undefined
 let sourceTables:{sheet:string;range:string;label:string;name:string}[]=[],members:Record<string,string[]>={}
 const modal=createModal({root,label:'数据透视表',closeLabel:'关闭数据透视表',variant:'wide',overlayClass:'workbook-ribbon-format-overlay',cardClass:'workbook-ribbon-format-dialog workbook-pivot-dialog',onRequestClose:()=>{if(!busy){epoch++;commitGeneration++;modal.close()}},content:
 '<h2>数据透视表</h2><form class="workbook-ribbon-format-form"><label data-existing>选择透视表<select aria-label="选择透视表"></select></label><label>名称<input aria-label="透视表名称"></label><label>来源表<select aria-label="来源表"><option value="">使用单元格区域</option></select></label><label>来源工作表<select aria-label="来源工作表"></select></label><label>来源区域<input aria-label="来源区域" placeholder="A1:E100"></label><button type="button" data-action="fields">读取来源字段</button><p data-fields></p><div data-field-pane></div><div data-axes></div><p data-pending role="status"></p><label>目标工作表<select aria-label="目标工作表"></select></label><label>目标起点<input aria-label="目标起点" placeholder="H1"></label><p>来源首行为唯一、非空字段名，最多10000条数据、200列。选择来源表后，刷新会跟随表区域变化（不含合计行）。至少一个行字段；值字段最多8个，列字段支持多个值。纯数值及日期序列分组可写入标准 Excel 分组；文本、空值或不可表达的日期使用兼容分组，桌面 Excel 刷新可能恢复原值。切片器/时间线另设筛选入口。</p><p class="workbook-ribbon-format-error" role="alert"></p><div class="workbook-ribbon-format-actions"><button type="button" data-action="cancel">取消</button><button type="submit" class="workbook-ribbon-format-apply">更新</button></div></form>'})
 const find=<T extends HTMLElement>(selector:string)=>modal.card.querySelector<T>(selector)!
 const source=find<HTMLSelectElement>('[aria-label="来源工作表"]'),range=find<HTMLInputElement>('[aria-label="来源区域"]'),target=find<HTMLSelectElement>('[aria-label="目标工作表"]'),anchor=find<HTMLInputElement>('[aria-label="目标起点"]'),name=find<HTMLInputElement>('[aria-label="透视表名称"]'),existing=find<HTMLSelectElement>('[aria-label="选择透视表"]'),error=find<HTMLElement>('[role="alert"]'),axes=find<HTMLElement>('[data-axes]')
 const option=(value:string,label=value)=>{const element=document.createElement('option');element.value=value;element.textContent=label;return element}
 const button=(label:string,action:()=>void)=>{const element=document.createElement('button');element.type='button';element.textContent=label;element.addEventListener('click',action);return element}
 const paneHost=find<HTMLElement>('[data-field-pane]'),pane=createPivotPane(paneHost)
 const configForApply=()=>structuredClone({...config,name:name.value.trim(),sourceSheetName:source.value,sourceRange:range.value.trim(),targetSheetName:target.value,targetCell:anchor.value.trim()})
 const pending=()=>{find('[data-pending]').textContent=busy?'正在更新透视表…':fieldDirty?'有待更新的字段布局':''}
 const commit=async(closeAfter:boolean,snapshot:PivotConfig,generation:number,version:number,tablePath?:string)=>{
  if(generation!==commitGeneration)return
  busy=true;pending();paneHost.inert=true
  const controls=Array.from(modal.card.querySelectorAll<HTMLInputElement|HTMLButtonElement|HTMLSelectElement>('input,button,select')),disabled=controls.map(element=>element.disabled)
  controls.forEach(element=>{element.disabled=true})
  try{await apply(snapshot,tablePath);if(generation===commitGeneration){if(version===editVersion)fieldDirty=false;error.textContent='';if(closeAfter){epoch++;commitGeneration++;modal.close()}}}
  catch(cause){if(generation===commitGeneration){fieldDirty=true;error.textContent=(cause as Error).message}}
  finally{busy=false;paneHost.inert=false;controls.forEach((element,index)=>{element.disabled=disabled[index]!});pending();if(generation===commitGeneration)render()}
 }
 const enqueue=(closeAfter:boolean)=>{if(busy)return;if(!fields.length||selected?.readonlyReason){error.textContent=selected?.readonlyReason??(error.textContent||'请先读取有效来源字段');return}const snapshot=configForApply(),generation=commitGeneration,version=editVersion,tablePath=selected?.tablePath;commitQueue=commitQueue.then(()=>commit(closeAfter,snapshot,generation,version,tablePath));void commitQueue}
 const markEdited=()=>{if(busy)return;fieldDirty=true;editVersion++;pending();if(selected&&!deferred)enqueue(false)}
 const render=()=>{
  axes.replaceChildren()
  pane.render({fields:paneFields,model:pivotPaneModel(config,paneFields),onModelChange:next=>{if(busy)return;config=pivotPaneConfig(config,paneFields,next);markEdited();render()},deferred,onDeferredChange:value=>{if(busy)return;deferred=value;if(!value&&fieldDirty)enqueue(false);render()},dirty:fieldDirty,error:error.textContent||null,onUpdate:()=>enqueue(!selected),onClose:()=>{if(!busy){epoch++;commitGeneration++;modal.close()}},onGetFieldMembers:index=>members[fields[index]!]??[]})
  const calculated=document.createElement('details'),summary=document.createElement('summary');summary.textContent='添加计算字段';calculated.append(summary)
  const calcName=document.createElement('input'),calcFormula=document.createElement('input');calcName.setAttribute('aria-label','计算字段名称');calcFormula.setAttribute('aria-label','计算字段公式');calcFormula.placeholder='例如 收入/数量'
  const addCalculated=button('添加计算字段',()=>{if(busy||!calcName.value.trim()||!calcFormula.value.trim())return;config.values.push({field:calcName.value.trim(),agg:'sum',formula:calcFormula.value.trim()});markEdited();render()});addCalculated.dataset.add='calculated';calculated.append(calcName,calcFormula,addCalculated);axes.append(calculated)
  pending()
 }
 const readFields=async()=>{
  const generation=++epoch;commitGeneration++;fields=[];paneHost.hidden=true;find<HTMLButtonElement>('[type="submit"]').disabled=true
  try{const workbook=await readWorkbook(input.bytes),sheet=workbook.sheets.find(sheet=>sheet.name===source.value);if(!sheet)throw new Error('来源工作表不存在');const area=parseRange(range.value);if(area.endColumn-area.startColumn>=200||area.endRow-area.startRow>10000)throw new Error('透视表来源最多10000条数据、200列');const next:string[]=[];for(let column=area.startColumn;column<=area.endColumn;column++)next.push(String(sheet.cells[formatAddress(area.startRow,column)]?.value??'').trim());if(next.some(field=>!field)||new Set(next.map(field=>field.toLowerCase())).size!==next.length)throw new Error('来源首行字段必须非空且唯一');if(generation!==epoch)return;const required=[...config.rowFields,...config.columnFields,...(config.pageFilters??[]).map(page=>page.field),...config.values.filter(value=>value.formula===undefined).map(value=>value.field)],missing=required.filter((field,index)=>!next.includes(field)&&required.indexOf(field)===index);if(missing.length)throw new Error('来源缺少已配置字段：'+missing.join('、')+'。已保留原布局，请恢复来源或重新打开配置。');paneHost.hidden=false;find<HTMLButtonElement>('[type="submit"]').disabled=Boolean(selected?.readonlyReason);fields=next;paneFields=next.map((label,offset)=>{const cells=Array.from({length:area.endRow-area.startRow},(_,i)=>sheet.cells[formatAddress(area.startRow+i+1,area.startColumn+offset)]).filter(cell=>cell?.value!==undefined&&cell.value!==null&&cell.value!=='');return {label,colIndex:area.startColumn+offset,numeric:cells.length>0&&cells.every(cell=>{if(typeof cell.value!=='number')return false;const xf=workbook.styles.cellXfs[cell.styleIndex??0];return !isCalendarDatePattern(xf?formatCodeFor(workbook.styles,xf):'')})}});members=Object.fromEntries(next.map((field,offset)=>[field,Array.from({length:area.endRow-area.startRow},(_,i)=>String(sheet.cells[formatAddress(area.startRow+i+1,area.startColumn+offset)]?.value??'')).filter((value,index,all)=>all.indexOf(value)===index)]));find('[data-fields]').textContent='可用字段：'+fields.join('、');error.textContent='';render()}catch(cause){if(generation===epoch){fields=[];paneHost.hidden=true;axes.replaceChildren();error.textContent=(cause as Error).message}}
 }
  const populate=async(pivot?:WorkbookPivot)=>{
  commitGeneration++;selected=pivot;deferred=false;fieldDirty=false;editVersion=0;config=pivot?structuredClone(pivot):{name:'数据透视表'+Date.now(),sourceSheetName:input.sourceSheetName,sourceRange:input.sourceRange,targetSheetName:input.sourceSheetName,targetCell:input.targetCell,rowFields:[],columnFields:[],values:[]}
  find<HTMLSelectElement>('[aria-label="来源表"]').value=config.sourceTableName?String(sourceTables.findIndex(table=>table.name===config.sourceTableName)):'';
  name.value=config.name;source.value=config.sourceSheetName;range.value=config.sourceRange;target.value=config.targetSheetName;anchor.value=config.targetCell
  name.disabled=target.disabled=anchor.disabled=Boolean(pivot)
  await readFields();if(pivot?.readonlyReason)error.textContent=pivot.readonlyReason
 }
 find<HTMLSelectElement>('[aria-label="来源表"]').addEventListener('change',event=>{const value=(event.target as HTMLSelectElement).value,table=value===''?undefined:sourceTables[Number(value)];if(table){config.sourceTableName=table.name;source.value=table.sheet;range.value=table.range;void readFields()}else delete config.sourceTableName})
 const invalidateSource=()=>{epoch++;commitGeneration++;fields=[];paneHost.hidden=true;find<HTMLButtonElement>('[type="submit"]').disabled=true;error.textContent='来源已变化，请重新读取来源字段；原布局已保留。'}
 range.addEventListener('input',invalidateSource);source.addEventListener('change',invalidateSource)
 existing.addEventListener('change',()=>{void populate(input.pivots?.find(pivot=>pivot.tablePath===existing.value))})
 find('[data-action="fields"]').addEventListener('click',()=>{void readFields()})
 find('[data-action="cancel"]').addEventListener('click',()=>{if(!busy){epoch++;commitGeneration++;modal.close()}})
 find('form').addEventListener('submit',event=>{
  event.preventDefault();if(busy)return
  if(selected?.readonlyReason){error.textContent=selected.readonlyReason;return}
  if(!fields.length){error.textContent=error.textContent||'请先读取有效来源字段';return}
  enqueue(!selected)
 })
 return {async open(value:Input){input=value;const workbook=await readWorkbook(value.bytes);sourceTables=workbook.sheets.flatMap(sheet=>(sheet.tables??[]).filter(table=>table.headerRowCount>0).map(table=>({sheet:sheet.name,label:table.displayName+' · '+sheet.name,name:table.name,range:formatAddress(table.range.startRow,table.range.startColumn)+':'+formatAddress(table.range.endRow-table.totalsRowCount,table.range.endColumn)})));find<HTMLSelectElement>('[aria-label="来源表"]').replaceChildren(option('','使用单元格区域'),...sourceTables.map((table,index)=>option(String(index),table.label)));source.replaceChildren(...workbook.sheets.map(sheet=>option(sheet.name)));target.replaceChildren(...workbook.sheets.map(sheet=>option(sheet.name)));existing.replaceChildren(...(value.pivots??[]).map(pivot=>option(pivot.tablePath,pivot.name+' · '+pivot.targetSheetName+'!'+pivot.targetCell)));find('[data-existing]').hidden=!value.pivots;const pivot=value.pivots?.find(pivot=>pivot.tablePath===value.selectedTablePath)??value.pivots?.[0];if(pivot)existing.value=pivot.tablePath;await populate(pivot);modal.open(name)},dispose:()=>{epoch++;commitGeneration++;pane.dispose();modal.remove()}}
}
