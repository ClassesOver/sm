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
import { chartSeriesColor, chartPointColor, fitted, paintChartLegend } from './chart-legend'
import { paintAxisTitles } from './chart-axis-titles'
import { barValueScale, scatterAxisScale } from './chart-value-scale'
import { paintValueAxis } from './chart-value-axis'
import { paintScatterAxes, scatterValueText } from './chart-scatter-axis'
import { chartCategoryLabels, chartCategorySlot, planCategoryAxis } from './chart-category-axis'
import { paintBarDataLabels, paintLineDataLabels, type BarLabelDatum } from './chart-data-labels'
import { paintPieDataLabels } from './chart-pie-data-labels'
import { chartBounds } from '../../workbook-chart-geometry'
import { selectedChartPath } from '../../workbook-chart-selection-state'
import { chartResizeHandles } from '../../workbook-chart-object-geometry'
import {clearChartElementRegions,setChartElementRegions,type ChartElementRegion,type WorkbookChartElement} from '../../workbook-chart-element-hit'

const store = new Map<string, ReadonlyArray<ChartReadSpec>>()

export function setCharts(
  unitId: string,
  sheetId: string,
  specs: ReadonlyArray<ChartReadSpec> | undefined,
): void {
  const key = `${unitId}::${sheetId}`
  clearChartElementRegions(unitId,sheetId)
  if (specs === undefined || specs.length === 0) store.delete(key)
  else store.set(key, specs)
}

;(window as unknown as { __sheetsWebCharts?: unknown }).__sheetsWebCharts = {
  store,
  draws: 0,
}

const CHART_UKEY = 'sheets-web-chart'
// Univer 单元格文字/边框/自定义绘制/角标依次为 45/50/55/60；锚定图表必须在其后绘制。
const EXTENSION_Z_INDEX = 61

