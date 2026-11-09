// Web equivalent of the pinned GenOffice File ▸ Print chain (f8c17004):
// sheets-main.ts builds a native File menu whose Print item forwards to the
// renderer's openPrintPreviewHost → PrintDialog, which lays the active sheet
// out as print HTML (print-html.ts + print-paginate.ts, honoring the
// EffectivePageSetup from the session Page Layout journal over the file's
// pageSetup/pageMargins/printOptions/_xlnm names) and spools it through a
// hidden Electron window (printToPDF → CUPS).
//
// A web page has no Electron print pipeline and the installed Univer stack
// (0.25.1) ships only SheetPrintInterceptorService hooks — no print flow — so
// this module reproduces the achievable subset with the browser: the same
// layout math (bandIndices pagination, margin presets, OOXML paper table) is
// used to build one print document per sheet, rendered into a hidden iframe
// and printed with contentWindow.print(). @page size/margin carry paper,
// orientation and margins; print area, repeated title rows/columns, manual
// breaks, print gridlines/headings and scale/fit-to-page are baked into the
// page tables. What the browser print dialog then owns (printer, copies,
// collate, page selection) and what we deliberately do not render
// (header/footer texts, cell borders, unsupported number formats, merged
// cells clipped across a page boundary) is declared in the editor feedback,
// not silently dropped.

import { fromUniverStyle, type LogicalStyle, type UniverStyleData } from './workbook-vendor/core/style-map'
import { formatNumericValue } from '@sheets-web/xlsx-engine'
import { isHiddenAxisEntry, type UniverColumnData, type UniverRowData } from './workbook-vendor/core/univer-data'

export interface PrintArea {
  readonly startRow: number
  readonly endRow: number
  readonly startColumn: number
  readonly endColumn: number
}

export interface IndexSpan {
  readonly start: number
  readonly end: number
}

export interface SheetPrintPage {
  readonly area: number
  readonly rowStart: number
  readonly rowEnd: number
  readonly colStart: number
  readonly colEnd: number
}

export interface PrintMarginsInches {
  readonly left: number
  readonly right: number
  readonly top: number
  readonly bottom: number
}

export type PrintMarginPreset = 'normal' | 'wide' | 'narrow' | 'custom'

/// Inches, mirroring the pinned source's MARGIN_PRESETS (print-settings.ts)
/// and the engine's margin presets (page-setup.ts). Header/footer distances
/// are not used: the web print document renders no header/footer texts.
export const PRINT_MARGIN_PRESETS: Record<Exclude<PrintMarginPreset, 'custom'>, PrintMarginsInches> = {
  normal: { left: 0.7, right: 0.7, top: 0.75, bottom: 0.75 },
  wide: { left: 1, right: 1, top: 1, bottom: 1 },
  narrow: { left: 0.25, right: 0.25, top: 0.75, bottom: 0.75 },
}

/// OOXML paper-size code → portrait [widthIn, heightIn]. Subset of the pinned
/// print-html.ts PAPER_SIZES + NAMED_PAPER_INCHES tables; unmapped codes fall
/// back to A4 like the source does.
const PAPER_INCHES: Record<number, readonly [number, number]> = {
  1: [8.5, 11], 2: [8.5, 11], 18: [8.5, 11],
  3: [11, 17], 4: [17, 11], 5: [8.5, 14], 6: [5.5, 8.5], 7: [7.25, 10.5],
  8: [11.69, 16.54], 9: [8.27, 11.69], 10: [8.27, 11.69], 11: [5.83, 8.27],
  12: [9.84, 13.9], 13: [7.17, 10.12], 14: [8.5, 13], 15: [8.46, 10.83], 16: [10, 14],
}

export function paperSizeInches(paperSize: number, orientation: 'portrait' | 'landscape'): { widthIn: number; heightIn: number } {
  const [widthIn, heightIn] = PAPER_INCHES[paperSize] ?? PAPER_INCHES[9]!
  return orientation === 'landscape' ? { widthIn: heightIn, heightIn: widthIn } : { widthIn, heightIn }
}

export interface PrintCell {
  value: string | number | boolean | null
  formula?: string | undefined
  style?: LogicalStyle | undefined
}

