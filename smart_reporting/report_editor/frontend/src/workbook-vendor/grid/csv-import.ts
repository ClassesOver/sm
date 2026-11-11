// Browser-safe CSV parser/decoder vendored from GenOffice, Apache-2.0.
// Source: packages/xlsx-gateway/src/gateway/csv-import.ts
// Ref: f8c17004fb730df11f0f743164ffd8b4281bb38c

const DELIMITERS = [',', ';', '\t'] as const

/** Excel's sheet bounds; anything past them cannot land in a workbook anyway. */
export const MAX_CSV_ROWS = 1_048_576
export const MAX_CSV_COLS = 16_384

// Excel writes CSV in the system's legacy charset, not UTF-8 (GBK on Chinese
// Windows, Shift_JIS on Japanese), so decoding everything as UTF-8 turns every
// non-ASCII cell into replacement characters.
const LEGACY_CHARSETS = ['gb18030', 'shift_jis', 'big5', 'euc-kr', 'windows-1252'] as const

function decode(bytes: Uint8Array, charset: string, fatal = false): string | null {
  try {
    return new TextDecoder(charset, { fatal }).decode(bytes)
  } catch {
    return null
  }
}

/** how plausible a decoding is: CJK/ASCII good, replacement chars and control bytes bad */
function score(text: string): number {
  let value = 0
  for (const character of text) {
    const code = character.codePointAt(0) ?? 0
    if (character === '�') value -= 20
    else if (code < 0x20 && character !== '\n' && character !== '\r' && character !== '\t')
      value -= 10
    else if (code < 0x7f) value += 1
    // half-width katakana is the signature of double-byte text misread as
    // Shift_JIS, and near-absent from real spreadsheets — never a good sign
    else if (code >= 0xff61 && code <= 0xff9f) value -= 2
    else if (
      (code >= 0x3000 && code <= 0x9fff) || // CJK punctuation, kana, unified ideographs
      (code >= 0xac00 && code <= 0xd7af) || // hangul
      (code >= 0xff00 && code <= 0xffef) // full-width forms
    )
      value += 2
  }
  return value
}

/**
 * Decodes CSV bytes: BOM, then strict UTF-8, then the legacy charsets Excel
 * writes. `preferred` (from the UI language) breaks the ties those charsets
 * produce — GBK and Shift_JIS both decode the same bytes to plausible-looking
 * but different CJK.
 */
/**
 * UTF-16 without a BOM (Excel writes it; editors strip it): NUL bytes then
 * interleave the text, which strict UTF-8 accepts — so this must run before
 * the UTF-8 attempt or the NULs survive as garbage. NUL bytes never occur in
 * UTF-8/legacy CSV text (GBK/Shift_JIS trail bytes exclude 0x00), so any
 * meaningful NUL presence means UTF-16, with the NUL-heavy side picking the
 * byte order (ties go LE, Excel's order).
 */
function sniffUtf16WithoutBom(bytes: Uint8Array): 'utf-16le' | 'utf-16be' | null {
  const sample = bytes.subarray(0, Math.min(bytes.length, 1024))
  let pairs = 0
  let evenNul = 0
  let oddNul = 0
  for (let i = 0; i + 1 < sample.length; i += 2) {
    pairs += 1
    if (sample[i] === 0) evenNul += 1
    if (sample[i + 1] === 0) oddNul += 1
  }
  if (pairs < 2) return null
  if ((evenNul + oddNul) / (pairs * 2) < 0.05) return null
  return oddNul >= evenNul ? 'utf-16le' : 'utf-16be'
}

export function decodeCsvBuffer(bytes: Uint8Array, preferred?: string): string {
  if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
    return decode(bytes.subarray(3), 'utf-8') ?? ''
  }
  if (bytes[0] === 0xff && bytes[1] === 0xfe) return decode(bytes.subarray(2), 'utf-16le') ?? ''
  if (bytes[0] === 0xfe && bytes[1] === 0xff) return decode(bytes.subarray(2), 'utf-16be') ?? ''
  const bomless = sniffUtf16WithoutBom(bytes)
  if (bomless) return decode(bytes, bomless) ?? ''

  const utf8 = decode(bytes, 'utf-8', true)
  if (utf8 !== null) return utf8

  let best = decode(bytes, 'utf-8') ?? ''
  let bestScore = score(best)
  const utf16 = ['utf-16le', 'utf-16be'] as const
  const candidates = preferred ? [preferred, ...LEGACY_CHARSETS] : LEGACY_CHARSETS
  // CJK-only UTF-16 carries too few NUL bytes for the sniffer above; let the scorer pick.
  // Local correction: preferred legacy charset wins equal-score BOM-less
  // UTF-16 guesses (GB18030 '中,1' otherwise becomes Korean text).
  for (const charset of [...candidates, ...utf16]) {
    const candidate = decode(bytes, charset)
    if (candidate === null) continue
    const candidateScore = score(candidate)
    if (candidateScore > bestScore) {
      best = candidate
      bestScore = candidateScore
    }
  }
  return best
}