interface SkeletonLike {
  worksheet?: {
    getName?: () => string
    getUnitId?: () => string
    getSheetId?: () => string
    getZoomRatio?: () => number
    getConfig?: () => { rightToLeft?: number }
    getCell(row: number, column: number): { v?: unknown } | null | undefined
    getCellRaw(row: number, column: number): { v?: unknown } | null | undefined
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
        // getCell() 包含 numfmt 显示拦截器，数值 10 可能已变为 "10.00"。
        const value = worksheet.getCellRaw(row, column)?.v
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
  regions: ChartElementRegion[],
): void {
  const hitRect=(element:WorkbookChartElement,left:number,top:number,right:number,bottom:number)=>regions.push({element,contains:(x,y)=>x>=left&&x<=right&&y>=top&&y<=bottom})
  const hitPoint=(seriesIndex:number,pointIndex:number,px:number,py:number)=>regions.push({element:{kind:'point',seriesIndex,pointIndex},contains:(x,y)=>Math.hypot(x-px,y-py)<=7})
  const { x0, y0, x1, y1 } = rect
  if (x1 - x0 < 24 || y1 - y0 < 24) return
  // frame
  ctx.save()
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(x0, y0, x1 - x0, y1 - y0)
  ctx.strokeStyle = '#9aa4ad'
  ctx.lineWidth = 1
  ctx.strokeRect(x0 + 0.5, y0 + 0.5, x1 - x0 - 1, y1 - y0 - 1)
  if (x1 - x0 < 40 || y1 - y0 < 30) { ctx.restore(); return }

  const title = spec.title ?? ''
  if (title) {
    hitRect({kind:'title'},x0+1,y0+1,x1-1,y0+19)
    ctx.save()
    ctx.beginPath(); ctx.rect(x0 + 1, y0 + 1, x1 - x0 - 2, 18); ctx.clip()
    ctx.fillStyle = '#1f2328'
    ctx.font = '11px system-ui'; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic'
    ctx.fillText(fitted(title, x1 - x0 - 12, text => ctx.measureText(text).width), x0 + 6, y0 + 14)
    ctx.restore()
  }

  if (spec.series.some(series => series.colorPreviewUnavailable)) {
    ctx.fillStyle = '#1f2328'; ctx.font = '11px system-ui'; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic'
    ctx.fillText(fitted('来源填充暂不支持预览，请下载原件查看', x1 - x0 - 12, text => ctx.measureText(text).width), x0 + 6, y0 + 34)
    ctx.restore(); return
  }

  const seriesValues = spec.series.map((entry) => entry.valuesRef
    ? numberSlotsOf(worksheet, entry.valuesRef)
    : [...entry.values ?? []].map(value => Number.isFinite(value) ? value : null))
  // scatter: resolve literal X values or grid-backed X references (per series)
  const seriesXValues = spec.series.map((entry) => {
    if (entry.xValues !== undefined && entry.xValues.length > 0) return [...entry.xValues]
    if (entry.xValuesRef !== undefined) return numberSlotsOf(worksheet, entry.xValuesRef)
    return undefined
  })
  const flat = seriesValues.flat().filter((value): value is number => value !== null && Number.isFinite(value))
  const basePlot = { top: y0 + (title ? 20 : 8), bottom: y1 - 8, left: x0 + 8, right: x1 - 8 }
  const hasSeriesLegend = ['bar','column','combo','line','area'].includes(spec.kind)
  const pieSeries = (spec.kind === 'pie' || spec.kind === 'doughnut') ? spec.series[0] : undefined
  const pieEntries = pieSeries ? chartCategoryLabels(pieSeries, worksheet, (pieSeries.valuesRef ? numberSlotsOf(worksheet, pieSeries.valuesRef) : pieSeries.values ?? []).length)
    .map((label, index) => ({ label: label ?? '', index, color: chartPointColor(spec, 0, index) })) : undefined
  const legendPlot = (hasSeriesLegend || pieSeries) && !spec.legend?.overlay ? paintChartLegend(ctx, spec, worksheet, basePlot, pieEntries) : basePlot
  if(spec.legend){const position=spec.legend.position;if(position==='left')hitRect({kind:'legend'},basePlot.left,basePlot.top,legendPlot.left,basePlot.bottom);else if(position==='right'||position==='top-right')hitRect({kind:'legend'},legendPlot.right,basePlot.top,basePlot.right,basePlot.bottom);else if(position==='top')hitRect({kind:'legend'},basePlot.left,basePlot.top,basePlot.right,legendPlot.top);else hitRect({kind:'legend'},basePlot.left,legendPlot.bottom,basePlot.right,basePlot.bottom)}
  const titledPlot = hasSeriesLegend ? paintAxisTitles(ctx, spec, worksheet, legendPlot) : legendPlot
  const slots = hasSeriesLegend ? spec.series.map(entry => entry.valuesRef ? numberSlotsOf(worksheet, entry.valuesRef) : (entry.values ?? []).map(value => Number.isFinite(value) ? value : null)) : []
  const scale = hasSeriesLegend && !spec.valueScaleUnavailable ? barValueScale(spec.kind === 'combo' ? slots.filter((_, index) => !spec.series[index]?.secondaryAxis) : slots, spec.axes?.value.scaling) : undefined
  const secondaryScale = spec.kind === 'combo' ? barValueScale(slots.filter((_, index) => spec.series[index]?.secondaryAxis), spec.secondaryAxes?.value.scaling) : undefined
  const categoryCount = spec.kind === 'line' || spec.kind === 'area'
    ? Math.max(1, slots[0]?.length ?? 0)
    : slots.reduce((count, values) => Math.max(count, values.length), 1)
  const category = scale && flat.length > 0 ? planCategoryAxis(ctx,spec,worksheet,categoryCount,titledPlot) : undefined
  const axisPlot = secondaryScale && spec.secondaryAxes ? paintValueAxis(ctx, { ...spec, axes: spec.secondaryAxes }, secondaryScale, category?.plot ?? titledPlot) : category?.plot ?? titledPlot
  const plot = scale && flat.length > 0 ? paintValueAxis(ctx, spec, scale, axisPlot) : axisPlot
  category?.paint(plot)
  const { top: plotTop, bottom: plotBottom, left: plotLeft, right: plotRight } = plot
  const plotHeight = Math.max(4, plotBottom - plotTop)
  const plotWidth = Math.max(4, plotRight - plotLeft)
  if(scale&&spec.design?.gridlines){ctx.save();ctx.strokeStyle='#e2e5e9';ctx.lineWidth=0.5;for(const tick of scale.ticks){ctx.beginPath();if(spec.kind==='bar'){const x=plotLeft+plotWidth*scale.fraction(tick);ctx.moveTo(x,plotTop);ctx.lineTo(x,plotBottom)}else{const y=plotBottom-plotHeight*scale.fraction(tick);ctx.moveTo(plotLeft,y);ctx.lineTo(plotRight,y)}ctx.stroke()}ctx.restore()}
  if(hasSeriesLegend){hitRect({kind:'category-axis'},plotLeft,plotBottom,plotRight,y1-1);hitRect({kind:'value-axis'},x0+1,plotTop,plotLeft,plotBottom)}
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
    const thickness = band / (Math.max(1, slots.length) + (spec.gapWidthPct ?? 150) / 100)
    const groupInset = (band - thickness * slots.length) / 2
    const zero = horizontal ? plotLeft + plotWidth * fraction(0) : plotBottom - plotHeight * fraction(0)
    const labelPoints: BarLabelDatum[] = []
    const wantsLabels = flat.length <= 500 && (spec.dataLabels !== undefined || spec.series.some(series=>series.dataLabels !== undefined))
    slots.forEach((values, seriesIndex) => {
      values.forEach((value, index) => {
        if (value === null) return
        ctx.fillStyle = chartPointColor(spec, seriesIndex, index)
        const offset = band * chartCategorySlot(spec,index,categoryCount) + groupInset + thickness * chartCategorySlot(spec,seriesIndex,slots.length)
        const end = horizontal ? plotLeft + plotWidth * fraction(value) : plotBottom - plotHeight * fraction(value)
        if (end === zero && value !== 0) return
        const rect = horizontal ? {left:Math.min(zero,end),top:plotTop+offset,right:Math.max(zero,end),bottom:plotTop+offset+thickness}
          : {left:plotLeft+offset,top:Math.min(zero,end),right:plotLeft+offset+thickness,bottom:Math.max(zero,end)}
        if(end!==zero)hitRect({kind:'point',seriesIndex,pointIndex:index},rect.left,rect.top,rect.right,rect.bottom)
        if (end !== zero) ctx.fillRect(rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top)
        if (wantsLabels && (value !== 0 || scale!.min <= 0 && scale!.max >= 0)) labelPoints.push({value,index,seriesIndex,zero,end,rect})
      })
    })
    if (wantsLabels) paintBarDataLabels(ctx,spec,labelPoints,plot)
    if (spec.legend?.overlay) paintChartLegend(ctx, spec, worksheet, basePlot)
    ctx.restore()
    return
  }

