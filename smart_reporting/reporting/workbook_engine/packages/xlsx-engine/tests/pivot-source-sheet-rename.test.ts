import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { expect, it } from 'vitest'
import JSZip from 'jszip'
import { applySheetEdits } from '../src/sheet-ops'
import { assemblePackage, createBufferEntrySource } from '../src/zip'

const cachePath = 'xl/pivotCache/pivotCacheDefinition1.xml'
const namespace = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'

// Openpyxl writes a real pivot table, cache and relationships on a surviving sheet.
function fixture(sheetName = 'Source'): Uint8Array {
  return new Uint8Array(execFileSync(fileURLToPath(new URL('../../../../../../.venv/bin/python', import.meta.url)), ['-c', `
from openpyxl import Workbook
from openpyxl.pivot.table import TableDefinition, Location
from openpyxl.pivot.cache import CacheDefinition, CacheSource, WorksheetSource, CacheField, SharedItems
from io import BytesIO
import sys
b=Workbook();s=b.active;s.title=${JSON.stringify(sheetName)};s.append(['Category','Amount']);s.append(['A',10])
pivot=b.create_sheet('Pivot');b.create_sheet('Unused')
p=TableDefinition(name='Report',cacheId=1,dataCaption='Values',location=Location(ref='A1:B3',firstHeaderRow=1,firstDataRow=1,firstDataCol=1))
p.cache=CacheDefinition(cacheSource=CacheSource(type='worksheet',worksheetSource=WorksheetSource(ref='A1:B2',sheet=s.title)),cacheFields=[CacheField(name='Category',sharedItems=SharedItems()),CacheField(name='Amount',sharedItems=SharedItems())])
pivot.add_pivot(p)
f=BytesIO();b.save(f);sys.stdout.buffer.write(f.getvalue())
`]))
}

async function withCache(bytes: Uint8Array, xml: string): Promise<Uint8Array> {
  return (await assemblePackage(bytes, { replaced: new Map([[cachePath, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [cachePath] })).buffer
}

it.each(['default', 'alias', 'entities', 'strict'])('renames actual pivot cache sources and preserves other ZIP parts (%s)', async mode => {
  const oldName = mode === 'entities' ? 'A&B' : 'Source'
  let bytes = fixture(oldName)
  const original = await (await createBufferEntrySource(bytes)).readText(cachePath)
  let cache = original
  if (mode === 'alias') cache = original.replace(`xmlns="${namespace}"`, `xmlns:p="${namespace}"`).replace(/<(\/?)([A-Za-z][\w]*)(?=[\s/>])/g, '<$1p:$2')
  if (mode === 'strict') cache = original.replace(namespace, 'http://purl.oclc.org/ooxml/spreadsheetml/main')
  if (mode === 'entities') cache = original.replace('sheet="A&amp;B"', "sheet = 'a&#38;b'")
  bytes = await withCache(bytes, cache)
  const before = await createBufferEntrySource(bytes)
  cache = await before.readText(cachePath) // EntrySource applies its existing OOXML prefix normalization.
  const result = await applySheetEdits(bytes, { renames: [{ sheetName: oldName, newName: 'New & Data' }], additions: [], removals: [], order: ['New & Data', 'Pivot', 'Unused'] })
  const after = await createBufferEntrySource(result)
  const expected = mode === 'entities' ? cache.replace("'a&#38;b'", "'New &amp; Data'") : cache.replace('sheet="Source"', 'sheet="New &amp; Data"')
  expect(await after.readText(cachePath)).toBe(expected)
  expect(await after.readText('xl/workbook.xml')).toContain('name="New &amp; Data"')
  for (const path of await before.paths()) {
    if (!['xl/workbook.xml', 'xl/_rels/workbook.xml.rels', cachePath].includes(path)) expect(await after.readText(path)).toBe(await before.readText(path))
  }
})

it('applies multiple renames to the previously replaced cache', async () => {
  const bytes = fixture()
  const original = await (await createBufferEntrySource(bytes)).readText(cachePath)
  const cache = original.replace('</cacheSource>', '<worksheetSource ref="C1" sheet="Unused"/></cacheSource>')
  const result = await applySheetEdits(await withCache(bytes, cache), { renames: [{ sheetName: 'Source', newName: 'Data' }, { sheetName: 'Unused', newName: 'Other' }], additions: [], removals: [], order: ['Data', 'Pivot', 'Other'] })
  expect(await (await createBufferEntrySource(result)).readText(cachePath)).toBe(cache.replace('sheet="Source"', 'sheet="Data"').replace('sheet="Unused"', 'sheet="Other"'))
})

it('refuses a separate deletion of the renamed pivot source', async () => {
  const bytes = await applySheetEdits(fixture(), { renames: [{ sheetName: 'Source', newName: 'Data' }], additions: [], removals: [], order: ['Data', 'Pivot', 'Unused'] })
  await expect(applySheetEdits(bytes, { renames: [], additions: [], removals: ['Data'], order: ['Pivot', 'Unused'] })).rejects.toThrow('仍有透视表')
})

it('only rewrites decoded matching unqualified source attributes with exact byte preservation', async () => {
  const { renameSheetInPivotCacheSource } = await import('../src/pivot-cache-source')
  const xml = `<r xmlns:p="${namespace}" xmlns:q="urn:foreign">😀<!-- <p:worksheetSource sheet="A&amp;B"/> --><![CDATA[<p:worksheetSource sheet="A&amp;B"/>]]><p:worksheetSource note=' &gt; sheet="A&amp;B"' sheet = 'a&#x26;b' q:sheet="A&amp;B"/><p:worksheetSource sheet="A&amp;amp;B"/><q:worksheetSource sheet="A&amp;B"/><p:worksheetSource xmlns:p="urn:foreign" sheet="A&amp;B"/><q:worksheetSource xmlns:q="${namespace}" sheet="A&amp;B"/></r>`
  expect(renameSheetInPivotCacheSource(xml, 'A&B', `New & "Q" 'S'`)).toBe(xml.replace("sheet = 'a&#x26;b'", "sheet = 'New &amp; &quot;Q&quot; &apos;S&apos;'").replace(`xmlns:q="${namespace}" sheet="A&amp;B"`, `xmlns:q="${namespace}" sheet="New &amp; &quot;Q&quot; &apos;S&apos;"`))
  expect(renameSheetInPivotCacheSource(xml, 'Missing', 'New')).toBe(xml)
})

it.each([
  `<pivotCacheDefinition xmlns="${namespace}"><worksheetSource sheet="Source"/></wrong>`,
  `<pivotCacheDefinition xmlns="${namespace}"><worksheetSource sheet="Source"/><x:a/></pivotCacheDefinition>`,
  `<!DOCTYPE root><root xmlns="${namespace}"><worksheetSource sheet="Source"/></root>`,
])('rejects the entire rename for malformed XML or DTD %#', async xml => {
  const { renameSheetInPivotCacheSource } = await import('../src/pivot-cache-source')
  expect(() => renameSheetInPivotCacheSource(xml, 'Source', 'New')).toThrow()
  const bytes = await withCache(fixture(), xml)
  await expect(applySheetEdits(bytes, { renames: [{ sheetName: 'Source', newName: 'New' }], additions: [], removals: [], order: ['New', 'Pivot', 'Unused'] })).rejects.toThrow()
  expect(await (await JSZip.loadAsync(bytes)).file(cachePath)!.async('string')).toBe(xml)
})
