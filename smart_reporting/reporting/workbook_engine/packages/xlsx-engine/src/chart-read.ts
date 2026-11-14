/// Chart read-back (图表网格渲染 v1): parses the worksheet's drawing part for
/// chart anchors and each chart part for type/title/series references. Values
/// are NOT cached here — the render extension resolves the references against
/// the live grid, so edits flow into the picture on the next paint.

import { createBufferEntrySource } from './zip'
import { chartThemePalette } from './chart-label-theme'
import { chartLabelColor } from './chart-label-color'
import { decodeXmlText, escapeXmlAttribute, escapeXmlText } from './xml'
import { SaxesParser } from 'saxes'
import { applyDrawingLuminance, themeSlotIndex } from './style-color'
import type { ChartEditLean } from './chart-edit'

/** 只读解析按命名空间URI统一内部标记；不重写ZIP中的来源XML。 */
function chartReadTokens(xml: string): string {
  const prefixes: Record<string, string> = {
    'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing': 'xdr',
    'http://schemas.openxmlformats.org/drawingml/2006/chart': 'c',
    'http://schemas.openxmlformats.org/drawingml/2006/main': 'a',
    'http://schemas.openxmlformats.org/officeDocument/2006/relationships': 'r',
    'http://schemas.openxmlformats.org/package/2006/relationships': '',
  }
  const name = (uri: string, local: string) => {
    const prefix = prefixes[uri] ?? (uri ? 'foreign' : '')
    return prefix ? `${prefix}:${local}` : local
  }
  const parser = new SaxesParser({ xmlns: true }), parts: string[] = []
  parser.on('doctype', () => { throw new Error('图表来源不支持DOCTYPE') })
  parser.on('opentag', tag => {
    const attrs = Object.values(tag.attributes).filter(attr => attr.uri !== 'http://www.w3.org/2000/xmlns/')
      .map(attr => ` ${name(attr.uri, attr.local)}="${escapeXmlAttribute(attr.value)}"`).join('')
    parts.push(`<${name(tag.uri, tag.local)}${attrs}>`)
  })
  parser.on('closetag', tag => { parts.push(`</${name(tag.uri, tag.local)}>` ) })
  parser.on('text', text => { parts.push(escapeXmlText(text)) })
  parser.on('cdata', text => { parts.push(escapeXmlText(text)) })
  try { parser.write(xml).close() } catch { return '' } // 无法读取的图表不阻断工作表展示。
  return parts.join('')
}

export type ChartReadKind =
  | 'column'
  | 'bar'
  | 'line'
  | 'area'
  | 'pie'
  | 'doughnut'
  | 'combo'
  | 'scatter'
  | 'radar'

export interface ChartReadDataLabel {
  readonly style?: {readonly sizePt?: number; readonly bold?: boolean; readonly color?: string} | undefined
  readonly showValue?: boolean | undefined
  readonly showCategory?: boolean | undefined
  readonly showPercent?: boolean | undefined
  readonly deleted?: boolean | undefined
  readonly position?: 'center' | 'inside-end' | 'outside-end' | undefined
  readonly numberFormat?: string | undefined
  readonly unsupported?: true | undefined
}
export interface ChartReadDataLabels extends ChartReadDataLabel {
  readonly points?: Readonly<Record<number, ChartReadDataLabel>> | undefined
}

export interface ChartReadSeries {
  readonly plot?: 'barChart' | 'lineChart' | undefined
  readonly secondaryAxis?: boolean | undefined
  readonly index?: number | undefined
  /// series name reference (c:tx strRef) or literal
  readonly name?: string | undefined
  readonly nameRef?: string | undefined
  readonly nameCache?: string | undefined
  /// Explicit series fill only; point fills and line colors are separate.
  readonly color?: string | undefined
  readonly lineColor?: string | undefined
  readonly lineColorUnavailable?: true | undefined
  readonly lineWidth?: number | undefined
  readonly marker?: string | undefined
  readonly dataLabels?: ChartReadDataLabels | undefined
  readonly numberFormat?: string | undefined
  readonly pointColors?: Readonly<Record<number, string>> | undefined
  readonly explosionPct?: number | undefined
  readonly pointExplosions?: Readonly<Record<number, number>> | undefined
  readonly colorPreviewUnavailable?: true | undefined
  readonly categoriesRef?: string | undefined
  /// Preserve single-level category point indices. Empty means an unreadable
  /// source category block; absent means there was no category block.
  readonly categories?: ReadonlyArray<string | null> | undefined
  /// First outer multiLvlStrCache level; spans index the leaf categories.
  readonly categoryGroups?: ReadonlyArray<{ readonly label: string; readonly start: number; readonly end: number }> | undefined
  readonly categoryNumberFormat?: string | undefined
  readonly valuesRef: string
  /// Select Data 行列切换写出的 numLit；不伪造网格引用。
  readonly values?: ReadonlyArray<number> | undefined
  /// scatter only: X values reference (c:xVal numRef), absent for ordinal X
  readonly xValuesRef?: string | undefined
  /// scatter only: literal X values when the writer emitted c:numLit ordinals
  readonly xValues?: ReadonlyArray<number> | undefined
}

export interface ChartReadAxis {
  readonly id: number
  readonly hidden: boolean
  readonly reversed?: boolean | undefined
  readonly position?: 'left' | 'right' | 'top' | 'bottom' | undefined
  readonly title?: string | undefined
  readonly titleRef?: string | undefined
  readonly titleCache?: string | undefined
  readonly numberFormat?: string | undefined
  readonly majorGridlines?: boolean | undefined
  readonly displayUnit?: number | undefined
  readonly displayUnitLabel?: string | undefined
  readonly scaling?: {
    readonly min?: number | undefined
    readonly max?: number | undefined
    readonly majorUnit?: number | undefined
    readonly reversed: boolean
    readonly unsupported?: 'invalid' | 'logarithmic' | undefined
  } | undefined
}

/** 对应现有编辑器的首个写入目标；无法用简化控件表示的状态不伪造默认值。 */
export type ChartReadDesign = Pick<ChartEditLean, 'axisTitles' | 'dataLabels' | 'grouping' | 'gridlines'> & {
  readonly legend?: NonNullable<ChartEditLean['legend']> | 'top-right' | undefined
}

