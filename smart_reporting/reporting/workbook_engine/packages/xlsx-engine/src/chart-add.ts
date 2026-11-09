/// Ported from genoffice xlsx-gateway/gateway/xlsx-drawing-add.ts (chart
/// branch): persists brand-new chart parts — a chart part, a drawing part
/// (created or extended), the worksheet/drawing relationships, and the
/// [Content_Types].xml overrides. The upstream shape/image branches are not
/// ported. The static report-bitmap extension below reuses this plumbing.

import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
import { createBufferEntrySource, assemblePackage, type EntrySource, type MutationPlan } from './zip'
import { ensureRelationshipNamespace, escapeXmlAttribute, escapeXmlText } from './xml'

export class ChartAddError extends Error {}

export interface DrawingAnchor {
  readonly fromRow: number
  readonly fromColumn: number
  readonly fromRowOffset: number
  readonly fromColumnOffset: number
  readonly toRow: number
  readonly toColumn: number
  readonly toRowOffset: number
  readonly toColumnOffset: number
}

export interface ChartAddSeries {
  readonly name: string
  readonly categories: readonly string[]
  readonly values: readonly number[]
  readonly valuesRef?: string | undefined
  readonly categoriesRef?: string | undefined
  readonly color?: string | undefined
  /// Per-point fills (`c:dPt`), keyed by 0-based point index.
  readonly pointColors?: Readonly<Record<string, string>> | undefined
  /// Pie/doughnut whole-ring explosion, % of radius.
  readonly explosionPct?: number | undefined
  /// Per-slice explosion overrides, keyed by 0-based point index.
  readonly pointExplosions?: Readonly<Record<string, number>> | undefined
}

export interface ChartAdd {
  /// 'combo' plots the last series as a line on a secondary right axis, the
  /// rest as clustered columns (single series degrades to plain columns).
  readonly chartType:
    | 'column'
    | 'bar'
    | 'line'
    | 'area'
    | 'pie'
    | 'scatter'
    | 'radar'
    | 'doughnut'
    | 'combo'
  readonly title: string
  readonly series: readonly ChartAddSeries[]
  readonly legend?: 'none' | 'right' | 'bottom' | 'top' | 'left' | undefined
  readonly dataLabels?: 'none' | 'value' | 'percent' | 'category-percent' | undefined
  readonly dataLabelPosition?: 'center' | 'inside-end' | 'outside-end' | undefined
  /// c:numFmt formatCode, written with sourceLinked="0".
  readonly dataLabelFormat?: string | undefined
  readonly axisTitles?:
    | {
        readonly category?: string | undefined
        readonly value?: string | undefined
      }
    | undefined
  /// Bar/line/area stacking; unset writes clustered/standard.
  readonly grouping?: 'clustered' | 'stacked' | 'percentStacked' | 'standard' | undefined
  /// true adds value-axis major gridlines; false/unset writes none.
  readonly gridlines?: boolean | undefined
  readonly valueAxis?:
    | {
        readonly min?: number | undefined
        readonly max?: number | undefined
      }
    | undefined
  readonly gapWidthPct?: number | undefined
  readonly holeSizePct?: number | undefined
}

export interface ChartAddition {
  /// Display name of the target worksheet; the part path is resolved through
  /// workbook.xml relationships.
  readonly worksheetSheetName: string
  readonly anchor: DrawingAnchor
  readonly chart: ChartAdd
}

const DRAWING_REL_TYPE =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing'
const CHART_REL_TYPE =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart'
const DRAWING_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.drawing+xml'
const CHART_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.drawingml.chart+xml'
const CONTENT_TYPES_PATH = '[Content_Types].xml'

const MAX_CHART_SERIES = 32
const MAX_CHART_POINTS = 5000
const MAX_CHART_POINT_INDEX = 9999
const HEX_COLOR = /^#[0-9A-Fa-f]{6}$/

/// point-index keyed maps (dPt overrides): keys must be non-negative
/// integers and, when present, colors must be #RRGGBB — junk keys would
/// otherwise bake `val="NaN"` dPt entries into the chart part.
function validatePointMap(
  label: string,
  map: Readonly<Record<string, string | number>> | undefined,
  color: boolean,
): void {
  if (map === undefined) return
  for (const [key, value] of Object.entries(map)) {
    if (!/^\d+$/.test(key) || Number(key) > MAX_CHART_POINT_INDEX) {
      throw new ChartAddError(`${label} keys must be 0-based point indices.`)
    }
    if (color) {
      if (typeof value !== 'string' || !HEX_COLOR.test(value)) {
        throw new ChartAddError(`${label} color "${String(value)}" 必须是 #RRGGBB。`)
      }
    } else if (typeof value !== 'number' || !Number.isInteger(value) || value < 0 || value > 400) {
      throw new ChartAddError(`${label} 值必须是 0-400 的整数。`)
    }
  }
}

