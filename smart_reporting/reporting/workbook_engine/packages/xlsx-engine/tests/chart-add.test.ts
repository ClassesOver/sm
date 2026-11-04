import { describe, expect, it } from 'vitest'

import { applyCellEdits, createBlankWorkbook, type ChartAddition } from '../src'
import { applyChartAdditions } from '../src/chart-add'
import { listChartParts } from '../src/rules'
import { createBufferEntrySource, inventoryXlsx } from '../src/zip'

async function partOf(bytes: Uint8Array, path: string): Promise<string> {
  const source = await createBufferEntrySource(bytes)
  return source.readText(path)
}

async function hasPart(bytes: Uint8Array, path: string): Promise<boolean> {
  const source = await createBufferEntrySource(bytes)
  return source.has(path)
}

async function buildSourceWorkbook(): Promise<Uint8Array> {
  return applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Q' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 'Sales' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'Q1' } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 10 } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 'Q2' } },
    { sheetName: 'Sheet1', row: 2, column: 1, writeValue: true, cell: { value: 20 } },
  ])
}

function columnChart(): ChartAddition {
  return {
    worksheetSheetName: 'Sheet1',
    anchor: {
      fromRow: 0, fromColumn: 3, fromRowOffset: 0, fromColumnOffset: 0,
      toRow: 15, toColumn: 10, toRowOffset: 0, toColumnOffset: 0,
    },
    chart: {
      chartType: 'column',
      title: 'Sales by quarter',
      series: [
        {
          name: 'Sales',
          categories: ['Q1', 'Q2'],
          values: [10, 20],
          valuesRef: 'Sheet1!$B$2:$B$3',
          categoriesRef: 'Sheet1!$A$2:$A$3',
        },
      ],
    },
  }
}

