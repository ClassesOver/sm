import { diffToEdits } from './workbook-vendor/core/session-core'
import { readBackSnapshot } from './workbook-vendor/grid/sync'
import type { WorkbookModel } from '@sheets-web/xlsx-engine'
import type { WorkbookOperation } from './workbook-draft'
import { WORKBOOK_MAX_CELL_EDITS } from './workbook-edit-budget'

const REPLACE_COMMANDS = new Set([
  'ui.operation.open-replace-dialog', 'ui.command.replace-current-match',
  'ui.command.replace-all-matches', 'sheet.command.replace',
])

type Snapshot = {
  id?: string
  sheetOrder: string[]
  sheets: Record<string, { name: string; cellData?: Record<string, Record<string, Record<string, unknown> | null>> }>
}
type Replacement = { subUnitId: string; value: Record<string, Record<string, Record<string, unknown> | null>> }

/** Project only the payload produced by Univer; never search or replace text ourselves.
 * Rich-text replacements are rejected until the grid readback can preserve runs.
 * Conservative budget preflight happens before the first multi-sheet mutation.
 */
export function validateWorkbookReplacement(
  command: { id: string; params?: unknown }, snapshot: unknown, model: WorkbookModel,
  staged: WorkbookOperation[], structuralCount: number,
): void {
  const params = command.params as { unitId?: string; subUnitId?: string; value?: Replacement['value']; replacements?: Replacement[] } | undefined
  const data = structuredClone(snapshot) as Snapshot
  if (!params || params.unitId !== data.id) throw new Error('替换目标与当前工作簿不一致')
  const replacements = command.id === 'sheet.command.replace'
    ? params.replacements
    : [{ subUnitId: params.subUnitId!, value: params.value! }]
  if (!Array.isArray(replacements)) throw new Error('替换操作无效')
  for (const replacement of replacements) {
    const sheet = data.sheets[replacement.subUnitId]
    if (!sheet || !replacement.value || typeof replacement.value !== 'object' || Array.isArray(replacement.value)) throw new Error('替换目标工作表无效')
    for (const [row, values] of Object.entries(replacement.value)) {
      if (!/^(0|[1-9]\d*)$/.test(row) || Number(row) > 1048575 || !values || typeof values !== 'object' || Array.isArray(values)) throw new Error('替换行无效')
      for (const [column, cell] of Object.entries(values)) {
        if (!/^(0|[1-9]\d*)$/.test(column) || Number(column) > 16383 || !cell || typeof cell !== 'object' || Array.isArray(cell)) throw new Error('替换单元格无效')
        const previous = sheet.cellData?.[row]?.[column]
        if (cell.p || previous?.p) throw new Error('富文本单元格暂不支持安全替换，请使用普通文本单元格')
        if (Object.keys(cell).some(key => !['v', 'f'].includes(key)) ||
          ('f' in cell && typeof cell.f !== 'string') ||
          ('v' in cell && cell.v !== null && !['string', 'number', 'boolean'].includes(typeof cell.v)) ||
          (typeof cell.v === 'number' && !Number.isFinite(cell.v))) throw new Error('替换单元格数据不受支持')
        // SetRangeValuesCommand merges the supplied fields into the original cell.
        const rows = sheet.cellData ??= {}
        const cells = rows[row] ??= {}
        cells[column] = { ...previous, ...cell }
      }
    }
  }
  const edits = diffToEdits(model, readBackSnapshot(data))
  if (edits.length > WORKBOOK_MAX_CELL_EDITS) throw new Error('替换超出单元格操作预算，请缩小查找范围')
  // Include prior operations and reserve a conservative allowance for geometry and
  // sheet/row/column edits not present in this value-only projection.
  const operations = [...staged, { kind: 'applyCellEdits', edits }]
  if (operations.length + structuralCount + data.sheetOrder.length * 2 + 1 > 500 ||
    new TextEncoder().encode(JSON.stringify(operations)).length > 10 * 1024 * 1024) {
    throw new Error('替换超出本地草稿预算，请缩小查找范围或先保存当前修改')
  }
}

/** Guard the official commands even when opened via Ctrl+H or Find's replace tab. */
export function workbookReplacementCommand(id: string): boolean { return REPLACE_COMMANDS.has(id) }
