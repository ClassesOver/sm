/// Chart render extension (图表网格渲染 v1): draws anchored column/bar/line/
/// pie charts on the canvas, the same way the sparkline extension works. The
/// spec store is injected before createWorkbook so the first paint includes
/// charts. Series references resolve against the live worksheet, so value
/// edits flow into the picture on repaint.

import type { ChartReadSpec } from '@sheets-web/xlsx-engine'
import { parseRange } from '@sheets-web/xlsx-engine'
import type { IRange, IScale } from '@univerjs/core'
import type { IDrawInfo, SpreadsheetSkeleton, UniverRenderingContext } from '@univerjs/engine-render'
import {
  SheetExtension,
  SpreadsheetExtensionRegistry,
} from '@univerjs/engine-render'
import { CHART_PALETTE, chartSeriesColor, fitted, paintChartLegend } from './chart-legend'
import { paintAxisTitles } from './chart-axis-titles'
import { barValueScale } from './chart-value-scale'
import { paintValueAxis } from './chart-value-axis'
import { chartCategorySlot, planCategoryAxis } from './chart-category-axis'

const store = new Map<string, ReadonlyArray<ChartReadSpec>>()

export function setCharts(
  unitId: string,
  sheetId: string,
  specs: ReadonlyArray<ChartReadSpec> | undefined,
): void {
  const key = `${unitId}::${sheetId}`
  if (specs === undefined || specs.length === 0) store.delete(key)
  else store.set(key, specs)
}

;(window as unknown as { __sheetsWebCharts?: unknown }).__sheetsWebCharts = {
  store,
  draws: 0,
}

const CHART_UKEY = 'sheets-web-chart'
const EXTENSION_Z_INDEX = 32
const PALETTE = CHART_PALETTE

interface SkeletonLike {
  worksheet?: {
    getName?: () => string
    getUnitId?: () => string
    getSheetId?: () => string
    getCell(row: number, column: number): { v?: unknown } | null | undefined
  } | null
  getCellWithCoordByIndex(
    row: number,
    column: number,
    merge: boolean,
  ): { startX: number; endX: number; startY: number; endY: number }
}

const numberSlotsOf = (
  worksheet: NonNullable<SkeletonLike['worksheet']>,
  valuesRef: string,
): Array<number | null> => {
  try {
    const bounds = parseRange(valuesRef.replace(/^[^!]*!/, ''))
    const values: Array<number | null> = []
    for (let row = bounds.startRow; row <= bounds.endRow; row += 1) {
      for (let column = bounds.startColumn; column <= bounds.endColumn; column += 1) {
        const value = worksheet.getCell(row, column)?.v
        values.push(typeof value === 'number' && Number.isFinite(value) ? value : null)
      }
    }
    return values
  } catch {
    return []
  }
}

const numbersOf = (worksheet: NonNullable<SkeletonLike['worksheet']>, ref: string): number[] =>
  numberSlotsOf(worksheet, ref).filter((value): value is number => value !== null)

const textsOf = (
  worksheet: NonNullable<SkeletonLike['worksheet']>,
  ref: string | undefined,
): string[] => {
  if (ref === undefined) return []
  try {
    const bounds = parseRange(ref.replace(/^[^!]*!/, ''))
    const texts: string[] = []
    for (let row = bounds.startRow; row <= bounds.endRow; row += 1) {
      for (let column = bounds.startColumn; column <= bounds.endColumn; column += 1) {
        const value = worksheet.getCell(row, column)?.v
        if (value !== null && value !== undefined) texts.push(String(value))
      }
    }
    return texts
  } catch {
    return []
  }
}

