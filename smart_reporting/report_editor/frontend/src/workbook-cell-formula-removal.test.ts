import { expect, it } from 'vitest'
const implementation = './workbook-cell-formula-removal'
const workbook = (cells: any[], sourceRules: any[] = []) => {
  const make = (id: string, name: string, values: any[]) => ({ getSheetId: () => id, getSheetName: () => name,
    getSheet: () => ({ getCellMatrix: () => ({ forValue: (callback: any) => values.forEach(([row, column, cell]) => callback(row, column, cell)) }) }),
    getRange: (row: number, column: number) => ({ getFormula: () => values.find(item => item[0] === row && item[1] === column)?.[2].resolved ?? '' }) })
  const source = make('source', 'Source', sourceRules), other = make('other', 'Other', cells)
  return { getId: () => 'book-id', getActiveSheet: () => source, getSheetBySheetId: () => source, getSheets: () => [source, other] }
}
it.each(['=Source!A1', '=source!a1', "='SOURCE'!$A$1", "='[book-id]SOURCE'!a1", '=[book-id]source!a1'])('rejects current offscreen sparse formula %s', async f => {
  const { assertCellFormulaSheetRemoval } = await import(/* @vite-ignore */ implementation)
  expect(() => assertCellFormulaSheetRemoval(workbook([[99999, 123, { f }]]), 'source')).toThrow('Other')
})
it('reads resolved shared formulas from the official formula facade and excludes the removed sheet', async () => {
  const { assertCellFormulaSheetRemoval } = await import(/* @vite-ignore */ implementation)
  expect(() => assertCellFormulaSheetRemoval(workbook([[7, 3, { si: 'shared', resolved: '=Source!A2' }]]), 'source')).toThrow('Source')
  expect(() => assertCellFormulaSheetRemoval(workbook([], [[0, 0, { f: '=Source!A1' }]]), 'source')).not.toThrow()
})
it.each(['="Source!A1"', '=[remote.xlsx]Source!A1', "='[remote.xlsx]Source'!A1", '=[BOOK-ID]Source!A1'])('allows actual external or literal %s', async f => {
  const { assertCellFormulaSheetRemoval } = await import(/* @vite-ignore */ implementation)
  expect(() => assertCellFormulaSheetRemoval(workbook([[0, 2, { f }]]), 'source')).not.toThrow()
})
it('uses raw only for unprojected cell formulas, excluding obsolete normal cells and CF/DV', async () => {
  const { assertCellFormulaSheetRemoval } = await import(/* @vite-ignore */ implementation)
  const book = workbook([[0, 2, { f: '=1' }]]), source = (sourceXml: string, unprojected = true) => () => ({ sourceXml, unprojected })
  expect(() => assertCellFormulaSheetRemoval(book, 'source', source('<worksheet><sheetData><c><f>Source!A1</f></c></sheetData></worksheet>', false))).not.toThrow()
  expect(() => assertCellFormulaSheetRemoval(book, 'source', source('<worksheet><sheetData><c><f t="shared">Source!A1</f></c></sheetData></worksheet>'))).toThrow('完整投影')
  expect(() => assertCellFormulaSheetRemoval(book, 'source', source('<worksheet><sheetData><c><f>1</f></c></sheetData><conditionalFormatting><formula>Source!A1</formula></conditionalFormatting><dataValidation><formula1>Source!A1</formula1></dataValidation></worksheet>'))).not.toThrow()
  expect(() => assertCellFormulaSheetRemoval(book, 'source', source('<worksheet><sheetData><c><f>Source!A1</f></c><c><f t="shared" si="0">1+1</f></c><c><f t="shared" si="0"/></c></sheetData></worksheet>'))).not.toThrow()
})
it('normalizes exact runtime ids with special characters and escaped sheet apostrophes', async () => {
  const { normalizeInternalSheetFormula } = await import('./workbook-internal-formula')
  const formula = `='[book.id+$]财务 O''Brien'!a1+"'[book.id+$]财务 O''Brien'!a1"`
  expect(normalizeInternalSheetFormula(formula, 'book.id+$', "财务 O'Brien")).toBe(`='财务 O''Brien'!a1+"'[book.id+$]财务 O''Brien'!a1"`)
  expect(normalizeInternalSheetFormula(formula, 'BOOK.id+$', "财务 O'Brien")).toBe(formula)
})
it('does not treat valid CF/DV xm:f outside sheetData as cell formula namespaces', async () => {
  const { unprojectedCellFormulaNodes } = await import(/* @vite-ignore */ implementation)
  expect(unprojectedCellFormulaNodes('<worksheet><sheetData><c><f>1</f></c></sheetData><x14:conditionalFormatting><xm:f>Source!A1</xm:f></x14:conditionalFormatting><x14:dataValidations><xm:f>Source!A1</xm:f></x14:dataValidations></worksheet>')).toEqual([])
})
