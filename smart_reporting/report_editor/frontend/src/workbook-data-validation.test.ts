import { expect, it } from 'vitest'
import { createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { withWorkbookDataValidations, workbookDataValidationOperations, validateDataValidationEdit } from './workbook-data-validation'

const ranges = [{ startRow: 1, endRow: 3, startColumn: 1, endColumn: 1 }]
const rule = { type: 'whole', operator: 'greaterThan', formula1: '0', allowBlank: false }

it('preflights unsupported rules and snapshot budgets before official commands change the grid', () => {
  const rules = [{ uid: 'r', ranges, ...rule }]
  expect(() => validateDataValidationEdit('sheets.command.update-data-validation-setting', { ruleId: 'r', setting: { type: 'listMultiple', formula1: 'a,b' } }, rules, [], 0)).toThrow(/Multi-select/)
  expect(() => validateDataValidationEdit('data-validation.mutation.updateRule', { ruleId: 'r', payload: { type: 0, payload: { type: 'listMultiple' } } }, rules, [], 0)).toThrow(/Multi-select/)
  expect(() => validateDataValidationEdit('sheet.command.addDataValidation', { rule: { ...rules[0], ranges: [] } }, rules, [], 0)).toThrow()
  expect(() => validateDataValidationEdit('sheets.command.update-data-validation-options', { ruleId: 'r', options: { error: 'x'.repeat(8 * 1024 * 1024) } }, rules, [], 0)).toThrow(/预算/)
  expect(() => validateDataValidationEdit('sheets.command.update-data-validation-options', { ruleId: 'r', options: { error: '修改提示' } }, rules, [], 0)).not.toThrow()
})

it('installs source rules into the official resource and emits no unchanged edits', async () => {
  const bytes = await applyWorkbookOperations(await createBlankWorkbook(), [{ kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules: [{ ranges, rule }] }])
  const model = await readWorkbook(bytes)
  const data = withWorkbookDataValidations({ sheets: { 'sheet-0': { id: 'sheet-0', name: 'Sheet1' } } }, model)
  const installed = JSON.parse(data.resources[0]!.data)['sheet-0']
  expect(installed[0]).toMatchObject({ uid: 'file-dv-sheet-0-0', ranges, ...rule })
  expect(workbookDataValidationOperations(model, { getSheets: () => [{ getSheetName: () => 'Sheet1', getDataValidations: () => installed.map((rule: unknown) => ({ rule })) }] })).toEqual([])
})

it('captures edits and complete removal as declarative snapshots', async () => {
  const model = await readWorkbook(await createBlankWorkbook())
  const sheet = { getSheetName: () => 'Sheet1', getDataValidations: () => [{ rule: { uid: 'new', ranges, ...rule, error: '填写正整数', showErrorMessage: true } }] }
  const operations = workbookDataValidationOperations(model, { getSheets: () => [sheet] })
  expect(operations).toHaveLength(1)
  expect(operations[0]).toMatchObject({ kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules: [{ ranges, rule: { ...rule, error: '填写正整数' } }] })
  const saved = await readWorkbook(await applyWorkbookOperations(await createBlankWorkbook(), operations))
  expect(workbookDataValidationOperations(saved, { getSheets: () => [{ ...sheet, getDataValidations: () => [] }] })).toEqual([{ kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules: [] }])
})

it('does not install partial source snapshots or erase their unseen rules', async () => {
  const model = await readWorkbook(await createBlankWorkbook())
  model.sheets[0]!.dataValidations = { rules: [{ ranges, rule }], readOnlyReason: '含未建模规则' }
  const data = withWorkbookDataValidations({ sheets: { 'sheet-0': { id: 'sheet-0', name: 'Sheet1' } } }, model)
  expect(data.resources).toEqual([])
  expect(workbookDataValidationOperations(model, { getSheets: () => [{ getSheetName: () => 'Sheet1', getDataValidations: () => [] }] })).toEqual([])
})
