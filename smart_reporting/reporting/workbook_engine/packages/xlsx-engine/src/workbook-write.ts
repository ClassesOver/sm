/// Save path: cell value/formula/style edits patched surgically into the
/// original package bytes. Ported from genoffice's applyCellEditsToXlsx
/// core (values + styles only — structural/chart/sheet-plan operations stay
/// desktop features for now).

import type { WorkbookRichRun, WorkbookStyleEdit } from './edit-schemas'
import { sha256Hex } from './sha256'
import { spillsDynamicArray, withFutureFunctionMarkers } from './future-functions'
import { StylesheetEditor } from './styles-write'
import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
import { assemblePackage, createBufferEntrySource, type EntrySource, type MutationPlan } from './zip'
import { escapeXmlAttribute, escapeCellText, escapeXmlText, readXmlAttribute } from './xml'

/// One cell rewrite. `writeValue: false` = style-only edit.
export interface CellEdit {
  readonly sheetName: string
  readonly row: number
  readonly column: number
  readonly writeValue: boolean
  readonly cell: { value: string | number | boolean | null; formula?: string | undefined }
  readonly style?: WorkbookStyleEdit | undefined
  readonly rich?: readonly WorkbookRichRun[] | undefined
  /// Reset the cell to the default style (xf 0) before applying `style`.
  readonly styleReset?: boolean | undefined
}

function hasStyleDelta(style: WorkbookStyleEdit | undefined): boolean {
  return style !== undefined && Object.keys(style).length > 0
}

// ── cell serialization (ported from genoffice serializeStyledCell) ──────

function formulaXml(address: string, formula: string): string {
  const text = escapeXmlText(withFutureFunctionMarkers(formula))
  return spillsDynamicArray(formula)
    ? `<f t="array" ref="${address}">${text}</f>`
    : `<f>${text}</f>`
}

function serializeStyledCell(
  address: string,
  cell: CellEdit['cell'],
  styleIndex: string | undefined,
  rich?: readonly WorkbookRichRun[],
): string {
  const style = styleIndex === undefined ? '' : ` s="${styleIndex}"`
  if (cell.formula) {
    return `<c r="${address}"${style}>${formulaXml(address, cell.formula.replace(/^=/, ''))}</c>`
  }
  if (cell.value === null) {
    // A cleared cell keeps its formatting only if it keeps a style index.
    return styleIndex === undefined ? '' : `<c r="${address}"${style}/>`
  }
  if (typeof cell.value === 'string') {
    if (rich && rich.length > 0) {
      const runs = rich
        .map(
          (run) =>
            `<r>${serializeRunProperties(run)}<t xml:space="preserve">${escapeCellText(run.text)}</t></r>`,
        )
        .join('')
      return `<c r="${address}"${style} t="inlineStr"><is>${runs}</is></c>`
    }
    return `<c r="${address}"${style} t="inlineStr"><is><t xml:space="preserve">${escapeCellText(cell.value)}</t></is></c>`
  }
  if (typeof cell.value === 'boolean') {
    return `<c r="${address}"${style} t="b"><v>${cell.value ? 1 : 0}</v></c>`
  }
  return `<c r="${address}"${style}><v>${cell.value}</v></c>`
}

