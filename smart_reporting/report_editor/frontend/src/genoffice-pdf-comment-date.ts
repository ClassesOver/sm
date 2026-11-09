/** GenOffice f8c17004fb730df11f0f743164ffd8b4281bb38c, Apache-2.0.
 * Extracted unchanged PDF date parser and calendar helper. License/NOTICE: reporting/pdf_engine.
 */
/**
 * Days in `month` (0-based) of `year`, leap years included. setUTCFullYear rather
 * than Date.UTC, which would fold years 0-99 into the 1900s.
 */
const daysInMonth = (year: number, month: number): number => {
  const d = new Date(0)
  d.setUTCFullYear(year, month + 1, 0)
  return d.getUTCDate()
}

/** PDF date string (D:YYYYMMDDHHmmSS±hh'mm') → epoch ms; null when unparseable */
export function parsePdfDate(s: string | null | undefined): number | null {
  if (!s) return null
  const m =
    /^D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?(?:([+\-Z])(?:(\d{2})'?(\d{2})?'?)?)?/.exec(
      s.trim(),
    )
  if (!m) return null
  const [, y, mo, d, h, mi, se, tzSign, tzH, tzM] = m
  const year = Number(y)
  const month = Number(mo ?? '1') - 1
  const day = Number(d ?? '1')
  const hour = Number(h ?? '0')
  const min = Number(mi ?? '0')
  const sec = Number(se ?? '0')
  if (
    month < 0 ||
    month > 11 ||
    day < 1 ||
    day > daysInMonth(year, month) ||
    hour > 23 ||
    min > 59 ||
    sec > 59
  )
    return null
  let ms = Date.UTC(year, month, day, hour, min, sec)
  if (tzSign === '+' || tzSign === '-') {
    const offMin = Number(tzH ?? '0') * 60 + Number(tzM ?? '0')
    ms += (tzSign === '+' ? -1 : 1) * offMin * 60_000
  } else if (tzSign !== 'Z') {
    // No timezone: treat as local time
    ms = new Date(year, month, day, hour, min, sec).getTime()
  }
  return Number.isFinite(ms) ? ms : null
}

