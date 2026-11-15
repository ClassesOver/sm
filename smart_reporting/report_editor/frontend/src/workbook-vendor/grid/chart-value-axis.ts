import { numfmt } from '@univerjs/core'
import type { ChartReadSpec } from '@sheets-web/xlsx-engine'
import type { UniverRenderingContext } from '@univerjs/engine-render'
import type { Plot } from './chart-legend'
import type { BarValueScale } from './chart-value-scale'

export function valueTickText(value: number, format?: string): string {
  if (format && format !== 'General') {
    try {
      const text = numfmt.format(format, value, { throws: false })
      if (typeof text === 'string' && text) return text
    } catch { /* Keep a readable actual value when an external format is invalid. */ }
  }
  // Full integer labels follow the source, while tiny fractions must not be
  // rounded into a misleading zero. Do not abbreviate 10,000 as 10K.
  return Number.isInteger(value) ? value.toLocaleString('en-US', {maximumFractionDigits:0}) : String(Number(value.toPrecision(12)))
}

/** A numeric band inside the already reserved legend/title bands. Suppress
 * colliding labels without changing the domain or the positions of ticks.
 */
export function paintValueAxis(ctx: UniverRenderingContext, spec: ChartReadSpec, scale: BarValueScale, outer: Plot, numberFormat?: string): Plot {
  const axis = spec.axes?.value
  if (!axis || axis.hidden || outer.right - outer.left < 64 || outer.bottom - outer.top < 64) return outer
  const horizontal = spec.kind === 'bar'
  const side: keyof Plot = horizontal ? axis.position === 'top' ? 'top' : 'bottom' : axis.position === 'right' ? 'right' : 'left'
  ctx.save(); ctx.font = '9px system-ui'
  const labels = scale.ticks.map(value => {
    const text = valueTickText(value, numberFormat ?? axis.numberFormat)
    return {value, text, width:ctx.measureText(text).width}
  })
  const widest = Math.max(0,...labels.map(label => label.width))
  const reserve = horizontal ? 20 : widest + 8
  // Never truncate a number into a different value to force it to fit.
  if (widest > outer.right - outer.left - 8 || !horizontal && reserve > (outer.right - outer.left) * 0.4) { ctx.restore(); return outer }
  const plot = {...outer}
  if (side === 'top' || side === 'left') plot[side] += reserve
  else plot[side] -= reserve
  const width = plot.right - plot.left, height = plot.bottom - plot.top
  const coordinate = (value: number) => horizontal ? plot.left + width * scale.fraction(value) : plot.bottom - height * scale.fraction(value)
  const edge = side === 'top' ? plot.top : side === 'bottom' ? plot.bottom : side === 'right' ? plot.right : plot.left
  const direction = side === 'top' || side === 'left' ? -1 : 1
  ctx.strokeStyle = '#6e7781'; ctx.lineWidth = 0.75
  ctx.beginPath()
  if (horizontal) { ctx.moveTo(plot.left,edge); ctx.lineTo(plot.right,edge) }
  else { ctx.moveTo(edge,plot.top); ctx.lineTo(edge,plot.bottom) }
  for (const label of labels) {
    const position = coordinate(label.value)
    if (horizontal) { ctx.moveTo(position,edge); ctx.lineTo(position,edge+direction*3) }
    else { ctx.moveTo(edge,position); ctx.lineTo(edge+direction*3,position) }
  }
  ctx.stroke()
  // The zero line uses exactly the same clamped mapping as the bars.
  if (scale.min < 0 && scale.max > 0) {
    const zero = coordinate(0)
    ctx.beginPath(); ctx.strokeStyle = '#c5ccd3'
    if (horizontal) {ctx.moveTo(zero,plot.top);ctx.lineTo(zero,plot.bottom)}
    else {ctx.moveTo(plot.left,zero);ctx.lineTo(plot.right,zero)}
    ctx.stroke()
  }
  ctx.fillStyle = '#1f2328'; ctx.textBaseline = 'middle'
  ctx.textAlign = horizontal ? 'center' : side === 'left' ? 'right' : 'left'
  ctx.beginPath(); ctx.rect(outer.left,outer.top,outer.right-outer.left,outer.bottom-outer.top); ctx.clip()
  let previousEnd = -Infinity
  // Sort screen positions, so reverse orientation has the same collision rule.
  const positioned = labels.map(label => {
    const position = coordinate(label.value)
    const center = horizontal ? Math.max(plot.left+label.width/2,Math.min(plot.right-label.width/2,position)) : Math.max(plot.top+5,Math.min(plot.bottom-5,position))
    const half = horizontal ? label.width/2 : 5
    return {...label,center,start:center-half,end:center+half}
  }).sort((a,b)=>a.start-b.start)
  for (const label of positioned) {
    if (label.start < previousEnd + 4) continue
    const x = horizontal ? label.center : edge+direction*6
    const y = horizontal ? edge+direction*11 : label.center
    ctx.fillText(label.text,x,y)
    previousEnd = label.end
  }
  ctx.restore()
  return plot
}