/// `<rPr>` for one inline-string run; empty string when the run is plain.
function serializeRunProperties(run: WorkbookRichRun): string {
  const parts: string[] = []
  if (run.bold) parts.push('<b/>')
  if (run.italic) parts.push('<i/>')
  if (run.strikethrough) parts.push('<strike/>')
  if (run.underline) parts.push('<u/>')
  if (run.size !== undefined) parts.push(`<sz val="${run.size}"/>`)
  if (run.color !== undefined) {
    const hex = run.color.replace(/^#/, '').toUpperCase()
    if (/^[0-9A-F]{6}$/.test(hex)) parts.push(`<color rgb="FF${hex}"/>`)
  }
  if (run.family !== undefined) {
    parts.push(`<rFont val="${escapeXmlAttribute(run.family)}"/>`)
  }
  if (run.vertAlign !== undefined) parts.push(`<vertAlign val="${run.vertAlign}"/>`)
  return parts.length === 0 ? '' : `<rPr>${parts.join('')}</rPr>`
}

// ── cell patching (ported from genoffice patchCell / insertMissingCell) ──

function parseA1Column(address: string): number {
  const letters = address.match(/^[A-Z]{1,3}/)?.[0]
  if (!letters) throw new Error(`Invalid cell address: ${address}`)
  let column = 0
  for (const character of letters) {
    column = column * 26 + character.charCodeAt(0) - 64
  }
  return column - 1
}

function insertCellInColumnOrder(rowBody: string, cellXml: string, targetColumn: number): string {
  const siblingPattern = /<c\b[^>]*?\br="([A-Z]{1,3})[1-9][0-9]*"/g
  for (const match of rowBody.matchAll(siblingPattern)) {
    const column = parseA1Column(`${match[1]}1`)
    if (column > targetColumn) {
      const index = match.index ?? 0
      return rowBody.slice(0, index) + cellXml + rowBody.slice(index)
    }
  }
  return rowBody + cellXml
}

function insertRowInOrder(worksheetXml: string, rowNumber: number, cellXml: string): string {
  const newRow = `<row r="${rowNumber}">${cellXml}</row>`
  const rowStartPattern = /<row\b[^>]*?\br="([1-9][0-9]*)"/g
  for (const match of worksheetXml.matchAll(rowStartPattern)) {
    if (Number(match[1]) > rowNumber) {
      const index = match.index ?? 0
      return worksheetXml.slice(0, index) + newRow + worksheetXml.slice(index)
    }
  }
  if (worksheetXml.includes('</sheetData>')) {
    return worksheetXml.replace('</sheetData>', () => `${newRow}</sheetData>`)
  }
  const emptySheetData = /<sheetData\s*\/>/
  if (emptySheetData.test(worksheetXml)) {
    return worksheetXml.replace(emptySheetData, () => `<sheetData>${newRow}</sheetData>`)
  }
  throw new Error('Worksheet has no sheetData element.')
}

function insertMissingCell(worksheetXml: string, address: string, cellXml: string): string {
  const rowNumber = Number(address.match(/[1-9][0-9]*$/)?.[0])
  if (!Number.isFinite(rowNumber)) throw new Error(`Invalid cell address: ${address}`)
  const targetColumn = parseA1Column(address)
  const rowMatch = worksheetXml.match(
    new RegExp(`<row\\b([^>]*?\\br="${rowNumber}"[^>]*?)(/>|>([\\s\\S]*?)</row>)`),
  )
  if (rowMatch) {
    const attributes = rowMatch[1] ?? ''
    const body = rowMatch[2] === '/>' ? '' : (rowMatch[3] ?? '')
    return worksheetXml.replace(
      rowMatch[0],
      () => `<row${attributes}>${insertCellInColumnOrder(body, cellXml, targetColumn)}</row>`,
    )
  }
  return insertRowInOrder(worksheetXml, rowNumber, cellXml)
}

function readCellStyleIndex(worksheetXml: string, address: string): number | undefined {
  const match = worksheetXml.match(new RegExp(`<c\\b([^>]*)\\br="${address}"([^>]*?)[/>]`))
  if (!match) return undefined
  const index = readXmlAttribute(`${match[1] ?? ''} ${match[2] ?? ''}`, 's')
  return index === undefined ? undefined : Number(index)
}

/// Rewrites one cell in worksheet XML. The original cell's style index is
/// kept (or replaced by styleOverride) so edits don't strip formatting, and
/// missing cells or rows are inserted in ascending order (Excel expects
/// sorted sheetData).
function patchCellKeepingStyle(
  worksheetXml: string,
  address: string,
  cell: CellEdit['cell'],
  styleOverride?: number,
  rich?: readonly WorkbookRichRun[],
): string {
  const cellMatch = worksheetXml.match(
    new RegExp(`<c\\b([^>]*)\\br="${address}"([^>]*?)(?:/>|>[\\s\\S]*?</c>)`),
  )
  const styleIndex =
    styleOverride !== undefined
      ? String(styleOverride)
      : cellMatch
        ? readXmlAttribute(`${cellMatch[1] ?? ''} ${cellMatch[2] ?? ''}`, 's')
        : undefined
  const replacement = serializeStyledCell(address, cell, styleIndex, rich)
  // Function replacements throughout: user text can contain `$1`/`$&`, which
  // string replacements would expand as backreferences and corrupt the XML.
  if (cellMatch) return worksheetXml.replace(cellMatch[0], () => replacement)
  if (replacement === '') return worksheetXml
  return insertMissingCell(worksheetXml, address, replacement)
}

/// Sets only the style index of a cell, leaving its stored content (value,
/// type, formula) byte-for-byte untouched. Missing cells become empty styled
/// cells so formatting applies to blanks too.
function patchCellStyleOnly(
  worksheetXml: string,
  address: string,
  styleIndex: number | undefined,
): string {
  if (styleIndex === undefined) return worksheetXml
  const cellMatch = worksheetXml.match(new RegExp(`(<c\\b[^>]*?\\br="${address}"[^>]*?)(\\s*/>|>)`))
  if (cellMatch) {
    const opening = cellMatch[1] ?? ''
    const patched = /\bs="[^"]*"/.test(opening)
      ? opening.replace(/\bs="[^"]*"/, () => `s="${styleIndex}"`)
      : opening.replace(`r="${address}"`, () => `r="${address}" s="${styleIndex}"`)
    return worksheetXml.replace(cellMatch[0], () => `${patched}${cellMatch[2] ?? ''}`)
  }
  return insertMissingCell(worksheetXml, address, `<c r="${address}" s="${styleIndex}"/>`)
}

