import type { ChartReadSpec } from '@sheets-web/xlsx-engine'
import type { UniverRenderingContext } from '@univerjs/engine-render'
import type { Plot, Worksheet } from './chart-legend'
import { numfmt } from '@univerjs/core'
import { chartCategoryLabels } from './chart-category-axis'
import { valueTickText } from './chart-value-axis'

type PieGeometry = { cx: number; cy: number; radius: number; innerRadius: number }
type Label = { index: number; x: number; y: number; cx: number; cy: number; inside: boolean; right: boolean; lines: string[]; font: string; size: number; color: string; angle: number }

/** 固定源 WorkbookVisuals.pieSliceLabels：保留点索引，份额按非负可见值计算，
 * 0.5% 以下不标注；9% 起默认内标，其余外标并绘引导线。调用方在打孔后绘制，
 * 并为外标预留图框内空间；超出边界、碰撞、复杂自定义标签不冒充支持。
 */
export function paintPieDataLabels(ctx: UniverRenderingContext, spec: ChartReadSpec, values: ReadonlyArray<number | null>, worksheet: Worksheet, geometry: PieGeometry, plot: Plot): void {
  const series = spec.series[0]
  if (!series || values.length > 500 || !['pie', 'doughnut'].includes(spec.kind)) return
  const normalized = values.map(value => value !== null && Number.isFinite(value) ? Math.max(0, value) : 0)
  const total = normalized.reduce((sum, value) => sum + value, 0)
  if (!(total > 0) || !Number.isFinite(total) || !(geometry.radius > 0)) return
  const categories = chartCategoryLabels(series, worksheet, values.length)
  const { cx, cy, radius, innerRadius } = geometry
  const labels: Label[] = []
  let cursor = 0
  normalized.forEach((value, index) => {
    const share = value / total, angle = (cursor + share / 2) * Math.PI * 2
    cursor += share
    if (share < 0.005) return
    const layers = [spec.dataLabels, series.dataLabels, spec.dataLabels?.points?.[index], series.dataLabels?.points?.[index]]
    if (layers.some(layer => layer?.unsupported)) return
    const setting = Object.assign({}, ...layers)
    if (setting.deleted) return
    const style = Object.assign({}, ...layers.map(layer => layer?.style))
    const lines: string[] = []
    if (setting.showCategory) {
      const text = categories[index] ?? ''
      if (text) lines.push(text.length > 12 ? `${text.slice(0, 12)}…` : text)
    }
    if (setting.showValue) {
      const text = valueTickText(value, setting.numberFormat && setting.numberFormat !== 'General' ? setting.numberFormat : series.numberFormat)
      if (text) lines.push(text)
    }
    if (setting.showPercent) {
      let text = `${Math.round(share * 100)}%`
      if (setting.numberFormat?.includes('%')) {
        try { const formatted = numfmt.format(setting.numberFormat, share, { throws: false }); if (typeof formatted === 'string') text = formatted.trim() } catch { /* 无效外部格式沿用整数百分比。 */ }
      }
      if (text) lines.push(text)
    }
    if (!lines.length) return
    const inside = setting.position === 'outside-end' ? false : setting.position !== undefined || share >= 0.09
    const size = style.sizePt === undefined ? inside ? 11 : 10 : style.sizePt * 4 / 3
    if (!(size > 0) || !Number.isFinite(size)) return
    const distance = inside ? innerRadius > 0 ? (radius + innerRadius) / 2
      : radius * (setting.position === 'inside-end' ? 0.8 : setting.position === 'center' ? 0.5 : 0.62) : radius * 1.1
    const right = Math.sin(angle) >= 0
    const shift = Math.min(100, Math.max(0, series.pointExplosions?.[index] ?? series.explosionPct ?? 0)) / 100 * radius * 0.4
    const sliceX = cx + Math.sin(angle) * shift, sliceY = cy - Math.cos(angle) * shift
    labels.push({ index, angle, inside, right, lines, size, cx: sliceX, cy: sliceY, font: `${style.bold ? 'bold ' : ''}${size}px system-ui`,
      color: style.color ?? (inside ? '#ffffff' : '#1f2328'),
      x: sliceX + Math.sin(angle) * distance + (inside ? 0 : right ? 13 : -13), y: sliceY - Math.cos(angle) * distance })
  })
  for (const right of [true, false]) {
    const side = labels.filter(label => !label.inside && label.right === right).sort((a, b) => a.y - b.y)
    for (let index = 1; index < side.length; index++) {
      const previous = side[index - 1]!, current = side[index]!
      const gap = Math.max(15, (previous.lines.length * previous.size + current.lines.length * current.size) * 0.6)
      current.y = Math.max(current.y, previous.y + gap)
    }
  }
  const painted: Plot[] = []
  ctx.save(); ctx.textBaseline = 'middle'
  ctx.beginPath(); ctx.rect(plot.left, plot.top, plot.right - plot.left, plot.bottom - plot.top); ctx.clip()
  for (const label of labels) {
    ctx.font = label.font
    const width = Math.max(...label.lines.map(text => ctx.measureText(text).width)), lineHeight = label.size * 1.2
    const height = label.lines.length * lineHeight
    const left = label.inside ? label.x - width / 2 : label.right ? label.x : label.x - width
    const box = { left, right: left + width, top: label.y - height / 2, bottom: label.y + height / 2 }
    if (!Number.isFinite(width) || !(width > 0) || box.left < plot.left || box.right > plot.right || box.top < plot.top || box.bottom > plot.bottom) continue
    if (painted.some(other => box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top)) continue
    if (!label.inside) {
      ctx.strokeStyle = '#9a9a9a'; ctx.lineWidth = 1; ctx.beginPath()
      ctx.moveTo(label.cx + Math.sin(label.angle) * radius, label.cy - Math.cos(label.angle) * radius)
      ctx.lineTo(label.cx + Math.sin(label.angle) * radius * 1.1, label.cy - Math.cos(label.angle) * radius * 1.1)
      ctx.lineTo(label.x + (label.right ? -3 : 3), label.y); ctx.stroke()
    }
    ctx.fillStyle = label.color; ctx.textAlign = label.inside ? 'center' : label.right ? 'left' : 'right'
    label.lines.forEach((text, index) => ctx.fillText(text, label.x, box.top + lineHeight * (index + 0.5)))
    painted.push(box)
  }
  ctx.restore()
}
