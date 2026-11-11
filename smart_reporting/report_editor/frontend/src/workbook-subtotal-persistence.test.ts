import { expect, it } from 'vitest'
import { createBlankWorkbook, readWorkbook, type CellEdit } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { NativeDraft, type NativeDraftIdentity, type NativeOperation } from './native-draft'
import { planSubtotal } from './workbook-subtotal'
import { subtotalPreflightOperations } from './workbook-subtotal-preflight'

const values = [['Group', 'Value', 'Other'], ['A', 10, 'a'], ['A', 20, 'b'], ['B', 30, 'c'], ['B', 40, 'd']]
const identity: NativeDraftIdentity = { documentId: 'subtotal', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'db', companyId: 'co', userId: 'u', threadId: 't' } }
function storage() {
  const data = new Map<string, string>()
  return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value) }, removeItem: (key: string) => { data.delete(key) } }
}

it.each(['sum', 'count', 'average'] as const)('persists production %s plans at C5 through draft restore and an unchanged save retry without duplicate inserts', async agg => {
  const offset = 4, column = 2
  const edits: CellEdit[] = [...values, ['Tail', 99, 'keep']].flatMap((row, r) => row.map((value, c) => ({ sheetName: 'Data', row: r + offset, column: c + column, writeValue: true, cell: { value } })))
  const original = await applyWorkbookOperations(await createBlankWorkbook('Data'), [
    { kind: 'applySheetEdits', plan: { renames: [], additions: [{ name: 'Dependent' }], removals: [], order: ['Data', 'Dependent'] } },
    { kind: 'applyCellEdits', edits: [...edits,
      { sheetName: 'Dependent', row: 0, column: 0, writeValue: true, cell: { value: null, formula: '=Data!$D$8' } },
      { sheetName: 'Dependent', row: 1, column: 0, writeValue: true, cell: { value: null, formula: '=SUM(Data!D6:D9)' } },
    ] },
    { kind: 'applyDefinedNames', plan: { sets: [{ name: 'Body', refersTo: "'Data'!$C$6:$D$9" }] } },
    { kind: 'applySheetOutline', sheetName: 'Data', summaryBelow: false },
  ])
  const plan = planSubtotal({ startRow: offset, endRow: offset + 4, startColumn: column, endColumn: column + 2 }, values, { groupCol: column, valueCol: column + 1, agg })
  const ops = subtotalPreflightOperations([], 'Data', plan) as NativeOperation[], store = storage()
  const draft = new NativeDraft(identity, store, () => 'subtotal-request')
  draft.setOperations(ops)
  const request = draft.beginSave()
  draft.saveFailed()
  const restored = new NativeDraft(identity, store, () => 'unexpected-new-request')
  expect(restored.operations).toEqual(ops)
  expect(restored.beginSave()).toEqual(request)
  const first = await readWorkbook(await applyWorkbookOperations(original, request.operations as NativeOperation[]))
  const replayed = await readWorkbook(await applyWorkbookOperations(original, restored.operations as NativeOperation[]))
  expect(replayed).toEqual(first)
  const sheet = replayed.sheets[0]!, dependent = replayed.sheets[1]!
  const code = { sum: 9, count: 3, average: 1 }[agg]
  expect(sheet.cells.D8.formula).toBe(`=SUBTOTAL(${code},$D$6:$D$7)`)
  expect(sheet.cells.D11.formula).toBe(`=SUBTOTAL(${code},$D$9:$D$10)`)
  expect(sheet.cells.D12.formula).toBe(`=SUBTOTAL(${code},$D$6:$D$11)`)
  expect(sheet.cells.C13.value).toBe('Tail')
  expect(sheet.cells.D13.value).toBe(99)
  expect(sheet.cells.E13.value).toBe('keep')
  expect(sheet.outlineSummaryBelow).toBe(true)
  expect(sheet.rows.filter(row => row.outlineLevel).map(row => [row.row, row.outlineLevel])).toEqual([[6, 2], [7, 2], [8, 1], [9, 2], [10, 2], [11, 1]])
  expect(dependent.cells.A1.formula).toBe('=Data!$D$9')
  expect(dependent.cells.A2.formula).toBe('=SUM(Data!D6:D10)')
  expect(replayed.definedNames).toContainEqual({ name: 'Body', refersTo: "'Data'!$C$6:$D$10" })
  restored.saveCompleted({ revision: 2, revisionRegistered: true })
  expect(new NativeDraft({ ...identity, revision: 2, sourceSha256: 'b'.repeat(64) }, store).operations).toEqual([])
})
