import { expect, it } from 'vitest'
const implementation = './workbook-cf-sheet-removal'
const rules = (formula: string) => [{ cfId: 'r', ranges: [{ startRow: 0, endRow: 3, startColumn: 1, endColumn: 1 }], rule: { type: 'highlightCell', subType: 'formula', value: formula, style: {} } }]
const workbook = (current: any[], targetRules: any[] = []) => {
  const source = { getSheetId: () => 'source', getSheetName: () => 'Source', getConditionalFormattingRules: () => targetRules }
  const other = { getSheetId: () => 'other', getSheetName: () => 'Other', getConditionalFormattingRules: () => current }
  return { getActiveSheet: () => source, getSheetBySheetId: (id: string) => id === 'source' ? source : other, getSheets: () => [source, other] }
}

it.each(['=Source!A1>0', '=source!a1>0', "='Source'!$A$1>0"])('rejects current surviving expression dependency %s', async formula => {
  const { assertConditionalFormattingSheetRemoval } = await import(/* @vite-ignore */ implementation)
  expect(() => assertConditionalFormattingSheetRemoval(workbook(rules(formula)), 'source')).toThrow('Other')
})

it.each(['dataBar', 'colorScale', 'iconSet'])('rejects current formula thresholds for %s', async type => {
  const { assertConditionalFormattingSheetRemoval } = await import(/* @vite-ignore */ implementation)
  const threshold = { type: 'formula', value: '=Source!A1' }
  expect(() => assertConditionalFormattingSheetRemoval(workbook([{ rule: { type, config: { min: threshold, values: [{ value: threshold }] } } }]), 'source')).toThrow('Source')
})

it.each(['=TRUE', '="Source!A1"', '=[remote.xlsx]Source!A1>0', "='[remote.xlsx]Source'!A1>0"])('allows nondependency %s and ignores the removed sheet own rules', async formula => {
  const { assertConditionalFormattingSheetRemoval } = await import(/* @vite-ignore */ implementation)
  expect(() => assertConditionalFormattingSheetRemoval(workbook(rules(formula), rules('=Source!A1>0')), 'source')).not.toThrow()
})

it('checks incomplete raw CF thresholds while excluding old ordinary cell formulas', async () => {
  const { assertConditionalFormattingSheetRemoval } = await import(/* @vite-ignore */ implementation)
  const book = workbook([]), source = (sourceXml: string) => () => ({ issues: ['unsupported CF'], sourceXml })
  expect(() => assertConditionalFormattingSheetRemoval(book, 'source', source('<worksheet><c><f>Source!A1</f></c><conditionalFormatting sqref="B1"><cfRule type="unknown"><formula>TRUE</formula></cfRule></conditionalFormatting></worksheet>'))).not.toThrow()
  expect(() => assertConditionalFormattingSheetRemoval(book, 'source', source('<worksheet><conditionalFormatting sqref="B1"><cfRule type="dataBar"><dataBar><cfvo type="formula" val="source!a1"/></dataBar></cfRule></conditionalFormatting></worksheet>'))).toThrow('Other')
  expect(() => assertConditionalFormattingSheetRemoval(book, 'source', source('<worksheet><x14:conditionalFormatting><x14:cfRule><xm:f>Source!A1</xm:f></x14:cfRule></x14:conditionalFormatting></worksheet>'))).toThrow('Other')
})

it('uses live rules instead of obsolete complete source expressions', async () => {
  const { assertConditionalFormattingSheetRemoval } = await import(/* @vite-ignore */ implementation)
  expect(() => assertConditionalFormattingSheetRemoval(workbook(rules('=TRUE')), 'source', () => ({ issues: [], sourceXml: '<conditionalFormatting><formula>Source!A1</formula></conditionalFormatting>' }))).not.toThrow()
})
