/// Surgical edits to a chart part (xl/charts/chartN.xml) — port of the
/// genoffice xlsx-chart write path: title text, chart-type conversion within
/// the convertible family, series colors, legend, data labels (mode +
/// position/format), axis titles, stacking, gridlines, value-axis bounds,
/// gap width, doughnut hole, pie explosions, point fills, and series
/// replacement / per-series rewrites. Anything outside the supported
/// envelope throws — fail closed, never corrupt a chart part.

import { SaxesParser } from 'saxes'
import { scatterLabelModes } from './scatter-label-mode'

export class ChartEditError extends Error {}

export type ChartTargetType = 'column' | 'bar' | 'line' | 'area' | 'pie' | 'doughnut'

export interface ChartSeriesSetEntry {
  readonly plot?: 'barChart' | 'lineChart' | undefined
  readonly secondaryAxis?: boolean | undefined
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

interface PlotMatch {
  readonly family: string
  readonly inner: string
  readonly whole: string
  readonly index: number
}

const PLOT_FAMILIES =
  'barChart|lineChart|areaChart|bar3DChart|line3DChart|area3DChart|pieChart|pie3DChart|doughnutChart|scatterChart|radarChart'

/// Every plot group element of the chart part, in document order.
function matchPlots(chartXml: string): PlotMatch[] {
  const pattern = new RegExp(`<c:(${PLOT_FAMILIES})>([\\s\\S]*?)</c:\\1>`, 'g')
  return [...chartXml.matchAll(pattern)].map((match) => ({
    family: match[1] ?? '',
    inner: match[2] ?? '',
    whole: match[0],
    index: match.index ?? 0,
  }))
}

interface AxisMatch {
  readonly kind: 'cat' | 'val'
  readonly xml: string
  readonly id: string | undefined
  readonly crossAx: string | undefined
  /// c:delete val="1" — scales its series but is not drawn.
  readonly hidden: boolean
  /// Value axis drawn on the right / crossing at max — the secondary scale.
  readonly right: boolean
}

/// Every paired-open axis element of the scoped XML, in document order.
/// (Self-closing axes carry no axId and no formatting — nothing to manage.)
function matchAxes(scopedXml: string): AxisMatch[] {
  const pattern = /<c:(catAx|dateAx|valAx)>([\s\S]*?)<\/c:\1>/g
  return [...scopedXml.matchAll(pattern)].map((match) => {
    const tag = match[1] ?? ''
    const inner = match[2] ?? ''
    return {
      kind: tag === 'valAx' ? ('val' as const) : ('cat' as const),
      xml: match[0],
      id: /<c:axId val="([0-9]+)"\/>/.exec(inner)?.[1],
      crossAx: /<c:crossAx val="([0-9]+)"\/>/.exec(inner)?.[1],
      hidden: /<c:delete val="1"\/>/.test(inner),
      right:
        tag === 'valAx' &&
        (/<c:axPos val="r"\/>/.test(inner) || /<c:crosses val="max"\/>/.test(inner)),
    }
  })
}

interface AxisPairSelection {
  readonly primaryCat: AxisMatch | undefined
  readonly primaryVal: AxisMatch | undefined
  readonly secondaryVal: AxisMatch | undefined
  readonly secondaryCat: AxisMatch | undefined
  /// Axes outside the two managed pairs — a rebuild fails closed on them.
  readonly leftovers: readonly AxisMatch[]
}

/// Splits a plotArea's axes into the primary pair (left value axis and the
/// category axis crossing it), the secondary pair, and anything else.
function classifyAxes(axes: readonly AxisMatch[]): AxisPairSelection {
  const vals = axes.filter((axis) => axis.kind === 'val')
  const cats = axes.filter((axis) => axis.kind === 'cat')
  const primaryVal = vals.find((axis) => !axis.right && axis.id !== undefined) ?? vals[0]
  const primaryCat =
    primaryVal === undefined
      ? undefined
      : (cats.find((axis) => axis.crossAx === primaryVal.id) ?? cats[0])
  const rest = axes.filter((axis) => axis !== primaryCat && axis !== primaryVal)
  const secondaryVal = rest.find((axis) => axis.kind === 'val' && axis.right)
  const secondaryCat =
    secondaryVal === undefined
      ? undefined
      : (rest.find((axis) => axis.kind === 'cat' && axis.crossAx === secondaryVal.id) ??
        rest.find((axis) => axis.kind === 'cat'))
  const leftovers = rest.filter((axis) => axis !== secondaryVal && axis !== secondaryCat)
  return { primaryCat, primaryVal, secondaryVal, secondaryCat, leftovers }
}

/// Fresh axIds above every id the plotArea already uses.
function nextAxisIds(plotAreaInner: string, count: number): string[] {
  let max = 0
  for (const found of plotAreaInner.matchAll(/<c:axId val="([0-9]+)"\/>/g)) {
    const value = Number(found[1])
    if (Number.isFinite(value) && value > max) max = value
  }
  return Array.from({ length: count }, (_, index) => String(max + 1 + index))
}

/// Secondary pair synthesized when tagged series need one the file lacks —
/// Insert Chart's shape (hidden category axis, right value axis at max).
function hiddenCatAxisXml(catId: string, valId: string): string {
  return (
    `<c:catAx><c:axId val="${catId}"/>` +
    '<c:scaling><c:orientation val="minMax"/></c:scaling>' +
    `<c:delete val="1"/><c:axPos val="b"/><c:crossAx val="${valId}"/></c:catAx>`
  )
}

function rightValAxisXml(valId: string, catId: string): string {
  return (
    `<c:valAx><c:axId val="${valId}"/>` +
    '<c:scaling><c:orientation val="minMax"/></c:scaling>' +
    `<c:delete val="0"/><c:axPos val="r"/><c:crossAx val="${catId}"/><c:crosses val="max"/></c:valAx>`
  )
}

/// The plotArea children this rebuild owns removed (plots and axes); the
/// layout element and any dTable/spPr tail stay in `rest`.
function plotAreaRemainder(
  plotAreaInner: string,
  plots: readonly PlotMatch[],
  axes: readonly AxisMatch[],
): { readonly layout: string; readonly rest: string } {
  let rest = plotAreaInner
  for (const plot of plots) rest = rest.replace(plot.whole, '')
  for (const axis of axes) rest = rest.replace(axis.xml, '')
  rest = rest.replace(/<c:(?:catAx|dateAx|valAx|serAx)\/>/g, '')
  const layout = /<c:layout\/>|<c:layout>[\s\S]*?<\/c:layout>/.exec(rest)?.[0] ?? ''
  return { layout, rest: layout === '' ? rest : rest.replace(layout, '') }
}

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
  /<c:(barChart|lineChart|areaChart|pieChart|doughnutChart)\b[^>]*(?<!\/)>([\s\S]*?)(<\/c:\1>)/
const SCATTER_PLOT_PATTERN = /<c:scatterChart\b[^>]*(?<!\/)>[\s\S]*?<\/c:scatterChart>/

/** 只暂换元素QName，编辑后恢复来源前缀；不重序列化来源XML。 */
function chartEditNamespaces(source: string): {xml: string; restore: (xml: string) => string} {
  const chart = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
  const drawing = 'http://schemas.openxmlformats.org/drawingml/2006/main'
  const parser = new SaxesParser({xmlns: true})
  const replacements: Array<{start: number; end: number; text: string}> = []
  const opaque: Array<{token: string; xml: string}> = []
  let marker = '__chartEditOpaque_'
  while (source.includes(marker)) marker += '_'
  let depth = 0, opaqueStart: number | undefined, opaqueDepth = 0, opaqueName: string | undefined
  let chartPrefix = '', drawingPrefix = 'a'
  const rootBindings = new Map<string, string>()
  let drawingSeen = false
  const retain = (start: number, end: number, name?: string) => {
    const token = name ? `<${name} ${marker}${opaque.length}__=""/>` : `${marker}${opaque.length}__`
    replacements.push({start, end, text: token})
    opaque.push({token, xml: source.slice(start, end)})
  }
  parser.on('doctype', () => {throw new ChartEditError('图表编辑不支持DOCTYPE。')})
  parser.on('opentag', node => {
    const start = source.lastIndexOf('<', parser.position - 1)
    if (depth++ === 0) {
      if (node.uri !== chart || node.local !== 'chartSpace') throw new ChartEditError('来源不是OOXML图表部件。')
      chartPrefix = node.prefix
      for (const attr of Object.values(node.attributes)) {
        if (attr.uri === 'http://www.w3.org/2000/xmlns/') rootBindings.set(attr.name === 'xmlns' ? '' : attr.local, attr.value)
      }
      const binding = [...rootBindings].find(([prefix, uri]) => prefix && uri === drawing)
      drawingPrefix = rootBindings.get('a') === drawing ? 'a' : binding?.[0] ?? 'a'
      drawingSeen = binding !== undefined
      while (drawingPrefix === chartPrefix || (rootBindings.has(drawingPrefix) && rootBindings.get(drawingPrefix) !== drawing)) drawingPrefix += '_'
    }
    if (opaqueStart !== undefined) return
    if (node.uri === drawing && !drawingSeen) {
      if (node.prefix && node.prefix !== chartPrefix) drawingPrefix = node.prefix
      drawingSeen = true
    }
    const canonical = node.uri === chart ? 'c' : node.uri === drawing ? 'a' : undefined
    // 扩展保持原始词法；全部同URI元素（含实际编辑目标的别名）参与编辑。
    if (!canonical || (node.uri === chart && node.local === 'extLst')) {
      opaqueStart = start
      opaqueDepth = depth
      opaqueName = canonical ? `${canonical}:${node.local}` : undefined
      return
    }
    replacements.push({start: start + 1, end: start + 1 + node.name.length, text: `${canonical}:${node.local}`})
  })
  parser.on('closetag', node => {
    if (opaqueStart !== undefined) {
      if (depth === opaqueDepth) {retain(opaqueStart, parser.position, opaqueName); opaqueStart = undefined}
    } else if (!node.isSelfClosing) {
      const start = source.lastIndexOf('</', parser.position - 1) + 2
      replacements.push({start, end: start + node.name.length, text: `${node.uri === chart ? 'c' : 'a'}:${node.local}`})
    }
    depth--
  })
  parser.on('comment', () => {
    if (opaqueStart === undefined) retain(source.lastIndexOf('<!--', parser.position), parser.position)
  })
  parser.on('cdata', () => {
    if (opaqueStart === undefined) retain(source.lastIndexOf('<![CDATA[', parser.position), parser.position)
  })
  parser.on('processinginstruction', () => {
    if (opaqueStart === undefined) retain(source.lastIndexOf('<?', parser.position), parser.position)
  })
  try {parser.write(source).close()} catch (error) {
    throw error instanceof ChartEditError ? error : new ChartEditError(`图表命名空间无法解析：${String(error)}`)
  }
  let xml = source
  for (const item of replacements.sort((a, b) => b.start - a.start)) xml = spliceAt(xml, item.start, item.end - item.start, item.text)
  return {xml, restore: edited => {
    if (edited === xml) return source
    // 按当前局部绑定恢复主前缀，避免默认namespace被遮蔽后改变元素URI。
    const output = new SaxesParser({xmlns: false})
    const scopes: Array<Map<string, string>> = [], names: string[] = []
    const patches: Array<{start: number; end: number; text: string}> = []
    output.on('opentag', node => {
      const scope = new Map(scopes.at(-1)), start = edited.lastIndexOf('<', output.position - 1)
      for (const [name, value] of Object.entries(node.attributes)) {
        if (name === 'xmlns') scope.set('', value)
        else if (name.startsWith('xmlns:')) scope.set(name.slice(6), value)
      }
      const opaqueNode = Object.keys(node.attributes).some(name => name.startsWith(marker))
      const canonical = opaqueNode ? undefined : /^([ca]):(.+)$/.exec(node.name)
      let restoredName = node.name
      if (canonical) {
        const uri = canonical[1] === 'c' ? chart : drawing
        const preferred = canonical[1] === 'c' ? chartPrefix : drawingPrefix
        let prefix = scope.get(preferred) === uri ? preferred : [...scope].find(([_prefix, bound]) => bound === uri)?.[0]
        let declaration = ''
        if (prefix === undefined) {
          prefix = preferred || canonical[1]!
          while (scope.has(prefix)) prefix += '_'
          declaration = ` xmlns:${prefix}="${uri}"`
          scope.set(prefix, uri)
        }
        restoredName = `${prefix ? prefix + ':' : ''}${canonical[2]}`
        patches.push({start: start + 1, end: start + 1 + node.name.length, text: restoredName + declaration})
      }
      scopes.push(scope)
      names.push(restoredName)
    })
    output.on('closetag', node => {
      const name = names.pop()!
      scopes.pop()
      if (!node.isSelfClosing && name !== node.name) {
        const start = edited.lastIndexOf('</', output.position - 1) + 2
        patches.push({start, end: start + node.name.length, text: name})
      }
    })
    output.write(edited).close()
    let restored = edited
    for (const patch of patches.sort((a, b) => b.start - a.start)) restored = spliceAt(restored, patch.start, patch.end - patch.start, patch.text)
    for (const item of opaque) {
      restored = restored.replaceAll(item.token, () => item.xml)
    }
    try {new SaxesParser({xmlns: true}).write(restored).close()} catch (error) {
      throw new ChartEditError(`编辑后的图表XML无效：${String(error)}`)
    }
    return restored
  }}
}

export function applyChartEdit(chartXml: string, edit: ChartEditLean): string {
  if (edit.axisTitles !== undefined || edit.gridlines !== undefined || edit.valueAxis !== undefined) {
    const scatter = editScatterAxes(chartXml, edit)
    if (scatter !== undefined) return applyChartEdit(scatter, { ...edit, axisTitles: undefined, gridlines: undefined, valueAxis: undefined })
  }
  const namespaces = chartEditNamespaces(chartXml)
  let xml = namespaces.xml
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
  return namespaces.restore(xml)
}

function spliceAt(xml: string, at: number, length: number, replacement: string): string {
  return xml.slice(0, at) + replacement + xml.slice(at + length)
}

/** Scatter 的两个 valAx 以 plot axId 定位；只替换目标子节点的原始字节。 */
function editScatterAxes(source: string, edit: ChartEditLean): string | undefined {
  const chartUri = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
  const drawingUri = 'http://schemas.openxmlformats.org/drawingml/2006/main'
  type Node = { local: string; uri: string; prefix: string; val?: string | undefined; start: number; end: number; openEnd: number; scope: Map<string, string>; children: Node[] }
  const parser = new SaxesParser({ xmlns: true }), stack: Node[] = [], roots: Node[] = []
  parser.on('doctype', () => { throw new ChartEditError('图表编辑不支持DOCTYPE。') })
  parser.on('opentag', tag => {
    let scope = stack.at(-1)?.scope ?? new Map<string, string>()
    const declarations = Object.values(tag.attributes).filter(attr => attr.uri === 'http://www.w3.org/2000/xmlns/')
    if (declarations.length) {
      scope = new Map(scope)
      for (const attr of declarations) scope.set(attr.name === 'xmlns' ? '' : attr.local, attr.value)
    }
    const start = source.lastIndexOf('<', parser.position - 1)
    const node: Node = { local: tag.local, uri: tag.uri, prefix: tag.prefix, val: Object.values(tag.attributes).find(attr => !attr.uri && attr.local === 'val')?.value,
      start, end: parser.position, openEnd: parser.position, scope, children: [] }
    ;(stack.at(-1)?.children ?? roots).push(node)
    stack.push(node)
  })
  parser.on('closetag', () => {
    const node = stack.pop()!
    node.end = parser.position
  })
  try { parser.write(source).close() } catch (error) {
    throw error instanceof ChartEditError ? error : new ChartEditError(`Scatter axis XML cannot be parsed: ${String(error)}`)
  }
  const children = (node: Node | undefined, name: string) => node?.children.filter(child => child.uri === chartUri && child.local === name) ?? []
  const area = children(children(roots[0], 'chart')[0], 'plotArea')[0]
  const scatter = children(area, 'scatterChart')
  if (!scatter.length) return undefined
  const fail = () => { throw new ChartEditError('Scatter axes require one plot, two unique axId values and reciprocal crossAx identities.') }
  if (scatter.length !== 1 || area!.children.filter(node => node.uri === chartUri && /Chart$/.test(node.local)).length !== 1) fail()
  const id = (node: Node, name: string) => {
    const entries = children(node, name), raw = entries[0]?.val
    const value = raw !== undefined && /^\d+$/.test(raw) ? Number(raw) : NaN
    if (entries.length !== 1 || !Number.isInteger(value) || value < 0 || value > 4294967295) return fail()
    return value
  }
  const ids = children(scatter[0], 'axId').map(node => {
    const value = node.val !== undefined && /^\d+$/.test(node.val) ? Number(node.val) : NaN
    if (!Number.isInteger(value) || value < 0 || value > 4294967295) return fail()
    return value
  })
  if (ids.length !== 2 || ids[0] === ids[1]) fail()
  const axes = area!.children.filter(node => node.uri === chartUri && ['valAx', 'catAx', 'dateAx'].includes(node.local) && ids.includes(id(node, 'axId')))
  const x = axes.find(node => id(node, 'axId') === ids[0]), y = axes.find(node => id(node, 'axId') === ids[1])
  if (axes.length !== 2 || x?.local !== 'valAx' || y?.local !== 'valAx' || id(x, 'crossAx') !== ids[1] || id(y, 'crossAx') !== ids[0]) fail()
  const patches: Array<{ start: number; length: number; text: string; priority: number }> = []
  const qualified = (node: Node, local: string) => {
    const prefix = node.scope.get(node.prefix) === chartUri ? node.prefix : [...node.scope].find(([, uri]) => uri === chartUri)?.[0]
    if (prefix === undefined) return fail()
    return `${prefix ? prefix + ':' : ''}${local}`
  }
  const replaceChild = (parent: Node, name: string, text: string, after: readonly string[]) => {
    const existing = children(parent, name)
    const priority = ['logBase', 'orientation', 'max', 'min', 'axPos', 'majorGridlines', 'minorGridlines', 'title'].indexOf(name)
    if (existing.length > 1) fail()
    if (existing[0]) patches.push({ start: existing[0].start, length: existing[0].end - existing[0].start, text, priority })
    else if (text) {
      const previous = parent.children.filter(node => node.uri === chartUri && after.includes(node.local)).at(-1)
      patches.push({ start: previous?.end ?? parent.openEnd, length: 0, text, priority })
    }
  }
  for (const [node, value] of [[x!, edit.axisTitles?.category], [y!, edit.axisTitles?.value]] as const) {
    if (value === undefined) continue
    let text = ''
    if (value !== null) {
      let prefix = [...node.scope].find(([key, uri]) => key && uri === drawingUri)?.[0] ?? 'a'
      while (node.scope.has(prefix) && node.scope.get(prefix) !== drawingUri) prefix += '_'
      text = builtTitle(escapeXmlText(value)).replace(/(<\/?)c:/g, `$1${node.prefix ? node.prefix + ':' : ''}`).replace(/(<\/?)a:/g, `$1${prefix}:`)
      if (node.scope.get(prefix) !== drawingUri) text = text.replace('>', ` xmlns:${prefix}="${drawingUri}">`)
    }
    replaceChild(node, 'title', text, ['axPos', 'majorGridlines', 'minorGridlines'])
  }
  if (edit.gridlines !== undefined) replaceChild(y!, 'majorGridlines', edit.gridlines ? `<${qualified(y!, 'majorGridlines')}/>` : '', ['axPos'])
  if (edit.valueAxis !== undefined) {
    const scalings = children(y, 'scaling'), scaling = scalings[0]
    if (scalings.length !== 1 || !scaling) throw new ChartEditError('Scatter value axis has no editable scaling element.')
    const open = source.slice(scaling.start, scaling.openEnd)
    if (/\/>$/.test(open)) {
      const bounds = (['max', 'min'] as const).flatMap(bound => {
        const value = edit.valueAxis![bound]
        return value === undefined || value === null ? [] : [`<${qualified(scaling, bound)} val="${value}"/>`]
      }).join('')
      if (bounds) patches.push({ start: scaling.start, length: scaling.end - scaling.start, text: `${open.slice(0, -2)}>${bounds}</${qualified(scaling, 'scaling')}>`, priority: 0 })
    } else for (const bound of ['max', 'min'] as const) {
      const value = edit.valueAxis[bound]
      if (value !== undefined) replaceChild(scaling, bound, value === null ? '' : `<${qualified(scaling, bound)} val="${value}"/>`, bound === 'max' ? ['logBase', 'orientation'] : ['logBase', 'orientation', 'max'])
    }
  }
  let result = source
  // 相邻新元素共享插入点时，逆 schema 顺序应用原字节补丁。
  for (const patch of patches.sort((a, b) => b.start - a.start || b.priority - a.priority)) result = spliceAt(result, patch.start, patch.length, patch.text)
  return result
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
  const plots = matchPlots(chartXml)
  const plotMatch = plots[0]
  if (!plotMatch) {
    throw new ChartEditError('This chart type does not support series replacement.')
  }
  if (plots.length > 1 || entries.some((entry) => entry.plot !== undefined)) {
    return replaceComboSeries(chartXml, plots, entries)
  }
  const plot = plotMatch.family
  if (!REPLACEABLE_PLOTS.includes(plot)) {
    throw new ChartEditError(`Replacing series on a ${plot} is not supported.`)
  }
  const inner = plotMatch.inner
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
    inner.slice(0, firstSer) +
    built +
    inner.slice(firstSer).replace(/<c:ser>[\s\S]*?<\/c:ser>/g, '')
  return (
    chartXml.slice(0, plotMatch.index) +
    `<c:${plot}>${nextInner}</c:${plot}>` +
    chartXml.slice(plotMatch.index + plotMatch.whole.length)
  )
}

/// Combo series replacement: series are grouped by their tagged family and
/// axis set into <c:barChart>/<c:lineChart> elements (c:idx/order stay
/// global in the dialog's row order), the primary axis pair survives
/// verbatim, and the secondary pair is kept, synthesized, or dropped to
/// match the tags.
function replaceComboSeries(
  chartXml: string,
  plots: readonly PlotMatch[],
  entries: readonly ChartSeriesSetEntry[],
): string {
  for (const plot of plots) {
    if (plot.family !== 'barChart' && plot.family !== 'lineChart') {
      throw new ChartEditError('Only bar + line combos support series replacement.')
    }
  }
  const plotAreaMatch = /<c:plotArea>([\s\S]*?)<\/c:plotArea>/.exec(chartXml)
  if (!plotAreaMatch || plotAreaMatch[1] === undefined) {
    throw new ChartEditError('Chart part has no plot area.')
  }
  const plotAreaInner = plotAreaMatch[1]
  // A series axis (3D charts) references its own scale; this rebuild cannot
  // re-point it, so fail closed rather than orphan it.
  if (/<c:serAx[>/]/.test(plotAreaInner)) {
    throw new ChartEditError('This chart has series axes this edit cannot rebuild.')
  }
  const axes = matchAxes(plotAreaInner)
  const { primaryCat, primaryVal, secondaryVal, secondaryCat, leftovers } = classifyAxes(axes)
  if (!primaryCat || !primaryVal || primaryCat.id === undefined || primaryVal.id === undefined) {
    throw new ChartEditError('Combo chart is missing its primary axes.')
  }
  if (leftovers.length > 0) {
    throw new ChartEditError('This chart has more axes than this edit can rebuild.')
  }
  // Untagged entries default to the first group's family.
  const defaultFamily: 'barChart' | 'lineChart' =
    plots[0]?.family === 'lineChart' ? 'lineChart' : 'barChart'
  const wantsSecondary = entries.some((entry) => entry.secondaryAxis === true)
  let secondaryValId: string | undefined
  let secondaryCatId: string | undefined
  let secondaryValXml = ''
  let secondaryCatXml = ''
  if (wantsSecondary) {
    if (
      secondaryVal &&
      secondaryCat &&
      secondaryVal.id !== undefined &&
      secondaryCat.id !== undefined
    ) {
      secondaryValId = secondaryVal.id
      secondaryCatId = secondaryCat.id
      secondaryValXml = secondaryVal.xml
      secondaryCatXml = secondaryCat.xml
    } else {
      ;[secondaryCatId, secondaryValId] = nextAxisIds(plotAreaInner, 2) as [string, string]
      secondaryCatXml = hiddenCatAxisXml(secondaryCatId, secondaryValId)
      secondaryValXml = rightValAxisXml(secondaryValId, secondaryCatId)
    }
  }
  // Group order: primary groups before secondary, bars before lines.
  const groupKeys: { family: 'barChart' | 'lineChart'; secondary: boolean }[] = []
  for (const secondary of [false, true]) {
    for (const family of ['barChart', 'lineChart'] as const) {
      if (
        entries.some(
          (entry) =>
            (entry.plot ?? defaultFamily) === family &&
            (entry.secondaryAxis === true) === secondary,
        )
      ) {
        groupKeys.push({ family, secondary })
      }
    }
  }
  // Per-family plot settings (grouping, gap width, labels) carry over from
  // the last existing group of that family.
  const familyInner = (family: string): string => {
    let inner = ''
    for (const plot of plots) if (plot.family === family) inner = plot.inner
    return inner
  }
  const builtGroups = groupKeys
    .map((group) => {
      const sers = entries
        .map((entry, index) => ({ entry, index }))
        .filter(
          ({ entry }) =>
            (entry.plot ?? defaultFamily) === group.family &&
            (entry.secondaryAxis === true) === group.secondary,
        )
        .map(({ entry, index }) => buildSeriesReplacement(entry, index))
        .join('')
      const inner = familyInner(group.family)
      const labels = /<\/c:ser>(<c:dLbls>[\s\S]*?<\/c:dLbls>)/.exec(inner)?.[1] ?? ''
      const grouping =
        /<c:grouping val="([^"]*)"\/>/.exec(inner)?.[1] ??
        (group.family === 'barChart' ? 'clustered' : 'standard')
      const catId = group.secondary ? secondaryCatId : primaryCat.id
      const valId = group.secondary ? secondaryValId : primaryVal.id
      if (group.family === 'barChart') {
        const barDir = /<c:barDir val="([^"]*)"\/>/.exec(inner)?.[1] ?? 'col'
        const gapWidth = /<c:gapWidth val="[^"]*"\/>/.exec(inner)?.[0] ?? ''
        const overlap = /<c:overlap val="[^"]*"\/>/.exec(inner)?.[0] ?? ''
        return (
          `<c:barChart><c:barDir val="${barDir}"/><c:grouping val="${grouping}"/>` +
          `<c:varyColors val="0"/>${sers}${labels}${gapWidth}${overlap}` +
          `<c:axId val="${catId}"/><c:axId val="${valId}"/></c:barChart>`
        )
      }
      const marker = /<c:marker val="[^"]*"\/>/.exec(inner)?.[0] ?? '<c:marker val="1"/>'
      return (
        `<c:lineChart><c:grouping val="${grouping}"/><c:varyColors val="0"/>` +
        `${sers}${labels}${marker}<c:axId val="${catId}"/><c:axId val="${valId}"/></c:lineChart>`
      )
    })
    .join('')
  const { layout, rest } = plotAreaRemainder(plotAreaInner, plots, axes)
  const axesXml =
    primaryCat.xml + primaryVal.xml + (wantsSecondary ? `${secondaryValXml}${secondaryCatXml}` : '')
  return (
    chartXml.slice(0, plotAreaMatch.index) +
    `<c:plotArea>${layout}${builtGroups}${axesXml}${rest}</c:plotArea>` +
    chartXml.slice(plotAreaMatch.index + plotAreaMatch[0].length)
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
  const parser = new SaxesParser({fragment:true})
  let depth = 0, current: {start:number;end:number;open:string} | undefined
  let found: {start:number;length:number;open:string;body:string} | undefined
  parser.on('opentag',tag=>{
    if (depth++ === 0 && tag.name === 'c:dLbls' && !found) {
      const start = inner.lastIndexOf('<',parser.position-1)
      current = {start,end:parser.position,open:inner.slice(start,parser.position)}
    }
  })
  parser.on('closetag',tag=>{
    if (--depth === 0 && current) {
      found = {start:current.start,length:parser.position-current.start,open:current.open.replace(/\/>$/,'>'),
        body:tag.isSelfClosing ? '' : inner.slice(current.end,inner.lastIndexOf('</',parser.position-1))}
      current = undefined
    }
  })
  parser.write(inner).close()
  return found
}

