import { afterEach, expect, it, vi } from 'vitest'
import { openSlidesSizeDialog } from './slides-size-dialog'

afterEach(() => document.body.replaceChildren())

it.each(['cancel', 'title', 'escape'])('returns focus without applying custom dimensions on %s', action => {
  const opener = document.body.appendChild(document.createElement('button'))
  opener.focus()
  const apply = vi.fn()
  openSlidesSizeDialog(document.body, { cx: 9144123, cy: 6858000 }, apply)
  const dialog = document.querySelector('dialog')!
  const width = dialog.querySelector<HTMLInputElement>('[aria-label="幻灯片宽度"]')!
  expect(document.activeElement).toBe(width)
  width.value = '42'
  if (action === 'escape') {
    const event = new Event('cancel', { cancelable: true })
    dialog.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
  } else {
    const close = dialog.querySelector<HTMLButtonElement>(action === 'title' ? '[aria-label="关闭自定义幻灯片尺寸"]' : '[data-command="cancelCustomSlideSize"]')
    expect(close).not.toBeNull()
    close!.click()
  }
  expect(dialog.isConnected).toBe(false)
  expect(document.activeElement).toBe(opener)
  expect(apply).not.toHaveBeenCalled()
})

it('converts units without rounding untouched EMU coordinates', () => {
  const apply = vi.fn()
  openSlidesSizeDialog(document.body, { cx: 9144123, cy: 6858000 }, apply)
  const unit = document.querySelector<HTMLSelectElement>('[aria-label="尺寸单位"]')!
  unit.value = 'in'; unit.dispatchEvent(new Event('change'))
  expect(document.querySelector<HTMLInputElement>('[aria-label="幻灯片宽度"]')!.value).toBe('10')
  document.querySelector<HTMLButtonElement>('[data-command="applyCustomSlideSize"]')!.click()
  expect(apply).toHaveBeenCalledWith({ cx: 9144123, cy: 6858000 })
})

it.each(['', '-1', 'NaN', 'Infinity', '57'])('rejects invalid inch dimensions %s', value => {
  const apply = vi.fn()
  openSlidesSizeDialog(document.body, { cx: 9144000, cy: 6858000 }, apply)
  const unit = document.querySelector<HTMLSelectElement>('[aria-label="尺寸单位"]')!
  unit.value = 'in'; unit.dispatchEvent(new Event('change'))
  document.querySelector<HTMLInputElement>('[aria-label="幻灯片宽度"]')!.value = value
  document.querySelector<HTMLButtonElement>('[data-command="applyCustomSlideSize"]')!.click()
  expect(apply).not.toHaveBeenCalled()
  expect(document.querySelector('dialog')).not.toBeNull()
})

it('rejects untouched source coordinates outside the supported OOXML range', () => {
  const apply = vi.fn()
  openSlidesSizeDialog(document.body, { cx: 914399, cy: 6858000 }, apply)
  document.querySelector<HTMLButtonElement>('[data-command="applyCustomSlideSize"]')!.click()
  expect(apply).not.toHaveBeenCalled()
  expect(document.querySelector('[role="alert"]')!.textContent).toContain('1–56')
})

it('uses the Office dialog layout and Chinese accessible names with a distinct primary action', () => {
  openSlidesSizeDialog(document.body, { cx: 9144000, cy: 6858000 }, vi.fn())
  const dialog = document.querySelector('dialog')!
  expect(dialog.classList.contains('slides-table-dialog')).toBe(true)
  expect(dialog.getAttribute('aria-label')).toBe('自定义幻灯片尺寸')
  expect(dialog.querySelector('[aria-label="幻灯片高度"]')).not.toBeNull()
  expect(dialog.querySelector('.slides-table-actions [value="ok"]')?.textContent).toBe('应用')
})
