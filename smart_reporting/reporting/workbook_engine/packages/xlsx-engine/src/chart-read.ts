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

export interface ChartReadSeries {
  readonly index?: number | undefined
  /// series name reference (c:tx strRef) or literal
  readonly name?: string | undefined
  readonly nameRef?: string | undefined
  readonly nameCache?: string | undefined
  /// Explicit series fill only; point fills and line colors are separate.
  readonly color?: string | undefined
  readonly categoriesRef?: string | undefined
  readonly valuesRef: string
  /// scatter only: X values reference (c:xVal numRef), absent for ordinal X
  readonly xValuesRef?: string | undefined
  /// scatter only: literal X values when the writer emitted c:numLit ordinals
  readonly xValues?: ReadonlyArray<number> | undefined
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

const titleOf = (chartXml: string): string | undefined => {
  const title = chartXml.match(/<c:title\b[^>]*>([\s\S]*?)<\/c:title>/)?.[1]
  if (title === undefined) return undefined
  const texts = [...title.matchAll(/<a:t>([\s\S]*?)<\/a:t>/g)].map((m) => decodeXmlText(m[1] ?? ''))
  const joined = texts.join('')
  return joined === '' ? undefined : joined
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
      ...(categoriesRef !== undefined ? { categoriesRef: decodeXmlText(categoriesRef) } : {}),
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
    charts.push({
      chartPath,
      anchor: anchorOf(block),
      kind,
      ...(titleOf(chartXml) !== undefined ? { title: titleOf(chartXml) } : {}),
      ...(legendOf(chartXml) !== undefined ? { legend: legendOf(chartXml) } : {}),
      series,
    })
  }
  return charts
}
