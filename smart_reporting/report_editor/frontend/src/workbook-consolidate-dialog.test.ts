import { afterEach, expect, it, vi } from 'vitest'

afterEach(() => document.body.replaceChildren())

it('keeps source references, counts pending input, limits label functions and retries with the captured target', async () => {
  const path = './workbook-consolidate-dialog'
  const { createConsolidateDialog } = await import(path)
  const apply = vi.fn().mockImplementationOnce(() => { throw new Error('目标与来源重叠') })
  const dialog = createConsolidateDialog(document.body, apply)
  const target = { workbookId: 'book', sheetId: 'sheet-1', row: 5, column: 0, defaultReference: "'O''Brien'!A1:B3", targetLabel: 'Summary!A6' }
  dialog.open(target); target.sheetId = 'sheet-2'
  const overlay = document.querySelector<HTMLElement>('[aria-label="合并计算"]')!
  const reference = overlay.querySelector<HTMLInputElement>('[aria-label="引用位置"]')!
  const add = overlay.querySelector<HTMLButtonElement>('[data-action="add"]')!
  const fn = overlay.querySelector<HTMLSelectElement>('[aria-label="函数"]')!
  const labels = overlay.querySelector<HTMLInputElement>('[aria-label="使用左列标签"]')!
  expect(reference.value).toBe("'O''Brien'!A1:B3")
  add.click(); reference.value = "'O''Brien'!A1:B3"; add.click()
  expect(overlay.querySelectorAll('[data-reference]')).toHaveLength(1)
  fn.value = 'max'; labels.checked = true; labels.dispatchEvent(new Event('change'))
  expect(fn.value).toBe('sum')
  expect([...fn.options].map(option => option.value)).toEqual(['sum', 'count', 'average'])
  reference.value = 'Other!A1:B2'
  overlay.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(apply).toHaveBeenCalledWith({ workbookId: 'book', sheetId: 'sheet-1', row: 5, column: 0 }, { fn: 'sum', leftLabels: true, references: ["'O''Brien'!A1:B3", 'Other!A1:B2'] })
  expect(overlay.hidden).toBe(false)
  expect(overlay.querySelector('[role="alert"]')!.textContent).toBe('目标与来源重叠')
  overlay.querySelector<HTMLButtonElement>('[data-reference] button')!.click()
  expect(overlay.querySelectorAll('[data-reference]')).toHaveLength(0)
  overlay.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(apply.mock.calls[1][1].references).toEqual(['Other!A1:B2'])
  expect(overlay.hidden).toBe(true)
  dialog.dispose()
})
