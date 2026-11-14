import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { bindPdfPrintDialog, parsePdfPrintPages } from './pdf-print-dialog'

beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.open = true } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value(this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event('close')) } })
})
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })

it('matches fixed-source page range parsing and rejects malformed, reversed, and out-of-range input', () => {
  expect(parsePdfPrintPages(' 4,1-2,, 2，3–4 ', 4)).toEqual([1, 2, 3, 4])
  expect(parsePdfPrintPages('3,1-2', 4)).toEqual([1, 2, 3])
  for (const value of ['0', '5', '3-1', '1.5', '1e2', 'x', '1-', '-2']) expect(parsePdfPrintPages(value, 4)).toBeNull()
  expect(parsePdfPrintPages('', 4)).toBeNull()
})

it('opens from the print trigger and prints all, current visible page, or a parsed visible range', () => {
  const root = document.createElement('main'), trigger = document.createElement('button')
  document.body.append(root, trigger)
  const printed = vi.fn(), view = bindPdfPrintDialog({ root, trigger, pageCount: () => 4, currentPage: () => 3, print: printed })
  const dialog = root.querySelector<HTMLDialogElement>('dialog')!
  const range = dialog.querySelector<HTMLInputElement>('[aria-label="打印页码"]')!
  const parity = dialog.querySelector<HTMLSelectElement>('[aria-label="打印页面子集"]')!
  trigger.click()
  expect(dialog.open).toBe(true)
  dialog.querySelector<HTMLButtonElement>('[data-pdf-print-confirm]')!.click()
  expect(printed).toHaveBeenLastCalledWith([1, 2, 3, 4])
  expect(dialog.open).toBe(false)

  trigger.click()
  dialog.querySelector<HTMLInputElement>('input[value="current"]')!.click()
  dialog.querySelector<HTMLButtonElement>('[data-pdf-print-confirm]')!.click()
  expect(printed).toHaveBeenLastCalledWith([3])

  trigger.click()
  dialog.querySelector<HTMLInputElement>('input[value="all"]')!.click()
  parity.value = 'odd'; parity.dispatchEvent(new Event('change'))
  dialog.querySelector<HTMLButtonElement>('[data-pdf-print-confirm]')!.click()
  expect(printed).toHaveBeenLastCalledWith([1, 3])

  trigger.click()
  dialog.querySelector<HTMLInputElement>('input[value="all"]')!.click()
  parity.value = 'even'; parity.dispatchEvent(new Event('change'))
  dialog.querySelector<HTMLButtonElement>('[data-pdf-print-confirm]')!.click()
  expect(printed).toHaveBeenLastCalledWith([2, 4])

  trigger.click()
  dialog.querySelector<HTMLInputElement>('input[value="custom"]')!.click()
  range.value = '4,2-3'
  parity.value = 'even'; parity.dispatchEvent(new Event('change'))
  range.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }))
  expect(printed).toHaveBeenLastCalledWith([2, 4])
  view.dispose()
})

it('keeps an invalid selection open and reports its error without printing', () => {
  const root = document.createElement('main'), trigger = document.createElement('button')
  document.body.append(root, trigger)
  const printed = vi.fn(), view = bindPdfPrintDialog({ root, trigger, pageCount: () => 4, currentPage: () => 1, print: printed })
  trigger.click()
  const dialog = root.querySelector<HTMLDialogElement>('dialog')!
  dialog.querySelector<HTMLInputElement>('input[value="custom"]')!.click()
  dialog.querySelector<HTMLInputElement>('[aria-label="打印页码"]')!.value = '4-2'
  dialog.querySelector<HTMLButtonElement>('[data-pdf-print-confirm]')!.click()
  expect(dialog.open).toBe(true)
  expect(dialog.querySelector('[role="status"]')!.textContent).toContain('页码')
  expect(printed).not.toHaveBeenCalled()
  dialog.querySelector<HTMLInputElement>('input[value="current"]')!.click()
  dialog.querySelector<HTMLSelectElement>('[aria-label="打印页面子集"]')!.value = 'even'
  dialog.querySelector<HTMLSelectElement>('[aria-label="打印页面子集"]')!.dispatchEvent(new Event('change'))
  dialog.querySelector<HTMLButtonElement>('[data-pdf-print-confirm]')!.click()
  expect(dialog.open).toBe(true)
  expect(dialog.querySelector('[role="status"]')!.textContent).toContain('空')
  expect(printed).not.toHaveBeenCalled()
  view.dispose()
})