export interface SheetPrintSource {
  readonly name: string
  readonly cells: Readonly<Record<string, PrintCell>>
  /// 0-based inclusive bounds.
  readonly merges: readonly { startRow: number; startColumn: number; endRow: number; endColumn: number }[]
  /// Live Univer pixel widths/heights keyed by 0-based index; absent = default.
  readonly columnWidths: Readonly<Record<number, number | undefined>>
  readonly rowHeights: Readonly<Record<number, number | undefined>>
  readonly hiddenColumns: ReadonlySet<number>
  readonly hiddenRows: ReadonlySet<number>
}

export interface SheetPrintSetup {
  readonly orientation: 'portrait' | 'landscape'
  readonly paperSize: number
  /// Percent (10-400); used when fitToPage is off.
  readonly scale: number
  readonly fitToPage: boolean
  /// Pages across / tall; 0 = automatic on that axis.
  readonly fitToWidth: number
  readonly fitToHeight: number
  readonly margins: PrintMarginsInches
  readonly printGridlines: boolean
  readonly printHeadings: boolean
  /// Display form "A1:B4" (or null → the used range).
  readonly printArea: string | null
  /// Display form "1:2" (rows) and/or "A:B" (columns), or null.
  readonly printTitles: string | null
  /// 0-based row/column index that starts a new page.
  readonly rowBreaks: readonly number[]
  readonly colBreaks: readonly number[]
}

export interface SheetPrintPlan {
  readonly paper: { widthIn: number; heightIn: number }
  /// Resolved scale percent actually applied (fit-to-page resolved).
  readonly scale: number
  readonly areas: readonly PrintArea[]
  readonly titleRows: IndexSpan | null
  readonly titleColumns: IndexSpan | null
  readonly pages: readonly SheetPrintPage[]
}

const DEFAULT_COLUMN_WIDTH_PX = 64
const DEFAULT_ROW_HEIGHT_PX = 20
/// Pinned source print-html.ts heading strip sizes.
const HEADING_COLUMN_WIDTH_PT = 24
const HEADING_ROW_HEIGHT_PT = 14
const PX_TO_PT = 0.75
export const SHEET_PRINT_MAX_CELLS = 50_000

const COLUMN_LETTERS = (index: number): string => {
  let label = ''
  for (let value = index; value >= 0; value = Math.floor(value / 26) - 1) {
    label = String.fromCharCode(65 + (value % 26)) + label
  }
  return label
}

const parseColumnRef = (letters: string): number | null => {
  let index = 0
  for (const char of letters) {
    if (char < 'A' || char > 'Z') return null
    index = index * 26 + (char.charCodeAt(0) - 64)
  }
  return index - 1
}

/** "A1:B4" / "$A$1:$B$4" → 0-based inclusive bounds; null when malformed. */
export function parsePrintRange(reference: string): PrintArea | null {
  const parts = reference.replace(/\$/g, '').split(':')
  if (parts.length !== 2) return null
  const match = (part: string): { row: number; column: number } | null => {
    const parsed = part.match(/^([A-Z]{1,3})([1-9][0-9]{0,6})$/)
    if (!parsed) return null
    const column = parseColumnRef(parsed[1]!)
    return column === null ? null : { column, row: Number(parsed[2]) - 1 }
  }
  const start = match(parts[0]!), end = match(parts[1]!)
  if (!start || !end || Math.max(start.row, end.row) > 1048575 || Math.max(start.column, end.column) > 16383) return null
  return {
    startRow: Math.min(start.row, end.row), endRow: Math.max(start.row, end.row),
    startColumn: Math.min(start.column, end.column), endColumn: Math.max(start.column, end.column),
  }
}

/** File/journal print area (possibly comma-separated areas) → bounds. */
export function parsePrintAreas(reference: string | null): PrintArea[] {
  if (!reference) return []
  return reference.split(',').map(part => parsePrintRange(part.trim())).filter((area): area is PrintArea => area !== null)
}

