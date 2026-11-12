import type { ChartReadSpec } from '@sheets-web/xlsx-engine'
import type { UniverRenderingContext } from '@univerjs/engine-render'
import { chartTextValue, fitted, type Plot, type Worksheet } from './chart-legend'

/** Follow the source bar renderer's semantic roles: horizontal bars put the
 * category title on Y and the value title on X. Accept opposite-side positions
 * on the matching dimension, without treating legacy bar writer b/l positions
 * as a request to interchange category and value dimensions.
 */
export function paintAxisTitles(ctx: UniverRenderingContext, spec: ChartReadSpec, worksheet: Worksheet, outer: Plot): Plot {
  if (!spec.axes || outer.right - outer.left < 64 || outer.bottom - outer.top < 64) return outer
  const horizontal = spec.kind === 'bar'
  const entries = (['category', 'value'] as const).flatMap(role => {
    const axis = spec.axes![role]
    if (axis.hidden) return []
    const text = chartTextValue({literal:axis.title,reference:axis.titleRef,cache:axis.titleCache},worksheet).replace(/\s+/g,' ').trim()
    if (!text) return []
    const vertical = role === 'category' ? horizontal : !horizontal
    const side: keyof Plot = vertical ? axis.position === 'right' ? 'right' : 'left' : axis.position === 'top' ? 'top' : 'bottom'
    return [{text,side}]
  })
  if (!entries.length) return outer
  const plot = {...outer}
  for (const entry of entries) {
    if (entry.side === 'left' || entry.side === 'top') plot[entry.side] += 24
    else plot[entry.side] -= 24
  }
  for (const entry of entries) {
    const vertical = entry.side === 'left' || entry.side === 'right'
    const x = entry.side === 'left' ? outer.left + 12 : entry.side === 'right' ? outer.right - 12 : (plot.left + plot.right) / 2
    const y = entry.side === 'top' ? outer.top + 12 : entry.side === 'bottom' ? outer.bottom - 12 : (plot.top + plot.bottom) / 2
    ctx.save(); ctx.font = '11px system-ui'; ctx.fillStyle = '#1f2328'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.beginPath()
    if (vertical) ctx.rect(x - 12, plot.top, 24, plot.bottom - plot.top)
    else ctx.rect(plot.left, y - 12, plot.right - plot.left, 24)
    ctx.clip()
    const label = fitted(entry.text, (vertical ? plot.bottom - plot.top : plot.right - plot.left) - 8, text => ctx.measureText(text).width)
    if (vertical) { ctx.translate(x,y); ctx.rotate(entry.side === 'left' ? -Math.PI/2 : Math.PI/2); ctx.fillText(label,0,0) }
    else ctx.fillText(label,x,y)
    ctx.restore()
  }
  return plot
}
