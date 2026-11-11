import { expect, it } from 'vitest'
const implementation = './workbook-dv-sheet-removal'
const workbook = (rule: any, ownRule?: any) => {
  const source = { getSheetId: () => 'source', getSheetName: () => 'Source', getDataValidations: () => ownRule ? [{ rule: ownRule }] : [] }
  const other = { getSheetId: () => 'other', getSheetName: () => 'Other', getDataValidations: () => rule ? [{ rule }] : [] }
  return { getId: () => 'book-id', getActiveSheet: () => source, getSheetBySheetId: () => source, getSheets: () => [source, other] }
}
it.each(['=Source!A1:A5', '=source!a1:a5', "='Source'!$A$1", "='[book-id]Source'!A1", '=[book-id]Source!A1'])('rejects live DV dependency %s', async formula1 => {
  const { assertDataValidationSheetRemoval } = await import(/* @vite-ignore */ implementation)
  expect(() => assertDataValidationSheetRemoval(workbook({ type: 'list', formula1 }), 'source')).toThrow('Other')
})
it('checks formula2 and current newly added references', async () => {
  const { assertDataValidationSheetRemoval } = await import(/* @vite-ignore */ implementation)
  const rule = { type: 'decimal', formula1: '1', formula2: '=Source!A1' }, book = workbook(rule)
  expect(() => assertDataValidationSheetRemoval(book, 'source')).toThrow('数据验证')
  rule.formula2 = '=1';expect(() => assertDataValidationSheetRemoval(book, 'source')).not.toThrow()
})
it.each(['custom', 'decimal'])('recognizes bare formulas for %s rather than list constants', async type => {
  const { assertDataValidationSheetRemoval } = await import(/* @vite-ignore */ implementation)
  expect(() => assertDataValidationSheetRemoval(workbook({ type, formula1: 'Source!A1' }), 'source')).toThrow('数据验证')
})
it.each(['Source!A1', '"Source!A1,a"', '="Source!A1"', '=[remote.xlsx]Source!A1', "='[remote.xlsx]Source'!A1", '=[BOOK-ID]Source!A1'])('preserves list literal/external %s and excludes deleted sheet own rules', async formula1 => {
  const { assertDataValidationSheetRemoval } = await import(/* @vite-ignore */ implementation)
  expect(() => assertDataValidationSheetRemoval(workbook({ type: 'list', formula1 }, { type: 'list', formula1: '=Source!A1' }), 'source')).not.toThrow()
})
it('scans incomplete raw DV only, excluding obsolete cell/CF formulas and complete old source', async () => {
  const { assertDataValidationSheetRemoval } = await import(/* @vite-ignore */ implementation)
  const book = workbook(undefined), source = (sourceXml: string, readOnlyReason = 'unknown') => () => ({ readOnlyReason, sourceXml })
  expect(() => assertDataValidationSheetRemoval(book, 'source', source('<worksheet><c><f>Source!A1</f></c><conditionalFormatting><formula>Source!A1</formula></conditionalFormatting><dataValidations><dataValidation><formula1>"Source!A1"</formula1></dataValidation></dataValidations></worksheet>'))).not.toThrow()
  expect(() => assertDataValidationSheetRemoval(book, 'source', source('<dataValidations><dataValidation><formula1>Source!A1</formula1></dataValidation></dataValidations>'))).toThrow('Other')
  expect(() => assertDataValidationSheetRemoval(book, 'source', source('<x14:dataValidations><x14:dataValidation><x14:formula1><xm:f>Source!A1</xm:f></x14:formula1></x14:dataValidation></x14:dataValidations>'))).toThrow('Other')
  expect(() => assertDataValidationSheetRemoval(book, 'source', source('<dataValidations><dataValidation><formula1>Source!A1</formula1></dataValidation></dataValidations>', ''))).not.toThrow()
})
it('refuses incomplete unknown DV namespaces instead of silently treating them as dependency-free', async () => {
  const { assertDataValidationSheetRemoval } = await import(/* @vite-ignore */ implementation)
  expect(() => assertDataValidationSheetRemoval(workbook(undefined), 'source', () => ({ readOnlyReason: 'unknown namespace', sourceXml: '<u:dataValidations><u:dataValidation><u:formula1>Source!A1</u:formula1></u:dataValidation></u:dataValidations>' }))).toThrow('无法完整核对')
})
