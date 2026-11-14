import { afterEach, expect, it, vi } from 'vitest'
import { appendSymbol, createWorkbookSymbolDialog, symbolInsertion, WORKBOOK_SYMBOL_CATEGORIES } from './workbook-symbol-dialog'

afterEach(() => { document.body.replaceChildren() })

it.each(['composition', 'legacy', 'handled'])('符号网格与分类保留受保护的导航按键：%s', protection => {
  const root = document.body.appendChild(document.createElement('div')), insert = vi.fn(() => '已插入')
  const dialog = createWorkbookSymbolDialog(root, insert)
  try {
    dialog.open()
    const tab = root.querySelector<HTMLButtonElement>('[data-symbol-category="1"]')!
    tab.click()
    const mathButton = root.querySelector<HTMLButtonElement>('[data-symbol="×"]')!
    for (const node of [mathButton, tab]) for (const key of ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End']) {
      node.focus()
      const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, isComposing: protection === 'composition', keyCode: protection === 'legacy' ? 229 : 0 })
      if (protection === 'handled') event.preventDefault()
      node.dispatchEvent(event)
      expect(document.activeElement).toBe(node)
      expect(tab.getAttribute('aria-selected')).toBe('true')
      expect(insert).not.toHaveBeenCalled()
    }
    tab.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }))
    expect((document.activeElement as HTMLElement).dataset.symbolCategory).toBe('2')
  } finally { dialog.dispose() }
})

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

it('keeps focus on a selected category and associates its symbols with that tab', () => {
  const root = document.body.appendChild(document.createElement('div'))
  let value = '价格'
  const dialog = createWorkbookSymbolDialog(root, char => value += char)
  try {
    dialog.open()
    const tab = root.querySelector<HTMLButtonElement>('[data-symbol-category="1"]')!
    tab.focus(); tab.click()
    expect(document.activeElement).toBe(tab)
    expect(tab.getAttribute('aria-selected')).toBe('true')
    expect([...root.querySelectorAll<HTMLElement>('[role=tab]')].map(node => node.tabIndex)).toEqual([-1, 0, -1, -1, -1])
    const panel = root.querySelector('[role=tabpanel]')!
    expect(panel.getAttribute('aria-labelledby')).toBe(tab.id)
    expect(tab.getAttribute('aria-controls')).toBe(panel.id)
    expect(value).toBe('价格')
  } finally { dialog.dispose() }
})

it('moves between categories with keyboard commands without inserting any symbol', () => {
  const root = document.body.appendChild(document.createElement('div'))
  let value = '价格'
  const dialog = createWorkbookSymbolDialog(root, char => value += char)
  try {
    dialog.open()
    const first = root.querySelector<HTMLButtonElement>('[data-symbol-category="0"]')!
    first.focus(); first.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }))
    expect((document.activeElement as HTMLElement).dataset.symbolCategory).toBe('1')
    document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true, cancelable: true }))
    expect((document.activeElement as HTMLElement).dataset.symbolCategory).toBe('4')
    document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(first)
    first.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true, cancelable: true }))
    expect((document.activeElement as HTMLElement).dataset.symbolCategory).toBe('4')
    const modified = new KeyboardEvent('keydown', { key: 'ArrowRight', ctrlKey: true, bubbles: true, cancelable: true })
    document.activeElement!.dispatchEvent(modified)
    expect(modified.defaultPrevented).toBe(false)
    expect((document.activeElement as HTMLElement).dataset.symbolCategory).toBe('4')
    expect(value).toBe('价格')
  } finally { dialog.dispose() }
})

it('navigates the symbol group with one Tab stop and preserves cell data until activation', () => {
  const root = document.body.appendChild(document.createElement('div'))
  let value = '价格'
  const dialog = createWorkbookSymbolDialog(root, char => value += char)
  try {
    dialog.open()
    const first = root.querySelector<HTMLButtonElement>('[data-symbol="€"]')!
    expect(document.activeElement).toBe(first)
    first.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }))
    const pound = root.querySelector<HTMLButtonElement>('[data-symbol="£"]')!
    expect(document.activeElement).toBe(pound)
    expect([...root.querySelectorAll<HTMLElement>('[data-symbol]')].filter(node => node.tabIndex === 0)).toEqual([pound])
    pound.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true, cancelable: true }))
    expect((document.activeElement as HTMLElement).dataset.symbol).toBe('¿')
    document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(first)
    expect(value).toBe('价格')
    first.click(); expect(value).toBe('价格€')
    expect(document.activeElement).toBe(first)
  } finally { dialog.dispose() }
})

it('provides keyboard access to insertion guidance and inline feedback', () => {
  const root = document.body.appendChild(document.createElement('div'))
  const dialog = createWorkbookSymbolDialog(root, () => { throw new Error('活动单元格含公式，请选择普通单元格') })
  try {
    dialog.open(); root.querySelector<HTMLButtonElement>('[data-symbol="€"]')!.click()
    const help = root.querySelector('[role=region][aria-label="符号插入说明"]')!
    expect(help).not.toBeNull()
    expect(help.getAttribute('tabindex')).toBe('0')
    const error = root.querySelector('[role=alert]')!
    expect(error.getAttribute('aria-label')).toBe('符号插入错误')
    expect(error.getAttribute('tabindex')).toBe('0')
    expect(error.textContent).toContain('含公式')
    expect(root.querySelector('[data-symbol-status]')?.getAttribute('aria-label')).toBe('符号插入结果')
  } finally { dialog.dispose() }
})
