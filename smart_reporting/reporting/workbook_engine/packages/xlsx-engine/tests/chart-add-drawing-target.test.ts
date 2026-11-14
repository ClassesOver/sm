import { expect, it } from 'vitest'
import { applyChartAdditions, createBlankWorkbook, type ChartAddition } from '../src'
import { assemblePackage, createBufferEntrySource, inventoryXlsx } from '../src/zip'

const sheetRels = 'xl/worksheets/_rels/sheet1.xml.rels'
const drawing = 'xl/drawings/drawing1.xml'
const addition: ChartAddition = { worksheetSheetName: 'Sheet1',
  anchor: { fromRow: 1, fromColumn: 3, toRow: 15, toColumn: 11, fromRowOffset: 0, fromColumnOffset: 0, toRowOffset: 0, toColumnOffset: 0 },
  chart: { chartType: 'column', title: 'Keep original', series: [{ name: 'Amount', categories: ['Q1', 'Q2'], values: [10, 20], valuesRef: 'Sheet1!$B$2:$B$3' }] } }
async function fixture(target: string, mode?: string) {
  const bytes = await applyChartAdditions(await createBlankWorkbook(), [addition]), source = await createBufferEntrySource(bytes)
  const xml = (await source.readText(sheetRels)).replace('Target="../drawings/drawing1.xml"', `Target="${target}"${mode ? ` TargetMode="${mode}"` : ''}`)
  return (await assemblePackage(bytes, { replaced: new Map([[sheetRels, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [sheetRels] })).buffer
}
it.each(['../drawings/drawing1.xml', '/xl/drawings/drawing1.xml'])('adds to an existing drawing using legal OPC target %s while preserving original chart and anchor', async target => {
  const bytes = await fixture(target), before = await createBufferEntrySource(bytes)
  const changed = await applyChartAdditions(bytes, [{ ...addition, chart: { ...addition.chart, chartType: 'line', title: 'New recommendation' } }]), after = await createBufferEntrySource(changed)
  expect(await after.readText('xl/charts/chart1.xml')).toBe(await before.readText('xl/charts/chart1.xml'))
  const originalAnchor = (await before.readText(drawing)).match(/<xdr:twoCellAnchor\b[\s\S]*?<\/xdr:twoCellAnchor>/)![0]
  expect(await after.readText(drawing)).toContain(originalAnchor)
  expect(await after.has('xl/charts/chart2.xml')).toBe(true)
  expect(await after.has('xl/drawings/drawing2.xml')).toBe(false)
  const allowed = new Set(['[Content_Types].xml', drawing, 'xl/drawings/_rels/drawing1.xml.rels'])
  const hashes = new Map((await inventoryXlsx(changed)).map(item => [item.path, item.sha256]))
  for (const entry of await inventoryXlsx(bytes)) if (!allowed.has(entry.path)) expect(hashes.get(entry.path), entry.path).toBe(entry.sha256)
})
it.each([
  { target: '../drawings/drawing1.xml', mode: 'External' },
  { target: 'https://example.invalid/drawing1.xml' },
  { target: '//example.invalid/drawing1.xml' },
  { target: '../../../xl/drawings/drawing1.xml' },
  { target: '/../../xl/drawings/drawing1.xml' },
])('rejects unsafe drawing relationship before writing: $target $mode', async ({ target, mode }) => {
  const bytes = await fixture(target, mode), original = bytes.slice()
  await expect(applyChartAdditions(bytes, [addition])).rejects.toThrow()
  expect(bytes).toEqual(original)
})
