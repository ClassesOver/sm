import JSZip from 'jszip'
import { expect, it } from 'vitest'
import { mkdir, writeFile } from 'node:fs/promises'
import { applyChartAdditions } from '../src/chart-add'
import { applyChartEdits } from '../src/rules'
import { createBlankWorkbook } from '../src/blank'
import { readWorkbook } from '../src/workbook-read'
import type { ChartEditLean } from '../src/chart-edit'

const path = 'xl/charts/chart1.xml'
const title = (text: string) => `<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>${text}</a:t></a:r></a:p></c:rich></c:tx><c:overlay val="0"/></c:title>`
const axis = (id: number, cross: number, side: string, text: string, units = '', grid = false) =>
  `<c:valAx><c:axId val="${id}"/><c:scaling><c:orientation val="minMax"/><c:max val="${id === 101 ? 8 : 8000}"/><c:min val="0"/></c:scaling><c:delete val="0"/><c:axPos val="${side}"/>${grid ? '<c:majorGridlines/>' : ''}${title(text)}<c:numFmt formatCode="0.0" sourceLinked="0"/><c:crossAx val="${cross}"/><c:majorUnit val="${id === 101 ? 2 : 2000}"/>${units}<c:extLst><c:ext uri="axes-test"><v:keep xmlns:v="urn:scatter-axes" id="${id}"/></c:ext></c:extLst></c:valAx>`

async function fixture(reverse = false, unitsX = '', unitsY = '') {
  const bytes = await applyChartAdditions(await createBlankWorkbook(), [{ worksheetSheetName: 'Sheet1',
    anchor: { fromRow: 0, fromColumn: 3, fromRowOffset: 0, fromColumnOffset: 0, toRow: 10, toColumn: 12, toRowOffset: 0, toColumnOffset: 0 },
    chart: { chartType: 'scatter', title: 'Axes', series: [{ name: 'Y', values: [2000, 6000], valuesRef: 'Sheet1!B2:B3', categories: ['2', '6'] }] },
  }])
  const zip = await JSZip.loadAsync(bytes)
  let xml = await zip.file(path)!.async('string')
  xml = xml.replace(/(<c:scatterChart>[\s\S]*?<c:axId val=")[^"]+("\/><c:axId val=")[^"]+("\/><\/c:scatterChart>)/, '$1101$2202$3')
  const x = axis(101, 202, 'b', 'X source', unitsX, true), y = axis(202, 101, 'l', 'Y source', unitsY)
  xml = xml.replace(/<c:valAx>[\s\S]*<\/c:valAx>/, reverse ? y + '<!-- between axes -->' + x : x + '<!-- between axes -->' + y)
  zip.file(path, xml)
  return zip.generateAsync({ type: 'uint8array' })
}

async function xmlOf(bytes: Uint8Array) { return (await JSZip.loadAsync(bytes)).file(path)!.async('string') }
async function withXml(bytes: Uint8Array, xml: string) { const zip = await JSZip.loadAsync(bytes); zip.file(path, xml); return zip.generateAsync({ type: 'uint8array' }) }
async function chartOf(bytes: Uint8Array) { return (await readWorkbook(bytes)).sheets[0]!.charts![0]! }
const axisOf = (xml: string, id: number) => [...xml.matchAll(/<c:valAx\b[^>]*>[\s\S]*?<\/c:valAx>/g)].find(match => match[0].includes(`<c:axId val="${id}"/>`))![0]

it.each([false, true])('hydrates scatter design and per-axis state by plot axId when reverse=%s', async reverse => {
  const bytes = await fixture(reverse, '<c:dispUnits><c:builtInUnit val="hundreds"/></c:dispUnits>', '<c:dispUnits><c:builtInUnit val="thousands"/><c:dispUnitsLbl/></c:dispUnits>')
  const chart = await chartOf(bytes)
  expect(chart.axes?.category).toMatchObject({ id: 101, title: 'X source', majorGridlines: true, displayUnit: 100 })
  expect(chart.axes?.value).toMatchObject({ id: 202, title: 'Y source', majorGridlines: false, displayUnit: 1000, displayUnitLabel: 'Thousands' })
  expect(chart.axes?.category).not.toHaveProperty('displayUnitLabel')
  expect(chart.design).toMatchObject({ axisTitles: { category: 'X source', value: 'Y source' }, gridlines: false })
})

