/// Display-format rendering for export surfaces (CSV export, print view).
/// The grid renders numFmts itself; these exports need the formatted STRING.
/// v1 scope: builtin date/time codes 14–22/45–46, explicit date patterns
/// (yyyy/m/d family incl. quoted literals like yyyy"年"m"月"), numeric
/// 0/0.00/#,##0(#.00)/percent. Anything else falls back to the raw value —
/// an honest "General" beats a wrong format.

interface DateParts {
  year: number
  month: number
  day: number
  hour: number
  minute: number
  second: number
}

/// Excel serial → date parts in UTC. serial 25569 = 1970-01-01; fractional
/// serials (< 1) are pure times and valid. Only 1–60 is refused — that is
/// the 1900 phantom-leap range where the serial↔date mapping is ambiguous.
function serialParts(serial: number): DateParts | null {
  if (!Number.isFinite(serial)) return null
  if (serial >= 1 && serial < 61) return null
  const date = new Date(Math.round((serial - 25569) * 86_400_000))
  return {
    year: date.getUTCFullYear(),
    month: date.getUTCMonth() + 1,
    day: date.getUTCDate(),
    hour: date.getUTCHours(),
    minute: date.getUTCMinutes(),
    second: date.getUTCSeconds(),
  }
}

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

type Token =
  | { kind: 'literal'; text: string }
  | { kind: 'date'; token: string }

/// Split a date pattern into quoted literals, alpha runs (yyyy, mmm, h, ss…),
/// and separator literals. Unknown letters (e.g. 'q', 'g') mark the pattern
/// unsupported.
function tokenizeDatePattern(pattern: string): Token[] | null {
  const tokens: Token[] = []
  let index = 0
  while (index < pattern.length) {
    const character = pattern[index]!
    if (character === '"') {
      const close = pattern.indexOf('"', index + 1)
      if (close < 0) return null
      tokens.push({ kind: 'literal', text: pattern.slice(index + 1, close) })
      index = close + 1
      continue
    }
    if (/[ymdhs]/i.test(character)) {
      const run = pattern.slice(index).match(/^[ymdhs]+/i)![0]
      for (const chunk of run.match(/yyyy|yy|mmmm|mmm|mm|m|dddd|ddd|dd|d|hh|h|ss|s/g) ?? []) {
        tokens.push({ kind: 'date', token: chunk.toLowerCase() })
      }
      index += run.length
      continue
    }
    if (character === 'A' || character === 'P') {
      if (pattern.slice(index, index + 5) === 'AM/PM') {
        tokens.push({ kind: 'date', token: 'ampm' })
        index += 5
        continue
      }
      return null
    }
    if (/[\/\-.: ,]/.test(character)) {
      tokens.push({ kind: 'literal', text: character })
      index += 1
      continue
    }
    return null // unsupported character (escapes like \x unsupported in v1)
  }
  return tokens
}

