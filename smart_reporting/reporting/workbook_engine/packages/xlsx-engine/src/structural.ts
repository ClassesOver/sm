/// Structural row/column transforms for worksheet XML, ported (lean) from
/// genoffice's xlsx-structure + formula-shift: rewrites row/cell addresses,
/// same-sheet and cross-sheet formula references, merges, and the dimension.
/// Ranged/anchored features (CF, DV, autoFilter, tables, drawings) make the
/// caller fail closed — this build refuses to shift around them rather than
/// corrupt references.

import { columnIndex, columnLabel } from './cell-address'
import { decodeXmlText, escapeXmlText, readXmlAttribute, extractElements } from './xml'
import { FORMULA_REFERENCE_PATTERN, qualifierMatches } from './sheets-edit'

export type StructuralOp =
  | { readonly kind: 'insert-rows' | 'remove-rows'; readonly index: number; readonly count: number }
  | { readonly kind: 'insert-cols' | 'remove-cols'; readonly index: number; readonly count: number }

export interface ShiftSpec {
  readonly axis: 'row' | 'column'
  /// 0-based first affected index
  readonly start: number
  /// positive for inserts, negative for deletes
  readonly delta: number
  /// Insert/Delete Cells shifts only this inclusive cross-axis span (rows for
  /// a column shift, columns for a row shift); absent = whole rows/columns.
  readonly band?: { readonly start: number; readonly end: number }
}

export class StructuralShiftError extends Error {}

export function shiftSpecOf(op: StructuralOp): ShiftSpec {
  const delta = op.kind.startsWith('insert') ? op.count : -op.count
  return { axis: op.kind.endsWith('rows') ? 'row' : 'column', start: op.index, delta }
}

/// index after the shift, or null when it falls inside a deleted region
export function shiftIndex(index: number, spec: ShiftSpec): number | null {
  if (index < spec.start) return index
  if (spec.delta > 0) return index + spec.delta
  if (index < spec.start - spec.delta) return null
  return index + spec.delta
}

/// Shared by persisted worksheet breaks and session page-setup coordinates.
export function shiftPageBreakIndexes(indexes: readonly number[], spec: ShiftSpec): number[] {
  const maximum = spec.axis === 'row' ? 1_048_575 : 16_383
  return [...new Set(indexes.flatMap(index => {
    const shifted = shiftIndex(index, spec)
    if (shifted === null || shifted <= 0) return []
    if (shifted > maximum) throw new StructuralShiftError('Page break exceeds worksheet bounds')
    return [shifted]
  }))].sort((a, b) => a - b)
}

function shiftWorksheetPageBreaks(xml: string, spec: ShiftSpec): string {
  const tag = spec.axis === 'row' ? 'rowBreaks' : 'colBreaks'
  return xml.replace(new RegExp(`<((?:[\\w.-]+:)?)${tag}\\b([^>]*?)>([\\s\\S]*?)<\\/\\1${tag}>`, 'g'),
    (_full: string, namespace: string, attributes: string, body: string) => {
      let count = 0, manual = 0
      const next = body.replace(/<((?:[\w.-]+:)?)brk\b([^>]*?)\/>/g, (full, prefix: string, attrs: string) => {
        const raw = readXmlAttribute(attrs, 'id')
        if (raw === undefined) return full
        const [index] = shiftPageBreakIndexes([Number(raw)], spec)
        if (index === undefined) return ''
        count++
        if (!['0', 'false'].includes(readXmlAttribute(attrs, 'man') ?? '1')) manual++
        return `<${prefix}brk${attrs.replace(/(\bid\s*=\s*["'])[0-9]+(["'])/, `$1${index}$2`)}/>`
      })
      const attrs = attributes.replace(/\s+(?:count|manualBreakCount)\s*=\s*(?:"[^"]*"|'[^']*')/g, '')
      return `<${namespace}${tag}${attrs} count="${count}" manualBreakCount="${manual}">${next}</${namespace}${tag}>`
    })
}

/// Cell coordinates after the shift (null when deleted); outside a band the
/// cell does not move.
export function shiftCellIndex(row: number, column: number, spec: ShiftSpec): { row: number; column: number } | null {
  const cross = spec.axis === 'row' ? column : row
  if (spec.band && (cross < spec.band.start || cross > spec.band.end)) return { row, column }
  const shifted = shiftIndex(spec.axis === 'row' ? row : column, spec)
  if (shifted === null) return null
  return spec.axis === 'row' ? { row: shifted, column } : { row, column: shifted }
}

/// Excel's Insert/Delete Cells rewrites a reference only when its cross-axis
/// extent lies wholly inside the shifted band; others stay as written.
function insideBand(spec: ShiftSpec, first: RefPart, second: RefPart = first): boolean {
  if (!spec.band) return true
  const a = spec.axis === 'row' ? first.col : first.row
  const b = spec.axis === 'row' ? second.col : second.row
  return Math.min(a, b) >= spec.band.start && Math.max(a, b) <= spec.band.end
}

// ── formula shifting (genoffice domain/formula-shift semantics) ──────────

const REF_RE =
  /(?<![A-Za-z0-9_.$!])(?:(?:'((?:[^']|'')+)'|([A-Za-z0-9_.]+))!)?(\$?)([A-Z]{1,3})(\$?)([0-9]{1,7})(?::(\$?)([A-Z]{1,3})(\$?)([0-9]{1,7}))?(?![A-Za-z0-9(])/g
const COLUMN_SPAN_RE =
  /(?<![A-Za-z0-9_.$!:])(?:(?:'((?:[^']|'')+)'|([A-Za-z0-9_.]+))!)?(\$?)([A-Z]{1,3}):(\$?)([A-Z]{1,3})(?![A-Za-z0-9($!:])/g
const ROW_SPAN_RE =
  /(?<![A-Za-z0-9_.$!:])(?:(?:'((?:[^']|'')+)'|([A-Za-z0-9_.]+))!)?(\$?)([0-9]{1,7}):(\$?)([0-9]{1,7})(?![A-Za-z0-9($!:])/g

interface RefPart {
  readonly colAbs: string
  readonly col: number
  readonly rowAbs: string
  readonly row: number
}

function formatRef(part: RefPart): string {
  return `${part.colAbs}${columnLabel(part.col)}${part.rowAbs}${part.row + 1}`
}

function shiftRefPart(part: RefPart, spec: ShiftSpec): RefPart | null {
  const value = spec.axis === 'row' ? part.row : part.col
  const shifted = shiftIndex(value, spec)
  if (shifted === null) return null
  return spec.axis === 'row' ? { ...part, row: shifted } : { ...part, col: shifted }
}

