import { TableMap } from '@tiptap/pm/tables'
import type { Schema } from '@tiptap/pm/model'
import type { DocxAnchor, DocxPmNode } from './docx-operations'
import type { DocxCellShapeSource } from './docx-table-cell-shape'
import { applyTableRowHeightSteps, type TableRowHeightStep } from './docx-table-row-height-core'
export interface DocxRowHeightAnchor {
  rowHeightEditable?: boolean
  rowHeightReadOnlyReason?: string | null
  rowHeightMaxTwips?: number
  rowHeightsTwips?: (number | null)[]
  rowHeightRules?: ('exact' | 'atLeast' | null)[]
  rowHeightCells?: DocxCellShapeSource[]
}
/** 只重放受签发行带；来源高度、规则及逻辑格网必须与baseline一致。 */
export function projectDocxRowHeights(source: DocxPmNode, anchor: DocxAnchor & DocxRowHeightAnchor, steps: readonly TableRowHeightStep[], schema?: Schema): DocxPmNode {
  if (!schema || source.type !== 'docTable' || !anchor.rowHeightEditable || !anchor.rowHeightCells || !anchor.rowHeightsTwips || !anchor.rowHeightRules || !anchor.rowHeightMaxTwips) throw new Error(anchor.rowHeightReadOnlyReason ?? '当前来源表格不支持调整行高')
  if (source.attrs?.nativeTableAltText || source.attrs?.nativeTableCellWrap || source.attrs?.nativeTableAlignment || source.attrs?.nativeTableRowBreaks || source.attrs?.nativeTableCellMarginOverrides || source.attrs?.nativeTableCellMargins || source.attrs?.nativeTableCellAlignment || source.attrs?.nativeTableStructure || source.attrs?.nativeTableCellShape || source.attrs?.nativeTableColumnWidths) throw new Error('行高不能与同表列宽、合并拆分或行列增删混用，请先保存')
  const table = schema.nodeFromJSON(source), map = TableMap.get(table)
  const cells: { top: number; left: number; bottom: number; right: number }[] = []
  table.forEach((row, rowOffset) => row.forEach((_cell, offset) => {
    const { top, left, bottom, right } = map.findCell(rowOffset + 1 + offset)
    cells.push({ top, left, bottom, right })
  }))
  const expected = anchor.rowHeightCells.map(({ top, left, bottom, right }) => ({ top, left, bottom, right }))
  if (map.problems?.length || JSON.stringify(cells) !== JSON.stringify(expected) || anchor.rowHeightsTwips.length !== table.childCount || anchor.rowHeightRules.length !== table.childCount) throw new Error('行高来源网格与当前文件不一致')
  table.forEach((row, _offset, index) => {
    if ((row.attrs.heightTwips ?? null) !== anchor.rowHeightsTwips![index] || (row.attrs.heightTwips == null ? null : row.attrs.heightRule === 'exact' ? 'exact' : 'atLeast') !== anchor.rowHeightRules![index]) throw new Error('行高来源高度或规则与当前文件不一致')
  })
  const result = applyTableRowHeightSteps(table, anchor.rowHeightMaxTwips, steps).table.toJSON() as DocxPmNode
  result.attrs = { ...result.attrs, nativeTableRowHeights: { steps } }
  return schema.nodeFromJSON(result).toJSON() as DocxPmNode
}