export interface ChartReadSpec {
  readonly chartPath: string
  readonly anchorKind?: 'twoCellAnchor' | 'oneCellAnchor' | 'absoluteAnchor' | undefined
  readonly anchor: {
    readonly fromRow: number
    readonly fromColumn: number
    readonly toRow: number
    readonly toColumn: number
    /** 来源标记内的EMU偏移；未指定为0，9525 EMU = 1 CSS px。 */
    readonly fromRowOffset?: number | undefined
    readonly fromColumnOffset?: number | undefined
    readonly toRowOffset?: number | undefined
    readonly toColumnOffset?: number | undefined
  }
  readonly kind: ChartReadKind
  readonly design?: ChartReadDesign | undefined
  readonly palette?: readonly string[] | undefined
  readonly varyColors?: boolean | undefined
  readonly gapWidthPct?: number | undefined
  readonly holeSizePct?: number | undefined
  readonly title?: string | undefined
  readonly dataLabels?: ChartReadDataLabels | undefined
  readonly scatterStyle?: string | undefined
  readonly axes?: { readonly category: ChartReadAxis; readonly value: ChartReadAxis } | undefined
  readonly secondaryAxes?: { readonly category: ChartReadAxis; readonly value: ChartReadAxis } | undefined
  readonly valueScaleUnavailable?: true | undefined
  readonly legend?: {
    readonly position: 'right' | 'left' | 'top' | 'bottom' | 'top-right'
    readonly overlay: boolean
    readonly hiddenEntries: readonly number[]
  } | undefined
  readonly series: ReadonlyArray<ChartReadSeries>
}

const relsPathOf = (partPath: string): string => {
  const slash = partPath.lastIndexOf('/')
  return `${partPath.slice(0, slash)}/_rels/${partPath.slice(slash + 1)}.rels`
}

async function drawingPathOf(
  source: Awaited<ReturnType<typeof createBufferEntrySource>>,
  worksheetPath: string,
): Promise<string | null> {
  const relsPath = relsPathOf(worksheetPath)
  if (!(await source.has(relsPath))) return null
  const relsXml = chartReadTokens(await source.readText(relsPath))
  for (const match of relsXml.matchAll(/<Relationship\b([^>]*?)\/?>/g)) {
    const attributes = match[1] ?? ''
    const type = attributes.match(/\bType="([^"]*)"/)?.[1] ?? ''
    if (!type.endsWith('/drawing')) continue
    const target = attributes.match(/\bTarget="([^"]*)"/)?.[1]
    if (target === undefined) continue
    // targets are relative to xl/worksheets/ — normalize ../drawings/x.xml
    const resolved = new URL(target, 'http://pkg/xl/worksheets/').pathname.replace(/^\//, '')
    return (await source.has(resolved)) ? resolved : null
  }
  return null
}

const anchorOf = (block: string, kind: string): ChartReadSpec['anchor'] | null => {
  const from = block.match(/<xdr:from>[\s\S]*?<\/xdr:from>/)?.[0] ?? ''
  const to = block.match(/<xdr:to>[\s\S]*?<\/xdr:to>/)?.[0] ?? ''
  const num = (xml: string, tag: string): number =>
    Number(xml.match(new RegExp(`<xdr:${tag}>(-?[0-9]+)</xdr:${tag}>`))?.[1] ?? 0)
  const fromRowOffset = num(from, 'rowOff'), fromColumnOffset = num(from, 'colOff')
  const toRowOffset = num(to, 'rowOff'), toColumnOffset = num(to, 'colOff')
  if (kind !== 'twoCellAnchor') {
    const integer = (value: string | undefined): number =>
      value !== undefined && /^-?\d+$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : NaN
    const attribute = (xml: string, name: string) => integer(xml.match(new RegExp(`\\b${name}="([^"]*)"`))?.[1])
    const extent = block.match(/<xdr:ext\b[^>]*>/)?.[0] ?? ''
    const width = attribute(extent, 'cx'), height = attribute(extent, 'cy')
    if (!(width > 0 && height > 0)) return null
    const absolute = kind === 'absoluteAnchor'
    const position = block.match(/<xdr:pos\b[^>]*>/)?.[0] ?? ''
    const row = absolute ? 0 : integer(from.match(/<xdr:row>([^<]*)<\/xdr:row>/)?.[1])
    const column = absolute ? 0 : integer(from.match(/<xdr:col>([^<]*)<\/xdr:col>/)?.[1])
    const x = absolute ? attribute(position, 'x') : fromColumnOffset
    const y = absolute ? attribute(position, 'y') : fromRowOffset
    if (row < 0 || row > 1048575 || column < 0 || column > 16383 ||
        ![row, column, x, y, x + width, y + height].every(Number.isSafeInteger)) return null
    // 同一基准单元格加EMU终点，复用现有渲染；不猜测列宽、行高或重写来源锚点。
    return { fromRow: row, fromColumn: column, toRow: row, toColumn: column,
      fromColumnOffset: x, fromRowOffset: y, toColumnOffset: x + width, toRowOffset: y + height }
  }
  return {
    fromRow: num(from, 'row'),
    fromColumn: num(from, 'col'),
    toRow: num(to, 'row'),
    toColumn: num(to, 'col'),
    ...(fromRowOffset ? { fromRowOffset } : {}),
    ...(fromColumnOffset ? { fromColumnOffset } : {}),
    ...(toRowOffset ? { toRowOffset } : {}),
    ...(toColumnOffset ? { toColumnOffset } : {}),
  }
}

function chartKindOf(chartXml: string): ChartReadKind | null {
  if (/<c:pieChart\b/.test(chartXml)) return 'pie'
  if (/<c:doughnutChart\b/.test(chartXml)) return 'doughnut'
  const hasBar = /<c:barChart\b/.test(chartXml)
  const hasLine = /<c:lineChart\b/.test(chartXml)
  if (hasBar && hasLine) return 'combo' // bar+line dual plot (write-side combo)
  // 全部系列改成同族后，次轴组仍是独立plot，不能在重新打开时丢失轴绑定。
  if ((hasBar || hasLine) && secondaryValueAxisIds(chartXml).size > 0) return 'combo'
  if (/<c:areaChart\b/.test(chartXml)) return 'area'
  if (/<c:scatterChart\b/.test(chartXml)) return 'scatter'
  if (/<c:radarChart\b/.test(chartXml)) return 'radar'
  const bar = chartXml.match(/<c:barChart\b[\s\S]*?<c:barDir val="(col|bar)"/)
  if (bar) return bar[1] === 'bar' ? 'bar' : 'column'
  if (hasLine) return 'line'
  return null
}

function titleText(xml: string): Pick<ChartReadAxis, 'title' | 'titleRef' | 'titleCache'> {
  const title = xml.match(/<c:title\b[^>]*>([\s\S]*?)<\/c:title>/)?.[1]
  const tx = title?.match(/<c:tx\b[^>]*>([\s\S]*?)<\/c:tx>/)?.[1]
  if (!tx) return {}
  const reference = tx.match(/<c:f>([\s\S]*?)<\/c:f>/)?.[1]
  if (reference !== undefined) {
    const cache = tx.match(/<c:strCache\b[^>]*>[\s\S]*?<c:pt\b[^>]*\bidx="0"[^>]*>[\s\S]*?<c:v>([\s\S]*?)<\/c:v>/)?.[1]
    return { titleRef: decodeXmlText(reference), ...(cache !== undefined ? { titleCache: decodeXmlText(cache) } : {}) }
  }
  const paragraphs = [...tx.matchAll(/<a:p\b[^>]*>([\s\S]*?)<\/a:p>/g)]
  const text = paragraphs.map(paragraph => [...paragraph[1]!.matchAll(/<a:t\b[^>]*>([\s\S]*?)<\/a:t>/g)]
    .map(run => decodeXmlText(run[1] ?? '')).join('')).join('\n')
  return text ? { title: text } : {}
}

