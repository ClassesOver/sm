import { expect, it } from 'vitest'
import { applyTableAdditions, createBlankWorkbook, readWorkbook } from '../src'
import { assemblePackage, createBufferEntrySource } from '../src/zip'
import { assertRemovedTableDependencies } from '../src/sheet-removal-parts'
async function fixture(transform: (xml: string) => string, relTransform?: (xml: string) => string) {
 const bytes = await applyTableAdditions(await createBlankWorkbook(), [
 { worksheetSheetName: 'Sheet1', name: 'First', area: { startRow: 0, startColumn: 0, endRow: 2, endColumn: 0 }, columnNames: ['A'], bandedRows: true },
 { worksheetSheetName: 'Sheet1', name: 'Second', area: { startRow: 0, startColumn: 2, endRow: 2, endColumn: 2 }, columnNames: ['B'], bandedRows: true }])
 const source = await createBufferEntrySource(bytes)
 const replaced = new Map([['xl/tables/table2.xml', transform(await source.readText('xl/tables/table2.xml'))]])
 if (relTransform) replaced.set('xl/worksheets/_rels/sheet1.xml.rels', relTransform(await source.readText('xl/worksheets/_rels/sheet1.xml.rels')))
 return (await assemblePackage(bytes, { replaced, added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [...replaced.keys()] })).buffer
}
it('retains every identity when the second projection fails', async () => {
 const sheet = (await readWorkbook(await fixture(xml => xml.replace('count="1"', 'count="9"')))).sheets[0]!
 expect(sheet.tables).toEqual([]);expect(sheet.tablesReadOnlyReason).toBeTruthy()
 expect(sheet.tableSources).toEqual([{ path: 'xl/tables/table1.xml', name: 'First', displayName: 'First' }, { path: 'xl/tables/table2.xml', name: 'Second', displayName: 'Second' }])
 expect(sheet.tableSourcesReadOnlyReason).toBeUndefined()
})
it.each([
 (xml: string) => xml.replace(' name="Second"', '').replace(' displayName="Second"', ''),
 (xml: string) => xml.replace('</table>', ''),
 (xml: string) => xml.replace('xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"', 'xmlns="urn:foreign"'),
 (xml: string) => xml.replace('name="Second"', 'name="First"'),
])('withholds partial identities for untrusted roots', async transform => {
 const sheet = (await readWorkbook(await fixture(transform))).sheets[0]!
 expect(sheet.tableSources).toBeUndefined();expect(sheet.tableSourcesReadOnlyReason).toBeTruthy()
})
it('withholds foreign relationship namespace identities', async () => {
 const sheet = (await readWorkbook(await fixture(xml => xml, xml => xml.replace('xmlns="http://schemas.openxmlformats.org/package/2006/relationships"', 'xmlns="urn:foreign"')))).sheets[0]!
 expect(sheet.tableSources).toBeUndefined();expect(sheet.tableSourcesReadOnlyReason).toBeTruthy()
})
it('checks both aliases for save dependencies', async () => {
 const source = await createBufferEntrySource(await fixture(xml => xml.replace('name="Second"', 'name="Alias"')))
 await expect(assertRemovedTableDependencies(source, new Set(['xl/tables/table2.xml']), [], '<definedNames><definedName name="X">SUM(alias[B])</definedName></definedNames>', new Set())).rejects.toThrow('Alias')
})
it('rejects missing names instead of treating them as no dependency', async () => {
 const source = await createBufferEntrySource(await fixture(xml => xml.replace(' name="Second"', '').replace(' displayName="Second"', '')))
 await expect(assertRemovedTableDependencies(source, new Set(['xl/tables/table2.xml']), [], '', new Set())).rejects.toThrow()
})
it('protects table relationships whose target is outside the conventional tables directory', async () => {
 const bytes = await fixture(xml => xml), original = await createBufferEntrySource(bytes)
 const oldPath = 'xl/tables/table2.xml', path = 'xl/custom/table.xml', relPath = 'xl/worksheets/_rels/sheet1.xml.rels'
 const moved = (await assemblePackage(bytes, { replaced: new Map([[relPath, (await original.readText(relPath)).replace('../tables/table2.xml', '../custom/table.xml')]]), added: new Map([[path, await original.readText(oldPath)]]), addedBinary: new Map(), removedEntries: [oldPath], addedEntries: [path], touchedEntries: [relPath] })).buffer
 const source = await createBufferEntrySource(moved)
 await expect(assertRemovedTableDependencies(source, new Set([path]), [], '<definedName name="X">Second[B]</definedName>', new Set())).rejects.toThrow('Second')
})
it('retains a readonly table shared by a surviving incoming relationship', async () => {
 const { planSheetRemovalParts } = await import('../src/sheet-removal-parts')
 const bytes = await fixture(xml => xml.replace('count="1"', 'count="9"'))
 const path = 'custom/_rels/owner.xml.rels'
 const shared = (await assemblePackage(bytes, { replaced: new Map(), added: new Map([[path, '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="shared" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/table" Target="/xl/tables/table2.xml"/></Relationships>']]), addedBinary: new Map(), removedEntries: [], addedEntries: [path], touchedEntries: [] })).buffer
 const source = await createBufferEntrySource(shared)
 const { removedParts } = await planSheetRemovalParts(source, ['xl/worksheets/sheet1.xml'])
 expect(removedParts.has('xl/tables/table1.xml')).toBe(true)
 expect(removedParts.has('xl/tables/table2.xml')).toBe(false)
 await expect(assertRemovedTableDependencies(source, removedParts, [], '<definedName name="X">Second[B]</definedName>', new Set())).resolves.toBeUndefined()
})
it('accepts name-only identity while preserving read-only editing', async () => {
 const sheet = (await readWorkbook(await fixture(xml => xml.replace(' displayName="Second"', '')))).sheets[0]!
 expect(sheet.tablesReadOnlyReason).toBeTruthy()
 expect(sheet.tableSources?.[1]).toEqual({ path: 'xl/tables/table2.xml', name: 'Second', displayName: 'Second' })
})