/** "1:2, A:B" → repeated title rows/columns (0-based inclusive). */
export function parsePrintTitles(reference: string | null): { rows: IndexSpan | null; columns: IndexSpan | null } {
  if (!reference) return { rows: null, columns: null }
  let rows: IndexSpan | null = null
  let columns: IndexSpan | null = null
  for (const rawPart of reference.split(',')) {
    const part = rawPart.trim().replace(/\$/g, '')
    const [from, to] = part.split(':')
    if (!from || !to) continue
    const rowsOnly = /^\d+$/.test(from) && /^\d+$/.test(to)
    if (rowsOnly) {
      const start = Number(from) - 1, end = Number(to) - 1
      if (start >= 0 && end >= start) rows = { start, end: Math.min(end, start + 20) }
      continue
    }
    const startColumn = parseColumnRef(from.toUpperCase()), endColumn = parseColumnRef(to.toUpperCase())
    if (startColumn !== null && endColumn !== null && startColumn <= endColumn) columns = { start: startColumn, end: endColumn }
  }
  return { rows, columns }
}

/// Snapshot sheet → print source. Mirrors workbook-vendor readBackSnapshot's
/// extraction but keeps the hidden flags it drops: print layout must give
/// hidden rows/columns zero size instead of the default.
export function printSourceFromSnapshotSheet(sheet: unknown, styles: Readonly<Record<string, UniverStyleData>> = {}): SheetPrintSource {
  const data = (sheet ?? {}) as {
    name?: string
    cellData?: Record<number, Record<number, { v?: unknown; f?: string; s?: string | UniverStyleData } | undefined>>
    mergeData?: Array<{ startRow?: number; startColumn?: number; endRow?: number; endColumn?: number }>
    columnData?: Record<string, UniverColumnData | undefined>
    rowData?: Record<string, UniverRowData | undefined>
  }
  const cells: Record<string, PrintCell> = {}
  for (const [rowKey, row] of Object.entries(data.cellData ?? {})) {
    for (const [columnKey, cell] of Object.entries(row ?? {})) {
      if (cell === undefined) continue
      const rawValue = cell.v
      const value = rawValue === null || rawValue === undefined ? null
        : typeof rawValue === 'number' || typeof rawValue === 'boolean' ? rawValue : String(rawValue)
      cells[`${COLUMN_LETTERS(Number(columnKey))}${Number(rowKey) + 1}`] = {
        value,
        ...(typeof cell.f === 'string' && cell.f ? { formula: cell.f } : {}),
        ...(cell.s != null ? { style: fromUniverStyle(typeof cell.s === 'string' ? styles[cell.s] ?? {} : cell.s) } : {}),
      }
    }
  }
  const merges = (data.mergeData ?? []).flatMap(merge => {
    const startRow = merge.startRow, startColumn = merge.startColumn, endRow = merge.endRow, endColumn = merge.endColumn
    return typeof startRow === 'number' && typeof startColumn === 'number' &&
      typeof endRow === 'number' && typeof endColumn === 'number' &&
      Number.isSafeInteger(startRow) && Number.isSafeInteger(startColumn) &&
      Number.isSafeInteger(endRow) && Number.isSafeInteger(endColumn) &&
      endRow >= startRow && endColumn >= startColumn
      ? [{ startRow, startColumn, endRow, endColumn }]
      : []
  })
  const columnWidths: Record<number, number | undefined> = {}
  const hiddenColumns = new Set<number>()
  for (const [columnKey, column] of Object.entries(data.columnData ?? {})) {
    const index = Number(columnKey)
    if (isHiddenAxisEntry(column)) hiddenColumns.add(index)
    if (column?.w !== undefined) columnWidths[index] = column.w
  }
  const rowHeights: Record<number, number | undefined> = {}
  const hiddenRows = new Set<number>()
  for (const [rowKey, row] of Object.entries(data.rowData ?? {})) {
    const index = Number(rowKey)
    if (isHiddenAxisEntry(row)) hiddenRows.add(index)
    if (row?.h !== undefined) rowHeights[index] = row.h
  }
  return { name: data.name ?? '', cells, merges, columnWidths, rowHeights, hiddenColumns, hiddenRows }
}

const columnWidthPx = (source: SheetPrintSource, column: number): number =>
  source.hiddenColumns.has(column) ? 0 : source.columnWidths[column] ?? DEFAULT_COLUMN_WIDTH_PX
const rowHeightPx = (source: SheetPrintSource, row: number): number =>
  source.hiddenRows.has(row) ? 0 : source.rowHeights[row] ?? DEFAULT_ROW_HEIGHT_PX