const titleOf = (xml: string): string | undefined => {
  // Axis titles live after plotArea begins and must never become chart titles.
  const text = titleText(xml.split(/<c:plotArea\b/)[0] ?? '')
  return text.title ?? text.titleCache
}

function valueScaling(body: string): ChartReadAxis['scaling'] {
  const block = body.match(/<c:scaling\b[^>]*>([\s\S]*?)<\/c:scaling>/)?.[1]
  let invalid = false
  const number = (tag: string, xml = block ?? ''): number | undefined => {
    const element = xml.match(new RegExp(`<c:${tag}\\b([^>]*)`))
    if (!element) return undefined
    const raw = element[1]!.match(/\bval="([^"]*)"/)?.[1]?.trim() ?? ''
    const value = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(raw) ? Number(raw) : NaN
    if (!Number.isFinite(value)) { invalid = true; return undefined }
    return value
  }
  const min = number('min'), max = number('max'), logBase = number('logBase')
  const majorUnit = number('majorUnit', body)
  if (majorUnit !== undefined && !(majorUnit > 0)) invalid = true
  const orientation = block?.match(/<c:orientation\b[^>]*\bval="([^"]*)"/)?.[1] ?? 'minMax'
  if (!['minMax', 'maxMin'].includes(orientation) || min !== undefined && max !== undefined && min >= max) invalid = true
  if (logBase !== undefined && (logBase < 2 || logBase > 1000)) invalid = true
  const unsupported = invalid ? 'invalid' : logBase !== undefined ? 'logarithmic' : undefined
  if (min === undefined && max === undefined && majorUnit === undefined && orientation === 'minMax' && !unsupported) return undefined
  return { reversed: orientation === 'maxMin', ...(min !== undefined ? {min} : {}), ...(max !== undefined ? {max} : {}),
    ...(majorUnit !== undefined ? {majorUnit} : {}), ...(unsupported ? {unsupported} : {}) }
}

function scatterAxisDetails(body: string): Pick<ChartReadAxis, 'majorGridlines' | 'displayUnit' | 'displayUnitLabel'> {
  const builtins: Record<string, readonly [number, string]> = {
    hundreds: [1e2, 'Hundreds'], thousands: [1e3, 'Thousands'], tenThousands: [1e4, 'x 10000'],
    hundredThousands: [1e5, 'x 100000'], millions: [1e6, 'Millions'], tenMillions: [1e7, 'x 10000000'],
    hundredMillions: [1e8, 'x 100000000'], billions: [1e9, 'Billions'], trillions: [1e12, 'Trillions'],
  }
  const parser = new SaxesParser({ xmlns: false }), stack: string[] = []
  let majorGridlines = false, builtin: readonly [number, string] | undefined, custom: number | undefined
  let hasLabel = false, label = ''
  parser.on('opentag', node => {
    const parent = stack.join('/')
    if (parent === 'axis' && node.name === 'c:majorGridlines') majorGridlines = true
    if (parent === 'axis/c:dispUnits') {
      if (node.name === 'c:builtInUnit') builtin = builtins[String(node.attributes.val)]
      if (node.name === 'c:custUnit') {
        const raw = String(node.attributes.val ?? '').trim()
        const value = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(raw) ? Number(raw) : NaN
        if (Number.isFinite(value) && value > 0) custom = value
      }
      if (node.name === 'c:dispUnitsLbl') hasLabel = true
    }
    stack.push(node.name)
  })
  parser.on('closetag', () => { stack.pop() })
  parser.on('text', text => {
    if (stack.slice(0, 3).join('/') === 'axis/c:dispUnits/c:dispUnitsLbl' && stack.at(-1) === 'a:t') label += text
  })
  parser.write(`<axis>${body}</axis>`).close()
  const displayUnit = builtin?.[0] ?? custom
  const displayUnitLabel = hasLabel && displayUnit !== undefined ? label || builtin?.[1] : undefined
  return { majorGridlines, ...(displayUnit !== undefined ? { displayUnit } : {}), ...(displayUnitLabel ? { displayUnitLabel } : {}) }
}

function axesOf(xml: string, kind: ChartReadKind, secondary = false): ChartReadSpec['axes'] {
  if (!['column','bar','combo','line','area','scatter'].includes(kind)) return undefined
  const plots = [...xml.matchAll(/<c:(?:barChart|lineChart|areaChart|scatterChart)\b[^>]*>([\s\S]*?)<\/c:(?:barChart|lineChart|areaChart|scatterChart)>/g)]
  if (kind !== 'combo' && (plots.length !== 1 || secondary)) return undefined
  const unsigned = (raw: string | undefined): number | undefined => {
    const value = raw === undefined ? NaN : Number(raw)
    return Number.isInteger(value) && value >= 0 && value <= 4294967295 ? value : undefined
  }
  const idOf = (body: string, tag: string) => {
    if (kind !== 'scatter') return unsigned(body.match(new RegExp(`<c:${tag}\\b[^>]*\\bval="(\\d+)"`))?.[1])
    const elements = [...body.matchAll(new RegExp(`<c:${tag}\\b[^>]*`, 'g'))]
    return elements.length === 1 ? unsigned(elements[0]![0].match(/\bval="(\d+)"/)?.[1]) : undefined
  }
  const rightIds = secondaryValueAxisIds(xml)
  const selected = kind === 'combo' ? plots.find(plot => [...plot[1]!.matchAll(/<c:axId\b[^>]*\bval="(\d+)"/g)].some(id => rightIds.has(id[1]!)) === secondary) : plots[0]
  if (!selected) return undefined
  const ids = [...selected[1]!.matchAll(/<c:axId\b[^>]*\bval="(\d+)"/g)].map(match => unsigned(match[1]))
  if (ids.length !== 2 || ids.some(id => id === undefined) || new Set(ids).size !== 2) return undefined
  const axes = [...xml.matchAll(/<c:(catAx|dateAx|valAx)\b[^>]*>([\s\S]*?)<\/c:\1>/g)]
    .map(match => ({ kind: match[1]!, body: match[2]!, id: idOf(match[2]!, 'axId') }))
    .filter(axis => axis.id !== undefined && ids.includes(axis.id))
  if (axes.length !== 2 || new Set(axes.map(axis => axis.id)).size !== 2) return undefined
  const category = kind === 'scatter'
    ? axes.find(axis => axis.kind === 'valAx' && axis.id === ids[0])
    : axes.find(axis => axis.kind === 'catAx' || axis.kind === 'dateAx')
  const value = kind === 'scatter'
    ? axes.find(axis => axis.kind === 'valAx' && axis.id === ids[1])
    : axes.find(axis => axis.kind === 'valAx')
  if (!category || !value || idOf(category.body, 'crossAx') !== value.id || idOf(value.body, 'crossAx') !== category.id) return undefined
  const project = (axis: NonNullable<typeof category>): ChartReadAxis => {
    const prefix = axis.body.split(/<c:title\b/)[0] ?? ''
    const deletion = prefix.match(/<c:delete\b([^>]*)/)
    const hidden = !!deletion && !/\bval="(?:0|false)"/.test(deletion[1]!)
    const raw = prefix.match(/<c:axPos\b[^>]*\bval="([^"]*)"/)?.[1] ?? ''
    const positions = { l: 'left', r: 'right', t: 'top', b: 'bottom' } as const
    const scaling = axis.kind === 'valAx' ? valueScaling(axis.body) : undefined
    const format = axis.body.match(/<c:numFmt\b[^>]*\bformatCode="([^"]*)"/)?.[1]
    const reversed = axis.kind !== 'valAx' && /<c:orientation\b[^>]*\bval="maxMin"/.test(axis.body.match(/<c:scaling\b[^>]*>([\s\S]*?)<\/c:scaling>/)?.[1] ?? '')
    const title = { ...titleText(axis.body) }
    if (kind === 'scatter' && !title.title && !title.titleRef && !title.titleCache && /<c:title\b/.test(axis.body)) title.title = 'Axis Title'
    return { id: axis.id!, hidden, ...title, ...(scaling ? {scaling} : {}),
      ...(kind === 'scatter' ? scatterAxisDetails(axis.body) : {}),
      ...(reversed ? {reversed:true} : {}),
      ...(format !== undefined ? {numberFormat:decodeXmlText(format)} : {}),
      ...(Object.hasOwn(positions, raw) ? { position: positions[raw as keyof typeof positions] } : {}) }
  }
  return { category: project(category), value: project(value) }
}