function ensureFullCalcOnLoad(workbookXml: string): string {
  if (/<calcPr\b[^>]*\bfullCalcOnLoad="1"/.test(workbookXml)) return workbookXml
  if (/<calcPr\b/.test(workbookXml)) {
    return workbookXml.replace(
      /<calcPr\b([^>]*?)(\/?>)/,
      (_full, attributes: string, close: string) => {
        const cleaned = attributes.replace(/\s*fullCalcOnLoad="[^"]*"/, '')
        return `<calcPr${cleaned} fullCalcOnLoad="1"${close}`
      },
    )
  }
  // Schema order places calcPr after definedNames (or after sheets).
  const anchor = workbookXml.includes('</definedNames>') ? '</definedNames>' : '</sheets>'
  if (!workbookXml.includes(anchor)) return workbookXml
  return workbookXml.replace(anchor, `${anchor}<calcPr fullCalcOnLoad="1"/>`)
}

const MINIMAL_STYLESHEET_XML =
  '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
  '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
  '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>' +
  '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>' +
  '<borders count="1"><border/></borders>' +
  '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>' +
  '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>' +
  '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>' +
  '</styleSheet>'

const STYLES_REL_TYPE =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles'
const STYLES_CONTENT_TYPE =
  'application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml'

function nextRelationshipId(relsXml: string): number {
  let max = 0
  for (const match of relsXml.matchAll(/\bId="rId([0-9]+)"/g)) {
    max = Math.max(max, Number(match[1]))
  }
  return max + 1
}