it.each([
  ['hundreds', 100, 'Hundreds'], ['thousands', 1000, 'Thousands'], ['tenThousands', 1e4, 'x 10000'],
  ['hundredThousands', 1e5, 'x 100000'], ['millions', 1e6, 'Millions'], ['tenMillions', 1e7, 'x 10000000'],
  ['hundredMillions', 1e8, 'x 100000000'], ['billions', 1e9, 'Billions'], ['trillions', 1e12, 'Trillions'],
])('reads source built-in display unit %s', async (unit, divisor, label) => {
  const chart = await chartOf(await fixture(false, '', `<c:dispUnits><c:builtInUnit val="${unit}"/><c:custUnit val="7"/><c:dispUnitsLbl/></c:dispUnits>`))
  expect(chart.axes?.value).toMatchObject({ displayUnit: divisor, displayUnitLabel: label })
})

it.each([
  ['<c:custUnit val="2.5"/>', '<c:dispUnitsLbl><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Custom &amp; units</a:t></a:r></a:p></c:rich></c:tx></c:dispUnitsLbl>', 2.5, 'Custom & units'],
  ['<c:builtInUnit val="millions"/>', '<c:dispUnitsLbl><c:tx><c:rich><a:p><a:r><a:t>万元</a:t></a:r></a:p></c:rich></c:tx></c:dispUnitsLbl>', 1e6, '万元'],
  ['<c:builtInUnit val="unknown"/><c:custUnit val="4"/>', '<c:dispUnitsLbl/>', 4, undefined],
  ['<c:custUnit val="0"/>', '<c:dispUnitsLbl/>', undefined, undefined],
  ['<c:custUnit val="-2"/>', '<c:dispUnitsLbl/>', undefined, undefined],
  ['<c:custUnit val="NaN"/>', '<c:dispUnitsLbl/>', undefined, undefined],
  ['<c:custUnit val="Infinity"/>', '<c:dispUnitsLbl/>', undefined, undefined],
  ['<c:builtInUnit val="thousands"/>', '', 1000, undefined],
])('reads unit/label boundaries %s %s', async (unit, labelXml, divisor, label) => {
  const chart = await chartOf(await fixture(false, '', `<c:dispUnits>${unit}${labelXml}</c:dispUnits>`))
  expect(chart.axes?.value?.displayUnit).toBe(divisor)
  expect(chart.axes?.value?.displayUnitLabel).toBe(label)
})

it.each([
  ['X title', { axisTitles: { category: 'X changed & 汉字' } }, 101],
  ['Y title', { axisTitles: { value: 'Y changed' } }, 202],
  ['Y grid', { gridlines: true }, 202],
  ['Y bounds', { valueAxis: { min: -1000, max: 9000 } }, 202],
] as const)('edits only the intended scatter axis for %s and preserves every other part', async (_name, edit, id) => {
  for (const reverse of [false, true]) {
    const before = await fixture(reverse, '', '<c:dispUnits><c:builtInUnit val="thousands"/><c:dispUnitsLbl/></c:dispUnits>'), original = await xmlOf(before)
    const after = await applyChartEdits(before, [{ chartPath: path, ...edit }]), xml = await xmlOf(after)
    expect(axisOf(xml, id === 101 ? 202 : 101)).toBe(axisOf(original, id === 101 ? 202 : 101))
    expect(xml.replace(axisOf(xml, id), 'TARGET')).toBe(original.replace(axisOf(original, id), 'TARGET'))
    const chart = await chartOf(after)
    if ('axisTitles' in edit) expect(chart.design?.axisTitles?.[id === 101 ? 'category' : 'value']).toBe(Object.values(edit.axisTitles)[0])
    if ('gridlines' in edit) expect(chart.axes?.value).toMatchObject({ majorGridlines: true, displayUnit: 1000, displayUnitLabel: 'Thousands' })
    if ('valueAxis' in edit) expect(chart.axes?.value?.scaling).toMatchObject({ min: -1000, max: 9000, majorUnit: 2000 })
    const source = await JSZip.loadAsync(before), saved = await JSZip.loadAsync(after)
    expect(Object.keys(saved.files).sort()).toEqual(Object.keys(source.files).sort())
    for (const [name, file] of Object.entries(source.files)) if (!file.dir && name !== path) expect(await saved.file(name)!.async('uint8array')).toEqual(await file.async('uint8array'))
  }
})