function drawChart(
  ctx: UniverRenderingContext,
  spec: ChartReadSpec,
  rect: { x0: number; y0: number; x1: number; y1: number },
  worksheet: NonNullable<SkeletonLike['worksheet']>,
): void {
  const { x0, y0, x1, y1 } = rect
  if (x1 - x0 < 40 || y1 - y0 < 30) return
  // frame
  ctx.save()
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(x0, y0, x1 - x0, y1 - y0)
  ctx.strokeStyle = '#9aa4ad'
  ctx.lineWidth = 1
  ctx.strokeRect(x0 + 0.5, y0 + 0.5, x1 - x0 - 1, y1 - y0 - 1)

  const title = spec.title ?? ''
  if (title) {
    ctx.fillStyle = '#1f2328'
    ctx.font = '11px system-ui'
    ctx.fillText(title.slice(0, 24), x0 + 6, y0 + 14)
  }

  const seriesValues = spec.series.map((entry) => numbersOf(worksheet, entry.valuesRef))
  // scatter: resolve literal X values or grid-backed X references (per series)
  const seriesXValues = spec.series.map((entry) => {
    if (entry.xValues !== undefined && entry.xValues.length > 0) return [...entry.xValues]
    if (entry.xValuesRef !== undefined) return numbersOf(worksheet, entry.xValuesRef)
    return undefined
  })
  const flat = seriesValues.flat()
  const basePlot = { top: y0 + (title ? 20 : 8), bottom: y1 - 8, left: x0 + 8, right: x1 - 8 }
  const hasSeriesLegend = spec.kind === 'bar' || spec.kind === 'column'
  const legendPlot = hasSeriesLegend && !spec.legend?.overlay ? paintChartLegend(ctx, spec, worksheet, basePlot) : basePlot
  const titledPlot = hasSeriesLegend ? paintAxisTitles(ctx, spec, worksheet, legendPlot) : legendPlot
  const slots = hasSeriesLegend ? spec.series.map(entry => numberSlotsOf(worksheet, entry.valuesRef)) : []
  const scale = hasSeriesLegend && !spec.valueScaleUnavailable ? barValueScale(slots, spec.axes?.value.scaling) : undefined
  const categoryCount = slots.reduce((count, values) => Math.max(count, values.length), 1)
  const category = scale && flat.length > 0 ? planCategoryAxis(ctx,spec,worksheet,categoryCount,titledPlot) : undefined
  const plot = scale && flat.length > 0 ? paintValueAxis(ctx, spec, scale, category?.plot ?? titledPlot) : titledPlot
  category?.paint(plot)
  const { top: plotTop, bottom: plotBottom, left: plotLeft, right: plotRight } = plot
  const plotHeight = Math.max(4, plotBottom - plotTop)
  const plotWidth = Math.max(4, plotRight - plotLeft)
  if (flat.length === 0) {
    if (hasSeriesLegend && spec.legend?.overlay) paintChartLegend(ctx, spec, worksheet, basePlot)
    ctx.restore()
    return
  }

  if (spec.kind === 'bar' || spec.kind === 'column') {
    // Preserve the category index of missing cells, including a longer later
    // series. Zero is a zero-length bar, never an invented minimum pixel size.
    const fraction = scale?.fraction
    if (!fraction) {
      ctx.save(); ctx.beginPath(); ctx.rect(plotLeft,plotTop,plotWidth,plotHeight); ctx.clip()
      ctx.fillStyle = '#1f2328'; ctx.font = '11px system-ui'; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic'
      ctx.fillText(fitted('此数值轴暂不支持预览，请下载原件查看',plotWidth-8,text=>ctx.measureText(text).width), plotLeft + 4, plotTop + 16)
      ctx.restore()
      ctx.restore(); return
    }
    const horizontal = spec.kind === 'bar'
    const band = (horizontal ? plotHeight : plotWidth) / categoryCount
    const thickness = band * 0.7 / Math.max(1, slots.length)
    const zero = horizontal ? plotLeft + plotWidth * fraction(0) : plotBottom - plotHeight * fraction(0)
    slots.forEach((values, seriesIndex) => {
      ctx.fillStyle = chartSeriesColor(spec.series[seriesIndex]!, seriesIndex)
      values.forEach((value, index) => {
        if (value === null || value === 0) return
        const offset = band * chartCategorySlot(spec,index,categoryCount) + band * 0.15 + thickness * chartCategorySlot(spec,seriesIndex,slots.length)
        const end = horizontal ? plotLeft + plotWidth * fraction(value) : plotBottom - plotHeight * fraction(value)
        if (end === zero) return
        if (horizontal) ctx.fillRect(Math.min(zero, end), plotTop + offset, Math.abs(end - zero), thickness)
        else ctx.fillRect(plotLeft + offset, Math.min(zero, end), thickness, Math.abs(end - zero))
      })
    })
    if (spec.legend?.overlay) paintChartLegend(ctx, spec, worksheet, basePlot)
    ctx.restore()
    return
  }

  if (spec.kind === 'pie' || spec.kind === 'doughnut') {
    // first series pie/doughnut
    const values = seriesValues[0] ?? []
    const total = values.reduce((sum, value) => sum + Math.max(0, value), 0)
    if (total <= 0) {
      ctx.restore()
      return
    }
    const cx = (plotLeft + plotRight) / 2
    const cy = (plotTop + plotBottom) / 2
    const radius = Math.min(plotWidth, plotHeight) / 2 - 2
    let angle = -Math.PI / 2
    values.forEach((value, index) => {
      const slice = Math.max(0, value) / total
      const next = angle + slice * Math.PI * 2
      ctx.beginPath()
      ctx.moveTo(cx, cy)
      ctx.arc(cx, cy, radius, angle, next)
      ctx.closePath()
      ctx.fillStyle = PALETTE[index % PALETTE.length]!
      ctx.fill()
      angle = next
    })
    if (spec.kind === 'doughnut') {
      // punch the hole with the frame background color (Excel default 50%)
      ctx.beginPath()
      ctx.arc(cx, cy, radius * 0.5, 0, Math.PI * 2)
      ctx.fillStyle = '#ffffff'
      ctx.fill()
    }
    ctx.restore()
    return
  }

  if (spec.kind === 'scatter') {
    // XY pairs: X from the series' xValuesRef/xValues (ordinal fallback), Y
    // from valuesRef; both axes scaled to their own min/max
    ctx.save()
    const axisFont = '9px system-ui'
    seriesValues.forEach((ys, seriesIndex) => {
      if (ys.length === 0) return
      const xs =
        seriesXValues[seriesIndex] ??
        Array.from({ length: ys.length }, (_unused, index) => index)
      if (xs.length !== ys.length) return
      const xMin = Math.min(...xs)
      const xMax = Math.max(...xs)
      const xSpan = xMax - xMin || 1
      const yMin = Math.min(...ys, 0)
      const yMax = Math.max(...ys, 0)
      const ySpan = yMax - yMin || 1
      ctx.strokeStyle = PALETTE[seriesIndex % PALETTE.length]!
      ctx.fillStyle = PALETTE[seriesIndex % PALETTE.length]!
      // light axes for orientation
      ctx.beginPath()
      ctx.moveTo(plotLeft, plotBottom)
      ctx.lineTo(plotRight, plotBottom)
      ctx.moveTo(plotLeft, plotTop)
      ctx.lineTo(plotLeft, plotBottom)
      ctx.stroke()
      xs.forEach((x, index) => {
        const px = plotLeft + (plotWidth * (x - xMin)) / xSpan
        const py = plotBottom - (plotHeight * (ys[index]! - yMin)) / ySpan
        ctx.beginPath()
        ctx.arc(px, py, 2.5, 0, Math.PI * 2)
        ctx.fill()
      })
      ctx.font = axisFont
    })
    ctx.restore()
    return
  }

  if (spec.kind === 'radar') {
    // spokes per category from the center; each series is a closed polygon
    const axisCount = Math.max(3, seriesValues[0]!.length)
    const cx = (plotLeft + plotRight) / 2
    const cy = (plotTop + plotBottom) / 2
    const radius = Math.min(plotWidth, plotHeight) / 2 - 6
    const max = Math.max(...flat, 0)
    const span = max || 1
    ctx.save()
    ctx.strokeStyle = '#d0d5da'
    ctx.lineWidth = 0.5
    for (let axis = 0; axis < axisCount; axis += 1) {
      const angle = -Math.PI / 2 + (Math.PI * 2 * axis) / axisCount
      ctx.beginPath()
      ctx.moveTo(cx, cy)
      ctx.lineTo(cx + radius * Math.cos(angle), cy + radius * Math.sin(angle))
      ctx.stroke()
    }
    seriesValues.forEach((values) => {
      if (values.length < 3) return
      ctx.strokeStyle = PALETTE[0]!
      ctx.fillStyle = PALETTE[0]!
      ctx.globalAlpha = 0.18
      ctx.beginPath()
      values.forEach((value, axis) => {
        const distance = (radius * Math.max(0, value)) / span
        const angle = -Math.PI / 2 + (Math.PI * 2 * axis) / values.length
        const px = cx + distance * Math.cos(angle)
        const py = cy + distance * Math.sin(angle)
        if (axis === 0) ctx.moveTo(px, py)
        else ctx.lineTo(px, py)
      })
      ctx.closePath()
      ctx.fill()
      ctx.globalAlpha = 1
      ctx.stroke()
    })
    ctx.restore()
    return
  }

  // Line/area and combo retain their existing category-axis rendering.
  const max = Math.max(...flat, 0)
  const min = spec.kind === 'line' || spec.kind === 'area' ? Math.min(...flat, 0) : 0
  const span = max - min || 1
  const valueY = (value: number): number =>
    plotBottom - (plotHeight * (value - min)) / span

  if (spec.kind === 'line' || spec.kind === 'area') {
    const plotPoints = (values: number[]): Array<[number, number]> =>
      values.map((value, index) => [
        plotLeft + (plotWidth * index) / (values.length - 1),
        valueY(value),
      ])
    seriesValues.forEach((values, seriesIndex) => {
      if (values.length < 2) return
      const points = plotPoints(values)
      if (spec.kind === 'area') {
        // translucent area fill down to the category axis, then the stroke
        ctx.globalAlpha = 0.35
        ctx.fillStyle = PALETTE[seriesIndex % PALETTE.length]!
        ctx.beginPath()
        points.forEach(([x, y], index) => {
          if (index === 0) ctx.moveTo(x, y)
          else ctx.lineTo(x, y)
        })
        ctx.lineTo(points[points.length - 1]![0], plotBottom)
        ctx.lineTo(points[0]![0], plotBottom)
        ctx.closePath()
        ctx.fill()
        ctx.globalAlpha = 1
      }
      ctx.strokeStyle = PALETTE[seriesIndex % PALETTE.length]!
      ctx.lineWidth = 1.5
      ctx.beginPath()
      points.forEach(([x, y], index) => {
        if (index === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      })
      ctx.stroke()
    })
    ctx.restore()
    return
  }

  if (spec.kind === 'combo') {
    // write-side convention: the LAST series rides the line plot, the rest
    // are clustered columns
    const barSeries = seriesValues.slice(0, Math.max(0, seriesValues.length - 1))
    const lineSeries = seriesValues[seriesValues.length - 1] ?? []
    const comboGroups = Math.max(1, barSeries[0]?.length ?? 1)
    const comboGroupWidth = plotWidth / comboGroups
    const comboSeriesCount = Math.max(1, barSeries.length)
    const comboBarWidth = Math.max(2, (comboGroupWidth * 0.7) / comboSeriesCount)
    barSeries.forEach((values, seriesIndex) => {
      ctx.fillStyle = PALETTE[seriesIndex % PALETTE.length]!
      values.forEach((value, index) => {
        const barHeight = Math.max(1, (plotHeight * (value - min)) / span)
        const x =
          plotLeft + comboGroupWidth * index + (comboGroupWidth - comboBarWidth * comboSeriesCount) / 2 + comboBarWidth * seriesIndex
        ctx.fillRect(x, plotBottom - barHeight, comboBarWidth, barHeight)
      })
    })
    if (lineSeries.length >= 2) {
      ctx.strokeStyle = PALETTE[(seriesValues.length - 1) % PALETTE.length]!
      ctx.lineWidth = 1.5
      ctx.beginPath()
      lineSeries.forEach((value, index) => {
        const x = plotLeft + (plotWidth * index) / (lineSeries.length - 1)
        const y = valueY(value)
        if (index === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      })
      ctx.stroke()
    }
    ctx.restore()
    return
  }

  ctx.restore()
}

class ChartRenderExtension extends SheetExtension {
  uKey = CHART_UKEY
  Z_INDEX = EXTENSION_Z_INDEX

  draw(
    ctx: UniverRenderingContext,
    _parentScale: IScale,
    skeletonRaw: SpreadsheetSkeleton,
    _diffRanges?: IRange[],
    _more?: IDrawInfo,
  ): void {
    const diagnostics = (window as unknown as { __sheetsWebCharts?: { draws: number } })
      .__sheetsWebCharts
    if (diagnostics) diagnostics.draws += 1
    const skeleton = skeletonRaw as unknown as SkeletonLike
    const worksheet = skeleton.worksheet
    if (!worksheet?.getUnitId || !worksheet.getSheetId) return
    const specs = store.get(`${worksheet.getUnitId()}::${worksheet.getSheetId()}`)
    if (!specs || specs.length === 0) return

    for (const spec of specs) {
      try {
        const from = parseRange(
          `${columnLetterOf(spec.anchor.fromRow, spec.anchor.fromColumn)}:${columnLetterOf(spec.anchor.fromRow, spec.anchor.fromColumn)}`,
        )
        const to = parseRange(
          `${columnLetterOf(spec.anchor.toRow, spec.anchor.toColumn)}:${columnLetterOf(spec.anchor.toRow, spec.anchor.toColumn)}`,
        )
        const fromCell = skeleton.getCellWithCoordByIndex(from.startRow, from.startColumn, false)
        const toCell = skeleton.getCellWithCoordByIndex(to.startRow, to.startColumn, false)
        drawChart(
          ctx,
          spec,
          {
            x0: Math.min(fromCell.startX, toCell.startX),
            y0: Math.min(fromCell.startY, toCell.startY),
            x1: Math.max(toCell.endX, fromCell.endX),
            y1: Math.max(toCell.endY, fromCell.endY),
          },
          worksheet,
        )
      } catch {
        // anchor/coordinate variance: skip this chart, keep rendering
      }
    }
  }
}

function columnLetterOf(row: number, column: number): string {
  let label = ''
  let remaining = column + 1
  while (remaining > 0) {
    remaining -= 1
    label = String.fromCharCode(65 + (remaining % 26)) + label
    remaining = Math.floor(remaining / 26)
  }
  return `${label}${row + 1}`
}

SpreadsheetExtensionRegistry.add(ChartRenderExtension)
