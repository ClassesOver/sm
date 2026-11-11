/** 固定源 editChartElement 的行列投影；宿主数据始终保持用户看到的方向。 */
export type ChartData = { categories: string[]; series: { name: string; values: number[] }[] }
export type ChartPointColors = Record<number, Record<number, string | null>>
/** 稀疏覆盖采用最终可见坐标；null显式恢复系列颜色。 */
export function validChartPointColors(value: unknown, seriesCount: number, categoryCount: number): value is ChartPointColors {
  const record = (item: unknown): item is Record<string, unknown> => !!item && typeof item === 'object' && !Array.isArray(item)
  const index = (key: string, count: number) => /^(0|[1-9]\d*)$/.test(key) && Number(key) < count
  return record(value) && Object.keys(value).length > 0 && Object.entries(value).every(([si, row]) =>
    index(si, seriesCount) && record(row) && Object.keys(row).length > 0 && Object.entries(row).every(([pi, color]) =>
      index(pi, categoryCount) && (color === null || typeof color === 'string' && /^#[\da-f]{6}$/i.test(color))))
}
export function transposeChartPointColors(colors: ChartPointColors): ChartPointColors {
  const result: ChartPointColors = {}
  for (const [si, row] of Object.entries(colors)) for (const [pi, color] of Object.entries(row)) (result[Number(pi)] ??= {})[Number(si)] = color
  return result
}
export function mergeChartPointColors(base: ChartPointColors = {}, patch: ChartPointColors = {}): ChartPointColors {
  const result: ChartPointColors = structuredClone(base)
  for (const [si, row] of Object.entries(patch)) result[Number(si)] = { ...result[Number(si)], ...row }
  return result
}
export function transposeChartData(data: ChartData): ChartData {
  return {
    categories: data.series.map(series => series.name),
    series: data.categories.map((name, index) => ({ name, values: data.series.map(series => series.values[index]!) })),
  }
}