  if (spec.kind === 'pie' || spec.kind === 'doughnut') {
    // first series pie/doughnut
    const first = spec.series[0]!, values = (first.valuesRef ? numberSlotsOf(worksheet, first.valuesRef) : first.values ?? []).map(value => Math.max(0, value ?? 0))
    const total = values.reduce((sum, value) => sum + Math.max(0, value), 0)
    if (total <= 0) {
      ctx.restore()
      return
    }
    const cx = (plotLeft + plotRight) / 2
    const cy = (plotTop + plotBottom) / 2
    const hasLabels = !!spec.dataLabels || !!spec.series[0]?.dataLabels
    const radius = Math.max(1, Math.min(plotWidth, plotHeight) / 2 - (hasLabels ? 22 : 2))
    const innerRadius = spec.kind === 'doughnut' ? radius * (spec.holeSizePct ?? 50) / 100 : 0
    let angle = -Math.PI / 2
    values.forEach((value, index) => {
      if (value === 0) return
      const slice = Math.max(0, value) / total
      const next = angle + slice * Math.PI * 2
      const shift = Math.min(100, Math.max(0, first.pointExplosions?.[index] ?? first.explosionPct ?? 0)) / 100 * radius * 0.4
      const mid = (angle + next) / 2, x = cx + Math.cos(mid) * shift, y = cy + Math.sin(mid) * shift
      const start=angle,end=next;regions.push({element:{kind:'point',seriesIndex:0,pointIndex:index},contains:(px,py)=>{const distance=Math.hypot(px-x,py-y);let a=Math.atan2(py-y,px-x);while(a<start)a+=Math.PI*2;return distance>=innerRadius&&distance<=radius&&a<=end}})
      ctx.beginPath()
      ctx.arc(x, y, radius, angle, next)
      if (innerRadius > 0) ctx.arc(x, y, innerRadius, next, angle, true)
      else ctx.lineTo(x, y)
      ctx.closePath()
      ctx.fillStyle = chartPointColor(spec, 0, index)
      ctx.fill()
      angle = next
    })
    paintPieDataLabels(ctx, spec, values, worksheet, { cx, cy, radius, innerRadius }, plot)
    if (spec.legend?.overlay) paintChartLegend(ctx, spec, worksheet, basePlot, pieEntries)
    ctx.restore()
    return
  }