function validateAddition(addition: ChartAddition): void {
  const anchor = addition.anchor
  for (const [name, value] of Object.entries(anchor)) {
    if (!Number.isInteger(value) || value < 0 || value > 10_000_000) {
      throw new ChartAddError(`Drawing anchor ${name} must be a non-negative integer.`)
    }
  }
  if (anchor.toRow < anchor.fromRow || anchor.toColumn < anchor.fromColumn) {
    throw new ChartAddError('Drawing anchor end must not precede its start.')
  }
  const chart = addition.chart
  if (chart.gapWidthPct !== undefined && (!Number.isInteger(chart.gapWidthPct) || chart.gapWidthPct < 0 || chart.gapWidthPct > 500)) {
    throw new ChartAddError('gapWidthPct must be an integer between 0 and 500.')
  }
  if (chart.holeSizePct !== undefined && (!Number.isInteger(chart.holeSizePct) || chart.holeSizePct < 10 || chart.holeSizePct > 90)) {
    throw new ChartAddError('holeSizePct must be an integer between 10 and 90.')
  }
  if (chart.series.length === 0) throw new ChartAddError('A chart needs at least one series.')
  if (chart.series.length > MAX_CHART_SERIES) {
    throw new ChartAddError(`A chart supports at most ${MAX_CHART_SERIES} series.`)
  }
  if (chart.title.length > 200) throw new ChartAddError('Chart title is too long.')
  for (const [index, series] of chart.series.entries()) {
    if (series.name.length > 200) throw new ChartAddError(`Series ${index + 1} name is too long.`)
    if (series.values.length === 0) throw new ChartAddError(`Series ${index + 1} has no values.`)
    if (series.values.length > MAX_CHART_POINTS) {
      throw new ChartAddError(`Series ${index + 1} exceeds ${MAX_CHART_POINTS} points.`)
    }
    if (!series.values.every((value) => Number.isFinite(value))) {
      throw new ChartAddError(`Series ${index + 1} has non-finite values.`)
    }
    if (series.categories.length > MAX_CHART_POINTS) {
      throw new ChartAddError(`Series ${index + 1} exceeds ${MAX_CHART_POINTS} categories.`)
    }
    if (series.color !== undefined && !HEX_COLOR.test(series.color)) {
      throw new ChartAddError(`Series ${index + 1} color "${series.color}" 必须是 #RRGGBB。`)
    }
    if (series.explosionPct !== undefined && (!Number.isInteger(series.explosionPct) || series.explosionPct < 0 || series.explosionPct > 400)) {
      throw new ChartAddError(`Series ${index + 1} explosion must be an integer between 0 and 400.`)
    }
    validatePointMap(`Series ${index + 1} pointColors`, series.pointColors, true)
    validatePointMap(`Series ${index + 1} pointExplosions`, series.pointExplosions, false)
  }
}

export async function applyChartAdditions(
  sourceBytes: Uint8Array,
  additions: readonly ChartAddition[],
): Promise<Uint8Array> {
  const source = await createBufferEntrySource(sourceBytes)
  const overlay = new Map<string, string>()
  const addedEntries: string[] = []
  const touchedEntries = new Set<string>()
  for (const addition of additions) {
    validateAddition(addition)
    const workbookXml = await readPart(source, overlay, 'xl/workbook.xml')
    const element = parseSheetElements(workbookXml).find((entry) => entry.name === addition.worksheetSheetName)
    if (!element?.relationshipId) {
      throw new ChartAddError(`工作表 "${addition.worksheetSheetName}" 不存在。`)
    }
    const worksheetPath = await resolveWorksheetPath(
      { readText: (path) => readPart(source, overlay, path) },
      element.relationshipId,
    )
    const drawing = await ensureSheetDrawing(source, overlay, addedEntries, worksheetPath, touchedEntries)
    const chartPath = await allocatePartPath(source, overlay, 'xl/charts/chart', '.xml')
    overlay.set(chartPath, buildChartXml(addition.chart))
    addedEntries.push(chartPath)
    touchedEntries.add(chartPath)
    await registerContentTypeOverride(source, overlay, chartPath, CHART_CONTENT_TYPE)
    const chartRelId = await appendRelationship(
      source,
      overlay,
      relsPathFor(drawing.path),
      CHART_REL_TYPE,
      relativeTarget(drawing.path, chartPath),
    )
    touchedEntries.add(relsPathFor(drawing.path))
    await appendAnchor(source, overlay, drawing.path, addition.anchor, (shapeId) =>
      chartFrameXml(shapeId, chartRelId),
    )
    touchedEntries.add(drawing.path)
  }
  const replaced = new Map<string, string>()
  for (const [path, content] of overlay) {
    if (!addedEntries.includes(path)) replaced.set(path, content)
  }
  const mutation = await assemblePackage(sourceBytes, {
    replaced,
    added: new Map(addedEntries.map((path): [string, string] => [path, overlay.get(path) ?? ''])),
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries,
    touchedEntries: [...touchedEntries],
  } satisfies MutationPlan)
  return mutation.buffer
}

/// Overlay read: writes staged for this plan win over the source package.
async function readPart(source: EntrySource, overlay: ReadonlyMap<string, string>, path: string): Promise<string> {
  return overlay.get(path) ?? (await source.readText(path))
}

async function hasPart(
  source: EntrySource,
  overlay: ReadonlyMap<string, string>,
  path: string,
): Promise<boolean> {
  return overlay.has(path) || (await source.has(path))
}

