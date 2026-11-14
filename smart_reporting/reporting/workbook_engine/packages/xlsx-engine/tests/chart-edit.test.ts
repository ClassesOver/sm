import { describe, expect, it } from 'vitest'

import { createBlankWorkbook, applyCellEdits, readWorkbook } from '../src'
import { applyChartEdits, listChartParts } from '../src/rules'
import { assemblePackage, createBufferEntrySource } from '../src/zip'

async function partOf(bytes: Uint8Array, path: string): Promise<string> {
  const source = await createBufferEntrySource(bytes)
  return source.readText(path)
}

/// A minimal but well-formed bar chart part over cached categories/values.
const CHART_XML =
  '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
  '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">' +
  '<c:chart>' +
  '<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Old</a:t></a:r></a:p></c:rich></c:tx><c:overlay val="0"/></c:title>' +
  '<c:autoTitleDeleted val="0"/>' +
  '<c:plotArea><c:layout/>' +
  '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/><c:varyColors val="0"/>' +
  '<c:ser><c:idx val="0"/><c:order val="0"/><c:tx><c:strRef><c:f>Sheet1!$B$1</c:f><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>Sales</c:v></c:pt></c:strCache></c:strRef></c:tx>' +
  '<c:cat><c:strRef><c:f>Sheet1!$A$2:$A$3</c:f><c:strCache><c:ptCount val="2"/><c:pt idx="0"><c:v>Q1</c:v></c:pt><c:pt idx="1"><c:v>Q2</c:v></c:pt></c:strCache></c:strRef></c:cat>' +
  '<c:val><c:numRef><c:f>Sheet1!$B$2:$B$3</c:f><c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="2"/><c:pt idx="0"><c:v>10</c:v></c:pt><c:pt idx="1"><c:v>20</c:v></c:pt></c:numCache></c:numRef></c:val>' +
  '</c:ser>' +
  '<c:axId val="111"/><c:axId val="222"/>' +
  '</c:barChart>' +
  '<c:catAx><c:axId val="111"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="b"/><c:crossAx val="222"/></c:catAx>' +
  '<c:valAx><c:axId val="222"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="l"/><c:crossAx val="111"/></c:valAx>' +
  '</c:plotArea>' +
  '</c:chart></c:chartSpace>'

async function buildChartWorkbook(): Promise<Uint8Array> {
  const blank = await createBlankWorkbook()
  const seeded = await applyCellEdits(blank, [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Q' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 'Sales' } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 10 } },
    { sheetName: 'Sheet1', row: 2, column: 1, writeValue: true, cell: { value: 20 } },
  ])
  const contentTypes = (await partOf(seeded, '[Content_Types].xml')).replace(
    '</Types>',
    '<Override PartName="/xl/charts/chart1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/></Types>',
  )
  const mutation = await assemblePackage(seeded, {
    replaced: new Map<string, string>([['[Content_Types].xml', contentTypes]]),
    added: new Map([['xl/charts/chart1.xml', CHART_XML]]),
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries: ['xl/charts/chart1.xml'],
    touchedEntries: ['[Content_Types].xml', 'xl/charts/chart1.xml'],
  })
  return mutation.buffer
}