/// Plot-level data labels: what every slice/bar/point shows. 'none' removes
/// the plot-level element (per-series overrides, if any, keep their own).
function setDataLabels(
  chartXml: string,
  mode: NonNullable<ChartEditLean['dataLabels']>,
): string {
  const scatterMatch = chartXml.match(SCATTER_PLOT_PATTERN)
  if (scatterMatch) {
    if (mode !== 'none' && mode !== 'value') {
      throw new ChartEditError('Scatter charts support only value data labels.')
    }
    const openEnd = scatterMatch[0].indexOf('>') + 1
    const inner = scatterMatch[0].slice(openEnd, -'</c:scatterChart>'.length)
    if (mode === 'none') {
      const modes = scatterLabelModes(inner)
      if (modes.unsupported) throw new ChartEditError('Scatter data labels cannot be safely read.')
      if (modes.firstSeriesMode === 'value') throw new ChartEditError('Scatter first-series value labels would remain visible; preserve source series labels.')
    }
    const existing = plotLabelBlock(inner)
    let next = existing ? spliceAt(inner,existing.start,existing.length,'') : inner
    if (mode === 'value') {
      const body = setLabelChildren(existing?.body ?? '', {
        delete:'',showLegendKey:'<c:showLegendKey val="0"/>',showVal:'<c:showVal val="1"/>',
        showCatName:'<c:showCatName val="0"/>',showSerName:'<c:showSerName val="0"/>',
        showPercent:'<c:showPercent val="0"/>',showBubbleSize:'<c:showBubbleSize val="0"/>',
      })
      const labels = (existing?.open ?? '<c:dLbls>')+body+'</c:dLbls>'
      if (existing) next = spliceAt(inner,existing.start,existing.length,labels)
      else {
        const lastSeriesEnd = next.lastIndexOf('</c:ser>')
        if (lastSeriesEnd === -1) throw new ChartEditError('This chart has no series to label.')
        const insertAt = lastSeriesEnd + '</c:ser>'.length
        next = next.slice(0,insertAt)+labels+next.slice(insertAt)
      }
    }
    return chartXml.replace(SCATTER_PLOT_PATTERN,full=>
      `${full.slice(0,openEnd)}${next}</c:scatterChart>`,
    )
  }
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
    (full, _plot: string, _inner: string, close: string) => `${full.slice(0, full.indexOf('>') + 1)}${next}${close}`,
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
  return chartXml.replace(LABELABLE_PLOT_PATTERN, (full, _plot: string, _i: string, close: string) =>
    `${full.slice(0, full.indexOf('>') + 1)}${next}${close}`,
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
  const titleElement = scope.match(/<c:title\b[^>]*(?<!\/)>[\s\S]*?<\/c:title>/)
  if (titleElement) {
    let isFirstRun = true
    const rewritten = titleElement[0].replace(
      /(<a:t\b[^>]*(?<!\/)>)[\s\S]*?(<\/a:t>)|<a:t\b[^>]*\/>/g,
      (full, open: string | undefined, close: string | undefined) => {
        const text = isFirstRun ? escaped : ''
        isFirstRun = false
        return `${open ?? full.replace(/\/>$/, '>')}${text}${close ?? '</a:t>'}`
      },
    )
    if (isFirstRun) {
      // A title without any text run (e.g. formula-linked): replace whole tx.
      const opening = titleElement[0].slice(0, titleElement[0].indexOf('>') + 1)
      return xml.replace(titleElement[0], () => builtTitle(escaped).replace('<c:title>', () => opening))
    }
    return xml.replace(titleElement[0], () => rewritten)
  }
  const chartOpen = xml.match(/<c:chart\b[^>]*(?<!\/)>/)
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
  const plots = matchPlots(chartXml)
  const plotMatch = plots[0]
  if (!plotMatch) {
    throw new ChartEditError('This chart type cannot be converted.')
  }
  const combo = plots.length > 1
  if (combo) {
    for (const plot of plots) {
      if (plot.family !== 'barChart' && plot.family !== 'lineChart' && plot.family !== 'areaChart') {
        throw new ChartEditError('Only bar, line, and area combos can be converted.')
      }
    }
  }
  const current = plotMatch.family
  if (!combo && !(CONVERTIBLE_PLOTS as readonly string[]).includes(current)) {
    throw new ChartEditError(`Converting a ${current} is not supported.`)
  }
  const inner = combo ? plots.map((plot) => plot.inner).join('') : plotMatch.inner
  const targetElement = TARGET_PLOTS[target]
  const currentIsPie = !combo && (current === 'pieChart' || current === 'doughnutChart')
  const targetIsPie = targetElement === 'pieChart' || targetElement === 'doughnutChart'

  if (!combo && current === 'barChart' && targetElement === 'barChart') {
    const direction = target === 'column' ? 'col' : 'bar'
    return chartXml.replace(/<c:barDir val="[^"]*"\/>/, () => `<c:barDir val="${direction}"/>`)
  }
  if (!combo && targetElement === current) return chartXml

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
    const replacement = `<c:${targetElement}>${parts.join('')}</c:${targetElement}>`
    let plotReplaced = chartXml
    for (const plot of [...plots].sort((a, b) => b.index - a.index)) {
      plotReplaced =
        plotReplaced.slice(0, plot.index) + plotReplaced.slice(plot.index + plot.whole.length)
    }
    const firstPlot = Math.min(...plots.map((plot) => plot.index))
    plotReplaced = plotReplaced.slice(0, firstPlot) + replacement + plotReplaced.slice(firstPlot)
    return plotReplaced.replace(
      /<c:(catAx|valAx|dateAx|serAx)>[\s\S]*?<\/c:\1>|<c:(?:catAx|valAx|dateAx|serAx)\/>/g,
      '',
    )
  }
  if (!currentIsPie && !combo) {
    const axisIds = [...inner.matchAll(/<c:axId val="[0-9]+"\/>/g)].map((match) => match[0])
    if (axisIds.length === 0) {
      throw new ChartEditError('This chart has no axes to convert.')
    }
    parts.push(...axisIds)
    return chartXml.replace(
      plotMatch.whole,
      () => `<c:${targetElement}>${parts.join('')}</c:${targetElement}>`,
    )
  }
  if (combo) {
    const plotAreaMatch = /<c:plotArea>([\s\S]*?)<\/c:plotArea>/.exec(chartXml)
    if (!plotAreaMatch || plotAreaMatch[1] === undefined) {
      throw new ChartEditError('Chart part has no plot area.')
    }
    if (/<c:serAx[>/]/.test(plotAreaMatch[1])) {
      throw new ChartEditError('This combo has series axes this conversion cannot keep.')
    }
    const axes = matchAxes(plotAreaMatch[1])
    const { primaryCat, primaryVal, leftovers } = classifyAxes(axes)
    if (
      !primaryCat ||
      !primaryVal ||
      primaryCat.id === undefined ||
      primaryVal.id === undefined ||
      leftovers.length > 0
    ) {
      throw new ChartEditError('This combo has axes this conversion cannot keep.')
    }
    parts.push(`<c:axId val="${primaryCat.id}"/>`, `<c:axId val="${primaryVal.id}"/>`)
    const { layout, rest } = plotAreaRemainder(plotAreaMatch[1], plots, axes)
    const keptAxes =
      primaryCat.xml.replace(/<c:crossAx val="[0-9]+"\/>/, `<c:crossAx val="${primaryVal.id}"/>`) +
      primaryVal.xml.replace(/<c:crossAx val="[0-9]+"\/>/, `<c:crossAx val="${primaryCat.id}"/>`)
    return (
      chartXml.slice(0, plotAreaMatch.index) +
      `<c:plotArea>${layout}<c:${targetElement}>${parts.join('')}</c:${targetElement}>` +
      `${keptAxes}${rest}</c:plotArea>` +
      chartXml.slice(plotAreaMatch.index + plotAreaMatch[0].length)
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
    plotMatch.whole,
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
  const result = chartXml.replace(/<c:ser\b[^>]*(?<!\/)>[\s\S]*?<\/c:ser>/g, (serXml) => {
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
