import type { Node as PmNode } from '@tiptap/pm/model'
import { TableMap } from '@tiptap/pm/tables'
export { Schema } from '@tiptap/pm/model'
export type TableAutoFitMode = 'contents' | 'window' | 'fixed'
export type TableAutoFitStep = { mode: TableAutoFitMode }
const fail = (): never => { throw new Error('docx_table_autofit_invalid') }
const positive = (n: unknown): n is number => Number.isSafeInteger(n) && Number(n) > 0
// 来源: GenOffice f8c17004 editor/table-properties.ts fixedGridWidths逐字摘录。
// 原文件SHA256 bbff51fa2da6198df69fb290b8dd5624c00c87713c381b32713d9cf36fd0001f。
// 其余是setTableAutoFit三分支的宿主纯投影；局部适配: 初始grid/15保整数twip，非法网格原子拒绝。
function fixedGridWidths(table: PmNode, columnCount: number, contentWidthPx: number): number[] {
  const firstRow = table.firstChild
  const explicit: number[] = []
  firstRow?.forEach((cell) => {
    const widths = cell.attrs.colwidth as number[] | null
    if (widths?.length) explicit.push(...widths)
  })
  if (explicit.length === columnCount && explicit.every((width) => width > 0)) return explicit
  const pct = table.attrs.colWidthsPct as number[] | null
  if (pct?.length === columnCount) {
    const total = pct.reduce((sum, width) => sum + Math.max(0, width), 0) || 100
    return pct.map((width) =>
      Math.max(24, Math.round((Math.max(0, width) / total) * contentWidthPx)),
    )
  }
  return Array.from({ length: columnCount }, () =>
    Math.max(24, Math.floor(contentWidthPx / Math.max(1, columnCount))),
  )
}

/** 保持源模式顺序；初始只恢复整数网格精度，不改变来源preferred宽/mode。 */
export function applyTableAutoFitSteps(table: PmNode, widthsTwips: readonly number[], contentWidthTwips: number, steps: readonly TableAutoFitStep[]) {
  if (!positive(contentWidthTwips) || contentWidthTwips > 31680 || !Array.isArray(widthsTwips) || !Array.isArray(steps) || !steps.length || steps.length > 50 || table.type.spec.tableRole !== 'table' || !table.childCount || table.childCount > 100) fail()
  table.check()
  let count = 0
  table.forEach(row => { if (row.type.spec.tableRole !== 'row' || row.childCount > 30) fail(); row.forEach(cell => { if (!positive(cell.attrs.colspan) || cell.attrs.colspan > 30 || !positive(cell.attrs.rowspan) || cell.attrs.rowspan > 100 || cell.attrs.gridGap || ++count > 1000) fail() }) })
  const map = TableMap.get(table)
  if (map.problems?.length || map.width < 1 || map.width > 30 || map.width * map.height > 1000 || widthsTwips.length !== map.width || widthsTwips.some(w => !positive(w) || w > 31680) || !['contents','window','fixed'].includes(table.attrs.tblAutoFit)) fail()
  const withWidths = (node: PmNode, widths: readonly number[] | null, patch: Record<string, unknown> = {}) => {
    const rows: PmNode[] = []
    node.forEach((row, rowOffset) => {
      const cells: PmNode[] = []
      row.forEach((cell, cellOffset) => { const rect = map.findCell(rowOffset + 1 + cellOffset); cells.push(cell.type.create({ ...cell.attrs, colwidth: widths ? widths.slice(rect.left, rect.right) : null }, cell.content, cell.marks)) })
      rows.push(row.type.create(row.attrs, cells, row.marks))
    })
    return node.type.create({ ...node.attrs, ...patch }, rows, node.marks)
  }
  let current = withWidths(table, widthsTwips.map(w => w / 15))
  for (const step of steps) {
    if (!step || typeof step !== 'object' || Array.isArray(step) || Object.keys(step).length !== 1 || !Object.hasOwn(step,'mode') || !['contents','window','fixed'].includes(step.mode)) fail()
    const patch: Record<string, unknown> = { tblAutoFit: step.mode, tblAutoFitEdited: true }
    if (step.mode === 'contents') current = withWidths(current, null, { ...patch, widthPx: null, widthPct: null, colWidthsPct: null })
    else if (step.mode === 'window') current = current.type.create({ ...current.attrs, ...patch, widthPx: null, widthPct: 100 }, current.content, current.marks)
    else {
      const widths = fixedGridWidths(current, map.width, contentWidthTwips / 15), total = widths.reduce((a,b) => a+b,0)
      current = withWidths(current, widths, { ...patch, widthPx: total, widthPct: null, colWidthsPct: widths.map(w => w / total * 100) })
    }
  }
  // 源pmTableToModel首行宽优先；源generateTableModelXml缺失时按比例分配9360。
  const explicit: number[] = []
  current.firstChild!.forEach(cell => explicit.push(...(cell.attrs.colwidth ?? [])))
  const pct = current.attrs.colWidthsPct as number[] | null
  const percentages = pct?.length === map.width ? pct : Array.from({length:map.width},()=>100/map.width)
  const totalPct = percentages.reduce((a,b)=>a+b,0) || 100
  const output = explicit.length === map.width && explicit.every(w => w > 0) ? explicit.map(w => Math.round(w * 15)) : percentages.map(w => Math.max(1,Math.round(w / totalPct * 9360)))
  if (output.some(w => !positive(w) || w > 31680) || output.reduce((a,b)=>a+b,0) > 31680) fail()
  return { table: current, mode: current.attrs.tblAutoFit as TableAutoFitMode, widthsTwips: output }
}
