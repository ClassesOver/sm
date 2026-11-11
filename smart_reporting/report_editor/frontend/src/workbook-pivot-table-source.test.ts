import { expect, it } from 'vitest'
import { applyCellEdits, createBlankWorkbook, createBufferEntrySource, readWorkbook } from '@sheets-web/xlsx-engine'
import { assemblePackage } from '@sheets-web/xlsx-engine/zip'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createPivotPlan, readWorkbookPivots, refreshWorkbookPivotsPlan } from './workbook-pivot'

const config = { name: 'ByRegion', sourceSheetName: 'Sheet1', sourceTableName: 'Sales', sourceRange: 'A1:B3', targetSheetName: 'Sheet1', targetCell: 'E1', rowFields: ['Region'], columnFields: [], values: [{ field: 'Amount', agg: 'sum' as const }] }
async function source() {
  const rows = [['Region', 'Amount'], ['East', 10], ['West', 20]]
  const bytes = await applyCellEdits(await createBlankWorkbook(), rows.flatMap((row, r) => row.map((value, c) => ({ sheetName: 'Sheet1', row: r, column: c, writeValue: true, cell: { value } }))))
  return applyWorkbookOperations(bytes, [{ kind: 'applyTableAdditions', additions: [{ worksheetSheetName: 'Sheet1', area: { startRow: 0, startColumn: 0, endRow: 2, endColumn: 1 }, name: 'Sales', columnNames: ['Region', 'Amount'], style: 'TableStyleMedium4', bandedRows: true }] }])
}

it('creates a dynamic pivot from a mixed-case table reference and persists the actual table identity', async () => {
  const bytes = await source(), snapshot = bytes.slice()
  const plan = await createPivotPlan(bytes, { ...config, sourceTableName: 'sAlEs', sourceRange: 'Z1:Z2' })
  const saved = await applyWorkbookOperations(bytes, plan.operations), pivot = (await readWorkbookPivots(saved))[0]!
  expect(bytes).toEqual(snapshot)
  expect(pivot).toMatchObject({ sourceTableName: 'Sales', sourceRange: 'A1:B3' })
  expect(pivot.readonlyReason).toBeUndefined()
  expect(await (await createBufferEntrySource(saved)).readText(pivot.cachePath)).toContain('name="Sales"')
  expect((await readWorkbook(saved)).sheets[0]!.cells.F4?.value).toBe(30)
})

it('resolves a mixed-case table reference in the save engine without relying on the frontend planner', async () => {
  const bytes = await source(), plan = await createPivotPlan(bytes, config)
  const saved = await applyWorkbookOperations(bytes, [{ kind: 'addPivot', addition: { ...plan.addition, sourceTableName: 'sAlEs' } }])
  const pivot = (await readWorkbookPivots(saved))[0]!
  expect(pivot.sourceTableName).toBe('Sales')
  expect(await (await createBufferEntrySource(saved)).readText(pivot.cachePath)).toContain('name="Sales"')
})

it.each([true, false])('reopens and refreshes a grown named table with a case-variant reference (owned state: %s)', async owned => {
  const bytes = await source(), created = await applyWorkbookOperations(bytes, (await createPivotPlan(bytes, config)).operations)
  const original = (await readWorkbookPivots(created))[0]!, zip = await createBufferEntrySource(created)
  const tableXml = (await zip.readText(original.tablePath)).replace('&quot;sourceTableName&quot;:&quot;Sales&quot;', '&quot;sourceTableName&quot;:&quot;sAlEs&quot;')
  const imported = (await assemblePackage(created, {
    replaced: new Map([[original.tablePath, owned ? tableXml : tableXml.replace(/<ext uri="\{AIO-PIVOT-STATE\}"[\s\S]*?<\/ext>/, '')], [original.cachePath, (await zip.readText(original.cachePath)).replace('name="Sales"', 'name="sAlEs"')]]),
    added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [original.tablePath, original.cachePath],
  })).buffer
  const reopened = (await readWorkbookPivots(imported))[0]!
  expect(reopened.readonlyReason).toBeUndefined()
  expect(reopened.sourceTableName).toBe('Sales')
  const grown = await applyWorkbookOperations(imported, [
    { kind: 'applyCellEdits', edits: ['North', 40].map((value, column) => ({ sheetName: 'Sheet1', row: 3, column, writeValue: true, cell: { value } })) },
    { kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'sales', area: { startRow: 0, startColumn: 0, endRow: 3, endColumn: 1 } }] },
  ])
  const saved = await applyWorkbookOperations(grown, (await refreshWorkbookPivotsPlan(grown)).operations), after = (await readWorkbookPivots(saved))[0]!
  expect(after).toMatchObject({ tablePath: original.tablePath, sourceTableName: 'Sales', sourceRange: 'A1:B4' })
  expect((await readWorkbook(saved)).sheets[0]!.cells.F5?.value).toBe(70)
  expect(await (await createBufferEntrySource(saved)).readText(after.cachePath)).toContain('recordCount="3"')
})