async function addDefaultStylesheet(
  replaced: Map<string, string>,
  addedEntries: string[],
  source: EntrySource,
  stylesXml: string,
): Promise<void> {
  replaced.set('xl/styles.xml', stylesXml)
  addedEntries.push('xl/styles.xml')
  const relsPath = 'xl/_rels/workbook.xml.rels'
  const relsXml = await source.readText(relsPath)
  if (!relsXml.includes(STYLES_REL_TYPE)) {
    const relId = `rId${nextRelationshipId(relsXml)}`
    replaced.set(
      relsPath,
      relsXml.replace('</Relationships>', () => {
        return `<Relationship Id="${relId}" Type="${STYLES_REL_TYPE}" Target="styles.xml"/></Relationships>`
      }),
    )
    addedEntries.push(relsPath)
  }
  const contentTypesPath = '[Content_Types].xml'
  const contentTypes = await source.readText(contentTypesPath)
  if (!contentTypes.includes(STYLES_CONTENT_TYPE)) {
    replaced.set(
      contentTypesPath,
      contentTypes.replace('</Types>', () => {
        return `<Override PartName="/xl/styles.xml" ContentType="${STYLES_CONTENT_TYPE}"/></Types>`
      }),
    )
    addedEntries.push(contentTypesPath)
  }
}

async function findWorksheetPath(
  source: EntrySource,
  workbookXml: string,
  sheetName: string,
): Promise<string> {
  const element = parseSheetElements(workbookXml).find((candidate) => candidate.name === sheetName)
  if (element?.relationshipId === undefined) {
    throw new Error(`Sheet "${sheetName}" was not found in workbook.xml.`)
  }
  return resolveWorksheetPath(source, element.relationshipId)
}

function columnLabelOf(column: number): string {
  if (!Number.isInteger(column) || column < 0) {
    throw new RangeError(`Invalid column index: ${column}`)
  }
  let label = ''
  let remaining = column + 1
  while (remaining > 0) {
    remaining -= 1
    label = String.fromCharCode(65 + (remaining % 26)) + label
    remaining = Math.floor(remaining / 26)
  }
  return label
}

/// Applies edits onto the source package: worksheet cells are patched in
/// place; style edits resolve through the copy-on-write StylesheetEditor.
/// Returns the new package bytes (untouched entries keep their content).
export async function applyCellEdits(
  sourceBytes: Uint8Array,
  edits: readonly CellEdit[],
): Promise<Uint8Array> {
  if (edits.length === 0) return sourceBytes
  // NaN/Infinity serialize as invalid OOXML numbers (<v>NaN</v>) — Excel
  // treats the whole file as corrupt. Fail closed instead of shipping it.
  for (const edit of edits) {
    if (edit.writeValue && typeof edit.cell.value === 'number' && !Number.isFinite(edit.cell.value)) {
      throw new Error(
        `单元格值 ${String(edit.cell.value)} 不是有限数值，无法写入（会生成 Excel 无法读取的文件）。`,
      )
    }
  }
  const source = await createBufferEntrySource(sourceBytes)

  const hasStylesPart = await source.has('xl/styles.xml')
  let stylesXml = hasStylesPart ? await source.readText('xl/styles.xml') : MINIMAL_STYLESHEET_XML
  const stylesheet = new StylesheetEditor(stylesXml)

  // sheet name → worksheet XML, patched through the overlay
  const worksheetXmlByName = new Map<string, string>()
  const worksheetPathByName = new Map<string, string>()
  const workbookXml = await source.readText('xl/workbook.xml')
  let workbookPatched = workbookXml
  const touchedEntries: string[] = []
  let sawFormula = false

  for (const edit of edits) {
    let worksheetXml = worksheetXmlByName.get(edit.sheetName)
    if (worksheetXml === undefined) {
      const path =
        worksheetPathByName.get(edit.sheetName) ??
        (await findWorksheetPath(source, workbookXml, edit.sheetName))
      worksheetPathByName.set(edit.sheetName, path)
      worksheetXml = await source.readText(path)
    }
    const address = `${columnLabelOf(edit.column)}${edit.row + 1}`
    const wantsStyle = edit.styleReset === true || hasStyleDelta(edit.style)
    let styleOverride: number | undefined
    if (wantsStyle) {
      const baseIndex =
        edit.styleReset === true ? 0 : (readCellStyleIndex(worksheetXml, address) ?? 0)
      styleOverride =
        edit.style === undefined ? baseIndex : stylesheet.resolveStyle(baseIndex, edit.style)
    }
    if (edit.writeValue) {
      sawFormula = sawFormula || edit.cell.formula !== undefined
      worksheetXml = patchCellKeepingStyle(worksheetXml, address, edit.cell, styleOverride, edit.rich)
    } else if (styleOverride !== undefined) {
      worksheetXml = patchCellStyleOnly(worksheetXml, address, styleOverride)
    }
    worksheetXmlByName.set(edit.sheetName, worksheetXml)
  }

  const replaced = new Map<string, string>()
  const added = new Map<string, string>()
  const addedEntries: string[] = []
  for (const [sheetName, xml] of worksheetXmlByName) {
    const path = worksheetPathByName.get(sheetName)!
    replaced.set(path, xml)
    touchedEntries.push(path)
  }
  if (stylesheet.changed) {
    stylesXml = stylesheet.serialize()
    if (hasStylesPart) {
      replaced.set('xl/styles.xml', stylesXml)
      touchedEntries.push('xl/styles.xml')
    } else {
      await addDefaultStylesheet(replaced, addedEntries, source, stylesXml)
    }
  }
  if (sawFormula) {
    workbookPatched = ensureFullCalcOnLoad(workbookPatched)
    if (workbookPatched !== workbookXml) {
      replaced.set('xl/workbook.xml', workbookPatched)
      touchedEntries.push('xl/workbook.xml')
    }
  }

  const plan: MutationPlan = {
    replaced,
    added,
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries,
    touchedEntries,
  }
  const mutation = await assemblePackage(sourceBytes, plan)
  return mutation.buffer
}