/// clamp a deleted endpoint so a partially-deleted range shrinks instead of erroring
function clampRefPart(part: RefPart, spec: ShiftSpec, side: 'start' | 'end'): RefPart {
  const clamped = side === 'start' ? spec.start : spec.start - 1
  return spec.axis === 'row' ? { ...part, row: clamped } : { ...part, col: clamped }
}

function prefixOf(quoted: string | undefined, bare: string | undefined): string {
  return quoted !== undefined ? `'${quoted}'!` : bare !== undefined ? `${bare}!` : ''
}

function appliesTo(
  quoted: string | undefined,
  bare: string | undefined,
  formulaSheetMatchesOp: boolean,
  opSheetName: string,
): boolean {
  if (quoted === undefined && bare === undefined) return formulaSheetMatchesOp
  const prefixSheet = quoted !== undefined ? quoted.replaceAll("''", "'") : bare
  return prefixSheet === opSheetName
}

/// Rewrites A1-style references after a shift: refs into the shifted region
/// move ($ does NOT pin against inserts/deletes), refs into a deleted region
/// become #REF!, partially-overlapping ranges shrink. String literals are
/// skipped. Mirrors genoffice's shiftFormulaRefs.
export function shiftFormulaText(
  formula: string,
  spec: ShiftSpec,
  formulaSheetMatchesOp: boolean,
  opSheetName: string,
): string {
  return formula
    .split('"')
    .map((segment, index) => (index % 2 === 1 ? segment : shiftSegment(segment, spec, formulaSheetMatchesOp, opSheetName)))
    .join('"')
}

function shiftSegment(
  segment: string,
  spec: ShiftSpec,
  formulaSheetMatchesOp: boolean,
  opSheetName: string,
): string {
  let out = segment.replace(
    REF_RE,
    (match, quoted, bare, aAbsC, aCol, aAbsR, aRow, bAbsC, bCol, bAbsR, bRow) => {
      if (!appliesTo(quoted, bare, formulaSheetMatchesOp, opSheetName)) return match
      const prefix = prefixOf(quoted, bare)
      const first: RefPart = {
        colAbs: aAbsC,
        col: columnIndex(aCol),
        rowAbs: aAbsR,
        row: Number(aRow) - 1,
      }
      if (bCol === undefined) {
        if (!insideBand(spec, first)) return match
        const shifted = shiftRefPart(first, spec)
        return shifted ? `${prefix}${formatRef(shifted)}` : `${prefix}#REF!`
      }
      const second: RefPart = {
        colAbs: bAbsC,
        col: columnIndex(bCol),
        rowAbs: bAbsR,
        row: Number(bRow) - 1,
      }
      if (!insideBand(spec, first, second)) return match
      let shiftedFirst = shiftRefPart(first, spec)
      let shiftedSecond = shiftRefPart(second, spec)
      if (!shiftedFirst && !shiftedSecond) return `${prefix}#REF!`
      if (!shiftedFirst) shiftedFirst = clampRefPart(first, spec, 'start')
      if (!shiftedSecond) shiftedSecond = clampRefPart(second, spec, 'end')
      return `${prefix}${formatRef(shiftedFirst)}:${formatRef(shiftedSecond)}`
    },
  )
  // whole-column/row spans cross every band, so a banded shift leaves them
  if (spec.axis === 'column' && !spec.band) {
    out = out.replace(COLUMN_SPAN_RE, (match, quoted, bare, aAbs, aCol, bAbs, bCol) => {
      if (!appliesTo(quoted, bare, formulaSheetMatchesOp, opSheetName)) return match
      const prefix = prefixOf(quoted, bare)
      const part = (abs: string, letters: string): RefPart => ({
        colAbs: abs,
        col: columnIndex(letters),
        rowAbs: '',
        row: 0,
      })
      const formatCol = (p: RefPart): string => `${p.colAbs}${columnLabel(p.col)}`
      let first = shiftRefPart(part(aAbs, aCol), spec)
      let second = shiftRefPart(part(bAbs, bCol), spec)
      if (!first && !second) return `${prefix}#REF!`
      if (!first) first = clampRefPart(part(aAbs, aCol), spec, 'start')
      if (!second) second = clampRefPart(part(bAbs, bCol), spec, 'end')
      return `${prefix}${formatCol(first)}:${formatCol(second)}`
    })
  }
  if (spec.axis === 'row' && !spec.band) {
    out = out.replace(ROW_SPAN_RE, (match, quoted, bare, aAbs, aRow, bAbs, bRow) => {
      if (!appliesTo(quoted, bare, formulaSheetMatchesOp, opSheetName)) return match
      const prefix = prefixOf(quoted, bare)
      const part = (abs: string, rowText: string): RefPart => ({
        colAbs: '',
        col: 0,
        rowAbs: abs,
        row: Number(rowText) - 1,
      })
      const formatRow = (p: RefPart): string => `${p.rowAbs}${p.row + 1}`
      let first = shiftRefPart(part(aAbs, aRow), spec)
      let second = shiftRefPart(part(bAbs, bRow), spec)
      if (!first && !second) return `${prefix}#REF!`
      if (!first) first = clampRefPart(part(aAbs, aRow), spec, 'start')
      if (!second) second = clampRefPart(part(bAbs, bRow), spec, 'end')
      return `${prefix}${formatRow(first)}:${formatRow(second)}`
    })
  }
  return out
}

/// Rewrites formula bodies in a worksheet part (same-sheet semantics).
function shiftWorksheetFormulas(
  worksheetXml: string,
  spec: ShiftSpec,
  sheetName: string,
  sameSheet: boolean,
): string {
  return worksheetXml.replace(
    /<(f|formula[12]|xm:f)\b([^>]*[^/>])?>([\s\S]*?)<\/\1>/g,
    (full, tag: string, attributes: string | undefined, body: string) => {
      const shifted = shiftFormulaText(decodeXmlText(body), spec, sameSheet, sheetName)
      if (shifted === decodeXmlText(body)) return full
      return `<${tag}${attributes ?? ''}>${escapeXmlText(shifted)}</${tag}>`
    },
  )
}

