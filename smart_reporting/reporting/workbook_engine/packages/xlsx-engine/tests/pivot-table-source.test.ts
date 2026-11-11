import { expect, it } from 'vitest'
import { pivotCacheReadsFromTable, renameTableInPivotCacheSource } from '../src/pivot-cache-source'

const ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
it('matches cached field dependencies by decoded name and ignores foreign nodes and comments', () => {
  const xml = `<root xmlns:p="${ns}" xmlns:q="urn:foreign"><p:worksheetSource name="sAlEs"/><p:cacheFields><p:cacheField name="Amount &amp; Tax"/><p:cacheField name="_x005F_Code"/><q:cacheField name="Ignored"/><!-- <p:cacheField name="Comment"/> --></p:cacheFields></root>`
  expect(pivotCacheReadsFromTable(xml, 'Sales', ['Amount & Tax'])).toBe(true)
  expect(pivotCacheReadsFromTable(xml, 'Sales', ['_Code'])).toBe(true)
  expect(pivotCacheReadsFromTable(xml, 'Sales', ['_x005F_Code'])).toBe(true)
  expect(pivotCacheReadsFromTable(xml, 'Sales', ['amount & tax'])).toBe(true)
  for (const names of [[], ['Ignored'], ['Comment'], ['Unused']]) expect(pivotCacheReadsFromTable(xml, 'Sales', names)).toBe(false)
  expect(pivotCacheReadsFromTable(xml, 'Other', ['Amount & Tax'])).toBe(false)
})
it('renames decoded table references while preserving comments, foreign nodes and other attributes', () => {
  const xml = `<root xmlns:p="${ns}" xmlns:q="urn:foreign"><!-- <p:worksheetSource name="Sales"/> --><q:worksheetSource name="Sales"/><p:worksheetSource note=' name="Sales"' name = 's&#x61;les' sheet="Data" q:name="Sales"/></root>`
  expect(pivotCacheReadsFromTable(xml, 'SALES')).toBe(true)
  expect(renameTableInPivotCacheSource(xml, 'Sales', 'CurrentSales', 'Data')).toBe(xml.replace("name = 's&#x61;les'", "name = 'CurrentSales'"))
})

it.each([
  `<root xmlns="${ns}"><worksheetSource name="Sales" sheet="Other"/></root>`,
  `<root xmlns="${ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><worksheetSource name="Sales" r:id="external"/></root>`,
])('refuses a mismatched or external named source instead of rewriting it: %#', xml => {
  expect(() => renameTableInPivotCacheSource(xml, 'Sales', 'CurrentSales', 'Data')).toThrow('透视')
})

it.each([
  `<root xmlns="${ns}"><worksheetSource name="Sales"/></wrong>`,
  `<!DOCTYPE root><root xmlns="${ns}"><worksheetSource name="Sales"/></root>`,
])('validates the entire cache before producing any renamed XML: %#', xml => {
  expect(() => renameTableInPivotCacheSource(xml, 'Sales', 'CurrentSales')).toThrow()
})
