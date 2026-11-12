/// Surgical edits to a chart part (xl/charts/chartN.xml) — port of the
/// genoffice xlsx-chart write path: title text, chart-type conversion within
/// the convertible family, series colors, legend, data labels (mode +
/// position/format), axis titles, stacking, gridlines, value-axis bounds,
/// gap width, doughnut hole, pie explosions, point fills, and series
/// replacement / per-series rewrites. Anything outside the supported
/// envelope throws — fail closed, never corrupt a chart part.

import { SaxesParser } from 'saxes'

export class ChartEditError extends Error {}

export type ChartTargetType = 'column' | 'bar' | 'line' | 'area' | 'pie' | 'doughnut'

export interface ChartSeriesSetEntry {
  readonly name: string
  readonly values: readonly number[]
  readonly valuesRef?: string | undefined
  readonly categories?: readonly string[] | undefined
  readonly categoriesRef?: string | undefined
  readonly color?: string | undefined
}

export interface ChartSeriesDataEdit {
  readonly index: number
  readonly name?: string | undefined
  readonly values?: readonly number[] | undefined
  readonly valuesRef?: string | undefined
  readonly categories?: readonly string[] | undefined
  readonly categoriesRef?: string | undefined
}

export interface ChartEditLean {
  readonly title?: string | undefined
  readonly chartType?: ChartTargetType | undefined
  /// series document-position index → #RRGGBB
  readonly seriesColors?: Readonly<Record<string, string>> | undefined
  /// 'none' removes the legend; a side re-positions (creating it if needed).
  readonly legend?: 'none' | 'right' | 'bottom' | 'top' | 'left' | undefined
  /// Plot-level data labels: values on bars/points, category+percent or
  /// percent on pie slices. 'none' removes them.
  readonly dataLabels?: 'none' | 'value' | 'percent' | 'category-percent' | undefined
  /// Placement and number format of the data labels (`c:dLblPos`/`c:numFmt`).
  readonly dataLabelPosition?: 'center' | 'inside-end' | 'outside-end' | undefined
  readonly dataLabelFormat?: string | undefined
  /// null removes that axis title. Axis-based charts only.
  readonly axisTitles?:
    | {
        readonly category?: string | null | undefined
        readonly value?: string | null | undefined
      }
    | undefined
  /// Per-point fills (`c:dPt`), keyed series index → point index → #RRGGBB;
  /// how pie/doughnut slices get individual colors.
  readonly pointColors?: Readonly<Record<string, Readonly<Record<string, string>>>> | undefined
  /// Bar/line/area stacking; 'clustered' means side-by-side (line/area
  /// write it as 'standard').
  readonly grouping?: 'clustered' | 'stacked' | 'percentStacked' | undefined
  /// Value-axis major gridlines on/off (axis charts only).
  readonly gridlines?: boolean | undefined
  /// Value-axis bounds; null resets that bound to auto.
  readonly valueAxis?:
    | {
        readonly min?: number | null | undefined
        readonly max?: number | null | undefined
      }
    | undefined
  /// Bar family gap between categories, % of one bar width.
  readonly gapWidthPct?: number | undefined
  /// Doughnut hole diameter, % of chart size.
  readonly holeSizePct?: number | undefined
  /// Pie whole-ring explosion (series 0), % of radius.
  readonly explosionPct?: number | undefined
  /// Pie per-slice explosion overrides (series 0), point index → %.
  readonly pointExplosions?: Readonly<Record<string, number>> | undefined
  /// Full series replacement (Select Data): existing series all drop and
  /// these are written in order. Wins over `series`/`seriesColors` edits.
  readonly seriesSet?: readonly ChartSeriesSetEntry[] | undefined
  /// Per-series rewrite of name and/or data (refs + caches travel together).
  readonly series?: readonly ChartSeriesDataEdit[] | undefined
}

const CONVERTIBLE_PLOTS = ['barChart', 'lineChart', 'areaChart', 'pieChart', 'doughnutChart'] as const
type PlotElement = (typeof CONVERTIBLE_PLOTS)[number]

const TARGET_PLOTS: Record<ChartTargetType, PlotElement> = {
  column: 'barChart',
  bar: 'barChart',
  line: 'lineChart',
  area: 'areaChart',
  pie: 'pieChart',
  doughnut: 'doughnutChart',
}

/// Axis ids synthesized when a pie gains axes; any values work as long as
/// plot and axes agree, and 9xx keeps them clear of authoring-tool ids.
const SYNTH_CAT_AXIS_ID = '900000001'
const SYNTH_VAL_AXIS_ID = '900000002'

function escapeXmlText(input: string): string {
  return input.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
}

function escapeXmlAttribute(input: string): string {
  return escapeXmlText(input).replaceAll('"', '&quot;')
}

function assertHexColor(color: string): string {
  if (!/^#[0-9A-Fa-f]{6}$/.test(color)) {
    throw new ChartEditError(`非法颜色 "${color}"：需要 #RRGGBB。`)
  }
  return color.slice(1).toUpperCase()
}

/// Single-plot matcher for the label-capable family (used by several edits).
const LABELABLE_PLOT_PATTERN =
  /<c:(barChart|lineChart|areaChart|pieChart|doughnutChart)>([\s\S]*?)(<\/c:\1>)/

export function applyChartEdit(chartXml: string, edit: ChartEditLean): string {
  let xml = chartXml
  if (edit.chartType !== undefined) xml = convertChartType(xml, edit.chartType)
  if (edit.title !== undefined) xml = setChartTitle(xml, edit.title)
  // Full replacement first: the index-keyed edits below target the new set.
  if (edit.seriesSet !== undefined) xml = replaceSeries(xml, edit.seriesSet)
  if (edit.seriesColors !== undefined) {
    for (const [index, color] of Object.entries(edit.seriesColors)) {
      xml = setSeriesColor(xml, Number(index), color)
    }
  }
  if (edit.pointColors !== undefined) {
    for (const [index, points] of Object.entries(edit.pointColors)) {
      xml = setPointColors(xml, Number(index), points)
    }
  }
  if (edit.legend !== undefined) xml = setLegend(xml, edit.legend)
  if (edit.dataLabels !== undefined) xml = setDataLabels(xml, edit.dataLabels)
  // 'none' in the same batch wins: the labels are gone, position/format drop.
  if (
    edit.dataLabels !== 'none' &&
    (edit.dataLabelPosition !== undefined || edit.dataLabelFormat !== undefined)
  ) {
    xml = setDataLabelDetail(xml, edit.dataLabelPosition, edit.dataLabelFormat)
  }
  if (edit.axisTitles !== undefined) {
    if (edit.axisTitles.category !== undefined) {
      xml = setAxisTitle(xml, 'catAx', edit.axisTitles.category)
    }
    if (edit.axisTitles.value !== undefined) {
      xml = setAxisTitle(xml, 'valAx', edit.axisTitles.value)
    }
  }
  if (edit.grouping !== undefined) xml = setGrouping(xml, edit.grouping)
  if (edit.gridlines !== undefined) xml = setGridlines(xml, edit.gridlines)
  if (edit.valueAxis !== undefined) xml = setValueAxisBounds(xml, edit.valueAxis)
  if (edit.gapWidthPct !== undefined) xml = setGapWidth(xml, edit.gapWidthPct)
  if (edit.holeSizePct !== undefined) xml = setHoleSize(xml, edit.holeSizePct)
  if (edit.explosionPct !== undefined) xml = setSeriesExplosion(xml, edit.explosionPct)
  if (edit.pointExplosions !== undefined) xml = setPointExplosions(xml, edit.pointExplosions)
  if (edit.series !== undefined) {
    for (const entry of edit.series) {
      xml = setSeriesData(xml, entry)
    }
  }
  return xml
}

