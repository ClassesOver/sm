import type {Schema} from '@tiptap/pm/model'
import type {DocxAnchor,DocxPmNode} from './docx-operations'
import {applyTableCellMargins,normalizeTableCellMargins,tableCellMarginsState,type TableCellMargins,type TableCellMarginsSource} from './docx-table-cell-margins-core'
export interface DocxCellMarginsAnchor {
 tableCellMarginsEditable?:boolean
 tableCellMarginsReadOnlyReason?:string|null
 tableCellMarginsSource?:TableCellMarginsSource
}
const intents=['nativeTableAltText','nativeTableCellWrap','nativeTableAlignment','nativeTableRowBreaks','nativeTableCellMarginOverrides','nativeTableStructure','nativeTableCellShape','nativeTableColumnWidths','nativeTableRowHeights','nativeTableAutoFit','nativeTableInsert','nativeTableCellTextDirection','nativeTableCellAlignment','nativeTableCellMargins']
export function projectDocxCellMargins(source:DocxPmNode,anchor:DocxAnchor&DocxCellMarginsAnchor,margins:TableCellMargins,schema?:Schema):DocxPmNode{
 const baseline=anchor.tableCellMarginsSource
 if(!schema||source.type!=='docTable'||!anchor.tableCellMarginsEditable||!baseline)throw new Error(anchor.tableCellMarginsReadOnlyReason??'当前来源表格不支持修改默认单元格边距')
 if(intents.some(key=>source.attrs?.[key])||source.attrs?.cellMarEdited)throw new Error('默认单元格边距不能与同表其他修改混用，请先保存')
 if(!(baseline.raw===null||typeof baseline.raw==='string')||!Array.isArray(baseline.cells))throw new Error('默认单元格边距来源快照无效')
 const table=schema.nodeFromJSON(source),state=tableCellMarginsState(table),expected={defaults:normalizeTableCellMargins(baseline.defaults),cells:baseline.cells.map(cell=>normalizeTableCellMargins(cell))}
 if(JSON.stringify(state)!==JSON.stringify(expected))throw new Error('默认单元格边距来源或单格覆盖与当前文件不一致')
 const result=applyTableCellMargins(table,margins).toJSON() as DocxPmNode
 result.attrs={...result.attrs,nativeTableCellMargins:{margins:{...margins}}}
 return schema.nodeFromJSON(result).toJSON() as DocxPmNode
}
