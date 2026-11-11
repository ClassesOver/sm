import { afterEach, expect, it, vi } from 'vitest'

afterEach(() => document.body.replaceChildren())

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
