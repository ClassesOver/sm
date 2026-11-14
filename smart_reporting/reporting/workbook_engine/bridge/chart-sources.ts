/** Source DSL resolves refs and caches from the actual replayed XLSX, never model literals. */
import { z } from 'zod'
import { readWorkbook, type SheetModel } from '../packages/xlsx-engine/src/workbook-read'
import { parseAddress, formatAddress, rangeCellCount } from '../packages/xlsx-engine/src/cell-address'
import { chartAdditionFromGrid } from '../packages/xlsx-engine/src/chart-grid'
import { applyChartAdditions } from '../packages/xlsx-engine/src/chart-add'
import { applyChartEdits } from '../packages/xlsx-engine/src/rules'
import type { ChartSeriesDataEdit } from '../packages/xlsx-engine/src/chart-edit'

const text = z.string().max(200).regex(/^[^\u0000-\u0008\u000b\u000c\u000e-\u001f]*$/)
const range = z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}(?::[A-Z]{1,3}[1-9][0-9]{0,6})?$/)
const color = z.string().regex(/^#[0-9a-fA-F]{6}$/)
const colors = z.record(z.string().regex(/^(0|[1-9][0-9]{0,3})$/), color)
const explosion = z.number().int().min(0).max(400)
const format = {
  title: text.optional(), chartType: z.enum(['column', 'bar', 'line', 'area', 'pie', 'doughnut']).optional(),
  legend: z.enum(['none', 'right', 'bottom', 'top', 'left']).optional(), seriesColors: colors.optional(),
  pointColors: z.record(z.string().regex(/^(0|[1-9][0-9]{0,3})$/), colors).optional(),
  dataLabels: z.enum(['none', 'value', 'percent', 'category-percent']).optional(),
  dataLabelPosition: z.enum(['center', 'inside-end', 'outside-end']).optional(), dataLabelFormat: text.optional(),
  axisTitles: z.object({ category: text.nullable().optional(), value: text.nullable().optional() }).strict().optional(),
  grouping: z.enum(['clustered', 'stacked', 'percentStacked']).optional(), gridlines: z.boolean().optional(),
  valueAxis: z.object({ min: z.number().finite().nullable().optional(), max: z.number().finite().nullable().optional() }).strict().optional(),
  gapWidthPct: z.number().int().min(0).max(500).optional(), holeSizePct: z.number().int().min(10).max(90).optional(),
  explosionPct: explosion.optional(), pointExplosions: z.record(z.string().regex(/^(0|[1-9][0-9]{0,3})$/), explosion).optional(),
}
const sourceSchema = z.discriminatedUnion('op', [
  z.object({ op: z.literal('add_chart'), sheetId: z.string(), chartType: z.enum(['column', 'bar', 'line', 'area', 'pie', 'doughnut', 'scatter', 'radar', 'combo']), dataRange: range, title: text.optional(), anchorCell: range.optional() }).strict(),
  z.object({ op: z.literal('edit_chart'), chartPath: z.string(), ...format,
    seriesData: z.array(z.object({ index: z.number().int().min(0).max(9999), name: text.optional(), valuesRange: range.optional(), categoriesRange: range.optional(), sheetId: z.string().optional() }).strict()).min(1).max(32).optional(),
  }).strict(),
])

function bounds(address: string, vector = false) {
  const [first, last = first!] = range.parse(address).split(':')
  const start = parseAddress(first!), end = parseAddress(last)
  const area = { startRow: start.row, startColumn: start.column, endRow: end.row, endColumn: end.column }
  if (start.row > end.row || start.column > end.column || end.row >= 1048576 || end.column >= 16384 || rangeCellCount(area) > 2000 || vector && start.row !== end.row && start.column !== end.column) throw new Error('workbook_ai_chart_source_invalid')
  return area
}
function values(sheet: SheetModel, address: string, vector = false) {
  const area = bounds(address, vector)
  return Array.from({ length: area.endRow-area.startRow+1 }, (_, row) => Array.from({ length: area.endColumn-area.startColumn+1 }, (_, column) => sheet.cells[formatAddress(row+area.startRow, column+area.startColumn)]?.value ?? null))
}
function reference(sheet: string, address: string) {
  const area = bounds(address, true)
  const absolute = (row: number, column: number) => formatAddress(row, column).replace(/^([A-Z]+)([0-9]+)$/, '$$$1$$$2')
  return `'${sheet.replaceAll("'", "''")}'!${absolute(area.startRow, area.startColumn)}:${absolute(area.endRow, area.endColumn)}`
}
function lengthOf(ref: string | undefined, cache: readonly unknown[] | undefined) {
  if (!ref) return cache?.length
  const address = ref.match(/!([A-Z$0-9:]+)$/)?.[1]?.replaceAll('$', '')
  if (!address) throw new Error('workbook_ai_chart_source_invalid')
  return rangeCellCount(bounds(address, true))
}

export async function applyChartSource(bytes: Uint8Array, raw: unknown): Promise<Uint8Array> {
  const operation = sourceSchema.parse(raw), model = await readWorkbook(bytes)
  const sheet = (name: string) => {
    const found = model.sheets.find(item => item.name === name)
    if (!found) throw new Error('workbook_ai_chart_source_invalid')
    return found
  }
  if (operation.op === 'add_chart') {
    const target = sheet(operation.sheetId), area = bounds(operation.dataRange)
    const addition = chartAdditionFromGrid({ sheetName: target.name, chartType: operation.chartType, ...(operation.title === undefined ? {} : { title: operation.title }), range: area, values: values(target, operation.dataRange) })
    const anchor = operation.anchorCell ? bounds(operation.anchorCell) : null
    if (anchor && rangeCellCount(anchor) !== 1) throw new Error('workbook_ai_chart_source_invalid')
    const fromRow = anchor?.startRow ?? addition.anchor.fromRow, fromColumn = anchor?.startColumn ?? addition.anchor.fromColumn
    if (fromRow+15 >= 1048576 || fromColumn+7 >= 16384) throw new Error('workbook_ai_chart_source_invalid')
    const series = operation.chartType === 'pie' ? addition.chart.series.slice(0, 1) : addition.chart.series
    return applyChartAdditions(bytes, [{ ...addition, chart: { ...addition.chart, series,
      title: operation.title ?? (series.length === 1 ? series[0]!.name : 'Chart Title'),
      ...(operation.chartType === 'column' || operation.chartType === 'bar' ? { dataLabels: 'value' as const } : {}),
    }, anchor: { ...addition.anchor, fromRow, fromColumn, toRow: fromRow+15, toColumn: fromColumn+7 } }])
  }
  const targets = model.sheets.flatMap(item => (item.charts ?? []).filter(chart => chart.chartPath === operation.chartPath).map(chart => ({ sheet: item, chart })))
  if (targets.length !== 1) throw new Error('workbook_ai_chart_target_invalid')
  const target = targets[0]!, { op: _op, chartPath, seriesData, ...formatEdit } = operation
  if (!seriesData && !Object.keys(formatEdit).length) throw new Error('workbook_ai_chart_source_invalid')
  const seen = new Set<number>()
  const series: ChartSeriesDataEdit[] = (seriesData ?? []).map(item => {
    const original = target.chart.series[item.index]
    if (!original || seen.has(item.index) || item.name === undefined && item.valuesRange === undefined && item.categoriesRange === undefined) throw new Error('workbook_ai_chart_source_invalid')
    seen.add(item.index)
    const dataSheet = sheet(item.sheetId ?? target.sheet.name)
    const numeric = item.valuesRange ? values(dataSheet, item.valuesRange, true).flat().map(value => typeof value === 'number' && Number.isFinite(value) ? value : typeof value === 'string' && value.trim() && Number.isFinite(Number(value)) ? Number(value) : 0) : undefined
    const categories = item.categoriesRange ? values(dataSheet, item.categoriesRange, true).flat().map(value => String(value ?? '')) : undefined
    const valueCount = numeric?.length ?? lengthOf(original.valuesRef, original.values)
    const categoryCount = categories?.length ?? lengthOf(original.categoriesRef, original.categories)
    if (valueCount !== undefined && categoryCount !== undefined && valueCount !== categoryCount) throw new Error('workbook_ai_chart_source_invalid')
    return { index: item.index, ...(item.name === undefined ? {} : { name: item.name }),
      ...(numeric ? { values: numeric, valuesRef: reference(dataSheet.name, item.valuesRange!) } : {}),
      ...(categories ? { categories, categoriesRef: reference(dataSheet.name, item.categoriesRange!) } : {}) }
  })
  return applyChartEdits(bytes, [{ chartPath, ...formatEdit, ...(seriesData ? { series } : {}) }])
}
