import { afterEach, expect, it, vi } from 'vitest'

afterEach(() => document.body.replaceChildren())

it('keeps the title and actions outside the scrollable fields with named keyboard-readable guidance', async () => {
  const { createDataTableDialog } = await import('./workbook-data-table-dialog')
  const dialog = createDataTableDialog(document.body, vi.fn())
  dialog.open({ workbookId: 'book', sheetId: 'sheet', range: 'D2:E5' })
  const card = document.querySelector('.workbook-data-table-dialog')!
  expect(card).not.toBeNull()
  expect(card.querySelector(':scope > header h2')?.textContent).toBe('模拟运算表')
  expect(card.querySelector(':scope > form > .workbook-analysis-body input')).not.toBeNull()
  expect(card.querySelector(':scope > form > footer [type="submit"]')).not.toBeNull()
  for (const name of ['模拟运算表说明', '模拟运算表结果', '模拟运算表错误']) {
    expect(card.querySelector(`[aria-label="${name}"]`)?.getAttribute('tabindex')).toBe('0')
  }
  dialog.dispose()
})

it('offers a focused running status and keeps an asynchronous error readable without losing fields', async () => {
  const { createDataTableDialog } = await import('./workbook-data-table-dialog')
  let reject!: (error: Error) => void
  const apply = vi.fn((_: unknown, input: { onProgress(done: number, total: number): void }) => {
    input.onProgress(1, 3)
    return new Promise<never>((_, fail) => { reject = fail })
  })
  const dialog = createDataTableDialog(document.body, apply)
  dialog.open({ workbookId: 'book', sheetId: 'sheet', range: 'D2:E5' })
  const overlay = document.querySelector<HTMLElement>('[aria-label="模拟运算表"]')!
  const status = overlay.querySelector<HTMLElement>('[role="status"]')!
  const error = overlay.querySelector<HTMLElement>('[role="alert"]')!
  const reveal = vi.fn(); status.scrollIntoView = reveal; error.scrollIntoView = reveal
  const input = overlay.querySelector<HTMLInputElement>('[aria-label="列输入单元格"]')!
  input.value = 'A1'; input.dispatchEvent(new Event('input')); input.focus()
  overlay.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(document.activeElement).toBe(status)
  expect(status.textContent).toBe('正在计算 1 / 3')
  expect(reveal).toHaveBeenCalledWith({ block: 'nearest' })
  expect([...overlay.querySelectorAll('button,input')].every(node => (node as HTMLInputElement).disabled)).toBe(true)
  reject(new Error('计算失败：' + '请核对来源。'.repeat(80)))
  await vi.waitFor(() => expect(error.textContent).toContain('计算失败'))
  expect(document.activeElement).toBe(error)
  expect(input.disabled).toBe(false)
  expect(input.value).toBe('A1')
  dialog.dispose()
})

it('captures the sheet, blocks dismissal and duplicate submits while running, and retains an error for retry', async () => {
  const modulePath = './workbook-data-table-dialog'
  const { createDataTableDialog } = await import(modulePath)
  let reject!: (error: Error) => void
  const apply = vi.fn().mockImplementationOnce((_: unknown, input: any) => {
    input.onProgress(1, 2)
    return new Promise((_, fail) => { reject = fail })
  }).mockResolvedValue({ kind: 'column', cells: 2 })
  const dialog = createDataTableDialog(document.body, apply)
  const target = { workbookId: 'book', sheetId: 'sheet-1', range: 'A1:B3' }
  dialog.open(target)
  target.sheetId = 'sheet-2'
  const overlay = document.querySelector<HTMLElement>('[role="dialog"]')!
  const form = overlay.querySelector('form')!
  const column = overlay.querySelector<HTMLInputElement>('[aria-label="列输入单元格"]')!
  column.value = ' d1 '
  column.dispatchEvent(new Event('input'))
  form.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(apply).toHaveBeenCalledTimes(1)
  expect(apply.mock.calls[0][0]).toEqual({ workbookId: 'book', sheetId: 'sheet-1' })
  expect(apply.mock.calls[0][1]).toMatchObject({ tableRange: 'A1:B3', rowInputCell: null, columnInputCell: 'D1' })
  expect(overlay.getAttribute('aria-busy')).toBe('true')
  expect(overlay.textContent).toContain('1 / 2')
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  form.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(overlay.hidden).toBe(false)
  expect(apply).toHaveBeenCalledTimes(1)
  reject(new Error('公式结果不可读取'))
  await vi.waitFor(() => expect(overlay.querySelector('[role="alert"]')!.textContent).toBe('公式结果不可读取'))
  expect(column.disabled).toBe(false)
  form.dispatchEvent(new Event('submit', { cancelable: true }))
  await vi.waitFor(() => expect(overlay.textContent).toContain('已生成 2 个结果'))
  expect(overlay.hidden).toBe(false)
  expect(overlay.textContent).toContain('静态值')
  dialog.dispose()
  expect(document.querySelector('[role="dialog"]')).toBeNull()
})