function spliceAt(xml: string, at: number, length: number, replacement: string): string {
  return xml.slice(0, at) + replacement + xml.slice(at + length)
}

function builtTitle(escapedText: string): string {
  return (
    '<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r>' +
    `<a:t>${escapedText}</a:t>` +
    '</a:r></a:p></c:rich></c:tx><c:overlay val="0"/></c:title>'
  )
}

const GRIDLINES_PATTERN = /<c:majorGridlines\/>|<c:majorGridlines>[\s\S]*?<\/c:majorGridlines>/

const VAL_AXIS_PATTERN = /<c:valAx>([\s\S]*?)<\/c:valAx>/

/// Major gridlines on the first value axis on/off. CT_ValAx order: axId,
/// scaling, delete, axPos, majorGridlines, minorGridlines, title, …
function setGridlines(chartXml: string, on: boolean): string {
  const axisMatch = chartXml.match(VAL_AXIS_PATTERN)
  if (!axisMatch || axisMatch[1] === undefined || axisMatch.index === undefined) {
    throw new ChartEditError('Chart has no value axis.')
  }
  const inner = axisMatch[1]
  if (!on) {
    return spliceAt(
      chartXml,
      axisMatch.index,
      axisMatch[0].length,
      `<c:valAx>${inner.replace(GRIDLINES_PATTERN, '')}</c:valAx>`,
    )
  }
  if (GRIDLINES_PATTERN.test(inner)) return chartXml
  const anchor =
    inner.match(/<c:axPos val="[^"]*"\/>/) ?? inner.match(/<c:delete val="[^"]*"\/>/)
  if (!anchor || anchor.index === undefined) {
    throw new ChartEditError('Chart axis is missing its position element.')
  }
  const at = anchor.index + anchor[0].length
  return spliceAt(
    chartXml,
    axisMatch.index,
    axisMatch[0].length,
    `<c:valAx>${inner.slice(0, at)}<c:majorGridlines/>${inner.slice(at)}</c:valAx>`,
  )
}

/// Bar/line/area `c:grouping`. 'clustered' maps to 'standard' for line/area
/// (ST_Grouping has no clustered member). Stacked bars are written with
/// full overlap (c:overlap 100); clustered returns to the conventional -27.
function setGrouping(chartXml: string, grouping: NonNullable<ChartEditLean['grouping']>): string {
  const plotMatch = chartXml.match(/<c:(barChart|lineChart|areaChart)>([\s\S]*?)<\/c:\1>/)
  if (!plotMatch?.[1] || plotMatch[2] === undefined) {
    throw new ChartEditError('Only bar, line, and area charts support stacking.')
  }
  const plot = plotMatch[1]
  const value = grouping === 'clustered' && plot !== 'barChart' ? 'standard' : grouping
  let inner = plotMatch[2]
  if (/<c:grouping val="[^"]*"\/>/.test(inner)) {
    inner = inner.replace(/<c:grouping val="[^"]*"\/>/, () => `<c:grouping val="${value}"/>`)
  } else {
    // CT_*Chart order: (barDir,) grouping, varyColors, ser*…
    const barDir = inner.match(/<c:barDir val="[^"]*"\/>/)
    const at = barDir?.index !== undefined ? barDir.index + barDir[0].length : 0
    inner = inner.slice(0, at) + `<c:grouping val="${value}"/>` + inner.slice(at)
  }
  if (plot === 'barChart') {
    const overlap = grouping === 'clustered' ? '-27' : '100'
    if (/<c:overlap val="[^"]*"\/>/.test(inner)) {
      inner = inner.replace(/<c:overlap val="[^"]*"\/>/, () => `<c:overlap val="${overlap}"/>`)
    } else {
      // CT_BarChart puts overlap right before the axId pair.
      const axId = inner.match(/<c:axId val="[0-9]+"\/>/)
      if (!axId || axId.index === undefined) {
        throw new ChartEditError('Chart has no axes for a stacking edit.')
      }
      inner = inner.slice(0, axId.index) + `<c:overlap val="${overlap}"/>` + inner.slice(axId.index)
    }
  }
  return chartXml.replace(plotMatch[0], () => `<c:${plot}>${inner}</c:${plot}>`)
}

/// Value-axis min/max on the first value axis; null resets a bound to auto.
function setValueAxisBounds(
  chartXml: string,
  bounds: NonNullable<ChartEditLean['valueAxis']>,
): string {
  const axisMatch = chartXml.match(VAL_AXIS_PATTERN)
  if (!axisMatch || axisMatch[1] === undefined || axisMatch.index === undefined) {
    throw new ChartEditError('Chart has no value axis.')
  }
  const scalingMatch = axisMatch[1].match(/<c:scaling>([\s\S]*?)<\/c:scaling>/)
  if (!scalingMatch || scalingMatch[1] === undefined || scalingMatch.index === undefined) {
    throw new ChartEditError('Chart value axis has no scaling element.')
  }
  let scaling = scalingMatch[1]
  if (bounds.max !== undefined) scaling = patchScalingBound(scaling, 'max', bounds.max)
  if (bounds.min !== undefined) scaling = patchScalingBound(scaling, 'min', bounds.min)
  const inner = spliceAt(
    axisMatch[1],
    scalingMatch.index,
    scalingMatch[0].length,
    `<c:scaling>${scaling}</c:scaling>`,
  )
  return spliceAt(
    chartXml,
    axisMatch.index,
    axisMatch[0].length,
    `<c:valAx>${inner}</c:valAx>`,
  )
}

/// CT_Scaling order: logBase, orientation, max, min.
function patchScalingBound(
  scalingInner: string,
  bound: 'max' | 'min',
  value: number | null,
): string {
  const pattern = new RegExp(`<c:${bound} val="[^"]*"/>`)
  if (value === null) return scalingInner.replace(pattern, '')
  const element = `<c:${bound} val="${value}"/>`
  if (pattern.test(scalingInner)) return scalingInner.replace(pattern, () => element)
  const anchors =
    bound === 'max'
      ? /<c:logBase val="[^"]*"\/>|<c:orientation val="[^"]*"\/>/g
      : /<c:logBase val="[^"]*"\/>|<c:orientation val="[^"]*"\/>|<c:max val="[^"]*"\/>/g
  let insertAt = 0
  for (const found of scalingInner.matchAll(anchors)) {
    if (found.index !== undefined) insertAt = found.index + found[0].length
  }
  return scalingInner.slice(0, insertAt) + element + scalingInner.slice(insertAt)
}

