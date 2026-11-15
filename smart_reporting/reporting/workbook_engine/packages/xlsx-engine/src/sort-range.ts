/// Range sorting, ported from genoffice sort-range.ts: computes the cell
/// rewrites a sort produces, so sorting rides the existing per-cell preview /
/// apply / undo machinery. Regions containing formulas are rejected: moving
/// formula text between rows silently re-targets relative references, which
/// is exactly the class of damage the preview model exists to prevent.

import { columnIndex, formatAddress, parseRange, type RangeBounds } from './cell-address'

export type SortScalar = string | number | boolean | null

export interface SortCellState {
  readonly value: string | number | boolean | null
  readonly formula?: string | undefined
  /// Raw model value (e.g. a date serial); falls back to `value`.
  readonly rawValue?: string | number | boolean | null | undefined
}

export interface SortComputedChange {
  readonly address: string
  readonly before: SortScalar
  readonly after: SortScalar
}

interface SortColumn {
  readonly byColumn: string
  readonly ascending: boolean
}

export interface SortSpec extends SortColumn {
  readonly range: string
  readonly hasHeader: boolean
  readonly thenBy?: readonly SortColumn[]
}

export function sortKeyOffsets(spec: SortSpec, bounds: RangeBounds) {
  const secondary = spec.thenBy ?? []
  if (!Array.isArray(secondary) || secondary.length > 2) throw new Error('排序最多支持三个关键字。')
  const seen = new Set<number>()
  return [spec, ...secondary].map(key => {
    if (!key || typeof key.byColumn !== 'string' || typeof key.ascending !== 'boolean') throw new Error('排序关键字无效。')
    const column = columnIndex(key.byColumn)
    if (column < bounds.startColumn || column > bounds.endColumn) throw new Error(`Sort column ${key.byColumn} is outside the range ${spec.range}.`)
    if (seen.has(column)) throw new Error('排序关键字不能重复。')
    seen.add(column)
    return { offset: column - bounds.startColumn, ascending: key.ascending }
  })
}

/// blanks always sort last; numbers before booleans before text (Excel order)
function compareScalars(a: SortScalar, b: SortScalar): number {
  if (a === null && b === null) return 0
  if (a === null) return 1
  if (b === null) return -1
  const rank = (value: Exclude<SortScalar, null>): number =>
    typeof value === 'number' ? 0 : typeof value === 'string' ? 1 : 2
  const rankA = rank(a)
  const rankB = rank(b)
  if (rankA !== rankB) return rankA - rankB
  if (typeof a === 'number' && typeof b === 'number') {
    const aFinite = Number.isFinite(a)
    const bFinite = Number.isFinite(b)
    if (aFinite && bFinite) return a < b ? -1 : a > b ? 1 : 0
    if (aFinite) return -1
    if (bFinite) return 1
    return 0
  }
  if (typeof a === 'boolean' && typeof b === 'boolean') return Number(a) - Number(b)
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' })
}

/// Stable data-row order for a sort: returns source-row indexes in their
/// sorted sequence (order[target] = source). Blanks stay last in both
/// directions (Excel behavior). Shared by the per-cell expansion path and the
/// range-level bulk executor so both sort identically.
export function computeSortedRowOrder(
  rows: readonly (readonly SortScalar[])[],
  keyOffset: number,
  ascending: boolean,
  thenBy: readonly { offset: number; ascending: boolean }[] = [],
): number[] {
  const keys = [{ offset: keyOffset, ascending }, ...thenBy]
  return rows
    .map((cells, index) => ({ cells, index }))
    .sort((a, b) => {
      for (const key of keys) {
        const left = a.cells[key.offset] ?? null, right = b.cells[key.offset] ?? null
        const compared = compareScalars(left, right)
        if (compared) return left === null || right === null || key.ascending ? compared : -compared
      }
      return a.index - b.index
    })
    .map((entry) => entry.index)
}

export function computeSortChanges(
  spec: SortSpec,
  readCell: (address: string) => SortCellState,
): SortComputedChange[] {
  const bounds = parseRange(spec.range)
  const [first, ...thenBy] = sortKeyOffsets(spec, bounds)
  const firstDataRow = bounds.startRow + (spec.hasHeader ? 1 : 0)
  if (firstDataRow >= bounds.endRow) {
    throw new Error('The sort range needs at least two data rows.')
  }

  const rows: SortScalar[][] = []
  for (let row = firstDataRow; row <= bounds.endRow; row += 1) {
    const cells: SortScalar[] = []
    for (let column = bounds.startColumn; column <= bounds.endColumn; column += 1) {
      const address = formatAddress(row, column)
      const state = readCell(address)
      if (state.formula) {
        throw new Error(
          `The sort range contains a formula at ${address} — sorting would silently re-target its references. Sort values only, or convert formulas to values first.`,
        )
      }
      // Raw model values: `value` is display text, so formatted numbers and
      // dates would sort lexicographically AND be rewritten as text by the
      // moves. Raw serials sort numerically — Excel's order.
      cells.push(state.rawValue !== undefined ? state.rawValue : state.value)
    }
    rows.push(cells)
  }

  const order = computeSortedRowOrder(rows, first!.offset, first!.ascending, thenBy)

  const changes: SortComputedChange[] = []
  order.forEach((sourceIndex, offset) => {
    const targetRow = firstDataRow + offset
    rows[sourceIndex]?.forEach((value, columnOffset) => {
      const address = formatAddress(targetRow, bounds.startColumn + columnOffset)
      const before = rows[offset]?.[columnOffset] ?? null
      if (before !== value) changes.push({ address, before, after: value })
    })
  })
  return changes
}
