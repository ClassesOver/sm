/// Chart read-back (图表网格渲染 v1): parses the worksheet's drawing part for
/// chart anchors and each chart part for type/title/series references. Values
/// are NOT cached here — the render extension resolves the references against
/// the live grid, so edits flow into the picture on the next paint.

import { createBufferEntrySource } from './zip'
import { decodeXmlText } from './xml'

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
  readonly deleted?: boolean | undefined
  readonly position?: 'center' | 'inside-end' | 'outside-end' | undefined
  readonly numberFormat?: string | undefined
  readonly unsupported?: true | undefined
}
export interface ChartReadDataLabels extends ChartReadDataLabel {
  readonly points?: Readonly<Record<number, ChartReadDataLabel>> | undefined
}

export interface ChartReadSeries {
  readonly index?: number | undefined
  /// series name reference (c:tx strRef) or literal
  readonly name?: string | undefined
  readonly nameRef?: string | undefined
  readonly nameCache?: string | undefined
  /// Explicit series fill only; point fills and line colors are separate.
  readonly color?: string | undefined
  readonly dataLabels?: ChartReadDataLabels | undefined
  readonly numberFormat?: string | undefined
  readonly categoriesRef?: string | undefined
  /// Preserve single-level category point indices. Empty means an unreadable
  /// source category block; absent means there was no category block.
  readonly categories?: ReadonlyArray<string | null> | undefined
  readonly categoryNumberFormat?: string | undefined
  readonly valuesRef: string
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
  readonly scaling?: {
    readonly min?: number | undefined
    readonly max?: number | undefined
    readonly majorUnit?: number | undefined
    readonly reversed: boolean
    readonly unsupported?: 'invalid' | 'logarithmic' | undefined
  } | undefined
}