/// Finds the sheet's drawing part, creating (and wiring) one if absent.
async function ensureSheetDrawing(
  source: EntrySource,
  overlay: Map<string, string>,
  addedEntries: string[],
  worksheetPath: string,
  touchedEntries: Set<string>,
): Promise<{ path: string }> {
  const sheetRelsPath = relsPathFor(worksheetPath)
  if (await hasPart(source, overlay, sheetRelsPath)) {
    const rels = await readPart(source, overlay, sheetRelsPath)
    const existing = matchRelationship(rels, DRAWING_REL_TYPE)
    if (existing) {
      return { path: resolveRelTarget(worksheetPath, existing.target) }
    }
  }
  const drawingPath = await allocatePartPath(source, overlay, 'xl/drawings/drawing', '.xml')
  overlay.set(
    drawingPath,
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
      '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"' +
      ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"></xdr:wsDr>',
  )
  addedEntries.push(drawingPath)
  touchedEntries.add(drawingPath)
  await registerContentTypeOverride(source, overlay, drawingPath, DRAWING_CONTENT_TYPE)
  const sheetRelsExisted = await hasPart(source, overlay, sheetRelsPath)
  const relId = await appendRelationship(
    source,
    overlay,
    sheetRelsPath,
    DRAWING_REL_TYPE,
    relativeTarget(worksheetPath, drawingPath),
  )
  if (!sheetRelsExisted) addedEntries.push(sheetRelsPath)
  touchedEntries.add(sheetRelsPath)
  await insertWorksheetDrawingElement(source, overlay, worksheetPath, relId, touchedEntries)
  return { path: drawingPath }
}

/// `<drawing>` sits near the end of CT_Worksheet — before the trailing
/// optional members if any of them are present.
const AFTER_DRAWING_ELEMENTS = [
  'legacyDrawing',
  'legacyDrawingHF',
  'picture',
  'oleObjects',
  'controls',
  'webPublishItems',
  'tableParts',
  'extLst',
] as const

async function insertWorksheetDrawingElement(
  source: EntrySource,
  overlay: Map<string, string>,
  worksheetPath: string,
  relId: string,
  touchedEntries: Set<string>,
): Promise<void> {
  let xml = await readPart(source, overlay, worksheetPath)
  if (/<drawing[\s/>]/.test(xml)) {
    throw new ChartAddError(`${worksheetPath} already has a drawing element but no drawing rel.`)
  }
  xml = ensureRelationshipNamespace(xml)
  const element = `<drawing r:id="${escapeXmlAttribute(relId)}"/>`
  let insertAt = xml.lastIndexOf('</worksheet>')
  if (insertAt < 0) throw new ChartAddError(`${worksheetPath} has no closing worksheet tag.`)
  for (const name of AFTER_DRAWING_ELEMENTS) {
    const match = xml.search(new RegExp(`<${name}[\\s/>]`))
    if (match >= 0 && match < insertAt) insertAt = match
  }
  overlay.set(worksheetPath, xml.slice(0, insertAt) + element + xml.slice(insertAt))
  touchedEntries.add(worksheetPath)
}

