/// Chart selection parsing, extracted from genoffice chart-visual.ts (the
/// chartDataFromValues subset used by chart recommendation): detects header
/// row / category column / series orientation from a raw value grid. The rest
/// of chart-visual (renderer visual state) stays desktop-only.

export type ChartGridValue = string | number | boolean | null | undefined

export interface ParsedChartData {
  /// Series run along rows (selection at least as wide as tall, Excel's
  /// default). In that orientation hasHeaderRow refers to the first
  /// COLUMN (series names), hasCategoryColumn to the first ROW, and each
  /// series' `column` is its row offset within the selection.
  readonly byRow: boolean
  readonly hasHeaderRow: boolean
  readonly hasCategoryColumn: boolean
  readonly categories: string[]
  /// Offset within the selection along the series axis (for range refs).
  readonly series: { name: string; values: number[]; column: number }[]
}

const MAX_CHART_ROWS = 500
const MAX_CHART_SERIES = 12

/// First row with non-numeric labels → header row; first column mostly
/// non-numeric → category column; every other column becomes a series.
/// Excel's default orientation puts the series along the shorter dimension:
/// a selection at least as wide as it is tall charts each ROW as a series.
/// Transposing up front lets the column-wise logic serve both.
export function chartDataFromValues(
  source: readonly (readonly ChartGridValue[])[],
  options?: {
    /// Scatter: the first data vector is the X axis even when numeric,
    /// so it must become the category vector instead of a Y series.
    numericCategoryColumn?: boolean
  },
): ParsedChartData | null {
  const sourceFirstRow = source[0]
  if (!sourceFirstRow || sourceFirstRow.length === 0) return null
  const byRow = sourceFirstRow.length > 1 && source.length <= sourceFirstRow.length
  const grid = byRow
    ? sourceFirstRow.map((_unused, column) => source.map((row) => row[column] ?? null))
    : source
  const firstRow = grid[0]
  if (!firstRow || firstRow.length === 0) return null
  const isBlank = (v: unknown): boolean => v === null || v === undefined || v === ''
  const isNumeric = (v: unknown): boolean =>
    (typeof v === 'number' && Number.isFinite(v)) ||
    (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v)))
  const toNumber = (v: unknown): number =>
    isNumeric(v) ? Number(v) : 0
  const width = firstRow.length
  // A header row is signalled by non-numeric labels, or by the cross-tab
  // fingerprint Excel also uses: blank corner cell with filled cells across
  // the rest of the first row (numeric headers — years, months — are data
  // otherwise).
  const hasLabelHeader =
    grid.length > 1 &&
    firstRow.some((v, i) => (width === 1 || i > 0) && !isBlank(v) && !isNumeric(v))
  const hasCrossTabHeader =
    grid.length > 1 &&
    width > 1 &&
    isBlank(firstRow[0]) &&
    firstRow.every((v, i) => i === 0 || !isBlank(v))
  const hasHeaderRow = hasLabelHeader || hasCrossTabHeader
  const body = (hasHeaderRow ? grid.slice(1) : grid).slice(0, MAX_CHART_ROWS)
  if (body.length === 0) return null
  // The blank-corner fingerprint marks the first column as the category axis
  // even when its labels are numeric (years down the side).
  const hasCategoryColumn =
    width > 1 &&
    (hasCrossTabHeader ||
      body.some((row) => !isBlank(row[0]) && !isNumeric(row[0])) ||
      (options?.numericCategoryColumn === true && body.some((row) => isNumeric(row[0]))))
  const categories = body.map((row, i) =>
    hasCategoryColumn ? String(row[0] ?? '') : String(i + 1),
  )
  const series: ParsedChartData['series'] = []
  for (let column = hasCategoryColumn ? 1 : 0; column < width; column++) {
    if (!body.some((row) => isNumeric(row[column]))) continue
    const header = hasHeaderRow ? firstRow[column] ?? null : null
    series.push({
      name: isBlank(header) ? `Series ${series.length + 1}` : String(header),
      values: body.map((row) => toNumber(row[column])),
      column,
    })
    if (series.length >= MAX_CHART_SERIES) break
  }
  // A mixed first column (labels plus numbers) gets claimed as the category
  // axis; when every other column is text that claim starves the chart even
  // though Excel still plots the numbers — chart it as the value series.
  if (series.length === 0 && hasCategoryColumn && body.some((row) => isNumeric(row[0]))) {
    const header = hasHeaderRow ? firstRow[0] ?? null : null
    return {
      byRow,
      hasHeaderRow,
      hasCategoryColumn: false,
      categories: body.map((_unused, i) => String(i + 1)),
      series: [
        {
          name: isBlank(header) ? 'Series 1' : String(header),
          values: body.map((row) => toNumber(row[0])),
          column: 0,
        },
      ],
    }
  }
  return series.length > 0 ? { byRow, hasHeaderRow, hasCategoryColumn, categories, series } : null
}