/// CT_BarChart order: …ser*, dLbls, gapWidth, overlap, axId.
function setGapWidth(chartXml: string, pct: number): string {
  const plotMatch = chartXml.match(/<c:barChart>([\s\S]*?)<\/c:barChart>/)
  if (!plotMatch || plotMatch[1] === undefined) {
    throw new ChartEditError('Only bar charts have a gap width.')
  }
  const inner = plotMatch[1]
  const element = `<c:gapWidth val="${pct}"/>`
  const existing = /<c:gapWidth val="[^"]*"\/>/
  if (existing.test(inner)) {
    return chartXml.replace(
      /<c:barChart>[\s\S]*?<\/c:barChart>/,
      () => `<c:barChart>${inner.replace(existing, () => element)}</c:barChart>`,
    )
  }
  let insertAt = -1
  for (const found of inner.matchAll(/<\/c:ser>|<\/c:dLbls>/g)) {
    if (found.index !== undefined) insertAt = found.index + found[0].length
  }
  if (insertAt === -1) throw new ChartEditError('This chart has no series.')
  return chartXml.replace(
    /<c:barChart>[\s\S]*?<\/c:barChart>/,
    () => `<c:barChart>${inner.slice(0, insertAt)}${element}${inner.slice(insertAt)}</c:barChart>`,
  )
}

/// holeSize is the last CT_DoughnutChart member (before extLst).
function setHoleSize(chartXml: string, pct: number): string {
  const plotMatch = chartXml.match(/<c:doughnutChart>([\s\S]*?)<\/c:doughnutChart>/)
  if (!plotMatch || plotMatch[1] === undefined) {
    throw new ChartEditError('Only doughnut charts have a hole size.')
  }
  const inner = plotMatch[1]
  const element = `<c:holeSize val="${pct}"/>`
  const existing = /<c:holeSize val="[^"]*"\/>/
  let next: string
  if (existing.test(inner)) {
    next = inner.replace(existing, () => element)
  } else {
    const extLst = inner.match(/<c:extLst[\s/>]/)
    const at = extLst?.index ?? inner.length
    next = inner.slice(0, at) + element + inner.slice(at)
  }
  return chartXml.replace(
    /<c:doughnutChart>[\s\S]*?<\/c:doughnutChart>/,
    () => `<c:doughnutChart>${next}</c:doughnutChart>`,
  )
}

/// Patches the first series of the first pie/doughnut plot.
function withFirstPieSeries(
  chartXml: string,
  what: string,
  patch: (serXml: string) => string,
): string {
  const plotMatch = chartXml.match(/<c:(pieChart|doughnutChart)>([\s\S]*?)<\/c:\1>/)
  if (!plotMatch?.[1] || plotMatch[2] === undefined) {
    throw new ChartEditError(`Only pie and doughnut charts support ${what}.`)
  }
  const serMatch = plotMatch[2].match(/<c:ser>[\s\S]*?<\/c:ser>/)
  if (!serMatch || serMatch.index === undefined) {
    throw new ChartEditError('This chart has no series.')
  }
  const inner = spliceAt(plotMatch[2], serMatch.index, serMatch[0].length, patch(serMatch[0]))
  return chartXml.replace(plotMatch[0], () => `<c:${plotMatch[1]}>${inner}</c:${plotMatch[1]}>`)
}

/// Series-level explosion (whole ring). CT_PieSer order: …spPr, explosion,
/// dPt* — a dPt's own explosion must stay untouched, so only the slice
/// before the first dPt is considered.
function setSeriesExplosion(chartXml: string, pct: number): string {
  return withFirstPieSeries(chartXml, 'explosion', (serXml) => {
    const element = `<c:explosion val="${pct}"/>`
    const dPtAt = serXml.search(/<c:dPt[>/]/)
    const scope = dPtAt === -1 ? serXml : serXml.slice(0, dPtAt)
    const tail = dPtAt === -1 ? '' : serXml.slice(dPtAt)
    const pattern = /<c:explosion val="[^"]*"\/>/
    if (pattern.test(scope)) return scope.replace(pattern, () => element) + tail
    if (dPtAt !== -1) return scope + element + tail
    const anchor = serXml.match(/<c:dLbls[>/]|<c:cat[>/]|<c:val[>/]/)
    const at = anchor?.index ?? serXml.lastIndexOf('</c:ser>')
    return serXml.slice(0, at) + element + serXml.slice(at)
  })
}

/// Per-slice explosion overrides on the first pie/doughnut series.
function setPointExplosions(chartXml: string, points: Readonly<Record<string, number>>): string {
  return withFirstPieSeries(chartXml, 'per-slice explosion', (serXml) => {
    let next = serXml
    const entries = Object.entries(points)
      .map(([point, pct]) => [Number(point), pct] as const)
      .sort((a, b) => a[0] - b[0])
    for (const [point, pct] of entries) {
      next = upsertPointExplosion(next, point, pct)
    }
    return next
  })
}

function upsertPointExplosion(serXml: string, pointIndex: number, pct: number): string {
  const element = `<c:explosion val="${pct}"/>`
  const dPts = [...serXml.matchAll(/<c:dPt>[\s\S]*?<\/c:dPt>/g)]
  for (const dPt of dPts) {
    if (dPt.index === undefined) continue
    const idx = Number(dPt[0].match(/<c:idx val="([0-9]+)"\/>/)?.[1])
    if (idx !== pointIndex) continue
    const pattern = /<c:explosion val="[^"]*"\/>/
    let patched: string
    if (pattern.test(dPt[0])) {
      patched = dPt[0].replace(pattern, () => element)
    } else {
      // CT_DPt order: idx, invertIfNegative, marker, bubble3D, explosion, spPr.
      const anchor = dPt[0].match(/<c:spPr[\s/>]|<c:pictureOptions[\s/>]|<c:extLst[\s/>]/)
      const at = anchor?.index ?? dPt[0].lastIndexOf('</c:dPt>')
      patched = dPt[0].slice(0, at) + element + dPt[0].slice(at)
    }
    return serXml.slice(0, dPt.index) + patched + serXml.slice(dPt.index + dPt[0].length)
  }
  const created = `<c:dPt><c:idx val="${pointIndex}"/><c:bubble3D val="0"/>${element}</c:dPt>`
  const insertAt = dPtInsertionIndex(serXml, dPts, pointIndex)
  return serXml.slice(0, insertAt) + created + serXml.slice(insertAt)
}

const REPLACEABLE_PLOTS: readonly string[] = [
  'barChart',
  'lineChart',
  'areaChart',
  'pieChart',
  'doughnutChart',
  'radarChart',
  'scatterChart',
]

