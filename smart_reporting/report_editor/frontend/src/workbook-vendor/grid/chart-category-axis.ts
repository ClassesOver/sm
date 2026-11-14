import {parseRange, type ChartReadSpec} from '@sheets-web/xlsx-engine'
import type {UniverRenderingContext} from '@univerjs/engine-render'
import {fitted, type Plot, type Worksheet} from './chart-legend'
import {valueTickText} from './chart-value-axis'

type Series = ChartReadSpec['series'][number]
const MAX_LABELS = 10000

/** One-dimensional same-sheet references use live cells, including blanks.
 * Other/unreadable references use their original indexed cache, never cells
 * at the same address in the active worksheet. No category block uses ordinals.
 */
export function chartCategoryLabels(series: Series | undefined, worksheet: Worksheet, count: number, format?: string): Array<string | null> {
  if (!series || count > MAX_LABELS) return []
  const formatValue = (value: unknown): string | null => {
    if (value === null || value === undefined || value === '') return null
    const code = format ?? series.categoryNumberFormat
    if (typeof value === 'number') return Number.isFinite(value) ? valueTickText(value,code) : null
    if (typeof value === 'string') return code && Number.isFinite(Number(value)) ? valueTickText(Number(value),code) : value
    return typeof value === 'boolean' ? String(value) : null
  }
  if (series.categoriesRef) {
    const match = /^(?:(?:'((?:[^']|'')+)'|([^'!\[\]]+))!)?(\$?[A-Z]+\$?[1-9]\d*(?::\$?[A-Z]+\$?[1-9]\d*)?)$/i.exec(series.categoriesRef)
    const name = match?.[1]?.replaceAll("''", "'") ?? match?.[2]
    if (match && (!name || name.toLowerCase() === worksheet.getName?.().toLowerCase())) {
      try {
        const range = parseRange(match[3]!.replaceAll('$','').toUpperCase())
        const rows = range.endRow-range.startRow+1, columns = range.endColumn-range.startColumn+1
        if ((rows === 1 || columns === 1) && rows*columns <= MAX_LABELS) {
          return Array.from({length:count},(_,index)=>index >= rows*columns ? null : formatValue(worksheet.getCell(range.startRow+(rows===1?0:index),range.startColumn+(columns===1?0:index))?.v))
        }
      } catch { /* An unreadable reference may still have a trustworthy cache. */ }
    }
  }
  if (series.categories !== undefined) return Array.from({length:count},(_,index)=>formatValue(series.categories?.[index]))
  return Array.from({length:count},(_,index)=>series.categoriesRef ? null : String(index+1))
}

// Source rowSlot/seriesSlot: horizontal minMax is bottom-up, maxMin is
// top-down; column maxMin mirrors both categories and series inside a group.
export function chartCategorySlot(spec: ChartReadSpec, index: number, count: number): number {
  const axis = spec.axes?.category
  const reversed = axis && (spec.kind === 'bar' ? !axis.reversed : spec.kind === 'column' && axis.reversed)
  return reversed ? count-1-index : index
}