it.each(['RenamedSales', 'SALES'])('keeps a renamed dynamic table source readable and refreshable: %s', async name => {
  const bytes = await source(), created = await applyWorkbookOperations(bytes, (await createPivotPlan(bytes, config)).operations)
  const before = (await readWorkbookPivots(created))[0]!, zip = await createBufferEntrySource(created)
  const renamed = await applyWorkbookOperations(created, [{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'sales', name }] }])
  const after = (await readWorkbookPivots(renamed))[0]!, result = await createBufferEntrySource(renamed)
  expect(after.readonlyReason).toBeUndefined()
  expect(after.sourceTableName).toBe(name)
  expect(await result.readText(after.cachePath)).toContain(`name="${name}"`)
  for (const path of await zip.paths()) {
    if (!['xl/tables/table1.xml', before.tablePath, before.cachePath].includes(path)) expect(await result.readText(path)).toBe(await zip.readText(path))
  }
  const changed = await applyCellEdits(renamed, [{ sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 50 } }])
  const saved = await applyWorkbookOperations(changed, (await refreshWorkbookPivotsPlan(changed)).operations)
  expect((await readWorkbook(saved)).sheets[0]!.cells.F4?.value).toBe(70)
})

it('applies consecutive source table renames against the current transaction state', async () => {
  const bytes = await source(), created = await applyWorkbookOperations(bytes, (await createPivotPlan(bytes, config)).operations)
  const renamed = await applyWorkbookOperations(created, [{ kind: 'applyTableEdits', edits: [
    { worksheetSheetName: 'Sheet1', tableName: 'Sales', name: 'CurrentSales' },
    { worksheetSheetName: 'Sheet1', tableName: 'CurrentSales', name: 'FinalSales' },
  ] }])
  const pivot = (await readWorkbookPivots(renamed))[0]!
  expect(pivot).toMatchObject({ sourceTableName: 'FinalSales' })
  expect(pivot.readonlyReason).toBeUndefined()
  expect(await (await createBufferEntrySource(renamed)).readText(pivot.cachePath)).toContain('name="FinalSales"')
})