it('roundtrips reset bounds, removed titles and gridlines with schema order and unit preservation', async () => {
  const bytes = await fixture(false, '', '<c:dispUnits><c:builtInUnit val="thousands"/><c:dispUnitsLbl/></c:dispUnits>')
  const first = await applyChartEdits(bytes, [{ chartPath: path, axisTitles: { category: 'New X', value: 'New Y' }, gridlines: true, valueAxis: { min: -1, max: 1e4 } }])
  const after = await applyChartEdits(first, [{ chartPath: path, axisTitles: { category: null, value: null }, gridlines: false, valueAxis: { min: null, max: null } }])
  const chart = await chartOf(after), xml = await xmlOf(first)
  expect(chart.design).toMatchObject({ axisTitles: { category: '', value: '' }, gridlines: false })
  expect(chart.axes?.value?.scaling).toMatchObject({ majorUnit: 2000 })
  expect(chart.axes?.value?.scaling).not.toHaveProperty('min')
  expect(chart.axes?.value?.scaling).not.toHaveProperty('max')
  expect(chart.axes?.value?.displayUnitLabel).toBe('Thousands')
  const y = axisOf(xml, 202)
  expect(y.indexOf('<c:axPos')).toBeLessThan(y.indexOf('<c:majorGridlines'))
  expect(y.indexOf('<c:majorGridlines')).toBeLessThan(y.indexOf('<c:title'))
  expect(y.indexOf('<c:title')).toBeLessThan(y.indexOf('<c:numFmt'))
  expect(y.indexOf('<c:max')).toBeLessThan(y.indexOf('<c:min'))
  if (process.env.SCATTER_AXES_EVIDENCE_DIRECTORY) {
    const directory = process.env.SCATTER_AXES_EVIDENCE_DIRECTORY
    await mkdir(directory, { recursive: true })
    await writeFile(`${directory}/scatter-axes-edited.xml`, xml)
    await writeFile(`${directory}/scatter-axes-reset.xml`, await xmlOf(after))
    await writeFile(`${directory}/scatter-axes-edited.xlsx`, first)
  }
})

it('preserves non-target prefix aliases and comments during scatter axis edits', async () => {
  const bytes = await fixture(), original = await xmlOf(bytes)
  const x = axisOf(original, 101).replaceAll('c:', 'x:').replace('<x:valAx>', '<x:valAx xmlns:x="http://schemas.openxmlformats.org/drawingml/2006/chart">')
  const y = axisOf(original, 202).replaceAll('c:', 'y:').replace('<y:valAx>', '<y:valAx xmlns:y="http://schemas.openxmlformats.org/drawingml/2006/chart">').replace('<y:axPos val="l"/>', '<y:axPos val="l"/><!-- keep Y title slot -->')
  const raw = original.replace(axisOf(original, 101), x).replace(axisOf(original, 202), y)
  const after = await applyChartEdits(await withXml(bytes, raw), [{ chartPath: path, axisTitles: { value: 'Y aliased' }, gridlines: true, valueAxis: { max: 9000 } }])
  const saved = await xmlOf(after)
  expect(saved).toContain(x)
  expect(saved).toContain('<!-- between axes -->')
  expect(saved).toContain('<!-- keep Y title slot -->')
  expect(saved).toContain('<y:valAx xmlns:y=')
  expect(saved).toContain('<y:majorGridlines/>')
  expect(await chartOf(after)).toMatchObject({ design: { axisTitles: { category: 'X source', value: 'Y aliased' }, gridlines: true } })
})