/// Rewrites OTHER parts' formulas: only refs explicitly qualified with
/// sheetName shift (the qualifiedOnly mode).
export function shiftQualifiedFormulas(
  partXml: string,
  spec: ShiftSpec,
  sheetName: string,
): string {
  return partXml.replace(
    /<(f|formula[12]|xm:f)\b([^>]*[^/>])?>([\s\S]*?)<\/\1>/g,
    (full, tag: string, attributes: string | undefined, body: string) => {
      const shifted = shiftFormulaText(decodeXmlText(body), spec, false, sheetName)
      if (shifted === decodeXmlText(body)) return full
      return `<${tag}${attributes ?? ''}>${escapeXmlText(shifted)}</${tag}>`
    },
  )
}

/// Local names also resolve unqualified references against their owning sheet.
export function shiftDefinedNames(workbookXml: string, spec: ShiftSpec, sheetName: string): string {
  const sheetNames = [...(workbookXml.match(/<sheets\b[^>]*>[\s\S]*?<\/sheets>/)?.[0] ?? '').matchAll(/<sheet\b[^>]*>/g)]
    .map(match => decodeXmlText(readXmlAttribute(match[0], 'name') ?? ''))
  return workbookXml.replace(
    /(<definedName\b[^>]*>)([\s\S]*?)(<\/definedName>)/g,
    (full, open: string, body: string, close: string) => {
      const localId = readXmlAttribute(open, 'localSheetId')
      const ownSheet = localId !== undefined && /^[0-9]+$/.test(localId) && sheetNames[Number(localId)] === sheetName
      const shifted = shiftFormulaText(decodeXmlText(body), spec, ownSheet, sheetName)
      if (shifted === decodeXmlText(body)) return full
      return `${open}${escapeXmlText(shifted)}${close}`
    },
  )
}

// ── worksheet geometry ──────────────────────────────────────────────────

interface ParsedRow {
  readonly xml: string
  readonly row: number
}

function parseSheetRows(worksheetXml: string): {
  prefix: string
  rows: ParsedRow[]
  suffix: string
} {
  const match = worksheetXml.match(/([\s\S]*?<sheetData[^>]*>)([\s\S]*?)(<\/sheetData>[\s\S]*)/)
  if (!match?.[1] || match[3] === undefined) {
    throw new StructuralShiftError('Worksheet has no sheetData element.')
  }
  const rows: ParsedRow[] = []
  for (const rowMatch of match[2]!.matchAll(/<row\b[^>]*?(?:\/>|>[\s\S]*?<\/row>)/g)) {
    const xml = rowMatch[0]
    const row = Number(xml.match(/\br="([0-9]+)"/)?.[1] ?? '0')
    rows.push({ xml, row })
  }
  return { prefix: match[1], rows, suffix: match[3] }
}

function rewriteRowNumber(rowXml: string, newRow: number): string {
  return rowXml.replace(/\br="[0-9]+"/, () => `r="${newRow}"`)
}

function rewriteCellRows(rowInner: string, delta: number): string {
  return rowInner.replace(/\br="([A-Z]{1,3})([0-9]+)"/g, (full, letters: string, row: string) =>
    letters === undefined ? full : `r="${letters}${Number(row) + delta}"`,
  )
}

/// Row insert/remove: rows renumber, deleted rows drop, cell addresses
/// inside surviving rows follow their row.
export function applyRowShift(worksheetXml: string, spec: ShiftSpec): string {
  const { prefix, rows, suffix } = parseSheetRows(worksheetXml)
  const rebuilt: string[] = []
  for (const row of rows) {
    const shifted = shiftIndex(row.row - 1, spec)
    if (shifted === null) continue // row inside the deleted region
    const newRow = shifted + 1
    const renumbered = rewriteRowNumber(row.xml, newRow)
    // cells inherit the row shift from the row element itself
    rebuilt.push(rewriteCellRowsInRow(renumbered, row.row, newRow))
  }
  rebuilt.sort((left, right) => rowNumberOf(left) - rowNumberOf(right))
  return `${prefix}${rebuilt.join('')}${suffix}`
}

function rewriteCellRowsInRow(rowXml: string, oldRow: number, newRow: number): string {
  if (oldRow === newRow) return rowXml
  return rowXml.replace(
    new RegExp(`\\br="([A-Z]{1,3})${oldRow}"`, 'g'),
    (_full, letters: string) => `r="${letters}${newRow}"`,
  )
}

function rowNumberOf(rowXml: string): number {
  return Number(rowXml.match(/\br="([0-9]+)"/)?.[1] ?? '0')
}

/// Column insert/remove: cells inside every row renumber and re-sort,
/// deleted cells drop. Row elements themselves stay.
export function applyColumnShift(worksheetXml: string, spec: ShiftSpec): string {
  const { prefix, rows, suffix } = parseSheetRows(worksheetXml)
  const rebuilt = rows.map((row) => {
    const rowMatch = row.xml.match(/^(<row\b[^>]*>)([\s\S]*?)(<\/row>)$/) ?? (() => {
      // self-closing row: nothing to shift inside
      const selfClosing = row.xml.match(/^(<row\b[^>]*\/>)$/) ?? null
      return selfClosing
    })()
    if (!rowMatch || rowMatch.length < 3) return row.xml
    const open = rowMatch[1] ?? ''
    const inner = rowMatch[2] ?? ''
    const close = rowMatch[3] ?? ''
    const cells: string[] = []
    for (const cellMatch of inner.matchAll(/<c\b[^>]*?(?:\/>|>[\s\S]*?<\/c>)/g)) {
      const cellXml = cellMatch[0]
      const address = cellXml.match(/\br="([A-Z]{1,3})([0-9]+)"/)
      if (!address?.[1] || address[2] === undefined) {
        cells.push(cellXml) // addressless cell: keep in place
        continue
      }
      const shifted = shiftIndex(columnIndex(address[1]), spec)
      if (shifted === null) continue // cell inside the deleted region
      cells.push(
        cellXml.replace(/\br="[A-Z]{1,3}[0-9]+"/, () => `r="${columnLabel(shifted)}${address[2]}"`),
      )
    }
    cells.sort((left, right) => columnNumberOf(left) - columnNumberOf(right))
    return `${open}${cells.join('')}${close}`
  })
  return `${prefix}${rebuilt.join('')}${suffix}`
}

function columnNumberOf(cellXml: string): number {
  const letters = cellXml.match(/\br="([A-Z]{1,3})[0-9]+"/)?.[1] ?? 'A'
  return columnIndex(letters)
}

