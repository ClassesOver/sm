import { afterEach, expect, it, vi } from 'vitest'
import { numfmtOptionsOf, numfmtPattern, DEFAULT_NUMFMT_OPTIONS } from './workbook-numfmt-dialog'

afterEach(() => { document.body.replaceChildren() })

it('keeps the fixed-source category ⇄ pattern round trip', () => {
  expect(numfmtPattern({ ...DEFAULT_NUMFMT_OPTIONS, category: 'currency', symbol: '¥', decimals: 2, negative: 'red' })).toBe('¥#,##0.00;[Red]¥#,##0.00')
  expect(numfmtPattern({ ...DEFAULT_NUMFMT_OPTIONS, category: 'accounting', symbol: '$', decimals: 0 })).toBe('_($* #,##0_);_($* (#,##0);_($* "-"_);_(@_)')
  for (const pattern of ['General', '@', '0.00%', '0.0E+00', '#,##0.000', '¥#,##0.00_);(¥#,##0.00)', 'yyyy-mm-dd', 'h:mm:ss', '# ?/?'])
    expect(numfmtPattern(numfmtOptionsOf(pattern)), pattern).toBe(pattern)
  expect(numfmtOptionsOf('0.0" kg"')).toMatchObject({ category: 'custom', custom: '0.0" kg"' })
})
