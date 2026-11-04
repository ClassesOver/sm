/// CSV import/export. Import parses RFC4180 (quoted fields, embedded
/// newlines/quotes, CRLF) with delimiter sniffing (, ; or tab) and converts
/// to a workbook via the engine write path; export renders a sheet as CSV.

import { applyCellEdits, type CellEdit } from './workbook-write'
import { createBlankWorkbook } from './blank'
import { readWorkbook } from './workbook-read'

const CANDIDATE_DELIMITERS = [',', ';', '\t'] as const

function sniffDelimiter(text: string): string {
  const firstLine = text.split(/\r?\n/, 1)[0] ?? ''
  let best = ','
  let bestCount = 0
  for (const delimiter of CANDIDATE_DELIMITERS) {
    let count = 0
    let quoted = false
    for (const character of firstLine) {
      if (character === '"') quoted = !quoted
      else if (character === delimiter && !quoted) count += 1
    }
    if (count > bestCount) {
      best = delimiter
      bestCount = count
    }
  }
  return best
}

/// RFC4180 parser; returns rows of raw string fields.
export function parseCsv(text: string, delimiter: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index]!
    if (quoted) {
      if (character === '"') {
        if (text[index + 1] === '"') {
          field += '"'
          index += 1
        } else {
          quoted = false
        }
      } else {
        field += character
      }
      continue
    }
    if (character === '"') {
      quoted = true
      continue
    }
    if (character === delimiter) {
      row.push(field)
      field = ''
      continue
    }
    if (character === '\n' || (character === '\r' && text[index + 1] === '\n')) {
      if (character === '\r') index += 1
      row.push(field)
      rows.push(row)
      row = []
      field = ''
      continue
    }
    field += character
  }
  if (field !== '' || row.length > 0) {
    row.push(field)
    rows.push(row)
  }
  // drop a single trailing empty line
  if (rows.length > 0) {
    const last = rows[rows.length - 1]!
    if (last.length === 1 && last[0] === '') rows.pop()
  }
  return rows
}

/// Field text → typed cell value (number / boolean / text; empty → null).
export function typedCsvValue(field: string): string | number | boolean | null {
  if (field === '') return null
  if (/^-?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(field)) {
    // leading zeros signal an identifier-like string (account codes, SKUs):
    // converting would silently drop digits, so keep the text form — same
    // choice Excel makes when typing such values into a General cell
    if (/^-?0\d/.test(field)) return field
    const numeric = Number(field)
    if (Number.isFinite(numeric) && numeric.toString().length <= field.length + 1) return numeric
  }
  if (field.toUpperCase() === 'TRUE') return true
  if (field.toUpperCase() === 'FALSE') return false
  return field
}

function columnLettersOf(index: number): string {
  let label = ''
  let remaining = index + 1
  while (remaining > 0) {
    remaining -= 1
    label = String.fromCharCode(65 + (remaining % 26)) + label
    remaining = Math.floor(remaining / 26)
  }
  return label
}

/// CSV text → workbook package bytes (single sheet, typed values).
export async function csvToWorkbook(text: string, sheetName = 'Sheet1'): Promise<Uint8Array> {
  const normalized = text.replace(/^\uFEFF/, '')
  const delimiter = sniffDelimiter(normalized)
  const rows = parseCsv(normalized, delimiter)
  const blank = await createBlankWorkbook(sheetName)
  const edits: CellEdit[] = []
  rows.forEach((fields, row) => {
    fields.forEach((field, column) => {
      const value = typedCsvValue(field)
      if (value === null) return
      edits.push({
        sheetName,
        row,
        column,
        writeValue: true,
        cell: { value },
      })
    })
  })
  const applied = edits.length > 0 ? await applyCellEdits(blank, edits) : blank
  return applied
}

/// RFC4180 field quoting; shared by the byte-level export and the web
/// readback export (which has computed formula values).
export function csvEscape(value: string): string {
  if (/[",\r\n]/.test(value)) return `"${value.replaceAll('"', '""')}"`
  return value
}

/// Workbook (already imported) → CSV text of one sheet; formulas render as
/// their computed values are unavailable here, so the formula text is kept.
export async function workbookToCsv(
  bytes: Uint8Array,
  sheetName: string | undefined,
): Promise<string> {
  const model = await readWorkbook(bytes)
  const sheet = (sheetName !== undefined
    ? model.sheets.find((candidate) => candidate.name === sheetName)
    : model.sheets[0]) ?? model.sheets[0]
  if (!sheet) return ''
  let maxRow = 0
  let maxColumn = 0
  for (const address of Object.keys(sheet.cells)) {
    const match = address.match(/^([A-Z]{1,3})([0-9]+)$/)
    if (!match?.[1] || !match[2]) continue
    const row = Number(match[2])
    let column = 0
    for (const character of match[1]) column = column * 26 + character.charCodeAt(0) - 64
    maxRow = Math.max(maxRow, row)
    maxColumn = Math.max(maxColumn, column - 1)
  }
  const lines: string[] = []
  for (let row = 1; row <= maxRow; row += 1) {
    const fields: string[] = []
    for (let column = 0; column <= maxColumn; column += 1) {
      const cell = sheet.cells[`${columnLettersOf(column)}${row}`]
      const raw = cell?.formula ?? (cell?.value === null || cell?.value === undefined ? '' : cell.value)
      // Excel spells booleans TRUE/FALSE in CSV; typedCsvValue re-imports those
      // as booleans, so lowercase String(true) would break the round-trip
      const value = typeof raw === 'boolean' ? (raw ? 'TRUE' : 'FALSE') : String(raw)
      fields.push(csvEscape(value))
    }
    lines.push(fields.join(','))
  }
  return lines.join('\r\n')
}