/// mergeCell refs shift with the op; fully-deleted merges drop.
export function shiftMerges(worksheetXml: string, spec: ShiftSpec): string {
  if (!worksheetXml.includes('<mergeCell')) return worksheetXml
  return worksheetXml.replace(
    /<mergeCell\b[^>]*\bref="([^"]+)"[^>]*\/>/g,
    (full, reference: string) => {
      const parts = reference.split(':')
      const first = parts[0]
      const second = parts[1] ?? first
      if (!first || !second) return full
      const parse = (token: string): RefPart | null => {
        const match = token.match(/^(\$?)([A-Z]{1,3})(\$?)([0-9]+)$/)
        if (!match?.[2] || match[4] === undefined) return null
        return {
          colAbs: match[1] ?? '',
          col: columnIndex(match[2]),
          rowAbs: match[3] ?? '',
          row: Number(match[4]) - 1,
        }
      }
      const a = parse(first)
      const b = parse(second)
      if (!a || !b) return full
      const sa = shiftRefPart(a, spec)
      const sb = shiftRefPart(b, spec)
      if (!sa && !sb) return '' // merge fully inside the deleted region
      const start = sa ?? clampRefPart(a, spec, 'start')
      const end = sb ?? clampRefPart(b, spec, 'end')
      return `<mergeCell ref="${formatRef(start)}:${formatRef(end)}"/>`
    },
  )
}

function rewriteDimension(worksheetXml: string, spec: ShiftSpec): string {
  return worksheetXml.replace(
    /(<dimension\b[^>]*\bref=")([^"]+)(")/,
    (full, prefix: string, reference: string, suffix: string) => {
      const parts = reference.split(':')
      const first = parts[0]
      const second = parts[1] ?? first
      if (!first || !second) return full
      const parse = (token: string): RefPart | null => {
        const match = token.match(/^(\$?)([A-Z]{1,3})(\$?)([0-9]+)$/)
        if (!match?.[2] || match[4] === undefined) return null
        return {
          colAbs: match[1] ?? '',
          col: columnIndex(match[2]),
          rowAbs: match[3] ?? '',
          row: Number(match[4]) - 1,
        }
      }
      const a = parse(first)
      const b = parse(second)
      if (!a || !b) return full
      const sa = shiftRefPart(a, spec)
      const sb = shiftRefPart(b, spec)
      if (!sa || !sb) return full
      // single-endpoint dimensions stay single-endpoint
      const rendered = parts.length === 1 ? formatRef(sa) : `${formatRef(sa)}:${formatRef(sb)}`
      return `${prefix}${rendered}${suffix}`
    },
  )
}

/// Features whose anchors/ranges this build does not shift: pivot parts
/// (their caches keep worksheet-scoped references genoffice also refuses to
/// rewrite). Everything else — drawings, oleObjects, VML shapes, autoFilter,
/// dataValidations, conditionalFormatting, tables, extLst — either shifts
/// with the op. Known linked CF x14 scopes shift with their base rules; other
/// extLst extensions remain untouched.
const UNSHIFTABLE_MARKERS = [
  '<pivotTable',
  '<pivotSelection',
  // sparkline sources/targets live in the x14 ext and never shift; refuse
  // rather than silently desyncing them
  '<x14:sparklineGroups',
]

export function assertShiftable(worksheetXml: string): void {
  for (const marker of UNSHIFTABLE_MARKERS) {
    if (worksheetXml.includes(marker)) {
      throw new StructuralShiftError(
        `The worksheet carries a feature this build cannot shift around (${marker.slice(1)}) — ` +
          'the structural edit was refused to protect its references.',
      )
    }
  }
}

/// Embedded OLE objects anchor through the worksheet's own `<oleObjects>`
/// (`objectPr/anchor` with drawing-style from/to markers), not the drawing
/// part — so shiftDrawingAnchors never sees them. The saved anchor has to
/// follow or the object jumps back over the wrong cells on reopen.
/// Ported from genoffice shiftOleObjectAnchors.
export function shiftOleObjectAnchors(worksheetXml: string, specs: readonly ShiftSpec[]): string {
  if (!worksheetXml.includes('<oleObjects')) return worksheetXml
  return worksheetXml.replace(/<oleObjects\b[\s\S]*?<\/oleObjects>/g, (block) =>
    shiftDrawingAnchors(block, specs),
  )
}

/// VML Pict shapes (form controls) anchor through 8-value `<x:Anchor>` rows
/// of [col, colOff, row, rowOff, col2, colOff2, row2, rowOff2]. Marks shift
/// with the drawing-anchor rules; clamps zero the pixel offset.
/// Ported (lean, linear ops only) from genoffice shiftVmlObjectAnchors.
export function shiftVmlObjectAnchors(vmlXml: string, specs: readonly ShiftSpec[]): string {
  if (specs.length === 0 || !vmlXml.includes('ObjectType="Pict"')) return vmlXml
  return vmlXml.replace(/<v:shape\b[\s\S]*?<\/v:shape>/g, (shape) => {
    if (!/<x:ClientData\b[^>]*\bObjectType="Pict"/.test(shape)) return shape
    return shape.replace(
      /(<x:Anchor>)([^<]*)(<\/x:Anchor>)/,
      (full, open: string, inner: string, close: string) => {
        const values = inner.split(',').map((part) => Number(part.trim()))
        if (values.length !== 8 || values.some((value) => !Number.isFinite(value))) return full
        return `${open}${shiftVmlAnchorValues(values, specs).join(', ')}${close}`
      },
    )
  })
}

function shiftVmlAnchorValues(values: readonly number[], specs: readonly ShiftSpec[]): number[] {
  const next = [...values]
  for (const spec of specs) {
    // [col, colOff, row, rowOff, col2, colOff2, row2, rowOff2]
    const from = spec.axis === 'row' ? 2 : 0
    const to = from + 4
    for (const at of [from, to]) {
      const moved = moveAnchorMark(next[at]!, spec)
      next[at] = moved.position
      if (moved.clamped) next[at + 1] = 0
    }
  }
  return next
}

// ── drawing anchors ─────────────────────────────────────────────────────

/// Linear anchor-mark semantics (genoffice moveAnchorMark): inserts move
/// marks at/after the boundary; deletes move later marks up and clamp marks
/// inside the deleted region to its start (zeroing the offset).
function moveAnchorMark(position: number, spec: ShiftSpec): { position: number; clamped: boolean } {
  if (spec.delta > 0) {
    return { position: position >= spec.start ? position + spec.delta : position, clamped: false }
  }
  const end = spec.start - spec.delta // exclusive end of the deleted region
  if (position >= end) return { position: position + spec.delta, clamped: false }
  if (position >= spec.start) return { position: spec.start, clamped: true }
  return { position, clamped: false }
}