/// Full series replacement (Select Data) on a single-plot chart: every
/// existing c:ser (with its dPt/trendline baggage) drops, the new set is
/// written in order at the old series slot, other plot children stay.
function replaceSeries(
  chartXml: string,
  entries: readonly ChartSeriesSetEntry[],
): string {
  const plotPattern =
    /<c:(barChart|lineChart|areaChart|bar3DChart|line3DChart|area3DChart|pieChart|pie3DChart|doughnutChart|scatterChart|radarChart)>([\s\S]*?)<\/c:\1>/g
  const plots = [...chartXml.matchAll(plotPattern)]
  const plotMatch = plots[0]
  if (!plotMatch?.[1] || plotMatch[2] === undefined || plotMatch.index === undefined) {
    throw new ChartEditError('This chart type does not support series replacement.')
  }
  if (plots.length > 1) {
    throw new ChartEditError('Combo charts cannot have their series replaced.')
  }
  const plot = plotMatch[1]
  if (!REPLACEABLE_PLOTS.includes(plot)) {
    throw new ChartEditError(`Replacing series on a ${plot} is not supported.`)
  }
  const inner = plotMatch[2]
  const firstSer = inner.search(/<c:ser>/)
  if (firstSer === -1) throw new ChartEditError('This chart has no series.')
  const built = entries
    .map((entry, index) =>
      plot === 'scatterChart'
        ? buildScatterSeriesReplacement(entry, index)
        : buildSeriesReplacement(entry, index),
    )
    .join('')
  const nextInner =
    inner.slice(0, firstSer) + built + inner.slice(firstSer).replace(/<c:ser>[\s\S]*?<\/c:ser>/g, '')
  return (
    chartXml.slice(0, plotMatch.index) +
    `<c:${plot}>${nextInner}</c:${plot}>` +
    chartXml.slice(plotMatch.index + plotMatch[0].length)
  )
}

/// Same cache structure buildSeriesXml (chart-add) produces: refs get
/// strRef/numRef with caches, ref-less data becomes strLit/numLit.
function buildSeriesReplacement(entry: ChartSeriesSetEntry, index: number): string {
  const color = entry.color === undefined ? undefined : assertHexColor(entry.color)
  const spPr =
    color === undefined
      ? ''
      : `<c:spPr><a:solidFill><a:srgbClr val="${color}"/></a:solidFill></c:spPr>`
  const categories = entry.categories?.slice(0, entry.values.length)
  const catPoints = (categories ?? [])
    .map((value, idx) => `<c:pt idx="${idx}"><c:v>${escapeXmlText(value)}</c:v></c:pt>`)
    .join('')
  const cat =
    categories === undefined || categories.length === 0
      ? ''
      : '<c:cat>' +
        (entry.categoriesRef !== undefined
          ? `<c:strRef><c:f>${escapeXmlText(entry.categoriesRef)}</c:f>` +
            `<c:strCache><c:ptCount val="${categories.length}"/>${catPoints}</c:strCache></c:strRef>`
          : `<c:strLit><c:ptCount val="${categories.length}"/>${catPoints}</c:strLit>`) +
        '</c:cat>'
  const val = `<c:val>${numDataXml(entry.valuesRef, entry.values)}</c:val>`
  return (
    `<c:ser><c:idx val="${index}"/><c:order val="${index}"/>` +
    `<c:tx><c:v>${escapeXmlText(entry.name)}</c:v></c:tx>${spPr}${cat}${val}</c:ser>`
  )
}

/// numRef with cache when a ref is given, numLit otherwise.
function numDataXml(ref: string | undefined, values: readonly number[]): string {
  const points =
    `<c:ptCount val="${values.length}"/>` +
    values.map((value, idx) => `<c:pt idx="${idx}"><c:v>${value}</c:v></c:pt>`).join('')
  return ref !== undefined
    ? `<c:numRef><c:f>${escapeXmlText(ref)}</c:f>` +
        `<c:numCache><c:formatCode>General</c:formatCode>${points}</c:numCache></c:numRef>`
    : `<c:numLit>${points}</c:numLit>`
}

/// Scatter rebuild, mirroring buildScatterSeriesXml (chart-add):
/// all-numeric categories become the X values, otherwise ordinals 0..n-1.
/// CT_ScatterSer: idx, order, tx, spPr, …, xVal, yVal, smooth.
function buildScatterSeriesReplacement(entry: ChartSeriesSetEntry, index: number): string {
  const color = entry.color === undefined ? undefined : assertHexColor(entry.color)
  const spPr =
    color === undefined
      ? ''
      : '<c:spPr><a:ln><a:solidFill>' +
        `<a:srgbClr val="${color}"/></a:solidFill></a:ln></c:spPr>`
  const categories = entry.categories?.slice(0, entry.values.length) ?? []
  const numericCategories = categories.map((value) => Number(value))
  const categoriesAreNumeric =
    categories.length === entry.values.length &&
    categories.length > 0 &&
    numericCategories.every((value) => Number.isFinite(value))
  const xValues = categoriesAreNumeric ? numericCategories : entry.values.map((_unused, idx) => idx)
  const xVal = `<c:xVal>${numDataXml(categoriesAreNumeric ? entry.categoriesRef : undefined, xValues)}</c:xVal>`
  const yVal = `<c:yVal>${numDataXml(entry.valuesRef, entry.values)}</c:yVal>`
  return (
    `<c:ser><c:idx val="${index}"/><c:order val="${index}"/>` +
    `<c:tx><c:v>${escapeXmlText(entry.name)}</c:v></c:tx>${spPr}${xVal}${yVal}` +
    '<c:smooth val="0"/></c:ser>'
  )
}

const LEGEND_POSITIONS: Record<string, string> = {
  right: 'r',
  bottom: 'b',
  top: 't',
  left: 'l',
}

/// Removes the legend or moves/creates it at the given side.
function setLegend(chartXml: string, legend: NonNullable<ChartEditLean['legend']>): string {
  const withoutLegend = chartXml.replace(/<c:legend>[\s\S]*?<\/c:legend>/, '')
  if (legend === 'none') return withoutLegend
  const position = LEGEND_POSITIONS[legend]
  const element = `<c:legend><c:legendPos val="${position}"/><c:overlay val="0"/></c:legend>`
  const plotAreaEnd = withoutLegend.match(/<\/c:plotArea>/)
  if (!plotAreaEnd || plotAreaEnd.index === undefined) {
    throw new ChartEditError('Chart part has no plot area.')
  }
  const insertAt = plotAreaEnd.index + plotAreaEnd[0].length
  return withoutLegend.slice(0, insertAt) + element + withoutLegend.slice(insertAt)
}

const LABEL_CHILD_ORDER = ['dLbl','delete','numFmt','spPr','txPr','dLblPos','showLegendKey','showVal','showCatName','showSerName','showPercent','showBubbleSize','separator','showLeaderLines','leaderLines','extLst']

/** SAX identifies direct children; their original byte spans stay untouched.
 * A point's nested numFmt/showVal/txPr must never become the plot defaults.
 */
function setLabelChildren(body: string, updates: Record<string,string>): string {
  for (const [local,replacement] of Object.entries(updates)) {
    const parser = new SaxesParser({fragment:true}), nodes: Array<{name:string;start:number;end:number}> = []
    let depth = 0, current: typeof nodes[number] | undefined
    parser.on('doctype',()=>{throw new ChartEditError('Data labels do not support DOCTYPE.')})
    parser.on('opentag',tag=>{
      if (depth++ === 0) current = {name:tag.name,start:body.lastIndexOf('<',parser.position-1),end:parser.position}
    })
    parser.on('closetag',()=>{if (--depth === 0 && current) {current.end=parser.position;nodes.push(current);current=undefined}})
    parser.write(body).close()
    const matches = nodes.filter(node=>node.name === 'c:'+local)
    if (matches.length > 1) throw new ChartEditError('Duplicate plot data-label property: '+local)
    const existing = matches[0]
    const rank = LABEL_CHILD_ORDER.indexOf(local)
    const before = nodes.find(node=>{const index=LABEL_CHILD_ORDER.indexOf(node.name.replace(/^c:/,''));return index >= 0 && index > rank})
    const start = existing?.start ?? before?.start ?? body.length
    body = spliceAt(body,start,existing ? existing.end-existing.start : 0,replacement)
  }
  return body
}

