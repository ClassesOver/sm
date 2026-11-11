import { TableMap } from '@tiptap/pm/tables'
import type { Schema } from '@tiptap/pm/model'
import type { DocxAnchor, DocxPmNode } from './docx-operations'
import type { DocxCellShapeSource } from './docx-table-cell-shape'
import { applyTableAutoFitSteps, type TableAutoFitStep } from './docx-table-autofit-core'

export interface DocxAutoFitAnchor {
  autoFitEditable?: boolean
  autoFitReadOnlyReason?: string | null
  autoFitMode?: 'contents' | 'window' | 'fixed'
  autoFitWidthsTwips?: number[]
  autoFitContentWidthTwips?: number
  autoFitCells?: DocxCellShapeSource[]
}
const intents = ['nativeTableAltText','nativeTableCellWrap','nativeTableAlignment','nativeTableRowBreaks','nativeTableCellMarginOverrides','nativeTableStructure', 'nativeTableCellShape', 'nativeTableColumnWidths', 'nativeTableRowHeights', 'nativeTableInsert', 'nativeTableAutoFit', 'nativeTableCellMargins','nativeTableCellAlignment']
function autoFitSource(source: DocxPmNode, anchor: DocxAnchor & DocxAutoFitAnchor, schema?: Schema) {
  if (!schema || source.type !== 'docTable' || !anchor.autoFitEditable || !anchor.autoFitCells || !anchor.autoFitWidthsTwips || !anchor.autoFitContentWidthTwips || !anchor.autoFitMode) throw new Error(anchor.autoFitReadOnlyReason ?? '当前来源表格不支持自动调整列宽')
  if (intents.some(key => source.attrs?.[key])) throw new Error('自动调整不能与同表其他结构修改混用，请先保存')
  const table = schema.nodeFromJSON(source), map = TableMap.get(table)
  const cells: { top: number; left: number; bottom: number; right: number }[] = []
  table.forEach((row, offset) => row.forEach((_cell, cellOffset) => {
    const { top, left, bottom, right } = map.findCell(offset + 1 + cellOffset)
    cells.push({ top, left, bottom, right })
  }))
  const expected = anchor.autoFitCells.map(({ top, left, bottom, right }) => ({ top, left, bottom, right }))
  if (map.problems?.length || map.width !== anchor.autoFitWidthsTwips.length || JSON.stringify(cells) !== JSON.stringify(expected)) throw new Error('自动调整来源网格与当前文件不一致')
  if (table.attrs.tblAutoFit !== anchor.autoFitMode || anchor.autoFitWidthsTwips.some(width => !Number.isSafeInteger(width) || width <= 0) || !Number.isSafeInteger(anchor.autoFitContentWidthTwips) || anchor.autoFitContentWidthTwips <= 0) throw new Error('自动调整来源模式或宽度与当前文件不一致')
  return { table, map, widths: anchor.autoFitWidthsTwips, contentWidth: anchor.autoFitContentWidthTwips }
}
export function projectDocxAutoFit(source: DocxPmNode, anchor: DocxAnchor & DocxAutoFitAnchor, steps: readonly TableAutoFitStep[], schema?: Schema): DocxPmNode {
  const { table, widths, contentWidth } = autoFitSource(source, anchor, schema)
  const result = applyTableAutoFitSteps(table, widths, contentWidth, steps).table.toJSON() as DocxPmNode
  result.attrs = { ...result.attrs, nativeTableAutoFit: { steps } }
  return schema!.nodeFromJSON(result).toJSON() as DocxPmNode
}
/** 初始baseline前恢复可信整数twip精度；保留进口模式、首选宽度及显示用属性，不记编辑意图。 */
export function normalizeDocxAutoFitSources(doc: DocxPmNode, anchors: readonly (DocxAnchor & DocxAutoFitAnchor)[], schema: Schema): DocxPmNode {
  return { ...doc, content: doc.content?.map(source => {
    const anchor = anchors.find(item => item.docxIndex === source.attrs?.docxIndex)
    if (source.type !== 'docTable' || !anchor?.autoFitEditable || intents.some(key => source.attrs?.[key])) return source
    const { table, map, widths } = autoFitSource(source, anchor, schema)
    const rows: typeof table[] = []
    table.forEach((row, offset) => {
      const cells: typeof table[] = []
      row.forEach((cell, cellOffset) => {
        const rect = map.findCell(offset + 1 + cellOffset)
        cells.push(cell.type.create({ ...cell.attrs, colwidth: widths.slice(rect.left, rect.right).map(width => width / 15) }, cell.content, cell.marks))
      })
      rows.push(row.type.create(row.attrs, cells, row.marks))
    })
    return table.type.create(table.attrs, rows, table.marks).toJSON() as DocxPmNode
  }) }
}
