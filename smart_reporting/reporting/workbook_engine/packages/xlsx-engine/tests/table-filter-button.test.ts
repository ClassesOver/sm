import { expect, it } from 'vitest'
import { applyTableAdditions, applyTableEdits, createBlankWorkbook, readWorkbook } from '../src'
import { assemblePackage, createBufferEntrySource } from '../src/zip'

it('removes filter criteria on disable, restores a totals-excluding filter on enable, and preserves worksheet cells', async () => {
  const initial = await applyTableAdditions(await createBlankWorkbook(), [{ worksheetSheetName: 'Sheet1', name: 'Staff',
    area: { startRow: 0, endRow: 4, startColumn: 0, endColumn: 1 }, columnNames: ['Name', 'Qty'], bandedRows: true }])
  const totals = await applyTableEdits(initial, [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', totalsRow: true }])
  const source = await createBufferEntrySource(totals), path = 'xl/tables/table1.xml'
  const xml = (await source.readText(path)).replace(/<autoFilter\b[^>]*\/>/, '<autoFilter ref="A1:B4"><filterColumn colId="0"><filters><filter val="Ada"/></filters></filterColumn></autoFilter>')
  const withCriteria = (await assemblePackage(totals, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
  const disabled = await applyTableEdits(withCriteria, [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', filterButton: false }])
  expect((await readWorkbook(disabled)).sheets[0]!.tables![0]).toMatchObject({ filterButton: false, totalsRowCount: 1 })
  const off = await createBufferEntrySource(disabled)
  expect(await off.readText(path)).not.toContain('<autoFilter')
  const enabled = await applyTableEdits(disabled, [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', filterButton: true }])
  const on = await createBufferEntrySource(enabled)
  expect(await on.readText(path)).toContain('<autoFilter ref="A1:B4"/>')
  expect(await on.readText(path)).not.toContain('<filterColumn')
  expect((await readWorkbook(enabled)).sheets[0]!.tables![0]!.filterButton).toBe(true)
  for (const entry of await source.paths()) if (entry !== path) expect(await on.readText(entry)).toBe(await source.readText(entry))
  const headerless = await applyTableEdits(enabled, [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', headerRow: false, filterButton: true }])
  expect((await readWorkbook(headerless)).sheets[0]!.tables![0]).toMatchObject({ filterButton: false, headerRowCount: 0 })
})
