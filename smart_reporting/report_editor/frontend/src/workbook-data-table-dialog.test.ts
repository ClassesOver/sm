import { afterEach, expect, it, vi } from 'vitest'

afterEach(() => document.body.replaceChildren())

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
