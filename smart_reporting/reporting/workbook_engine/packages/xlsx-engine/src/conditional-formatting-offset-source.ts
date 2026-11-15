// Fixed GenOffice formula-shift.ts copy/fill subset; local token guards also
// protect implicit structured references, Unicode/named tokens and 3D sheets.
import {columnIndex,columnLabel} from './cell-address'
const MAX_GRID_ROWS=1048576,MAX_GRID_COLUMNS=16384
interface RefPart {readonly colAbs:string;readonly col:number;readonly rowAbs:string;readonly row:number}
function formatRef(part:RefPart):string{return `${part.colAbs}${columnLabel(part.col)}${part.rowAbs}${part.row+1}`}
const REF_RE =
  /(?<![\p{L}\p{N}\p{M}_.$!\\])(?:(?:'((?:[^']|'')+)'|([\p{L}\p{N}\p{M}_.]+(?::[\p{L}\p{N}\p{M}_.]+)?))!)?(\$?)([A-Z]{1,3})(\$?)([0-9]{1,7})(?::(\$?)([A-Z]{1,3})(\$?)([0-9]{1,7}))?(?![\p{L}\p{N}\p{M}_.(!\\])/giu

// Protect names and literal spans before shifting the remaining references.
function formulaSegments(formula: string): string[] {
  // Alternating rewritable/protected spans, matching the old split contract.
  // Every bracketed reference is protected, including [@A1] inside a table.
  // Apostrophes escape special characters inside structured column names.
  const segments: string[] = []
  let start = 0, index = 0
  while (index < formula.length) {
    const character = formula[index]
    // Treat the sheet qualifier as an opaque span, separately from the range
    // operator. This covers S1:S3!A1 and Sheet1!A1:Sheet1!A2 without confusing
    // reference-shaped sheet names with cell endpoints.
    const boundary = index === 0 || !/[\p{L}\p{N}\p{M}_.$!\\]/u.test(formula[index - 1]!)
    const qualifier = boundary ? formula.slice(index).match(/^(?:'(?:[^']|'')*'|[\p{L}\p{N}\p{M}_.\\]+)(?::(?:'(?:[^']|'')*'|[\p{L}\p{N}\p{M}_.\\]+))?!/u)?.[0] : undefined
    if (qualifier) {
      segments.push(formula.slice(start, index), qualifier)
      index += qualifier.length
      start = index
      continue
    }
    if (character === "'") {
      index++
      while (index < formula.length) {
        if (formula[index++] !== "'") continue
        if (formula[index] === "'") { index++; continue }
        break
      }
      continue
    }
    if (character !== '"' && character !== '[') { index++; continue }
    const protectedStart = index++
    if (character === '"') {
      while (index < formula.length) {
        if (formula[index++] !== '"') continue
        if (formula[index] === '"') { index++; continue }
        break
      }
    } else {
      let depth = 1
      while (index < formula.length && depth > 0) {
        const token = formula[index++]
        if (token === "'" && /[\[\]'#@]/.test(formula[index] ?? '')) { index++; continue }
        if (token === '[') depth++
        if (token === ']') depth--
      }
    }
    segments.push(formula.slice(start, protectedStart), formula.slice(protectedStart, index))
    start = index
  }
  segments.push(formula.slice(start))
  return segments
}

function offsetRefPart(part: RefPart, rowDelta: number, columnDelta: number): RefPart | null {
  const row = part.rowAbs === '$' ? part.row : part.row + rowDelta
  const col = part.colAbs === '$' ? part.col : part.col + columnDelta
  if (row < 0 || row >= MAX_GRID_ROWS || col < 0 || col >= MAX_GRID_COLUMNS) return null
  return { ...part, row, col }
}

// Whole-column spans (B:D) — REF_RE only matches refs with a row component,
// so these need their own pass (fill-right must shift =SUM(B:B) to =SUM(C:C)).
// The `:` in the lookbehind stops the second column of one span (or the end
// cell of B2:D4) from starting a new match. Quoted names use '' escaping like REF_RE.
const COLUMN_SPAN_RE =
  /(?<![\p{L}\p{N}\p{M}_.$!\\])(?:(?:'((?:[^']|'')+)'|([\p{L}\p{N}\p{M}_.]+(?::[\p{L}\p{N}\p{M}_.]+)?))!)?(\$?)([A-Z]{1,3}):(\$?)([A-Z]{1,3})(?![\p{L}\p{N}\p{M}_.($!:\\])/giu

// Whole-row spans (2:4) — the row-axis mirror of COLUMN_SPAN_RE, same
// lookbehind and '' sheet-name escaping.
const ROW_SPAN_RE =
  /(?<![\p{L}\p{N}\p{M}_.$!\\])(?:(?:'((?:[^']|'')+)'|([\p{L}\p{N}\p{M}_.]+(?::[\p{L}\p{N}\p{M}_.]+)?))!)?(\$?)([0-9]{1,7}):(\$?)([0-9]{1,7})(?![\p{L}\p{N}\p{M}_.($!:\\])/gu

