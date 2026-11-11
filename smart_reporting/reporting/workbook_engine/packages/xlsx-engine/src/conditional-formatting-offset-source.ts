// Fixed GenOffice formula-shift.ts copy/fill subset; imports adapted locally.
import {columnIndex,columnLabel} from './cell-address'
const MAX_GRID_ROWS=1048576,MAX_GRID_COLUMNS=16384
interface RefPart {readonly colAbs:string;readonly col:number;readonly rowAbs:string;readonly row:number}
function formatRef(part:RefPart):string{return `${part.colAbs}${columnLabel(part.col)}${part.rowAbs}${part.row+1}`}
const REF_RE =
  /(?<![A-Za-z0-9_.$!])(?:(?:'((?:[^']|'')+)'|([A-Za-z0-9_.]+))!)?(\$?)([A-Z]{1,3})(\$?)([0-9]{1,7})(?::(\$?)([A-Z]{1,3})(\$?)([0-9]{1,7}))?(?![A-Za-z0-9(])/gi

// Split a formula into the parts REF_RE may rewrite and the parts it must not
// touch: string literals, and a structured reference's bracketed contents.
// A column header is a NAME, not a cell — `Table1[Q1]`, `Table1[@Q1]` and
// `Table1[ Q1 ]` all name the column Q1 and must survive an insert verbatim, as
// must `[[#Headers],[Q1]]`. ONE capturing group around the whole alternation, so
// every protected run lands at an odd index of a split and the existing
// `index % 2` guard covers both kinds. One level of nesting covers [[...],[...]].
// The lookbehind keeps external-workbook prefixes (`[1]Sheet1!A1`, `'[Book.xlsx]Sheet 1'!A1`)
// out of the skip: they follow a quote or `=`/operator, never a table name.
const REWRITE_SKIP_RE = /((?:"(?:[^"]|"")*")|(?:(?<=[A-Za-z0-9_.])\[(?:[^\][]|\[[^\][]*\])*\]))/

function decodeQuotedSheetName(quoted: string): string {
  return quoted.replaceAll("''", "'")
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
  /(?<![A-Za-z0-9_.$!:])(?:(?:'((?:[^']|'')+)'|([A-Za-z0-9_.]+))!)?(\$?)([A-Z]{1,3}):(\$?)([A-Z]{1,3})(?![A-Za-z0-9($!:])/gi

function sheetPrefixApplies(
  quoted: string | undefined,
  bare: string | undefined,
  formulaSheetMatchesOp: boolean,
  opSheetName: string,
): boolean {
  if (quoted === undefined && bare === undefined) return formulaSheetMatchesOp
  const prefixSheet = quoted !== undefined ? decodeQuotedSheetName(quoted) : bare
  if (prefixSheet === undefined) return false
  return prefixSheet.toLowerCase() === opSheetName.toLowerCase()
}

// Whole-row spans (2:4) — the row-axis mirror of COLUMN_SPAN_RE, same
// lookbehind and '' sheet-name escaping.
const ROW_SPAN_RE =
  /(?<![A-Za-z0-9_.$!:])(?:(?:'((?:[^']|'')+)'|([A-Za-z0-9_.]+))!)?(\$?)([0-9]{1,7}):(\$?)([0-9]{1,7})(?![A-Za-z0-9($!:])/g

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
  const segments = formula.split(REWRITE_SKIP_RE)
  const rewritten = segments.map((segment, index) => {
    if (index % 2 === 1) return segment
    let out = segment.replace(
      REF_RE,
      (match, quoted, bare, aAbsC, aCol, aAbsR, aRow, bAbsC, bCol, bAbsR, bRow) => {
        const prefix = quoted !== undefined ? `'${quoted}'!` : bare !== undefined ? `${bare}!` : ''
        const first = offsetRefPart(
          {
            colAbs: aAbsC as string,
            col: columnIndex(aCol as string),
            rowAbs: aAbsR as string,
            row: Number(aRow) - 1,
          },
          rowDelta,
          columnDelta,
        )
        if (bCol === undefined) {
          return first ? `${prefix}${formatRef(first)}` : `${prefix}#REF!`
        }
        const second = offsetRefPart(
          {
            colAbs: bAbsC as string,
            col: columnIndex(bCol as string),
            rowAbs: bAbsR as string,
            row: Number(bRow) - 1,
          },
          rowDelta,
          columnDelta,
        )
        if (!first || !second) return `${prefix}#REF!`
        return `${prefix}${formatRef(first)}:${formatRef(second)}`
      },
    )
    if (columnDelta !== 0) {
      out = out.replace(COLUMN_SPAN_RE, (match, quoted, bare, aAbs, aCol, bAbs, bCol) => {
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

