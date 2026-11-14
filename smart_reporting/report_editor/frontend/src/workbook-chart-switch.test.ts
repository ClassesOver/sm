import { expect, it } from 'vitest'
import { chartSwitchReference, switchChartSeries } from './workbook-chart-switch'

const series = [
  { name: 'North', valuesRef: '', categories: ['Q1', 'Q2'], values: [10, 30] },
  { name: 'South', valuesRef: '', categories: ['Q1', 'Q2'], values: [20, 40] },
]
const read = (_ref: string) => { throw new Error('cache should be used') }

it('transposes reference-independent cached values to literal series', () => {
  expect(switchChartSeries({ kind: 'column', series }, read)).toEqual([
    { name: 'Q1', categories: ['North', 'South'], values: [10, 20] },
    { name: 'Q2', categories: ['North', 'South'], values: [30, 40] },
  ])
})

it('uses literal scatter X caches as categories and supports every replaceable family', () => {
  for (const kind of ['column', 'bar', 'line', 'area', 'pie', 'doughnut', 'radar', 'scatter'] as const) {
    const chartSeries = kind === 'scatter'
      ? series.map((entry, index) => ({ name: entry.name, valuesRef: '', xValues: [1, 2], values: index ? [200, 400] : [100, 300] }))
      : series
    const firstValue = kind === 'scatter' ? 100 : 10
    const secondValue = kind === 'scatter' ? 200 : 20
    const thirdValue = kind === 'scatter' ? 300 : 30
    const fourthValue = kind === 'scatter' ? 400 : 40
    expect(switchChartSeries({ kind, series: chartSeries }, read)).toMatchObject([
      { name: kind === 'scatter' ? '1' : 'Q1', categories: ['North', 'South'], values: [firstValue, secondValue] },
      { name: kind === 'scatter' ? '2' : 'Q2', categories: ['North', 'South'], values: [thirdValue, fourthValue] },
    ])
  }
})

it('uses reference caches, fills sparse cache slots with zero, and bounds the replacement', () => {
  const values = Array.from({ length: 26 }, (_, index) => index + 1)
  const chartSeries = [
    { name: 'A', categories: [null, ...Array.from({ length: 25 }, (_, index) => `C${index + 1}`)], valuesRef: 'Sheet1!A1:A26', values: [] },
    { name: 'B', categories: ['other'], valuesRef: 'Sheet1!B1:B26', values: [] },
  ]
  const result = switchChartSeries({ kind: 'radar', series: chartSeries }, ref => ref.endsWith('A1:A26') ? values : values.map(value => value * 10))
  expect(result).toHaveLength(24)
  expect(result[0]).toEqual({ name: '系列 1', categories: ['A', 'B'], values: [1, 10] })
  expect(result[23]).toEqual({ name: 'C23', categories: ['A', 'B'], values: [24, 240] })
})

it('normalizes nonnumeric cache values like the source grid sync', () => {
  expect(switchChartSeries({ kind: 'column', series: [
    { name: 'A', categories: ['x', 'y', 'z'], valuesRef: 'Sheet1!A1:A3', values: [] },
    { name: 'B', categories: ['ignored'], valuesRef: '', values: [2, Number.NaN, Number.POSITIVE_INFINITY] },
  ] }, () => ['4', 'text', null])).toEqual([
    { name: 'x', categories: ['A', 'B'], values: [4, 2] },
    { name: 'y', categories: ['A', 'B'], values: [0, 0] },
    { name: 'z', categories: ['A', 'B'], values: [0, 0] },
  ])
})

it('hydrates series names from their single-cell references', () => {
  const result = switchChartSeries({ kind: 'column', series: [
    { name: undefined, nameCache: undefined, nameRef: "'Data'!$A$1", categories: ['x'], valuesRef: '', values: [1] },
    { name: 'B', categories: ['x'], valuesRef: '', values: [2] },
  ] }, reference => reference.includes('$A$1') ? ['Referenced name'] : [])
  expect(result[0]?.categories).toEqual(['Referenced name', 'B'])
})

it('accepts current-sheet and quoted cross-sheet vectors and reads only the needed prefix', () => {
  expect(chartSwitchReference(' $A$1:$A$24 ', 'Current Sheet')).toEqual({ sheetName: 'Current Sheet', range: 'A1:A24' })
  expect(chartSwitchReference("'Owner''s Data'!$B$2:$B$3", 'Current')).toEqual({ sheetName: "Owner's Data", range: 'B2:B3' })
  expect(chartSwitchReference('Sheet1!A1:A1001', 'Current')).toEqual({ sheetName: 'Sheet1', range: 'A1:A24' })
  expect(chartSwitchReference('Sheet1!A1:XFD1', 'Current')).toEqual({ sheetName: 'Sheet1', range: 'A1:X1' })
  expect(() => chartSwitchReference('[book.xlsx]Sheet1!A1:A2', 'Current')).toThrow()
  expect(() => chartSwitchReference('Sheet1!A1:B2', 'Current')).toThrow()
  expect(() => chartSwitchReference('Sheet1!XFE1:XFE2', 'Current')).toThrow()
  expect(() => chartSwitchReference('Sheet1!A1048577:A1048578', 'Current')).toThrow()
})

it('retains the source combo defaults when transposing a combo chart', () => {
  expect(switchChartSeries({ kind: 'combo', series }, read)).toEqual([
    { name: 'Q1', categories: ['North', 'South'], values: [10, 20], plot: 'barChart', secondaryAxis: false },
    { name: 'Q2', categories: ['North', 'South'], values: [30, 40], plot: 'lineChart', secondaryAxis: true },
  ])
})

it('rejects unsupported types, missing categories, and unbounded series input', () => {
  expect(() => switchChartSeries({ kind: 'combo', series: [] }, read)).toThrow()
  expect(() => switchChartSeries({ kind: 'unsupported' as never, series }, read)).toThrow()
  expect(() => switchChartSeries({ kind: 'column', series: [{ name: 'A', valuesRef: '', values: [1] }] }, read)).toThrow()
  expect(() => switchChartSeries({ kind: 'column', series: Array.from({ length: 1001 }, (_, index) => ({ name: `S${index}`, valuesRef: '', categories: ['A'], values: [1] })) }, read)).toThrow()
})
