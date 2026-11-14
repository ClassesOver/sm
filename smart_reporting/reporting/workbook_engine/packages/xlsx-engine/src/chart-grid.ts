import { chartDataFromValues } from './chart-data'
import { hasNumericYearAxis } from './chart-recommend'
import type { ChartAdd, ChartAddition, ChartAddSeries } from './chart-add'

type Cell = string | number | boolean | null | undefined
export type ChartGridRange = { startRow: number; endRow: number; startColumn: number; endColumn: number }

const columnName = (column: number): string => {
  let result = ''
  for (let value = column + 1; value > 0; value = Math.floor((value - 1) / 26)) result = String.fromCharCode(65 + ((value - 1) % 26)) + result
  return result
}
const quoteSheet = (name: string): string => `'${name.replaceAll("'", "''")}'`
const ref = (sheet: string, range: ChartGridRange, row: number, startColumn: number, endColumn: number) =>
  `${quoteSheet(sheet)}!$${columnName(range.startColumn + startColumn)}$${range.startRow + row + 1}:$${columnName(range.startColumn + endColumn)}$${range.startRow + row + 1}`
const rangeRef = (sheet: string, range: ChartGridRange, startRow: number, endRow: number, startColumn: number, endColumn: number) =>
  `${quoteSheet(sheet)}!$${columnName(range.startColumn + startColumn)}$${range.startRow + startRow + 1}:$${columnName(range.startColumn + endColumn)}$${range.startRow + endRow + 1}`

export function chartAdditionFromGrid(input: {
  sheetName: string
  chartType: ChartAdd['chartType']
  title?: string
  range: ChartGridRange
  values: readonly (readonly Cell[])[]
}): ChartAddition {
  let parsed = chartDataFromValues(input.values, { numericCategoryColumn: input.chartType === 'scatter' })
  if (!parsed) throw new Error('图表需要至少一列数值数据')
  if (input.chartType !== 'scatter' && hasNumericYearAxis(parsed))
    parsed = chartDataFromValues(input.values, { numericCategoryColumn: true }) ?? parsed
  const headerOffset = parsed.hasHeaderRow ? 1 : 0
  const categoryOffset = parsed.hasCategoryColumn ? 1 : 0
  const series: ChartAddSeries[] = parsed.series.map((item) => {
    const seriesRow = parsed.byRow ? item.column : 0
    const valuesStart = parsed.byRow ? categoryOffset : item.column
    const valuesEnd = parsed.byRow ? input.values[0]!.length - 1 : item.column
    const categoriesStart = parsed.byRow ? categoryOffset : 0
    const categoriesEnd = parsed.byRow ? input.values[0]!.length - 1 : 0
    const categories = parsed.categories
    return {
      name: item.name,
      categories,
      values: item.values,
      ...(parsed.hasCategoryColumn ? { categoriesRef: parsed.byRow
        ? rangeRef(input.sheetName, input.range, 0, 0, categoriesStart, categoriesEnd)
        : rangeRef(input.sheetName, input.range, headerOffset, input.values.length - 1, 0, 0) } : {}),
      valuesRef: parsed.byRow
        ? ref(input.sheetName, input.range, seriesRow, valuesStart, valuesEnd)
        : rangeRef(input.sheetName, input.range, headerOffset, input.values.length - 1, valuesStart, valuesEnd),
    }
  })
  const chart: ChartAdd = { chartType: input.chartType, title: input.title ?? '', series }
  return {
    worksheetSheetName: input.sheetName,
    anchor: { fromRow: input.range.startRow, fromColumn: input.range.endColumn + 2, fromRowOffset: 0, fromColumnOffset: 0,
      toRow: input.range.startRow + 15, toColumn: input.range.endColumn + 9, toRowOffset: 0, toColumnOffset: 0 },
    chart,
  }
}