async function appendAnchor(
  source: EntrySource,
  overlay: Map<string, string>,
  drawingPath: string,
  anchor: DrawingAnchor,
  buildInner: (shapeId: number) => string,
): Promise<void> {
  let xml = await readPart(source, overlay, drawingPath)
  // Other producers write the wsDr root with any prefix and self-close it
  // when the drawing is empty (Google Sheets exports do); normalize before
  // appending, and declare our prefixes locally when the root lacks them.
  const root = xml.match(/<(?:([A-Za-z_][\w.-]*):)?wsDr(?=[\s/>])([^>]*)>/)
  if (!root || root.index === undefined) {
    throw new ChartAddError(`${drawingPath} is not a spreadsheet drawing part.`)
  }
  const closeTag = `</${root[1] === undefined ? '' : `${root[1]}:`}wsDr>`
  if ((root[2] ?? '').trimEnd().endsWith('/')) {
    const openTag = root[0].replace(/\/\s*>$/, '>')
    xml = xml.slice(0, root.index) + openTag + closeTag + xml.slice(root.index + root[0].length)
  }
  const closeAt = xml.lastIndexOf(closeTag)
  if (closeAt < 0) throw new ChartAddError(`${drawingPath} is not a spreadsheet drawing part.`)
  const namespaceFix =
    (root[0].includes('xmlns:xdr=')
      ? ''
      : ' xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"') +
    (root[0].includes('xmlns:a=')
      ? ''
      : ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"')
  const marker = (row: number, column: number, rowOffset: number, columnOffset: number) =>
    `<xdr:col>${column}</xdr:col><xdr:colOff>${columnOffset}</xdr:colOff>` +
    `<xdr:row>${row}</xdr:row><xdr:rowOff>${rowOffset}</xdr:rowOff>`
  const element =
    `<xdr:twoCellAnchor${namespaceFix}>` +
    `<xdr:from>${marker(anchor.fromRow, anchor.fromColumn, anchor.fromRowOffset, anchor.fromColumnOffset)}</xdr:from>` +
    `<xdr:to>${marker(anchor.toRow, anchor.toColumn, anchor.toRowOffset, anchor.toColumnOffset)}</xdr:to>` +
    buildInner(nextShapeId(xml)) +
    '<xdr:clientData/>' +
    '</xdr:twoCellAnchor>'
  overlay.set(drawingPath, xml.slice(0, closeAt) + element + xml.slice(closeAt))
}

function chartFrameXml(shapeId: number, chartRelId: string): string {
  return (
    '<xdr:graphicFrame macro="">' +
    '<xdr:nvGraphicFramePr>' +
    `<xdr:cNvPr id="${shapeId}" name="Chart ${shapeId}"/>` +
    '<xdr:cNvGraphicFramePr/>' +
    '</xdr:nvGraphicFramePr>' +
    '<xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm>' +
    '<a:graphic>' +
    '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">' +
    '<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"' +
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"' +
    ` r:id="${escapeXmlAttribute(chartRelId)}"/>` +
    '</a:graphicData>' +
    '</a:graphic>' +
    '</xdr:graphicFrame>'
  )
}

function nextShapeId(drawingXml: string): number {
  let max = 1
  for (const match of drawingXml.matchAll(/<(?:[\w.-]+:)?cNvPr [^>]*id="(\d+)"/g)) {
    max = Math.max(max, Number(match[1]))
  }
  return max + 1
}

// ---- chart XML ----

const LEGEND_POSITIONS: Record<string, string> = {
  right: 'r',
  bottom: 'b',
  top: 't',
  left: 'l',
}

const DLBL_POSITIONS: Record<NonNullable<ChartAdd['dataLabelPosition']>, string> = {
  center: 'ctr',
  'inside-end': 'inEnd',
  'outside-end': 'outEnd',
}

/// Office theme accent cycle — same order as the renderer's chartColors, so
/// Excel opens a new chart with the colors the canvas showed.
const OFFICE_PALETTE = [
  '4472C4',
  'ED7D31',
  'A5A5A5',
  'FFC000',
  '5B9BD5',
  '70AD47',
  '264478',
  '9E480E',
  '636363',
  '997300',
] as const

function paletteArgb(index: number): string {
  return OFFICE_PALETTE[index % OFFICE_PALETTE.length] ?? '4472C4'
}

export function buildChartXml(chart: ChartAdd): string {
  const isPieLike = chart.chartType === 'pie' || chart.chartType === 'doughnut'
  const isScatter = chart.chartType === 'scatter'
  const isCombo = chart.chartType === 'combo'
  const axCat = 100000001
  const axVal = 100000002
  // Combo secondary pair: hidden category axis + right value axis.
  const axCat2 = 100000003
  const axVal2 = 100000004
  const seriesXml = chart.series
    .map((series, index) =>
      isScatter
        ? buildScatterSeriesXml(series, index)
        : buildSeriesXml(series, index, chart.chartType),
    )
    .join('')
  const wantsLabelDetail =
    chart.dataLabelPosition !== undefined || chart.dataLabelFormat !== undefined
  // 'none' beats a position/format sent in the same call; detail without a
  // mode implies value labels (mirrors the edit-side default).
  const dLbls =
    chart.dataLabels === 'none' || (chart.dataLabels === undefined && !wantsLabelDetail)
      ? ''
      : dataLabelsXml(chart.dataLabels ?? 'value', chart.dataLabelPosition, chart.dataLabelFormat)
  // Pie-likes have no axes: their titles are ignored.
  const catTitle =
    chart.axisTitles?.category === undefined ? '' : axisTitleXml(chart.axisTitles.category)
  const valTitle = chart.axisTitles?.value === undefined ? '' : axisTitleXml(chart.axisTitles.value)
  // CT_Scaling order: orientation, max, min.
  const valScaling =
    '<c:scaling><c:orientation val="minMax"/>' +
    (chart.valueAxis?.max === undefined ? '' : `<c:max val="${chart.valueAxis.max}"/>`) +
    (chart.valueAxis?.min === undefined ? '' : `<c:min val="${chart.valueAxis.min}"/>`) +
    '</c:scaling>'
  const gridlines = chart.gridlines === true ? '<c:majorGridlines/>' : ''
  const gapWidth =
    chart.gapWidthPct !== undefined &&
    (chart.chartType === 'column' || chart.chartType === 'bar' || chart.chartType === 'combo')
      ? `<c:gapWidth val="${chart.gapWidthPct}"/>`
      : ''
  // Stacked bars overlap fully, matching what Excel writes.
  const overlap =
    (chart.chartType === 'column' || chart.chartType === 'bar') &&
    (chart.grouping === 'stacked' || chart.grouping === 'percentStacked')
      ? '<c:overlap val="100"/>'
      : ''
  // Bars ride the primary axes, the line rides a secondary right value axis
  // plus a hidden category axis — PowerPoint's combo-with-secondary shape
  // (mirrors pptx-engine chart-insert).
  const comboPlot = (): string => {
    const lineCount = chart.series.length >= 2 ? 1 : 0
    const barEnd = chart.series.length - lineCount
    const barSers = chart.series
      .slice(0, barEnd)
      .map((series, index) => buildSeriesXml(series, index, 'column'))
      .join('')
    const lineSers = chart.series
      .slice(barEnd)
      .map((series, index) => buildSeriesXml(series, barEnd + index, 'line'))
      .join('')
    return (
      '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/><c:varyColors val="0"/>' +
      `${barSers}${dLbls}${gapWidth}<c:axId val="${axCat}"/><c:axId val="${axVal}"/></c:barChart>` +
      (lineSers
        ? '<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>' +
          `${lineSers}<c:marker val="1"/><c:axId val="${axCat2}"/><c:axId val="${axVal2}"/></c:lineChart>`
        : '') +
      `<c:catAx><c:axId val="${axCat}"/><c:scaling><c:orientation val="minMax"/></c:scaling>` +
      `<c:delete val="0"/><c:axPos val="b"/>${catTitle}<c:crossAx val="${axVal}"/></c:catAx>` +
      `<c:valAx><c:axId val="${axVal}"/>${valScaling}` +
      `<c:delete val="0"/><c:axPos val="l"/>${gridlines}${valTitle}<c:crossAx val="${axCat}"/></c:valAx>` +
      (lineSers
        ? `<c:valAx><c:axId val="${axVal2}"/><c:scaling><c:orientation val="minMax"/></c:scaling>` +
          `<c:delete val="0"/><c:axPos val="r"/><c:crossAx val="${axCat2}"/><c:crosses val="max"/></c:valAx>` +
          `<c:catAx><c:axId val="${axCat2}"/><c:scaling><c:orientation val="minMax"/></c:scaling>` +
          `<c:delete val="1"/><c:axPos val="b"/><c:crossAx val="${axVal2}"/></c:catAx>`
        : '')
    )
  }
  const plot = isCombo
    ? comboPlot()
    : isPieLike
      ? chart.chartType === 'doughnut'
        ? `<c:doughnutChart><c:varyColors val="1"/>${seriesXml}${dLbls}<c:holeSize val="${chart.holeSizePct ?? 50}"/></c:doughnutChart>`
        : `<c:pieChart><c:varyColors val="1"/>${seriesXml}${dLbls}</c:pieChart>`
      : isScatter
        ? /// XY scatter plots against two value axes (X on bottom, Y on left)
          /// instead of the category + value pair the other plots use.
          `<c:scatterChart><c:scatterStyle val="lineMarker"/>${seriesXml}${dLbls}` +
          `<c:axId val="${axCat}"/><c:axId val="${axVal}"/>` +
          '</c:scatterChart>' +
          `<c:valAx><c:axId val="${axCat}"/><c:scaling><c:orientation val="minMax"/></c:scaling>` +
          `<c:delete val="0"/><c:axPos val="b"/>${catTitle}<c:crossAx val="${axVal}"/></c:valAx>` +
          `<c:valAx><c:axId val="${axVal}"/>${valScaling}` +
          `<c:delete val="0"/><c:axPos val="l"/>${gridlines}${valTitle}<c:crossAx val="${axCat}"/></c:valAx>`
        : `${plotOpenTag(chart.chartType, chart.grouping)}${seriesXml}${dLbls}${gapWidth}${overlap}` +
          `<c:axId val="${axCat}"/><c:axId val="${axVal}"/>` +
          `${plotCloseTag(chart.chartType)}` +
          `<c:catAx><c:axId val="${axCat}"/><c:scaling><c:orientation val="minMax"/></c:scaling>` +
          `<c:delete val="0"/><c:axPos val="b"/>${catTitle}<c:crossAx val="${axVal}"/></c:catAx>` +
          `<c:valAx><c:axId val="${axVal}"/>${valScaling}` +
          `<c:delete val="0"/><c:axPos val="l"/>${gridlines}${valTitle}<c:crossAx val="${axCat}"/></c:valAx>`
  const legend =
    chart.legend !== undefined
      ? chart.legend === 'none'
        ? ''
        : `<c:legend><c:legendPos val="${LEGEND_POSITIONS[chart.legend]}"/><c:overlay val="0"/></c:legend>`
      : chart.series.length > 1 || isPieLike
        ? '<c:legend><c:legendPos val="b"/><c:overlay val="0"/></c:legend>'
        : ''
  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"' +
    ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"' +
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
    '<c:chart>' +
    '<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r>' +
    `<a:t>${escapeXmlText(chart.title)}</a:t>` +
    '</a:r></a:p></c:rich></c:tx><c:overlay val="0"/></c:title>' +
    '<c:autoTitleDeleted val="0"/>' +
    `<c:plotArea><c:layout/>${plot}</c:plotArea>` +
    legend +
    '<c:plotVisOnly val="1"/>' +
    '</c:chart>' +
    '</c:chartSpace>'
  )
}