  if (spec.kind === 'scatter') {
    // XY pairs: X from the series' xValuesRef/xValues (ordinal fallback), Y
    // from valuesRef; both axes scaled to their own min/max
    ctx.save()
    const axisFont = '9px system-ui'
    const scatterXs = seriesValues.flatMap((ys,index)=>{
      const xs=seriesXValues[index]??Array.from({length:ys.length},(_unused,point)=>point)
      return xs.length===ys.length?xs.filter((value,point):value is number=>ys[point]!==null&&typeof value==='number'&&Number.isFinite(value)):[]
    })
    const xAxisBounds = scatterAxisScale(scatterXs,spec.axes?.category?.scaling)
    const yAxisBounds = scatterAxisScale(flat,spec.axes?.value?.scaling)
    const valueLabels=spec.dataLabels?.showValue ? seriesValues.flatMap((values,index)=>values.flatMap(value=>value===null?[]:[scatterValueText(value,spec.series[index]?.numberFormat)])) : []
    const {plot: scatterPlot,xAt,yAt}=paintScatterAxes(ctx,spec,worksheet,plot,xAxisBounds,yAxisBounds,valueLabels)
    const categoryAxis = spec.axes?.category
    const valueAxis = spec.axes?.value
    if (!categoryAxis?.hidden) hitRect({kind:'category-axis'},scatterPlot.left,scatterPlot.bottom,scatterPlot.right,plot.bottom+17)
    if (!valueAxis?.hidden) hitRect({kind:'value-axis'},plot.left-4,scatterPlot.top,scatterPlot.left,scatterPlot.bottom)
    seriesValues.forEach((ys, seriesIndex) => {
      if (ys.length === 0) return
      const xs =
        seriesXValues[seriesIndex] ??
        Array.from({ length: ys.length }, (_unused, index) => index)
      if (xs.length !== ys.length) return
      const series=spec.series[seriesIndex]!
      const valid=ys.flatMap((y,index)=>y!==null&&Number.isFinite(y)&&Number.isFinite(xs[index])?[{index,x:xs[index]!,y}]:[])
      if(spec.scatterStyle&&spec.scatterStyle!=='marker'&&series.lineColor!=='none'&&!series.lineColorUnavailable&&series.lineWidth!==0&&valid.length>1){
        ctx.beginPath();ctx.moveTo(xAt(valid[0]!.x),yAt(valid[0]!.y))
        valid.slice(1).forEach(point=>ctx.lineTo(xAt(point.x),yAt(point.y)))
        ctx.strokeStyle=series.lineColor??chartSeriesColor(series,seriesIndex,spec.palette);ctx.lineWidth=series.lineWidth??2;ctx.stroke()
      }
      if(series.marker!=='none')valid.forEach(({index,x,y})=>{
        const px = xAt(x)
        const py = yAt(y)
        hitPoint(seriesIndex,index,px,py)
        ctx.beginPath()
        ctx.fillStyle = chartPointColor(spec,seriesIndex,index)
        ctx.arc(px, py, 2.5, 0, Math.PI * 2)
        ctx.fill()
      })
      if(spec.dataLabels?.showValue){
        ctx.save();ctx.font='9px system-ui';ctx.textAlign='center';ctx.textBaseline='alphabetic';ctx.fillStyle='#888'
        valid.forEach(({x,y})=>ctx.fillText(scatterValueText(y,series.numberFormat),xAt(x),yAt(y)-8))
        ctx.restore()
      }
      ctx.font = axisFont
    })
    ctx.restore()
    ctx.restore()
    return
  }

