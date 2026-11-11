import { expect, it } from 'vitest'
import { applyCellEdits, createBlankWorkbook, createBufferEntrySource, readWorkbook } from '@sheets-web/xlsx-engine'
import { assemblePackage } from '@sheets-web/xlsx-engine/zip'
import { readPivotState } from '@sheets-web/xlsx-engine/pivot-add'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createPivotPlan, readWorkbookPivots, refreshWorkbookPivotsPlan } from './workbook-pivot'

const config = { name: 'ByRegion', sourceSheetName: 'Sheet1', sourceTableName: 'Sales', sourceRange: 'A1:C3', targetSheetName: 'Sheet1', targetCell: 'F1', rowFields: ['Region'], columnFields: [], values: [{ field: 'Amount', agg: 'sum' as const }] }
async function fixture(calculated = false, grouped = false) {
  const rows = [['Region', 'Amount', 'Cost'], ['East', 10, 2], ['West', 20, 3]]
  const cells = await applyCellEdits(await createBlankWorkbook(), rows.flatMap((row, r) => row.map((value, c) => ({ sheetName: 'Sheet1', row: r, column: c, writeValue: true, cell: { value } }))))
  const table = await applyWorkbookOperations(cells, [{ kind: 'applyTableAdditions', additions: [{ worksheetSheetName: 'Sheet1', area: { startRow: 0, startColumn: 0, endRow: 2, endColumn: 2 }, name: 'Sales', columnNames: rows[0], style: 'TableStyleMedium4' }] }])
  return applyWorkbookOperations(table, (await createPivotPlan(table, { ...config, ...(calculated ? { values: [{ field: 'Profit', agg: 'sum' as const, formula: "'Amount' - 'Cost'" }], pageFilters: [{ field: 'Cost' }] } : {}), ...(grouped ? { rowFields: ['Cost'], groupings: [{ field: 'Cost', kind: 'range' as const, rangeStep: 10 }], filters: [{ field: 'Cost', kind: 'label' as const, op: 'equal' as const, value: '0-10' }], pageFilters: [{ field: 'Region' }] } : {}) })).operations)
}
const rename = (names: string[]) => ({ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Sales', columnNames: names }] })
const headers = (names: string[]) => ({ kind: 'applyCellEdits', edits: names.map((value, column) => ({ sheetName: 'Sheet1', row: 0, column, writeValue: true, cell: { value } })) })

it.each([{ names: ['Area', 'Revenue', 'Cost'] }, { names: ['Amount', 'Region', 'Cost'] }])('migrates owned field identities simultaneously and refreshes with unchanged results: $names', async ({ names }) => {
  const input = await fixture(), snapshot = input.slice(), before = (await readWorkbookPivots(input))[0]!, zip = await createBufferEntrySource(input)
  const saved = await applyWorkbookOperations(input, [headers(names), rename(names)]), after = (await readWorkbookPivots(saved))[0]!, result = await createBufferEntrySource(saved)
  expect(input).toEqual(snapshot)
  expect(after).toMatchObject({ fieldNames: names, rowFields: [names[0]], values: [{ field: names[1], agg: 'sum' }] })
  expect(after.readonlyReason).toBeUndefined()
  for (const path of await zip.paths()) if (!['xl/worksheets/sheet1.xml', 'xl/tables/table1.xml', before.cachePath, before.tablePath].includes(path)) expect(await result.readText(path)).toBe(await zip.readText(path))
  const refreshed = await applyWorkbookOperations(saved, (await refreshWorkbookPivotsPlan(saved)).operations)
  expect((await readWorkbook(refreshed)).sheets[0]!.cells.G4?.value).toBe(30)
})

it('renames calculated field references while retaining report filter indices and raw extra metadata', async () => {
  const input = await fixture(true), pivot = (await readWorkbookPivots(input))[0]!, zip = await createBufferEntrySource(input)
  const xml = await zip.readText(pivot.tablePath), tag = xml.match(/<aio:aioPivotState\b[^>]*\/>/)![0]
  const extended = (await assemblePackage(input, { replaced: new Map([[pivot.tablePath, xml.replace(tag, tag.replace('&quot;fieldNames&quot;', '&quot;localExtra&quot;:{&quot;keep&quot;:7},&quot;fieldNames&quot;'))]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [pivot.tablePath] })).buffer
  const names = ['Area', "Rev'enue & Tax", 'Expense'], saved = await applyWorkbookOperations(extended, [headers(names), rename(names)]), source = await createBufferEntrySource(saved)
  const state = readPivotState(await source.readText(pivot.tablePath))!
  expect(state.fieldNames).toEqual(names)
  expect(state.values[0]!.formula).toContain("Rev''enue & Tax")
  expect(state.values[0]!.formula).toContain('Expense')
  expect(state.pageFilters).toEqual(readPivotState(await zip.readText(pivot.tablePath))!.pageFilters)
  expect(await source.readText(pivot.tablePath)).toContain('&quot;localExtra&quot;:{&quot;keep&quot;:7}')
  const refreshed = await applyWorkbookOperations(saved, (await refreshWorkbookPivotsPlan(saved)).operations)
  expect((await readWorkbookPivots(refreshed))[0]!.values[0]!.formula).toContain('Expense')
  expect((await readWorkbook(refreshed)).sheets[0]!.cells.G4?.value).toBe(25)
})

it('preserves numeric grouping, label filters and report selection while renaming their source fields', async () => {
  const input = await fixture(true, true), pivot = (await readWorkbookPivots(input))[0]!, zip = await createBufferEntrySource(input)
  const before = readPivotState(await zip.readText(pivot.tablePath))!, names = ['Area', 'Revenue', 'Expense']
  const saved = await applyWorkbookOperations(input, [headers(names), rename(names)]), state = readPivotState(await (await createBufferEntrySource(saved)).readText(pivot.tablePath))!
  for (const key of ['groupings', 'standardGroupings', 'groupingPersistence', 'filters', 'pageFilters', 'manualHiddenMembers'] as const) expect(state[key]).toEqual(before[key])
  const refreshed = await applyWorkbookOperations(saved, (await refreshWorkbookPivotsPlan(saved)).operations), after = (await readWorkbookPivots(refreshed))[0]!
  expect(after.groupings?.[0]!.field).toBe('Expense')
  expect(after.filters?.[0]!.field).toBe('Expense')
  expect(after.pageFilters?.[0]!.field).toBe('Area')
  expect((await readWorkbook(refreshed)).sheets[0]!.cells.G3?.value).toBe(25)
})

it('uses current transaction field names for consecutive renames', async () => {
  const input = await fixture(), names = ['Region', 'FinalAmount', 'Cost']
  const saved = await applyWorkbookOperations(input, [rename(['Region', 'Revenue', 'Cost']), headers(names), rename(names)])
  expect((await readWorkbookPivots(saved))[0]!.values[0]!.field).toBe('FinalAmount')
  expect((await readWorkbook(await applyWorkbookOperations(saved, (await refreshWorkbookPivotsPlan(saved)).operations))).sheets[0]!.cells.G4?.value).toBe(30)
})

it('migrates field and table names together while preserving the dynamic source', async () => {
  const input = await fixture(), names = ['Region', 'Revenue', 'Cost']
  const operation = rename(names);Object.assign(operation.edits[0]!, { name: 'CurrentSales' })
  const saved = await applyWorkbookOperations(input, [headers(names), operation]), pivot = (await readWorkbookPivots(saved))[0]!
  expect(pivot).toMatchObject({ sourceTableName: 'CurrentSales', fieldNames: names, values: [{ field: 'Revenue' }] })
  expect((await readWorkbook(await applyWorkbookOperations(saved, (await refreshWorkbookPivotsPlan(saved)).operations))).sheets[0]!.cells.G4?.value).toBe(30)
})

it('rejects an incomplete shared owner even when its matching relationship is not first', async () => {
  const first = await fixture(), input = await applyWorkbookOperations(first, (await createPivotPlan(first, { ...config, sourceTableName: undefined, name: 'Second', targetCell: 'K1' })).operations)
  const pivots = await readWorkbookPivots(input), original = pivots[0]!, second = pivots[1]!, zip = await createBufferEntrySource(input)
  const path = second.tablePath.replace(/([^/]+)$/, '_rels/$1.rels'), rels = await zip.readText(path)
  const sharedTarget = original.cachePath.slice('xl/'.length)
  const altered = rels.replace('</Relationships>', `<Relationship Id="rIdShared" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotCacheDefinition" Target="../${sharedTarget}"/></Relationships>`)
  const xml = (await zip.readText(second.tablePath)).replace(/<ext uri="\{AIO-PIVOT-STATE\}"[\s\S]*?<\/ext>/, '')
  const malformed = (await assemblePackage(input, { replaced: new Map([[path, altered], [second.tablePath, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path, second.tablePath] })).buffer
  const snapshot = malformed.slice()
  await expect(applyWorkbookOperations(malformed, [rename(['Region', 'Revenue', 'Cost'])])).rejects.toThrow('完整自有状态')
  expect(malformed).toEqual(snapshot)
})

it('rewrites legal cache attribute quotes and spacing without leaving standard and private names inconsistent', async () => {
  const input = await fixture(true), pivot = (await readWorkbookPivots(input))[0]!, zip = await createBufferEntrySource(input)
  const xml = (await zip.readText(pivot.cachePath)).replace('name="Amount"', `note=' name="Fake"' name = 'Amount'`).replace(/formula="([^"]+)"/, (_match, value) => "formula = '" + value + "'")
  const varied = (await assemblePackage(input, { replaced: new Map([[pivot.cachePath, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [pivot.cachePath] })).buffer
  const names = ['Region', 'Revenue', 'Cost'], saved = await applyWorkbookOperations(varied, [headers(names), rename(names)]), source = await createBufferEntrySource(saved)
  const cache = await source.readText(pivot.cachePath)
  expect(cache).toContain("name = 'Revenue'")
  expect(cache).toContain(`note=' name="Fake"'`)
  expect(cache).not.toContain('name = \'Amount\'')
  expect(cache).toContain('Revenue')
  const refreshed = await applyWorkbookOperations(saved, (await refreshWorkbookPivotsPlan(saved)).operations)
  expect((await readWorkbook(refreshed)).sheets[0]!.cells.G4?.value).toBe(25)
})

it('rejects collisions with calculated names and unowned pivots without changing the input', async () => {
  const calculated = await fixture(true), input = await fixture(), pivot = (await readWorkbookPivots(input))[0]!, zip = await createBufferEntrySource(input)
  const imported = (await assemblePackage(input, { replaced: new Map([[pivot.tablePath, (await zip.readText(pivot.tablePath)).replace(/<ext uri="\{AIO-PIVOT-STATE\}"[\s\S]*?<\/ext>/, '')]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [pivot.tablePath] })).buffer
  for (const [bytes, names] of [[calculated, ['Region', 'Profit', 'Cost']], [imported, ['Area', 'Amount', 'Cost']]] as const) {
    const snapshot = bytes.slice()
    await expect(applyWorkbookOperations(bytes, [rename([...names])])).rejects.toThrow()
    expect(bytes).toEqual(snapshot)
  }
})
