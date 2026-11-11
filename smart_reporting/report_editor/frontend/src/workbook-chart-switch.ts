import { formatAddress, parseRange, type ChartReadSpec, type ChartSeriesSetEntry } from '@sheets-web/xlsx-engine'

/** 仅切换带表头/分类标签的连续矩形；不猜测字面缓存、名称或外部引用。 */
export function switchChartSeries(
  chart: Pick<ChartReadSpec, 'kind' | 'series'>,
  sheetName: string,
  read: (row: number, column: number) => unknown,
): (ChartSeriesSetEntry & { valuesRef: string; categoriesRef: string })[] {
  const reject = () => { throw new Error('当前图表来源不是可切换的带表头连续矩形数据') }
  if (!['column', 'bar', 'line', 'area'].includes(chart.kind) || !chart.series.length || chart.series.length > 32) return reject()
  const parse = (ref: string | undefined) => {
    const match = /^(?:'((?:[^']|'')+)'|([^'!\[\]]+))!(\$?[A-Z]+\$?[1-9]\d*(?::\$?[A-Z]+\$?[1-9]\d*)?)$/.exec(ref ?? '')
    if (!match || (match[1]?.replaceAll("''", "'") ?? match[2]) !== sheetName) return reject()
    return parseRange(match[3]!)
  }
  const ranges = chart.series.map(entry => parse(entry.valuesRef)), category = parse(chart.series[0]!.categoriesRef)
  if (chart.series.some(entry => JSON.stringify(parse(entry.categoriesRef)) !== JSON.stringify(category))) return reject()
  const first = ranges[0]!
  const columns = first.startColumn === first.endColumn && category.startColumn === category.endColumn &&
    category.startRow === first.startRow && category.endRow === first.endRow && category.startColumn + 1 === first.startColumn && first.startRow > 0 &&
    ranges.every((range, index) => range.startRow === first.startRow && range.endRow === first.endRow && range.startColumn === first.startColumn + index && range.endColumn === range.startColumn)
  const rows = first.startRow === first.endRow && category.startRow === category.endRow &&
    category.startColumn === first.startColumn && category.endColumn === first.endColumn && category.startRow + 1 === first.startRow && first.startColumn > 0 &&
    ranges.every((range, index) => range.startColumn === first.startColumn && range.endColumn === first.endColumn && range.startRow === first.startRow + index && range.endRow === range.startRow)
  if (columns === rows) return reject()
  const count = columns ? first.endRow - first.startRow + 1 : first.endColumn - first.startColumn + 1
  if (count > 32) return reject()
  const names = chart.series.map((entry, index) => {
    const name = read(columns ? first.startRow - 1 : first.startRow + index, columns ? first.startColumn + index : first.startColumn - 1)
    if (typeof name !== 'string' || name !== entry.name || !name) return reject()
    return name
  })
  const reference = (r1: number, c1: number, r2: number, c2: number) => {
    const absolute = (r: number, c: number) => formatAddress(r, c).replace(/^([A-Z]+)(\d+)$/, '$$$1$$$2')
    return `'${sheetName.replaceAll("'", "''")}'!${absolute(r1, c1)}:${absolute(r2, c2)}`
  }
  return Array.from({ length: count }, (_, index) => {
    const row = columns ? first.startRow + index : first.startRow
    const column = columns ? first.startColumn : first.startColumn + index
    const name = read(columns ? row : category.startRow, columns ? category.startColumn : column)
    if (typeof name !== 'string' || !name) return reject()
    const values = chart.series.map((_, offset) => {
      const value = read(columns ? row : row + offset, columns ? column + offset : column)
      if (typeof value !== 'number' || !Number.isFinite(value)) return reject()
      return value
    })
    return { name, categories: names, values,
      categoriesRef: columns
        ? reference(first.startRow - 1, column, first.startRow - 1, column + names.length - 1)
        : reference(row, first.startColumn - 1, row + names.length - 1, first.startColumn - 1),
      valuesRef: columns ? reference(row, column, row, column + names.length - 1) : reference(row, column, row + names.length - 1, column),
    }
  })
}
