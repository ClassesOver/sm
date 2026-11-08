/// Workbook importer: bytes → editor model (sheets, cells with style
/// indexes, geometry, styles, theme palette). Values/formulas follow the
/// genoffice reader; styles and geometry are read here because the web app
/// has no sidecar to resolve them.

import { readSheetNotes, type SheetNotesModel } from './note-read'
import { readSheetFilter, type SheetFilterModel } from './filter-read'
import { parseStylesheet, parseThemePalette, type Stylesheet } from './style-read'
import { readCfRules, type CfReadableRule } from './cf-read'
import { readDefinedNames } from './defined-names'
import { readSparklines, type SparklineSpec } from './sparklines'
import { readCharts, type ChartReadSpec } from './chart-read'
import { createBufferEntrySource, type EntrySource } from './zip'
import { decodeCellText, decodeXmlText, escapeRegExp, readXmlAttribute, extractElements, sectionInner } from './xml'

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
}

export interface RowDef {
  row: number
  height: number | undefined
  hidden: boolean
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

export interface SheetModel {
  name: string
  /// worksheet part path (xl/worksheets/sheetN.xml)
  path: string
  cells: Readonly<Record<string, ModelCell>>
  /// mergeCell refs, e.g. "A1:B2"
  merges: readonly string[]
  columns: readonly ColumnDef[]
  rows: readonly RowDef[]
  freeze: { frozenRows: number; frozenColumns: number } | null
  /// sheetView showGridLines（OOXML 默认 true；写回经 applyPageSetups）。
  showGridlines: boolean
  /// 常规视图缩放百分比（10-400，OOXML 默认 100；写回经 applyPageSetups）。
  zoomScale: number
  /// 页面设置（pageSetup 元素 + sheetPr@pageSetUpPr；写回经 applyPageSetups）。
  pageSetup?: SheetPageSetupModel
  /// 页边距（英寸；OOXML 默认 0.7/0.7/0.75/0.75/0.3/0.3；写回经 applyPageSetups 预设）。
  margins?: SheetMarginsModel
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
  /// self-colored conditional formats (dataBar / colorScale) read back for
  /// grid rendering; cellIs/iconSet are write-only boundaries
  conditionalFormats?: ReadonlyArray<CfReadableRule>
  /// sparklines (x14) read back for grid rendering
  sparklines?: ReadonlyArray<SparklineSpec>
  /// anchored charts read back for grid rendering (column/bar/line/pie v1)
  charts?: ReadonlyArray<ChartReadSpec>
  notes?: SheetNotesModel
  /// worksheet-level autoFilter: range + per-column criteria (values/blank/
  /// customs/dateGroups); readOnlyReason marks structures (color/icon/top10/
  /// dynamic) the write path refuses
  filter?: SheetFilterModel
}

export interface WorkbookModel {
  sheets: readonly SheetModel[]
  styles: Stylesheet
  /// theme index order palette for resolving theme colors; undefined → defaults
  themePalette: readonly string[] | undefined
  /// workbook-level defined names (global scope; sheet-scoped excluded)
  definedNames?: ReadonlyArray<{ name: string; refersTo: string }>
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
      cells[address] = { value: null, formula: `=${decodeXmlText(formula)}`, styleIndex }
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

function parseGeometry(worksheetXml: string) {
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
  const freeze =
    pane === undefined
      ? null
      : {
          frozenRows: Number(readXmlAttribute(pane, 'ySplit') ?? 0),
          frozenColumns: Number(readXmlAttribute(pane, 'xSplit') ?? 0),
        }
  // OOXML 默认显示网格线；仅显式 showGridLines="0" 才是隐藏。
  const sheetView = worksheetXml.match(/<(?:[\w.-]+:)?sheetView\b[^>]*?(?:\/>|>[\s\S]*?<\/(?:[\w.-]+:)?sheetView>)/)?.[0]
  const showGridlines = sheetView && readXmlAttribute(sheetView, 'showGridLines') === '0' ? false : true
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
    dimension, merges, columns, rows, freeze, showGridlines, zoomScale,
    margins, printGridlines, printHeadings, pageSetup,
    rowBreaks: manualBreaks('rowBreaks'), colBreaks: manualBreaks('colBreaks'),
  }
}

export async function readWorkbook(bytes: Uint8Array): Promise<WorkbookModel> {
  const source = await createBufferEntrySource(bytes)
  const workbookXml = await source.readText('xl/workbook.xml')
  const sharedStrings = await readSharedStrings(source)
  const stylesXml = await source.readText('xl/styles.xml')
  const styles = parseStylesheet(stylesXml)
  const parentStyles = stylesXml.match(/<cellStyleXfs\b[^>]*>([\s\S]*?)<\/cellStyleXfs>/)?.[1] ?? ''
  const rotatedParent = [...parentStyles.matchAll(/<alignment\b[^>]*\btextRotation=["']([^"']+)["']/g)].some(match => Number(match[1]) !== 0)
  const defaultRotation = styles.cellXfs[0]?.alignment?.textRotation ?? 0
  const disabledAlignment = extractElements(sectionInner(stylesXml, 'cellXfs') ?? '', 'xf').some(xf => ['0', 'false'].includes(readXmlAttribute(xf, 'applyAlignment') ?? '') && /<alignment\b[^>]*\btextRotation=/.test(xf))
  const themePalette = (await source.has('xl/theme/theme1.xml'))
    ? parseThemePalette(await source.readText('xl/theme/theme1.xml'))
    : undefined

  const sheets: SheetModel[] = []
  const sheetPrintNames = readSheetPrintNames(workbookXml)
  for (const [sheetIndex, element] of parseSheetElements(workbookXml).entries()) {
    if (element.relationshipId === undefined) continue
    const path = await resolveWorksheetPath(source, element.relationshipId)
    const worksheetXml = await source.readText(path)
    const geometry = parseGeometry(worksheetXml)
    const printNames = sheetPrintNames.get(sheetIndex)
    const inheritedSheetStyle = [...worksheetXml.matchAll(/<(row|col)\b([^>]*)>/g)].some(match => readXmlAttribute(match[2]!, match[1] === 'row' ? 's' : 'style') !== undefined)
    const rotationReadOnly = inheritedSheetStyle || defaultRotation !== 0 || rotatedParent || disabledAlignment
    const conditionalFormats = readCfRules(worksheetXml, element.name)
    const sparklines = readSparklines(worksheetXml)
    const charts = await readCharts(bytes, path)
    const { notes, sourceIdentity, readOnlyReason } = await readSheetNotes(source, path)
    const filter = readSheetFilter(worksheetXml)
    sheets.push({
      notes: { notes, sourceIdentity, ...(readOnlyReason ? { readOnlyReason } : {}) },
      name: element.name,
      path,
      cells: parseWorksheetCells(worksheetXml, sharedStrings),
      ...geometry,
      ...(printNames?.printArea !== undefined
        ? { printArea: stripPrintReferenceSheetPrefix(printNames.printArea) }
        : {}),
      ...(printNames?.printTitles !== undefined
        ? { printTitles: stripPrintReferenceSheetPrefix(printNames.printTitles) }
        : {}),
      ...(rotationReadOnly ? { rotationReadOnlyReason: 'xlsx_rotation_inherited_style_unsupported' } : {}),
      ...(conditionalFormats.length > 0 ? { conditionalFormats } : {}),
      ...(sparklines.length > 0 ? { sparklines } : {}),
      ...(charts.length > 0 ? { charts } : {}),
      ...(filter ? { filter } : {}),
    })
  }
  if (sheets.length === 0) throw new Error('工作簿没有可读取的工作表。')
  const definedNames = readDefinedNames(workbookXml)
  return {
    sheets,
    styles,
    themePalette,
    ...(definedNames.length > 0 ? { definedNames } : {}),
  }
}