/// Same flag set xlsx-chart.ts writes, so later edits recognize the element.
/// CT_DLbls order: numFmt, spPr, txPr, dLblPos, show*.
function dataLabelsXml(
  mode: 'value' | 'percent' | 'category-percent',
  position?: ChartAdd['dataLabelPosition'],
  format?: string | undefined,
): string {
  const showValue = mode === 'value'
  const showCategory = mode === 'category-percent'
  const showPercent = mode === 'percent' || mode === 'category-percent'
  return (
    '<c:dLbls>' +
    (format === undefined
      ? ''
      : `<c:numFmt formatCode="${escapeXmlAttribute(format)}" sourceLinked="0"/>`) +
    (position === undefined ? '' : `<c:dLblPos val="${DLBL_POSITIONS[position]}"/>`) +
    '<c:showLegendKey val="0"/>' +
    `<c:showVal val="${showValue ? '1' : '0'}"/>` +
    `<c:showCatName val="${showCategory ? '1' : '0'}"/>` +
    '<c:showSerName val="0"/>' +
    `<c:showPercent val="${showPercent ? '1' : '0'}"/>` +
    '<c:showBubbleSize val="0"/></c:dLbls>'
  )
}

function axisTitleXml(text: string): string {
  return (
    '<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r>' +
    `<a:t>${escapeXmlText(text)}</a:t>` +
    '</a:r></a:p></c:rich></c:tx><c:overlay val="0"/></c:title>'
  )
}

