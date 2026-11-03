/// Geometry persistence (列宽/行高落盘): the grid edits column widths and
/// row heights in pixels; these writers put them back into the worksheet as
/// OOXML <col customWidth> entries and <row ht customHeight> attributes.
/// Cell edits and geometry touch disjoint XML sections, so they compose.

import { createBufferEntrySource } from './zip'
import { escapeXmlText } from './xml'

export interface ColumnWidthEntry {
  /// 0-based column index
  readonly index: number
  /// width in Excel character units
  readonly widthChars: number
}

export interface RowHeightEntry {
  /// 0-based row index
  readonly index: number
  /// height in points
  readonly heightPoints: number
}

interface ColRange {
  min: number
  max: number
  attrs: string // serialized attributes without min/max
}

function parseColRanges(colsInner: string): ColRange[] {
  const ranges: ColRange[] = []
  for (const match of colsInner.matchAll(/<col\b([^>]*?)\/>/g)) {
    const attrs = match[1] ?? ''
    const min = Number(attrs.match(/\bmin="([0-9]+)"/)?.[1] ?? 1)
    const max = Number(attrs.match(/\bmax="([0-9]+)"/)?.[1] ?? min)
    ranges.push({
      min,
      max,
      attrs: attrs.replace(/\s*(?:min|max)="[0-9]+"/g, '').trim(),
    })
  }
  return ranges
}

function serializeCols(ranges: readonly ColRange[]): string {
  const ordered = [...ranges].sort((left, right) => left.min - right.min)
  return `<cols>${ordered
    .map((range) => `<col min="${range.min}" max="${range.max}"${range.attrs ? ` ${range.attrs}` : ''}/>`)
    .join('')}</cols>`
}

/// Set explicit per-column widths. Existing <col> ranges that span a requested
/// column are split around it; untouched ranges keep their attributes.
export function setColumnWidthsXml(worksheetXml: string, entries: readonly ColumnWidthEntry[]): string {
  if (entries.length === 0) return worksheetXml
  const requested = new Map<number, number>()
  for (const entry of entries) {
    if (entry.index < 0 || entry.index >= 16384) throw new Error(`列 ${entry.index + 1} 超出工作表宽度。`)
    if (!(entry.widthChars > 0) || entry.widthChars > 255) throw new Error(`列宽 ${entry.widthChars} 必须在 0–255 字符之间。`)
    requested.set(entry.index + 1, entry.widthChars)
  }

  const existing = worksheetXml.match(/<cols\b[^>]*>([\s\S]*?)<\/cols>/)
  let ranges = existing ? parseColRanges(existing[1] ?? '') : []
  // split every range around each requested column, then add the singles
  const next: ColRange[] = []
  for (const range of ranges) {
    let cursor = range.min
    for (const [column, _width] of [...requested.entries()].sort((a, b) => a[0] - b[0])) {
      void _width
      if (column < cursor || column > range.max) continue
      if (column > cursor) next.push({ ...range, min: cursor, max: column - 1 })
      cursor = column + 1
    }
    if (cursor <= range.max) next.push({ ...range, min: cursor, max: range.max })
  }
  for (const [column, width] of requested) {
    next.push({ min: column, max: column, attrs: `width="${width.toFixed(4)}" customWidth="1"` })
  }
  ranges = next

  const section = serializeCols(ranges)
  if (existing?.index !== undefined) {
    return worksheetXml.slice(0, existing.index) + section + worksheetXml.slice(existing.index + existing[0].length)
  }
  // schema position: cols precedes sheetData (and follows sheetFormatPr)
  const anchor = worksheetXml.search(/<sheetData\b/)
  if (anchor < 0) throw new Error('工作表缺少 sheetData，无法写入列宽。')
  return worksheetXml.slice(0, anchor) + section + worksheetXml.slice(anchor)
}

