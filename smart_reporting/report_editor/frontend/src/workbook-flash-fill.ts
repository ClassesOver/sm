import { inferFlashFillTemplate, applyFlashFillTemplate } from '@sheets-web/xlsx-engine'
import type { ICellData, IRange, Nullable } from '@univerjs/core'

type FlashRange = { getRange(): IRange; getValues(): unknown[][]; getCellDatas(): Nullable<ICellData>[][] }
type FlashSheet = {
  getMaxRows(): number
  getRange(row: number, column: number, rows: number, columns: number): FlashRange
  getMergedRanges(): { getRange(): IRange }[]
}

/** 固定源 ribbon-actions.ts:2082：左侧最多六列、单格向下探测最多 1000 行。
 * 复用引擎的字段拼接推断；只规划空白目标，保留已有公式、富文本及样式。
 * 一次稀疏 set-range-values 命令实现单次撤销，先完成全部校验再交给调用方写入。 */
export function planWorkbookFlashFill(sheet: FlashSheet, active: FlashRange) {
  const { startRow, endRow: selectedEnd, startColumn: column, endColumn } = active.getRange()
  if (column === 0) throw new Error('快速填充需要目标列左侧的数据')
  if (column !== endColumn) throw new Error('快速填充请选择单列目标区域')
  let endRow = selectedEnd
  if (endRow === startRow) {
    const probe = sheet.getRange(startRow, column - 1, Math.min(1000, sheet.getMaxRows() - startRow), 1).getValues()
    for (const [offset, row] of probe.entries()) {
      if (row[0] === null || row[0] === undefined || String(row[0]) === '') break
      endRow = startRow + offset
    }
  }
  const rows = endRow - startRow + 1, firstColumn = Math.max(0, column - 6)
  if (rows < 2) throw new Error('快速填充至少需要两行数据')
  if (rows > 1000) throw new Error('快速填充单次最多处理 1000 行，请缩小选区')
  if (sheet.getMergedRanges().some(item => {
    const merge = item.getRange()
    return merge.startRow <= endRow && merge.endRow >= startRow && merge.startColumn <= column && merge.endColumn >= firstColumn
  })) throw new Error('快速填充的来源或目标区域包含合并单元格，请使用普通单元格区域')
  const range = sheet.getRange(startRow, firstColumn, rows, column - firstColumn + 1)
  const grid = range.getValues(), raw = range.getCellDatas(), target = column - firstColumn
  const occupied = (cell: Nullable<ICellData>, value: unknown) => !!(cell?.f || cell?.si || cell?.p) || (value !== null && value !== undefined && value !== '')
  const sourceOf = (row: unknown[]) => row.slice(0, target).map(value => String(value ?? ''))
  const examples = grid.flatMap((row, index) => {
    const cell = raw[index]?.[target], output = row[target]
    return occupied(cell, output) && !cell?.f && !cell?.si && !cell?.p && output !== null && output !== undefined && output !== ''
      ? [{ source: sourceOf(row), output: String(output) }] : []
  })
  if (!examples.length) throw new Error('请先在目标列输入一个或多个填充示例')
  const template = inferFlashFillTemplate(examples)
  if (!template) throw new Error('无法从示例推断字段拼接模式；暂不支持截取或大小写转换')
  const value: Record<number, Record<number, { v: string }>> = {}
  let count = 0
  grid.forEach((row, index) => {
    if (occupied(raw[index]?.[target], row[target])) return
    const source = sourceOf(row)
    if (source.every(item => item.trim() === '')) return
    const output = applyFlashFillTemplate(template, source)
    if (output.length > 32767) throw new Error('快速填充结果超过单元格文本长度上限')
    value[startRow + index] = { [column]: { v: output } }; count += 1
  })
  if (!count) throw new Error('目标区域没有可填充的空白单元格')
  return { value, count }
}
