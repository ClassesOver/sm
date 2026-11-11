import type { Node as PmNode } from '@tiptap/pm/model'
import { EditorState, type Command, type Transaction } from '@tiptap/pm/state'
import { CellSelection, TableMap, mergeCells } from '@tiptap/pm/tables'
import { splitCellsInto } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/table-cell-shape-source'
export { Schema } from '@tiptap/pm/model'
export { TableMap } from '@tiptap/pm/tables'

export type TableCellShapeRect = { top: number; left: number; bottom: number; right: number }
export type TableCellShapeStep = { kind: 'mergeTableCells'; rect: TableCellShapeRect } |
  { kind: 'splitTableCells'; rect: TableCellShapeRect; rows: number; columns: number; mergeFirst: boolean }
const fail = (): never => { throw new Error('表格合并拆分的字段、矩形、宽度或大小超出支持范围') }
const integer = (n: unknown): n is number => Number.isSafeInteger(n)
const keys = (value: unknown, expected: string[]): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === expected.length && Object.keys(value).every(key => expected.includes(key))
const partition = (total: number, count: number) => Array.from({ length: count }, (_, i) => Math.floor(total / count) + (i < total % count ? 1 : 0))
function checkedMap(table: PmNode, widths: readonly number[]): TableMap {
  if (table.type.spec.tableRole !== 'table') fail()
  if (table.childCount < 1 || table.childCount > 100) fail()
  let cells = 0
  table.forEach(row => {
    if (row.type.spec.tableRole !== 'row' || row.childCount > 30) fail()
    row.forEach(cell => {
      if (!['cell', 'header_cell'].includes(cell.type.spec.tableRole ?? '') || !integer(cell.attrs.colspan) || !integer(cell.attrs.rowspan) || cell.attrs.colspan < 1 || cell.attrs.colspan > 30 || cell.attrs.rowspan < 1 || cell.attrs.rowspan > 100 || ++cells > 1000) fail()
    })
  })
  table.check()
  const map = TableMap.get(table)
  if (map.problems?.length || map.width < 1 || map.width > 30 || map.height < 1 || map.height > 100 || map.width * map.height > 1000 || widths.length !== map.width || widths.some(w => !integer(w) || w <= 0) || !Number.isSafeInteger(widths.reduce((a, b) => a + b, 0))) fail()
  for (const pos of new Set(map.map)) {
    const cell = table.nodeAt(pos)!
    if (!integer(cell.attrs.colspan) || !integer(cell.attrs.rowspan) || cell.attrs.colspan < 1 || cell.attrs.rowspan < 1 || cell.attrs.gridGap) fail()
  }
  return map
}
function checkedRect(value: unknown, map: TableMap): TableCellShapeRect {
  if (!keys(value, ['top', 'left', 'bottom', 'right']) || !Object.values(value).every(integer)) fail()
  const rect = value as TableCellShapeRect
  if (rect.top < 0 || rect.left < 0 || rect.bottom <= rect.top || rect.right <= rect.left || rect.bottom > map.height || rect.right > map.width) fail()
  for (let r = rect.top; r < rect.bottom; r++) for (let c = rect.left; c < rect.right; c++) {
    const cell = map.findCell(map.map[r * map.width + c])
    if (cell.top < rect.top || cell.left < rect.left || cell.bottom > rect.bottom || cell.right > rect.right) fail()
  }
  return rect
}
function projectWidths(table: PmNode, widths: number[]): PmNode {
  const map = TableMap.get(table)
  let rowOffset = 0
  return table.type.create({ ...table.attrs, colWidthsPct: widths.map(w => w * 100 / widths.reduce((a, b) => a + b, 0)) }, Array.from({ length: table.childCount }, (_, i) => {
    const row = table.child(i)
    const start = rowOffset
    rowOffset += row.nodeSize
    let cellOffset = 0
    const cells: PmNode[] = []
    row.forEach(cell => {
      const rect = map.findCell(start + 1 + cellOffset)
      cells.push(cell.type.create({ ...cell.attrs, colwidth: widths.slice(rect.left, rect.right).map(w => w / 15) }, cell.content, cell.marks))
      cellOffset += cell.nodeSize
    })
    return row.type.create(row.attrs, cells, row.marks)
  }), table.marks)
}
function run(table: PmNode, rect: TableCellShapeRect, command: Command): PmNode {
  const doc = table.type.schema.topNodeType.create(null, table)
  const map = TableMap.get(table)
  const selection = CellSelection.create(doc, 1 + map.map[rect.top * map.width + rect.left], 1 + map.map[(rect.bottom - 1) * map.width + rect.right - 1])
  const state = EditorState.create({ doc, selection })
  const captured: { tr?: Transaction } = {}
  if (!command(state, tr => { captured.tr = tr }) || !captured.tr) fail()
  return captured.tr!.doc.firstChild!
}
/** 两端共享来源 PM 语义；每个单格拆分后以整数 twip 网格重新投影，避免累计舍入漂移。 */
export function applyTableCellShapeSteps(table: PmNode, widthsTwips: number[], steps: readonly TableCellShapeStep[]): { table: PmNode; widthsTwips: number[] } {
  if (!Array.isArray(steps) || steps.length < 1 || steps.length > 50 || !Array.isArray(widthsTwips)) fail()
  let widths = [...widthsTwips]
  checkedMap(table, widths)
  let current = projectWidths(table, widths)
  for (const step of steps) {
    if (!keys(step, step?.kind === 'mergeTableCells' ? ['kind', 'rect'] : ['kind', 'rect', 'rows', 'columns', 'mergeFirst'])) fail()
    const map = checkedMap(current, widths)
    const rect = checkedRect(step.rect, map)
    const positions = new Set<number>()
    for (let r = rect.top; r < rect.bottom; r++) for (let c = rect.left; c < rect.right; c++) positions.add(map.map[r * map.width + c])
    if (step.kind === 'mergeTableCells') {
      if (positions.size < 2) fail()
      current = projectWidths(run(current, rect, mergeCells), widths)
    } else if (step.kind === 'splitTableCells') {
      if (!integer(step.rows) || !integer(step.columns) || step.rows < 1 || step.rows > 50 || step.columns < 1 || step.columns > 30 || (step.rows === 1 && step.columns === 1) || typeof step.mergeFirst !== 'boolean') fail()
      // 与固定源 splitCellsInto 相同：先合并，或对原选择去重后按右下到左上处理。
      if (step.mergeFirst && positions.size > 1) current = projectWidths(run(current, rect, mergeCells), widths)
      const targets = step.mergeFirst ? [{ top: rect.top, left: rect.left }] : [...positions].map(pos => map.findCell(pos)).sort((a, b) => b.top - a.top || b.left - a.left)
      for (const target of targets) {
        const before = checkedMap(current, widths)
        const cell = before.findCell(before.map[target.top * before.width + target.left])
        const span = cell.right - cell.left
        const counts = step.columns > span ? partition(step.columns, span) : Array(span).fill(1) as number[]
        const nextWidths = widths.flatMap((w, col) => col >= cell.left && col < cell.right ? partition(w, counts[col - cell.left]) : [w])
        const height = before.height + Math.max(0, step.rows - (cell.bottom - cell.top))
        if (nextWidths.length > 30 || height > 100 || nextWidths.length * height > 1000 || nextWidths.some(w => w <= 0)) fail()
        current = projectWidths(run(current, cell, splitCellsInto(step.rows, step.columns, false)), nextWidths)
        widths = nextWidths
        checkedMap(current, widths)
      }
    } else fail()
    checkedMap(current, widths)
  }
  return { table: current, widthsTwips: widths }
}
