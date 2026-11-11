import { TableMap } from '@tiptap/pm/tables'
import type { Schema } from '@tiptap/pm/model'
import type { DocxAnchor, DocxPmNode } from './docx-operations'
import type { DocxCellShapeSource } from './docx-table-cell-shape'
import { applyTableCellTextDirectionSteps, type TableCellTextDirectionStep } from './docx-table-cell-text-direction-core'
export interface DocxCellTextDirectionAnchor {
  cellTextDirectionEditable?: boolean
  cellTextDirectionReadOnlyReason?: string | null
  cellTextDirectionCells?: DocxCellShapeSource[]
  cellTextDirections?: ('tbRl' | 'btLr' | null)[]
}
/** 按来源逻辑owner投影方向；别名已由engine有效归一，rawTcPr不作重写。 */
export function projectDocxCellTextDirection(source: DocxPmNode, anchor: DocxAnchor & DocxCellTextDirectionAnchor, steps: readonly TableCellTextDirectionStep[], schema?: Schema): DocxPmNode {
  if (!schema || source.type !== 'docTable' || !anchor.cellTextDirectionEditable || !anchor.cellTextDirectionCells || !anchor.cellTextDirections) throw new Error(anchor.cellTextDirectionReadOnlyReason ?? '当前来源表格不支持修改文字方向')
  if (['nativeTableAltText','nativeTableCellWrap','nativeTableAlignment','nativeTableRowBreaks','nativeTableCellMarginOverrides','nativeTableStructure','nativeTableCellShape','nativeTableColumnWidths','nativeTableRowHeights','nativeTableAutoFit','nativeTableInsert','nativeTableCellTextDirection','nativeTableCellMargins','nativeTableCellAlignment'].some(key => source.attrs?.[key])) throw new Error('文字方向不能与同表其他结构修改混用，请先保存')
  const table = schema.nodeFromJSON(source), map = TableMap.get(table)
  const cells: { top: number; left: number; bottom: number; right: number }[] = [], directions: unknown[] = []
  table.forEach((row, offset) => row.forEach((cell, cellOffset) => {
    const { top, left, bottom, right } = map.findCell(offset + 1 + cellOffset)
    cells.push({ top, left, bottom, right }); directions.push(cell.attrs.textDirection ?? null)
  }))
  const expected = anchor.cellTextDirectionCells.map(({ top, left, bottom, right }) => ({ top, left, bottom, right }))
  if (map.problems?.length || JSON.stringify(cells) !== JSON.stringify(expected)) throw new Error('文字方向来源网格与当前文件不一致')
  if (JSON.stringify(directions) !== JSON.stringify(anchor.cellTextDirections)) throw new Error('文字方向来源值与当前文件不一致')
  const result = applyTableCellTextDirectionSteps(table, steps).table.toJSON() as DocxPmNode
  result.attrs = { ...result.attrs, nativeTableCellTextDirection: { steps } }
  return schema.nodeFromJSON(result).toJSON() as DocxPmNode
}