it('keeps imported standard pivots bound when the source table is renamed', async () => {
  const bytes = await source(), created = await applyWorkbookOperations(bytes, (await createPivotPlan(bytes, config)).operations)
  const pivot = (await readWorkbookPivots(created))[0]!, zip = await createBufferEntrySource(created)
  const imported = (await assemblePackage(created, { replaced: new Map([[pivot.tablePath, (await zip.readText(pivot.tablePath)).replace(/<ext uri="\{AIO-PIVOT-STATE\}"[\s\S]*?<\/ext>/, '')]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [pivot.tablePath] })).buffer
  const renamed = await applyWorkbookOperations(imported, [{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Sales', name: 'ImportedSales' }] }])
  const after = (await readWorkbookPivots(renamed))[0]!
  expect(after.readonlyReason).toBeUndefined()
  expect(after.sourceTableName).toBe('ImportedSales')
  expect(await (await createBufferEntrySource(renamed)).readText(pivot.tablePath)).toBe(await (await createBufferEntrySource(imported)).readText(pivot.tablePath))
})

it('rejects conversion of a table still used as a dynamic pivot source without changing the input', async () => {
  const bytes = await source(), created = await applyWorkbookOperations(bytes, (await createPivotPlan(bytes, config)).operations), snapshot = created.slice()
  await expect(applyWorkbookOperations(created, [{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'sAlEs', remove: true }] }])).rejects.toThrow('透视表')
  expect(created).toEqual(snapshot)
})

it.each([true, false])('rejects hiding a dynamic source header before saving (owned state: %s)', async owned => {
  const bytes = await source(), created = await applyWorkbookOperations(bytes, (await createPivotPlan(bytes, config)).operations)
  const pivot = (await readWorkbookPivots(created))[0]!, zip = await createBufferEntrySource(created)
  const input = owned ? created : (await assemblePackage(created, { replaced: new Map([[pivot.tablePath, (await zip.readText(pivot.tablePath)).replace(/<ext uri="\{AIO-PIVOT-STATE\}"[\s\S]*?<\/ext>/, '')]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [pivot.tablePath] })).buffer
  const snapshot = input.slice()
  await expect(applyWorkbookOperations(input, [{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'sAlEs', headerRow: false }] }])).rejects.toThrow('不能关闭标题行')
  expect(input).toEqual(snapshot)
  expect((await readWorkbookPivots(input))[0]!.readonlyReason).toBeUndefined()
})

it('rejects a header removal after a source rename in the same transaction', async () => {
  const bytes = await source(), created = await applyWorkbookOperations(bytes, (await createPivotPlan(bytes, config)).operations), snapshot = created.slice()
  await expect(applyWorkbookOperations(created, [{ kind: 'applyTableEdits', edits: [
    { worksheetSheetName: 'Sheet1', tableName: 'Sales', name: 'CurrentSales' },
    { worksheetSheetName: 'Sheet1', tableName: 'CurrentSales', headerRow: false },
  ] }])).rejects.toThrow('不能关闭标题行')
  expect(created).toEqual(snapshot)
})

it('allows ordinary table headers and fixed-range pivot sources to be hidden', async () => {
  const bytes = await source(), fixed = await applyWorkbookOperations(bytes, (await createPivotPlan(bytes, { ...config, sourceTableName: undefined })).operations)
  for (const input of [bytes, fixed]) {
    const saved = await applyWorkbookOperations(input, [{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Sales', headerRow: false }] }])
    expect((await readWorkbook(saved)).sheets[0]!.tables![0]!.headerRowCount).toBe(0)
  }
})

it('allows keeping the header and changing style on a dynamic source table', async () => {
  const bytes = await source(), created = await applyWorkbookOperations(bytes, (await createPivotPlan(bytes, config)).operations)
  const saved = await applyWorkbookOperations(created, [{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Sales', headerRow: true, bandedRows: false }] }])
  expect((await readWorkbookPivots(saved))[0]!.readonlyReason).toBeUndefined()
  expect((await readWorkbook(saved)).sheets[0]!.tables![0]!.headerRowCount).toBe(1)
})

it.each([true, false])('rejects cached field removal and unsupported renames (owned state: %s)', async owned => {
  const bytes = await source(), created = await applyWorkbookOperations(bytes, (await createPivotPlan(bytes, config)).operations)
  const pivot = (await readWorkbookPivots(created))[0]!, zip = await createBufferEntrySource(created)
  const input = owned ? created : (await assemblePackage(created, { replaced: new Map([[pivot.tablePath, (await zip.readText(pivot.tablePath)).replace(/<ext uri="\{AIO-PIVOT-STATE\}"[\s\S]*?<\/ext>/, '')]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [pivot.tablePath] })).buffer
  const snapshot = input.slice()
  for (const edit of [
    ...(!owned ? [{ columnNames: ['Region', 'Revenue'] }, { columnNames: ['Amount', 'Region'] }] : []),
    { columnNames: ['Region'], area: { startRow: 0, startColumn: 0, endRow: 2, endColumn: 0 } },
  ]) {
    await expect(applyWorkbookOperations(input, [{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'sales', ...edit }] }])).rejects.toThrow('透视')
    expect(input).toEqual(snapshot)
  }
})

it('allows undoing a newly added column not yet used by the pivot cache', async () => {
  const bytes = await source(), created = await applyWorkbookOperations(bytes, (await createPivotPlan(bytes, config)).operations)
  const grown = await applyWorkbookOperations(created, [{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Sales', area: { startRow: 0, startColumn: 0, endRow: 2, endColumn: 2 }, columnNames: ['Region', 'Amount', 'Unused'] }] }])
  const restored = await applyWorkbookOperations(grown, [{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Sales', area: { startRow: 0, startColumn: 0, endRow: 2, endColumn: 1 }, columnNames: ['Region', 'Amount'] }] }])
  expect((await readWorkbookPivots(restored))[0]!.readonlyReason).toBeUndefined()
  const refreshed = await applyWorkbookOperations(restored, (await refreshWorkbookPivotsPlan(restored)).operations)
  expect((await readWorkbook(refreshed)).sheets[0]!.cells.F4?.value).toBe(30)
})

it('refuses a source rename when private pivot state and the standard cache disagree', async () => {
  const bytes = await source(), created = await applyWorkbookOperations(bytes, (await createPivotPlan(bytes, config)).operations)
  const pivot = (await readWorkbookPivots(created))[0]!, zip = await createBufferEntrySource(created)
  const corrupt = (await assemblePackage(created, { replaced: new Map([[pivot.cachePath, (await zip.readText(pivot.cachePath)).replace('name="Sales"', 'name="OtherSales"')]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [pivot.cachePath] })).buffer
  const snapshot = corrupt.slice()
  await expect(applyWorkbookOperations(corrupt, [{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Sales', name: 'CurrentSales' }] }])).rejects.toThrow('来源与缓存归属不一致')
  expect(corrupt).toEqual(snapshot)
})

it('preserves owned native controls when renaming their dynamic source table', async () => {
  const bytes = await source(), created = await applyWorkbookOperations(bytes, (await createPivotPlan(bytes, config)).operations)
  const pivot = (await readWorkbookPivots(created))[0]!
  const controlled = await applyWorkbookOperations(created, [{ kind: 'upsertPivotControl', request: { kind: 'slicer', tablePath: pivot.tablePath, field: 'Region', name: 'SourceRegion' } }])
  const renamed = await applyWorkbookOperations(controlled, [{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Sales', name: 'CurrentSales' }] }])
  const before = await createBufferEntrySource(controlled), after = await createBufferEntrySource(renamed)
  expect((await readWorkbookPivots(renamed))[0]!.readonlyReason).toBeUndefined()
  for (const path of await before.paths()) {
    if (/^xl\/(?:slicers|slicerCaches|drawings)\//.test(path)) expect(await after.readText(path)).toBe(await before.readText(path))
  }
})
