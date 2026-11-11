import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { expect, it } from 'vitest'
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

it.each(['default', 'alias', 'entities'])('refuses deleting a surviving pivot source (%s)', async mode => {
  let bytes = fixture(mode === 'entities' ? 'A&B' : 'Source')
  const source = await createBufferEntrySource(bytes)
  const original = await source.readText(cachePath)
  expect(await source.readText('xl/pivotTables/pivotTable1.xml')).toContain('cacheId="1"')
  expect(original).toContain('<worksheetSource')
  if (mode === 'alias') bytes = await withCache(bytes, original.replace(`xmlns="${namespace}"`, `xmlns:p="${namespace}"`).replace(/<(\/?)([A-Za-z][\w]*)(?=[\s/>])/g, '<$1p:$2'))
  if (mode === 'entities') bytes = await withCache(bytes, original.replace('sheet="A&amp;B"', "sheet='a&#38;b'"))
  await expect(applySheetEdits(bytes, { renames: [], additions: [], removals: [mode === 'entities' ? 'A&B' : 'Source'], order: ['Pivot', 'Unused'] })).rejects.toThrow('仍有透视表')
  expect(await (await createBufferEntrySource(bytes)).has('xl/worksheets/sheet1.xml')).toBe(true)
})

it('allows unrelated deletion and retains the actual cache and pivot bytes', async () => {
  const bytes = fixture(), before = await createBufferEntrySource(bytes)
  const result = await applySheetEdits(bytes, { renames: [], additions: [], removals: ['Unused'], order: ['Source', 'Pivot'] })
  const after = await createBufferEntrySource(result)
  for (const path of [cachePath, 'xl/pivotTables/pivotTable1.xml', 'xl/worksheets/sheet2.xml']) expect(await after.readText(path)).toBe(await before.readText(path))
  expect(await after.has('xl/worksheets/sheet3.xml')).toBe(false)
})

it.each([
  [`<pivotCacheDefinition xmlns="${namespace}"><cacheSource type="worksheet"><worksheetSource sheet="source"/></cacheSource></pivotCacheDefinition>`, 'Source', true],
  [`<p:pivotCacheDefinition xmlns:p="${namespace}"><p:worksheetSource sheet='A&#x26;B'/></p:pivotCacheDefinition>`, 'a&b', true],
  [`<root xmlns:p="${namespace}"><p:worksheetSource xmlns:p="urn:foreign" sheet="Source"/></root>`, 'Source', false],
  [`<root xmlns:p="urn:foreign"><p:worksheetSource xmlns:p="${namespace}" sheet="Source"/></root>`, 'Source', true],
  [`<pivotCacheDefinition xmlns="${namespace}"><worksheetSource xmlns:q="urn:foreign" q:sheet="Source"/></pivotCacheDefinition>`, 'Source', false],
  [`<pivotCacheDefinition xmlns="${namespace}"><!-- <worksheetSource sheet="Source"/> --><worksheetSource sheet="Other"/></pivotCacheDefinition>`, 'Source', false],
  [`<pivotCacheDefinition xmlns="${namespace}"><worksheetSource sheet="A&amp;amp;B"/></pivotCacheDefinition>`, 'A&B', false],
  [`<pivotCacheDefinition xmlns="http://purl.oclc.org/ooxml/spreadsheetml/main"><worksheetSource sheet="Source"/></pivotCacheDefinition>`, 'Source', true],
])('uses decoded unqualified attributes and scoped namespace identity %#', async (xml, sheet, expected) => {
  const { pivotCacheReadsFromSheet } = await import('../src/pivot-cache-source')
  expect(pivotCacheReadsFromSheet(String(xml), String(sheet))).toBe(expected)
})

it('rejects malformed or DTD cache XML and matches fixed-source cache paths', async () => {
  const { pivotCacheReadsFromSheet, isPivotCacheDefinitionPath } = await import('../src/pivot-cache-source')
  for (const xml of ['<p:pivotCacheDefinition/>', `<pivotCacheDefinition xmlns="${namespace}"><worksheetSource sheet="Source"/></wrong>`, '<!DOCTYPE root><root/>']) expect(() => pivotCacheReadsFromSheet(xml, 'Source')).toThrow()
  for (const path of [cachePath, 'xl/pivotCache/pivotCacheDefinitionCustom.xml']) expect(isPivotCacheDefinitionPath(path)).toBe(true)
  for (const path of ['xl/pivotCache/pivotCacheRecords1.xml', 'xl/pivotCache/pivotCacheDefinition/nested.xml']) expect(isPivotCacheDefinitionPath(path)).toBe(false)
})