function plotOpenTag(chartType: ChartAdd['chartType'], grouping?: ChartAdd['grouping']): string {
  const stacked = grouping === 'stacked' || grouping === 'percentStacked' ? grouping : undefined
  if (chartType === 'line')
    return `<c:lineChart><c:grouping val="${stacked ?? 'standard'}"/><c:varyColors val="0"/>`
  if (chartType === 'area')
    return `<c:areaChart><c:grouping val="${stacked ?? 'standard'}"/><c:varyColors val="0"/>`
  if (chartType === 'radar')
    return '<c:radarChart><c:radarStyle val="marker"/><c:varyColors val="0"/>'
  return (
    `<c:barChart><c:barDir val="${chartType === 'bar' ? 'bar' : 'col'}"/>` +
    `<c:grouping val="${stacked ?? 'clustered'}"/><c:varyColors val="0"/>`
  )
}

function plotCloseTag(chartType: ChartAdd['chartType']): string {
  if (chartType === 'line') return '</c:lineChart>'
  if (chartType === 'area') return '</c:areaChart>'
  if (chartType === 'radar') return '</c:radarChart>'
  return '</c:barChart>'
}

function buildSeriesXml(
  series: ChartAddSeries,
  index: number,
  chartType: ChartAdd['chartType'],
): string {
  const categories = series.categories.slice(0, series.values.length)
  const cat =
    categories.length === 0
      ? ''
      : '<c:cat>' +
        (series.categoriesRef
          ? `<c:strRef><c:f>${escapeXmlText(series.categoriesRef)}</c:f>` +
            `<c:strCache>${pointCount(categories.length)}${strPoints(categories)}</c:strCache></c:strRef>`
          : `<c:strLit>${pointCount(categories.length)}${strPoints(categories)}</c:strLit>`) +
        '</c:cat>'
  const val =
    '<c:val>' +
    (series.valuesRef
      ? `<c:numRef><c:f>${escapeXmlText(series.valuesRef)}</c:f>` +
        `<c:numCache><c:formatCode>General</c:formatCode>` +
        `${pointCount(series.values.length)}${numPoints(series.values)}</c:numCache></c:numRef>`
      : `<c:numLit>${pointCount(series.values.length)}${numPoints(series.values)}</c:numLit>`) +
    '</c:val>'
  const isPieLike = chartType === 'pie' || chartType === 'doughnut'
  const isLineLike = chartType === 'line' || chartType === 'radar'
  // Pie-likes color per slice (dPt) like the renderer; the ser-level spPr
  // only appears when explicitly asked for.
  const spPr = isPieLike
    ? seriesColorXml(series.color, false)
    : seriesColorXml(series.color ?? `#${paletteArgb(index)}`, isLineLike)
  return (
    '<c:ser>' +
    `<c:idx val="${index}"/><c:order val="${index}"/>` +
    `<c:tx><c:v>${escapeXmlText(series.name)}</c:v></c:tx>` +
    spPr +
    // CT_PieSer only: explosion sits after spPr, before dPt.
    (isPieLike && series.explosionPct !== undefined
      ? `<c:explosion val="${series.explosionPct}"/>`
      : '') +
    (chartType === 'line' ? '<c:marker><c:symbol val="none"/></c:marker>' : '') +
    (chartType === 'radar' ? '<c:marker><c:symbol val="circle"/></c:marker>' : '') +
    dataPointsXml(isPieLike ? sliceColors(series) : series.pointColors, series.pointExplosions) +
    cat +
    val +
    '</c:ser>'
  )
}

/// Line-drawn plots color the stroke (a:ln); the rest fill the shape.
function seriesColorXml(color: string | undefined, stroke: boolean): string {
  if (color === undefined) return ''
  const fill = `<a:solidFill><a:srgbClr val="${color.slice(1).toUpperCase()}"/></a:solidFill>`
  return stroke ? `<c:spPr><a:ln>${fill}</a:ln></c:spPr>` : `<c:spPr>${fill}</c:spPr>`
}

/// Every slice gets a fill: explicit pointColors win, the Office palette
/// cycles underneath (same order as the renderer's pieSliceColor).
function sliceColors(series: ChartAddSeries): Readonly<Record<string, string>> {
  return Object.fromEntries(
    series.values.map((_, idx) => [
      String(idx),
      series.pointColors?.[idx] ?? `#${paletteArgb(idx)}`,
    ]),
  )
}

/// dPt entries in ascending idx order; a same-idx color and explosion share
/// one dPt (CT_DPt order: idx, bubble3D, explosion, spPr).
function dataPointsXml(
  pointColors: ChartAddSeries['pointColors'],
  pointExplosions: ChartAddSeries['pointExplosions'],
): string {
  const indices = [
    ...new Set(
      [...Object.keys(pointColors ?? {}), ...Object.keys(pointExplosions ?? {})].map(Number),
    ),
  ].sort((a, b) => a - b)
  return indices
    .map((idx) => {
      const color = pointColors?.[idx]
      const explosion = pointExplosions?.[idx]
      return (
        `<c:dPt><c:idx val="${idx}"/><c:bubble3D val="0"/>` +
        (explosion === undefined ? '' : `<c:explosion val="${explosion}"/>`) +
        (color === undefined
          ? ''
          : `<c:spPr><a:solidFill><a:srgbClr val="${color.slice(1).toUpperCase()}"/></a:solidFill></c:spPr>`) +
        '</c:dPt>'
      )
    })
    .join('')
}