/// Rewrites chart series references (`<c:f>` bodies, e.g. `Sheet1!$B$2:$B$4`)
/// along one shift. Chart refs are always sheet-qualified, so only refs
/// explicitly pointing at the operated sheet move — other sheets' refs stay.
/// Series caches (numCache/strCache) are left as-is: Excel recomputes them on
/// load, and shifting cached values without recomputation would be a lie.
export function shiftChartSeriesReferences(
  chartXml: string,
  spec: ShiftSpec,
  sheetName: string,
): string {
  return chartXml.replace(
    /(<c:f>)([\s\S]*?)(<\/c:f>)/g,
    (full: string, open: string, body: string, close: string) => {
      const shifted = shiftFormulaText(decodeXmlText(body), spec, false, sheetName)
      if (shifted === body) return full
      return `${open}${escapeXmlText(shifted)}${close}`
    },
  )
}

/// Shifts xdr:from/to row|col markers in a drawing part along the op stream.
export function shiftDrawingAnchors(drawingXml: string, specs: readonly ShiftSpec[]): string {
  let xml = drawingXml
  for (const spec of specs) {
    const tag = spec.axis === 'row' ? 'row' : 'col'
    xml = xml.replace(
      /<((?:\w+:)?)(from|to)>([\s\S]*?)<\/\1\2>/g,
      (full, ns: string, kind: string, inner: string) => {
        if (
          !new RegExp(`<(?:\\w+:)?${tag}>[0-9]+</(?:\\w+:)?${tag}>`).test(inner)
        ) {
          return full // this from/to pair has no marker on the shifted axis
        }
        let clamped = false
        const patched = inner.replace(
          new RegExp(`(<(?:\\w+:)?${tag}>)([0-9]+)(</(?:\\w+:)?${tag}>)`),
          (_m, open: string, value: string, close: string) => {
            const moved = moveAnchorMark(Number(value), spec)
            clamped = moved.clamped
            return `${open}${moved.position}${close}`
          },
        )
        const withOffsets = clamped
          ? patched.replace(
              new RegExp(`(<(?:\\w+:)?${tag}Off>)-?[0-9]+(</(?:\\w+:)?${tag}Off>)`),
              (m, open: string, close: string) => `${open}0${close}`,
            )
          : patched
        return `<${ns}${kind}>${withOffsets}</${ns}${kind}>`
      },
    )
  }
  return xml
}

// ── ranged features on the worksheet ────────────────────────────────────

/// A1:B3 (or single A1) → shifted, or null when fully inside the deleted region.
export function shiftRangeReference(reference: string, spec: ShiftSpec): string | null {
  const parts = reference.split(':')
  const first = parts[0]
  const second = parts[1] ?? first
  if (!first || !second) return null
  const parse = (token: string): RefPart | null => {
    const match = token.match(/^(\$?)([A-Z]{1,3})(\$?)([0-9]+)$/)
    if (!match?.[2] || match[4] === undefined) return null
    return {
      colAbs: match[1] ?? '',
      col: columnIndex(match[2]),
      rowAbs: match[3] ?? '',
      row: Number(match[4]) - 1,
    }
  }
  const a = parse(first)
  const b = parse(second)
  if (!a || !b) return null
  const sa = shiftRefPart(a, spec)
  const sb = shiftRefPart(b, spec)
  if (!sa && !sb) return null
  const start = sa ?? clampRefPart(a, spec, 'start')
  const end = sb ?? clampRefPart(b, spec, 'end')
  return parts.length === 1 ? formatRef(start) : `${formatRef(start)}:${formatRef(end)}`
}

function shiftSqrefAttribute(sqref: string, spec: ShiftSpec): { sqref: string; allDead: boolean } {
  const refs = sqref.trim().split(/\s+/).filter(Boolean)
  const shifted = refs.map((ref) => shiftRangeReference(ref, spec))
  const alive = shifted.filter((ref): ref is string => ref !== null)
  if (alive.length === 0) return { sqref: '', allDead: true }
  return { sqref: alive.join(' '), allDead: false }
}

/// First column (0-based) of an A1 range token; 0 when unparseable.
function refStartColumn(reference: string): number {
  const token = reference.split(':')[0] ?? reference
  const match = token.match(/^(\$?)([A-Z]{1,3})/)
  return match?.[2] ? columnIndex(match[2]) : 0
}

/// One worksheet-level autoFilter element along the op: the ref moves, and on
/// column ops the filterColumn colIds follow (a colId is an offset from the
/// range's first column, so its base moves with the ref — the same rebase
/// Excel performs, and the table-part shift already mirrors). Columns deleted
/// out of the range drop their filterColumn; a fully deleted ref drops the
/// element. Row ops never touch colIds. Criteria bodies (values/customs/
/// dateGroupItem buckets) carry no coordinates of their own — a dateGroupItem
/// describes an attribute bucket (year/month/day/...), not a cell address —
/// so they ride along verbatim inside the shifted element.
function shiftAutoFilterElement(
  attributes: string,
  body: string | undefined,
  spec: ShiftSpec,
): string | null {
  const reference = readXmlAttribute(attributes, 'ref')
  if (reference === undefined) return null
  const shifted = shiftRangeReference(reference, spec)
  if (shifted === null) return null
  const shiftedAttributes = attributes.replace(reference, () => shifted)
  if (body === undefined) return `<autoFilter${shiftedAttributes}/>`
  let shiftedBody = body
  if (spec.axis === 'column') {
    const oldStart = refStartColumn(reference)
    const newStart = refStartColumn(shifted)
    shiftedBody = body.replace(
      /<filterColumn\b([^>]*?)(\/>|>[\s\S]*?<\/filterColumn>)/g,
      (element, columnAttributes: string) => {
        const raw = readXmlAttribute(columnAttributes, 'colId')
        if (raw === undefined || !/^\d+$/.test(raw)) return element
        const moved = shiftIndex(oldStart + Number(raw), spec)
        if (moved === null) return '' // column deleted → its criteria die with it
        return element.replace(
          /(\bcolId=")([0-9]+)(")/,
          (_m, prefix: string, _value: string, suffix: string) =>
            `${prefix}${moved - newStart}${suffix}`,
        )
      },
    )
  }
  return `<autoFilter${shiftedAttributes}>${shiftedBody}</autoFilter>`
}