export interface ChartReadSpec {
  readonly chartPath: string
  readonly anchor: {
    readonly fromRow: number
    readonly fromColumn: number
    readonly toRow: number
    readonly toColumn: number
  }
  readonly kind: ChartReadKind
  readonly title?: string | undefined
  readonly dataLabels?: ChartReadDataLabels | undefined
  readonly axes?: { readonly category: ChartReadAxis; readonly value: ChartReadAxis } | undefined
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
  const relsXml = await source.readText(relsPath)
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

const anchorOf = (block: string) => {
  const from = block.match(/<xdr:from>[\s\S]*?<\/xdr:from>/)?.[0] ?? ''
  const to = block.match(/<xdr:to>[\s\S]*?<\/xdr:to>/)?.[0] ?? ''
  const num = (xml: string, tag: string): number =>
    Number(xml.match(new RegExp(`<xdr:${tag}>([0-9]+)</xdr:${tag}>`))?.[1] ?? 0)
  return {
    fromRow: num(from, 'row'),
    fromColumn: num(from, 'col'),
    toRow: num(to, 'row'),
    toColumn: num(to, 'col'),
  }
}

function chartKindOf(chartXml: string): ChartReadKind | null {
  if (/<c:pieChart\b/.test(chartXml)) return 'pie'
  if (/<c:doughnutChart\b/.test(chartXml)) return 'doughnut'
  const hasBar = /<c:barChart\b/.test(chartXml)
  const hasLine = /<c:lineChart\b/.test(chartXml)
  if (hasBar && hasLine) return 'combo' // bar+line dual plot (write-side combo)
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

function axesOf(xml: string, kind: ChartReadKind): ChartReadSpec['axes'] {
  if (kind !== 'column' && kind !== 'bar') return undefined
  const plots = [...xml.matchAll(/<c:barChart\b[^>]*>([\s\S]*?)<\/c:barChart>/g)]
  if (plots.length !== 1) return undefined
  const unsigned = (raw: string | undefined): number | undefined => {
    const value = raw === undefined ? NaN : Number(raw)
    return Number.isInteger(value) && value >= 0 && value <= 4294967295 ? value : undefined
  }
  const idOf = (body: string, tag: string) => unsigned(body.match(new RegExp(`<c:${tag}\\b[^>]*\\bval="(\\d+)"`))?.[1])
  const ids = [...plots[0]![1]!.matchAll(/<c:axId\b[^>]*\bval="(\d+)"/g)].map(match => unsigned(match[1]))
  if (ids.length !== 2 || ids.some(id => id === undefined) || new Set(ids).size !== 2) return undefined
  const axes = [...xml.matchAll(/<c:(catAx|dateAx|valAx)\b[^>]*>([\s\S]*?)<\/c:\1>/g)]
    .map(match => ({ kind: match[1]!, body: match[2]!, id: idOf(match[2]!, 'axId') }))
    .filter(axis => axis.id !== undefined && ids.includes(axis.id))
  if (axes.length !== 2 || new Set(axes.map(axis => axis.id)).size !== 2) return undefined
  const category = axes.find(axis => axis.kind === 'catAx' || axis.kind === 'dateAx')
  const value = axes.find(axis => axis.kind === 'valAx')
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
    return { id: axis.id!, hidden, ...titleText(axis.body), ...(scaling ? {scaling} : {}),
      ...(reversed ? {reversed:true} : {}),
      ...(format !== undefined ? {numberFormat:decodeXmlText(format)} : {}),
      ...(Object.hasOwn(positions, raw) ? { position: positions[raw as keyof typeof positions] } : {}) }
  }
  return { category: project(category), value: project(value) }
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

function labelSettings(body: string): ChartReadDataLabel {
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
    const colorNode = fill?.match(/^\s*<a:srgbClr\b([^>]*?)(?:\/>|>\s*<\/a:srgbClr>)\s*$/)
    const rgb = colorNode?.[1]?.match(/\bval="([a-fA-F0-9]{6})"/)?.[1]
    if (fill !== undefined && !rgb || /<a:(?:noFill|gradFill|pattFill|blipFill)\b/.test(contents)) unsupported = true
    style = {...(size !== undefined ? {sizePt:size/100}:{}),...(rawBold !== undefined ? {bold:rawBold === '1' || rawBold === 'true'}:{}),...(rgb ? {color:'#'+rgb.toUpperCase()}: {})}
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
  for (const name of ['showCatName','showSerName','showPercent','showBubbleSize','showLegendKey']) if (flag(name)) unsupported = true
  const positions = [...body.matchAll(/<c:dLblPos\b[^>]*\bval="([^"]*)"/g)]
  const code = positions[0]?.[1], map = {ctr:'center',inEnd:'inside-end',outEnd:'outside-end'} as const
  if (positions.length > 1 || code !== undefined && !Object.hasOwn(map,code)) unsupported = true
  const format = body.match(/<c:numFmt\b[^>]*\bformatCode="([^"]*)"/)?.[1]
  return {...(showValue !== undefined ? {showValue}:{}),...(deleted !== undefined ? {deleted}:{}),
    ...(style !== undefined ? {style}:{}),
    ...(code !== undefined && Object.hasOwn(map,code) ? {position:map[code as keyof typeof map]}:{}),
    ...(format !== undefined ? {numberFormat:decodeXmlText(format)}:{}),...(unsupported ? {unsupported:true}: {})}
}

function dataLabelsOf(xml: string): ChartReadDataLabels | undefined {
  const blocks = [...xml.matchAll(/<c:dLbls\b[^>]*(?:\/>|>([\s\S]*?)<\/c:dLbls>)/g)]
  if (!blocks.length) return undefined
  if (blocks.length !== 1) return {unsupported:true}
  const body = blocks[0]![1] ?? '', points: Record<number,ChartReadDataLabel> = {}
  let invalid = false, count = 0
  const defaults = body.replace(/<c:dLbl\b[^>]*(?:\/>|>([\s\S]*?)<\/c:dLbl>)/g,(_all,pointBody: string | undefined)=>{
    const raw = pointBody?.match(/<c:idx\b[^>]*\bval="(\d+)"/)?.[1], index = raw === undefined ? NaN : Number(raw)
    if (!Number.isInteger(index) || index > 4294967295 || Object.hasOwn(points,index) || ++count > 10000) invalid = true
    else points[index] = labelSettings(pointBody ?? '')
    return ''
  })
  return {...labelSettings(defaults),...(count ? {points}:{}),...(invalid ? {unsupported:true}: {})}
}

function categoryLabels(cat: string): Pick<ChartReadSeries, 'categories' | 'categoryNumberFormat'> {
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

function seriesOf(chartXml: string): ChartReadSeries[] {
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
    const fill = beforePoints.match(/<c:spPr\b[^>]*>([\s\S]*?)<\/c:spPr>/)?.[1]?.split(/<a:ln\b/)[0]
    const color = fill?.match(/<a:solidFill\b[^>]*>\s*<a:srgbClr\b[^>]*\bval="([a-fA-F0-9]{6})"/)?.[1]
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
    if (valuesRef === undefined) continue
    const dataLabels = dataLabelsOf(body)
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
      ...(color !== undefined ? { color: '#' + color } : {}),
      ...(dataLabels !== undefined ? {dataLabels}:{}),
      ...(numberFormat !== undefined && numberFormat !== 'General' ? {numberFormat:decodeXmlText(numberFormat)}:{}),
      ...(categoriesRef !== undefined ? { categoriesRef: decodeXmlText(categoriesRef) } : {}),
      ...(cat !== undefined ? categoryLabels(cat) : {}),
      valuesRef: decodeXmlText(valuesRef),
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
  const drawingXml = await source.readText(drawingPath)
  // drawing rels: r:id → ../charts/chartN.xml
  const rels = new Map<string, string>()
  const drawingRelsPath = relsPathOf(drawingPath)
  if (await source.has(drawingRelsPath)) {
    const relsXml = await source.readText(drawingRelsPath)
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
  for (const match of drawingXml.matchAll(/<xdr:twoCellAnchor\b[^>]*>([\s\S]*?)<\/xdr:twoCellAnchor>/g)) {
    const block = match[1] ?? ''
    if (!block.includes('<xdr:graphicFrame')) continue
    const relId = block.match(/\br:id="([^"]*)"/)?.[1]
    if (relId === undefined) continue
    const chartPath = rels.get(relId)
    if (chartPath === undefined || !(await source.has(chartPath))) continue
    const chartXml = await source.readText(chartPath)
    const kind = chartKindOf(chartXml)
    if (kind === null) continue // combo/exotic types stay write-only for now
    const series = seriesOf(chartXml)
    if (series.length === 0) continue
    const axes = axesOf(chartXml, kind)
    const plot = axes ? chartXml.match(/<c:barChart\b[^>]*>([\s\S]*?)<\/c:barChart>/)?.[1]?.replace(/<c:ser\b[^>]*>[\s\S]*?<\/c:ser>/g,'') : undefined
    const dataLabels = plot === undefined ? undefined : dataLabelsOf(plot)
    const valueScaleUnavailable = !axes && (kind === 'bar' || kind === 'column') &&
      [...chartXml.matchAll(/<c:valAx\b[^>]*>([\s\S]*?)<\/c:valAx>/g)].some(axis => valueScaling(axis[1]!) !== undefined)
    charts.push({
      chartPath,
      anchor: anchorOf(block),
      kind,
      ...(titleOf(chartXml) !== undefined ? { title: titleOf(chartXml) } : {}),
      ...(dataLabels !== undefined ? {dataLabels}:{}),
      ...(legendOf(chartXml) !== undefined ? { legend: legendOf(chartXml) } : {}),
      ...(axes !== undefined ? { axes } : {}), ...(valueScaleUnavailable ? {valueScaleUnavailable:true as const} : {}),
      series,
    })
  }
  return charts
}
