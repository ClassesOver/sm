import { afterEach, expect, it, vi } from 'vitest'
import { createTableCreateDialog } from './workbook-table-create-dialog'

afterEach(() => document.body.replaceChildren())

it('keeps the captured sheet, defaults to headers and retains a failed creation for correction', () => {
  const create = vi.fn().mockImplementationOnce(() => { throw new Error('范围与已有表格重叠') })
  const dialog = createTableCreateDialog(document.body, create)
  const target = { sheetId: 'sheet-one', range: 'A1:B4' }
  dialog.open(target)
  target.sheetId = 'sheet-two'
  const overlay = document.querySelector<HTMLElement>('[role="dialog"]')!
  const range = document.querySelector<HTMLInputElement>('[aria-label="表格范围"]')!
  const headers = document.querySelector<HTMLInputElement>('[aria-label="表包含标题"]')!
  expect(overlay.getAttribute('aria-label')).toBe('创建表格')
  expect(range.value).toBe('A1:B4')
  expect(headers.checked).toBe(true)
  range.value = 'C1:D5'; headers.checked = false
  document.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(create).toHaveBeenCalledWith('sheet-one', 'C1:D5', false)
  expect(overlay.hidden).toBe(false)
  expect(document.querySelector('[role="alert"]')!.textContent).toBe('范围与已有表格重叠')
  expect(range.getAttribute('aria-invalid')).toBe('true')
  range.value = 'E1:F5'
  document.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(create).toHaveBeenLastCalledWith('sheet-one', 'E1:F5', false)
  expect(overlay.hidden).toBe(true)
  dialog.open({ sheetId: 'sheet-three', range: 'G1:H3' })
  expect(headers.checked).toBe(true)
  expect(range.value).toBe('G1:H3')
  expect(range.hasAttribute('aria-invalid')).toBe(false)
  expect(document.querySelector('[role="alert"]')!.textContent).toBe('')
  dialog.dispose()
  expect(document.querySelector('[role="dialog"]')).toBeNull()
})

it('cancels without creating a table', () => {
  const create = vi.fn(), dialog = createTableCreateDialog(document.body, create)
  dialog.open({ sheetId: 'sheet-one', range: 'A1:B4' })
  document.querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
  expect(create).not.toHaveBeenCalled()
  expect(document.querySelector<HTMLElement>('[role="dialog"]')!.hidden).toBe(true)
  dialog.dispose()
})
