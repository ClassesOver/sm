import { expect, it } from 'vitest'
import { switchChartSeries } from './workbook-chart-switch'

const sheetName = "Owner's Data"
const qualifier = "'Owner''s Data'!"
const grid = [['', 'North', 'South'], ['Q1', 10, 20], ['Q2', 30, 40]]
const read = (row: number, column: number) => grid[row]?.[column]
const series = [1, 2].map(column => ({ name: grid[0]![column] as string,
  categoriesRef: `${qualifier}$A$2:$A$3`, valuesRef: `${qualifier}$${column === 1 ? 'B' : 'C'}$2:$${column === 1 ? 'B' : 'C'}$3` }))

it('switches column series into row series with live values and correct references', () => {
  expect(switchChartSeries({ kind: 'column', series }, sheetName, read)).toEqual([
    { name: 'Q1', categories: ['North', 'South'], categoriesRef: `${qualifier}$B$1:$C$1`, values: [10, 20], valuesRef: `${qualifier}$B$2:$C$2` },
    { name: 'Q2', categories: ['North', 'South'], categoriesRef: `${qualifier}$B$1:$C$1`, values: [30, 40], valuesRef: `${qualifier}$B$3:$C$3` },
  ])
})

it('switches the resulting row series back to the original references', () => {
  const switched = switchChartSeries({ kind: 'column', series }, sheetName, read)
  expect(switchChartSeries({ kind: 'column', series: switched }, sheetName, read)).toEqual(series.map((entry, index) => ({
    ...entry, categories: ['Q1', 'Q2'], values: index ? [20, 40] : [10, 30],
  })))
})

it('rejects noncontiguous, external, mismatched and unsupported data without guessing', () => {
  expect(() => switchChartSeries({ kind: 'combo', series }, sheetName, read)).toThrow()
  expect(() => switchChartSeries({ kind: 'column', series: [series[1]!, series[0]!] }, sheetName, read)).toThrow()
  expect(() => switchChartSeries({ kind: 'column', series: [{ ...series[0]!, valuesRef: '[1]Other!A1:A2' }] }, sheetName, read)).toThrow()
  expect(() => switchChartSeries({ kind: 'column', series: [{ ...series[0]!, name: 'Different' }, series[1]!] }, sheetName, read)).toThrow()
  expect(() => switchChartSeries({ kind: 'column', series }, sheetName, () => 'text')).toThrow()
})
