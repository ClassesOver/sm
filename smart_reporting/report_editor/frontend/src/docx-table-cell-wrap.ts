import type {Schema} from '@tiptap/pm/model'
import type {DocxAnchor,DocxPmNode} from './docx-operations'
import {applyTableCellWrapSteps,replayTableCellWrapSteps,type TableCellWrapStep,type TableCellWrapSource} from './docx-table-cell-wrap-core'
export interface DocxCellWrapAnchor {tableCellWrapEditable?:boolean;tableCellWrapReadOnlyReason?:string|null;tableCellWrapSource?:TableCellWrapSource}
const intents=['nativeTableAltText','nativeTableAlignment','nativeTableRowBreaks','nativeTableStructure','nativeTableCellShape','nativeTableColumnWidths','nativeTableRowHeights','nativeTableAutoFit','nativeTableInsert','nativeTableCellTextDirection','nativeTableCellAlignment','nativeTableCellMargins','nativeTableCellMarginOverrides']
export function projectDocxCellWrap(source:DocxPmNode,anchor:DocxAnchor&DocxCellWrapAnchor,steps:readonly TableCellWrapStep[],schema?:Schema):DocxPmNode{
 const baseline=anchor.tableCellWrapSource
 if(!schema||source.type!=='docTable'||!anchor.tableCellWrapEditable||!baseline)throw new Error(anchor.tableCellWrapReadOnlyReason??'当前来源表格不支持修改单元格自动换行')
 if(intents.some(key=>source.attrs?.[key])||source.attrs?.cellMarEdited)throw new Error('单元格自动换行不能与同表其他修改混用，请先保存')
 const pending=source.attrs?.nativeTableCellWrap as {steps:TableCellWrapStep[]}|null|undefined
 if(pending&&(typeof pending!=='object'||Object.keys(pending).length!==1||!Array.isArray(pending.steps)))throw new Error('单元格自动换行意图无效')
 const all=[...(pending?.steps??[]),...steps],table=schema.nodeFromJSON(source)
 // 校验重复编辑前的PM等于原可信快照回放，不能用当前client属性重新签发来源。
 const expected=pending?replayTableCellWrapSteps(baseline,pending.steps).noWrap:baseline.cells.map(c=>c.noWrap)
 const actual:unknown[]=[];table.forEach(row=>row.forEach(cell=>actual.push(cell.attrs.noWrap===true)))
 if(JSON.stringify(actual)!==JSON.stringify(expected))throw new Error('单元格自动换行来源值与当前文件不一致')
 const result=applyTableCellWrapSteps(table,all,baseline),json=result.table.toJSON() as DocxPmNode
 json.attrs={...json.attrs,nativeTableCellWrap:{steps:result.steps}}
 return schema.nodeFromJSON(json).toJSON() as DocxPmNode
}