export function planCategoryAxis(ctx: UniverRenderingContext, spec: ChartReadSpec, worksheet: Worksheet, count: number, outer: Plot): {plot: Plot; paint(plot: Plot): void} {
  const empty = {plot:outer,paint:(_plot: Plot)=>{}}
  const axis = spec.axes?.category
  if (!axis || axis.hidden || count < 1 || count > MAX_LABELS || outer.right-outer.left < 64 || outer.bottom-outer.top < 64) return empty
  const horizontal = spec.kind === 'column' || spec.kind === 'line' || spec.kind === 'area'
  const side: keyof Plot = horizontal ? axis.position === 'top' ? 'top' : 'bottom' : axis.position === 'right' ? 'right' : 'left'
  const primary = spec.series[0]
  const labels = chartCategoryLabels(primary,worksheet,count,axis.numberFormat)
  const groups = spec.kind === 'bar' || spec.kind === 'column' ? primary?.categoryGroups ?? [] : []
  if (!labels.some(Boolean) && !groups.length) return empty
  ctx.save(); ctx.font = '10px system-ui'
  const measure = (text: string) => ctx.measureText(text).width
  const width = outer.right-outer.left
  const labelReserve = horizontal ? 20 : Math.min(width*0.3,Math.max(16,...labels.map(text=>text?measure(text.slice(0,500))+10:0)))
  const reserve = labelReserve + (groups.length ? horizontal ? 22 : 54 : 0)
  ctx.restore()
  const plot = {...outer}
  if (side === 'top' || side === 'left') plot[side] += reserve
  else plot[side] -= reserve
  return {plot,paint(finalPlot: Plot){
    const edge = finalPlot[side], direction = side === 'left' || side === 'top' ? -1 : 1
    const extent = horizontal ? finalPlot.right-finalPlot.left : finalPlot.bottom-finalPlot.top
    const band = extent/count
    ctx.save(); ctx.font = '10px system-ui'; ctx.fillStyle = '#1f2328'
    ctx.textBaseline = 'middle'; ctx.textAlign = horizontal ? 'center' : side === 'left' ? 'right' : 'left'
    ctx.beginPath()
    if (horizontal) ctx.rect(finalPlot.left,side==='top'?outer.top:edge,finalPlot.right-finalPlot.left,reserve)
    else ctx.rect(side==='left'?outer.left:edge,finalPlot.top,reserve,finalPlot.bottom-finalPlot.top)
    ctx.clip()
    const stride = Math.max(1,Math.ceil(14/band))
    labels.forEach((text,index)=>{
      const slot = chartCategorySlot(spec,index,count)
      if (!text || slot%stride) return
      const label = fitted(text.replace(/\s+/g,' ').trim(),horizontal ? band-6 : reserve-10,measure)
      if (!label) return
      const lineLike = spec.kind === 'line' || spec.kind === 'area'
      const x = horizontal
        ? lineLike ? finalPlot.left + extent * slot / Math.max(1,count-1) : finalPlot.left+band*(slot+0.5)
        : edge+direction*6
      const y = horizontal ? edge+direction*11 : finalPlot.top+band*(slot+0.5)
      ctx.fillText(label,x,y)
    })
    if (groups.length) {
      const slotAt = (index: number): number => chartCategorySlot(spec,index,count)
      ctx.font = '10px system-ui'; ctx.strokeStyle = '#d9d9d9'; ctx.lineWidth = 1
      ctx.beginPath()
      groups.forEach(group => {
        if (group.start < 0 || group.end > count || group.start >= group.end) return
        const first = slotAt(group.start), last = slotAt(group.end - 1)
        const start = Math.min(first,last), end = Math.max(first,last)+1
        if (horizontal) {
          const xStart = finalPlot.left + extent * start / count
          const xEnd = finalPlot.left + extent * end / count
          const y1 = edge + direction * 22, y2 = edge + direction * reserve
          ctx.moveTo(xStart,y1); ctx.lineTo(xStart,y2); ctx.moveTo(xEnd,y1); ctx.lineTo(xEnd,y2)
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
          ctx.fillText(fitted(group.label,xEnd-xStart-6,measure),(xStart+xEnd)/2,edge+direction*31)
        } else {
          const yStart = finalPlot.top + extent * start / count
          const yEnd = finalPlot.top + extent * end / count
          const x1 = edge + direction * labelReserve, x2 = edge + direction * reserve
          ctx.moveTo(x1,yStart); ctx.lineTo(x2,yStart); ctx.moveTo(x1,yEnd); ctx.lineTo(x2,yEnd)
          const x = edge + direction * (labelReserve + 27), y = (yStart+yEnd)/2
          const label = fitted(group.label,Math.max(0,yEnd-yStart-6),measure)
          if (label) {
            ctx.save(); ctx.translate(x,y); ctx.rotate(-Math.PI/2)
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(label,0,0); ctx.restore()
          }
        }
      })
      ctx.stroke()
    }
    ctx.restore()
  }}
}
