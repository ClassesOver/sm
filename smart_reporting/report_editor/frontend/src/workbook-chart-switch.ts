import { formatAddress, parseRange, type ChartReadSpec, type ChartSeriesSetEntry } from '@sheets-web/xlsx-engine'

const REPLACEABLE_KINDS = new Set<ChartReadSpec['kind']>([
  'column', 'bar', 'line', 'area', 'pie', 'doughnut', 'radar', 'scatter', 'combo',
])
const MAX_SERIES = 1_000
const MAX_TRANSPOSED_CATEGORIES = 24

export function chartSwitchReference(reference: string, defaultSheet: string, maxCells = MAX_TRANSPOSED_CATEGORIES): { sheetName: string; range: string } {
  const trimmed = reference.trim()
  const qualified = /^(?:'((?:[^']|'')+)'|([^'!\[\]]+))!(.+)$/.exec(trimmed)
  if (/[\[\]]/.test(trimmed)) throw new Error('图表数据缓存引用不能来自外部工作簿')
  const sheetName = qualified ? qualified[1]?.replaceAll("''", "'") ?? qualified[2]! : defaultSheet
  const range = (qualified ? qualified[3]! : trimmed).toUpperCase().replaceAll('$', '')
  if (!/^[A-Z]{1,3}[1-9]\d*(?::[A-Z]{1,3}[1-9]\d*)?$/.test(range)) throw new Error('图表数据缓存引用格式无效')
  const bounds = parseRange(range)
  if (bounds.endRow >= 1_048_576 || bounds.endColumn >= 16_384) throw new Error('图表数据缓存引用超出工作表范围')
  if (bounds.startRow !== bounds.endRow && bounds.startColumn !== bounds.endColumn) throw new Error('图表数据缓存引用必须为一行或一列')
  const vertical = bounds.startColumn === bounds.endColumn
  const count = Math.min(vertical ? bounds.endRow - bounds.startRow + 1 : bounds.endColumn - bounds.startColumn + 1, maxCells)
  const endRow = vertical ? bounds.startRow + count - 1 : bounds.startRow
  const endColumn = vertical ? bounds.startColumn : bounds.startColumn + count - 1
  return { sheetName, range: `${formatAddress(bounds.startRow, bounds.startColumn)}:${formatAddress(endRow, endColumn)}` }
}

/** 固定源 chart-visual.transposeChartSeries：基于已读缓存转置，不保留单元格引用。 */
export function switchChartSeries(
  chart: Pick<ChartReadSpec, 'kind' | 'series'>,
  readValues: (ref: string) => readonly unknown[],
): ChartSeriesSetEntry[] {
  const reject = () => { throw new Error('当前图表的数据缓存无法切换行/列') }
  if (!REPLACEABLE_KINDS.has(chart.kind) || !chart.series.length || chart.series.length > MAX_SERIES) return reject()

  const first = chart.series[0]!
  const categories = first.categories?.length
    ? first.categories.map(value => String(value ?? '').slice(0, 255))
    : first.xValues?.map(value => String(value).slice(0, 255)) ?? (first.xValuesRef ? readValues(first.xValuesRef).map(value => String(value ?? '').slice(0, 255)) : [])
  if (!categories.length) return reject()

  const names = chart.series.map((entry, index) => {
    const value = (entry.nameRef ? readValues(entry.nameRef)[0] : undefined) || entry.nameCache || entry.name
    return String(value ?? `系列 ${index + 1}`).slice(0, 255)
  })
  const valuesBySeries = chart.series.map(entry => {
    const values = entry.valuesRef ? readValues(entry.valuesRef) : entry.values ?? []
    return values.map(value => {
      const number = typeof value === 'number' ? value : Number(String(value ?? '').trim())
      return Number.isFinite(number) ? number : 0
    })
  })
  const transposed = categories.slice(0, MAX_TRANSPOSED_CATEGORIES).map((category, index) => ({
    name: category || `系列 ${index + 1}`,
    values: valuesBySeries.map(values => values[index] ?? 0),
    categories: names,
  }))

  if (chart.kind !== 'combo') return transposed
  return transposed.map((entry, index) => {
    const line = transposed.length >= 2 && index === transposed.length - 1
    return { ...entry, plot: line ? 'lineChart' : 'barChart', secondaryAxis: line }
  })
}
