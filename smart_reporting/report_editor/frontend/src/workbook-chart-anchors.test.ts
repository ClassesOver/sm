import { expect, it } from 'vitest'
import { applyChartAdditions, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { assemblePackage, createBufferEntrySource, inventoryXlsx } from '@sheets-web/xlsx-engine/zip'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'

const from = { fromRow: 2, fromColumn: 3, fromRowOffset: 0, fromColumnOffset: 0, toRow: 10, toColumn: 9, toRowOffset: 0, toColumnOffset: 0 }
const next = { fromRow: 4, fromColumn: 5, fromRowOffset: 9525, fromColumnOffset: 19050, toRow: 12, toColumn: 11, toRowOffset: 9525, toColumnOffset: 19050 }
const drawingPath = 'xl/drawings/drawing1.xml'
async function fixture() {
  return applyChartAdditions(await createBlankWorkbook(), [0, 1].map(index => ({ worksheetSheetName: 'Sheet1', anchor: from,
    chart: { chartType: 'column' as const, title: `Chart ${index + 1}`, series: [{ name: 'Amount', values: [2], valuesRef: 'Sheet1!A1:A1', categories: ['Q1'] }] } })))
}
async function patch(bytes: Uint8Array, transform: (xml: string) => string, path = drawingPath) {
  const source = await createBufferEntrySource(bytes)
  return (await assemblePackage(bytes, { replaced: new Map([[path, transform(await source.readText(path, { preservePrefixes: true }))]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
}
const operation = (fields = {}) => ({ kind: 'applyChartAnchors', edits: [{ sheetName: 'Sheet1', chartPath: 'xl/charts/chart2.xml', mode: 'move', before: from, anchor: next, ...fields }] })

it('moves the exact chart path, preserves the other drawing object and all other package entry bytes', async () => {
  const bytes = await fixture(), source = await createBufferEntrySource(bytes)
  const original = await source.readText(drawingPath, { preservePrefixes: true })
  const originalFirst = original.match(/<xdr:twoCellAnchor\b[\s\S]*?<\/xdr:twoCellAnchor>/)![0]
  const changed = await applyWorkbookOperations(bytes, [operation()])
  const reopened = await readWorkbook(changed)
  expect(reopened.sheets[0]!.charts![0]!.anchor).toEqual(expect.objectContaining({ fromRow: 2, fromColumn: 3, toRow: 10, toColumn: 9 }))
  expect(reopened.sheets[0]!.charts![1]!.anchor).toEqual(next)
  expect(await (await createBufferEntrySource(changed)).readText(drawingPath, { preservePrefixes: true })).toContain(originalFirst)
  const before = await inventoryXlsx(bytes), after = await inventoryXlsx(changed)
  expect(after.filter(item => item.path !== drawingPath)).toEqual(before.filter(item => item.path !== drawingPath))
})

it('resizes a two-cell chart without changing the opposite marker or the chart part', async () => {
  const bytes = await fixture(), anchor = { ...from, fromRow: 3, fromColumnOffset: 9525 }
  const changed = await applyWorkbookOperations(bytes, [operation({ mode: 'resize', anchor })])
  expect({ ...from, ...(await readWorkbook(changed)).sheets[0]!.charts![1]!.anchor }).toEqual(anchor)
})

it.each(['xdr:', ''])('moves a one-cell chart with %s namespace while retaining its actual extent', async prefix => {
  let bytes = await fixture()
  bytes = await patch(bytes, xml => {
    let index = 0
    const next = xml.replace(/<xdr:twoCellAnchor\b[\s\S]*?<\/xdr:twoCellAnchor>/g, value => ++index !== 2 ? value
      : value.replace('twoCellAnchor', 'oneCellAnchor').replace('/xdr:twoCellAnchor', '/xdr:oneCellAnchor')
        .replace(/<xdr:to>[\s\S]*?<\/xdr:to>/, '<xdr:ext cx="914400" cy="609600"/>'))
    return prefix ? next : next.replaceAll('xdr:', '').replace('xmlns:xdr=', 'xmlns=')
  })
  const before = { ...from, toRow: 2, toColumn: 3, toRowOffset: 609600, toColumnOffset: 914400 }
  const changed = await applyWorkbookOperations(bytes, [operation({ before })])
  const xml = await (await createBufferEntrySource(changed)).readText(drawingPath, { preservePrefixes: true })
  expect(xml).toContain(`<${prefix}ext cx="914400" cy="609600"/>`)
  expect((await readWorkbook(changed)).sheets[0]!.charts![1]).toMatchObject({ anchorKind: 'oneCellAnchor', anchor: {
    fromRow: 4, fromColumn: 5, fromRowOffset: 9525, fromColumnOffset: 19050, toRow: 4, toColumn: 5, toRowOffset: 619125, toColumnOffset: 933450,
  } })
  await expect(applyWorkbookOperations(bytes, [operation({ before, mode: 'resize' })])).rejects.toThrow('单单元格锚点')
})

it('retains the source absolute-anchor limitation and does not turn it into a two-cell anchor', async () => {
  let bytes = await fixture()
  bytes = await patch(bytes, xml => {
    let index = 0
    return xml.replace(/<xdr:twoCellAnchor\b[\s\S]*?<\/xdr:twoCellAnchor>/g, value => ++index !== 2 ? value
      : value.replace('twoCellAnchor', 'absoluteAnchor').replace('/xdr:twoCellAnchor', '/xdr:absoluteAnchor')
        .replace(/<xdr:from>[\s\S]*?<\/xdr:from><xdr:to>[\s\S]*?<\/xdr:to>/, '<xdr:pos x="100" y="200"/><xdr:ext cx="914400" cy="609600"/>'))
  })
  expect((await readWorkbook(bytes)).sheets[0]!.charts![1]!.anchorKind).toBe('absoluteAnchor')
  const before = bytes.slice()
  await expect(applyWorkbookOperations(bytes, [operation()])).rejects.toThrow('绝对锚点')
  expect(bytes).toEqual(before)
})

it.each([
  { sheetName: 'Other' }, { chartPath: 'xl/charts/chart99.xml' }, { before: { ...from, fromRow: 7 } },
  { anchor: { ...next, fromRow: -1 } }, { anchor: { ...next, toColumn: 16384 } },
  { anchor: { ...next, fromRowOffset: Infinity } }, { anchor: { ...next, extra: 1 } },
])('rejects a foreign, stale or invalid anchor request: %j', async fields => {
  await expect(applyWorkbookOperations(await fixture(), [operation(fields)])).rejects.toThrow()
})

it('rejects a repeated relationship target rather than moving an arbitrary same-path chart', async () => {
  const bytes = await patch(await fixture(), xml => xml.replace('r:id="rId1"', 'r:id="rId2"'))
  await expect(applyWorkbookOperations(bytes, [operation()])).rejects.toThrow('图表锚点身份')
})