function renderDatePattern(pattern: string, serial: number): string | null {
  const parts = serialParts(serial)
  if (parts === null) return null
  const tokens = tokenizeDatePattern(pattern)
  if (tokens === null) return null
  const twelveHour = tokens.some((token) => token.kind === 'date' && token.token === 'ampm')
  const weekday = new Date(Date.UTC(parts.year, parts.month - 1, parts.day)).getUTCDay()
  // an m/mm run is minutes when the nearest date token before it is h/s or
  // the nearest date token after it is s (h:mm, mm:ss); otherwise a month
  const isMinutes = (position: number): boolean => {
    for (let i = position - 1; i >= 0; i -= 1) {
      const token = tokens[i]!
      if (token.kind !== 'date') continue
      return token.token === 'h' || token.token === 'hh' || token.token === 's' || token.token === 'ss'
    }
    for (let i = position + 1; i < tokens.length; i += 1) {
      const token = tokens[i]!
      if (token.kind !== 'date') continue
      return token.token === 's' || token.token === 'ss'
    }
    return false
  }
  const out: string[] = []
  tokens.forEach((token, position) => {
    if (token.kind === 'literal') {
      out.push(token.text)
      return
    }
    const t = token.token
    if (t === 'ampm') {
      out.push(parts.hour < 12 ? 'AM' : 'PM')
      return
    }
    if (t === 'yyyy') out.push(String(parts.year))
    else if (t === 'yy') out.push(String(parts.year % 100).padStart(2, '0'))
    else if (t === 'mmmm') out.push(MONTHS[parts.month - 1]!)
    else if (t === 'mmm') out.push(MONTHS[parts.month - 1]!.slice(0, 3))
    else if (t === 'dddd') out.push(WEEKDAYS[weekday]!)
    else if (t === 'ddd') out.push(WEEKDAYS[weekday]!.slice(0, 3))
    else if (t === 'm' || t === 'mm') {
      const value = isMinutes(position) ? parts.minute : parts.month
      out.push(t === 'mm' ? String(value).padStart(2, '0') : String(value))
    } else if (t === 'd') out.push(String(parts.day))
    else if (t === 'dd') out.push(String(parts.day).padStart(2, '0'))
    else if (t === 'h' || t === 'hh') {
      let hour = parts.hour
      if (twelveHour) hour = hour % 12 === 0 ? 12 : hour % 12
      out.push(t === 'hh' ? String(hour).padStart(2, '0') : String(hour))
    } else if (t === 's') out.push(String(parts.second))
    else if (t === 'ss') out.push(String(parts.second).padStart(2, '0'))
  })
  return out.join('')
}

function renderNumericPattern(pattern: string, value: number): string | null {
  // 引号中的百分号是字面量：项目百分数事实已是12.5，不能再次乘100。
  const sections = pattern.split(';')
  const negativeSection = value < 0 && sections.length > 1
  const selected = sections[negativeSection ? 1 : 0]!
  const points = selected.match(/^(?:\[Red\])?(-|\()?0(?:\.(0{1,15}))?"%"(\))?$/)
  if (points && Boolean(points[1] === '(') === Boolean(points[3])) {
    const number = Math.abs(value).toFixed(points[2]?.length ?? 0)
    const prefix = points[1] ?? (value < 0 && !negativeSection ? '-' : '')
    return prefix + number + '%' + (points[3] ?? '')
  }
  if (pattern === 'General' || pattern === '@') return null // caller renders raw
  if (pattern === '0') return String(Math.round(value))
  if (pattern === '0%') return `${Math.round(value * 100)}%`
  if (pattern === '0.00%') return `${(value * 100).toFixed(2)}%`
  if (pattern === '#,##0') return Math.round(value).toLocaleString('en-US')
  if (pattern === '#,##0.00') {
    return value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }
  const fixed = pattern.match(/^0\.(0+)$/)
  if (fixed) return value.toFixed(fixed[1]!.length)
  return null // unsupported numeric pattern → raw
}

/// Builtin format ids → concrete patterns (id 14/22 are regional; en-US
/// forms here, which is also what the builtin table in style-read carries).
const BUILTIN_DATE_PATTERNS: Record<string, string> = {
  14: 'm/d/yyyy', 15: 'd-mmm-yy', 16: 'd-mmm', 17: 'mmm-yy',
  18: 'h:mm AM/PM', 19: 'h:mm:ss AM/PM', 20: 'h:mm', 21: 'h:mm:ss',
  22: 'm/d/yyyy h:mm', 45: 'mm:ss', 46: 'h:mm:ss',
}

/// Format a numeric cell for display-oriented export. Non-numeric values and
/// unsupported patterns return the raw string form (honest fallback).
export function formatNumericValue(value: number, code: string | undefined): string {
  if (code === undefined || code === '') return String(value)
  const builtin = BUILTIN_DATE_PATTERNS[code]
  if (builtin !== undefined) {
    const rendered = renderDatePattern(builtin, value)
    return rendered ?? String(value)
  }
  const looksLikeDate = /^[ymdhs]/i.test(code) || /yyyy|mmm|dddd|AM\/PM/.test(code)
  if (looksLikeDate) {
    const rendered = renderDatePattern(code, value)
    return rendered ?? String(value)
  }
  return renderNumericPattern(code, value) ?? String(value)
}