function plotLabelBlock(inner: string): {start:number;length:number;open:string;body:string} | undefined {
  const afterSeries = inner.lastIndexOf('</c:ser>') + '</c:ser>'.length
  const found = inner.slice(afterSeries).match(/^\s*(<c:dLbls\b[^>]*\/>|<c:dLbls\b[^>]*>([\s\S]*?)<\/c:dLbls>)/)
  if (!found) return undefined
  const block = found[1]!
  return {start:afterSeries+found[0].length-block.length,length:block.length,open:block.match(/^<c:dLbls\b[^>]*>/)![0].replace(/\/>$/,'>'),body:found[2] ?? ''}
}

/// Plot-level data labels: what every slice/bar/point shows. 'none' removes
/// the plot-level element (per-series overrides, if any, keep their own).
function setDataLabels(
  chartXml: string,
  mode: NonNullable<ChartEditLean['dataLabels']>,
): string {
  const plotMatch = chartXml.match(LABELABLE_PLOT_PATTERN)
  if (!plotMatch?.[1] || plotMatch[2] === undefined) {
    throw new ChartEditError('This chart type does not support data labels.')
  }
  const inner = plotMatch[2]
  const existing = plotLabelBlock(inner)
  let next = existing ? spliceAt(inner,existing.start,existing.length,'') : inner
  if (mode !== 'none') {
    const showValue = mode === 'value'
    const showCategory = mode === 'category-percent'
    const showPercent = mode === 'percent' || mode === 'category-percent'
    const body = setLabelChildren(existing?.body ?? '',{
      showLegendKey:'<c:showLegendKey val="0"/>',showVal:`<c:showVal val="${showValue ? '1' : '0'}"/>`,
      showCatName:`<c:showCatName val="${showCategory ? '1' : '0'}"/>`,showSerName:'<c:showSerName val="0"/>',
      showPercent:`<c:showPercent val="${showPercent ? '1' : '0'}"/>`,showBubbleSize:'<c:showBubbleSize val="0"/>',
    })
    const labels = (existing?.open ?? '<c:dLbls>')+body+'</c:dLbls>'
    const lastSeriesEnd = next.lastIndexOf('</c:ser>')
    if (lastSeriesEnd === -1) throw new ChartEditError('This chart has no series to label.')
    const insertAt = lastSeriesEnd + '</c:ser>'.length
    next = next.slice(0, insertAt) + labels + next.slice(insertAt)
  }
  return chartXml.replace(
    LABELABLE_PLOT_PATTERN,
    (_full, plot: string, _inner: string, close: string) => `<c:${plot}>${next}${close}`,
  )
}

const DLBL_POSITIONS: Record<NonNullable<ChartEditLean['dataLabelPosition']>, string> = {
  center: 'ctr',
  'inside-end': 'inEnd',
  'outside-end': 'outEnd',
}

/// Label position (c:dLblPos) and number format (c:numFmt) on the plot-level
/// dLbls, upgrading an existing element or creating a value-labels one.
/// CT_DLbls order: numFmt, spPr, txPr, dLblPos, show*.
function setDataLabelDetail(
  chartXml: string,
  position: ChartEditLean['dataLabelPosition'],
  format: ChartEditLean['dataLabelFormat'],
): string {
  const plotMatch = chartXml.match(LABELABLE_PLOT_PATTERN)
  if (!plotMatch?.[1] || plotMatch[2] === undefined) {
    throw new ChartEditError('This chart type does not support data labels.')
  }
  const inner = plotMatch[2]
  const numFmt =
    format === undefined
      ? ''
      : `<c:numFmt formatCode="${escapeXmlAttribute(format)}" sourceLinked="0"/>`
  const dLblPos = position === undefined ? '' : `<c:dLblPos val="${DLBL_POSITIONS[position]}"/>`
  const existing = plotLabelBlock(inner)
  let next: string
  if (existing) {
    const labels = setLabelChildren(existing.body,{...(numFmt ? {numFmt}:{}),...(dLblPos ? {dLblPos}: {})})
    next = spliceAt(inner, existing.start, existing.length, `${existing.open}${labels}</c:dLbls>`)
  } else {
    const lastSeriesEnd = inner.lastIndexOf('</c:ser>')
    if (lastSeriesEnd === -1) throw new ChartEditError('This chart has no series to label.')
    const at = lastSeriesEnd + '</c:ser>'.length
    const created =
      `<c:dLbls>${numFmt}${dLblPos}<c:showLegendKey val="0"/><c:showVal val="1"/>` +
      '<c:showCatName val="0"/><c:showSerName val="0"/><c:showPercent val="0"/>' +
      '<c:showBubbleSize val="0"/></c:dLbls>'
    next = inner.slice(0, at) + created + inner.slice(at)
  }
  return chartXml.replace(LABELABLE_PLOT_PATTERN, (_full, plot: string, _i: string, close: string) =>
    `<c:${plot}>${next}${close}`,
  )
}

/// Sets or removes (null) the title of the first category/value axis.
function setAxisTitle(chartXml: string, axis: 'catAx' | 'valAx', title: string | null): string {
  const axisPattern = new RegExp(`<c:${axis}>([\\s\\S]*?)</c:${axis}>`)
  const axisMatch = chartXml.match(axisPattern)
  if (!axisMatch || axisMatch[1] === undefined) {
    // Date axes stand in for category axes on time-series charts.
    if (axis === 'catAx' && /<c:dateAx>/.test(chartXml)) {
      return setDateAxisTitle(chartXml, title)
    }
    throw new ChartEditError(`Chart has no ${axis === 'catAx' ? 'category' : 'value'} axis.`)
  }
  return chartXml.replace(
    axisPattern,
    (_full, inner: string) => `<c:${axis}>${patchAxisInnerTitle(inner, title)}</c:${axis}>`,
  )
}

function setDateAxisTitle(chartXml: string, title: string | null): string {
  return chartXml.replace(
    /<c:dateAx>([\s\S]*?)<\/c:dateAx>/,
    (_full, inner: string) => `<c:dateAx>${patchAxisInnerTitle(inner, title)}</c:dateAx>`,
  )
}

/// CT_*Ax order: the title slot follows axPos / gridlines.
function patchAxisInnerTitle(axisInner: string, title: string | null): string {
  const stripped = axisInner.replace(/<c:title>[\s\S]*?<\/c:title>/, '')
  if (title === null) return stripped
  const anchor =
    /<c:minorGridlines\/>|<c:minorGridlines>[\s\S]*?<\/c:minorGridlines>|<c:majorGridlines\/>|<c:majorGridlines>[\s\S]*?<\/c:majorGridlines>|<c:axPos val="[^"]*"\/>/g
  let insertAt = -1
  for (const found of stripped.matchAll(anchor)) {
    if (found.index !== undefined) insertAt = found.index + found[0].length
  }
  if (insertAt === -1) throw new ChartEditError('Chart axis is missing its position element.')
  return stripped.slice(0, insertAt) + builtTitle(escapeXmlText(title)) + stripped.slice(insertAt)
}

