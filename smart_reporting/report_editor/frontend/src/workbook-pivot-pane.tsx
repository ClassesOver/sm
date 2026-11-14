/** 固定源 PivotFieldPane 的宿主桥接；计算与写包仍走现有 PivotConfig 链路。 */
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { PivotFieldPane } from './vendor/genoffice-sheets-pivot/PivotFieldPane'
import type { PivotField, PivotLayoutModel, PivotValueFilterOption } from './vendor/genoffice-sheets-pivot/pivot-field-model'
import type { PivotConfig, PivotValue } from './workbook-pivot'
import './vendor/genoffice-docs/packages/ui/src/dropdown.css'
import './workbook-pivot-pane.css'

export function pivotPaneModel(config: PivotConfig, fields: readonly PivotField[]): PivotLayoutModel {
 const index=(name:string)=>fields.findIndex(field=>field.label===name)
 return {
  rows:config.rowFields.map(index),columns:config.columnFields.map(index),
  filters:(config.pageFilters??[]).map(page=>({fieldIndex:index(page.field),item:page.selected?.length===1?page.selected[0]!:null,selected:page.selected})),
  values:config.values.map((value,valueIndex)=>({...value,fieldIndex:value.formula===undefined?index(value.field):-1,...(value.formula!==undefined?{calcName:value.field}:{}),filter:config.filters?.find(filter=>filter.kind==='value'&&filter.valueIndex===valueIndex) as PivotValueFilterOption|undefined})),
  groupings:Object.fromEntries((config.groupings??[]).map(rule=>[index(rule.field),rule])),
  labelFilters:Object.fromEntries((config.filters??[]).filter(rule=>rule.kind==='label').map(rule=>[index(rule.field),rule])),
 }
}
export function pivotPaneConfig(config: PivotConfig, fields: readonly PivotField[], model: PivotLayoutModel): PivotConfig {
 const label=(index:number)=>fields[index]!.label
 const axis=new Set([...model.rows,...model.columns])
 return {...config,rowFields:model.rows.map(label),columnFields:model.columns.map(label),
  pageFilters:model.filters.map(page=>({field:label(page.fieldIndex),...(page.item===null?((page as typeof page & {selected?:readonly string[]}).selected?{selected:(page as typeof page & {selected:readonly string[]}).selected}:{}):{selected:[page.item]})})),
  values:model.values.map(value=>({field:value.formula===undefined?label(value.fieldIndex):value.calcName??'',agg:value.agg as PivotValue['agg'],...(value.formula!==undefined?{formula:value.formula}:{}),...(value.showDataAs?{showDataAs:value.showDataAs as PivotValue['showDataAs']}:{}),...(value.numFmt?{numFmt:value.numFmt}:{})})),
  groupings:Object.entries(model.groupings).filter(([index])=>axis.has(Number(index))).map(([index,rule])=>({...rule,field:label(Number(index))})),
  filters:[...Object.entries(model.labelFilters).filter(([index])=>axis.has(Number(index))).map(([index,rule])=>({...rule,kind:'label' as const,field:label(Number(index))})),...model.values.flatMap((value,valueIndex)=>value.filter&&model.rows[0]!==undefined?[{...value.filter,kind:'value' as const,field:label(model.rows[0]),valueIndex}]:[])],
 }
}
export function createPivotPane(root:HTMLElement){
 const reactRoot=createRoot(root)
 return {render(props:Parameters<typeof PivotFieldPane>[0]){flushSync(()=>reactRoot.render(createElement(PivotFieldPane,props)))},dispose(){reactRoot.unmount()}}
}