/// Used range from the live cells plus merge bounds (the snapshot carries no
/// dimension): an empty sheet prints nothing rather than a full default grid.
function usedRange(source: SheetPrintSource): PrintArea | null {
  let endRow = -1, endColumn = -1
  for (const address of Object.keys(source.cells)) {
    const parsed = address.match(/^([A-Z]{1,3})([1-9][0-9]{0,6})$/)
    if (!parsed) continue
    const column = parseColumnRef(parsed[1]!)
    if (column === null) continue
    endRow = Math.max(endRow, Number(parsed[2]) - 1)
    endColumn = Math.max(endColumn, column)
  }
  for (const merge of source.merges) {
    endRow = Math.max(endRow, merge.endRow)
    endColumn = Math.max(endColumn, merge.endColumn)
  }
  return endRow < 0 || endColumn < 0 ? null
    : { startRow: 0, endRow, startColumn: 0, endColumn }
}

/** Splits `indices` into bands that fit `capacity` (pt), starting a new band
 * at every manual break; an index larger than the capacity gets its own band.
 * Port of the pinned print-paginate.ts bandIndices. */
export function bandIndices(
  indices: readonly number[],
  sizeOf: (index: number) => number,
  capacity: number,
  breaks: ReadonlySet<number>,
): IndexSpan[] {
  const bands: IndexSpan[] = []
  let start: number | null = null
  let used = 0
  let last = -1
  for (const index of indices) {
    const size = sizeOf(index)
    if (start !== null && (breaks.has(index) || used + size > capacity)) {
      bands.push({ start, end: last })
      start = null
      used = 0
    }
    if (start === null) start = index
    used += size
    last = index
  }
  if (start !== null) bands.push({ start, end: last })
  return bands
}

const spanSize = (span: IndexSpan | null, sizeOf: (index: number) => number): number => {
  if (span === null) return 0
  let total = 0
  for (let index = span.start; index <= span.end; index += 1) total += sizeOf(index)
  return total
}

/** Resolves the printable areas (file/journal area or the used range), applies
 * scale / fit-to-page, and plans pages with rows-never-split banding — the
 * pinned planPrintPages semantics: title strips and heading edges take their
 * share of every page, manual breaks end the page, pages run down then over. */
