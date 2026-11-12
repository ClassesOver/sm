import { afterEach, expect, it, vi } from 'vitest'
import { appendSymbol, createWorkbookSymbolDialog, symbolInsertion, WORKBOOK_SYMBOL_CATEGORIES } from './workbook-symbol-dialog'

afterEach(() => { document.body.replaceChildren() })

it('keeps the pinned SymbolDialog categories, order and append semantics', () => {
  expect(WORKBOOK_SYMBOL_CATEGORIES.map(category => [category.label, category.symbols.length])).toEqual([
    ['货币/常用', 20], ['数学', 30], ['箭头', 20], ['希腊字母', 27], ['几何/其它', 26],
  ])
  expect(WORKBOOK_SYMBOL_CATEGORIES[0]!.symbols.slice(0, 3)).toEqual(['€', '£', '¥'])
  expect(appendSymbol(null, '€')).toBe('€')
  expect(appendSymbol('', '€')).toBe('€')
  expect(appendSymbol('价格', '€')).toBe('价格€')
  expect(appendSymbol(12.5, '%')).toBe('12.5%')
  expect(appendSymbol(true, '✓')).toBe('true✓')
})

it('refuses formulas, rich text, unknown symbols and oversized text instead of overwriting them', () => {
  expect(symbolInsertion({ value: 'A' }, '→')).toBe('A→')
  expect(symbolInsertion({ value: 3 }, '°')).toBe('3°')
  expect(() => symbolInsertion({ value: 10, formula: '=SUM(A1:A2)' }, '€')).toThrow('含公式')
  expect(() => symbolInsertion({ value: 'x', richText: true }, '€')).toThrow('富文本')
  expect(() => symbolInsertion({ value: 'x' }, 'X')).toThrow('不支持的符号')
  expect(() => symbolInsertion({ value: 'x'.repeat(32767) }, '€')).toThrow('32767')
})

it('inserts repeatedly while open, reports errors inline and switches categories', () => {
  const root = document.createElement('div'); document.body.append(root)
  const insert = vi.fn((char: string) => { if (char === '♠') throw new Error('工作表受保护，请先撤销保护'); return `已插入 ${char}` })
  const dialog = createWorkbookSymbolDialog(root, insert)
  dialog.open()
  const overlay = root.querySelector<HTMLElement>('[aria-label="插入符号"]')!
  expect(overlay.hidden).toBe(false)
  root.querySelector<HTMLButtonElement>('[data-symbol="€"]')!.click()
  root.querySelector<HTMLButtonElement>('[data-symbol="£"]')!.click()
  expect(insert.mock.calls).toEqual([['€'], ['£']])
  expect(overlay.hidden).toBe(false)
  expect(root.querySelector('[data-symbol-status]')!.textContent).toBe('已插入 £')
  root.querySelector<HTMLButtonElement>('[data-symbol-category="4"]')!.click()
  expect(root.querySelector('[data-symbol-category="4"]')!.getAttribute('aria-selected')).toBe('true')
  root.querySelector<HTMLButtonElement>('[data-symbol="♠"]')!.click()
  expect(root.querySelector('[role="alert"]')!.textContent).toBe('工作表受保护，请先撤销保护')
  root.querySelector<HTMLButtonElement>('[data-symbol-close]')!.click()
  expect(overlay.hidden).toBe(true)
  dialog.dispose()
  expect(root.querySelector('[aria-label="插入符号"]')).toBeNull()
})