/// Scatter series plot X/Y number pairs (`c:xVal` + `c:yVal`) rather than
/// category + value. Categories become the X values when they are all
/// numeric; otherwise ordinals 0,1,2,… stand in.
function buildScatterSeriesXml(series: ChartAddSeries, index: number): string {
  const categories = series.categories.slice(0, series.values.length)
  const numericCategories = categories.map((value) => Number(value))
  const categoriesAreNumeric =
    categories.length === series.values.length &&
    categories.length > 0 &&
    numericCategories.every((value) => Number.isFinite(value))
  const xValues = categoriesAreNumeric ? numericCategories : series.values.map((_unused, i) => i)
  const xVal =
    '<c:xVal>' +
    (categoriesAreNumeric && series.categoriesRef
      ? `<c:numRef><c:f>${escapeXmlText(series.categoriesRef)}</c:f>` +
        `<c:numCache><c:formatCode>General</c:formatCode>` +
        `${pointCount(xValues.length)}${numPoints(xValues)}</c:numCache></c:numRef>`
      : `<c:numLit>${pointCount(xValues.length)}${numPoints(xValues)}</c:numLit>`) +
    '</c:xVal>'
  const yVal =
    '<c:yVal>' +
    (series.valuesRef
      ? `<c:numRef><c:f>${escapeXmlText(series.valuesRef)}</c:f>` +
        `<c:numCache><c:formatCode>General</c:formatCode>` +
        `${pointCount(series.values.length)}${numPoints(series.values)}</c:numCache></c:numRef>`
      : `<c:numLit>${pointCount(series.values.length)}${numPoints(series.values)}</c:numLit>`) +
    '</c:yVal>'
  return (
    '<c:ser>' +
    `<c:idx val="${index}"/><c:order val="${index}"/>` +
    `<c:tx><c:v>${escapeXmlText(series.name)}</c:v></c:tx>` +
    seriesColorXml(series.color ?? `#${paletteArgb(index)}`, true) +
    dataPointsXml(series.pointColors, series.pointExplosions) +
    xVal +
    yVal +
    '</c:ser>'
  )
}

function pointCount(count: number): string {
  return `<c:ptCount val="${count}"/>`
}

function strPoints(values: readonly string[]): string {
  return values
    .map((value, i) => `<c:pt idx="${i}"><c:v>${escapeXmlText(value)}</c:v></c:pt>`)
    .join('')
}

function numPoints(values: readonly number[]): string {
  return values.map((value, i) => `<c:pt idx="${i}"><c:v>${String(value)}</c:v></c:pt>`).join('')
}

// ---- package plumbing ----

/// Next free `<prefix>N<suffix>` path, scanning current entries (including
/// entries added earlier in this same plan).
async function allocatePartPath(
  source: EntrySource,
  overlay: ReadonlyMap<string, string>,
  prefix: string,
  suffix: string,
): Promise<string> {
  const pattern = new RegExp(`^${prefix}(\\d+)${suffix.replace('.', '\\.')}$`)
  let max = 0
  for (const path of new Set([...(await source.paths()), ...overlay.keys()])) {
    const match = path.match(pattern)
    if (match) max = Math.max(max, Number(match[1]))
  }
  return `${prefix}${max + 1}${suffix}`
}

function relsPathFor(partPath: string): string {
  const slash = partPath.lastIndexOf('/')
  return `${partPath.slice(0, slash)}/_rels/${partPath.slice(slash + 1)}.rels`
}

/// Relative target from one part to another (e.g. worksheet → ../drawings/…).
function relativeTarget(fromPart: string, toPart: string): string {
  const fromDir = fromPart.split('/').slice(0, -1)
  const toSegments = toPart.split('/')
  let common = 0
  while (
    common < fromDir.length &&
    common < toSegments.length - 1 &&
    fromDir[common] === toSegments[common]
  ) {
    common += 1
  }
  const ups = fromDir.length - common
  return `${'../'.repeat(ups)}${toSegments.slice(common).join('/')}`
}

function matchRelationship(relsXml: string, type: string): { id: string; target: string } | null {
  for (const match of relsXml.matchAll(/<Relationship\b[^>]*\/?>(?:<\/Relationship>)?/g)) {
    const tag = match[0]
    if (!tag.includes(`Type="${type}"`)) continue
    const id = tag.match(/\bId="([^"]+)"/)?.[1]
    const target = tag.match(/\bTarget="([^"]+)"/)?.[1]
    if (id && target) return { id, target }
  }
  return null
}

function resolveRelTarget(fromPart: string, target: string): string {
  const base = fromPart.split('/').slice(0, -1)
  for (const segment of target.split('/')) {
    if (segment === '..') base.pop()
    else if (segment !== '.' && segment !== '') base.push(segment)
  }
  return base.join('/')
}

