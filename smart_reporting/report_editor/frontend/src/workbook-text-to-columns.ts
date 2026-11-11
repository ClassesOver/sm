import { formatAddress } from '@sheets-web/xlsx-engine'
import type { ICellData, IRange, Nullable } from '@univerjs/core'
import { CellValueType } from '@univerjs/core'
import { textToColumnChanges } from './workbook-vendor/core/data-tools'

type SplitRange = { getRange(): IRange; getCellDatas(): Nullable<ICellData>[][] }
type SplitSheet = {
  getMaxColumns(): number
  getRange(row: number, column: number, rows: number, columns: number): SplitRange
  getMergedRanges(): { getRange(): IRange }[]
}

/** 复用现有分列规划器；全部预检完成后，由调用方一次写入官方命令。 */
export function planWorkbookTextToColumns(sheet: SplitSheet, active: SplitRange, delimiter: string) {
  const { startRow, endRow, startColumn, endColumn } = active.getRange()
  if (startColumn !== endColumn) throw new Error('文本分列请选择单列区域')
  const rows = endRow - startRow + 1
  if (rows > 2000) throw new Error('文本分列单次最多处理 2000 行，请缩小选区')
  const source = active.getCellDatas()
  let widest = 0, populated = 0
  for (const row of source) {
    const cell = row[0]
    if (cell?.f || cell?.si || cell?.p) throw new Error('文本分列暂不支持公式或富文本来源，请使用普通文本单元格')
    if (cell?.v === null || cell?.v === undefined) continue
    populated += 1
    widest = Math.max(widest, String(cell.v).split(delimiter).length)
    if (widest * populated > 2000) throw new Error('文本分列结果超过 2000 个单元格，请缩小选区')
  }
  const changes = textToColumnChanges({ sheet: '', range: `${formatAddress(startRow, startColumn)}:${formatAddress(endRow, startColumn)}`, delimiter },
    row => {
      const cell = source[row - startRow]?.[0]
      return cell?.t === CellValueType.BOOLEAN && (cell.v === 0 || cell.v === 1) ? cell.v === 1 : cell?.v
    })
  if (!changes.length) throw new Error('选区没有可分列的数据')
  const lastColumn = Math.max(...changes.map(change => change.column))
  if (lastColumn === startColumn) throw new Error('选区未找到所选分隔符')
  if (lastColumn >= Math.min(sheet.getMaxColumns(), 16384)) throw new Error('分列结果超出工作表列边界')
  if (changes.length > 2000) throw new Error('文本分列结果超过 2000 个单元格，请缩小选区')
  if (sheet.getMergedRanges().some(item => {
    const merge = item.getRange()
    return merge.startRow <= endRow && merge.endRow >= startRow && merge.startColumn <= lastColumn && merge.endColumn >= startColumn
  })) throw new Error('分列来源或目标包含合并单元格，请使用普通区域')
  const target = sheet.getRange(startRow, startColumn, rows, lastColumn - startColumn + 1).getCellDatas()
  const value: Record<number, Record<number, { v: string | number | boolean | null }>> = {}
  for (const change of changes) {
    const cell = target[change.row - startRow]?.[change.column - startColumn]
    if (change.column !== startColumn && (cell?.f || cell?.si || cell?.p || (cell?.v !== null && cell?.v !== undefined && cell?.v !== ''))) {
      throw new Error('分列目标右侧已有数据或公式，请先清空目标区域')
    }
    ;(value[change.row] ??= {})[change.column] = { v: change.value }
  }
  return { value, count: changes.length }
}
