import type {Schema} from '@tiptap/pm/model'
import type {DocxAnchor,DocxPmNode} from './docx-operations'
import {applyTableRowBreakSteps,replayTableRowBreakSteps,tableRowBreakState,type TableRowBreakStep,type TableRowBreakSource} from './docx-table-row-breaks-core'
export interface DocxRowBreakAnchor {rowBreakEditable?:boolean;rowBreakReadOnlyReason?:string|null;rowBreakSource?:TableRowBreakSource}
const intents=['nativeTableAltText','nativeTableCellWrap','nativeTableAlignment','nativeTableStructure','nativeTableCellShape','nativeTableColumnWidths','nativeTableRowHeights','nativeTableAutoFit','nativeTableInsert','nativeTableCellTextDirection','nativeTableCellAlignment','nativeTableCellMargins','nativeTableCellMarginOverrides']
export function projectDocxRowBreaks(source:DocxPmNode,anchor:DocxAnchor&DocxRowBreakAnchor,steps:readonly TableRowBreakStep[],schema?:Schema):DocxPmNode{
 const baseline=anchor.rowBreakSource
 if(!schema||source.type!=='docTable'||!anchor.rowBreakEditable||!baseline)throw new Error(anchor.rowBreakReadOnlyReason??'当前来源表格不支持修改行跨页设置')
 if(intents.some(k=>source.attrs?.[k]))throw new Error('行跨页设置不能与同表其他修改混用，请先保存')
 if(!Array.isArray(baseline.cells)||!Array.isArray(baseline.rows)||baseline.rows.some(r=>!r||typeof r.cantSplit!=='boolean'||!(r.raw===null||typeof r.raw==='string')))throw new Error('行跨页来源快照无效')
 const pending=source.attrs?.nativeTableRowBreaks as {steps:TableRowBreakStep[]}|null|undefined
 if(pending&&(typeof pending!=='object'||Object.keys(pending).length!==1||!Array.isArray(pending.steps)))throw new Error('行跨页草稿意图无效')
 const table=schema.nodeFromJSON(source),state=tableRowBreakState(table),flags=baseline.rows.map(r=>r.cantSplit),expected=pending?replayTableRowBreakSteps(flags,pending.steps).cantSplit:flags
 if(JSON.stringify(state.cells)!==JSON.stringify(baseline.cells.map(({top,left,bottom,right})=>({top,left,bottom,right})))||JSON.stringify(state.cantSplit)!==JSON.stringify(expected))throw new Error('行跨页来源网格或标记与当前文件不一致')
 const result=applyTableRowBreakSteps(table,[...(pending?.steps??[]),...steps]),json=result.table.toJSON() as DocxPmNode
 json.attrs={...json.attrs,nativeTableRowBreaks:{steps:result.steps}}
 return schema.nodeFromJSON(json).toJSON() as DocxPmNode
}
