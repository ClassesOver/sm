import { expect, it } from 'vitest'
import { applyTableAdditions, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from './operations'

async function fixture() {
  return applyTableAdditions(await createBlankWorkbook(), [{ worksheetSheetName: 'Sheet1', name: 'Staff',
    area: { startRow: 0, startColumn: 0, endRow: 3, endColumn: 1 }, columnNames: ['Name', 'Qty'], bandedRows: true }])
}
it('persists table edits through the shared browser and server protocol', async () => {
  const bytes = await applyWorkbookOperations(await fixture(), [{ kind: 'applyTableEdits', edits: [{
    worksheetSheetName: 'Sheet1', tableName: 'Staff', columnNames: ['Employee', 'Qty'],
  }] }])
  expect((await readWorkbook(bytes)).sheets[0]!.tables![0]!.columns[0]!.name).toBe('Employee')
})
it.each([
  { worksheetSheetName: 'Sheet1', tableName: 'Staff', worksheetPath: 'xl/foreign.xml' },
  { worksheetSheetName: 'Sheet1', tableName: 'Staff', area: { startRow: 0, endRow: 4, startColumn: 0, endColumn: 16384 } },
  { worksheetSheetName: 'Sheet1', tableName: 'Staff', firstColumn: 'true' },
])('rejects untrusted table edit payloads', async edit => {
  await expect(applyWorkbookOperations(await fixture(), [{ kind: 'applyTableEdits', edits: [edit] }])).rejects.toThrow()
})