export function planSheetPrint(source: SheetPrintSource, setup: SheetPrintSetup): SheetPrintPlan | null {
  const areas = setup.printArea !== null && setup.printArea !== ''
    ? parsePrintAreas(setup.printArea)
    : [usedRange(source)].filter((area): area is PrintArea => area !== null)
  if (areas.length === 0) return null
  const cellCount = areas.reduce((sum, area) =>
    sum + (area.endRow - area.startRow + 1) * (area.endColumn - area.startColumn + 1), 0)
  if (cellCount === 0 || cellCount > SHEET_PRINT_MAX_CELLS) return null
  const paper = paperSizeInches(setup.paperSize, setup.orientation)
  const printableWidthPt = Math.max((paper.widthIn - setup.margins.left - setup.margins.right) * 72, 1)
  const printableHeightPt = Math.max((paper.heightIn - setup.margins.top - setup.margins.bottom) * 72, 1)
  // Title strips only consume page space when they actually precede the
  // printed area; titles wholly outside it are dropped instead of shrinking
  // every page's capacity for content that is never rendered.
  const parsedTitles = parsePrintTitles(setup.printTitles)
  const titleRows = parsedTitles.rows !== null && areas.some(area =>
    parsedTitles.rows!.end >= area.startRow && parsedTitles.rows!.start <= area.endRow)
    ? parsedTitles.rows : null
  const titleColumns = parsedTitles.columns !== null && areas.some(area =>
    parsedTitles.columns!.end >= area.startColumn && parsedTitles.columns!.start <= area.endColumn)
    ? parsedTitles.columns : null
  const headingWidthPt = setup.printHeadings ? HEADING_COLUMN_WIDTH_PT : 0
  const headingHeightPt = setup.printHeadings ? HEADING_ROW_HEIGHT_PT : 0
  const inSpan = (span: IndexSpan | null, index: number): boolean => span !== null && index >= span.start && index <= span.end
  const bodyRows = (area: PrintArea): number[] => {
    const rows: number[] = []
    for (let row = area.startRow; row <= area.endRow; row += 1) {
      if (inSpan(titleRows, row) || rowHeightPx(source, row) <= 0) continue
      rows.push(row)
    }
    return rows
  }
  const bodyColumns = (area: PrintArea): number[] => {
    const columns: number[] = []
    for (let column = area.startColumn; column <= area.endColumn; column += 1) {
      if (inSpan(titleColumns, column) || columnWidthPx(source, column) <= 0) continue
      columns.push(column)
    }
    return columns
  }
  let scale = Math.min(Math.max(setup.scale, 10), 400) / 100
  if (setup.fitToPage) {
    // Fit-to-page only shrinks: resolve the constrained axes' fraction against
    // the full (unscaled) content width/height including strips.
    let contentWidthPt = 0
    let contentHeightPt = 0
    for (const area of areas) {
      let width = headingWidthPt + spanSize(titleColumns, column => columnWidthPx(source, column) * PX_TO_PT)
      let height = headingHeightPt + spanSize(titleRows, row => rowHeightPx(source, row) * PX_TO_PT)
      for (const column of bodyColumns(area)) width += columnWidthPx(source, column) * PX_TO_PT
      for (const row of bodyRows(area)) height += rowHeightPx(source, row) * PX_TO_PT
      contentWidthPt = Math.max(contentWidthPt, width)
      contentHeightPt = Math.max(contentHeightPt, height)
    }
    scale = 1
    if (setup.fitToWidth > 0 && contentWidthPt > 0) scale = Math.min(scale, (printableWidthPt * setup.fitToWidth) / contentWidthPt)
    if (setup.fitToHeight > 0 && contentHeightPt > 0) scale = Math.min(scale, (printableHeightPt * setup.fitToHeight) / contentHeightPt)
    scale = Math.min(Math.max(scale, 0.05), 1)
  }
  const pageWidthPt = printableWidthPt / scale
  const pageHeightPt = printableHeightPt / scale
  const rowCapacity = pageHeightPt - headingHeightPt - spanSize(titleRows, row => rowHeightPx(source, row) * PX_TO_PT)
  const columnCapacity = pageWidthPt - headingWidthPt - spanSize(titleColumns, column => columnWidthPx(source, column) * PX_TO_PT)
  const rowBreaks = new Set(setup.rowBreaks)
  const colBreaks = new Set(setup.colBreaks)
  const pages: SheetPrintPage[] = []
  areas.forEach((area, areaIndex) => {
    const rows = bodyRows(area)
    const columns = bodyColumns(area)
    if (rows.length === 0 || columns.length === 0) return
    const rowBands = bandIndices(rows, row => rowHeightPx(source, row) * PX_TO_PT, Math.max(rowCapacity, 1), rowBreaks)
    const columnBands = bandIndices(columns, column => columnWidthPx(source, column) * PX_TO_PT, Math.max(columnCapacity, 1), colBreaks)
    for (const columnBand of columnBands) {
      for (const rowBand of rowBands) {
        pages.push({ area: areaIndex, rowStart: rowBand.start, rowEnd: rowBand.end, colStart: columnBand.start, colEnd: columnBand.end })
      }
    }
  })
  return pages.length === 0 ? null : {
    paper, scale: Math.round(scale * 100), areas, titleRows, titleColumns, pages,
  }
}

const escapeHtml = (value: string): string => value
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;')

const displayValue = (cell: PrintCell | undefined): string => {
  const value = cell?.value
  return value === null || value === undefined ? '' : typeof value === 'number'
    ? formatNumericValue(value, cell?.style?.numberFormat) : String(value)
}

/// Visual subset of LogicalStyle → inline CSS (sizes pre-scaled by the print
/// scale). Number formats use the shared engine formatter; cell
/// borders are not rendered (only the sheet-level print-gridlines toggle).
const cellStyleCss = (style: LogicalStyle | undefined, scalePercent: number): string => {
  if (!style) return ''
  const rules: string[] = []
  if (style.bold) rules.push('font-weight:700')
  if (style.italic) rules.push('font-style:italic')
  const decorations = [style.underline ? 'underline' : '', style.strikethrough ? 'line-through' : ''].filter(Boolean)
  if (decorations.length) rules.push(`text-decoration-line:${decorations.join(' ')}`)
  if (style.underline && style.underlineStyle === 'double') rules.push('text-decoration-style:double')
  if (style.fontSize !== undefined) rules.push(`font-size:${Math.max(style.fontSize * scalePercent, 0.5)}pt`)
  if (style.fontFamily) rules.push(`font-family:${style.fontFamily}`)
  if (style.fontColor && style.fontColor !== 'none') rules.push(`color:${style.fontColor}`)
  if (style.fillColor && style.fillColor !== 'none') rules.push(`background-color:${style.fillColor}`)
  if (style.hAlign) rules.push(`text-align:${style.hAlign === 'justify' ? 'justify' : style.hAlign}`)
  if (style.vAlign) rules.push(`vertical-align:${style.vAlign === 'top' ? 'top' : style.vAlign === 'middle' ? 'middle' : 'bottom'}`)
  if (!style.wrap) rules.push('white-space:nowrap')
  return rules.length > 0 ? ` style="${escapeHtml(rules.join(';'))}"` : ''
}

