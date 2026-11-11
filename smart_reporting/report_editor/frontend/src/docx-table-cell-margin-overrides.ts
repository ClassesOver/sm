import type {Schema} from '@tiptap/pm/model'
import type {DocxAnchor,DocxPmNode} from './docx-operations'
import {applyTableCellMarginOverrideSteps,replayTableCellMarginOverrides,type TableCellMarginOverrideStep,type TableCellMarginOverridesSource} from './docx-table-cell-margin-overrides-core'
import {normalizeTableCellMargins} from './docx-table-cell-margins-core'
export interface DocxCellMarginOverridesAnchor {tableCellMarginOverridesEditable?:boolean;tableCellMarginOverridesReadOnlyReason?:string|null;tableCellMarginOverridesSource?:TableCellMarginOverridesSource}
const intents=['nativeTableAltText','nativeTableCellWrap','nativeTableAlignment','nativeTableRowBreaks','nativeTableStructure','nativeTableCellShape','nativeTableColumnWidths','nativeTableRowHeights','nativeTableAutoFit','nativeTableInsert','nativeTableCellTextDirection','nativeTableCellAlignment','nativeTableCellMargins']
export function projectDocxCellMarginOverrides(source:DocxPmNode,anchor:DocxAnchor&DocxCellMarginOverridesAnchor,steps:readonly TableCellMarginOverrideStep[],schema?:Schema):DocxPmNode{
 const baseline=anchor.tableCellMarginOverridesSource
 if(!schema||source.type!=='docTable'||!anchor.tableCellMarginOverridesEditable||!baseline)throw new Error(anchor.tableCellMarginOverridesReadOnlyReason??'当前来源表格不支持修改单元格边距覆盖')
 if(intents.some(key=>source.attrs?.[key])||source.attrs?.cellMarEdited)throw new Error('单元格边距覆盖不能与同表其他修改混用，请先保存')
 const pending=source.attrs?.nativeTableCellMarginOverrides as {steps:TableCellMarginOverrideStep[]}|null|undefined
 if(pending&&(typeof pending!=='object'||Object.keys(pending).length!==1||!Array.isArray(pending.steps)))throw new Error('单元格边距覆盖意图无效')
 const all=[...(pending?.steps??[]),...steps],table=schema.nodeFromJSON(source)
 // 校验重复编辑前的PM等于原可信快照回放，不能用当前client属性重新签发来源。
 const expected=pending?replayTableCellMarginOverrides(baseline,pending.steps).margins:baseline.cells.map(c=>normalizeTableCellMargins(c.effective))
 const actual:unknown[]=[];table.forEach(row=>row.forEach(cell=>actual.push(normalizeTableCellMargins(cell.attrs.cellMar))))
 if(JSON.stringify(actual)!==JSON.stringify(expected))throw new Error('单元格边距覆盖来源值与当前文件不一致')
 const result=applyTableCellMarginOverrideSteps(table,all,baseline),json=result.table.toJSON() as DocxPmNode
 json.attrs={...json.attrs,nativeTableCellMarginOverrides:{steps:result.steps}}
 return schema.nodeFromJSON(json).toJSON() as DocxPmNode
}
