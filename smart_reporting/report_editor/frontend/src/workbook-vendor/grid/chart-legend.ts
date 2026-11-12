import { parseRange, type ChartReadSpec } from '@sheets-web/xlsx-engine'
import type { UniverRenderingContext } from '@univerjs/engine-render'

type Series = ChartReadSpec['series'][number]
export type Worksheet = { getName?(): string; getCell(row: number, column: number): { v?: unknown } | null | undefined }
export type Plot = { left: number; top: number; right: number; bottom: number }
export const CHART_PALETTE = ['#4472c4', '#ed7d31', '#a5a5a5', '#ffc000', '#5b9bd5', '#70ad47']
export const chartSeriesColor = (series: Series, index: number) => series.color ?? CHART_PALETTE[index % CHART_PALETTE.length]!

export function chartLegendName(series: Series, index: number, worksheet: Worksheet): string {
  return chartTextValue({literal:series.name,reference:series.nameRef,cache:series.nameCache},worksheet,`系列 ${index + 1}`)
}

export function chartTextValue(text: {literal?:string;reference?:string;cache?:string}, worksheet: Worksheet, fallback = ''): string {
  if (!text.reference) return text.literal || fallback
  // Resolve only an actual single-cell reference in this worksheet. A literal
  // name that resembles an address stays literal; external refs are never read.
  const ref = /^(?:(?:'((?:[^']|'')+)'|([^'!\[\]]+))!)?(\$?[A-Z]+\$?[1-9]\d*)$/.exec(text.reference)
  if (ref && (!ref[1] && !ref[2] || (ref[1]?.replaceAll("''", "'") ?? ref[2]) === worksheet.getName?.())) {
    try {
      const range = parseRange(ref[3]!)
      const value = worksheet.getCell(range.startRow, range.startColumn)?.v
      if (value === null || value === undefined || value === '') return fallback
      if (typeof value === 'string' && value || typeof value === 'number' && Number.isFinite(value) || typeof value === 'boolean') return String(value)
    } catch { /* Keep the original cached label when the reference is unreadable. */ }
  }
  return text.cache || fallback
}

export function fitted(text: string, width: number, measure: (value: string) => number): string {
  if (width <= 0 || measure('…') > width) return ''
  if (text.length <= 500 && measure(text) <= width) return text
  let low = 0, high = Math.min(500, text.length)
  while (low < high) {
    const middle = Math.ceil((low + high) / 2)
    if (measure(text.slice(0, middle) + '…') <= width) low = middle
    else high = middle - 1
  }
  return text.slice(0, low) + '…'
}

/** Common automatic bar/column legends. Reserve plot space unless overlay=1;
 * bound labels/entry counts to the frame and expose omissions with … +N.
 */
export function paintChartLegend(ctx: UniverRenderingContext, spec: ChartReadSpec, worksheet: Worksheet, plot: Plot): Plot {
  if (!spec.legend || plot.right - plot.left < 64 || plot.bottom - plot.top < 50) return plot
  // Noncanonical series identities plus legend exceptions need their own
  // OOXML ordering reconciliation. Do not guess which label to suppress.
  if (spec.legend.hiddenEntries.length && spec.series.some((series, index) => series.index !== undefined && series.index !== index)) return plot
  const entries = spec.series.map((series, index) => ({
    label: chartLegendName(series, index, worksheet), color: chartSeriesColor(series, index), index: series.index ?? index,
  })).filter(entry => !spec.legend!.hiddenEntries.includes(entry.index))
  if (!entries.length) return plot
  ctx.save()
  ctx.font = '11px system-ui'; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic'
  const measure = (value: string) => ctx.measureText(value).width
  const horizontal = spec.legend.position === 'top' || spec.legend.position === 'bottom'
  const width = plot.right - plot.left, height = plot.bottom - plot.top
  const capacity = horizontal ? Math.max(1, Math.floor(width / 56)) : Math.max(1, Math.floor(height / 16))
  const items: Array<{ label: string; color?: string }> = entries.length <= capacity ? entries : [
    ...entries.slice(0, capacity - 1), { label: `… +${entries.length - capacity + 1}` },
  ]
  const legendWidth = horizontal ? width : Math.min(width * 0.4, Math.max(28, ...items.map(item => measure(item.label.slice(0, 500)) + 20)))
  const legendHeight = horizontal ? 16 : items.length * 16
  const left = spec.legend.position === 'left' || horizontal ? plot.left : plot.right - legendWidth
  const top = spec.legend.position === 'bottom' ? plot.bottom - legendHeight
    : spec.legend.position === 'top' || spec.legend.position === 'top-right' ? plot.top
    : plot.top + (height - legendHeight) / 2
  ctx.beginPath(); ctx.rect(left, top, legendWidth, legendHeight); ctx.clip()
  ctx.fillStyle = '#ffffff'; ctx.fillRect(left, top, legendWidth, legendHeight)
  const cellWidth = horizontal ? legendWidth / items.length : legendWidth
  items.forEach((item, index) => {
    const x = left + (horizontal ? index * cellWidth : 0), y = top + (horizontal ? 0 : index * 16)
    if (item.color) { ctx.fillStyle = item.color; ctx.fillRect(x, y + 4, 8, 8) }
    ctx.fillStyle = '#1f2328'
    ctx.fillText(fitted(item.label, cellWidth - 18, measure), x + 14, y + 12)
  })
  ctx.restore()
  if (spec.legend.overlay) return plot
  return {
    left: plot.left + (spec.legend.position === 'left' ? legendWidth + 8 : 0),
    right: plot.right - (!horizontal && spec.legend.position !== 'left' ? legendWidth + 8 : 0),
    top: plot.top + (spec.legend.position === 'top' ? legendHeight + 8 : 0),
    bottom: plot.bottom - (spec.legend.position === 'bottom' ? legendHeight + 8 : 0),
  }
}
