import { expect, it } from 'vitest'
import { advancedFilterPreflightOperations } from './workbook-advanced-filter-preflight'
import type { WorkbookOperation } from './workbook-draft'

const filter = { range: { startRow: 4, endRow: 9, startColumn: 2, endColumn: 4 }, columns: [{ colId: 1, customs: { filters: [{ val: '10', operator: 'greaterThan' }] } }] }
const prior = (sheetName: string): WorkbookOperation => ({ kind: 'applySheetFilter', sheetName, filter: null, hiddenRows: [] })

it('replaces only the live target filter while retaining staged filter states and other sheets', () => {
  const staged = prior('Data'), other = prior('Other'), live = prior('Data')
  const edit: WorkbookOperation = { kind: 'applyCellEdits', edits: [] }
  const operations = advancedFilterPreflightOperations([staged, edit, other, live], 1, 'Data', filter)
  expect(operations).toEqual([staged, edit, other, { kind: 'applySheetFilter', sheetName: 'Data', filter }])
  expect(operations[0]).toBe(staged)
  expect(live).toEqual(prior('Data'))
})

it('checks the 500 operation request budget after replacing the live filter', () => {
  const edits = Array.from({ length: 499 }, (): WorkbookOperation => ({ kind: 'applyCellEdits', edits: [] }))
  expect(advancedFilterPreflightOperations([...edits, prior('Data')], 0, 'Data', filter)).toHaveLength(500)
  expect(() => advancedFilterPreflightOperations([...edits, prior('Other')], 0, 'Data', filter)).toThrow('500')
})
