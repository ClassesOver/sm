import { expect, it } from 'vitest'
import { applyCellEdits, createBlankWorkbook, createBufferEntrySource, readWorkbook, formatAddress } from '@sheets-web/xlsx-engine'
import { assemblePackage } from '@sheets-web/xlsx-engine/zip'
import { readPivotState } from '@sheets-web/xlsx-engine/pivot-add'
import { readPivotControls } from '@sheets-web/xlsx-engine/pivot-controls'
import { planPivotTableFieldRename } from '@sheets-web/xlsx-engine/pivot-source-field-rename'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createPivotPlan, readWorkbookPivots, refreshWorkbookPivotsPlan } from './workbook-pivot'

async function fixture(timelines = false) {
  const rows = [['Region', 'Date', 'Delivery', 'Amount'], ['East', 45292, 45296, 10], ['West', 45306, 45311, 20], ['East', 45323, 45327, 30]]
  const source = await applyCellEdits(await createBlankWorkbook(), rows.flatMap((row, r) => row.map((value, column) => ({ sheetName: 'Sheet1', row: r, column, writeValue: true, cell: { value }, ...(r && (column === 1 || column === 2) ? { style: { numberFormat: 'yyyy-mm-dd' } } : {}) }))))
  const table = await applyWorkbookOperations(source, [{ kind: 'applyTableAdditions', additions: [{ worksheetSheetName: 'Sheet1', area: { startRow: 0, startColumn: 0, endRow: 3, endColumn: 3 }, name: 'Sales', columnNames: rows[0] }] }])
  const plan = await createPivotPlan(table, { name: 'Report', sourceSheetName: 'Sheet1', sourceTableName: 'Sales', sourceRange: 'A1:D4', targetSheetName: 'Sheet1', targetCell: 'H1', rowFields: ['Region'], columnFields: ['Date', 'Delivery'], values: [{ field: 'Amount', agg: 'sum' }], hiddenMembers: { row: [['West']], column: timelines ? [['45323'], ['45327']] : [[], []] } })
  const pivot = await applyWorkbookOperations(table, plan.operations), tablePath = (await readWorkbookPivots(pivot))[0]!.tablePath
  return applyWorkbookOperations(pivot, [
    { kind: 'upsertPivotControl', request: { kind: 'slicer', tablePath, field: 'Region', name: 'Regions', anchor: { row: 9, column: 8, width: 224, height: 180 } } },
    ...(timelines ? [
      { kind: 'upsertPivotControl', request: { kind: 'timeline', tablePath, field: 'Date', name: 'Dates', from: '2024-01-01', to: '2024-01-31', anchor: { row: 15, column: 8, width: 480, height: 160 } } },
      { kind: 'upsertPivotControl', request: { kind: 'timeline', tablePath, field: 'Delivery', name: 'Deliveries', caption: '发货区间', from: '2024-01-01', to: '2024-01-31', anchor: { row: 22, column: 8, width: 500, height: 180 } } },
    ] : []),
  ])
}
const rename = (names: string[]) => ({ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Sales', columnNames: names }] })
const headers = (names: string[]) => ({ kind: 'applyCellEdits', edits: names.map((value, column) => ({ sheetName: 'Sheet1', row: 0, column, writeValue: true, cell: { value } })) })

it('renames an owned slicer field and its default caption without changing selections, output or unrelated parts', async () => {
  const input = await fixture(), pivot = (await readWorkbookPivots(input))[0]!, before = await createBufferEntrySource(input), original = (await readPivotControls(input))[0]!
  const names = ['Area & Sales', 'Date', 'Delivery', 'Revenue'], saved = await applyWorkbookOperations(input, [headers(names), rename(names)]), after = await createBufferEntrySource(saved)
  expect(await readPivotControls(saved)).toEqual([{ ...original, field: names[0] }])
  expect(await after.readText(original.cachePath)).toContain('sourceName="Area &amp; Sales"')
  expect(await after.readText(original.partPath)).toContain('caption="Area &amp; Sales"')
  expect(await after.readText('xl/drawings/drawing1.xml')).toContain('Area &amp; Sales（需要支持原生控件的 Excel）')
  const previous = readPivotState(await before.readText(pivot.tablePath))!, current = readPivotState(await after.readText(pivot.tablePath))!
  expect(current.manualHiddenMembers).toEqual(previous.manualHiddenMembers)
  const left = (await readWorkbook(input)).sheets[0]!, right = (await readWorkbook(saved)).sheets[0]!
  for (let row = pivot.location.startRow; row <= pivot.location.endRow; row++) for (let column = pivot.location.startColumn; column <= pivot.location.endColumn; column++) expect(right.cells[formatAddress(row, column)]).toEqual(left.cells[formatAddress(row, column)])
  for (const path of await before.paths()) if (![pivot.tablePath, pivot.cachePath, original.partPath, original.cachePath, 'xl/drawings/drawing1.xml', 'xl/tables/table1.xml', 'xl/worksheets/sheet1.xml'].includes(path)) expect(await after.readText(path)).toBe(await before.readText(path))
  expect((await readWorkbookPivots(saved))[0]!.readonlyReason).toBeUndefined()
})

it('migrates two timelines simultaneously, retaining custom captions, typed dates, filters and refresh selection', async () => {
  const input = await fixture(true), pivot = (await readWorkbookPivots(input))[0]!, before = await createBufferEntrySource(input), controls = await readPivotControls(input)
  const names = ['Area', 'Delivery', 'Date', 'Revenue'], saved = await applyWorkbookOperations(input, [headers(names), rename(names)]), after = await createBufferEntrySource(saved)
  expect(await readPivotControls(saved)).toEqual(controls.map(control => ({ ...control, field: control.field === 'Region' ? 'Area' : control.field === 'Date' ? 'Delivery' : 'Date' })))
  expect(await after.readText(controls[2]!.partPath)).toContain('caption="发货区间"')
  expect((await after.readText(pivot.cachePath)).match(/<d v=/g)).toHaveLength(6)
  expect((await after.readText(pivot.tablePath)).match(/<filters count="2">[\s\S]*?<\/filters>/)?.[0]).toBe((await before.readText(pivot.tablePath)).match(/<filters count="2">[\s\S]*?<\/filters>/)?.[0])
  const refreshed = await applyWorkbookOperations(saved, (await refreshWorkbookPivotsPlan(saved)).operations), view = (await readWorkbookPivots(refreshed))[0]!
  expect(await readPivotControls(refreshed)).toEqual(await readPivotControls(saved))
  const model = (await readWorkbook(refreshed)).sheets[0]!
  expect(model.cells[formatAddress(view.location.endRow, view.location.endColumn)]?.value).toBe(10)
})

it('uses the current overlay when multiple controlled field renames are saved together', async () => {
  const input = await fixture(true), names = ['FinalArea', 'FinalDate', 'Delivery', 'Amount']
  const saved = await applyWorkbookOperations(input, [headers(names), { kind: 'applyTableEdits', edits: [...rename(['Area', 'OrderDate', 'Delivery', 'Amount']).edits, ...rename(names).edits] }])
  expect((await readPivotControls(saved)).map(control => control.field)).toEqual(['FinalArea', 'FinalDate', 'Delivery'])
})

it('rejects damaged or unknown native control graphs and retains the input bytes', async () => {
  const input = await fixture(true), source = await createBufferEntrySource(input), path = 'xl/timelineCaches/timelineCache1.xml'
  const damaged = (await assemblePackage(input, { replaced: new Map([[path, (await source.readText(path)).replace('sourceName="Date"', 'sourceName="Missing"')]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
  const unknown = (await assemblePackage(input, { replaced: new Map(), added: new Map([['xl/slicerCaches/unknown.xml', '<unknown/>']]), addedBinary: new Map(), removedEntries: [], addedEntries: ['xl/slicerCaches/unknown.xml'], touchedEntries: [] })).buffer
  for (const bytes of [damaged, unknown]) { const copy = bytes.slice();await expect(applyWorkbookOperations(bytes, [rename(['Area', 'OrderDate', 'Delivery', 'Amount'])])).rejects.toThrow();expect(bytes).toEqual(copy) }
})

it.each([
  '<Relationship Id="rIdExtra" Type="urn:test:owner" Target="/xl/slicerCaches/slicerCache1.xml"/>',
  '<Relationship Id="rIdExtra" Type="urn:test:owner" Target="/xl/slicerCaches/slicerCache1.xml"></Relationship>',
  `<Relationship Id='rIdExtra' Type='urn:test:owner' Target = '/xl/slicerCaches/slicerCache1.xml'/>`,
  '<p:Relationship xmlns:p="http://schemas.openxmlformats.org/package/2006/relationships" Id="rIdExtra" Type="urn:test:owner" Target="/xl/slicerCaches/slicerCache%31.xml"/>',
])('rejects an extra owner of a native control cache before changing its field identity: %s', async relationship => {
  const input = await fixture(), source = await createBufferEntrySource(input), path = 'xl/_rels/workbook.xml.rels'
  const xml = (await source.readText(path)).replace('</Relationships>', relationship + '</Relationships>')
  const shared = (await assemblePackage(input, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
  const copy = shared.slice()
  await expect(planPivotTableFieldRename(shared, { aliases: ['Sales'], sheetName: 'Sheet1', startColumn: 0, beforeNames: ['Region', 'Date', 'Delivery', 'Amount'], afterNames: ['Region', 'Date', 'Delivery', 'Amount'] })).rejects.toThrow('其他关系引用')
  await expect(applyWorkbookOperations(shared, [rename(['Area', 'Date', 'Delivery', 'Amount'])])).rejects.toThrow('其他关系引用')
  expect(shared).toEqual(copy)
})

it('ignores commented relationship decoys while retaining them unchanged', async () => {
  const input = await fixture(), source = await createBufferEntrySource(input), path = 'xl/_rels/workbook.xml.rels'
  const xml = (await source.readText(path)).replace('</Relationships>', '<!-- <Relationship Id="rIdExtra" Type="urn:test:owner" Target="/xl/slicerCaches/slicerCache1.xml"/> --></Relationships>')
  const annotated = (await assemblePackage(input, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
  const names = ['Area', 'Date', 'Delivery', 'Amount'], saved = await applyWorkbookOperations(annotated, [headers(names), rename(names)])
  expect((await readPivotControls(saved))[0]!.field).toBe('Area')
  expect(await (await createBufferEntrySource(saved)).readText(path)).toBe(xml)
})

it('preserves unrelated external URI octets without treating them as local control owners', async () => {
  const input = await fixture(), source = await createBufferEntrySource(input), path = 'xl/_rels/workbook.xml.rels'
  const xml = (await source.readText(path)).replace('</Relationships>', '<Relationship Id="rIdLink" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com/%FF" TargetMode="External"/></Relationships>')
  const linked = (await assemblePackage(input, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
  const names = ['Area', 'Date', 'Delivery', 'Amount'], saved = await applyWorkbookOperations(linked, [headers(names), rename(names)])
  expect((await readPivotControls(saved))[0]!.field).toBe('Area')
  expect(await (await createBufferEntrySource(saved)).readText(path)).toBe(xml)
})
