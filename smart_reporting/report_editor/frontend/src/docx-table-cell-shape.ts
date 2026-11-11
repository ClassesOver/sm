import { TableMap } from '@tiptap/pm/tables'
import type { Schema } from '@tiptap/pm/model'
import type { DocxAnchor, DocxPmNode } from './docx-operations'
import { applyTableCellShapeSteps, type TableCellShapeStep } from './docx-table-cell-shape-core'

export interface DocxCellShapeSource { top: number; left: number; bottom: number; right: number; physicalRow: number; physicalColumn: number }

/** Project only a server-issued source; logical coordinates never replace physical cell IDs. */
export function projectDocxCellShape(source: DocxPmNode, anchor: DocxAnchor, steps: readonly TableCellShapeStep[], schema?: Schema): DocxPmNode {
  if (!schema || source.type !== 'docTable' || !anchor.cellShapeEditable || !anchor.cellShapeCells || !anchor.cellShapeWidthsTwips) throw new Error(anchor.cellShapeReadOnlyReason ?? '当前来源表格不支持合并或拆分')
  if (source.attrs?.nativeTableAltText || source.attrs?.nativeTableCellWrap || source.attrs?.nativeTableAlignment || source.attrs?.nativeTableRowBreaks || source.attrs?.nativeTableCellMarginOverrides || source.attrs?.nativeTableCellMargins || source.attrs?.nativeTableCellAlignment || source.attrs?.nativeTableStructure) throw new Error('合并拆分不能与同表行列增删混用，请先保存')
  const table = schema.nodeFromJSON(source), map = TableMap.get(table)
  const cells: DocxCellShapeSource[] = []
  table.forEach((row, rowOffset, physicalRow) => row.forEach((_cell, offset, physicalColumn) => {
    const rect = map.findCell(rowOffset + 1 + offset)
    cells.push({ top: rect.top, left: rect.left, bottom: rect.bottom, right: rect.right, physicalRow, physicalColumn })
  }))
  // PM omits vertical continuation cells; its child index is not an XML cell index.
  const logical = (items: DocxCellShapeSource[]) => items.map(({ top, left, bottom, right }) => ({ top, left, bottom, right }))
  if (map.problems?.length || map.width !== anchor.cellShapeWidthsTwips.length || JSON.stringify(logical(cells)) !== JSON.stringify(logical(anchor.cellShapeCells))) throw new Error('合并拆分的来源网格与当前文件不一致')
  const result = applyTableCellShapeSteps(table, anchor.cellShapeWidthsTwips, steps).table.toJSON() as DocxPmNode
  result.attrs = { ...result.attrs, nativeTableCellShape: { steps } }
  return schema.nodeFromJSON(result).toJSON() as DocxPmNode
}