/// Adds a relationship (creating the rels part when missing); returns its id.
async function appendRelationship(
  source: EntrySource,
  overlay: Map<string, string>,
  relsPath: string,
  type: string,
  target: string,
): Promise<string> {
  const exists = await hasPart(source, overlay, relsPath)
  const xml = exists
    ? await readPart(source, overlay, relsPath)
    : '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '</Relationships>'
  let max = 0
  for (const match of xml.matchAll(/\bId="rId(\d+)"/g)) {
    max = Math.max(max, Number(match[1]))
  }
  const id = `rId${max + 1}`
  const element =
    `<Relationship Id="${id}" Type="${escapeXmlAttribute(type)}" ` +
    `Target="${escapeXmlAttribute(target)}"/>`
  const closeAt = xml.lastIndexOf('</Relationships>')
  if (closeAt < 0) throw new ChartAddError(`${relsPath} is not a relationships part.`)
  overlay.set(relsPath, xml.slice(0, closeAt) + element + xml.slice(closeAt))
  return id
}

async function registerContentTypeOverride(
  source: EntrySource,
  overlay: Map<string, string>,
  partPath: string,
  contentType: string,
): Promise<void> {
  const xml = await readPart(source, overlay, CONTENT_TYPES_PATH)
  if (xml.includes(`PartName="/${partPath}"`)) return
  const closeAt = xml.lastIndexOf('</Types>')
  if (closeAt < 0) throw new ChartAddError('[Content_Types].xml is malformed.')
  overlay.set(
    CONTENT_TYPES_PATH,
    xml.slice(0, closeAt) +
      `<Override PartName="${escapeXmlAttribute(`/${partPath}`)}" ` +
      `ContentType="${escapeXmlAttribute(contentType)}"/>` +
      xml.slice(closeAt),
  )
}

/** Static bitmap addition; shares the existing drawing/relationship/package pipeline. */
export interface StaticImageAddition {
  readonly worksheetSheetName: string
  readonly anchor: DrawingAnchor
  readonly imageId: string
  readonly bytes: Uint8Array
  readonly contentType: 'image/png' | 'image/jpeg'
  /** A trusted existing media part replaces pixels without changing the anchor. */
  readonly replaceMediaPart?: string | undefined
}

export async function applyStaticImage(
  sourceBytes: Uint8Array, addition: StaticImageAddition,
): Promise<{ bytes: Uint8Array; mediaPart: string }> {
  const source = await createBufferEntrySource(sourceBytes)
  const overlay = new Map<string, string>()
  const addedEntries: string[] = []
  const touchedEntries = new Set<string>()
  const workbookXml = await source.readText('xl/workbook.xml')
  const sheet = parseSheetElements(workbookXml).find(entry => entry.name === addition.worksheetSheetName)
  if (!sheet?.relationshipId) throw new Error('workbook_image_sheet_missing')
  const worksheetPath = await resolveWorksheetPath(source, sheet.relationshipId)
  const mediaPart = addition.replaceMediaPart ?? await allocatePartPath(
    source, overlay, 'xl/media/image', addition.contentType === 'image/png' ? '.png' : '.jpeg',
  )
  if (addition.replaceMediaPart) {
    if (!/^xl\/media\/image\d+\.(png|jpeg)$/.test(mediaPart) || !await source.has(mediaPart)) {
      throw new Error('workbook_image_replacement_invalid')
    }
  } else {
    const drawing = await ensureSheetDrawing(source, overlay, addedEntries, worksheetPath, touchedEntries)
    const relsPath = relsPathFor(drawing.path)
    if (!await hasPart(source, overlay, relsPath)) addedEntries.push(relsPath)
    const relId = await appendRelationship(source, overlay, relsPath,
      'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image',
      relativeTarget(drawing.path, mediaPart))
    await appendAnchor(source, overlay, drawing.path, addition.anchor, shapeId =>
      '<xdr:pic><xdr:nvPicPr>' +
      `<xdr:cNvPr id="${shapeId}" name="${escapeXmlAttribute(addition.imageId)}"/>` +
      '<xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr></xdr:nvPicPr>' +
      '<xdr:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"' +
      ` r:embed="${escapeXmlAttribute(relId)}"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>` +
      '<xdr:spPr><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic>')
    touchedEntries.add(drawing.path)
    touchedEntries.add(relsPath)
    addedEntries.push(mediaPart)
  }
  // Replacements can change PNG ↔ JPEG: content type follows the actual bytes.
  let types = await readPart(source, overlay, CONTENT_TYPES_PATH)
  types = types.replace(new RegExp(`<Override\\b[^>]*PartName="/${mediaPart}"[^>]*/>`), '')
  overlay.set(CONTENT_TYPES_PATH, types)
  await registerContentTypeOverride(source, overlay, mediaPart, addition.contentType)
  touchedEntries.add(CONTENT_TYPES_PATH)
  touchedEntries.add(mediaPart)
  const mutation = await assemblePackage(sourceBytes, {
    replaced: new Map([...overlay].filter(([path]) => !addedEntries.includes(path))),
    added: new Map([...overlay].filter(([path]) => addedEntries.includes(path))),
    addedBinary: new Map([[mediaPart, addition.bytes]]), removedEntries: [], addedEntries,
    touchedEntries: [...touchedEntries],
  })
  return { bytes: mutation.buffer, mediaPart }
}