/// Builds the complete print document (one `@page` rule + one absolutely
/// sized .page div per planned page, content inset by the margins, title
/// strips and optional heading edges repeated per page) — the same document
/// shape the pinned source renders into its hidden Electron print window.
export function buildSheetPrintHtml(source: SheetPrintSource, setup: SheetPrintSetup): string | null {
  const plan = planSheetPrint(source, setup)
  if (!plan) return null
  const { paper, scale, areas, titleRows, titleColumns, pages } = plan
  const marginCss = `left:${setup.margins.left}in;top:${setup.margins.top}in;` +
    `width:${Math.max(paper.widthIn - setup.margins.left - setup.margins.right, 0.01)}in;` +
    `height:${Math.max(paper.heightIn - setup.margins.top - setup.margins.bottom, 0.01)}in`
  const scalePercent = scale / 100
  const pageElements = pages.map(page => {
    const area = areas[page.area]!
    // Plan capacities are in unscaled content pt; rendering multiplies every
    // size by the scale so the table physically fits the printable area.
    const columnWidthPt = (column: number) => columnWidthPx(source, column) * PX_TO_PT * scalePercent
    const rowHeightPt = (row: number) => rowHeightPx(source, row) * PX_TO_PT * scalePercent
    // Merges fully inside this page's band span their cells; merges reaching
    // past the band print as plain cells (clipped text is not recomposed).
    const merges = source.merges.filter(merge =>
      merge.startRow >= page.rowStart && merge.endRow <= page.rowEnd &&
      merge.startColumn >= page.colStart && merge.endColumn <= page.colEnd)
    const spanOf = (row: number, column: number): string => {
      if (merges.length === 0) return ''
      const merge = merges.find(item => row >= item.startRow && row <= item.endRow &&
        column >= item.startColumn && column <= item.endColumn)
      if (!merge) return ''
      if (merge.startRow !== row || merge.startColumn !== column) return 'skip'
      let rows = 0, columns = 0
      for (let index = merge.startRow; index <= merge.endRow; index += 1) if (rowHeightPt(index) > 0) rows += 1
      for (let index = merge.startColumn; index <= merge.endColumn; index += 1) if (columnWidthPt(index) > 0) columns += 1
      return ` rowspan="${rows}" colspan="${columns}"`
    }
    const titleColumnList: number[] = []
    if (titleColumns !== null) for (let column = titleColumns.start; column <= titleColumns.end; column += 1) {
      if (columnWidthPt(column) > 0) titleColumnList.push(column)
    }
    const bodyColumnList: number[] = []
    for (let column = page.colStart; column <= page.colEnd; column += 1) {
      if (columnWidthPt(column) > 0) bodyColumnList.push(column)
    }
    const headingCell = (tag: 'th' | 'td', text: string, css: string): string =>
      `<${tag} class="${css}">${escapeHtml(text)}</${tag}>`
    const dataCell = (row: number, column: number): string => {
      const span = spanOf(row, column)
      if (span === 'skip') return ''
      const cell = source.cells[`${COLUMN_LETTERS(column)}${row + 1}`]
      return `<td${span}${cellStyleCss(cell?.style, scalePercent)}>${escapeHtml(displayValue(cell))}</td>`
    }
    const rowCells = (row: number, includeRowNumber: boolean): string => {
      const cells: string[] = []
      if (setup.printHeadings) {
        cells.push(headingCell('th', includeRowNumber ? String(row + 1) : '', 'hd hd-row'))
      }
      for (const column of titleColumnList) cells.push(dataCell(row, column))
      for (const column of bodyColumnList) cells.push(dataCell(row, column))
      return cells.join('')
    }
    const rows: string[] = []
    if (setup.printHeadings) {
      const headingCells: string[] = [headingCell('th', '', 'hd hd-corner')]
      for (const column of titleColumnList) headingCells.push(headingCell('th', COLUMN_LETTERS(column), 'hd hd-column'))
      for (const column of bodyColumnList) headingCells.push(headingCell('th', COLUMN_LETTERS(column), 'hd hd-column'))
      rows.push(`<tr class="heading-row">${headingCells.join('')}</tr>`)
    }
    if (titleRows !== null) {
      for (let row = titleRows.start; row <= titleRows.end; row += 1) {
        if (rowHeightPt(row) <= 0) continue
        rows.push(`<tr style="height:${rowHeightPt(row)}pt">${rowCells(row, true)}</tr>`)
      }
    }
    for (let row = page.rowStart; row <= page.rowEnd; row += 1) {
      if (rowHeightPt(row) <= 0) continue
      rows.push(`<tr style="height:${rowHeightPt(row)}pt">${rowCells(row, true)}</tr>`)
    }
    const colgroup: string[] = []
    if (setup.printHeadings) colgroup.push(`<col style="width:${HEADING_COLUMN_WIDTH_PT * scalePercent}pt">`)
    for (const column of titleColumnList) colgroup.push(`<col style="width:${columnWidthPt(column)}pt">`)
    for (const column of bodyColumnList) colgroup.push(`<col style="width:${columnWidthPt(column)}pt">`)
    return `<div class="page" style="width:${paper.widthIn}in;height:${paper.heightIn}in">` +
      `<div class="content" style="${marginCss}">` +
      `<table class="${setup.printGridlines ? 'gridlines' : ''}" style="font-size:${11 * scalePercent}pt">` +
      `<colgroup>${colgroup.join('')}</colgroup><tbody>${rows.join('')}</tbody></table>` +
      `</div></div>`
  }).join('')
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${escapeHtml(source.name || 'Sheet')}</title><style>` +
    `@page { size: ${paper.widthIn}in ${paper.heightIn}in; margin: 0; }` +
    `html, body { margin: 0; padding: 0; background: #fff; }` +
    `.page { position: relative; overflow: hidden; break-after: page; page-break-after: always; }` +
    `.page:last-child { break-after: auto; page-break-after: auto; }` +
    `.content { position: absolute; overflow: hidden; }` +
    `table { border-collapse: collapse; table-layout: fixed; font-family: Calibri, Arial, sans-serif; }` +
    `td, th { padding: 0 2pt; border: 0; overflow: hidden; vertical-align: bottom; word-break: break-all; }` +
    `table.gridlines td { border: 0.5pt solid #b7b7b7; }` +
    `th.hd { background: #f1f1f1; color: #444; font-size: 8.5pt; font-weight: 400; text-align: center; }` +
    `</style></head><body>${pageElements}</body></html>`
}

/// Prints a prepared document through a hidden iframe — the browser dialog
/// that opens is owned by the user (printer/copies/page range are not
/// scriptable); the document itself already carries the page setup. Returns
/// false when the environment cannot print a frame (the caller must say so
/// instead of pretending the job was sent).
export function printDocument(html: string, doc: Document = document): boolean {
  let frame: HTMLIFrameElement | undefined
  try {
    const created = doc.createElement('iframe')
    frame = created
    frame.setAttribute('aria-hidden', 'true')
    frame.style.position = 'fixed'
    frame.style.right = '0'
    frame.style.bottom = '0'
    frame.style.width = '0'
    frame.style.height = '0'
    frame.style.border = '0'
    doc.body.append(frame)
    const frameDoc = frame.contentDocument
    if (!frameDoc) throw new Error('no frame document')
    frameDoc.open()
    frameDoc.write(html)
    frameDoc.close()
    const frameWindow = frame.contentWindow
    if (!frameWindow || typeof frameWindow.print !== 'function') throw new Error('no frame printing')
    frameWindow.print()
  } catch {
    frame?.remove()
    return false
  }
  // Keep the frame (and its document) alive until the spooler consumed it.
  setTimeout(() => frame!.remove(), 60_000)
  return true
}