/**
 * Rewrites A1-style references for COPY/FILL semantics (Excel's fill handle):
 * relative axes shift by the cell's offset from its source cell, `$`-anchored
 * axes stay pinned, and references pushed off the grid become #REF!.
 * Sheet-qualified refs shift too (as in Excel), string literals are skipped,
 * and whole-row spans (3:5) shift on fill-down while whole-column spans
 * shift on fill-right ($ pins either axis; off-grid becomes #REF!).
 */
export function offsetFormulaRefs(formula: string, rowDelta: number, columnDelta: number): string {
  if (rowDelta === 0 && columnDelta === 0) return formula
  const segments = formulaSegments(formula)
  const rewritten = segments.map((segment, index) => {
    if (index % 2 === 1) return segment
    let out = segment.replace(
      REF_RE,
      (match, quoted, bare, aAbsC, aCol, aAbsR, aRow, bAbsC, bCol, bAbsR, bRow) => {
        // Out-of-grid identifiers (XFE1, A1048577) may be defined names.
        const valid = (col: string, row: string) => columnIndex(col) < MAX_GRID_COLUMNS && Number(row) >= 1 && Number(row) <= MAX_GRID_ROWS
        const firstValid = valid(aCol as string, aRow as string)
        const secondValid = bCol !== undefined && valid(bCol as string, bRow as string)
        if (!firstValid && bCol === undefined) return match
        const prefix = quoted !== undefined ? `'${quoted}'!` : bare !== undefined ? `${bare}!` : ''
        const first = firstValid ? offsetRefPart(
          {
            colAbs: aAbsC as string,
            col: columnIndex(aCol as string),
            rowAbs: aAbsR as string,
            row: Number(aRow) - 1,
          },
          rowDelta,
          columnDelta,
        ) : null
        if (bCol === undefined) {
          return first ? `${prefix}${formatRef(first)}` : `${prefix}#REF!`
        }
        const second = secondValid ? offsetRefPart(
          {
            colAbs: bAbsC as string,
            col: columnIndex(bCol as string),
            rowAbs: bAbsR as string,
            row: Number(bRow) - 1,
          },
          rowDelta,
          columnDelta,
        ) : null
        if (firstValid && !first || secondValid && !second) return `${prefix}#REF!`
        const firstText = first ? formatRef(first) : `${aAbsC}${aCol}${aAbsR}${aRow}`
        const secondText = second ? formatRef(second) : `${bAbsC}${bCol}${bAbsR}${bRow}`
        return `${prefix}${firstText}:${secondText}`
      },
    )
    if (columnDelta !== 0) {
      out = out.replace(COLUMN_SPAN_RE, (match, quoted, bare, aAbs, aCol, bAbs, bCol) => {
        if (columnIndex(aCol as string) >= MAX_GRID_COLUMNS || columnIndex(bCol as string) >= MAX_GRID_COLUMNS) return match
        const prefix = quoted !== undefined ? `'${quoted}'!` : bare !== undefined ? `${bare}!` : ''
        // Returns the full component including its anchor ("$B" stays "$B").
        const shift = (abs: string, letters: string): string | null => {
          if (abs === '$') return `$${letters.toUpperCase()}`
          const shifted = columnIndex(letters) + columnDelta
          return shifted < 0 || shifted >= MAX_GRID_COLUMNS ? null : columnLabel(shifted)
        }
        const first = shift(aAbs as string, aCol as string)
        const second = shift(bAbs as string, bCol as string)
        if (first === null || second === null) return `${prefix}#REF!`
        return `${prefix}${first}:${second}`
      })
    }
    // Whole-row spans (2:4): the row-axis mirror of the column pass above
    // (fill-down must shift =SUM(2:4) to =SUM(3:5), like =SUM(B:B) → =SUM(C:C)
    // on fill-right). REF_RE needs a column component, so without this pass
    // whole-row refs silently stay stale on copy/fill.
    if (rowDelta !== 0) {
      out = out.replace(ROW_SPAN_RE, (match, quoted, bare, aAbs, aRow, bAbs, bRow) => {
        if (Number(aRow) < 1 || Number(aRow) > MAX_GRID_ROWS || Number(bRow) < 1 || Number(bRow) > MAX_GRID_ROWS) return match
        const prefix = quoted !== undefined ? `'${quoted}'!` : bare !== undefined ? `${bare}!` : ''
        // Returns the full component including its anchor ("$2" stays "$2").
        const shift = (abs: string, digits: string): string | null => {
          if (abs === '$') return `$${digits}`
          const shifted = Number(digits) - 1 + rowDelta
          return shifted < 0 || shifted >= MAX_GRID_ROWS ? null : String(shifted + 1)
        }
        const first = shift(aAbs as string, aRow as string)
        const second = shift(bAbs as string, bRow as string)
        if (first === null || second === null) return `${prefix}#REF!`
        return `${prefix}${first}:${second}`
      })
    }
    return out
  })
  return rewritten.join('')
}

