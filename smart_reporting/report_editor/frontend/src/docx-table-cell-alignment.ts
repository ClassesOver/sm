import {TableMap} from '@tiptap/pm/tables'
import type {Schema} from '@tiptap/pm/model'
import type {DocxAnchor,DocxPmNode} from './docx-operations'
import type {DocxCellShapeSource} from './docx-table-cell-shape'
import {applyTableCellAlignmentSteps,tableCellAlignmentState,type TableCellAlignmentStep,type CellAlignmentParagraph} from './docx-table-cell-alignment-core'
export interface DocxCellAlignmentAnchor {
 cellAlignmentEditable?:boolean
 cellAlignmentReadOnlyReason?:string|null
 cellAlignmentCells?:DocxCellShapeSource[]
 cellAlignments?:('center'|'bottom'|null)[]
 cellAlignmentParagraphs?:CellAlignmentParagraph[][]
}
export function projectDocxCellAlignment(source:DocxPmNode,anchor:DocxAnchor&DocxCellAlignmentAnchor,steps:readonly TableCellAlignmentStep[],schema?:Schema):DocxPmNode{
 if(!schema||source.type!=='docTable'||!anchor.cellAlignmentEditable||!anchor.cellAlignmentCells||!anchor.cellAlignments||!anchor.cellAlignmentParagraphs)throw new Error(anchor.cellAlignmentReadOnlyReason??'当前来源表格不支持修改单元格对齐')
 if(['nativeTableAltText','nativeTableCellWrap','nativeTableAlignment','nativeTableRowBreaks','nativeTableCellMarginOverrides','nativeTableStructure','nativeTableCellShape','nativeTableColumnWidths','nativeTableRowHeights','nativeTableAutoFit','nativeTableInsert','nativeTableCellTextDirection','nativeTableCellMargins','nativeTableCellAlignment'].some(k=>source.attrs?.[k]))throw new Error('单元格对齐不能与同表其他结构修改混用，请先保存')
 const table=schema.nodeFromJSON(source),map=TableMap.get(table),cells:{top:number;left:number;bottom:number;right:number}[]=[]
 table.forEach((row,offset)=>row.forEach((_cell,cellOffset)=>{const{top,left,bottom,right}=map.findCell(offset+1+cellOffset);cells.push({top,left,bottom,right})}))
 const expected=anchor.cellAlignmentCells.map(({top,left,bottom,right})=>({top,left,bottom,right})),state=tableCellAlignmentState(table)
 if(map.problems?.length||JSON.stringify(cells)!==JSON.stringify(expected))throw new Error('单元格对齐来源网格与当前文件不一致')
 if(JSON.stringify(state.alignments)!==JSON.stringify(anchor.cellAlignments)||JSON.stringify(state.paragraphs)!==JSON.stringify(anchor.cellAlignmentParagraphs))throw new Error('单元格对齐来源段落或方向与当前文件不一致')
 const result=applyTableCellAlignmentSteps(table,steps).table.toJSON() as DocxPmNode
 result.attrs={...result.attrs,nativeTableCellAlignment:{steps}}
 return schema.nodeFromJSON(result).toJSON() as DocxPmNode
}
