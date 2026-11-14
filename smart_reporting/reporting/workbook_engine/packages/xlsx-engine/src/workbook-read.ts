import { readSheetThreads, type SheetThreadsModel } from './thread-read'
import type { SheetTableSource } from './table-source'
import { SaxesParser } from 'saxes'
import { columnWidthToPixels, rowHeightToPixels } from './geometry'
/// Workbook importer: bytes → editor model (sheets, cells with style
/// indexes, geometry, styles, theme palette). Values/formulas follow the
/// genoffice reader; styles and geometry are read here because the web app
/// has no sidecar to resolve them.

import { withoutFutureFunctionMarkers } from './future-functions'
import { readSheetProtection, readWorkbookProtection, type SheetProtectionModel, type WorkbookProtectionModel } from './protection-read'
import { readOutlineSummary, readOutlineLine } from './outline-read'
import { readSheetNotes, type SheetNotesModel } from './note-read'
import { readSheetFilter, type SheetFilterModel } from './filter-read'
import { readDataValidations, type SheetDataValidationModel } from './data-validation-read'
import { readSheetTables, type SheetTableModel } from './table-read'
import { parseStylesheet, parseThemePalette, type Stylesheet } from './style-read'
import { readCfRules, type CfReadableRule } from './cf-read'
import { readConditionalFormattingSnapshot, type ConditionalFormattingSnapshot } from './conditional-formatting-read'
import { readDefinedNames, type DefinedNameEntry } from './defined-names'
import { readSparklines, type SparklineSpec } from './sparklines'
import { readCharts, type ChartReadSpec } from './chart-read'
import { createBufferEntrySource, type EntrySource } from './zip'
import { decodeCellText, decodeXmlText, escapeXmlText, escapeRegExp, readXmlAttribute, extractElements, sectionInner } from './xml'

export interface ModelCell {
  value: string | number | boolean | null
  formula?: string | undefined
  /// cellXfs index the cell carries (`s` attribute), for style resolution
  styleIndex?: number | undefined
}

export interface ColumnDef {
  start: number
  end: number
  width: number | undefined
  hidden: boolean
  outlineLevel?: number
  collapsed?: boolean
}

export interface RowDef {
  row: number
  height: number | undefined
  hidden: boolean
  outlineLevel?: number
  collapsed?: boolean
}

export interface SheetMarginsModel {
  left: number
  right: number
  top: number
  bottom: number
  header: number
  footer: number
}

export interface SheetPageSetupModel {
  orientation?: 'portrait' | 'landscape' | undefined
  paperSize?: number | undefined
  /// 打印缩放百分比（10-400；OOXML 默认 100，缺省时保留 undefined）。
  scale?: number | undefined
  /// fitToPage 宽/高页数（OOXML 默认 1，缺省时保留 undefined）。
  fitToWidth?: number | undefined
  fitToHeight?: number | undefined
  fitToPage?: boolean | undefined
}

export interface SheetHeaderFooterModel {
  oddHeader?: string
  oddFooter?: string
  firstHeader?: string
  firstFooter?: string
  evenHeader?: string
  evenFooter?: string
  differentFirst?: boolean
  differentOddEven?: boolean
  scaleWithDoc?: boolean
}

