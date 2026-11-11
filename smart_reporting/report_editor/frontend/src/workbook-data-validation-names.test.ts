import { expect, it, vi } from 'vitest'
import { ICommandService } from '@univerjs/core'
import { DataValidationFormulaService } from '@univerjs/sheets-data-validation'
import { DataValidatorRegistryService } from '@univerjs/data-validation'
import { installDataValidationNames } from './workbook-data-validation-names'

it('resolves global aliases case-insensitively, delegates other inputs and restores the validator', () => {
  const original = vi.fn((rule: any) => ({ success: rule.formula1 === '=Sheet1!$A$1:$A$2' }))
  const validator = { validatorFormula: original }
  const entries: Record<string, any> = {
    a: { name: 'Choices', formulaOrRefString: 'Alias' },
    b: { name: 'Alias', formulaOrRefString: 'Sheet1!$A$1:$A$2' },
    c: { name: 'Cycle', formulaOrRefString: 'Cycle' },
    d: { name: 'LocalOnly', formulaOrRefString: 'Sheet1!$A$1:$A$2', localSheetId: 'sheet-0' },
  }
  const registration = installDataValidationNames({ univer: { __getInjector: () => ({ get: (id: unknown) =>
    id === DataValidationFormulaService ? { addRule() {} } : id === ICommandService ? { onCommandExecuted: () => ({ dispose() {} }) } : id === DataValidatorRegistryService ? { getValidatorItem: () => validator } : { getDefinedNameMap: () => entries } }) }, univerAPI: { getActiveWorkbook: () => null } })
  const rule = { formula1: '=cHoIcEs' }
  expect(validator.validatorFormula(rule)).toEqual({ success: true })
  expect(rule.formula1).toBe('=cHoIcEs')
  expect(validator.validatorFormula({ formula1: '=Missing' })).toEqual({ success: false })
  expect(validator.validatorFormula({ formula1: '=Cycle' })).toEqual({ success: false })
  expect(validator.validatorFormula({ formula1: '=LocalOnly' })).toEqual({ success: false })
  expect(validator.validatorFormula({ formula1: 'a,b' })).toEqual({ success: false })
  entries.b.formulaOrRefString = 'Missing'
  expect(validator.validatorFormula(rule)).toEqual({ success: false })
  registration.dispose()
  expect(validator.validatorFormula).toBe(original)
})

it('resolves local aliases before globals per rule sheet and detects local cycles without changing file rules', () => {
  const original = vi.fn((rule: any, _unitId: string, _sheetId: string) => rule.formula1), validator = { validatorFormula: original }
  const entries = {
    global: { name: 'Choices', formulaOrRefString: 'Sheet1!$A$1:$A$2' },
    local: { name: 'Choices', formulaOrRefString: 'Alias', localSheetId: 'sheet-1' },
    alias: { name: 'Alias', formulaOrRefString: 'Other!$B$1:$B$2', localSheetId: 'sheet-1' },
    cycle: { name: 'Alias', formulaOrRefString: 'Choices', localSheetId: 'sheet-2' },
    cycleChoice: { name: 'Choices', formulaOrRefString: 'Alias', localSheetId: 'sheet-2' },
  }
  const registration = installDataValidationNames({ univer: { __getInjector: () => ({ get: (id: unknown) =>
    id === DataValidationFormulaService ? { addRule() {} } : id === ICommandService ? { onCommandExecuted: () => ({ dispose() {} }) } : id === DataValidatorRegistryService ? { getValidatorItem: () => validator } : { getDefinedNameMap: () => entries } }) }, univerAPI: { getActiveWorkbook: () => null } })
  try {
    const rule = { formula1: '=Choices' }
    expect(validator.validatorFormula(rule, 'book', 'sheet-0')).toBe('=Sheet1!$A$1:$A$2')
    expect(validator.validatorFormula(rule, 'book', 'sheet-1')).toBe('=Other!$B$1:$B$2')
    expect(validator.validatorFormula(rule, 'book', 'sheet-2')).toBe('=#NAME?')
    expect(rule.formula1).toBe('=Choices')
  } finally { registration.dispose() }
})
