/// Data tools shared by the value path (text-to-columns → CellEdits inside
/// planOps) and the package path (delete-duplicates → remove-rows runs).
/// Both are batch display-data tools, so they carry a tighter cell budget
/// than the generic write path.

import { formatAddress, parseRange, rangeCellCount, typedCsvValue } from '@sheets-web/xlsx-engine'
import type { WorkbookModel } from '@sheets-web/xlsx-engine'
import type { ReadbackWorkbook } from './session-core'

/// columnWidthToPixels inverse (univer-data's display approximation):
/// px = round(chars * 7 + 5) → chars = (px - 5) / 7
const PIXELS_PER_CHAR = 7
const CHAR_OFFSET = 5
/// rowHeightToPixels inverse: px = round(pts * 96 / 72) → pts = px * 72 / 96
const PIXELS_PER_POINT = 96 / 72
/// ignore sub-pixel drag noise and rounding wobble
const GEOMETRY_THRESHOLD_PX = 2

export interface GeometryChanges {
  readonly columns: ReadonlyArray<{ sheet: string; index: number; widthChars: number }>
  readonly rows: ReadonlyArray<{ sheet: string; index: number; heightPoints: number }>
}

/// Grid-dragged geometry (readback, pixels) vs the imported model (chars /
/// points): emit write-back entries where the pixel rendering moved beyond
/// the threshold. Pure — the save path applies them through the engine.
export function geometryChanges(
  model: WorkbookModel,
  readback: ReadbackWorkbook,
): GeometryChanges {
  const columns: Array<{ sheet: string; index: number; widthChars: number }> = []
  const rows: Array<{ sheet: string; index: number; heightPoints: number }> = []
  const modelSheetByName = new Map(model.sheets.map((sheet) => [sheet.name, sheet]))
  for (const sheet of readback.sheets) {
    const modelSheet = modelSheetByName.get(sheet.name)
    if (!modelSheet) continue

    const expectedWidthPx = new Map<number, number>()
    for (const column of modelSheet.columns) {
      for (let index = column.start - 1; index < column.end; index += 1) {
        if (column.width !== undefined) {
          expectedWidthPx.set(index, Math.max(8, Math.round(column.width * PIXELS_PER_CHAR + CHAR_OFFSET)))
        }
      }
    }
    for (const [indexKey, pixels] of Object.entries(sheet.columnWidths ?? {})) {
      if (pixels === undefined) continue
      const index = Number(indexKey)
      const expected = expectedWidthPx.get(index)
      if (expected !== undefined && Math.abs(expected - pixels) < GEOMETRY_THRESHOLD_PX) continue
      const widthChars = Math.max(1, (pixels - CHAR_OFFSET) / PIXELS_PER_CHAR)
      columns.push({ sheet: sheet.name, index, widthChars })
    }

    const expectedHeightPx = new Map<number, number>()
    for (const row of modelSheet.rows) {
      if (row.height !== undefined) {
        expectedHeightPx.set(row.row - 1, Math.max(2, Math.round(row.height * PIXELS_PER_POINT)))
      }
    }
    for (const [indexKey, pixels] of Object.entries(sheet.rowHeights ?? {})) {
      if (pixels === undefined) continue
      const index = Number(indexKey)
      const expected = expectedHeightPx.get(index)
      if (expected !== undefined && Math.abs(expected - pixels) < GEOMETRY_THRESHOLD_PX) continue
      rows.push({ sheet: sheet.name, index, heightPoints: pixels / PIXELS_PER_POINT })
    }
  }
  return { columns, rows }
}

export interface TextToColumnsOp {
  readonly sheet: string
  /// single-column range; tokens land to the right of it
  readonly range: string
  /// literal delimiter (multi-character allowed, e.g. ', ' or tab)
  readonly delimiter: string
  /// drop empty tokens between consecutive delimiters
  readonly treatConsecutiveAsOne?: boolean | undefined
}

export interface DeleteDuplicatesOp {
  readonly sheet: string
  readonly range: string
  /// 0-based column indexes RELATIVE to the range start; default all columns
  readonly columns?: readonly number[] | undefined
  /// first row is a header: excluded from comparison and never removed
  readonly hasHeader?: boolean | undefined
}

const MAX_BATCH_CELLS = 2000
const MAX_BATCH_ROWS = 5000