/// Excel's own hint line: a first line of exactly `sep=<char>` names the
/// delimiter and is not data. Excel writes it for CSV exports in locales
/// that use ";" and honours it on open.
const SEP_DECLARATION = /^\uFEFF?sep=(.)\r?\n/i

export function splitSepDeclaration(text: string): { text: string; delimiter?: string } {
  const match = SEP_DECLARATION.exec(text)
  if (!match) return { text }
  return { text: text.slice(match[0].length), delimiter: match[1]! }
}

/// Counts delimiter occurrences outside quotes over the first lines and
/// picks the most frequent one; ties favor the comma. A `sep=` line wins.
export function sniffDelimiter(input: string): string {
  const { text, delimiter } = splitSepDeclaration(input)
  if (delimiter !== undefined) return delimiter
  const sample = text
    .slice(0, 64 * 1024)
    .split(/\r?\n/)
    .slice(0, 20)
  const counts = new Map<string, number>(DELIMITERS.map((d) => [d, 0]))
  // Quote state carries across lines: a quoted field may span line breaks,
  // and delimiters inside it must never be counted.
  let quoted = false
  for (const line of sample) {
    for (let index = 0; index < line.length; index += 1) {
      const character = line[index]
      if (character === undefined) continue
      if (character === '"') {
        // An escaped quote ("") stays inside the quoted field; only a lone
        // quote toggles quoting, mirroring parseCsv below.
        if (quoted && line[index + 1] === '"') {
          index += 1
        } else {
          quoted = !quoted
        }
      } else if (!quoted && counts.has(character)) {
        counts.set(character, (counts.get(character) ?? 0) + 1)
      }
    }
  }
  let best: string = DELIMITERS[0]
  let bestCount = -1
  for (const delimiter of DELIMITERS) {
    const count = counts.get(delimiter) ?? 0
    if (count > bestCount) {
      best = delimiter
      bestCount = count
    }
  }
  return best
}

export function parseCsv(input: string, delimiter = sniffDelimiter(input)): string[][] {
  const stripped = splitSepDeclaration(input).text
  const text = stripped.startsWith('﻿') ? stripped.slice(1) : stripped
  const rows: string[][] = []
  const fail = (msg: string): never => {
    throw new Error(`CSV import rejected: ${msg}`)
  }
  let row: string[] = []
  let field = ''
  const pushField = (): void => {
    row.push(field)
    if (row.length > MAX_CSV_COLS) fail(`too many columns (cap ${MAX_CSV_COLS})`)
    field = ''
  }
  const pushRow = (): void => {
    rows.push(row)
    if (rows.length > MAX_CSV_ROWS) fail(`too many rows (cap ${MAX_CSV_ROWS})`)
    row = []
  }
  let quoted = false
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index]
    if (quoted) {
      if (character === '"') {
        if (text[index + 1] === '"') {
          field += '"'
          index += 1
        } else {
          quoted = false
        }
      } else if (character === '\r') {
        if (text[index + 1] === '\n') index += 1
        field += '\n'
      } else {
        field += character
      }
      continue
    }
    if (character === '"' && field === '') {
      quoted = true
    } else if (character === delimiter) {
      pushField()
    } else if (character === '\n' || character === '\r') {
      if (character === '\r' && text[index + 1] === '\n') index += 1
      pushField()
      pushRow()
    } else {
      field += character
    }
  }
  if (field !== '' || row.length > 0) {
    pushField()
    pushRow()
  }
  // A trailing newline produces one empty row — drop it.
  while (rows.length > 0 && rows[rows.length - 1]?.every((cell) => cell === '')) rows.pop()
  return rows
}

/// Plain decimal numbers only (".5", "1." and "-.5" count, as in Excel); leading
/// zeros ("007") and a "+" sign ("+86") stay text so codes and phone numbers
/// survive the import. Integers past Excel's 15-digit precision stay text too,
/// so long IDs are not corrupted on open.
export function isNumericCell(value: string): boolean {
  if (!/^-?(?:(?:0|[1-9][0-9]*)(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(value))
    return false
  if (!/[.eE]/.test(value) && value.replace(/^-/, '').length > 15) return false
  return Number.isFinite(Number(value))
}