async function buildComboChartWorkbook(secondPlot = 'lineChart'): Promise<Uint8Array> {
  const comboPlot =
    `<c:${secondPlot}><c:grouping val="standard"/><c:varyColors val="0"/>` +
    '<c:ser><c:idx val="1"/><c:order val="1"/><c:tx><c:v>Costs</c:v></c:tx>' +
    '<c:cat><c:strRef><c:f>Sheet1!$A$2:$A$3</c:f><c:strCache><c:ptCount val="2"/></c:strCache></c:strRef></c:cat>' +
    '<c:val><c:numRef><c:f>Sheet1!$C$2:$C$3</c:f><c:numCache><c:ptCount val="2"/></c:numCache></c:numRef></c:val>' +
    '</c:ser><c:axId val="333"/><c:axId val="444"/></c:' + secondPlot + '>'
  const comboXml = CHART_XML.replace('</c:barChart>', `</c:barChart>${comboPlot}`)
    .replace(
      '</c:plotArea>',
      '<c:catAx><c:axId val="333"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="1"/><c:axPos val="b"/><c:crossAx val="444"/></c:catAx>' +
        '<c:valAx><c:axId val="444"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="r"/><c:crossAx val="333"/><c:crosses val="max"/></c:valAx></c:plotArea>',
    )
  const blank = await createBlankWorkbook()
  const seeded = await applyCellEdits(blank, [])
  const contentTypes = (await partOf(seeded, '[Content_Types].xml')).replace(
    '</Types>',
    '<Override PartName="/xl/charts/chart1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/></Types>',
  )
  const mutation = await assemblePackage(seeded, {
    replaced: new Map<string, string>([['[Content_Types].xml', contentTypes]]),
    added: new Map([['xl/charts/chart1.xml', comboXml]]),
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries: ['xl/charts/chart1.xml'],
    touchedEntries: ['[Content_Types].xml', 'xl/charts/chart1.xml'],
  })
  return mutation.buffer
}