it.each([
  ['missing ID', (xml: string) => xml.replace('<c:axId val="202"/></c:scatterChart>', '</c:scatterChart>')],
  ['duplicate plot ID', (xml: string) => xml.replace('<c:axId val="202"/></c:scatterChart>', '<c:axId val="101"/></c:scatterChart>')],
  ['duplicate axis ID', (xml: string) => xml.replace('<c:valAx><c:axId val="202"/>', '<c:valAx><c:axId val="101"/>')],
  ['duplicate axis ID child', (xml: string) => xml.replace('<c:valAx><c:axId val="101"/>', '<c:valAx><c:axId val="101"/><c:axId val="101"/>')],
  ['duplicate crossAx child', (xml: string) => xml.replace('<c:crossAx val="101"/>', '<c:crossAx val="101"/><c:crossAx val="101"/>')],
  ['broken crossAx', (xml: string) => xml.replace('<c:crossAx val="101"/>', '<c:crossAx val="999"/>')],
  ['out of range ID', (xml: string) => xml.replaceAll('202', '4294967296')],
])('rejects scatter %s without fallback to the first value axis', async (_name, damage) => {
  const bytes = await fixture(), malformed = await withXml(bytes, damage(await xmlOf(bytes)))
  expect((await chartOf(malformed)).axes).toBeUndefined()
  expect((await chartOf(malformed)).design?.axisTitles?.value).toBeUndefined()
  expect((await chartOf(malformed)).design?.gridlines).toBeUndefined()
  for (const edit of [{ axisTitles: { category: 'No' } }, { axisTitles: { value: 'No' } }, { gridlines: true }, { valueAxis: { max: 10 } }] satisfies ChartEditLean[]) {
    await expect(applyChartEdits(malformed, [{ chartPath: path, ...edit }])).rejects.toThrow(/scatter.*ax|axis.*scatter/i)
  }
})

it('uses the source placeholder for a genuinely empty scatter title without replacing linked titles', async () => {
  const bytes = await fixture(), original = await xmlOf(bytes)
  const xml = original.replace(title('X source'), '<c:title/>').replace(title('Y source'), '<c:title><c:tx><c:strRef><c:f>Sheet1!A1</c:f><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>Linked Y</c:v></c:pt></c:strCache></c:strRef></c:tx></c:title>')
  const chart = await chartOf(await withXml(bytes, xml))
  expect(chart.axes?.category?.title).toBe('Axis Title')
  expect(chart.axes?.value).toMatchObject({ titleRef: 'Sheet1!A1', titleCache: 'Linked Y' })
  expect(chart.axes?.value?.title).toBeUndefined()
  expect(chart.design?.axisTitles).toEqual({ category: 'Axis Title', value: 'Linked Y' })
})

it.each(['<c:scaling/>', '<c:scaling></c:scaling>'])('expands %s and orders adjacent inserted bounds, grid and title', async scaling => {
  const bytes = await fixture(), original = await xmlOf(bytes)
  const y = axisOf(original, 202).replace(/<c:scaling>[\s\S]*?<\/c:scaling>/, scaling).replace(title('Y source'), '')
  const before = await withXml(bytes, original.replace(axisOf(original, 202), y))
  const after = await applyChartEdits(before, [{ chartPath: path, axisTitles: { value: 'With c: and a: literals' }, gridlines: true, valueAxis: { min: -2, max: 4 } }])
  const xml = await xmlOf(after)
  expect(axisOf(xml, 101)).toBe(axisOf(original, 101))
  expect(axisOf(xml, 202)).toContain('<c:scaling><c:max val="4"/><c:min val="-2"/></c:scaling>')
  expect(axisOf(xml, 202)).toContain('<c:axPos val="l"/><c:majorGridlines/><c:title>')
  expect((await chartOf(after)).design?.axisTitles?.value).toBe('With c: and a: literals')
})

it('edits default-namespace axes without touching prefixed non-target nodes', async () => {
  const bytes = await fixture(), original = await xmlOf(bytes)
  const raw = original.replace('xmlns:c=', 'xmlns=').replace(/(<\/?)(?:c:)/g, '$1')
  const after = await applyChartEdits(await withXml(bytes, raw), [{ chartPath: path, axisTitles: { value: 'Default Y' }, gridlines: true }])
  const xml = await xmlOf(after)
  expect(xml).not.toContain('<c:')
  expect(xml).toContain('<majorGridlines/>')
  expect(xml).toContain('<a:t>Default Y</a:t>')
  expect((await chartOf(after)).design).toMatchObject({ axisTitles: { category: 'X source', value: 'Default Y' }, gridlines: true })
})
