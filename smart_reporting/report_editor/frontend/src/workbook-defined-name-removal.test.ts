import { expect, it } from 'vitest'
const implementation = './workbook-defined-name-removal'
const entry = (formula: string, scope = 'AllDefaultWorkbook', name = 'Dependency') => ({ getName: () => name, getFormulaOrRefString: () => formula, getLocalSheetId: () => scope })
const book = (entries: any[]) => {
  const source = { getSheetId: () => 'source', getSheetName: () => 'Source' }, other = { getSheetId: () => 'other', getSheetName: () => 'Other' }
  return { getId: () => 'book-id', getDefinedNames: () => entries, getActiveSheet: () => source, getSheets: () => [source, other], getSheetBySheetId: (id: string) => [source, other].find(s => s.getSheetId() === id) }
}
const xml = (node: string) => `<workbook><sheets><sheet name="Source"/><sheet name="Other"/></sheets><definedNames>${node}</definedNames></workbook>`
it.each(['AllDefaultWorkbook', 'other'])('rejects surviving name scope %s before deletion', async scope => {
  const { assertDefinedNameSheetRemoval } = await import(/* @vite-ignore */ implementation)
  expect(() => assertDefinedNameSheetRemoval(book([entry("='[book-id]sOuRcE'!$a$1", scope)]), 'source')).toThrow('Dependency')
})
it('drops only names owned by the removed sheet and uses current edits', async () => {
  const { assertDefinedNameSheetRemoval } = await import(/* @vite-ignore */ implementation)
  const entries = [entry('Source!A1', 'source'), entry('Source!A1', 'other')], workbook = book(entries)
  expect(() => assertDefinedNameSheetRemoval(workbook, 'source')).toThrow()
  entries.pop()
  expect(() => assertDefinedNameSheetRemoval(workbook, 'source', { workbookXml: xml('<definedName name="Dependency" localSheetId="1">Source!A1</definedName>') })).not.toThrow()
})
it.each(['="Source!A1"', '=[remote.xlsx]Source!A1', "='[remote.xlsx]Source'!A1", '=[BOOK-ID]Source!A1', '=Other!A1'])('preserves literal and external identity %s', async formula => {
  const { assertDefinedNameSheetRemoval } = await import(/* @vite-ignore */ implementation)
  expect(() => assertDefinedNameSheetRemoval(book([entry(formula)]), 'source')).not.toThrow()
})
it('protects unprojected built-in names by original positional sheet scope', async () => {
  const { assertDefinedNameSheetRemoval } = await import(/* @vite-ignore */ implementation)
  const check = (scope: string) => () => assertDefinedNameSheetRemoval(book([]), 'source', { workbookXml: xml(`<definedName name="_xlnm.Print_Area" localSheetId="${scope}">Source!$A$1</definedName>`) })
  expect(check('1')).toThrow('完整投影')
  expect(check('0')).not.toThrow()
  expect(check('bad')).toThrow('完整')
})
it('does not hide malformed runtime names or scope identities', async () => {
  const { assertDefinedNameSheetRemoval } = await import(/* @vite-ignore */ implementation)
  expect(() => assertDefinedNameSheetRemoval(book([entry('Source!A1', 'missing')]), 'source')).toThrow('作用域')
  expect(() => assertDefinedNameSheetRemoval(book([{ getName: () => 'Lost' }]), 'source')).toThrow('完整')
})
it('protects only initial failed projection identities, preserving later user deletions', async () => {
  const { assertDefinedNameSheetRemoval } = await import(/* @vite-ignore */ implementation)
  const workbook = book([]), workbookXml = xml('<definedName name="Dependency" localSheetId="1">Source!A1</definedName>')
  expect(() => assertDefinedNameSheetRemoval(workbook, 'source', { workbookXml, unprojectedNames: [{ name: 'dependency', scopeSheetId: 'other' }] })).toThrow('完整投影')
  expect(() => assertDefinedNameSheetRemoval(workbook, 'source', { workbookXml, unprojectedNames: [{ name: 'Dependency', scopeSheetId: 'source' }] })).not.toThrow()
  expect(() => assertDefinedNameSheetRemoval(workbook, 'source', { workbookXml })).not.toThrow()
})