/// Rewrites a series' name and/or data (reference + cached values together).
/// On a scatter plot the categories become numeric X values (c:xVal) and the
/// values land in c:yVal.
function setSeriesData(chartXml: string, entry: ChartSeriesDataEdit): string {
  const isScatter = /<c:scatterChart[\s>]/.test(chartXml)
  const seriesPattern = /<c:ser>[\s\S]*?<\/c:ser>/g
  let found = false
  let position = -1
  const result = chartXml.replace(seriesPattern, (serXml) => {
    position += 1
    if (position !== entry.index) return serXml
    found = true
    let next = serXml
    if (entry.name !== undefined) {
      const tx = `<c:tx><c:v>${escapeXmlText(entry.name)}</c:v></c:tx>`
      if (/<c:tx>[\s\S]*?<\/c:tx>/.test(next)) {
        next = next.replace(/<c:tx>[\s\S]*?<\/c:tx>/, () => tx)
      } else {
        const anchor = next.match(/<c:order val="[0-9]+"\/>/)
        if (!anchor || anchor.index === undefined) {
          throw new ChartEditError('Chart series is missing idx/order structure.')
        }
        next =
          next.slice(0, anchor.index + anchor[0].length) +
          tx +
          next.slice(anchor.index + anchor[0].length)
      }
    }
    if (entry.categories !== undefined) {
      if (isScatter) {
        next = setScatterXValues(next, entry.categories, entry.categoriesRef)
      } else {
        const catPattern = /<c:cat\/>|<c:cat>[\s\S]*?<\/c:cat>/
        const previousCat = next.match(catPattern)?.[0] ?? ''
        // Numeric categories cached as numRef/numLit (dates) keep that
        // shape and its formatCode; a strRef rewrite drops the format for good.
        const numeric = entry.categories.map((value) => Number(value))
        const keepNumeric =
          /<c:num(?:Ref|Lit)[\s>]/.test(previousCat) &&
          entry.categories.length > 0 &&
          entry.categories.every(
            (value, idx) => value.trim() !== '' && Number.isFinite(numeric[idx]),
          )
        // A ref-less entry must not demote an existing reference to a
        // literal: keep the previous c:f (already escaped) and only refresh
        // the cache.
        const catRefXml =
          entry.categoriesRef !== undefined
            ? escapeXmlText(entry.categoriesRef)
            : previousCat.match(/<c:f>([\s\S]*?)<\/c:f>/)?.[1]
        let cat: string
        if (keepNumeric) {
          const formatCode =
            previousCat.match(/<c:formatCode>([^<]*)<\/c:formatCode>/)?.[1] ?? 'General'
          const data =
            `<c:formatCode>${formatCode}</c:formatCode>` +
            `<c:ptCount val="${entry.categories.length}"/>` +
            numeric.map((value, idx) => `<c:pt idx="${idx}"><c:v>${value}</c:v></c:pt>`).join('')
          // c:f is mandatory inside numRef, so ref-less data must be a literal.
          cat =
            catRefXml === undefined
              ? `<c:cat><c:numLit>${data}</c:numLit></c:cat>`
              : `<c:cat><c:numRef><c:f>${catRefXml}</c:f>` +
                `<c:numCache>${data}</c:numCache></c:numRef></c:cat>`
        } else {
          const points =
            `<c:ptCount val="${entry.categories.length}"/>` +
            entry.categories
              .map((value, idx) => `<c:pt idx="${idx}"><c:v>${escapeXmlText(value)}</c:v></c:pt>`)
              .join('')
          // c:f is mandatory inside strRef, so ref-less data must be a literal.
          cat =
            catRefXml === undefined
              ? `<c:cat><c:strLit>${points}</c:strLit></c:cat>`
              : `<c:cat><c:strRef><c:f>${catRefXml}</c:f>` +
                `<c:strCache>${points}</c:strCache></c:strRef></c:cat>`
        }
        if (previousCat !== '') {
          next = next.replace(catPattern, () => cat)
        } else {
          const valElement = next.match(/<c:val\/>|<c:val>/)
          if (!valElement || valElement.index === undefined) {
            throw new ChartEditError('Chart series has no value element.')
          }
          next = next.slice(0, valElement.index) + cat + next.slice(valElement.index)
        }
      }
    }
    if (entry.values !== undefined) {
      const tag = isScatter ? 'yVal' : 'val'
      const points = entry.values
        .map((value, idx) => `<c:pt idx="${idx}"><c:v>${value}</c:v></c:pt>`)
        .join('')
      // Keep the original number format: the axis-scale renderer reads it.
      const valPattern = new RegExp(`<c:${tag}/>|<c:${tag}>[\\s\\S]*?</c:${tag}>`)
      const previousVal = next.match(valPattern)?.[0] ?? ''
      const formatCode =
        previousVal.match(/<c:formatCode>([^<]*)<\/c:formatCode>/)?.[1] ?? 'General'
      const data =
        `<c:formatCode>${formatCode}</c:formatCode>` +
        `<c:ptCount val="${entry.values.length}"/>${points}`
      // c:f is mandatory inside numRef, so ref-less data must be a literal —
      // but never demote an existing reference (see the c:cat rewrite above).
      const valRefXml =
        entry.valuesRef !== undefined
          ? escapeXmlText(entry.valuesRef)
          : previousVal.match(/<c:f>([\s\S]*?)<\/c:f>/)?.[1]
      const val =
        valRefXml === undefined
          ? `<c:${tag}><c:numLit>${data}</c:numLit></c:${tag}>`
          : `<c:${tag}><c:numRef><c:f>${valRefXml}</c:f>` +
            `<c:numCache>${data}</c:numCache></c:numRef></c:${tag}>`
      if (!valPattern.test(next)) throw new ChartEditError('Chart series has no value element.')
      next = next.replace(valPattern, () => val)
    }
    return next
  })
  if (!found) throw new ChartEditError(`Chart has no series with index ${entry.index}.`)
  return result
}

/// Scatter X data (c:xVal): categories numericized, a non-numeric entry
/// falls back to its own index.
function setScatterXValues(
  serXml: string,
  categories: readonly string[],
  categoriesRef: string | undefined,
): string {
  const points =
    `<c:formatCode>General</c:formatCode><c:ptCount val="${categories.length}"/>` +
    categories
      .map((value, idx) => {
        const numeric = Number(value)
        const x = value.trim() !== '' && Number.isFinite(numeric) ? numeric : idx
        return `<c:pt idx="${idx}"><c:v>${x}</c:v></c:pt>`
      })
      .join('')
  const xValPattern = /<c:xVal\/>|<c:xVal>[\s\S]*?<\/c:xVal>/
  // Same demotion guard as c:cat/c:val: a ref-less rewrite keeps an
  // existing c:f rather than baking the reference into a literal.
  const refXml =
    categoriesRef !== undefined
      ? escapeXmlText(categoriesRef)
      : serXml.match(xValPattern)?.[0].match(/<c:f>([\s\S]*?)<\/c:f>/)?.[1]
  const xVal =
    refXml === undefined
      ? `<c:xVal><c:numLit>${points}</c:numLit></c:xVal>`
      : `<c:xVal><c:numRef><c:f>${refXml}</c:f>` +
        `<c:numCache>${points}</c:numCache></c:numRef></c:xVal>`
  if (xValPattern.test(serXml)) return serXml.replace(xValPattern, () => xVal)
  // CT_ScatterSer: xVal precedes yVal and smooth.
  const anchor = serXml.match(/<c:yVal[>/]|<c:smooth[\s/>]/)
  const at = anchor?.index ?? serXml.lastIndexOf('</c:ser>')
  return serXml.slice(0, at) + xVal + serXml.slice(at)
}

