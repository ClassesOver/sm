import { describe, expect, it } from 'vitest'

import { createBlankWorkbook } from '../src/blank'
import { applyChartAdditions } from '../src/chart-add'
import { readWorkbook } from '../src/workbook-read'

const SHEET = 'Sheet1'

describe('chart read-back (网格渲染 v1)', () => {
  it('reads anchored charts back with type, title, and series references', async () => {
    const bytes = await createBlankWorkbook()
    const withChart = await applyChartAdditions(bytes, [
      {
        worksheetSheetName: SHEET,
        anchor: {
          fromRow: 0, fromColumn: 4, fromRowOffset: 0, fromColumnOffset: 0,
          toRow: 8, toColumn: 10, toRowOffset: 0, toColumnOffset: 0,
        },
        chart: {
          chartType: 'column',
          title: '季度销售',
          series: [
            {
              name: '销售额',
              categories: ['一季度', '二季度', '三季度'],
              values: [120, 200, 160],
              valuesRef: `${SHEET}!$B$2:$B$4`,
              categoriesRef: `${SHEET}!$A$2:$A$4`,
            },
          ],
        },
      },
    ])
    const model = await readWorkbook(withChart)
    const charts = model.sheets[0]?.charts ?? []
    expect(charts).toHaveLength(1)
    const chart = charts[0]!
    expect(chart.kind).toBe('column')
    expect(chart.title).toBe('季度销售')
    expect(chart.anchor.fromColumn).toBe(4)
    expect(chart.series).toHaveLength(1)
    expect(chart.series[0]!.valuesRef).toBe('Sheet1!$B$2:$B$4')
    expect(chart.series[0]!.categoriesRef).toBe('Sheet1!$A$2:$A$4')
    expect(chart.series[0]!.name).toBe('销售额')
  })

  it('maps line and pie kinds and reads nothing from a chart-free workbook', async () => {
    const bytes = await createBlankWorkbook()
    const seeded = await applyChartAdditions(bytes, [
      {
        worksheetSheetName: SHEET,
        anchor: {
          fromRow: 0, fromColumn: 4, fromRowOffset: 0, fromColumnOffset: 0,
          toRow: 8, toColumn: 10, toRowOffset: 0, toColumnOffset: 0,
        },
        chart: {
          chartType: 'line',
          title: 'L',
          series: [{ name: 'S', categories: ['一', '二'], values: [1, 2], valuesRef: `${SHEET}!$B$2:$B$3` }],
        },
      },
      {
        worksheetSheetName: SHEET,
        anchor: {
          fromRow: 10, fromColumn: 4, fromRowOffset: 0, fromColumnOffset: 0,
          toRow: 18, toColumn: 10, toRowOffset: 0, toColumnOffset: 0,
        },
        chart: {
          chartType: 'pie',
          title: 'P',
          series: [{ name: 'S', categories: ['一', '二'], values: [1, 2], valuesRef: `${SHEET}!$B$2:$B$3` }],
        },
      },
    ])
    const charts = (await readWorkbook(seeded)).sheets[0]?.charts ?? []
    expect(charts.map((chart) => chart.kind)).toEqual(['line', 'pie'])
    expect(charts.every((chart) => chart.series.length === 1)).toBe(true)

    const plain = await readWorkbook(await createBlankWorkbook())
    expect(plain.sheets[0]?.charts ?? []).toEqual([])
  })

  it('maps area, doughnut, and combo (bar+line dual plot) kinds', async () => {
    const bytes = await createBlankWorkbook()
    const seeded = await applyChartAdditions(bytes, [
      {
        worksheetSheetName: SHEET,
        anchor: {
          fromRow: 0, fromColumn: 4, fromRowOffset: 0, fromColumnOffset: 0,
          toRow: 8, toColumn: 10, toRowOffset: 0, toColumnOffset: 0,
        },
        chart: {
          chartType: 'area',
          title: 'A',
          series: [{ name: 'S', categories: ['一', '二'], values: [1, 2], valuesRef: `${SHEET}!$B$2:$B$3` }],
        },
      },
      {
        worksheetSheetName: SHEET,
        anchor: {
          fromRow: 10, fromColumn: 4, fromRowOffset: 0, fromColumnOffset: 0,
          toRow: 18, toColumn: 10, toRowOffset: 0, toColumnOffset: 0,
        },
        chart: {
          chartType: 'doughnut',
          title: 'D',
          series: [{ name: 'S', categories: ['一', '二'], values: [1, 2], valuesRef: `${SHEET}!$B$2:$B$3` }],
        },
      },
      {
        worksheetSheetName: SHEET,
        anchor: {
          fromRow: 20, fromColumn: 4, fromRowOffset: 0, fromColumnOffset: 0,
          toRow: 28, toColumn: 10, toRowOffset: 0, toColumnOffset: 0,
        },
        chart: {
          chartType: 'combo',
          title: 'C',
          series: [
            { name: '柱', categories: ['一', '二'], values: [1, 2], valuesRef: `${SHEET}!$B$2:$B$3` },
            { name: '线', categories: ['一', '二'], values: [3, 4], valuesRef: `${SHEET}!$C$2:$C$3` },
          ],
        },
      },
    ])
    const charts = (await readWorkbook(seeded)).sheets[0]?.charts ?? []
    expect(charts.map((chart) => chart.kind)).toEqual(['area', 'doughnut', 'combo'])
    // combo keeps both series in document order (bars first, line last)
    expect(charts[2]!.series.map((entry) => entry.name)).toEqual(['柱', '线'])
  })

  it('maps scatter with an X reference and radar with the plain series shape', async () => {
    const bytes = await createBlankWorkbook()
    const seeded = await applyChartAdditions(bytes, [
      {
        worksheetSheetName: SHEET,
        anchor: {
          fromRow: 0, fromColumn: 4, fromRowOffset: 0, fromColumnOffset: 0,
          toRow: 8, toColumn: 10, toRowOffset: 0, toColumnOffset: 0,
        },
        chart: {
          chartType: 'scatter',
          title: 'XY',
          // numeric category column → the writer emits c:xVal numRef
          series: [
            { name: '点', categories: ['1', '2', '3'], values: [5, 7, 11], valuesRef: `${SHEET}!$B$2:$B$4`, categoriesRef: `${SHEET}!$A$2:$A$4` },
          ],
        },
      },
      {
        worksheetSheetName: SHEET,
        anchor: {
          fromRow: 10, fromColumn: 4, fromRowOffset: 0, fromColumnOffset: 0,
          toRow: 18, toColumn: 10, toRowOffset: 0, toColumnOffset: 0,
        },
        chart: {
          chartType: 'radar',
          title: 'R',
          series: [{ name: '雷达', categories: ['一', '二', '三'], values: [3, 6, 9], valuesRef: `${SHEET}!$B$2:$B$4` }],
        },
      },
    ])
    const charts = (await readWorkbook(seeded)).sheets[0]?.charts ?? []
    expect(charts.map((chart) => chart.kind)).toEqual(['scatter', 'radar'])
    const scatter = charts[0]!
    // numeric categories ride c:xVal numRef back as the X reference
    expect(scatter.series[0]!.xValuesRef).toBe(`${SHEET}!$A$2:$A$4`)
    expect(scatter.series[0]!.valuesRef).toBe(`${SHEET}!$B$2:$B$4`)
    expect(charts[1]!.series[0]!.valuesRef).toBe(`${SHEET}!$B$2:$B$4`)
  })
})
