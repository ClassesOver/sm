import { afterEach, expect, it, vi } from 'vitest'
import { openSlidesSizeDialog } from './slides-size-dialog'

afterEach(() => document.body.replaceChildren())

it('converts units without rounding untouched EMU coordinates', () => {
  const apply = vi.fn()
  openSlidesSizeDialog(document.body, { cx: 9144123, cy: 6858000 }, apply)
  const unit = document.querySelector<HTMLSelectElement>('[aria-label="Size Unit"]')!
  unit.value = 'in'; unit.dispatchEvent(new Event('change'))
  expect(document.querySelector<HTMLInputElement>('[aria-label="Slide Width"]')!.value).toBe('10')
  document.querySelector<HTMLButtonElement>('[data-command="applyCustomSlideSize"]')!.click()
  expect(apply).toHaveBeenCalledWith({ cx: 9144123, cy: 6858000 })
})

it.each(['', '-1', 'NaN', 'Infinity', '57'])('rejects invalid inch dimensions %s', value => {
  const apply = vi.fn()
  openSlidesSizeDialog(document.body, { cx: 9144000, cy: 6858000 }, apply)
  const unit = document.querySelector<HTMLSelectElement>('[aria-label="Size Unit"]')!
  unit.value = 'in'; unit.dispatchEvent(new Event('change'))
  document.querySelector<HTMLInputElement>('[aria-label="Slide Width"]')!.value = value
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