function setChartTitle(chartXml: string, title: string): string {
  const escaped = escapeXmlText(title)
  const xml = chartXml.replace(/<c:autoTitleDeleted val="1"\/>/, '<c:autoTitleDeleted val="0"/>')
  const plotAreaAt = xml.search(/<c:plotArea[\s>]/)
  const scope = plotAreaAt === -1 ? xml : xml.slice(0, plotAreaAt)
  const titleElement = scope.match(/<c:title>[\s\S]*?<\/c:title>/)
  if (titleElement) {
    let isFirstRun = true
    const rewritten = titleElement[0].replace(
      /(<a:t>)[\s\S]*?(<\/a:t>)|<a:t\/>/g,
      (full, open: string | undefined, close: string | undefined) => {
        const text = isFirstRun ? escaped : ''
        isFirstRun = false
        return `${open ?? '<a:t>'}${text}${close ?? '</a:t>'}`
      },
    )
    if (isFirstRun) {
      // A title without any text run (e.g. formula-linked): replace whole tx.
      return xml.replace(/<c:title>[\s\S]*?<\/c:title>/, () => builtTitle(escaped))
    }
    return xml.replace(/<c:title>[\s\S]*?<\/c:title>/, () => rewritten)
  }
  const chartOpen = xml.match(/<c:chart>/)
  if (!chartOpen) throw new ChartEditError('Chart part has no c:chart element.')
  const insertAt = (chartOpen.index ?? 0) + chartOpen[0].length
  const autoTitle = /<c:autoTitleDeleted /.test(xml) ? '' : '<c:autoTitleDeleted val="0"/>'
  return xml.slice(0, insertAt) + `${builtTitle(escaped)}${autoTitle}` + xml.slice(insertAt)
}

