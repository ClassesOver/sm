import type {Schema} from '@tiptap/pm/model'
import type {DocxAnchor,DocxPmNode} from './docx-operations'
import {applyTableAlignment,tableAlignmentState,type TableAlignment,type TableAlignmentSource,type TableAlignmentDisplayIndents} from './docx-table-alignment-core'
export interface DocxTableAlignmentAnchor {tableAlignmentDisplayIndents?:TableAlignmentDisplayIndents;tableAlignmentEditable?:boolean;tableAlignmentReadOnlyReason?:string|null;tableAlignmentSource?:TableAlignmentSource}
const intents=['nativeTableAltText','nativeTableCellWrap','nativeTableStructure','nativeTableCellShape','nativeTableColumnWidths','nativeTableRowHeights','nativeTableAutoFit','nativeTableInsert','nativeTableCellTextDirection','nativeTableCellAlignment','nativeTableCellMargins','nativeTableCellMarginOverrides','nativeTableRowBreaks']
export function projectDocxTableAlignment(source:DocxPmNode,anchor:DocxAnchor&DocxTableAlignmentAnchor,alignment:TableAlignment,schema?:Schema):DocxPmNode{
 const baseline=anchor.tableAlignmentSource
 if(!schema||source.type!=='docTable'||!anchor.tableAlignmentEditable||!baseline)throw new Error(anchor.tableAlignmentReadOnlyReason??'当前来源表格不支持修改整表对齐')
 if(intents.some(k=>source.attrs?.[k]))throw new Error('整表对齐不能与同表其他修改混用，请先保存')
 if(![null,'center','right'].includes(baseline.alignment)||typeof baseline.bidiVisual!=='boolean'||!['inline','floating'].includes(baseline.positioning)||[baseline.raw,baseline.rawIndent,baseline.rawWidth].some(v=>v!==null&&typeof v!=='string')||!Array.isArray(baseline.cells))throw new Error('整表对齐来源快照无效')
 const pending=source.attrs?.nativeTableAlignment as {alignment:TableAlignment}|null|undefined
 if(pending&&(typeof pending!=='object'||Object.keys(pending).length!==1||!['left','center','right'].includes(pending.alignment)))throw new Error('整表对齐草稿无效')
 const table=schema.nodeFromJSON(source),state=tableAlignmentState(table),expected=pending?(pending.alignment==='left'?null:pending.alignment):baseline.alignment
 if(state.alignment!==expected||Boolean(table.attrs.bidiVisual)!==baseline.bidiVisual||JSON.stringify(state.cells)!==JSON.stringify(baseline.cells.map(({top,left,bottom,right})=>({top,left,bottom,right}))))throw new Error('整表对齐来源值或网格与当前文件不一致')
 const indents=anchor.tableAlignmentDisplayIndents
 if(indents&&(Object.keys(indents).length!==3||['left','center','right'].some(key=>!Object.hasOwn(indents,key)||indents[key as TableAlignment]!==null&&(typeof indents[key as TableAlignment]!=='number'||!Number.isFinite(indents[key as TableAlignment])))||table.attrs.indentTwips!==indents[expected==='center'||expected==='right'?expected:'left']))throw new Error('整表对齐显示缩进与来源不一致')
 const json=applyTableAlignment(table,alignment,indents).toJSON() as DocxPmNode
 json.attrs={...json.attrs,nativeTableAlignment:{alignment}}
 return schema.nodeFromJSON(json).toJSON() as DocxPmNode
}