describe('chart edits', () => {
  it('lists chart parts and rewrites the title', async () => {
    const bytes = await buildChartWorkbook()
    expect(await listChartParts(bytes)).toEqual(['xl/charts/chart1.xml'])
    const edited = await applyChartEdits(bytes, [
      { chartPath: 'xl/charts/chart1.xml', title: '季度销售额' },
    ])
    const xml = await partOf(edited, 'xl/charts/chart1.xml')
    expect(xml).toContain('<a:t>季度销售额</a:t>')
    expect(xml).not.toContain('<a:t>Old</a:t>')
  })

  it('converts a bar chart to line and back, keeping series and axes', async () => {
    const bytes = await buildChartWorkbook()
    const edited = await applyChartEdits(bytes, [
      { chartPath: 'xl/charts/chart1.xml', chartType: 'line' },
    ])
    const xml = await partOf(edited, 'xl/charts/chart1.xml')
    expect(xml).toContain('<c:lineChart>')
    expect(xml).toContain('<c:marker val="1"/>')
    expect(xml).toContain('<c:v>Q1</c:v>') // series data survived
    expect(xml).toContain('<c:axId val="111"/>')
    // column → bar flips only the direction
    const flipped = await applyChartEdits(bytes, [
      { chartPath: 'xl/charts/chart1.xml', chartType: 'bar' },
    ])
    expect(await partOf(flipped, 'xl/charts/chart1.xml')).toContain('<c:barDir val="bar"/>')
  })

  it('collapses supported combos to one plot, preserving all series and primary axes', async () => {
    const bytes = await buildComboChartWorkbook()
    const edited = await applyChartEdits(bytes, [
      { chartPath: 'xl/charts/chart1.xml', chartType: 'line' },
    ])
    const xml = await partOf(edited, 'xl/charts/chart1.xml')
    expect(xml.match(/<c:lineChart>/g)).toHaveLength(1)
    expect(xml.match(/<c:ser>/g)).toHaveLength(2)
    expect(xml).toContain('<c:v>Sales</c:v>')
    expect(xml).toContain('<c:v>Costs</c:v>')
    expect(xml).toContain('<c:f>Sheet1!$C$2:$C$3</c:f>')
    expect(xml).toContain('<c:axId val="111"/>')
    expect(xml).toContain('<c:axId val="222"/>')
    expect(xml).not.toContain('<c:axId val="444"/>')
    expect(xml).not.toContain('<c:valAx><c:axId val="444"/>')
    expect(xml).toContain('<a:t>Old</a:t>')
  })

  it('rejects combos containing a plot family outside bar, line, or area', async () => {
    const bytes = await buildComboChartWorkbook('scatterChart')
    await expect(
      applyChartEdits(bytes, [{ chartPath: 'xl/charts/chart1.xml', chartType: 'line' }]),
    ).rejects.toThrow(/Only bar, line, and area combos/)
  })

  it('converting to pie drops the axes; back to column synthesizes them', async () => {
    const bytes = await buildChartWorkbook()
    const pie = await applyChartEdits(bytes, [
      { chartPath: 'xl/charts/chart1.xml', chartType: 'pie' },
    ])
    const pieXml = await partOf(pie, 'xl/charts/chart1.xml')
    expect(pieXml).toContain('<c:pieChart>')
    expect(pieXml).not.toContain('<c:catAx>')
    expect(pieXml).not.toContain('<c:valAx>')
    const back = await applyChartEdits(pie, [
      { chartPath: 'xl/charts/chart1.xml', chartType: 'column' },
    ])
    const backXml = await partOf(back, 'xl/charts/chart1.xml')
    expect(backXml).toContain('<c:barChart>')
    expect(backXml).toContain('<c:axId val="900000001"/>')
    expect(backXml).toContain('<c:crossAx val="900000001"/>')
  })

  it('sets a series solid color (fill + line)', async () => {
    const bytes = await buildChartWorkbook()
    const edited = await applyChartEdits(bytes, [
      { chartPath: 'xl/charts/chart1.xml', seriesColors: { '0': '#2F9E6E' } },
    ])
    const xml = await partOf(edited, 'xl/charts/chart1.xml')
    expect((xml.match(/<a:srgbClr val="2F9E6E"\/>/g) ?? []).length).toBe(2) // fill + ln
  })

  it('fails closed on unknown charts and bad colors', async () => {
    const bytes = await buildChartWorkbook()
    await expect(
      applyChartEdits(bytes, [{ chartPath: 'xl/charts/chart9.xml', title: 'x' }]),
    ).rejects.toThrow(/不存在/)
    await expect(
      applyChartEdits(bytes, [{ chartPath: 'xl/charts/chart1.xml', seriesColors: { '0': 'red' } }]),
    ).rejects.toThrow(/非法颜色/)
    await expect(
      applyChartEdits(bytes, [{ chartPath: 'xl/charts/chart1.xml', seriesColors: { '5': '#123456' } }]),
    ).rejects.toThrow(/no series with index 5/)
  })

  it('positions or removes the legend', async () => {
    const bytes = await buildChartWorkbook()
    const withLegend = await applyChartEdits(bytes, [
      { chartPath: 'xl/charts/chart1.xml', legend: 'bottom' },
    ])
    const xml = await partOf(withLegend, 'xl/charts/chart1.xml')
    expect(xml).toContain('<c:legend><c:legendPos val="b"/><c:overlay val="0"/></c:legend>')
    expect(xml.indexOf('</c:plotArea>')).toBeLessThan(xml.indexOf('<c:legend>'))
    const without = await applyChartEdits(withLegend, [
      { chartPath: 'xl/charts/chart1.xml', legend: 'none' },
    ])
    expect(await partOf(without, 'xl/charts/chart1.xml')).not.toContain('<c:legend>')
  })

  it('writes plot-level data labels with position and number format', async () => {
    const bytes = await buildChartWorkbook()
    const edited = await applyChartEdits(bytes, [
      {
        chartPath: 'xl/charts/chart1.xml',
        dataLabels: 'value',
        dataLabelPosition: 'outside-end',
        dataLabelFormat: '0.0%',
      },
    ])
    const xml = await partOf(edited, 'xl/charts/chart1.xml')
    expect(xml).toContain('<c:dLbls><c:numFmt formatCode="0.0%" sourceLinked="0"/>')
    expect(xml).toContain('<c:dLblPos val="outEnd"/>')
    expect(xml).toContain('<c:showVal val="1"/>')
    const off = await applyChartEdits(edited, [
      { chartPath: 'xl/charts/chart1.xml', dataLabels: 'none' },
    ])
    const offXml = await partOf(off, 'xl/charts/chart1.xml')
    expect(offXml).not.toContain('<c:dLblPos')
  })

  it('sets and removes axis titles', async () => {
    const bytes = await buildChartWorkbook()
    const edited = await applyChartEdits(bytes, [
      {
        chartPath: 'xl/charts/chart1.xml',
        axisTitles: { category: '季度', value: '销售额' },
      },
    ])
    const xml = await partOf(edited, 'xl/charts/chart1.xml')
    expect(xml).toContain('<a:t>季度</a:t>')
    expect(xml).toContain('<a:t>销售额</a:t>')
    const removed = await applyChartEdits(edited, [
      { chartPath: 'xl/charts/chart1.xml', axisTitles: { value: null } },
    ])
    const removedXml = await partOf(removed, 'xl/charts/chart1.xml')
    expect(removedXml).toContain('<a:t>季度</a:t>')
    expect(removedXml).not.toContain('<a:t>销售额</a:t>')
  })

  it('stacks and unstacks bar charts with the matching overlap', async () => {
    const bytes = await buildChartWorkbook()
    const stacked = await applyChartEdits(bytes, [
      { chartPath: 'xl/charts/chart1.xml', grouping: 'stacked' },
    ])
    const stackedXml = await partOf(stacked, 'xl/charts/chart1.xml')
    expect(stackedXml).toContain('<c:grouping val="stacked"/>')
    expect(stackedXml).toContain('<c:overlap val="100"/>')
    const clustered = await applyChartEdits(stacked, [
      { chartPath: 'xl/charts/chart1.xml', grouping: 'clustered' },
    ])
    const clusteredXml = await partOf(clustered, 'xl/charts/chart1.xml')
    expect(clusteredXml).toContain('<c:grouping val="clustered"/>')
    expect(clusteredXml).toContain('<c:overlap val="-27"/>')
  })

  it('toggles gridlines and sets value-axis bounds', async () => {
    const bytes = await buildChartWorkbook()
    const withLines = await applyChartEdits(bytes, [
      { chartPath: 'xl/charts/chart1.xml', gridlines: true },
    ])
    const withLinesXml = await partOf(withLines, 'xl/charts/chart1.xml')
    expect(withLinesXml).toContain('<c:majorGridlines/>')
    const bounded = await applyChartEdits(withLines, [
      { chartPath: 'xl/charts/chart1.xml', valueAxis: { min: 0, max: 50 } },
    ])
    const boundedXml = await partOf(bounded, 'xl/charts/chart1.xml')
    expect(boundedXml).toContain('<c:max val="50"/>')
    expect(boundedXml).toContain('<c:min val="0"/>')
    // CT_Scaling order: orientation precedes max, which precedes min.
    expect(boundedXml.indexOf('<c:orientation')).toBeLessThan(boundedXml.indexOf('<c:max'))
    expect(boundedXml.indexOf('<c:max')).toBeLessThan(boundedXml.indexOf('<c:min'))
    const reset = await applyChartEdits(bounded, [
      { chartPath: 'xl/charts/chart1.xml', valueAxis: { max: null }, gridlines: false },
    ])
    const resetXml = await partOf(reset, 'xl/charts/chart1.xml')
    expect(resetXml).not.toContain('<c:max')
    expect(resetXml).not.toContain('<c:majorGridlines')
  })

  it('sets the bar gap width', async () => {
    const bytes = await buildChartWorkbook()
    const edited = await applyChartEdits(bytes, [
      { chartPath: 'xl/charts/chart1.xml', gapWidthPct: 80 },
    ])
    expect(await partOf(edited, 'xl/charts/chart1.xml')).toContain('<c:gapWidth val="80"/>')
  })

  it('replaces the whole series set with refs and caches', async () => {
    const bytes = await buildChartWorkbook()
    const edited = await applyChartEdits(bytes, [
      {
        chartPath: 'xl/charts/chart1.xml',
        seriesSet: [
          {
            name: 'Revenue',
            values: [1, 2],
            valuesRef: 'Sheet1!$B$2:$B$3',
            categories: ['Q1', 'Q2'],
            categoriesRef: 'Sheet1!$A$2:$A$3',
            color: '#112233',
          },
          { name: 'Cost', values: [3] },
        ],
      },
    ])
    const xml = await partOf(edited, 'xl/charts/chart1.xml')
    expect(xml).toContain('<c:v>Revenue</c:v>')
    expect(xml).toContain('<c:f>Sheet1!$B$2:$B$3</c:f>')
    expect((xml.match(/<c:ser>/g) ?? []).length).toBe(2)
    expect(xml).not.toContain('<c:v>Sales</c:v>')
    expect(xml).toContain('<c:numLit><c:ptCount val="1"/>')
  })

  it('rewrites one series name and values without demoting refs', async () => {
    const bytes = await buildChartWorkbook()
    const edited = await applyChartEdits(bytes, [
      {
        chartPath: 'xl/charts/chart1.xml',
        series: [{ index: 0, name: 'Sales 2026', values: [11, 22] }],
      },
    ])
    const xml = await partOf(edited, 'xl/charts/chart1.xml')
    expect(xml).toContain('<c:v>Sales 2026</c:v>') // c:tx text run
    expect(xml).toContain('<c:f>Sheet1!$B$2:$B$3</c:f>') // reference kept
    expect(xml).toContain('<c:v>11</c:v>')
    expect(xml).toContain('<c:v>22</c:v>')
    expect(xml).not.toContain('<c:v>10</c:v>')
  })

  it('colors pie points, explodes slices, and resizes the doughnut hole', async () => {
    const bytes = await buildChartWorkbook()
    const pie = await applyChartEdits(bytes, [{ chartPath: 'xl/charts/chart1.xml', chartType: 'pie' }])
    const colored = await applyChartEdits(pie, [
      {
        chartPath: 'xl/charts/chart1.xml',
        pointColors: { '0': { '0': '#AABBCC', '1': '#DDEEFF' } },
        explosionPct: 12,
        pointExplosions: { '1': 25 },
      },
    ])
    const xml = await partOf(colored, 'xl/charts/chart1.xml')
    expect(xml).toContain('<c:explosion val="12"/>')
    expect(xml).toContain('<c:idx val="1"/><c:bubble3D val="0"/><c:explosion val="25"/>')
    expect(xml).toContain('<a:srgbClr val="AABBCC"/>')
    expect(xml).toContain('<a:srgbClr val="DDEEFF"/>')
    const doughnut = await applyChartEdits(pie, [
      { chartPath: 'xl/charts/chart1.xml', chartType: 'doughnut', holeSizePct: 30 },
    ])
    expect(await partOf(doughnut, 'xl/charts/chart1.xml')).toContain('<c:holeSize val="30"/>')
  })

  it('fails closed when an edit does not fit the chart family', async () => {
    const bytes = await buildChartWorkbook()
    const pie = await applyChartEdits(bytes, [{ chartPath: 'xl/charts/chart1.xml', chartType: 'pie' }])
    await expect(
      applyChartEdits(pie, [{ chartPath: 'xl/charts/chart1.xml', gridlines: true }]),
    ).rejects.toThrow(/no value axis/)
    await expect(
      applyChartEdits(pie, [{ chartPath: 'xl/charts/chart1.xml', holeSizePct: 40 }]),
    ).rejects.toThrow(/doughnut/)
    await expect(
      applyChartEdits(bytes, [{ chartPath: 'xl/charts/chart1.xml', series: [{ index: 3, name: 'x' }] }]),
    ).rejects.toThrow(/no series with index 3/)
  })

  it('leaves the rest of the package byte-identical and readable', async () => {
    const bytes = await buildChartWorkbook()
    const edited = await applyChartEdits(bytes, [
      { chartPath: 'xl/charts/chart1.xml', title: 'New', chartType: 'line' },
    ])
    const model = await readWorkbook(edited)
    expect(model.sheets[0]?.cells.B2?.value).toBe(10)
    const { inventoryXlsx } = await import('../src/zip')
    const before = await inventoryXlsx(bytes)
    const after = await inventoryXlsx(edited)
    const afterByPath = new Map(after.map((entry) => [entry.path, entry.sha256]))
    for (const entry of before) {
      if (entry.path === 'xl/charts/chart1.xml') continue
      expect(afterByPath.get(entry.path)).toBe(entry.sha256)
    }
  })
})