/// Converts between column/bar/line/area/pie/doughnut. Bar direction changes
/// rewrite only c:barDir; cross-type conversion rebuilds the plot element
/// keeping series and dropping type-specific leftovers. Axis↔pie conversions
/// also remove or synthesize the axis pair, since pie plots reference none.
function convertChartType(chartXml: string, target: ChartTargetType): string {
  const plotPattern =
    /<c:(barChart|lineChart|areaChart|bar3DChart|line3DChart|area3DChart|pieChart|pie3DChart|doughnutChart|scatterChart|radarChart)>([\s\S]*?)<\/c:\1>/g
  const plots = [...chartXml.matchAll(plotPattern)]
  const plotMatch = plots[0]
  if (!plotMatch?.[1] || plotMatch[2] === undefined) {
    throw new ChartEditError('This chart type cannot be converted.')
  }
  if (plots.length > 1) {
    throw new ChartEditError('Combo charts cannot be converted.')
  }
  const current = plotMatch[1] as string
  if (!(CONVERTIBLE_PLOTS as readonly string[]).includes(current)) {
    throw new ChartEditError(`Converting a ${current} is not supported.`)
  }
  const inner = plotMatch[2]
  const targetElement = TARGET_PLOTS[target]
  const currentIsPie = current === 'pieChart' || current === 'doughnutChart'
  const targetIsPie = targetElement === 'pieChart' || targetElement === 'doughnutChart'

  if (current === 'barChart' && targetElement === 'barChart') {
    const direction = target === 'column' ? 'col' : 'bar'
    return chartXml.replace(/<c:barDir val="[^"]*"\/>/, () => `<c:barDir val="${direction}"/>`)
  }
  if (targetElement === current) return chartXml

  const series = [...inner.matchAll(/<c:ser>[\s\S]*?<\/c:ser>/g)].map((match) =>
    sanitizeSeries(match[0], targetIsPie),
  )
  if (series.length === 0) {
    throw new ChartEditError('This chart has no series to convert.')
  }
  const parts: string[] = []
  if (targetElement === 'barChart') {
    parts.push(`<c:barDir val="${target === 'bar' ? 'bar' : 'col'}"/>`)
  }
  if (!targetIsPie) {
    const grouping = inner.match(/<c:grouping val="(stacked|percentStacked)"\/>/)?.[1]
    parts.push(
      `<c:grouping val="${grouping ?? (targetElement === 'barChart' ? 'clustered' : 'standard')}"/>`,
    )
  }
  parts.push(`<c:varyColors val="${targetIsPie ? '1' : '0'}"/>`, ...series)
  // Plot-level data labels survive; only the position is dropped (values
  // differ per chart type).
  const plotLabels = inner.match(/<\/c:ser>(<c:dLbls>[\s\S]*?<\/c:dLbls>)/)?.[1]
  if (plotLabels) parts.push(plotLabels.replace(/<c:dLblPos val="[^"]*"\/>/, ''))
  if (targetElement === 'barChart') parts.push('<c:gapWidth val="150"/>')
  if (targetElement === 'lineChart') parts.push('<c:marker val="1"/>')
  if (targetIsPie) {
    parts.push('<c:firstSliceAng val="0"/>')
    if (targetElement === 'doughnutChart') parts.push('<c:holeSize val="50"/>')
    const plotReplaced = chartXml.replace(
      plotMatch[0],
      () => `<c:${targetElement}>${parts.join('')}</c:${targetElement}>`,
    )
    return plotReplaced.replace(
      /<c:(catAx|valAx|dateAx|serAx)>[\s\S]*?<\/c:\1>|<c:(?:catAx|valAx|dateAx|serAx)\/>/g,
      '',
    )
  }
  if (!currentIsPie) {
    const axisIds = [...inner.matchAll(/<c:axId val="[0-9]+"\/>/g)].map((match) => match[0])
    if (axisIds.length === 0) {
      throw new ChartEditError('This chart has no axes to convert.')
    }
    parts.push(...axisIds)
    return chartXml.replace(
      plotMatch[0],
      () => `<c:${targetElement}>${parts.join('')}</c:${targetElement}>`,
    )
  }
  // Pie → axis chart: the plot gains a synthesized category/value axis pair
  // (bar charts flip them onto the other sides).
  parts.push(`<c:axId val="${SYNTH_CAT_AXIS_ID}"/>`, `<c:axId val="${SYNTH_VAL_AXIS_ID}"/>`)
  const catPos = target === 'bar' ? 'l' : 'b'
  const valPos = target === 'bar' ? 'b' : 'l'
  const axes =
    `<c:catAx><c:axId val="${SYNTH_CAT_AXIS_ID}"/>` +
    '<c:scaling><c:orientation val="minMax"/></c:scaling>' +
    `<c:delete val="0"/><c:axPos val="${catPos}"/>` +
    `<c:crossAx val="${SYNTH_VAL_AXIS_ID}"/></c:catAx>` +
    `<c:valAx><c:axId val="${SYNTH_VAL_AXIS_ID}"/>` +
    '<c:scaling><c:orientation val="minMax"/></c:scaling>' +
    `<c:delete val="0"/><c:axPos val="${valPos}"/><c:majorGridlines/>` +
    `<c:crossAx val="${SYNTH_CAT_AXIS_ID}"/></c:valAx>`
  return chartXml.replace(
    plotMatch[0],
    () => `<c:${targetElement}>${parts.join('')}</c:${targetElement}>${axes}`,
  )
}

/// Strips per-type series options that are invalid on other chart types.
function sanitizeSeries(serXml: string, forPie: boolean): string {
  const cleaned = serXml
    .replace(/<c:invertIfNegative val="[^"]*"\/>/g, '')
    .replace(/<c:marker>[\s\S]*?<\/c:marker>/g, '')
    .replace(/<c:smooth val="[^"]*"\/>/g, '')
    .replace(/<c:shape val="[^"]*"\/>/g, '')
    .replace(/<c:explosion val="[^"]*"\/>/g, '')
  // CT_PieSer has no trendline slot.
  return forPie ? cleaned.replace(/<c:trendline>[\s\S]*?<\/c:trendline>/g, '') : cleaned
}

/// Sets a series' solid color (fill + line, so bars and lines both take it).
function setSeriesColor(chartXml: string, seriesIndex: number, color: string): string {
  const argb = assertHexColor(color)
  const spPr =
    `<c:spPr><a:solidFill><a:srgbClr val="${argb}"/></a:solidFill>` +
    `<a:ln><a:solidFill><a:srgbClr val="${argb}"/></a:solidFill></a:ln></c:spPr>`
  let found = false
  // Document position, not c:idx: numbering series by document order keeps
  // edits aligned with what the UI showed as N even when c:idx is shuffled.
  let position = -1
  const result = chartXml.replace(/<c:ser>[\s\S]*?<\/c:ser>/g, (serXml) => {
    position += 1
    if (position !== seriesIndex) return serXml
    found = true
    // The series-level spPr precedes any c:dPt; don't clobber a point's spPr.
    const dPtAt = serXml.indexOf('<c:dPt>')
    const scope = dPtAt === -1 ? serXml : serXml.slice(0, dPtAt)
    const replaced = scope.replace(/<c:spPr>[\s\S]*?<\/c:spPr>/, () => spPr)
    if (replaced !== scope) return replaced + (dPtAt === -1 ? '' : serXml.slice(dPtAt))
    // No spPr yet: schema order puts it right after c:tx (or c:order when
    // the series has no name element).
    const anchor =
      serXml.match(/<c:tx>[\s\S]*?<\/c:tx>/) ?? serXml.match(/<c:order val="[0-9]+"\/>/)
    if (!anchor) throw new ChartEditError('Chart series is missing idx/order structure.')
    const insertAt = (anchor.index ?? 0) + anchor[0].length
    return serXml.slice(0, insertAt) + spPr + serXml.slice(insertAt)
  })
  if (!found) throw new ChartEditError(`Chart has no series with index ${seriesIndex}.`)
  return result
}

/// Per-point fills via c:dPt on the series at the given document position.
function setPointColors(
  chartXml: string,
  seriesIndex: number,
  points: Readonly<Record<string, string>>,
): string {
  let found = false
  let position = -1
  const result = chartXml.replace(/<c:ser>[\s\S]*?<\/c:ser>/g, (serXml) => {
    position += 1
    if (position !== seriesIndex) return serXml
    found = true
    let next = serXml
    const entries = Object.entries(points)
      .map(([point, color]) => [Number(point), color] as const)
      .sort((a, b) => a[0] - b[0])
    for (const [point, color] of entries) {
      next = upsertPointColor(next, point, color)
    }
    return next
  })
  if (!found) throw new ChartEditError(`Chart has no series with index ${seriesIndex}.`)
  return result
}

function upsertPointColor(serXml: string, pointIndex: number, color: string): string {
  const fill = `<a:solidFill><a:srgbClr val="${assertHexColor(color)}"/></a:solidFill>`
  const dPts = [...serXml.matchAll(/<c:dPt>[\s\S]*?<\/c:dPt>/g)]
  for (const dPt of dPts) {
    if (dPt.index === undefined) continue
    const idx = Number(dPt[0].match(/<c:idx val="([0-9]+)"\/>/)?.[1])
    if (idx !== pointIndex) continue
    return (
      serXml.slice(0, dPt.index) +
      patchPointFill(dPt[0], fill) +
      serXml.slice(dPt.index + dPt[0].length)
    )
  }
  const element =
    `<c:dPt><c:idx val="${pointIndex}"/><c:bubble3D val="0"/>` + `<c:spPr>${fill}</c:spPr></c:dPt>`
  const insertAt = dPtInsertionIndex(serXml, dPts, pointIndex)
  return serXml.slice(0, insertAt) + element + serXml.slice(insertAt)
}

/// Where a new dPt with this idx belongs: ascending among existing dPt
/// entries, otherwise before dLbls/cat/val.
function dPtInsertionIndex(
  serXml: string,
  dPts: readonly RegExpMatchArray[],
  pointIndex: number,
): number {
  let insertAt = -1
  for (const dPt of dPts) {
    if (dPt.index === undefined) continue
    const idx = Number(dPt[0].match(/<c:idx val="([0-9]+)"\/>/)?.[1])
    if (idx > pointIndex) return dPt.index
    insertAt = dPt.index + dPt[0].length
  }
  if (insertAt !== -1) return insertAt
  const anchor = serXml.match(/<c:dLbls[>/]|<c:cat[>/]|<c:val[>/]|<c:xVal[>/]/)
  if (!anchor || anchor.index === undefined) {
    throw new ChartEditError('Chart series has no data element to anchor a point.')
  }
  return anchor.index
}

/// Existing dPt: swap only the spPr fill, keeping every other child.
function patchPointFill(dPtXml: string, fill: string): string {
  const spPrMatch = dPtXml.match(/<c:spPr>([\s\S]*?)<\/c:spPr>/)
  if (!spPrMatch || spPrMatch[1] === undefined || spPrMatch.index === undefined) {
    const anchor = dPtXml.match(/<c:pictureOptions[\s/>]|<c:extLst[\s/>]/)
    const insertAt = anchor?.index ?? dPtXml.lastIndexOf('</c:dPt>')
    return dPtXml.slice(0, insertAt) + `<c:spPr>${fill}</c:spPr>` + dPtXml.slice(insertAt)
  }
  const inner = spPrMatch[1]
  // Only touch the shape fill, never a fill nested inside a:ln.
  const lnAt = inner.search(/<a:ln[\s>]/)
  const head = lnAt === -1 ? inner : inner.slice(0, lnAt)
  const tail = lnAt === -1 ? '' : inner.slice(lnAt)
  const fillPattern =
    /<a:noFill\/>|<a:solidFill>[\s\S]*?<\/a:solidFill>|<a:gradFill[\s\S]*?<\/a:gradFill>|<a:pattFill[\s\S]*?<\/a:pattFill>|<a:blipFill[\s\S]*?<\/a:blipFill>|<a:grpFill\/>/
  const nextHead = fillPattern.test(head) ? head.replace(fillPattern, () => fill) : head + fill
  return dPtXml.replace(spPrMatch[0], () => `<c:spPr>${nextHead}${tail}</c:spPr>`)
}