/// Shifts autoFilter@ref (with per-column criteria), dataValidation sqrefs,
/// conditionalFormatting sqref, and hyperlink ref anchors with the op.
/// Elements whose every reference dies are dropped (the rows they annotated
/// are gone).
/** Only migrate source-verified base/x14 twins; unrelated extensions stay raw. */
function shiftLinkedConditionalFormats(xml: string, spec: ShiftSpec): string {
  const twins = extractElements(xml, 'x14:conditionalFormatting')
  const replacements = new Map<string, string>()
  const usedIds = new Set<string>()
  const namespaces = (name: string, uri: string) => {
    const values = [...xml.matchAll(new RegExp(`\\bxmlns:${name}\\s*=\\s*["']([^"']+)["']`, 'g'))]
    return values.length > 0 && values.every(value => value[1] === uri)
  }
  for (const base of extractElements(xml, 'conditionalFormatting')) {
    const sqref = readXmlAttribute(base, 'sqref')
    for (const rule of extractElements(base, 'cfRule')) {
      const ids = extractElements(rule, 'x14:id')
      if (!ids.length) continue
      const id = decodeXmlText(ids[0]!.replace(/^<[^>]*>|<\/[^>]*>$/g, ''))
      const matches = twins.filter(twin => extractElements(twin, 'x14:cfRule').some(entry => readXmlAttribute(entry, 'id') === id))
      if (ids.length !== 1 || !id || usedIds.has(id) || matches.length !== 1 || !sqref ||
          !namespaces('x14', 'http://schemas.microsoft.com/office/spreadsheetml/2009/9/main') ||
          !namespaces('xm', 'http://schemas.microsoft.com/office/excel/2006/main')) {
        throw new StructuralShiftError('Conditional-formatting linked identity is missing or ambiguous.')
      }
      usedIds.add(id)
      const twin = matches[0]!, rules = extractElements(twin, 'x14:cfRule'), refs = extractElements(twin, 'xm:sqref')
      if (rules.length !== 1 || refs.length !== 1 ||
          decodeXmlText(refs[0]!.replace(/^<[^>]*>|<\/[^>]*>$/g, '')) !== sqref ||
          readXmlAttribute(rules[0]!, 'type') !== readXmlAttribute(rule, 'type') ||
          readXmlAttribute(rules[0]!, 'priority') !== readXmlAttribute(rule, 'priority')) {
        throw new StructuralShiftError('Conditional-formatting linked scope differs from its base rule.')
      }
      const shifted = shiftSqrefAttribute(sqref, spec)
      replacements.set(twin, shifted.allDead ? '' : twin.replace(refs[0]!, () => refs[0]!.replace(/>[^<]*</, () => `>${escapeXmlText(shifted.sqref)}<`)))
    }
  }
  for (const [original, replacement] of replacements) xml = xml.replace(original, () => replacement)
  // Remove only the known CF container/extension when its last twin dies.
  xml = xml.replace(/<x14:conditionalFormattings\b[^>]*>\s*<\/x14:conditionalFormattings>/g, '')
  return xml.replace(/<ext\b([^>]*)>\s*<\/ext>/g, (full, attributes: string) =>
    readXmlAttribute(attributes, 'uri') === '{78C0D931-6437-407D-A8EE-F0AAD7539E65}' ? '' : full)
}

export function shiftRangedFeatures(worksheetXml: string, spec: ShiftSpec): string {
  let xml = shiftLinkedConditionalFormats(worksheetXml, spec).replace(
    /<autoFilter\b([^>]*?)(\/>|>([\s\S]*?)<\/autoFilter>)/g,
    (_full, attributes: string, _tail: string, body: string | undefined) => {
      const shifted = shiftAutoFilterElement(attributes, body, spec)
      return shifted ?? ''
    },
  )
  xml = xml.replace(
    /<dataValidation\b[^>]*?\bsqref="([^"]+)"[^>]*?(?:\/>|>[\s\S]*?<\/dataValidation>)/g,
    (full, sqref: string) => {
      const shifted = shiftSqrefAttribute(sqref, spec)
      return shifted.allDead ? '' : full.replace(sqref, () => shifted.sqref)
    },
  )
  xml = xml.replace(
    /<conditionalFormatting\b([^>]*?\bsqref=")([^"]+)(")([^>]*)>([\s\S]*?)<\/conditionalFormatting>/g,
    (full, open: string, sqref: string, closeQuote: string, rest: string, body: string) => {
      const shifted = shiftSqrefAttribute(sqref, spec)
      return shifted.allDead ? '' : `<conditionalFormatting${open}${shifted.sqref}${closeQuote}${rest}>${body}</conditionalFormatting>`
    },
  )
  xml = xml.replace(
    /<x14:dataValidation\b[^>]*>[\s\S]*?<\/x14:dataValidation>/g,
    (full) => {
      const sqref = full.match(/<xm:sqref\b[^>]*>([\s\S]*?)<\/xm:sqref>/)
      if (!sqref) return full
      const shifted = shiftSqrefAttribute(decodeXmlText(sqref[1]!), spec)
      return shifted.allDead ? '' : full.replace(sqref[0], () => '<xm:sqref>' + escapeXmlText(shifted.sqref) + '</xm:sqref>')
    },
  )
  xml = xml.replace(/<(x14:)?dataValidations\b([^>]*)>([\s\S]*?)<\/(?:x14:)?dataValidations>/g,
    (_full, namespace: string | undefined, attributes: string, body: string) => {
      const count = [...body.matchAll(/<(?:x14:)?dataValidation\b/g)].length
      if (!count) return ''
      const attrs = attributes.replace(/\s+count="[^"]*"/, '')
      return `<${namespace ?? ""}dataValidations${attrs} count="${count}">${body}</${namespace ?? ""}dataValidations>`
    })
  xml = xml.replace(/<ext\b([^>]*)>\s*<\/ext>/g, (full, attrs: string) =>
    readXmlAttribute(attrs, 'uri') === '{CCE6A557-97BC-4b89-ADB6-D9C93CAAB3DF}' ? '' : full)
  xml = xml.replace(/<extLst\b[^>]*>\s*<\/extLst>/g, '')
  return xml.replace(
    /(<hyperlink\b[^>]*?\bref=")([^"]+)(")/g,
    (full, prefix: string, reference: string, suffix: string) => {
      const shifted = shiftRangeReference(reference, spec)
      return shifted === null ? full : `${prefix}${shifted}${suffix}`
    },
  )
}

