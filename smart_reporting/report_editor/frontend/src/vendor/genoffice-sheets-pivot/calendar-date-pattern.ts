// Extracted from fixed-source renderer/numfmt-fix.ts; see SOURCE.md.
import { numfmt } from '@univerjs/core'

const EMPTY_CURRENCY_TAG = /\[\$\]/g
const datePatternCache = new Map<string, boolean>()

export function isCalendarDatePattern(pattern: string): boolean {
  let isDate = datePatternCache.get(pattern)
  if (isDate === undefined) {
    try {
      const type = (numfmt.getFormatInfo(pattern.replace(EMPTY_CURRENCY_TAG, '')) as { type?: string }).type
      isDate = type === 'date' || type === 'datetime'
    } catch {
      isDate = false
    }
    datePatternCache.set(pattern, isDate)
  }
  return isDate
}
