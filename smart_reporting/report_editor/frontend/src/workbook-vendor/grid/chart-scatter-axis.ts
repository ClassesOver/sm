import type { ChartReadSpec } from '@sheets-web/xlsx-engine'
import type { UniverRenderingContext } from '@univerjs/engine-render'
import { numfmt } from '@univerjs/core'
import { chartTextValue, fitted, type Plot, type Worksheet } from './chart-legend'
import type { BarValueScale } from './chart-value-scale'

/** Scatter 的 Y 刻度与数值标签沿用固定源的值格式；X 刻度保留独立精度。 */
export function scatterValueText(value: number, format?: string): string {
  if (format && format !== 'General' && !format.includes('%')) {
    try {
      const text = numfmt.format(format, value, { throws: false })
      if (typeof text === 'string' && text !== '') return text
    } catch { /* 无效来源格式回退实际数值。 */ }
  }
  if (format?.includes('%')) return `${Math.round(value * 100)}%`
  return Number(value.toPrecision(12)).toLocaleString('en-US', { maximumFractionDigits: 4 })
}

function xTickText(value: number, format?: string): string {
  if (format && format !== 'General') {
    try {
      const text = numfmt.format(format, value, { throws: false })
      if (typeof text === 'string') return text
    } catch { /* 保留源 Scatter 的四位有效数字回退。 */ }
  }
  return Number.isInteger(value) || Math.abs(value) >= 1e4
    ? scatterValueText(value) : String(Number(value.toPrecision(4)))
}

/** 单独保留 Scatter 的底/左标题及隐藏轴网格语义，不改变其它图族。 */
export function paintScatterAxes(ctx: UniverRenderingContext, spec: ChartReadSpec, worksheet: Worksheet,
  outer: Plot, boundsX: Pick<BarValueScale, 'min' | 'max' | 'ticks'>, boundsY: Pick<BarValueScale, 'min' | 'max' | 'ticks'>,
  valueLabels: readonly string[] = []) {
  const xAxis = spec.axes?.category, yAxis = spec.axes?.value
  const title = (axis: typeof xAxis) => chartTextValue({ literal: axis?.title, reference: axis?.titleRef, cache: axis?.titleCache }, worksheet).replace(/\s+/g, ' ').trim()
  const xTitle = title(xAxis), yTitle = title(yAxis)
  const units = yAxis?.displayUnit ? yAxis.displayUnitLabel ?? '' : ''
  const xFormat = xAxis?.numberFormat ?? spec.series[0]?.categoryNumberFormat
  const yFormat = yAxis?.numberFormat ?? spec.series[0]?.numberFormat
  ctx.save(); ctx.font = '9px system-ui'
  const xLabels = boundsX.ticks.map(value => ({ value, text: xTickText(value / (xAxis?.displayUnit || 1), xFormat) }))
  const yLabels = boundsY.ticks.map(value => ({ value, text: scatterValueText(value / (yAxis?.displayUnit || 1), yFormat) }))
  const measure = (text: string) => ctx.measureText(text).width
  const titleBand = yTitle ? 22 : 0, unitsBand = units ? 18 : 0
  const xHalf = Math.max(Math.max(0, ...xLabels.map(label => measure(label.text) / 2)),
    valueLabels.reduce((half, text) => Math.max(half, measure(text) / 2), 0)) + 1
  const yBand = Math.max(0, ...yLabels.map(label => measure(label.text))) + 8
  const width = outer.right - outer.left, height = outer.bottom - outer.top
  const left = Math.min(width * 0.6, Math.max(xHalf, titleBand + unitsBand + yBand))
  const right = Math.min(width * 0.2, xHalf)
  const bottom = Math.min(height * 0.45, 20 + (xTitle ? 20 : 0))
  const plot = { left: outer.left + left, right: outer.right - right, top: outer.top + (spec.dataLabels?.showValue ? 18 : 5), bottom: outer.bottom - bottom }
  const xAt = (value: number) => plot.left + (plot.right - plot.left) * Math.max(0, Math.min(1, (value - boundsX.min) / (boundsX.max - boundsX.min)))
  const yAt = (value: number) => plot.bottom - (plot.bottom - plot.top) * Math.max(0, Math.min(1, (value - boundsY.min) / (boundsY.max - boundsY.min)))
  ctx.strokeStyle = '#e3e3e3'; ctx.lineWidth = 1
  yLabels.forEach((label, index) => {
    if ((spec.design?.gridlines ?? yAxis?.majorGridlines) === false && index !== 0) return
    const y = yAt(label.value)
    ctx.beginPath(); ctx.moveTo(plot.left, y); ctx.lineTo(plot.right, y); ctx.stroke()
  })
  if (xAxis?.majorGridlines) xLabels.forEach(label => {
    const x = xAt(label.value)
    ctx.beginPath(); ctx.moveTo(x, plot.top); ctx.lineTo(x, plot.bottom); ctx.stroke()
  })
  ctx.fillStyle = '#1f2328'; ctx.strokeStyle = '#6e7781'; ctx.lineWidth = 0.75
  if (!xAxis?.hidden) {
    ctx.beginPath(); ctx.moveTo(plot.left, plot.bottom); ctx.lineTo(plot.right, plot.bottom)
    xLabels.forEach(label => { const x = xAt(label.value); ctx.moveTo(x, plot.bottom); ctx.lineTo(x, plot.bottom + 3) })
    ctx.stroke(); ctx.textAlign = 'center'; ctx.textBaseline = 'top'
    xLabels.forEach(label => {
      const x = xAt(label.value), half = measure(label.text) / 2
      if (x - half >= outer.left && x + half <= outer.right) ctx.fillText(label.text, x, plot.bottom + 5)
    })
  }
  if (!yAxis?.hidden) {
    ctx.beginPath(); ctx.moveTo(plot.left, plot.top); ctx.lineTo(plot.left, plot.bottom)
    yLabels.forEach(label => { const y = yAt(label.value); ctx.moveTo(plot.left, y); ctx.lineTo(plot.left - 3, y) })
    ctx.stroke(); ctx.textAlign = 'right'; ctx.textBaseline = 'middle'
    yLabels.forEach(label => {
      if (measure(label.text) + 5 <= left - titleBand - unitsBand) ctx.fillText(label.text, plot.left - 5, yAt(label.value))
    })
  }
  const paintTitle = (text: string, x: number, y: number, vertical: boolean, font: number, limit: number) => {
    ctx.save(); ctx.font = `${font}px system-ui`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    const label = fitted(text.length > limit ? text.slice(0, limit - 1) + '…' : text,
      (vertical ? plot.bottom - plot.top : plot.right - plot.left) - 4, measure)
    if (vertical) { ctx.translate(x, y); ctx.rotate(-Math.PI / 2); ctx.fillText(label, 0, 0) }
    else ctx.fillText(label, x, y)
    ctx.restore()
  }
  if (xTitle) paintTitle(xTitle, (plot.left + plot.right) / 2, outer.bottom - 5, false, 11, 60)
  if (yTitle) paintTitle(yTitle, outer.left + 11, (plot.top + plot.bottom) / 2, true, 11, 40)
  if (units) paintTitle(units, outer.left + titleBand + 9, (plot.top + plot.bottom) / 2, true, 9, 500)
  ctx.restore()
  return { plot, xAt, yAt }
}
