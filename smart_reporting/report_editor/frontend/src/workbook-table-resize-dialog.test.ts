import { afterEach, expect, it, vi } from 'vitest'
import { createTableResizeDialog } from './workbook-table-resize-dialog'

afterEach(() => document.body.replaceChildren())

it('keeps the captured table target, retains errors and closes only after a successful resize', () => {
  const apply = vi.fn().mockImplementationOnce(() => { throw new Error('表格必须保留原表头行') })
  const dialog = createTableResizeDialog(document.body, apply)
  const target = { tableId: 'table-one', range: 'A1:B4' }
  dialog.open(target)
  target.tableId = 'table-two'
  const input = document.querySelector<HTMLInputElement>('[aria-label="新的表格范围"]')!
  const overlay = document.querySelector<HTMLElement>('[role="dialog"]')!
  expect(input.value).toBe('A1:B4')
  input.value = 'A2:B8'
  document.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(apply).toHaveBeenCalledWith('table-one', 'A2:B8')
  expect(overlay.hidden).toBe(false)
  expect(document.querySelector('[role="alert"]')!.textContent).toBe('表格必须保留原表头行')
  input.value = 'A1:B8'
  document.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(apply).toHaveBeenLastCalledWith('table-one', 'A1:B8')
  expect(overlay.hidden).toBe(true)
  dialog.open({ tableId: 'table-three', range: 'C1:D4' })
  expect(input.value).toBe('C1:D4')
  expect(document.querySelector('[role="alert"]')!.textContent).toBe('')
  dialog.dispose()
  expect(document.querySelector('[role="dialog"]')).toBeNull()
})