export interface SheetModel {
  name: string
  /// workbook sheet@state 的 hidden/veryHidden；可见表保持旧模型缺省。
  hidden?: boolean
  /// worksheet part path (xl/worksheets/sheetN.xml)
  path: string
  cells: Readonly<Record<string, ModelCell>>
  /// mergeCell refs, e.g. "A1:B2"
  merges: readonly string[]
  columns: readonly ColumnDef[]
  rows: readonly RowDef[]
  /// 源sheetFormatPr默认尺寸，与图片锚点及SDK使用同一像素转换。
  defaultColumnWidthPx?: number
  defaultRowHeightPx?: number
  outlineSummaryBelow?: boolean
  outlineSummaryRight?: boolean
  freeze: { frozenRows: number; frozenColumns: number } | null
  /// 视图▸拆分窗口：state 缺省或 split 的 pane，xSplit/ySplit 为 1/20 磅（twips）而非行列数，不得当作冻结。
  /// 只读回报以便保留与说明；冻结写回会按 Excel 行为以冻结窗格替换它。
  splitPane?: { xSplitTwips: number; ySplitTwips: number; topLeftCell?: string }
  /// sheetView showGridLines（OOXML 默认 true；写回经 applyPageSetups）。
  showGridlines: boolean
  /// sheetView showRowColHeaders（缺省 true；旧模型可省略）。
  showHeadings?: boolean
  /// sheetView rightToLeft（缺省 false；旧模型可省略）。
  rightToLeft?: boolean
  /// sheetView showFormulas（公式视图，OOXML 默认 false；仅为真时出现，写回经 applyPageSetups）。
  showFormulas?: boolean
  /// 常规视图缩放百分比（10-400，OOXML 默认 100；写回经 applyPageSetups）。
  zoomScale: number
  /// 页面设置（pageSetup 元素 + sheetPr@pageSetUpPr；写回经 applyPageSetups）。
  pageSetup?: SheetPageSetupModel
  /// 页边距（英寸；OOXML 默认 0.7/0.7/0.75/0.75/0.3/0.3；写回经 applyPageSetups 预设）。
  margins?: SheetMarginsModel
  /// 文件页眉页脚只读投影；保留原生控制串，打印时才展开字段。
  headerFooter?: SheetHeaderFooterModel
  /// printOptions 打印网格线/标题（OOXML 默认 false；写回经 applyPageSetups）。
  printGridlines?: boolean
  printHeadings?: boolean
  /// 手动分页符（brk@id，0-based，位于该行/列之前；写回经 applyPageSetups breaks）。
  rowBreaks?: readonly number[]
  colBreaks?: readonly number[]
  /// 工作表级 `_xlnm.Print_Area` / `_xlnm.Print_Titles`（去掉工作表前缀与 $ 的
  /// 显示形式，如 "A1:B4"；写回经 applyPageSetups printArea/printTitles）。
  printArea?: string | undefined
  printTitles?: string | undefined
  dimension: string | null
  /// Rotation commands are gated until inherited row/column/base-XF styles are modeled.
  rotationReadOnlyReason?: string
  /// 同 rotationReadOnlyReason：缩进经行/列样式、默认 xf、父样式或禁用对齐继承时，
  /// 网格投影无法完整回读，前端缩进编辑禁用。
  indentReadOnlyReason?: string
  /// self-colored conditional formats (dataBar / colorScale) read back for
  /// grid rendering; cellIs/iconSet are write-only boundaries
  conditionalFormats?: ReadonlyArray<CfReadableRule>
  /// Native full-rule manager projection; old conditionalFormats remains the render-only compatibility view.
  conditionalFormatting?: Omit<ConditionalFormattingSnapshot, 'sourceXml'>
  /// sparklines (x14) read back for grid rendering
  sparklines?: ReadonlyArray<SparklineSpec>
  /// anchored charts read back for grid rendering (column/bar/line/pie v1)
  charts?: ReadonlyArray<ChartReadSpec>
  threads?: SheetThreadsModel
  notes?: SheetNotesModel
  /// worksheet-level autoFilter: range + per-column criteria (values/blank/
  /// customs/dateGroups); readOnlyReason marks structures (color/icon/top10/
  /// dynamic) the write path refuses
  filter?: SheetFilterModel
  /// Complete source validation snapshot; partial reads prohibit replacement.
  dataValidations?: SheetDataValidationModel
  tables?: readonly SheetTableModel[]
  tablesReadOnlyReason?: string
  tableSources?: readonly SheetTableSource[]
  tableSourcesReadOnlyReason?: string
  /// `<sheetProtection>` state; absent when the sheet carries no element
  protection?: SheetProtectionModel
}

export interface WorkbookModel {
  sheets: readonly SheetModel[]
  styles: Stylesheet
  /// theme index order palette for resolving theme colors; undefined → defaults
  themePalette: readonly string[] | undefined
  /// workbook-level defined names (global scope; sheet-scoped excluded)
  definedNames?: ReadonlyArray<DefinedNameEntry>
  /// `<workbookProtection>` state; absent when workbook.xml carries no element
  workbookProtection?: WorkbookProtectionModel
}

