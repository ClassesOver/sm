/// Workbook importer: bytes → editor model (sheets, cells with style
/// indexes, geometry, styles, theme palette). Values/formulas follow the
/// genoffice reader; styles and geometry are read here because the web app
/// has no sidecar to resolve them.

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

  const pane = worksheetXml.match(/<pane\b([^>]*?)\/?>/)?.[1]
  const freeze =
    pane === undefined
      ? null
      : {
          frozenRows: Number(readXmlAttribute(pane, 'ySplit') ?? 0),
          frozenColumns: Number(readXmlAttribute(pane, 'xSplit') ?? 0),
        }

  return { dimension, merges, columns, rows, freeze }
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
  for (const element of parseSheetElements(workbookXml)) {
    if (element.relationshipId === undefined) continue
    const path = await resolveWorksheetPath(source, element.relationshipId)
    const worksheetXml = await source.readText(path)
    const geometry = parseGeometry(worksheetXml)
    const inheritedSheetStyle = [...worksheetXml.matchAll(/<(row|col)\b([^>]*)>/g)].some(match => readXmlAttribute(match[2]!, match[1] === 'row' ? 's' : 'style') !== undefined)
    const rotationReadOnly = inheritedSheetStyle || defaultRotation !== 0 || rotatedParent || disabledAlignment
    const conditionalFormats = readCfRules(worksheetXml, element.name)
    const sparklines = readSparklines(worksheetXml)
    const charts = await readCharts(bytes, path)
    sheets.push({
      name: element.name,
      path,
      cells: parseWorksheetCells(worksheetXml, sharedStrings),
      ...geometry,
      ...(rotationReadOnly ? { rotationReadOnlyReason: 'xlsx_rotation_inherited_style_unsupported' } : {}),
      ...(conditionalFormats.length > 0 ? { conditionalFormats } : {}),
      ...(sparklines.length > 0 ? { sparklines } : {}),
      ...(charts.length > 0 ? { charts } : {}),
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