function secondaryValueAxisIds(xml: string): Set<string> {
  return new Set([...xml.matchAll(/<c:valAx\b[^>]*>([\s\S]*?)<\/c:valAx>/g)]
    .filter(axis => /<c:axPos\b[^>]*\bval="r"|<c:crosses\b[^>]*\bval="max"/.test(axis[1]!))
    .flatMap(axis => axis[1]!.match(/<c:axId\b[^>]*\bval="(\d+)"/)?.[1] ?? []))
}

function legendOf(xml: string): ChartReadSpec['legend'] {
  const match = xml.match(/<c:legend\b[^>]*(?:\/>|>([\s\S]*?)<\/c:legend>)/)
  if (!match) return undefined
  const body = match[1] ?? ''
  const position = { r: 'right', l: 'left', t: 'top', b: 'bottom', tr: 'top-right' } as const
  const raw = body.match(/<c:legendPos\b[^>]*\bval="([^"]*)"/)?.[1] ?? 'r'
  if (!Object.hasOwn(position, raw)) return undefined
  const hiddenEntries = [...body.matchAll(/<c:legendEntry\b[^>]*>([\s\S]*?)<\/c:legendEntry>/g)]
    .filter(entry => /<c:delete\b[^>]*\bval="(?:1|true)"/.test(entry[1]!))
    .map(entry => Number(entry[1]!.match(/<c:idx\b[^>]*\bval="(\d+)"/)?.[1]))
    .filter(Number.isSafeInteger)
  return { position: position[raw as keyof typeof position],
    overlay: /<c:overlay\b[^>]*\bval="(?:1|true)"/.test(body), hiddenEntries }
}

function labelSettings(body: string, palette?: readonly string[], pie = false): ChartReadDataLabel {
  let unsupported = /<c:(?:tx|manualLayout)\b/.test(body)
  const txPr = body.match(/<c:txPr\b[^>]*>([\s\S]*?)<\/c:txPr>/)?.[1]
  let style: ChartReadDataLabel['style']
  if (txPr !== undefined) {
    const defaults = [...txPr.matchAll(/<a:defRPr\b([^>]*)(?:\/>|>([\s\S]*?)<\/a:defRPr>)/g)]
    const fallback = [...txPr.matchAll(/<a:endParaRPr\b([^>]*)(?:\/>|>([\s\S]*?)<\/a:endParaRPr>)/g)]
    const runs = defaults.length ? defaults : fallback
    if (runs.length > 1) unsupported = true
    const attributes = runs[0]?.[1] ?? '', contents = runs[0]?.[2] ?? ''
    const rawSize = attributes.match(/\bsz="([^"]*)"/)?.[1]
    const size = rawSize !== undefined && /^\d+$/.test(rawSize) ? Number(rawSize) : undefined
    if (rawSize !== undefined && (size === undefined || size < 100 || size > 400000)) unsupported = true
    const rawBold = attributes.match(/\bb="([^"]*)"/)?.[1]
    if (rawBold !== undefined && !['0','1','false','true'].includes(rawBold)) unsupported = true
    const fill = contents.match(/<a:solidFill\b[^>]*>([\s\S]*?)<\/a:solidFill>/)?.[1]
    const color = fill === undefined ? undefined : chartLabelColor(fill, palette)
    if (fill !== undefined && !color || /<a:(?:noFill|gradFill|pattFill|blipFill)\b/.test(contents)) unsupported = true
    style = {...(size !== undefined ? {sizePt:size/100}:{}),...(rawBold !== undefined ? {bold:rawBold === '1' || rawBold === 'true'}:{}),...(color ? {color}: {})}
  }
  const flag = (name: string): boolean | undefined => {
    const elements = [...body.matchAll(new RegExp(`<c:${name}\\b([^>]*)`,'g'))]
    if (elements.length > 1) unsupported = true
    if (!elements.length) return undefined
    const raw = elements[0]![1]!.match(/\bval="([^"]*)"/)?.[1] ?? '1'
    if (!['0','1','false','true'].includes(raw)) unsupported = true
    return raw === '1' || raw === 'true'
  }
  const showValue = flag('showVal'), deleted = flag('delete')
  const showCategory = flag('showCatName'), showPercent = flag('showPercent')
  if (!pie && (showCategory || showPercent)) unsupported = true
  for (const name of ['showSerName','showBubbleSize','showLegendKey']) if (flag(name)) unsupported = true
  const positions = [...body.matchAll(/<c:dLblPos\b[^>]*\bval="([^"]*)"/g)]
  const code = positions[0]?.[1], map = {ctr:'center',inEnd:'inside-end',outEnd:'outside-end'} as const
  if (positions.length > 1 || code !== undefined && !Object.hasOwn(map,code) && !(pie && code === 'bestFit')) unsupported = true
  const format = body.match(/<c:numFmt\b[^>]*\bformatCode="([^"]*)"/)?.[1]
  return {...(showValue !== undefined ? {showValue}:{}),...(deleted !== undefined ? {deleted}:{}),
    ...(pie && showCategory !== undefined ? {showCategory}:{}),...(pie && showPercent !== undefined ? {showPercent}:{}),
    ...(style !== undefined ? {style}:{}),
    ...(code !== undefined && Object.hasOwn(map,code) ? {position:map[code as keyof typeof map]}:{}),
    ...(format !== undefined ? {numberFormat:decodeXmlText(format)}:{}),...(unsupported ? {unsupported:true}: {})}
}

