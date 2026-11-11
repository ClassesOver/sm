// Text field expansion and section decoding ported from pinned GenOffice
// f8c17004fb730df11f0f743164ffd8b4281bb38c: print-hf-codes.ts and
// print-settings.ts. Images are intentionally omitted.
import type { HeaderFooterParts } from '@sheets-web/xlsx-engine/page-setup'

/// Excel header/footer field codes → printed text for one page. Handles the
/// stored `&X` forms and the `&[Page]`-style names the Excel UI shows; an
/// unknown code is kept as the literal text Excel prints.

export interface HeaderFooterFields {
  readonly page: number
  readonly total: number
  readonly date: Date
  readonly fileName: string
  readonly sheetName: string
  readonly filePath?: string | undefined
  /// Replaces `&G` (the section picture); nothing when absent.
  readonly picture?: string | undefined
}

const NAMED_CODES: Record<string, string> = {
  page: 'P',
  pages: 'N',
  date: 'D',
  time: 'T',
  file: 'F',
  tab: 'A',
  path: 'Z',
  picture: 'G',
}

export function expandHeaderFooterCodes(text: string, fields: HeaderFooterFields): string {
  let out = ''
  let index = 0
  while (index < text.length) {
    const character = text[index] ?? ''
    if (character !== '&') {
      out += character
      index += 1
      continue
    }
    const next = text[index + 1]
    if (next === undefined) {
      out += '&'
      break
    }
    if (next === '&') {
      out += '&'
      index += 2
      continue
    }
    let code = next.toUpperCase()
    let length = 2
    if (next === '[') {
      const close = text.indexOf(']', index + 2)
      const named =
        close === -1 ? undefined : NAMED_CODES[text.slice(index + 2, close).toLowerCase()]
      if (named === undefined) {
        out += '&['
        index += 2
        continue
      }
      code = named
      length = close + 1 - index
    }
    // &P+n / &P-n offsets the page number.
    let pageOffset = 0
    if (code === 'P') {
      const offset = /^([+-])(\d{1,4})/.exec(text.slice(index + length))
      if (offset) {
        pageOffset = Number(offset[2]) * (offset[1] === '-' ? -1 : 1)
        length += offset[0].length
      }
    }
    const expanded = expandCode(code, fields, pageOffset)
    if (expanded === null) {
      out += `&${next}`
      index += 2
      continue
    }
    out += expanded
    index += length
  }
  return out
}

function expandCode(code: string, fields: HeaderFooterFields, pageOffset: number): string | null {
  switch (code) {
    case 'P':
      return String(fields.page + pageOffset)
    case 'N':
      return String(fields.total)
    case 'D':
      return fields.date.toLocaleDateString()
    case 'T':
      return fields.date.toLocaleTimeString()
    case 'F':
      return fields.fileName
    case 'A':
      return fields.sheetName
    case 'Z':
      return fields.filePath ?? ''
    case 'G':
      return fields.picture ?? ''
    default:
      return null
  }
}

const STRIPPED_CODES = new Set(['B', 'I', 'U', 'S', 'E', 'X', 'Y', 'Z', 'O', 'H'])
export function decodeHeaderFooter(encoded: string): HeaderFooterParts | null {
  const sections = { L: '', C: '', R: '' }
  let current: 'L' | 'C' | 'R' = 'C'
  let index = 0
  while (index < encoded.length) {
    const character = encoded[index] ?? ''
    if (character !== '&') {
      sections[current] += character
      index += 1
      continue
    }
    const next = encoded[index + 1]
    if (next === undefined) break
    if (next === '&') {
      sections[current] += '&&'
      index += 2
      continue
    }
    // &"Font Name,Style" — skip the whole quoted spec.
    if (next === '"') {
      const close = encoded.indexOf('"', index + 2)
      index = close === -1 ? encoded.length : close + 1
      continue
    }
    // &nn font size.
    if (/[0-9]/.test(next)) {
      index += 2
      while (index < encoded.length && /[0-9]/.test(encoded[index] ?? '')) index += 1
      continue
    }
    const code = next.toUpperCase()
    // &K followed by an RRGGBB or theme color spec.
    if (code === 'K') {
      index += 8
      continue
    }
    if (code === 'L' || code === 'C' || code === 'R') {
      current = code
      index += 2
      continue
    }
    if (
      code === 'P' ||
      code === 'N' ||
      code === 'D' ||
      code === 'T' ||
      code === 'F' ||
      code === 'A' ||
      code === 'G'
    ) {
      sections[current] += `&${code}`
      index += 2
      continue
    }
    if (STRIPPED_CODES.has(code)) {
      index += 2
      continue
    }
    sections[current] += `&${code}`
    index += 2
  }
  if (sections.L === '' && sections.C === '' && sections.R === '') return null
  return {
    ...(sections.L === '' ? {} : { left: sections.L }),
    ...(sections.C === '' ? {} : { center: sections.C }),
    ...(sections.R === '' ? {} : { right: sections.R }),
  }
}