  if (spec.kind === 'radar') {
    // spokes per category from the center; each series is a closed polygon
    const radarValues = spec.series.map((entry) => entry.valuesRef ? numberSlotsOf(worksheet, entry.valuesRef) : [...entry.values ?? []])
    const axisCount = Math.min(12, Math.max(3, radarValues[0]?.length ?? 0))
    const cx = (plotLeft + plotRight) / 2
    const cy = (plotTop + plotBottom) / 2
    const radius = Math.min(plotWidth, plotHeight) / 2 - 6
    const radarCategories = chartCategoryLabels(spec.series[0],worksheet,axisCount,spec.axes?.category.numberFormat)
    const categoryAxisVisible = !spec.axes?.category.hidden
    if(categoryAxisVisible){
      ctx.save();ctx.font='10px system-ui';ctx.fillStyle='#1f2328';ctx.textBaseline='middle'
      for(let axis=0;axis<axisCount;axis++){
        const angle=-Math.PI/2+Math.PI*2*axis/axisCount,px=cx+Math.cos(angle)*radius*1.12,py=cy+Math.sin(angle)*radius*1.12
        const label=radarCategories[axis]??String(axis+1),width=ctx.measureText(label).width
        ctx.textAlign=Math.abs(px-cx)<8?'center':px>cx?'left':'right';ctx.fillText(label,px,py)
        const left=ctx.textAlign==='center'?px-width/2:ctx.textAlign==='left'?px:px-width
        regions.push({element:{kind:'category-axis'},contains:(x,y)=>x>=left-2&&x<=left+width+2&&Math.abs(y-py)<=7})
      }
      ctx.restore()
    }
    let dataMaximum = 0
    for (const value of flat) dataMaximum = Math.max(dataMaximum, value)
    const magnitude = dataMaximum > 0 ? 10 ** Math.floor(Math.log10(dataMaximum)) : 1
    const normalized = dataMaximum / magnitude
    const ceiling = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10
    const maximum = dataMaximum > 0 ? ceiling * magnitude : 1
    ctx.save()
    ctx.strokeStyle = '#e3e3e3'
    ctx.lineWidth = 0.5
    for (const fraction of [0.25, 0.5, 0.75, 1]) {
      ctx.beginPath()
      for (let axis = 0; axis < axisCount; axis += 1) {
        const angle = -Math.PI / 2 + (Math.PI * 2 * axis) / axisCount
        const px = cx + radius * fraction * Math.cos(angle)
        const py = cy + radius * fraction * Math.sin(angle)
        if (axis === 0) ctx.moveTo(px, py)
        else ctx.lineTo(px, py)
      }
      ctx.closePath()
      ctx.stroke()
    }
    ctx.strokeStyle = '#d0d5da'
    ctx.lineWidth = 0.5
    for (let axis = 0; axis < axisCount; axis += 1) {
      const angle = -Math.PI / 2 + (Math.PI * 2 * axis) / axisCount
      ctx.beginPath()
      ctx.moveTo(cx, cy)
      ctx.lineTo(cx + radius * Math.cos(angle), cy + radius * Math.sin(angle))
      ctx.stroke()
    }
    const labelPoints: Array<{value:number;index:number;seriesIndex:number;x:number;y:number}> = []
    radarValues.forEach((values,seriesIndex) => {
      const points = Array.from({ length: axisCount }, (_, axis) => values[axis] ?? 0)
      const polygon = points.map((value, axis) => {
        const distance = radius * Math.max(0, Math.min(maximum, value)) / maximum
        const angle = -Math.PI / 2 + (Math.PI * 2 * axis) / axisCount
        return { x: cx + distance * Math.cos(angle), y: cy + distance * Math.sin(angle) }
      })
      regions.push({element:{kind:'series',seriesIndex},contains:(x,y)=>{
        let inside=false
        for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){
          const a=polygon[i]!,b=polygon[j]!
          if((a.y>y)!==(b.y>y)&&x<(b.x-a.x)*(y-a.y)/(b.y-a.y)+a.x)inside=!inside
        }
        return inside
      }})
      ctx.strokeStyle = chartSeriesColor(spec.series[seriesIndex]!,seriesIndex,spec.palette)
      ctx.fillStyle = ctx.strokeStyle
      ctx.globalAlpha = 0.18
      ctx.beginPath()
      points.forEach((value, axis) => {
        const distance = radius * Math.max(0, Math.min(maximum, value)) / maximum
        const angle = -Math.PI / 2 + (Math.PI * 2 * axis) / axisCount
        const px = cx + distance * Math.cos(angle)
        const py = cy + distance * Math.sin(angle)
        if (axis === 0) ctx.moveTo(px, py)
        else ctx.lineTo(px, py)
      })
      ctx.closePath()
      ctx.fill()
      ctx.globalAlpha = 1
      ctx.stroke()
      values.forEach((value,index)=>{if(value===null||index>=axisCount)return;const angle=-Math.PI/2+Math.PI*2*index/axisCount,distance=radius*Math.max(0,Math.min(maximum,value))/maximum,px=cx+distance*Math.cos(angle),py=cy+distance*Math.sin(angle);hitPoint(seriesIndex,index,px,py);ctx.beginPath();ctx.arc(px,py,2.5,0,Math.PI*2);ctx.fillStyle=chartPointColor(spec,seriesIndex,index);ctx.fill();labelPoints.push({value,index,seriesIndex,x:px,y:py})})
    })
    paintLineDataLabels(ctx,spec,labelPoints,plot)
    ctx.restore()
    ctx.restore()
    return
  }

  // Line/area and combo retain their existing category-axis rendering.
  const max = Math.max(...flat, 0)
  const min = spec.kind === 'line' || spec.kind === 'area' ? Math.min(...flat, 0) : 0
  const span = max - min || 1
  const valueY = (value: number): number =>
    plotBottom - plotHeight * (scale?.fraction(value) ?? (value-min)/span)

  if (spec.kind === 'line' || spec.kind === 'area') {
    const labelPoints:Array<{value:number;index:number;seriesIndex:number;x:number;y:number}>=[]
    slots.forEach((values, seriesIndex) => {
      const points=values.flatMap((value,index)=>value===null||!Number.isFinite(value)?[]:[{x:plotLeft+plotWidth*index/Math.max(1,values.length-1),y:valueY(value),index,value}])
      if(!points.length)return
      const runs:Array<typeof points>=[]
      points.forEach(point=>{
        const run=runs[runs.length-1]
        if(!run||run[run.length-1]!.index!==point.index-1)runs.push([point])
        else run.push(point)
      })
      ctx.fillStyle = chartSeriesColor(spec.series[seriesIndex]!,seriesIndex,spec.palette)
      runs.forEach(run=>{
        if(spec.kind==='area'&&run.length>1){
          const polygon=[...run.map(({x,y})=>({x,y})),{x:run[run.length-1]!.x,y:plotBottom},{x:run[0]!.x,y:plotBottom}]
          regions.push({element:{kind:'series',seriesIndex},contains:(x,y)=>{
            let inside=false
            for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){
              const a=polygon[i]!,b=polygon[j]!
              if((a.y>y)!==(b.y>y)&&x<(b.x-a.x)*(y-a.y)/(b.y-a.y)+a.x)inside=!inside
            }
            return inside
          }})
        }
        if(spec.kind==='area'&&run.length>1){
          // Fill only contiguous spans so blank categories remain real gaps.
          ctx.globalAlpha=0.35;ctx.beginPath();run.forEach(({x,y},index)=>index===0?ctx.moveTo(x,y):ctx.lineTo(x,y));ctx.lineTo(run[run.length-1]!.x,plotBottom);ctx.lineTo(run[0]!.x,plotBottom);ctx.closePath();ctx.fill();ctx.globalAlpha=1
        }
        ctx.strokeStyle=chartSeriesColor(spec.series[seriesIndex]!,seriesIndex,spec.palette);ctx.lineWidth=1.5;ctx.beginPath()
        run.forEach(({x,y},index)=>index===0?ctx.moveTo(x,y):ctx.lineTo(x,y));ctx.stroke()
        for(let index=1;index<run.length;index++){
          const a=run[index-1]!,b=run[index]!
          regions.push({element:{kind:'series',seriesIndex},contains:(x,y)=>{
            const dx=b.x-a.x,dy=b.y-a.y,length=dx*dx+dy*dy
            const fraction=length===0?0:Math.max(0,Math.min(1,((x-a.x)*dx+(y-a.y)*dy)/length))
            return Math.hypot(x-(a.x+fraction*dx),y-(a.y+fraction*dy))<=4
          }})
        }
      })
      ctx.strokeStyle = chartSeriesColor(spec.series[seriesIndex]!,seriesIndex,spec.palette)
      points.forEach(({x,y,index,value})=>{hitPoint(seriesIndex,index,x,y);ctx.beginPath();ctx.arc(x,y,2.5,0,Math.PI*2);ctx.fillStyle=chartPointColor(spec,seriesIndex,index);ctx.fill();labelPoints.push({value,index,seriesIndex,x,y})})
    })
    paintLineDataLabels(ctx,spec,labelPoints,plot)
    ctx.restore()
    return
  }

  if (spec.kind === 'combo') {
    // 固定源按实际plot/axis标签绘制；仅未标记的旧会话组合图沿最后一条折线约定。
    const family = (index: number) => spec.series[index]?.plot ?? (index === spec.series.length - 1 ? 'lineChart' : 'barChart')
    const bars = spec.series.map((_, index) => index).filter(index => family(index) === 'barChart')
    const count = Math.max(1, ...slots.map(values => values.length)), band = plotWidth / count, thickness = band / (Math.max(1, bars.length) + (spec.gapWidthPct ?? 150) / 100)
    const groupInset = (band - thickness * bars.length) / 2
    const y = (value: number, index: number) => {
      const axis = spec.series[index]?.secondaryAxis ? secondaryScale : scale
      return axis ? plotBottom - plotHeight * axis.fraction(value) : undefined
    }
    ctx.save(); ctx.beginPath(); ctx.rect(plotLeft,plotTop,plotWidth,plotHeight); ctx.clip()
    bars.forEach((seriesIndex, barIndex) => {
      const zero = y(0, seriesIndex)
      if (zero === undefined) return
      slots[seriesIndex]!.forEach((value, index) => {
        if (value === null) return
        const end = y(value, seriesIndex)
        if (end === undefined || end === zero) return
        ctx.fillStyle = chartPointColor(spec, seriesIndex, index)
        const x = plotLeft + band * chartCategorySlot(spec,index,count) + groupInset + thickness * barIndex
        hitRect({kind:'point',seriesIndex,pointIndex:index},x,Math.min(zero,end),x+thickness,Math.max(zero,end))
        ctx.fillRect(x, Math.min(zero,end), thickness, Math.abs(end-zero))
      })
    })
    slots.forEach((values, seriesIndex) => {
      if (family(seriesIndex) !== 'lineChart') return
      ctx.strokeStyle = chartPointColor(spec, seriesIndex, 0); ctx.lineWidth = 1.5; ctx.beginPath()
      let connected = false
      values.forEach((value, index) => {
        const point = value === null ? undefined : y(value,seriesIndex)
        if (point === undefined) { connected = false; return }
        const x = plotLeft + band * (chartCategorySlot(spec,index,count) + 0.5)
        hitPoint(seriesIndex,index,x,point)
        if (connected) ctx.lineTo(x,point); else ctx.moveTo(x,point)
        connected = true
      })
      ctx.stroke()
    })
    ctx.restore()
    if (spec.legend?.overlay) paintChartLegend(ctx,spec,worksheet,basePlot)
    ctx.restore(); return
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
        const rect = chartBounds(spec.anchor, (row, column) => skeleton.getCellWithCoordByIndex(row, column, false), worksheet.getConfig?.().rightToLeft === 1)
        if (rect.x1 - rect.x0 < 24 || rect.y1 - rect.y0 < 24) continue
        const regions:ChartElementRegion[]=[]
        drawChart(
          ctx,
          spec,
          rect,
          worksheet,
          regions,
        )
        setChartElementRegions(worksheet.getUnitId(),worksheet.getSheetId(),spec,regions)
        if (selectedChartPath(worksheet.getUnitId(), worksheet.getSheetId()) === spec.chartPath) {
          ctx.save();ctx.strokeStyle = '#2563eb';ctx.lineWidth = 2
          ctx.strokeRect(rect.x0+1,rect.y0+1,rect.x1-rect.x0-2,rect.y1-rect.y0-2)
          if (spec.anchorKind !== 'oneCellAnchor' && spec.anchorKind !== 'absoluteAnchor') {
            const size = 8 / (worksheet.getZoomRatio?.() || 1)
            ctx.fillStyle = '#2563eb'
            for (const point of chartResizeHandles(rect)) ctx.fillRect(point.x-size/2,point.y-size/2,size,size)
          }
          ctx.restore()
        }
      } catch {
        // anchor/coordinate variance: skip this chart, keep rendering
      }
    }
  }
}

SpreadsheetExtensionRegistry.add(ChartRenderExtension)