export interface CellChange {
  readonly row: number
  readonly column: number
  readonly value: string | number | boolean | null
}

/// Split one column of values by a delimiter into a rectangular token block.
/// Tokens are typed like CSV import ("123" → 123, "TRUE" → true); rows whose
/// split is shorter than the widest are null-padded so leftovers clear.
export function textToColumnChanges(
  op: TextToColumnsOp,
  valueAt: (row: number, column: number) => unknown,
): CellChange[] {
  const bounds = parseRange(op.range)
  if (rangeCellCount(bounds) > MAX_BATCH_CELLS) {
    throw new Error(`区域 ${op.range} 超出分列的 ${MAX_BATCH_CELLS} 行上限。`)
  }
  if (bounds.startColumn !== bounds.endColumn) {
    throw new Error(`分列仅支持单列区域（收到 ${op.range}）。`)
  }
  const column = bounds.startColumn
  const rows: Array<{ row: number; tokens: Array<string | number | boolean | null> }> = []
  let widest = 0
  for (let row = bounds.startRow; row <= bounds.endRow; row += 1) {
    const raw = valueAt(row, column)
    if (raw === null || raw === undefined) continue
    const parts = String(raw).split(op.delimiter)
    const tokens = (
      op.treatConsecutiveAsOne ? parts.filter((part) => part !== '') : parts
    ).map((part) => typedCsvValue(part))
    widest = Math.max(widest, tokens.length)
    rows.push({ row, tokens })
  }
  const changes: CellChange[] = []
  for (const { row, tokens } of rows) {
    for (let offset = 0; offset < widest; offset += 1) {
      changes.push({ row, column: column + offset, value: tokens[offset] ?? null })
    }
  }
  return changes
}

/// Minimal workbook view both WorkbookModel and ReadbackWorkbook satisfy.
export interface WorkbookLike {
  readonly sheets: ReadonlyArray<{
    readonly name: string
    readonly cells: Readonly<Record<string, { readonly value: unknown } | undefined>>
  }>
}

const canonical = (value: unknown): string => {
  if (value === null || value === undefined) return '∅'
  if (typeof value === 'number') return Number.isFinite(value) ? `n:${value}` : '∅'
  return `${typeof value}:${value}`
}

/// Contiguous 0-based row runs to remove (original coordinates; the caller
/// applies them bottom-up). Excel semantics: keep the first occurrence,
/// remove later rows equal on the compared columns. Runs against the STAGED
/// model when called from the package path, so same-payload writes count.
export function duplicateRowRuns(
  workbook: WorkbookLike,
  op: DeleteDuplicatesOp,
): Array<{ index: number; count: number }> {
  const sheet = workbook.sheets.find((candidate) => candidate.name === op.sheet)
  if (!sheet) throw new Error(`工作表 "${op.sheet}" 不存在。`)
  const bounds = parseRange(op.range)
  if (bounds.endRow - bounds.startRow + 1 > MAX_BATCH_ROWS) {
    throw new Error(`区域 ${op.range} 超出去重的 ${MAX_BATCH_ROWS} 行上限。`)
  }
  const width = bounds.endColumn - bounds.startColumn + 1
  const relative = op.columns ?? Array.from({ length: width }, (_, offset) => offset)
  if (relative.length === 0) throw new Error('去重至少需要一列参与比较。')
  for (const offset of relative) {
    if (offset >= width) {
      throw new Error(`比较列 ${offset} 超出区域 ${op.range} 的宽度。`)
    }
  }
  const seen = new Set<string>()
  const remove: number[] = []
  for (let row = bounds.startRow + (op.hasHeader ? 1 : 0); row <= bounds.endRow; row += 1) {
    const key = JSON.stringify(
      relative.map((offset) => canonical(sheet.cells[formatAddress(row, bounds.startColumn + offset)]?.value)),
    )
    if (seen.has(key)) remove.push(row)
    else seen.add(key)
  }
  if (remove.length === 0) return []
  const runs: Array<{ index: number; count: number }> = []
  let start = remove[0]!
  let previous = remove[0]!
  for (const row of remove.slice(1)) {
    if (row === previous + 1) {
      previous = row
      continue
    }
    runs.push({ index: start, count: previous - start + 1 })
    start = row
    previous = row
  }
  runs.push({ index: start, count: previous - start + 1 })
  return runs
}