/// 固定来源 transformColDefinitions：整列定义随列身份迁移，范围内插入扩展，删除裁剪。
function shiftColumnDefinitions(xml: string, spec: ShiftSpec): string {
  const definitions = [...xml.matchAll(/<col\b([^>]*?)\/>/g)].map(match => ({
    min: Number(match[1]!.match(/(?:^|\s)min\s*=\s*(["'])([0-9]+)\1/)?.[2]),
    max: Number(match[1]!.match(/(?:^|\s)max\s*=\s*(["'])([0-9]+)\1/)?.[2]),
  })).sort((a, b) => a.min - b.min)
  for (let index = 0; index < definitions.length; index++) {
    const range = definitions[index]!
    if (!Number.isInteger(range.min) || !Number.isInteger(range.max) || range.min < 1 || range.max < range.min || range.max > 16384)
      throw new StructuralShiftError('列定义范围无效，无法安全移动列。')
    if (index && range.min <= definitions[index - 1]!.max) throw new StructuralShiftError('列定义范围重叠，无法安全移动列。')
  }
  return xml.replace(/<col\b([^>]*?)\/>/g, (full, attrs: string) => {
    const min = Number(attrs.match(/(?:^|\s)min\s*=\s*(["'])([0-9]+)\1/)?.[2]) - 1, max = Number(attrs.match(/(?:^|\s)max\s*=\s*(["'])([0-9]+)\1/)?.[2]) - 1
    const first = shiftIndex(min, spec), last = shiftIndex(max, spec)
    if (first === null && last === null) return ''
    const start = first ?? spec.start, end = last ?? spec.start - 1
    if (end >= 16384) throw new StructuralShiftError('列定义超出工作表宽度。')
    return full.replace(/(\smin\s*=\s*["'])[0-9]+(["'])/, `$1${start + 1}$2`)
      .replace(/(\smax\s*=\s*["'])[0-9]+(["'])/, `$1${end + 1}$2`)
  })
}

/// Apply one structural op to the target worksheet part (same-sheet view).
export function applyStructuralOp(
  worksheetXml: string,
  op: StructuralOp,
  sheetName: string,
): string {
  const spec = shiftSpecOf(op)
  let xml =
    spec.axis === 'row' ? applyRowShift(worksheetXml, spec) : applyColumnShift(worksheetXml, spec)
  if (spec.axis === 'column') xml = shiftColumnDefinitions(xml, spec)
  xml = shiftWorksheetFormulas(xml, spec, sheetName, true)
  xml = shiftMerges(xml, spec)
  xml = shiftWorksheetPageBreaks(xml, spec)
  xml = shiftRangedFeatures(xml, spec)
  xml = rewriteDimension(xml, spec)
  return shiftOleObjectAnchors(xml, [spec])
}

// ── table parts (ported, lean, from genoffice shiftTablePart) ───────────

interface TablePartArea {
  readonly name: string
  readonly startRow: number
  readonly endRow: number
  readonly startColumn: number
  readonly endColumn: number
  readonly headerRows: number
  readonly totalsRows: number
}

export interface TableInsertion {
  /// 0-based sheet row of the table header, post-shift; null without a header.
  readonly headerRow: number | null
  readonly columns: ReadonlyArray<{ column: number; name: string }>
}

function parseA1Token(token: string): { row: number; column: number } | null {
  const match = token.match(/^(\$?)([A-Z]{1,3})(\$?)([0-9]+)$/)
  if (!match?.[2] || match[4] === undefined) return null
  let column = 0
  for (const character of match[2]) column = column * 26 + character.charCodeAt(0) - 64
  return { row: Number(match[4]) - 1, column: column - 1 }
}

function parseTablePart(tableXml: string): TablePartArea {
  const open = tableXml.match(/<table\b[^>]*>/)?.[0]
  const ref = open === undefined ? undefined : open.match(/\bref="([^"]+)"/)?.[1]
  const parts = (ref ?? '').split(':')
  const start = parseA1Token(parts[0] ?? '')
  const end = parseA1Token(parts[1] ?? parts[0] ?? '')
  if (!open || !start || !end) {
    throw new StructuralShiftError('An Excel table part has no readable ref — aborted.')
  }
  return {
    name: decodeXmlText(open.match(/\bname="([^"]*)"/)?.[1] ?? 'Table'),
    startRow: start.row,
    endRow: end.row,
    startColumn: start.column,
    endColumn: end.column,
    headerRows: Number(open.match(/\bheaderRowCount="([0-9]+)"/)?.[1] ?? '1'),
    totalsRows: Number(open.match(/\btotalsRowCount="([0-9]+)"/)?.[1] ?? '0'),
  }
}

interface TableColumnElement {
  readonly start: number
  readonly end: number
  readonly id: number
  readonly name: string
}

function listTableColumns(tableXml: string): TableColumnElement[] {
  const elements: TableColumnElement[] = []
  for (const match of tableXml.matchAll(/<tableColumn\b[^>]*?(?:\/>|>[\s\S]*?<\/tableColumn>)/g)) {
    const open = match[0].match(/^<tableColumn\b[^>]*/)?.[0] ?? ''
    elements.push({
      start: match.index,
      end: match.index + match[0].length,
      id: Number(open.match(/\bid="([0-9]+)"/)?.[1] ?? '0'),
      name: decodeXmlText(open.match(/\bname="([^"]*)"/)?.[1] ?? ''),
    })
  }
  return elements
}

function setTableColumnsCount(tableXml: string, count: number): string {
  return tableXml.replace(
    /(<tableColumns\b[^>]*?\bcount=")[0-9]+(")/,
    (_m, prefix: string, suffix: string) => `${prefix}${count}${suffix}`,
  )
}

/// Deleted index range (inclusive, pre-op space) of a delete spec.
function deletedSpan(spec: ShiftSpec): { start: number; end: number } | null {
  return spec.delta < 0 ? { start: spec.start, end: spec.start - spec.delta - 1 } : null
}

function assertTableRowShiftSupported(table: TablePartArea, spec: ShiftSpec): void {
  const deleted = deletedSpan(spec)
  if (!deleted) return
  const overlaps = (a: number, b: number): boolean => deleted.start <= b && a <= deleted.end
  if (table.headerRows > 0 && overlaps(table.startRow, table.startRow + table.headerRows - 1)) {
    throw new StructuralShiftError(
      `Deleting the header row of table "${table.name}" is not supported.`,
    )
  }
  if (table.totalsRows > 0 && overlaps(table.endRow - table.totalsRows + 1, table.endRow)) {
    throw new StructuralShiftError(
      `Deleting the totals row of table "${table.name}" is not supported.`,
    )
  }
  const movedStart = shiftIndex(table.startRow, spec) ?? spec.start
  const movedEnd = shiftIndex(table.endRow, spec) ?? spec.start - 1
  const dataRows = movedEnd - movedStart + 1 - table.headerRows - table.totalsRows
  if (dataRows < 1) {
    throw new StructuralShiftError(
      `Deleting these rows would leave table "${table.name}" without data rows — not supported.`,
    )
  }
}

function reshapeTableColumns(
  tableXml: string,
  table: TablePartArea,
  spec: ShiftSpec,
  records: TableInsertion[],
): string {
  const width = table.endColumn - table.startColumn + 1
  const deleted = deletedSpan(spec)
  if (deleted) {
    if (!(deleted.start <= table.endColumn && table.startColumn <= deleted.end)) return tableXml
    if (deleted.start <= table.startColumn && deleted.end >= table.endColumn) {
      throw new StructuralShiftError(
        `Deleting all columns of table "${table.name}" is not supported — delete the table first.`,
      )
    }
    const columns = tableColumnsOrAbort(tableXml, table, width)
    const first = Math.max(deleted.start, table.startColumn) - table.startColumn
    const last = Math.min(deleted.end, table.endColumn) - table.startColumn
    const removed = last - first + 1
    let xml =
      tableXml.slice(0, columns[first]!.start) + tableXml.slice(columns[last]!.end)
    xml = setTableColumnsCount(xml, width - removed)
    xml = xml.replace(
      /<filterColumn\b[^>]*?\bcolId="([0-9]+)"[^>]*?(?:\/>|>[\s\S]*?<\/filterColumn>)/g,
      (full, colId: string) => {
        const id = Number(colId)
        if (id >= first && id <= last) return ''
        if (id > last) {
          return full.replace(
            /(\bcolId=")[0-9]+(")/,
            (_m, prefix: string, suffix: string) => `${prefix}${id - removed}${suffix}`,
          )
        }
        return full
      },
    )
    // sort conditions on removed columns keep a stale ref otherwise — drop them
    const deletedStart = table.startColumn + first
    const deletedEnd = table.startColumn + last
    xml = xml.replace(/<sortCondition\b[^>]*?\bref="([^"]+)"[^>]*?\/>/g, (full, ref: string) => {
      const refParts = ref.split(':')
      const startRef = parseA1Token(refParts[0] ?? '')
      const endRef = parseA1Token(refParts[1] ?? refParts[0] ?? '')
      if (!startRef || !endRef) return full
      return startRef.column >= deletedStart && endRef.column <= deletedEnd ? '' : full
    })
    return xml.replace(/<sortState\b[^>]*>\s*<\/sortState>/g, '')
  }
  // insert: only when the insertion point is strictly inside the table span
  if (spec.start <= table.startColumn || spec.start > table.endColumn) return tableXml
  const columns = tableColumnsOrAbort(tableXml, table, width)
  const position = spec.start - table.startColumn
  const taken = new Set(columns.map((column) => column.name.toLowerCase()))
  let nextId = Math.max(0, ...columns.map((column) => column.id)) + 1
  let seed = 1
  const record: { headerRow: number | null; columns: Array<{ column: number; name: string }> } = {
    headerRow: table.headerRows > 0 ? table.startRow : null,
    columns: [],
  }
  let inserted = ''
  for (let offset = 0; offset < spec.delta; offset += 1) {
    let name = `Column${seed}`
    while (taken.has(name.toLowerCase())) {
      seed += 1
      name = `Column${seed}`
    }
    taken.add(name.toLowerCase())
    inserted += `<tableColumn id="${nextId}" name="${name}"/>`
    record.columns.push({ column: spec.start + offset, name })
    nextId += 1
  }
  records.push(record)
  const at = columns[position]!.start
  let xml = tableXml.slice(0, at) + inserted + tableXml.slice(at)
  xml = setTableColumnsCount(xml, width + spec.delta)
  return xml.replace(
    /(<filterColumn\b[^>]*?\bcolId=")([0-9]+)(")/g,
    (full, prefix: string, colId: string, suffix: string) =>
      Number(colId) >= position ? `${prefix}${Number(colId) + spec.delta}${suffix}` : full,
  )
}

function tableColumnsOrAbort(
  tableXml: string,
  table: TablePartArea,
  width: number,
): TableColumnElement[] {
  const columns = listTableColumns(tableXml)
  if (columns.length !== width) {
    throw new StructuralShiftError(
      `Table "${table.name}" has ${columns.length} column entries for ${width} columns — aborted.`,
    )
  }
  return columns
}

/// Shifts a table part along the op stream: ref/autoFilter/sortState ranges
/// move, column inserts/deletes inside the span reshape tableColumns the way
/// Excel does (unique "ColumnN" names, filterColumn colId follow). Inserted
/// columns are reported so the caller can write their header cell text.
export function shiftTablePart(
  tableXml: string,
  specs: readonly ShiftSpec[],
): { xml: string; insertions: TableInsertion[] } {
  let xml = tableXml
  const records: MutableInsertion[] = []
  for (const spec of specs) {
    const table = parseTablePart(xml)
    // earlier insertion records hold post-op coordinates; later ops move them
    for (const record of records) {
      if (spec.axis === 'row') {
        if (record.headerRow !== null) {
          record.headerRow = shiftIndex(record.headerRow, spec) ?? record.headerRow
        }
        continue
      }
      record.columns = record.columns.flatMap((column) => {
        const moved = shiftIndex(column.column, spec)
        return moved === null ? [] : [{ ...column, column: moved }]
      })
    }
    if (spec.axis === 'row') assertTableRowShiftSupported(table, spec)
    else xml = reshapeTableColumns(xml, table, spec, records)
    xml = xml.replace(
      /(<(?:table|autoFilter|sortState|sortCondition)\b[^>]*?\bref=")([^"]+)(")/g,
      (full, prefix: string, ref: string, suffix: string) => {
        const moved = shiftRangeReference(ref, spec)
        return moved === null ? full : `${prefix}${moved}${suffix}`
      },
    )
  }
  return { xml, insertions: records.map((record) => ({ ...record })) }
}

interface MutableInsertion {
  headerRow: number | null
  columns: Array<{ column: number; name: string }>
}

export { FORMULA_REFERENCE_PATTERN, qualifierMatches }