function dataLabelsOf(xml: string, palette?: readonly string[], pie = false): ChartReadDataLabels | undefined {
  const blocks = [...xml.matchAll(/<c:dLbls\b[^>]*(?:\/>|>([\s\S]*?)<\/c:dLbls>)/g)]
  if (!blocks.length) return undefined
  if (blocks.length !== 1) return {unsupported:true}
  const body = blocks[0]![1] ?? '', points: Record<number,ChartReadDataLabel> = {}
  let invalid = false, count = 0
  const defaults = body.replace(/<c:dLbl\b[^>]*(?:\/>|>([\s\S]*?)<\/c:dLbl>)/g,(_all,pointBody: string | undefined)=>{
    const raw = pointBody?.match(/<c:idx\b[^>]*\bval="(\d+)"/)?.[1], index = raw === undefined ? NaN : Number(raw)
    if (!Number.isInteger(index) || index > 4294967295 || Object.hasOwn(points,index) || ++count > 10000) invalid = true
    else points[index] = labelSettings(pointBody ?? '', palette, pie)
    return ''
  })
  return {...labelSettings(defaults, palette, pie),...(count ? {points}:{}),...(invalid ? {unsupported:true}: {})}
}

function scatterPlotDataLabelsOf(xml: string): ChartReadDataLabels | undefined {
  const chartUri = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
  const parser = new SaxesParser({xmlns:true})
  let depth = 0, labelsDepth = -1, blocks = 0
  const flags = new Map<string,string>()
  parser.on('doctype',()=>{throw new Error('DOCTYPE')})
  parser.on('opentag',tag=>{
    if (depth === 1 && tag.uri === chartUri && tag.local === 'dLbls') {
      blocks++
      labelsDepth = depth+1
    } else if (depth === labelsDepth && tag.uri === chartUri && ['delete','showVal','showPercent'].includes(tag.local) && !flags.has(tag.local)) {
      flags.set(tag.local,tag.attributes.val?.value ?? '')
    }
    depth++
  })
  parser.on('closetag',()=>{
    depth--
    if (depth < labelsDepth) labelsDepth = -1
  })
  try {
    parser.write(`<c:scatterChart xmlns:c="${chartUri}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:foreign="urn:foreign">${xml}</c:scatterChart>`).close()
  } catch {
    return {unsupported:true}
  }
  if (!blocks) return undefined
  if (blocks !== 1) return {unsupported:true}
  const shown = (name:string) => ['1','true'].includes(flags.get(name) ?? '')
  return {showValue:!shown('delete') && shown('showVal') && !shown('showPercent')}
}

function designOf(xml: string, palette: readonly string[] | undefined, axes: ChartReadSpec['axes']): ChartReadDesign {
  const axis = (name: string) => xml.match(new RegExp(`<c:${name}\\b[^>]*>([\\s\\S]*?)<\\/c:${name}>`))?.[1]
  const scatter = /<c:scatterChart\b/.test(xml)
  const axisById = (id: number | undefined) => id === undefined ? undefined : [...xml.matchAll(/<c:valAx\b[^>]*>([\s\S]*?)<\/c:valAx>/g)]
    .find(match => Number(match[1]!.match(/<c:axId\b[^>]*\bval="(\d+)"/)?.[1]) === id)?.[1]
  const category = scatter ? axisById(axes?.category.id) : axis('catAx') ?? axis('dateAx')
  const value = scatter ? axisById(axes?.value.id) : axis('valAx')
  const axisTitle = (body: string | undefined, fallback?: string) => {
    if (body === undefined) return undefined
    const title = titleText(body)
    return title.title ?? title.titleCache ?? fallback ?? (/<c:title\b/.test(body) ? undefined : '')
  }
  const plot = xml.match(/<c:(barChart|lineChart|areaChart|pieChart|doughnutChart|radarChart|scatterChart)\b[^>]*>([\s\S]*?)<\/c:\1>/)
  const body = plot?.[2], withoutSeries = body?.replace(/<c:ser\b[^>]*>[\s\S]*?<\/c:ser>/g, '')
  const pie = plot?.[1] === 'pieChart' || plot?.[1] === 'doughnutChart'
  const grouping = withoutSeries?.match(/<c:grouping\b[^>]*\bval="([^"]*)"/)?.[1] ?? 'standard'
  const labels = withoutSeries === undefined ? undefined : scatter ? scatterPlotDataLabelsOf(withoutSeries) : dataLabelsOf(withoutSeries, palette, pie)
  const customLabels = /<c:dLbls\b/.test(body ?? '') && (labels === undefined || labels.unsupported ||
    /<c:dLbl\b/.test(body ?? '') || [...(body ?? '').matchAll(/<c:ser\b[^>]*>([\s\S]*?)<\/c:ser>/g)].some(series => /<c:dLbls\b/.test(series[1]!)))
  let dataLabels: ChartReadDesign['dataLabels']
  if (!customLabels && body !== undefined) {
    if (scatter) dataLabels = labels?.showValue ? 'value' : 'none'
    else {
      const flags = [!!labels?.showValue, !!labels?.showCategory, !!labels?.showPercent].map(flag => !labels?.deleted && flag).join(',')
      dataLabels = flags === 'true,false,false' ? 'value' : flags === 'false,true,true' ? 'category-percent'
        : flags === 'false,false,true' ? 'percent' : flags === 'false,false,false' ? 'none' : undefined
    }
  }
  return {
    axisTitles: { category: axisTitle(category, scatter ? axes?.category.title : undefined), value: axisTitle(value, scatter ? axes?.value.title : undefined) },
    legend: /<c:legend\b/.test(xml) ? legendOf(xml)?.position : 'none',
    ...(dataLabels !== undefined ? { dataLabels } : {}),
    ...(['barChart', 'lineChart', 'areaChart'].includes(plot?.[1] ?? '') && ['standard', 'clustered', 'stacked', 'percentStacked'].includes(grouping)
      ? { grouping: grouping === 'standard' ? 'clustered' as const : grouping as ChartReadDesign['grouping'] } : {}),
    ...(scatter ? axes?.value.majorGridlines === undefined ? {} : { gridlines: axes.value.majorGridlines }
      : value !== undefined ? { gridlines: /<c:majorGridlines\b/.test(value) } : {}),
  }
}