const TAG_ATTRIBUTES = `(?:"[^"]*"|'[^']*'|[^>"'])*?`

export interface SheetElement {
  readonly xml: string
  readonly name: string
  readonly hidden: boolean
  readonly relationshipId: string | undefined
}

export function parseSheetElements(workbookXml: string): SheetElement[] {
  const elements: SheetElement[] = []
  for (const match of workbookXml.matchAll(
    new RegExp(`<sheet\\b${TAG_ATTRIBUTES}(?:/>|>[\\s\\S]*?</sheet>)`, 'g'),
  )) {
    const xml = match[0]
    const name = readXmlAttribute(xml, 'name')
    if (name === undefined) continue
    const state = readXmlAttribute(xml, 'state')
    elements.push({
      xml,
      name: decodeXmlText(name),
      hidden: state === 'hidden' || state === 'veryHidden',
      // The relationships namespace is conventionally bound to "r", but any
      // prefix is legal — fall back to whatever prefix the producer chose.
      relationshipId:
        readXmlAttribute(xml, 'r:id') ??
        xml.match(/(?:^|\s)[A-Za-z_][\w.-]*:id="([^"]*)"/)?.[1],
    })
  }
  return elements
}

/// Two-step lookup through workbook.xml.rels: attribute order varies by
/// producer (openpyxl puts Target before Id), so never assume Id precedes
/// Target.
export async function resolveWorksheetPath(
  reader: Pick<EntrySource, 'readText'>,
  relationshipId: string,
): Promise<string> {
  const relationshipsXml = await reader.readText('xl/_rels/workbook.xml.rels')
  const relationshipXml = relationshipsXml.match(
    new RegExp(`<Relationship\\b[^>]*\\bId="${escapeRegExp(relationshipId)}"[^>]*/?>`),
  )?.[0]
  const targetMatch =
    relationshipXml === undefined ? undefined : readXmlAttribute(relationshipXml, 'Target')
  if (!targetMatch) throw new Error(`找不到关系 ${relationshipId}。`)
  const target = targetMatch.replace(/^\/?xl\//, '')
  return `xl/${target.replace(/^\.\//, '')}`
}

async function readSharedStrings(source: EntrySource): Promise<readonly string[]> {
  if (!(await source.has('xl/sharedStrings.xml'))) return []
  const xml = await source.readText('xl/sharedStrings.xml')
  return [...xml.matchAll(/<si(?:\s[^>]*)?>([\s\S]*?)<\/si>/g)].map((itemMatch) =>
    [...(itemMatch[1] ?? '').matchAll(/<t(?:\s[^>]*)?>([\s\S]*?)<\/t>/g)]
      .map((textMatch) => decodeCellText(textMatch[1] ?? ''))
      .join(''),
  )
}

function parseWorksheetCells(worksheetXml: string, sharedStrings: readonly string[]) {
  const cells: Record<string, ModelCell> = {}
  for (const match of worksheetXml.matchAll(/<c\b([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g)) {
    const attributes = match[1] ?? ''
    const address = readXmlAttribute(attributes, 'r')
    if (!address || !/^[A-Z]{1,3}[1-9][0-9]{0,6}$/.test(address)) continue
    const body = match[2] ?? ''
    const styleRaw = readXmlAttribute(attributes, 's')
    const styleIndex = styleRaw === undefined ? undefined : Number(styleRaw)
    const formula = body.match(/<f(?:\s[^>]*[^/>])?>([\s\S]*?)<\/f>/)?.[1]
    if (formula !== undefined) {
      cells[address] = { value: null, formula: `=${withoutFutureFunctionMarkers(decodeXmlText(formula))}`, styleIndex }
      continue
    }
    const type = readXmlAttribute(attributes, 't')
    if (type === 'inlineStr') {
      const text = [...body.matchAll(/<t(?:\s[^>]*)?>([\s\S]*?)<\/t>/g)]
        .map((textMatch) => decodeCellText(textMatch[1] ?? ''))
        .join('')
      cells[address] = { value: text, styleIndex }
      continue
    }
    const rawValue = body.match(/<v(?:\s[^>]*)?>([\s\S]*?)<\/v>/)?.[1]
    if (rawValue === undefined) {
      cells[address] = { value: null, styleIndex }
    } else if (type === 's') {
      const index = Number(rawValue)
      cells[address] = { value: sharedStrings[index] ?? '', styleIndex }
    } else if (type === 'b') {
      cells[address] = { value: rawValue === '1', styleIndex }
    } else if (type === 'str') {
      cells[address] = { value: decodeCellText(rawValue), styleIndex }
    } else {
      const numericValue = Number(rawValue)
      cells[address] = {
        value: Number.isFinite(numericValue) ? numericValue : decodeXmlText(rawValue),
        styleIndex,
      }
    }
  }
  return cells
}

/// Sheet-scoped `_xlnm.Print_Area` / `_xlnm.Print_Titles` keyed by
/// localSheetId (positional sheet order in workbook.xml). The reference keeps
/// its stored text; stripSheetPrefix trims the sheet part for display.
export function readSheetPrintNames(
  workbookXml: string,
): ReadonlyMap<number, { printArea?: string; printTitles?: string }> {
  const section = workbookXml.match(/<definedNames\b[^>]*>([\s\S]*?)<\/definedNames>/)
  const result = new Map<number, { printArea?: string; printTitles?: string }>()
  if (!section) return result
  for (const match of (section[1] ?? '').matchAll(/<definedName\b([^>]*?)>([\s\S]*?)<\/definedName>/g)) {
    const attributes = match[1] ?? ''
    const name = attributes.match(/\bname="(_xlnm\.Print_Area|_xlnm\.Print_Titles)"/)?.[1]
    const localSheetId = Number(attributes.match(/\blocalSheetId="(\d+)"/)?.[1] ?? Number.NaN)
    if (name === undefined || !Number.isInteger(localSheetId)) continue
    const entry = result.get(localSheetId) ?? {}
    const reference = (match[2] ?? '').trim()
    if (name === '_xlnm.Print_Area') entry.printArea = reference
    else entry.printTitles = reference
    result.set(localSheetId, entry)
  }
  return result
}

/// `'Sheet'!$A$1:$B$4,'Sheet'!$D$1:$E$4` → `A1:B4,D1:E4`：多打印区域、行+列打印
/// 标题的每个逗号分量各自带工作表前缀，须逐个去掉前缀与绝对引用标记。分量按
/// 引号外的逗号切分（带引号的工作表名可含逗号，'' 为转义引号）；单元格引用
/// 本身不含 "!"，取分量最后一个 "!" 之后（工作表名允许含 "!"）。
export function stripPrintReferenceSheetPrefix(reference: string): string {
  const components: string[] = []
  let current = ''
  let quoted = false
  for (const character of reference) {
    if (character === "'") quoted = !quoted
    if (character === ',' && !quoted) { components.push(current); current = ''; continue }
    current += character
  }
  components.push(current)
  return components.map(component => {
    const separator = component.lastIndexOf('!')
    return (separator === -1 ? component : component.slice(separator + 1)).replaceAll('$', '').trim()
  }).join(',')
}

function readHeaderFooter(worksheetXml: string): SheetHeaderFooterModel | undefined {
  const main = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
  const parser = new SaxesParser({ xmlns: true })
  const stack: { local: string; uri: string }[] = []
  const fields = new Set(['oddHeader', 'oddFooter', 'firstHeader', 'firstFooter', 'evenHeader', 'evenFooter'])
  let result: SheetHeaderFooterModel | undefined
  let capture: { key: keyof SheetHeaderFooterModel; text: string } | undefined
  parser.on('doctype', () => { throw new Error('页眉页脚不支持 DOCTYPE') })
  parser.on('opentag', tag => {
    const depth = stack.length
    if (depth === 1 && stack[0]?.local === 'worksheet' && stack[0].uri === main && tag.uri === main && tag.local === 'headerFooter') {
      if (result) throw new Error('页眉页脚结构不唯一')
      result = {}
      for (const key of ['differentFirst', 'differentOddEven', 'scaleWithDoc'] as const) {
        const raw = Object.values(tag.attributes).find(attr => !attr.uri && attr.local === key)?.value
        if (raw === '1' || raw === 'true') result[key] = true
        else if (raw === '0' || raw === 'false') result[key] = false
      }
    } else if (depth === 2 && result && stack[1]?.local === 'headerFooter' && stack[1].uri === main && tag.uri === main && fields.has(tag.local)) {
      capture = { key: tag.local as keyof SheetHeaderFooterModel, text: '' }
    }
    stack.push({ local: tag.local, uri: tag.uri })
  })
  const text = (value: string) => { if (capture && stack.length === 3) capture.text += value }
  parser.on('text', text)
  parser.on('cdata', text)
  parser.on('closetag', () => {
    if (capture && stack.length === 3) {
      // saxes 已解 XML 实体；重新转义再交 decodeCellText，避免二次解码 &amp;。
      Object.assign(result!, { [capture.key]: decodeCellText(escapeXmlText(capture.text)) })
      capture = undefined
    }
    stack.pop()
  })
  try { parser.write(worksheetXml).close() } catch { return undefined }
  return result
}

function parseGeometry(worksheetXml: string) {
  let defaultColumnWidthPx=columnWidthToPixels(8.43),defaultRowHeightPx=rowHeightToPixels(15),depth=0
  const formatParser=new SaxesParser({xmlns:true})
  formatParser.on('opentag',tag=>{
    depth++
    if(depth!==2||tag.uri!=='http://schemas.openxmlformats.org/spreadsheetml/2006/main'||tag.local!=='sheetFormatPr')return
    const attr=(name:string)=>Object.values(tag.attributes).find(a=>!a.uri&&a.local===name)?.value
    defaultColumnWidthPx=columnWidthToPixels(Number(attr('defaultColWidth')??8.43))
    defaultRowHeightPx=rowHeightToPixels(Number(attr('defaultRowHeight')??15))
  })
  formatParser.on('closetag',()=>{depth--});formatParser.write(worksheetXml).close()
  const { outlineSummaryBelow, outlineSummaryRight } = readOutlineSummary(worksheetXml)
  const dimension = worksheetXml.match(/<dimension\b[^>]*\bref="([^"]+)"/)?.[1] ?? null

  const merges = [...worksheetXml.matchAll(/<mergeCell\b[^>]*\bref="([^"]+)"/g)].map(
    (match) => match[1]!,
  )

  const columns: ColumnDef[] = [...worksheetXml.matchAll(/<col\b([^>]*?)\/>/g)].map((match) => {
    const attributes = match[1] ?? ''
    return {
      start: Number(readXmlAttribute(attributes, 'min') ?? 1),
      end: Number(readXmlAttribute(attributes, 'max') ?? 1),
      width:
        readXmlAttribute(attributes, 'width') === undefined
          ? undefined
          : Number(readXmlAttribute(attributes, 'width')),
      hidden: readXmlAttribute(attributes, 'hidden') === '1',
      ...readOutlineLine(attributes),
    }
  })

  const rows: RowDef[] = [...worksheetXml.matchAll(/<row\b([^>]*?)(?:\/>|>)/g)].map((match) => {
    const attributes = match[1] ?? ''
    return {
      row: Number(readXmlAttribute(attributes, 'r') ?? 0),
      height:
        readXmlAttribute(attributes, 'ht') === undefined
          ? undefined
          : Number(readXmlAttribute(attributes, 'ht')),
      hidden: readXmlAttribute(attributes, 'hidden') === '1',
      ...readOutlineLine(attributes),
    }
  })

  // printOptions：打印网格线/标题（OOXML 默认 false，仅显式 "1"/"true" 打开）。
  const printOptions = worksheetXml.match(/<(?:[\w.-]+:)?printOptions\b[^>]*?(?:\/>|>)/)?.[0]
  const printGridlines = printOptions !== undefined && /^(1|true)$/i.test(readXmlAttribute(printOptions, 'gridLines') ?? '')
  const printHeadings = printOptions !== undefined && /^(1|true)$/i.test(readXmlAttribute(printOptions, 'headings') ?? '')

  // pageMargins（英寸；OOXML 默认值对齐 CT_PageMargins）。
  const marginsElement = worksheetXml.match(/<(?:[\w.-]+:)?pageMargins\b[^>]*?(?:\/>|>)/)?.[0]
  const marginAttr = (name: string, fallback: number): number => {
    const raw = marginsElement === undefined ? undefined : readXmlAttribute(marginsElement, name)
    const value = raw === undefined ? Number.NaN : Number(raw)
    return Number.isFinite(value) ? value : fallback
  }
  const margins: SheetMarginsModel = {
    left: marginAttr('left', 0.7), right: marginAttr('right', 0.7),
    top: marginAttr('top', 0.75), bottom: marginAttr('bottom', 0.75),
    header: marginAttr('header', 0.3), footer: marginAttr('footer', 0.3),
  }

  // pageSetup + sheetPr@pageSetUpPr（fitToPage）。
  const pageSetupElement = worksheetXml.match(/<(?:[\w.-]+:)?pageSetup\b[^>]*?(?:\/>|>)/)?.[0]
  const pageSetupAttr = (name: string): number | undefined => {
    const raw = pageSetupElement === undefined ? undefined : readXmlAttribute(pageSetupElement, name)
    const value = raw === undefined ? Number.NaN : Number(raw)
    return Number.isFinite(value) ? value : undefined
  }
  const fitToPage = /<pageSetUpPr\b[^>]*\bfitToPage="(1|true)"/i.test(worksheetXml)
  const orientationRaw = pageSetupElement === undefined ? undefined : readXmlAttribute(pageSetupElement, 'orientation')
  const pageSetup: SheetPageSetupModel = {
    ...(orientationRaw === 'portrait' || orientationRaw === 'landscape' ? { orientation: orientationRaw } : {}),
    ...(pageSetupAttr('paperSize') !== undefined ? { paperSize: pageSetupAttr('paperSize') } : {}),
    ...(pageSetupAttr('scale') !== undefined ? { scale: pageSetupAttr('scale') } : {}),
    ...(pageSetupAttr('fitToWidth') !== undefined ? { fitToWidth: pageSetupAttr('fitToWidth') } : {}),
    ...(pageSetupAttr('fitToHeight') !== undefined ? { fitToHeight: pageSetupAttr('fitToHeight') } : {}),
    ...(fitToPage ? { fitToPage: true } : {}),
  }

  const pane = worksheetXml.match(/<pane\b([^>]*?)\/?>/)?.[1]
  // ECMA-376 §18.3.1.66：pane@state 缺省为 split；只有 frozen/frozenSplit 的 x/ySplit 是行列数。
  const paneState = pane === undefined ? undefined : readXmlAttribute(pane, 'state') ?? 'split'
  const paneCount = (name: string) => {
    const value = Number(readXmlAttribute(pane ?? '', name) ?? 0)
    return Number.isInteger(value) && value >= 0 ? value : 0
  }
  const freeze =
    pane === undefined || (paneState !== 'frozen' && paneState !== 'frozenSplit')
      ? null
      : { frozenRows: paneCount('ySplit'), frozenColumns: paneCount('xSplit') }
  const splitTwips = (name: string) => {
    const value = Number(readXmlAttribute(pane ?? '', name) ?? 0)
    return Number.isFinite(value) && value > 0 ? value : 0
  }
  const splitTopLeft = pane === undefined ? undefined : readXmlAttribute(pane, 'topLeftCell')
  const splitPane = pane !== undefined && paneState === 'split' && (splitTwips('xSplit') > 0 || splitTwips('ySplit') > 0)
    ? { xSplitTwips: splitTwips('xSplit'), ySplitTwips: splitTwips('ySplit'), ...(splitTopLeft ? { topLeftCell: splitTopLeft } : {}) }
    : undefined
  // OOXML 默认显示网格线；仅显式 showGridLines="0" 才是隐藏。
  const sheetView = worksheetXml.match(/<(?:[\w.-]+:)?sheetView\b[^>]*?(?:\/>|>[\s\S]*?<\/(?:[\w.-]+:)?sheetView>)/)?.[0]
  const showGridlines = sheetView && readXmlAttribute(sheetView, 'showGridLines') === '0' ? false : true
  const showHeadings = !sheetView || !['0', 'false'].includes(readXmlAttribute(sheetView, 'showRowColHeaders') ?? '')
  const rightToLeft = !!sheetView && ['1', 'true'].includes(readXmlAttribute(sheetView, 'rightToLeft') ?? '')
  const showFormulas = !!sheetView && ['1', 'true'].includes(readXmlAttribute(sheetView, 'showFormulas') ?? '')
  // 常规视图缩放百分比（OOXML 默认 100）。
  const zoomScaleRaw = sheetView ? readXmlAttribute(sheetView, 'zoomScale') : undefined
  const zoomScale = zoomScaleRaw !== undefined && Number.isFinite(Number(zoomScaleRaw)) ? Math.min(Math.max(Number(zoomScaleRaw), 10), 400) : 100

  // 手动分页符：brk@id 为 0-based 行/列号；man 缺省为 true（Excel 缓存的
  // 自动分页带 man="0"，排除）。brk 归属其父 rowBreaks/colBreaks 元素。
  const manualBreaks = (tag: 'rowBreaks' | 'colBreaks'): number[] => {
    const section = worksheetXml.match(
      new RegExp(`<(?:[\\w.-]+:)?${tag}\\b[^>]*?(?:/>|>([\\s\\S]*?)</(?:[\\w.-]+:)?${tag}>)`),
    )
    const body = section?.[1]
    if (body === undefined) return []
    return [...body.matchAll(/<brk\b([^>]*?)\/?>/g)]
      .map((match) => match[1]!)
      .filter((attributes) => /^(1|true)$/i.test(readXmlAttribute(attributes, 'man') ?? '1'))
      .map((attributes) => Number(readXmlAttribute(attributes, 'id') ?? Number.NaN))
      .filter((id) => Number.isInteger(id) && id > 0)
      .sort((a, b) => a - b)
  }

  return {
    dimension, merges, columns, rows, defaultColumnWidthPx, defaultRowHeightPx, outlineSummaryBelow, outlineSummaryRight, freeze, ...(splitPane ? { splitPane } : {}), showGridlines, showHeadings, rightToLeft, zoomScale, ...(showFormulas ? { showFormulas } : {}),
    margins, printGridlines, printHeadings, pageSetup,
    rowBreaks: manualBreaks('rowBreaks'), colBreaks: manualBreaks('colBreaks'),
  }
}

export async function readWorkbook(bytes: Uint8Array): Promise<WorkbookModel> {
  const source = await createBufferEntrySource(bytes)
  const workbookXml = await source.readText('xl/workbook.xml')
  const sharedStrings = await readSharedStrings(source)
  // Fixed-source Rust read_styles uses one default CellStyle when the optional
  // part is absent. This read-only projection supplies no invented font/color
  // and never adds a stylesheet to the original package.
  const stylesXml = await source.has('xl/styles.xml') ? await source.readText('xl/styles.xml')
    : '<styleSheet><fonts count="1"><font/></fonts><fills count="1"><fill/></fills><borders count="1"><border/></borders><cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellXfs></styleSheet>'
  const styles = parseStylesheet(stylesXml)
  const parentStyles = stylesXml.match(/<cellStyleXfs\b[^>]*>([\s\S]*?)<\/cellStyleXfs>/)?.[1] ?? ''
  const rotatedParent = [...parentStyles.matchAll(/<alignment\b[^>]*\btextRotation=["']([^"']+)["']/g)].some(match => Number(match[1]) !== 0)
  const defaultRotation = styles.cellXfs[0]?.alignment?.textRotation ?? 0
  const disabledAlignment = extractElements(sectionInner(stylesXml, 'cellXfs') ?? '', 'xf').some(xf => ['0', 'false'].includes(readXmlAttribute(xf, 'applyAlignment') ?? '') && /<alignment\b[^>]*\btextRotation=/.test(xf))
  const indentedParent = [...parentStyles.matchAll(/<alignment\b[^>]*\bindent=["']([^"']+)["']/g)].some(match => Number(match[1]) !== 0)
  const defaultIndent = styles.cellXfs[0]?.alignment?.indent ?? 0
  const disabledIndentAlignment = extractElements(sectionInner(stylesXml, 'cellXfs') ?? '', 'xf').some(xf => ['0', 'false'].includes(readXmlAttribute(xf, 'applyAlignment') ?? '') && /<alignment\b[^>]*\bindent=/.test(xf))
  const themePalette = (await source.has('xl/theme/theme1.xml'))
    ? parseThemePalette(await source.readText('xl/theme/theme1.xml'))
    : undefined

  const { readCustomTableStyles } = await import('./table-style-read')
  const customTableStyles = readCustomTableStyles(stylesXml, themePalette)
  const sheets: SheetModel[] = []
  const sheetPrintNames = readSheetPrintNames(workbookXml)
  for (const [sheetIndex, element] of parseSheetElements(workbookXml).entries()) {
    if (element.relationshipId === undefined) continue
    const path = await resolveWorksheetPath(source, element.relationshipId)
    const worksheetXml = await source.readText(path)
    const geometry = parseGeometry(worksheetXml)
    const headerFooter = readHeaderFooter(worksheetXml)
    const printNames = sheetPrintNames.get(sheetIndex)
    const inheritedSheetStyle = [...worksheetXml.matchAll(/<(row|col)\b([^>]*)>/g)].some(match => readXmlAttribute(match[2]!, match[1] === 'row' ? 's' : 'style') !== undefined)
    const rotationReadOnly = inheritedSheetStyle || defaultRotation !== 0 || rotatedParent || disabledAlignment
    const indentReadOnly = inheritedSheetStyle || defaultIndent !== 0 || indentedParent || disabledIndentAlignment
    const conditionalFormats = readCfRules(worksheetXml, element.name)
    const { sourceXml: _cfSourceXml, ...conditionalFormatting } = readConditionalFormattingSnapshot(worksheetXml, stylesXml, themePalette)
    const sparklines = readSparklines(worksheetXml)
    const charts = await readCharts(bytes, path)
    const { notes, sourceIdentity, readOnlyReason } = await readSheetNotes(source, path)
    const filter = readSheetFilter(worksheetXml)
    const dataValidations = readDataValidations(worksheetXml)
    const tables = await readSheetTables(source, path, worksheetXml)
    for (const table of tables.tables) {
      const customStyle = table.style?.name ? customTableStyles.get(table.style.name) : undefined
      if (customStyle) table.customStyle = customStyle
    }
    const protection = readSheetProtection(worksheetXml)
    sheets.push({
      threads: await readSheetThreads(source, path),
      notes: { notes, sourceIdentity, ...(readOnlyReason ? { readOnlyReason } : {}) },
      name: element.name,
      ...(element.hidden ? { hidden: true } : {}),
      path,
      cells: parseWorksheetCells(worksheetXml, sharedStrings),
      ...geometry,
      ...(headerFooter ? { headerFooter } : {}),
      ...(printNames?.printArea !== undefined
        ? { printArea: stripPrintReferenceSheetPrefix(printNames.printArea) }
        : {}),
      ...(printNames?.printTitles !== undefined
        ? { printTitles: stripPrintReferenceSheetPrefix(printNames.printTitles) }
        : {}),
      ...(rotationReadOnly ? { rotationReadOnlyReason: 'xlsx_rotation_inherited_style_unsupported' } : {}),
      ...(indentReadOnly ? { indentReadOnlyReason: 'xlsx_indent_inherited_style_unsupported' } : {}),
      ...(conditionalFormats.length > 0 ? { conditionalFormats } : {}),
      conditionalFormatting,
      ...(sparklines.length > 0 ? { sparklines } : {}),
      ...(charts.length > 0 ? { charts } : {}),
      ...(filter ? { filter } : {}),
      dataValidations,
      ...tables,
      ...(protection ? { protection } : {}),
    })
  }
  if (sheets.length === 0) throw new Error('工作簿没有可读取的工作表。')
  const definedNames = readDefinedNames(workbookXml)
  const workbookProtection = readWorkbookProtection(workbookXml)
  return {
    sheets,
    styles,
    themePalette,
    ...(definedNames.length > 0 ? { definedNames } : {}),
    ...(workbookProtection ? { workbookProtection } : {}),
  }
}
