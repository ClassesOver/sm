import { formatAddress, parseRange, type SheetEditPlan, type StructuralOp } from '@sheets-web/xlsx-engine'
import type { ReadbackWorkbook } from './workbook-vendor/core/session-core'

export type GridSnapshot = { sheetOrder: string[]; sheets: Record<string, { name: string }> }

export function gridMergeChanges(model: { sheets: readonly { name: string; merges: readonly string[] }[] }, readback: ReadbackWorkbook) {
  const reference = (range: ReturnType<typeof parseRange>) =>
    `${formatAddress(range.startRow, range.startColumn)}:${formatAddress(range.endRow, range.endColumn)}`
  return readback.sheets.flatMap(sheet => {
    const before = (model.sheets.find(original => original.name === sheet.name)?.merges ?? []).map(ref => reference(parseRange(ref))).sort()
    const ranges = (sheet.merges ?? []).map(reference).sort()
    return JSON.stringify(before) === JSON.stringify(ranges) ? [] : [{ sheetName: sheet.name, ranges }]
  })
}

export function planGridSheets(names: readonly string[], snapshot: GridSnapshot): SheetEditPlan {
  const originalIds = new Map(names.map((name, index) => [`sheet-${index}`, name]))
  return {
    renames: [...originalIds].flatMap(([id, sheetName]) => {
      const name = snapshot.sheets[id]?.name
      return name && name !== sheetName ? [{ sheetName, newName: name }] : []
    }),
    additions: snapshot.sheetOrder.filter(id => !originalIds.has(id)).map(id => ({ name: snapshot.sheets[id]!.name })),
    removals: [...originalIds].filter(([id]) => !snapshot.sheets[id]).map(([, name]) => name),
    order: snapshot.sheetOrder.map(id => snapshot.sheets[id]!.name),
  }
}

export function structuralMutation(id: string, params: unknown): { sheetId: string; op: StructuralOp } | undefined {
  const kinds: Record<string, StructuralOp['kind']> = {
    'sheet.mutation.insert-row': 'insert-rows', 'sheet.mutation.remove-rows': 'remove-rows',
    'sheet.mutation.insert-col': 'insert-cols', 'sheet.mutation.remove-col': 'remove-cols',
  }
  const kind = kinds[id]
  if (!kind || !params || typeof params !== 'object') return undefined
  const value = params as { subUnitId: string; range: { startRow: number; endRow: number; startColumn: number; endColumn: number } }
  const rows = kind.endsWith('rows')
  const index = rows ? value.range.startRow : value.range.startColumn
  const end = rows ? value.range.endRow : value.range.endColumn
  return { sheetId: value.subUnitId, op: { kind, index, count: end - index + 1 } }
}