function categoryLabels(cat: string): Pick<ChartReadSeries, 'categories' | 'categoryNumberFormat' | 'categoryGroups'> {
  const multi = cat.match(/<c:multiLvlStrCache\b[^>]*>([\s\S]*?)<\/c:multiLvlStrCache>/)?.[1]
  if (multi !== undefined) {
    const rawCount = multi.match(/<c:ptCount\b[^>]*\bval="([^"]*)"/)?.[1]
    const count = rawCount === undefined ? NaN : /^\d+$/.test(rawCount) ? Number(rawCount) : NaN
    if (!Number.isSafeInteger(count) || count < 0 || count > 10000) return { categories: [] }
    const levels = [...multi.matchAll(/<c:lvl\b[^>]*>([\s\S]*?)<\/c:lvl>/g)].map(match => match[1] ?? '')
    const readLevel = (body: string): Map<number, string | null> | undefined => {
      const points = new Map<number, string | null>()
      for (const point of body.matchAll(/<c:pt\b([^>]*)>([\s\S]*?)<\/c:pt>/g)) {
        const raw = point[1]!.match(/\bidx="(\d+)"/)?.[1], index = raw === undefined ? NaN : Number(raw)
        const text = point[2]!.match(/<c:v\b[^>]*>([\s\S]*?)<\/c:v>/)?.[1]
        if (!Number.isSafeInteger(index) || index >= count || points.has(index) || text === undefined) return undefined
        points.set(index, decodeXmlText(text))
      }
      return points
    }
    const leaves = levels[0] === undefined ? undefined : readLevel(levels[0])
    if (!leaves) return { categories: [] }
    const outer = levels[1] === undefined ? undefined : readLevel(levels[1])
    if (levels[1] !== undefined && !outer) return { categories: [] }
    const starts = [...(outer ?? new Map<number, string | null>())].sort(([a], [b]) => a - b)
    const categoryGroups = starts.map(([start, label], index) => ({
      label: label ?? '', start, end: starts[index + 1]?.[0] ?? count,
    })).filter(group => group.start < group.end)
    return {
      categories: Array.from({ length: count }, (_, index) => leaves.get(index) ?? null),
      ...(categoryGroups.length ? { categoryGroups } : {}),
    }
  }
  const cache = cat.match(/<c:(strCache|numCache|strLit|numLit)\b[^>]*>([\s\S]*?)<\/c:\1>/)
  if (!cache) return {categories:[]}
  const body = cache[2]!, limit = 10000
  const rawCount = body.match(/<c:ptCount\b[^>]*\bval="([^"]*)"/)?.[1]
  const count = rawCount === undefined ? undefined : /^\d+$/.test(rawCount) ? Number(rawCount) : NaN
  if (count !== undefined && (!Number.isSafeInteger(count) || count > limit)) return {categories:[]}
  const points = new Map<number,string | null>()
  let length = count ?? 0
  for (const point of body.matchAll(/<c:pt\b([^>]*)>([\s\S]*?)<\/c:pt>/g)) {
    const raw = point[1]!.match(/\bidx="(\d+)"/)?.[1], index = raw === undefined ? NaN : Number(raw)
    if (!Number.isSafeInteger(index) || index >= (count ?? limit) || points.has(index)) return {categories:[]}
    const text = point[2]!.match(/<c:v\b[^>]*>([\s\S]*?)<\/c:v>/)?.[1]
    points.set(index,text === undefined ? null : decodeXmlText(text))
    length = Math.max(length,index+1)
  }
  const format = /^num/.test(cache[1]!) ? body.match(/<c:formatCode\b[^>]*>([\s\S]*?)<\/c:formatCode>/)?.[1] : undefined
  return {categories:Array.from({length},(_,index)=>points.get(index) ?? null),
    ...(format !== undefined ? {categoryNumberFormat:decodeXmlText(format)} : {})}
}

function sourceFill(shape: string | undefined, palette: readonly string[] | undefined): Pick<ChartReadSeries, 'color' | 'colorPreviewUnavailable'> {
  const fill = shape?.split(/<a:ln\b/)[0] ?? ''
  if (/<a:noFill\b/.test(fill)) return { color: 'transparent' }
  const solid = fill.match(/<a:solidFill\b[^>]*>([\s\S]*?)<\/a:solidFill>/)?.[1]
  if (solid === undefined) return /<a:(?:gradFill|pattFill|blipFill|grpFill)\b/.test(fill) ? { colorPreviewUnavailable: true } : {}
  const node = solid.match(/^\s*<a:(srgbClr|schemeClr|sysClr)\b([^>]*)>([\s\S]*?)<\/a:\1>\s*$/)
  const raw = node?.[2]?.match(/\bval="([^"]*)"/)?.[1]
  let color: string | undefined
  if (node?.[1] === 'schemeClr') {
    const slot = themeSlotIndex(raw ?? '')
    color = slot === undefined ? undefined : palette?.[slot]
  } else {
    const hex = node?.[1] === 'sysClr' ? node[2]!.match(/\blastClr="([^"]*)"/)?.[1] : raw
    if (hex && /^[a-fA-F0-9]{6}$/.test(hex)) color = '#' + hex.toUpperCase()
  }
  const operations: { kind: 'lumMod' | 'lumOff'; value: number }[] = []
  let invalid = false
  const remaining = (node?.[3] ?? '').replace(/<a:(lumMod|lumOff)\b([^>]*)>\s*<\/a:\1>/g, (_xml, kind: 'lumMod' | 'lumOff', attrs: string) => {
    const raw = attrs.match(/\bval="([+-]?\d+)"/)?.[1], value = raw === undefined ? NaN : Number(raw)
    if (!Number.isSafeInteger(value) || Math.abs(value) > 2147483647 || kind === 'lumMod' && value < 0) invalid = true
    else operations.push({ kind, value: value / 100000 })
    return ''
  })
  // 未支持的透明度/渐变等不能退回未变换的基色。
  return color && !invalid && !remaining.trim()
    ? { color: operations.length ? applyDrawingLuminance(color, operations) : color } : { colorPreviewUnavailable: true }
}

function sourceLine(shape: string | undefined, palette: readonly string[] | undefined): Pick<ChartReadSeries, 'lineColor' | 'lineColorUnavailable' | 'lineWidth'> {
  const line = shape?.match(/<a:ln\b([^>]*?)(?:\/>|>([\s\S]*?)<\/a:ln>)/)
  if (!line) return {}
  const body = line[2] ?? ''
  if (/<a:noFill\b/.test(body)) return {lineColor:'none'}
  const solid = body.match(/<a:solidFill\b[^>]*>[\s\S]*?<\/a:solidFill>/)?.[0]
  const fill = solid === undefined ? undefined : sourceFill(solid,palette)
  const rawWidth = line[1]?.match(/\bw="(\d+)"/)?.[1]
  const width = rawWidth === undefined ? undefined : Number(rawWidth) / 9525
  return {...(fill?.color !== undefined ? {lineColor:fill.color} : {}),
    ...(fill?.colorPreviewUnavailable ? {lineColorUnavailable:true as const} : {}),
    ...(width !== undefined && Number.isFinite(width) && width >= 0 ? {lineWidth:width} : {})}
}