function setRowAttributes(rowXml: string, heightPoints: number): string {
  const ht = `ht="${heightPoints.toFixed(4)}"`
  let xml = rowXml
  if (/\bht="/.test(xml)) xml = xml.replace(/\bht="[^"]*"/, ht)
  else xml = xml.replace(/<row\b/, `<row ${ht}`)
  if (/\bcustomHeight="/.test(xml)) xml = xml.replace(/\bcustomHeight="[^"]*"/, 'customHeight="1"')
  else xml = xml.replace(/<row\b/, '<row customHeight="1"')
  return xml
}

/// Set explicit per-row heights. Existing rows keep their other attributes;
/// missing rows are created as empty <row> elements in ascending order (a
/// row carrying only ht/customHeight is valid OOXML).
export function setRowHeightsXml(worksheetXml: string, entries: readonly RowHeightEntry[]): string {
  if (entries.length === 0) return worksheetXml
  const wanted = new Map<number, number>()
  for (const entry of entries) {
    if (entry.index < 0 || entry.index >= 1_048_576) throw new Error(`行 ${entry.index + 1} 超出工作表高度。`)
    if (!(entry.heightPoints > 0) || entry.heightPoints > 409) throw new Error(`行高 ${entry.heightPoints} 必须在 0–409 磅之间。`)
    wanted.set(entry.index + 1, entry.heightPoints)
  }

  // normalize a self-closing <sheetData/> to open/close form first
  let xml = worksheetXml.replace(/<sheetData\b([^>]*?)\/>/, '<sheetData$1></sheetData>')
  const open = xml.match(/<sheetData\b[^>]*>/)
  if (open?.index === undefined) throw new Error('工作表缺少 sheetData，无法写入行高。')
  const openEnd = open.index + open[0].length
  const close = xml.indexOf('</sheetData>', openEnd)
  if (close < 0) throw new Error('工作表缺少 sheetData，无法写入行高。')
  let inner = xml.slice(openEnd, close)

  for (const [rowNumber, height] of wanted) {
    const rowPattern = new RegExp(`<row\\b[^>]*\\br="${rowNumber}"(?:[^>]*)(?:/>|>[\\s\\S]*?</row>)`)
    const existingRow = inner.match(rowPattern)
    if (existingRow) {
      inner = inner.replace(rowPattern, (full) => setRowAttributes(full, height))
      continue
    }
    const newRow = `<row r="${rowNumber}" ht="${height.toFixed(4)}" customHeight="1"/>`
    // insert before the first row with a larger r, else append
    let inserted = false
    inner = inner.replace(/<row\b[^>]*\br="([0-9]+)"/g, (full, r: string) => {
      if (!inserted && Number(r) > rowNumber) {
        inserted = true
        return `${newRow}${full}`
      }
      return full
    })
    if (!inserted) inner += newRow
  }
  return `${xml.slice(0, openEnd)}${inner}${xml.slice(close)}`
}

async function worksheetPathFor(
  sourceBytes: Uint8Array,
  sheetName: string,
): Promise<{ path: string; xml: string }> {
  const source = await createBufferEntrySource(sourceBytes)
  const workbookXml = await source.readText('xl/workbook.xml')
  const { parseSheetElements, resolveWorksheetPath } = await import('./workbook-read')
  const element = parseSheetElements(workbookXml).find((entry) => entry.name === sheetName)
  if (!element?.relationshipId) throw new Error(`workbook.xml 中找不到工作表 "${escapeXmlText(sheetName)}"。`)
  const path = await resolveWorksheetPath(source, element.relationshipId)
  return { path, xml: await source.readText(path) }
}

async function rewriteWorksheet(
  sourceBytes: Uint8Array,
  path: string,
  xml: string,
): Promise<Uint8Array> {
  const { assemblePackage } = await import('./zip')
  const mutation = await assemblePackage(sourceBytes, {
    replaced: new Map([[path, xml]]),
    added: new Map(),
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries: [],
    touchedEntries: [path],
  })
  return mutation.buffer
}

export async function applyColumnWidths(
  sourceBytes: Uint8Array,
  sheetName: string,
  entries: readonly ColumnWidthEntry[],
): Promise<Uint8Array> {
  if (entries.length === 0) return sourceBytes
  const { path, xml } = await worksheetPathFor(sourceBytes, sheetName)
  return rewriteWorksheet(sourceBytes, path, setColumnWidthsXml(xml, entries))
}

export async function applyRowHeights(
  sourceBytes: Uint8Array,
  sheetName: string,
  entries: readonly RowHeightEntry[],
): Promise<Uint8Array> {
  if (entries.length === 0) return sourceBytes
  const { path, xml } = await worksheetPathFor(sourceBytes, sheetName)
  return rewriteWorksheet(sourceBytes, path, setRowHeightsXml(xml, entries))
}
