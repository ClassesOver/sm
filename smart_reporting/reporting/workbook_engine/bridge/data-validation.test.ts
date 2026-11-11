import { expect, it } from 'vitest'
import { createBlankWorkbook, readWorkbook, createBufferEntrySource } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from './operations'

it('replaces and clears full sheet validation snapshots without changing other parts', async () => {
  const bytes = await createBlankWorkbook()
  const operation = { kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules: [{
    ranges: [{ startRow: 1, endRow: 9, startColumn: 0, endColumn: 0 }],
    rule: { type: 'whole', operator: 'greaterThan', formula1: '0', allowBlank: false, showErrorMessage: true, errorTitle: '数量', error: '请输入正整数' },
  }] }
  const result = await applyWorkbookOperations(bytes, [operation])
  expect((await readWorkbook(result)).sheets[0]?.dataValidations?.rules[0]?.rule).toMatchObject({ type: 'whole', allowBlank: false, errorTitle: '数量', error: '请输入正整数' })
  const before = await createBufferEntrySource(bytes), after = await createBufferEntrySource(result)
  for (const path of await before.paths()) {
    if (path !== 'xl/worksheets/sheet1.xml') expect(await after.readText(path)).toBe(await before.readText(path))
  }
  const cleared = await applyWorkbookOperations(result, [{ ...operation, rules: [] }])
  expect((await readWorkbook(cleared)).sheets[0]?.dataValidations?.rules).toEqual([])
})

it('rejects malformed wire rules and unknown target sheets', async () => {
  const bytes = await createBlankWorkbook()
  await expect(applyWorkbookOperations(bytes, [{ kind: 'replaceSheetDataValidations', sheetName: 'Missing', rules: [] }])).rejects.toThrow()
  await expect(applyWorkbookOperations(bytes, [{ kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules: [{ ranges: [{ startRow: -1, endRow: 1, startColumn: 0, endColumn: 0 }], rule: { type: 'whole' } }] }])).rejects.toThrow()
})

it('keeps validation counts correct after deleting a complete rule and permits later edits', async () => {
  const rules = [0, 1].map(row => ({ ranges: [{ startRow: row, endRow: row, startColumn: 0, endColumn: 0 }], rule: { type: 'whole', formula1: '0', operator: 'greaterThan' } }))
  const source = await applyWorkbookOperations(await createBlankWorkbook(), [{ kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules }])
  const shifted = await applyWorkbookOperations(source, [{ kind: 'applyRowColumnOps', sheetName: 'Sheet1', ops: [{ kind: 'remove-rows', index: 0, count: 1 }] }])
  const model = (await readWorkbook(shifted)).sheets[0]!.dataValidations!
  expect(model.readOnlyReason).toBeUndefined()
  expect(model.rules).toHaveLength(1)
  const changed = await applyWorkbookOperations(shifted, [{ kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules: model.rules.map(item => ({ ...item, rule: { ...item.rule, formula1: '5' } })) }])
  expect((await readWorkbook(changed)).sheets[0]?.dataValidations?.rules[0]?.rule.formula1).toBe('5')
})