function boundedFormatValue(xml: string, tag: string, min: number, max: number): number | undefined {
  const raw = xml.match(new RegExp(`<c:${tag}\\b[^>]*\\bval="([0-9]+)"`))?.[1]
  const value = raw === undefined ? NaN : Number(raw)
  return Number.isSafeInteger(value) && value >= min && value <= max ? value : undefined
}

function seriesOf(chartXml: string, palette: readonly string[] | undefined, pie = false): ChartReadSeries[] {
  const series: ChartReadSeries[] = []
  for (const match of chartXml.matchAll(/<c:ser\b[^>]*>([\s\S]*?)<\/c:ser>/g)) {
    const body = match[1] ?? ''
    const rawIndex = body.match(/<c:idx\b[^>]*\bval="(\d+)"/)?.[1]
    const index = rawIndex === undefined ? undefined : Number(rawIndex)
    // bound the name lookup to the c:tx element; a lazy match across the
    // whole series body would bleed into the c:cat section
    const tx = body.match(/<c:tx\b[^>]*>([\s\S]*?)<\/c:tx>/)?.[1]
    const nameRef = tx?.match(/<c:f>([\s\S]*?)<\/c:f>/)?.[1]
    const nameCache = tx?.match(/<c:strCache\b[^>]*>[\s\S]*?<c:pt\b[^>]*\bidx="0"[^>]*>[\s\S]*?<c:v>([\s\S]*?)<\/c:v>/)?.[1]
    const beforePoints = body.split(/<c:(?:dPt|marker|cat|val|yVal)\b/)[0] ?? ''
    const fill = sourceFill(beforePoints.match(/<c:spPr\b[^>]*>([\s\S]*?)<\/c:spPr>/)?.[1], palette)
    const line = sourceLine(beforePoints.match(/<c:spPr\b[^>]*>([\s\S]*?)<\/c:spPr>/)?.[1], palette)
    const marker = body.match(/<c:marker\b[^>]*>([\s\S]*?)<\/c:marker>/)?.[1]?.match(/<c:symbol\b[^>]*\bval="([^"]*)"/)?.[1]
    const pointColors: Record<number, string> = {}, pointExplosions: Record<number, number> = {}, pointIds = new Set<number>()
    const explosionPct = pie ? boundedFormatValue(beforePoints, 'explosion', 0, 400) : undefined
    let colorPreviewUnavailable = fill.colorPreviewUnavailable
    for (const point of body.matchAll(/<c:dPt\b[^>]*>([\s\S]*?)<\/c:dPt>/g)) {
      const raw = point[1]!.match(/<c:idx\b[^>]*\bval="(\d+)"/)?.[1], id = raw === undefined ? NaN : Number(raw)
      const pointFill = sourceFill(point[1]!.match(/<c:spPr\b[^>]*>([\s\S]*?)<\/c:spPr>/)?.[1], palette)
      if (!Number.isSafeInteger(id) || id > 4294967295 || pointIds.has(id) || pointFill.colorPreviewUnavailable) colorPreviewUnavailable = true
      else if (pointFill.color !== undefined) pointColors[id] = pointFill.color
      const explosion = pie ? boundedFormatValue(point[1]!, 'explosion', 0, 400) : undefined
      if (Number.isSafeInteger(id) && id <= 4294967295 && !pointIds.has(id) && explosion !== undefined) pointExplosions[id] = explosion
      pointIds.add(id)
    }
    const name =
      (tx !== undefined ? tx.match(/<c:f>([\s\S]*?)<\/c:f>/)?.[1] : undefined) ??
      (tx !== undefined ? tx.match(/<c:v>([\s\S]*?)<\/c:v>/)?.[1] : undefined)
    const cat = body.match(/<c:cat\b[^>]*>([\s\S]*?)<\/c:cat>/)?.[1]
    const categoriesRef = cat !== undefined ? cat.match(/<c:f>([\s\S]*?)<\/c:f>/)?.[1] : undefined
    const val =
      body.match(/<c:val\b[^>]*>([\s\S]*?)<\/c:val>/)?.[1] ??
      // scatter series carry Y in c:yVal and have no c:val at all
      body.match(/<c:yVal\b[^>]*>([\s\S]*?)<\/c:yVal>/)?.[1]
    const valuesRef = val !== undefined ? val.match(/<c:f>([\s\S]*?)<\/c:f>/)?.[1] : undefined
    const literalValues = valuesRef === undefined && val !== undefined && /<c:numLit\b/.test(val)
      ? categoryLabels(val).categories?.map(value => { const number = Number(value); return Number.isFinite(number) ? number : 0 }) : undefined
    if (valuesRef === undefined && literalValues === undefined) continue
    const dataLabels = dataLabelsOf(body, palette, pie)
    const numberFormat = val?.match(/<c:formatCode\b[^>]*>([\s\S]*?)<\/c:formatCode>/)?.[1]
    // scatter: X lives in c:xVal — either a numRef (numeric categories) or a
    // numLit with literal ordinals (no reference to resolve on the grid)
    const xVal = body.match(/<c:xVal\b[^>]*>([\s\S]*?)<\/c:xVal>/)?.[1]
    let xValuesRef: string | undefined
    let xValues: number[] | undefined
    if (xVal !== undefined) {
      xValuesRef = xVal.match(/<c:numRef\b[^>]*>(?:[\s\S]*?)<c:f>([\s\S]*?)<\/c:f>/)?.[1]
      const literal = xVal.match(/<c:numLit\b[^>]*>([\s\S]*?)<\/c:numLit>/)?.[1]
      if (literal !== undefined) {
        xValues = [...literal.matchAll(/<c:v>([\s\S]*?)<\/c:v>/g)]
          .map((point) => Number(point[1]))
          .filter((value) => Number.isFinite(value))
      }
    }
    series.push({
      ...(index !== undefined && Number.isSafeInteger(index) ? { index } : {}),
      ...(name !== undefined ? { name: decodeXmlText(name) } : {}),
      ...(nameRef !== undefined ? { nameRef: decodeXmlText(nameRef) } : {}),
      ...(nameCache !== undefined ? { nameCache: decodeXmlText(nameCache) } : {}),
      ...(fill.color !== undefined ? { color: fill.color } : {}),
      ...line,
      ...(marker !== undefined ? {marker:decodeXmlText(marker)} : {}),
      ...(Object.keys(pointColors).length ? { pointColors } : {}),
      ...(explosionPct === undefined ? {} : { explosionPct }),
      ...(Object.keys(pointExplosions).length ? { pointExplosions } : {}),
      ...(colorPreviewUnavailable ? { colorPreviewUnavailable } : {}),
      ...(dataLabels !== undefined ? {dataLabels}:{}),
      ...(numberFormat !== undefined && numberFormat !== 'General' ? {numberFormat:decodeXmlText(numberFormat)}:{}),
      ...(categoriesRef !== undefined ? { categoriesRef: decodeXmlText(categoriesRef) } : {}),
      ...(cat !== undefined ? categoryLabels(cat) : {}),
      valuesRef: valuesRef === undefined ? '' : decodeXmlText(valuesRef),
      ...(literalValues === undefined ? {} : { values: literalValues }),
      ...(xValuesRef !== undefined ? { xValuesRef: decodeXmlText(xValuesRef) } : {}),
      ...(xValues !== undefined ? { xValues } : {}),
    })
  }
  return series
}

