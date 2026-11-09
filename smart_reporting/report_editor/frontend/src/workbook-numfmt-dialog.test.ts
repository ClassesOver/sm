import { afterEach, expect, it, vi } from 'vitest'
import { createFormatCellsDialog, numfmtOptionsOf, numfmtPattern, DEFAULT_NUMFMT_OPTIONS } from './workbook-numfmt-dialog'

afterEach(() => { document.body.replaceChildren() })

it('keeps the fixed-source category ⇄ pattern round trip', () => {
  expect(numfmtPattern({ ...DEFAULT_NUMFMT_OPTIONS, category: 'currency', symbol: '¥', decimals: 2, negative: 'red' })).toBe('¥#,##0.00;[Red]¥#,##0.00')
  expect(numfmtPattern({ ...DEFAULT_NUMFMT_OPTIONS, category: 'accounting', symbol: '$', decimals: 0 })).toBe('_($* #,##0_);_($* (#,##0);_($* "-"_);_(@_)')
  for (const pattern of ['General', '@', '0.00%', '0.0E+00', '#,##0.000', '¥#,##0.00_);(¥#,##0.00)', 'yyyy-mm-dd', 'h:mm:ss', '# ?/?'])
    expect(numfmtPattern(numfmtOptionsOf(pattern)), pattern).toBe(pattern)
  expect(numfmtOptionsOf('0.0" kg"')).toMatchObject({ category: 'custom', custom: '0.0" kg"' })
})

it('builds the pattern from category and options with a live preview, and applies it', () => {
  document.body.innerHTML = '<main></main>'
  const apply = vi.fn()
  const dialog = createFormatCellsDialog(document.querySelector('main')!, { current: () => ({ pattern: '0.00', anchor: -1234.5 }), apply })
  dialog.open()
  const card = document.querySelector<HTMLElement>('.workbook-ribbon-numfmt-dialog')!
  expect(card.querySelector('[data-numfmt-category="number"]')!.getAttribute('aria-selected')).toBe('true')
  card.querySelector<HTMLButtonElement>('[data-numfmt-category="currency"]')!.click()
  const symbol = card.querySelector<HTMLSelectElement>('[data-numfmt-symbol]')!
  symbol.value = '¥'; symbol.dispatchEvent(new Event('change', { bubbles: true }))
  const negative = card.querySelector<HTMLSelectElement>('[data-numfmt-negative]')!
  negative.value = 'parens'; negative.dispatchEvent(new Event('change', { bubbles: true }))
  expect(card.querySelector<HTMLElement>('[data-numfmt-field="thousands"]')!.hidden).toBe(true)
  expect(card.querySelector('[data-numfmt-preview]')!.textContent).toBe('(¥1,234.50)')
  card.querySelector<HTMLFormElement>('form')!.requestSubmit()
  expect(apply).toHaveBeenCalledWith('¥#,##0.00_);(¥#,##0.00)')
  apply.mockImplementation(() => { throw new Error('预算超限') })
  dialog.open(); card.querySelector<HTMLFormElement>('form')!.requestSubmit()
  expect(card.querySelector('[role="alert"]')!.textContent).toBe('预算超限')
})
