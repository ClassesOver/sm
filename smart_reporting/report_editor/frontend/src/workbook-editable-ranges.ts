/** 允许编辑区域的文件定义与值编辑权限；不引入网格私有权限快照。 */
import { parseRange, type RangeBounds, readWorkbook } from '@sheets-web/xlsx-engine'
import { setSheetEditableRanges, type ProtectedRangeState } from '@sheets-web/xlsx-engine/protection'
import { normalizeEditableRangeRef, readProtectedRanges, type EditableRange } from '@sheets-web/xlsx-engine/protection-read'
import { createBufferEntrySource } from '@sheets-web/xlsx-engine/zip'

export type { EditableRange }
export interface ProtectedValueContext { range: RangeBounds; ranges: readonly EditableRange[]; writtenRanges?: readonly RangeBounds[]; safeValue?: unknown }

export async function readWorkbookEditableRanges(bytes: Uint8Array): Promise<Map<string, EditableRange[]>> {
  const [model, source] = await Promise.all([readWorkbook(bytes), createBufferEntrySource(bytes)])
  return new Map(await Promise.all(model.sheets.map(async sheet => [sheet.name, readProtectedRanges(await source.readText(sheet.path))] as const)))
}

export async function createEditableRangesPlan(bytes: Uint8Array, sheetName: string, ranges: readonly ProtectedRangeState[]) {
  await setSheetEditableRanges(bytes, sheetName, ranges)
  const operation = { kind: 'setSheetEditableRanges', sheetName, ranges: ranges.map(range => ({ name: range.name.trim(), sqref: normalizeEditableRangeRef(range.sqref) })) }
  return { operation, operations: [operation] }
}

const validRange = (range: RangeBounds): boolean => Number.isSafeInteger(range.startRow) && Number.isSafeInteger(range.endRow) && Number.isSafeInteger(range.startColumn) && Number.isSafeInteger(range.endColumn) && range.startRow >= 0 && range.startColumn >= 0 && range.endRow >= range.startRow && range.endColumn >= range.startColumn && range.endRow < 1048576 && range.endColumn < 16384

/** 按行边界扫描矩形并集，无须展开大范围为百万个单元格。 */
export function editableRangeContains(target: RangeBounds, ranges: readonly EditableRange[]): boolean {
  if (!validRange(target)) return false
  let areas: RangeBounds[]
  try { areas = ranges.filter(range => !range.readonlyReason).flatMap(range => normalizeEditableRangeRef(range.sqref).split(' ').map(parseRange)).filter(area => area.startRow <= target.endRow && area.endRow >= target.startRow && area.startColumn <= target.endColumn && area.endColumn >= target.startColumn) } catch { return false }
  const cuts = new Set([target.startRow, target.endRow + 1])
  for (const area of areas) { cuts.add(Math.max(target.startRow, area.startRow)); cuts.add(Math.min(target.endRow + 1, area.endRow + 1)) }
  const rows = [...cuts].sort((a, b) => a - b)
  for (const row of rows.slice(0, -1)) {
    let covered = target.startColumn
    for (const area of areas.filter(area => area.startRow <= row && area.endRow >= row).sort((a, b) => a.startColumn - b.startColumn)) {
      if (area.startColumn > covered) break
      covered = Math.max(covered, area.endColumn + 1)
      if (covered > target.endColumn) break
    }
    if (covered <= target.endColumn) return false
  }
  return rows.length > 1
}

const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value)
const plainValue = (value: unknown): boolean => record(value) && Object.keys(value).length > 0 && Object.keys(value).every(key => ['v', 'f', 't', 'p', 'si', 's'].includes(key)) &&
  (value.v !== undefined || value.f !== undefined) &&
  (value.v === undefined || value.v === null || typeof value.v === 'string' || typeof value.v === 'boolean' || typeof value.v === 'number' && Number.isFinite(value.v)) &&
  (value.f === undefined || value.f === null || typeof value.f === 'string') && (value.t === undefined || value.t === null || Number.isInteger(value.t)) &&
  // 原生键盘提交携带这两个空清理标记；非空富文本或共享公式身份仍不支持。
  (value.p === undefined || value.p === null) && (value.si === undefined || value.si === null)

const withoutStyle = (cell: unknown) => Object.fromEntries(Object.entries(cell as Record<string, unknown>).filter(([key]) => key !== 's'))

/** 对照 Univer set-range-values 的三种原生载荷，校验实际写入而非只相信 range。 */
export function protectedValueCommandContext(params: unknown, fallbackRange: RangeBounds | undefined, ranges: readonly EditableRange[]): ProtectedValueContext | undefined {
  if (!record(params)) return undefined
  const value = params.value
  const requested = (record(params.range) ? params.range : fallbackRange) as RangeBounds | undefined
  if (Array.isArray(value) || plainValue(value)) {
    if (!requested || !validRange(requested) || !editableRangeContains(requested, ranges)) return undefined
    if (Array.isArray(value)) {
      if (value.length !== requested.endRow - requested.startRow + 1 || !value.every(row => Array.isArray(row) && row.length === requested.endColumn - requested.startColumn + 1 && row.every(plainValue))) return undefined
    }
    return { range: requested, ranges, safeValue: Array.isArray(value) ? value.map(row => row.map(withoutStyle)) : withoutStyle(value) }
  }
  if (!record(value) || !Object.keys(value).length) return undefined
  const cells: { row: number; column: number }[] = []
  const safeValue: Record<string, Record<string, Record<string, unknown>>> = {}
  for (const [rowKey, columns] of Object.entries(value)) {
    if (!/^(0|[1-9][0-9]*)$/.test(rowKey) || !record(columns) || !Object.keys(columns).length) return undefined
    safeValue[rowKey] = {}
    for (const [columnKey, cell] of Object.entries(columns)) {
      if (!/^(0|[1-9][0-9]*)$/.test(columnKey) || !plainValue(cell)) return undefined
      const row = Number(rowKey), column = Number(columnKey)
      if (!editableRangeContains({ startRow: row, endRow: row, startColumn: column, endColumn: column }, ranges)) return undefined
      cells.push({ row, column })
      safeValue[rowKey]![columnKey] = withoutStyle(cell)
    }
  }
  // 外接矩形可包含未写入的受保护洞；保留逐格写入集合供权限与表头保护检查。
  const first = cells[0]!
  return { range: { startRow: first.row, endRow: first.row, startColumn: first.column, endColumn: first.column }, ranges,
    writtenRanges: cells.map(cell => ({ startRow: cell.row, endRow: cell.row, startColumn: cell.column, endColumn: cell.column })), safeValue }
}