/// Read the charts anchored on one worksheet (anchor + type + title + series refs).
export async function readCharts(
  sourceBytes: Uint8Array,
  worksheetPath: string,
): Promise<ChartReadSpec[]> {
  const source = await createBufferEntrySource(sourceBytes)
  const drawingPath = await drawingPathOf(source, worksheetPath)
  if (drawingPath === null) return []
  const palette = await chartThemePalette(source)
  const drawingXml = chartReadTokens(await source.readText(drawingPath))
  // drawing rels: r:id → ../charts/chartN.xml
  const rels = new Map<string, string>()
  const drawingRelsPath = relsPathOf(drawingPath)
  if (await source.has(drawingRelsPath)) {
    const relsXml = chartReadTokens(await source.readText(drawingRelsPath))
    for (const match of relsXml.matchAll(/<Relationship\b([^>]*?)\/?>/g)) {
      const attributes = match[1] ?? ''
      const id = attributes.match(/\bId="([^"]*)"/)?.[1]
      const target = attributes.match(/\bTarget="([^"]*)"/)?.[1]
      if (id === undefined || target === undefined) continue
      const resolved = new URL(target, `http://pkg/${drawingPath.slice(0, drawingPath.lastIndexOf('/'))}/`)
        .pathname.replace(/^\//, '')
      rels.set(id, resolved)
    }
  }
  const charts: ChartReadSpec[] = []
  for (const match of drawingXml.matchAll(/<xdr:(twoCellAnchor|oneCellAnchor|absoluteAnchor)\b[^>]*>([\s\S]*?)<\/xdr:\1>/g)) {
    const block = match[2] ?? ''
    if (!block.includes('<xdr:graphicFrame')) continue
    const anchor = anchorOf(block, match[1]!)
    if (anchor === null) continue
    const relId = block.match(/\br:id="([^"]*)"/)?.[1]
    if (relId === undefined) continue
    const chartPath = rels.get(relId)
    if (chartPath === undefined || !(await source.has(chartPath))) continue
    const chartXml = chartReadTokens(await source.readText(chartPath))
    const kind = chartKindOf(chartXml)
    if (kind === null) continue // combo/exotic types stay write-only for now
    const pie = kind === 'pie' || kind === 'doughnut'
    const rightIds = secondaryValueAxisIds(chartXml)
    // 保持部件文档顺序，兼容原按位置的series改写；idx/order由源writer保留全局编号。
    const series = kind === 'combo' ? [...chartXml.matchAll(/<c:(barChart|lineChart)\b[^>]*>([\s\S]*?)<\/c:\1>/g)].flatMap(plot => {
      const secondaryAxis = [...plot[2]!.matchAll(/<c:axId\b[^>]*\bval="(\d+)"/g)].some(id => rightIds.has(id[1]!))
      return seriesOf(plot[2]!, palette).map(entry => ({ ...entry, plot: plot[1] as 'barChart' | 'lineChart', secondaryAxis }))
    }) : seriesOf(chartXml, palette, pie)
    if (series.length === 0) continue
    const axes = axesOf(chartXml, kind)
    const secondaryAxes = axesOf(chartXml, kind, true)
    const plot = (
      pie ? chartXml.match(/<c:(?:pieChart|doughnutChart)\b[^>]*>([\s\S]*?)<\/c:(?:pieChart|doughnutChart)>/)?.[1]
        : kind === 'radar' ? chartXml.match(/<c:radarChart\b[^>]*>([\s\S]*?)<\/c:radarChart>/)?.[1]
          : kind === 'scatter' ? chartXml.match(/<c:scatterChart\b[^>]*>([\s\S]*?)<\/c:scatterChart>/)?.[1]
            : axes ? chartXml.match(/<c:(?:barChart|lineChart|areaChart)\b[^>]*>([\s\S]*?)<\/c:(?:barChart|lineChart|areaChart)>/)?.[1] : undefined
    )?.replace(/<c:ser\b[^>]*>[\s\S]*?<\/c:ser>/g, '')
    const dataLabels = plot === undefined ? undefined
      : kind === 'scatter' ? scatterPlotDataLabelsOf(plot) : dataLabelsOf(plot, palette, pie)
    const scatterStyle = kind === 'scatter' ? chartXml.match(/<c:scatterStyle\b[^>]*\bval="([^"]*)"/)?.[1] : undefined
    const valueScaleUnavailable = !axes && (kind === 'bar' || kind === 'column') &&
      [...chartXml.matchAll(/<c:valAx\b[^>]*>([\s\S]*?)<\/c:valAx>/g)].some(axis => valueScaling(axis[1]!) !== undefined)
    charts.push({
      chartPath,
      anchorKind: match[1] as NonNullable<ChartReadSpec['anchorKind']>,
      anchor,
      kind,
      ...(boundedFormatValue(plot ?? '', 'gapWidth', 0, 500) === undefined ? {} : { gapWidthPct: boundedFormatValue(plot ?? '', 'gapWidth', 0, 500) }),
      ...(boundedFormatValue(plot ?? '', 'holeSize', 10, 90) === undefined ? {} : { holeSizePct: boundedFormatValue(plot ?? '', 'holeSize', 10, 90) }),
      design: designOf(chartXml, palette, axes),
      ...(palette ? { palette: palette.slice(4, 10) } : {}),
      ...(/<c:varyColors\b/.test(chartXml) ? { varyColors: /<c:varyColors\b[^>]*\bval="(?:1|true)"/.test(chartXml) } : {}),
      ...(titleOf(chartXml) !== undefined ? { title: titleOf(chartXml) } : {}),
      ...(dataLabels !== undefined ? {dataLabels}:{}),
      ...(scatterStyle !== undefined ? {scatterStyle:decodeXmlText(scatterStyle)} : {}),
      ...(legendOf(chartXml) !== undefined ? { legend: legendOf(chartXml) } : {}),
      ...(axes !== undefined ? { axes } : {}), ...(valueScaleUnavailable ? {valueScaleUnavailable:true as const} : {}),
      ...(secondaryAxes !== undefined ? { secondaryAxes } : {}),
      series,
    })
  }
  return charts
}