/// Whole-file SHA-256 (identity gate for in-place saves: the bytes opened
/// must still be the bytes being replaced).
export function packageSha256(bytes: Uint8Array): string {
  return sha256Hex(bytes)
}

/// Rewrites one cell to plain text, keeping its style index intact (table
/// header reconciliation after column inserts). Ported from genoffice's
/// writeHeaderCellText.
export function setWorksheetCellText(worksheetXml: string, address: string, text: string): string {
  const match = worksheetXml.match(
    new RegExp(`<c\\b([^>]*)\\br="${address}"([^>]*?)(?:/>|>[\\s\\S]*?</c>)`),
  )
  const body = `<is><t xml:space="preserve">${escapeCellText(text)}</t></is>`
  if (match) {
    const style = readXmlAttribute(`${match[1] ?? ''} ${match[2] ?? ''}`, 's')
    const cell = `<c r="${address}"${style === undefined ? '' : ` s="${style}"`} t="inlineStr">${body}</c>`
    return worksheetXml.replace(match[0], () => cell)
  }
  const rowNumber = Number(address.match(/[1-9][0-9]*$/)?.[0])
  const rowMatch = worksheetXml.match(
    new RegExp(`(<row\\b[^>]*\\br="${rowNumber}"[^>]*>)([\\s\\S]*?)(</row>)`),
  )
  if (rowMatch) {
    return worksheetXml.replace(
      rowMatch[0],
      () => `${rowMatch[1]}${rowMatch[2]}<c r="${address}" t="inlineStr">${body}</c>${rowMatch[3]}`,
    )
  }
  const newRow = `<row r="${rowNumber}"><c r="${address}" t="inlineStr">${body}</c></row>`
  for (const rowStart of worksheetXml.matchAll(/<row\b[^>]*?\br="([1-9][0-9]*)"/g)) {
    if (Number(rowStart[1]) > rowNumber) {
      const index = rowStart.index ?? 0
      return worksheetXml.slice(0, index) + newRow + worksheetXml.slice(index)
    }
  }
  if (worksheetXml.includes('</sheetData>')) {
    return worksheetXml.replace('</sheetData>', () => `${newRow}</sheetData>`)
  }
  const emptySheetData = /<sheetData\s*\/>/
  if (emptySheetData.test(worksheetXml)) {
    return worksheetXml.replace(emptySheetData, () => `<sheetData>${newRow}</sheetData>`)
  }
  throw new Error('Worksheet has no sheetData element.')
}
