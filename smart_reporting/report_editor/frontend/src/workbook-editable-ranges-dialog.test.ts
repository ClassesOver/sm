import { afterEach, expect, it, vi } from 'vitest'
import { createEditableRangesDialog } from './workbook-editable-ranges-dialog'

afterEach(() => document.body.replaceChildren())
it('adds, edits and removes ranges only when confirmed; refuses protected or unsupported definitions', async () => {
  const apply = vi.fn().mockResolvedValue(undefined), root = document.createElement('div');document.body.append(root)
  const dialog = createEditableRangesDialog(root, apply)
  dialog.open({ sheetName: 'Sheet1', ranges: [{ name: 'Input', sqref: 'B2:C4' }], selection: 'E2:E4' })
  const field = (label: string) => root.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!
  field('区域名称 1').value = 'Edited'
  root.querySelector<HTMLButtonElement>('[data-action="add"]')!.click()
  expect(field('区域引用 2').value).toBe('E2:E4')
  field('区域名称 2').value = 'Extra'
  root.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  await vi.waitFor(() => expect(apply).toHaveBeenCalledWith('Sheet1', [{ name: 'Edited', sqref: 'B2:C4' }, { name: 'Extra', sqref: 'E2:E4' }]))
  await vi.waitFor(() => expect(root.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled).toBe(false))
  expect(root.querySelector<HTMLElement>('[role="dialog"]')!.hidden).toBe(true)
  dialog.open({ sheetName: 'Sheet1', ranges: [{ name: 'Secret', sqref: 'A1', readonlyReason: '需要密码' }] })
  expect(root.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled).toBe(true)
  expect(root.textContent).toContain('需要密码')
  dialog.open({ sheetName: 'Sheet1', ranges: [], protected: true })
  expect(root.querySelector<HTMLButtonElement>('[data-action="add"]')!.disabled).toBe(true)
  expect(root.textContent).toContain('撤销工作表保护')
  dialog.dispose()
})
