import { afterEach, expect, it, vi } from 'vitest'

afterEach(() => document.body.replaceChildren())

it('keeps the title and actions outside the scrollable fields with named keyboard-readable guidance', async () => {
  const { createGoalSeekDialog } = await import('./workbook-goal-seek-dialog')
  const dialog = createGoalSeekDialog(document.body, vi.fn())
  dialog.open({ workbookId: 'book', sheetId: 'sheet', setCell: 'B1' })
  const card = document.querySelector('.workbook-goal-seek-dialog')!
  expect(card).not.toBeNull()
  expect(card.querySelector(':scope > header h2')?.textContent).toBe('单变量求解')
  expect(card.querySelector(':scope > form > .workbook-analysis-body input')).not.toBeNull()
  expect(card.querySelector(':scope > form > footer [type="submit"]')).not.toBeNull()
  for (const name of ['单变量求解说明', '单变量求解结果', '单变量求解错误']) {
    expect(card.querySelector(`[aria-label="${name}"]`)?.getAttribute('tabindex')).toBe('0')
  }
  dialog.dispose()
})

it('offers a focused running status and keeps a failed solve readable before retry or dismissal', async () => {
  const { createGoalSeekDialog } = await import('./workbook-goal-seek-dialog')
  let reject!: (error: Error) => void
  const solve = vi.fn(() => new Promise<never>((_, fail) => { reject = fail }))
  const entry = document.createElement('button'); document.body.append(entry); entry.focus()
  const dialog = createGoalSeekDialog(document.body, solve)
  dialog.open({ workbookId: 'book', sheetId: 'sheet', setCell: 'B1' })
  const overlay = document.querySelector<HTMLElement>('[aria-label="单变量求解"]')!
  const status = overlay.querySelector<HTMLElement>('[role="status"]')!
  const error = overlay.querySelector<HTMLElement>('[role="alert"]')!
  const reveal = vi.fn(); status.scrollIntoView = reveal; error.scrollIntoView = reveal
  const input = overlay.querySelector<HTMLInputElement>('[aria-label="目标值"]')!
  input.value = '30'
  overlay.querySelector<HTMLInputElement>('[aria-label="可变单元格"]')!.value = 'A1'
  input.dispatchEvent(new Event('input')); input.focus()
  overlay.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(document.activeElement).toBe(status)
  expect(reveal).toHaveBeenCalledWith({ block: 'nearest' })
  expect([...overlay.querySelectorAll('button,input')].every(node => (node as HTMLInputElement).disabled)).toBe(true)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); expect(overlay.hidden).toBe(false)
  reject(new Error('求解失败：' + '请核对公式。'.repeat(80)))
  await vi.waitFor(() => expect(error.textContent).toContain('求解失败'))
  expect(document.activeElement).toBe(error)
  expect(input.disabled).toBe(false)
  expect(input.value).toBe('30')
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  expect(document.activeElement).toBe(entry)
  dialog.dispose()
})

it('validates a finite target, freezes the sheet identity and keeps results visible after an asynchronous solve', async () => {
  const path = './workbook-goal-seek-dialog'
  const { createGoalSeekDialog } = await import(path)
  let finish!: (value: unknown) => void
  const solve = vi.fn().mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    .mockResolvedValueOnce({ found: false, solution: 11, reached: NaN, iterations: 2 })
  const dialog = createGoalSeekDialog(document.body, solve)
  const target = { workbookId: 'book', sheetId: 'sheet-1', setCell: 'B1' }
  dialog.open(target); target.sheetId = 'sheet-2'
  const overlay = document.querySelector<HTMLElement>('[aria-label="单变量求解"]')!
  const [setCell, toValue, byCell] = [...overlay.querySelectorAll<HTMLInputElement>('input')]
  expect(setCell!.value).toBe('B1')
  toValue!.value = 'Infinity'; byCell!.value = ' a1 '
  byCell!.dispatchEvent(new Event('input'))
  const form = overlay.querySelector('form')!
  form.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(solve).not.toHaveBeenCalled()
  expect(overlay.querySelector('[role="alert"]')!.textContent).toContain('有限数值')
  toValue!.value = '30'; toValue!.dispatchEvent(new Event('input'))
  form.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(solve).toHaveBeenCalledWith({ workbookId: 'book', sheetId: 'sheet-1' }, { setCell: 'B1', toValue: 30, byCell: 'A1' })
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  expect(overlay.hidden).toBe(false)
  expect(byCell!.disabled).toBe(true)
  form.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(solve).toHaveBeenCalledTimes(1)
  finish({ found: true, solution: 15, reached: 30, iterations: 3 })
  await vi.waitFor(() => expect(overlay.querySelector('[role="status"]')!.textContent).toContain('找到解：15'))
  expect(overlay.hidden).toBe(false)
  expect(byCell!.disabled).toBe(false)
  form.dispatchEvent(new Event('submit', { cancelable: true }))
  await vi.waitFor(() => expect(overlay.querySelector('[role="status"]')!.textContent).toContain('未找到解'))
  expect(overlay.querySelector('[role="status"]')!.textContent).toContain('—')
  dialog.dispose()
})
