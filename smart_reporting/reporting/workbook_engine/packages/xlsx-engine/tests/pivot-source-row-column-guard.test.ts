import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { expect, it } from 'vitest'
import { applyRowColumnOps, applySheetEdits } from '../src/sheet-ops'
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

it.each([
  { kind: 'insert-rows', index: 0, count: 1 }, { kind: 'insert-rows', index: 1, count: 1 },
  { kind: 'remove-rows', index: 0, count: 1 }, { kind: 'remove-rows', index: 1, count: 1 },
  { kind: 'insert-cols', index: 0, count: 1 }, { kind: 'remove-cols', index: 0, count: 1 },
] as const)('refuses source $kind at $index before mutating actual pivot ZIP', async op => {
  const bytes = fixture(), before = await createBufferEntrySource(bytes)
  expect(await before.readText(cachePath)).toContain('sheet="Source"')
  expect(await before.has('xl/pivotTables/pivotTable1.xml')).toBe(true)
  await expect(applyRowColumnOps(bytes, 'Source', [op])).rejects.toThrow('透视表')
  expect(await (await createBufferEntrySource(bytes)).readText(cachePath)).toBe(await before.readText(cachePath))
})
it('allows an unrelated sheet change and preserves pivot/cache/source XML', async () => {
  const bytes = fixture(), before = await createBufferEntrySource(bytes)
  const output = await applyRowColumnOps(bytes, 'Unused', [{ kind: 'insert-rows', index: 0, count: 1 }])
  const after = await createBufferEntrySource(output)
  for (const path of [cachePath, 'xl/pivotTables/pivotTable1.xml', 'xl/worksheets/sheet1.xml', 'xl/worksheets/sheet2.xml']) expect(await after.readText(path)).toBe(await before.readText(path))
})
it.each(['alias', 'entities', 'strict'])('uses trusted decoded namespace source identity (%s)', async mode => {
  const name = mode === 'entities' ? 'A&B' : 'Source'
  const bytes = fixture(name), xml = await (await createBufferEntrySource(bytes)).readText(cachePath)
  const cache = mode === 'alias' ? xml.replace(`xmlns="${namespace}"`, `xmlns:p="${namespace}"`).replace(/<(\/?)([A-Za-z][\w]*)(?=[\s/>])/g, '<$1p:$2')
    : mode === 'entities' ? xml.replace('sheet="A&amp;B"', "sheet='a&#38;b'") : xml.replace(namespace, 'http://purl.oclc.org/ooxml/spreadsheetml/main')
  await expect(applyRowColumnOps(await withCache(bytes, cache), name, [{ kind: 'insert-rows', index: 0, count: 1 }])).rejects.toThrow('透视表')
})
it('checks the current bytes after a prior rename, not the original source names', async () => {
  const renamed = await applySheetEdits(fixture(), { renames: [{ sheetName: 'Source', newName: 'New Data' }], additions: [], removals: [], order: ['New Data', 'Pivot', 'Unused'] })
  await expect(applyRowColumnOps(renamed, 'New Data', [{ kind: 'remove-rows', index: 1, count: 1 }])).rejects.toThrow('透视表')
})
it('allows a source edit after the current cache source has genuinely moved elsewhere', async () => {
  const bytes = fixture(), xml = await (await createBufferEntrySource(bytes)).readText(cachePath)
  const changed = await withCache(bytes, xml.replace('sheet="Source"', 'sheet="Unused"'))
  await expect(applyRowColumnOps(changed, 'Source', [{ kind: 'insert-rows', index: 0, count: 1 }])).resolves.toBeInstanceOf(Uint8Array)
})