describe('chart creation', () => {
  it('creates the chart and drawing parts and wires worksheet, rels, and content types', async () => {
    const edited = await applyChartAdditions(await buildSourceWorkbook(), [columnChart()])
    expect(await hasPart(edited, 'xl/charts/chart1.xml')).toBe(true)
    expect(await hasPart(edited, 'xl/drawings/drawing1.xml')).toBe(true)
    expect(await hasPart(edited, 'xl/drawings/_rels/drawing1.xml.rels')).toBe(true)

    const chart = await partOf(edited, 'xl/charts/chart1.xml')
    expect(chart).toContain('<c:barChart><c:barDir val="col"/>')
    expect(chart).toContain('<a:t>Sales by quarter</a:t>')
    expect(chart).toContain('<c:f>Sheet1!$B$2:$B$3</c:f>')
    expect(chart).toContain('<c:pt idx="0"><c:v>10</c:v></c:pt>')

    const drawing = await partOf(edited, 'xl/drawings/drawing1.xml')
    expect(drawing).toContain('<xdr:twoCellAnchor')
    expect(drawing).toContain('<xdr:col>3</xdr:col>')
    expect(drawing).toContain('</xdr:wsDr>')

    const drawingRels = await partOf(edited, 'xl/drawings/_rels/drawing1.xml.rels')
    expect(drawingRels).toContain('Target="../charts/chart1.xml"')

    const sheetRels = await partOf(edited, 'xl/worksheets/_rels/sheet1.xml.rels')
    expect(sheetRels).toContain('Target="../drawings/drawing1.xml"')
    expect(await partOf(edited, 'xl/worksheets/sheet1.xml')).toContain('<drawing r:id=')

    const contentTypes = await partOf(edited, '[Content_Types].xml')
    expect(contentTypes).toContain('PartName="/xl/charts/chart1.xml"')
    expect(contentTypes).toContain('PartName="/xl/drawings/drawing1.xml"')

    // the new chart joins the workbook's chart numbering used by editCharts
    expect(await listChartParts(edited)).toEqual(['xl/charts/chart1.xml'])
  })

  it('reuses the drawing part when a second chart joins the sheet', async () => {
    const withOne = await applyChartAdditions(await buildSourceWorkbook(), [columnChart()])
    const withTwo = await applyChartAdditions(withOne, [columnChart()])
    expect(await hasPart(withTwo, 'xl/charts/chart2.xml')).toBe(true)
    expect(await hasPart(withTwo, 'xl/drawings/drawing2.xml')).toBe(false)
    const drawing = await partOf(withTwo, 'xl/drawings/drawing1.xml')
    expect(drawing.match(/<xdr:twoCellAnchor/g)?.length).toBe(2)
    const rels = await partOf(withTwo, 'xl/drawings/_rels/drawing1.xml.rels')
    expect(rels).toContain('Target="../charts/chart2.xml"')
    expect(await listChartParts(withTwo)).toEqual([
      'xl/charts/chart1.xml',
      'xl/charts/chart2.xml',
    ])
  })

  it('keeps untouched package entries byte-identical', async () => {
    const base = await buildSourceWorkbook()
    const edited = await applyChartAdditions(base, [columnChart()])
    const before = new Map((await inventoryXlsx(base)).map((entry) => [entry.path, entry.sha256]))
    const after = new Map((await inventoryXlsx(edited)).map((entry) => [entry.path, entry.sha256]))
    const expectedChanged = new Set([
      '[Content_Types].xml',
      'xl/worksheets/sheet1.xml',
      'xl/charts/chart1.xml',
      'xl/drawings/drawing1.xml',
      'xl/drawings/_rels/drawing1.xml.rels',
    ])
    // the sheet rels part is either extended (existed) or newly created
    expectedChanged.add('xl/worksheets/_rels/sheet1.xml.rels')
    for (const [path, sha] of after) {
      if (expectedChanged.has(path)) continue
      expect(before.get(path)).toBe(sha)
    }
  })

  it('writes cached literal series when refs are absent', async () => {
    const addition = columnChart()
    const edited = await applyChartAdditions(await buildSourceWorkbook(), [
      {
        ...addition,
        chart: {
          ...addition.chart,
          series: [{ name: 'Sales', categories: ['Q1'], values: [7] }],
        },
      },
    ])
    const chart = await partOf(edited, 'xl/charts/chart1.xml')
    expect(chart).toContain('<c:numLit><c:ptCount val="1"/><c:pt idx="0"><c:v>7</c:v></c:pt></c:numLit>')
    expect(chart).toContain('<c:strLit><c:ptCount val="1"/><c:pt idx="0"><c:v>Q1</c:v></c:pt></c:strLit>')
  })

  it('rejects empty series, non-finite values, and hostile anchors', async () => {
    const base = await buildSourceWorkbook()
    const base0 = columnChart()
    await expect(
      applyChartAdditions(base, [{ ...base0, chart: { ...base0.chart, series: [] } }]),
    ).rejects.toThrow(/at least one series/)
    await expect(
      applyChartAdditions(base, [
        {
          ...base0,
          chart: {
            ...base0.chart,
            series: [{ name: 'x', categories: ['a'], values: [Number.NaN] }],
          },
        },
      ]),
    ).rejects.toThrow(/non-finite/)
    await expect(
      applyChartAdditions(base, [
        { ...base0, anchor: { ...base0.anchor, fromRow: -1 } },
      ]),
    ).rejects.toThrow(/anchor fromRow/)
    // an inverted anchor (end before start) must fail closed, not bake a
    // backwards twoCellAnchor into the drawing part
    await expect(
      applyChartAdditions(base, [
        { ...base0, anchor: { ...base0.anchor, fromRow: 10, toRow: 2, fromColumn: 5, toColumn: 1 } },
      ]),
    ).rejects.toThrow(/must not precede/)
  })

  it('rejects out-of-envelope point overrides and layout percentages', async () => {
    const base = await buildSourceWorkbook()
    const pie: () => ChartAddition = () => ({
      worksheetSheetName: 'Sheet1',
      anchor: columnChart().anchor,
      chart: {
        chartType: 'pie',
        title: 't',
        series: [{ name: 's', categories: ['a', 'b'], values: [1, 2] }],
      },
    })
    // junk point-index keys would otherwise become val="NaN" dPt entries
    await expect(
      applyChartAdditions(base, [
        {
          ...pie(),
          chart: {
            ...pie().chart,
            chartType: 'column',
            series: [
              { name: 's', categories: ['a', 'b'], values: [1, 2], pointColors: { oops: '#AABBCC' } },
            ],
          },
        },
      ]),
    ).rejects.toThrow(/point indices/)
    await expect(
      applyChartAdditions(base, [
        {
          ...pie(),
          chart: {
            ...pie().chart,
            series: [
              { name: 's', categories: ['a'], values: [1], pointColors: { '0': 'red' } },
            ],
          },
        },
      ]),
    ).rejects.toThrow(/#RRGGBB/)
    await expect(
      applyChartAdditions(base, [
        {
          ...pie(),
          chart: {
            ...pie().chart,
            series: [
              { name: 's', categories: ['a'], values: [1], pointExplosions: { '0': 9999 } },
            ],
          },
        },
      ]),
    ).rejects.toThrow(/0-400/)
    await expect(
      applyChartAdditions(base, [
        { ...pie(), chart: { ...pie().chart, chartType: 'doughnut', holeSizePct: 9999.5 } },
      ]),
    ).rejects.toThrow(/10 and 90/)
    await expect(
      applyChartAdditions(base, [
        {
          ...pie(),
          chart: {
            ...pie().chart,
            chartType: 'doughnut',
            series: [{ name: 's', categories: ['a'], values: [1], explosionPct: 1e9 }],
          },
        },
      ]),
    ).rejects.toThrow(/0 and 400/)
  })
})
