import type { Node as PmNode } from '@tiptap/pm/model'
import { TableMap } from '@tiptap/pm/tables'
import { fitColumnWidths, MIN_TABLE_COLUMN_PX } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/table-column-width-source'
export { Schema } from '@tiptap/pm/model'
export { TableMap } from '@tiptap/pm/tables'
export type TableColumnWidthStep = { kind: 'setTableColumnWidth'; left: number; right: number; widthTwips: number } | { kind: 'distributeTableColumns'; left: number; right: number }
const fail = (): never => { throw new Error('docx_table_column_width_invalid') }
const positive = (n: unknown): n is number => Number.isSafeInteger(n) && Number(n) > 0
/** 来源 fit 保留两位像素；整数 DOCX 按最大余数分配，相同余数优先前列。 */
function quantize(px: number[], max: number): number[] {
  const exact = px.map(w => w * 15), result = exact.map(w => Math.floor(w + 1e-8))
  const total = Math.min(max, Math.round(exact.reduce((a, b) => a + b, 0)))
  const order = exact.map((w, i) => ({ i, fraction: w - result[i] })).sort((a, b) => b.fraction - a.fraction || a.i - b.i)
  let left = total - result.reduce((a, b) => a + b, 0)
  for (const { i } of order) { if (left-- <= 0) break; result[i]++ }
  if (result.some(w => !positive(w)) || result.reduce((a, b) => a + b, 0) > max) fail()
  return result
}
export function applyTableColumnWidthSteps(table: PmNode, widthsTwips: number[], maxWidthTwips: number, steps: readonly TableColumnWidthStep[]): { table: PmNode; widthsTwips: number[] } {
  if (!positive(maxWidthTwips) || maxWidthTwips > 31680 || !Array.isArray(widthsTwips) || !Array.isArray(steps) || !steps.length || steps.length > 50 || table.type.spec.tableRole !== 'table' || table.childCount > 100 || !table.childCount) fail()
  let count = 0
  table.forEach(row => { if (row.type.spec.tableRole !== 'row' || row.childCount > 30) fail(); row.forEach(cell => { if (!positive(cell.attrs.colspan) || cell.attrs.colspan > 30 || !positive(cell.attrs.rowspan) || cell.attrs.rowspan > 100 || cell.attrs.gridGap || ++count > 1000) fail() }) })
  table.check()
  const map = TableMap.get(table)
  if (map.problems?.length || map.width < 1 || map.width > 30 || map.height > 100 || map.width * map.height > 1000 || widthsTwips.length !== map.width || widthsTwips.some(w => !positive(w) || w > 31680)) fail()
  let widths = [...widthsTwips]
  for (const step of steps) {
    if (!step || typeof step !== 'object' || Array.isArray(step)) fail()
    const fields = step.kind === 'setTableColumnWidth' ? ['kind', 'left', 'right', 'widthTwips'] : ['kind', 'left', 'right']
    if (Object.keys(step).length !== fields.length || Object.keys(step).some(k => !fields.includes(k)) || !Number.isSafeInteger(step.left) || !Number.isSafeInteger(step.right) || step.left < 0 || step.right <= step.left || step.right > map.width) fail()
    const requested = new Map<number, number>()
    if (step.kind === 'setTableColumnWidth') {
      if (!positive(step.widthTwips) || step.widthTwips > 31680) fail()
      for (let c = step.left; c < step.right; c++) requested.set(c, Math.max(1, Math.round(step.widthTwips / 15)))
    } else if (step.kind === 'distributeTableColumns') {
      const from = step.right - step.left > 1 ? step.left : 0, to = step.right - step.left > 1 ? step.right : map.width
      const average = widths.slice(from, to).reduce((a, b) => a + b, 0) / (to - from) / 15
      for (let c = from; c < to; c++) requested.set(c, average)
    } else fail()
    const current = widths.map(w => w / 15)
    const fitted = fitColumnWidths(current, requested, maxWidthTwips / 15)
    // 非请求列若仅发生来源0.01px取整，保留其原整数宽度，避免多步漂移。
    const floor = Math.min(MIN_TABLE_COLUMN_PX, maxWidthTwips / 15 / map.width)
    const desired = current.map((w, c) => requested.get(c) ?? w)
    const unchangedTotal = step.kind === 'distributeTableColumns' && desired.every(w => w >= floor) && widths.reduce((a, b) => a + b, 0) <= maxWidthTwips
    // 均分未触发来源floor/fit时，以原始整数总宽分配，不累计来源0.01px舍入误差。
    const exact = unchangedTotal ? desired : fitted.map((w, c) => !requested.has(c) && Math.abs(w - current[c]) <= 0.005001 ? current[c] : w)
    widths = quantize(exact, maxWidthTwips)
  }
  let rowOffset = 0
  const rows: PmNode[] = []
  table.forEach(row => {
    let cellOffset = 0
    const cells: PmNode[] = []
    row.forEach(cell => { const rect = map.findCell(rowOffset + 1 + cellOffset); cells.push(cell.type.create({ ...cell.attrs, colwidth: widths.slice(rect.left, rect.right).map(w => w / 15) }, cell.content, cell.marks)); cellOffset += cell.nodeSize })
    rows.push(row.type.create(row.attrs, cells, row.marks)); rowOffset += row.nodeSize
  })
  const total = widths.reduce((a, b) => a + b, 0)
  return { table: table.type.create({ ...table.attrs, widthPx: total / 15, widthPct: null, colWidthsPct: widths.map(w => w * 100 / total) }, rows, table.marks), widthsTwips: widths }
}
