import { TableMap } from '@tiptap/pm/tables'
import type { Schema } from '@tiptap/pm/model'
import type { DocxAnchor, DocxPmNode } from './docx-operations'
import type { DocxCellShapeSource } from './docx-table-cell-shape'
import { applyTableColumnWidthSteps, type TableColumnWidthStep } from './docx-table-column-width-core'

export interface DocxColumnWidthAnchor {
  columnWidthEditable?: boolean
  columnWidthReadOnlyReason?: string | null
  columnWidthsTwips?: number[]
  columnWidthMaxTwips?: number
  columnWidthCells?: DocxCellShapeSource[]
}
/** 只接受服务端签发的来源网格；物理 continuation 坐标不参与 PM 逻辑列匹配。 */
function columnWidthSource(source: DocxPmNode, anchor: DocxAnchor & DocxColumnWidthAnchor, schema?: Schema) {
  if (!schema || source.type !== 'docTable' || !anchor.columnWidthEditable || !anchor.columnWidthCells || !anchor.columnWidthsTwips || !anchor.columnWidthMaxTwips) throw new Error(anchor.columnWidthReadOnlyReason ?? '当前来源表格不支持调整列宽')
  if (source.attrs?.nativeTableAltText || source.attrs?.nativeTableCellWrap || source.attrs?.nativeTableAlignment || source.attrs?.nativeTableRowBreaks || source.attrs?.nativeTableCellMarginOverrides || source.attrs?.nativeTableCellMargins || source.attrs?.nativeTableCellAlignment || source.attrs?.nativeTableStructure || source.attrs?.nativeTableCellShape) throw new Error('列宽不能与同表合并拆分或行列增删混用，请先保存')
  const table = schema.nodeFromJSON(source), map = TableMap.get(table)
  const cells: { top: number; left: number; bottom: number; right: number }[] = []
  table.forEach((row, rowOffset) => row.forEach((_cell, offset) => {
    const { top, left, bottom, right } = map.findCell(rowOffset + 1 + offset)
    cells.push({ top, left, bottom, right })
  }))
  const expected = anchor.columnWidthCells.map(({ top, left, bottom, right }) => ({ top, left, bottom, right }))
  if (map.problems?.length || map.width !== anchor.columnWidthsTwips.length || JSON.stringify(cells) !== JSON.stringify(expected)) throw new Error('列宽来源网格与当前文件不一致')
  if (anchor.columnWidthsTwips.some(width => !Number.isSafeInteger(width) || width <= 0)) throw new Error('列宽来源宽度无效')
  return { table, map, widths: anchor.columnWidthsTwips, maxWidth: anchor.columnWidthMaxTwips }
}
export function projectDocxColumnWidths(source: DocxPmNode, anchor: DocxAnchor & DocxColumnWidthAnchor, steps: readonly TableColumnWidthStep[], schema?: Schema): DocxPmNode {
  const { table, widths, maxWidth } = columnWidthSource(source, anchor, schema)
  const result = applyTableColumnWidthSteps(table, widths, maxWidth, steps).table.toJSON() as DocxPmNode
  result.attrs = { ...result.attrs, nativeTableColumnWidths: { steps } }
  return schema!.nodeFromJSON(result).toJSON() as DocxPmNode
}

/** 来源转换器会取整到像素；建立 baseline 前恢复签发的整数 twip，不登记编辑步骤。 */
export function normalizeDocxColumnWidthSources(doc: DocxPmNode, anchors: readonly (DocxAnchor & DocxColumnWidthAnchor)[], schema: Schema): DocxPmNode {
  return { ...doc, content: doc.content?.map(source => {
    const anchor = anchors.find(item => item.docxIndex === source.attrs?.docxIndex)
    if (source.type !== 'docTable' || !anchor?.columnWidthEditable) return source
    // 草稿必须由原 baseline 重放，不能用来源宽度覆盖已提交的意图。
    if (source.attrs?.nativeTableColumnWidths || source.attrs?.nativeTableCellShape || source.attrs?.nativeTableStructure) return source
    const { table, map, widths } = columnWidthSource(source, anchor, schema)
    const total = widths.reduce((sum, width) => sum + width, 0)
    let rowOffset = 0
    const rows: typeof table[] = []
    table.forEach(row => {
      let cellOffset = 0
      const cells: typeof table[] = []
      row.forEach(cell => {
        const rect = map.findCell(rowOffset + 1 + cellOffset)
        cells.push(cell.type.create({ ...cell.attrs, colwidth: widths.slice(rect.left, rect.right).map(width => width / 15) }, cell.content, cell.marks))
        cellOffset += cell.nodeSize
      })
      rows.push(row.type.create(row.attrs, cells, row.marks)); rowOffset += row.nodeSize
    })
    return table.type.create({ ...table.attrs, widthPx: total / 15, widthPct: null, colWidthsPct: widths.map(width => width * 100 / total) }, rows, table.marks).toJSON() as DocxPmNode
  }) }
}
