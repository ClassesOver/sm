import { afterEach, expect, it, vi } from 'vitest'
import { createEditableRangesDialog } from './workbook-editable-ranges-dialog'

afterEach(() => document.body.replaceChildren())
function setup(apply: Parameters<typeof createEditableRangesDialog>[1] = async () => {}) {
  const entry = document.createElement('button'); document.body.append(entry); entry.focus()
  const dialog = createEditableRangesDialog(document.body, apply)
  const input = { sheetName: 'Inputs', selection: 'E2:E4', ranges: [{ name: 'Entry', sqref: 'B2:C4' }] }
  dialog.open(input)
  const card = document.querySelector<HTMLElement>('section.modal-card')!
  const field = (label: string) => card.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!
  return { dialog, input, card, field, entry }
}

it('puts a newly added region into keyboard editing immediately', () => {
  const { dialog, card, field } = setup()
  card.querySelector<HTMLButtonElement>('[data-action=add]')!.click()
  expect(document.activeElement).toBe(field('区域名称 2'))
  expect(field('区域引用 2').value).toBe('E2:E4')
  expect(card.querySelector('[role=status]')?.textContent).toContain('2')
  dialog.dispose()
})

it('keeps focus on the next region, previous region, then add after deletion', () => {
  const { dialog, card, field } = setup()
  card.querySelector<HTMLButtonElement>('[data-action=add]')!.click()
  card.querySelector<HTMLButtonElement>('[data-action=add]')!.click()
  const remove = (index: number) => { const button = card.querySelectorAll<HTMLButtonElement>('[data-range] button')[index]!; button.focus(); button.click() }
  remove(1); expect(document.activeElement).toBe(field('区域名称 2'))
  remove(1); expect(document.activeElement).toBe(field('区域名称 1'))
  remove(0); expect(document.activeElement).toBe(card.querySelector('[data-action=add]'))
  expect(card.querySelector('[role=status]')?.textContent).toContain('0')
  dialog.dispose()
})

it('freezes the opened target and selection against caller changes', async () => {
  let submitted: unknown
  const { dialog, input, card, field } = setup(async (sheetName, ranges) => { submitted = { sheetName, ranges } })
  input.sheetName = 'WrongSheet'; input.selection = 'Z99'; input.ranges[0]!.name = 'Changed'
  card.querySelector<HTMLButtonElement>('[data-action=add]')!.click(); field('区域名称 2').value = 'Extra'
  card.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  await vi.waitFor(() => expect(submitted).toEqual({ sheetName: 'Inputs', ranges: [{ name: 'Entry', sqref: 'B2:C4' }, { name: 'Extra', sqref: 'E2:E4' }] }))
  dialog.dispose()
})

it('provides keyboard reading while pending and reveals a retryable failure without losing fields', async () => {
  let fail!: (cause: Error) => void
  const { dialog, card, field } = setup(() => new Promise((_, reject) => { fail = reject }))
  const status = card.querySelector<HTMLElement>('[role=status]')
  expect(status?.getAttribute('tabindex')).toBe('0')
  const error = card.querySelector<HTMLElement>('[role=alert]')!
  const reveal = vi.fn(); error.scrollIntoView = reveal
  field('区域名称 1').value = 'Preserved'
  card.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  await vi.waitFor(() => expect(fail).toBeTypeOf('function'))
  expect(card.closest('[role=dialog]')?.getAttribute('aria-busy')).toBe('true')
  expect(document.activeElement).toBe(status)
  expect([...card.querySelectorAll<HTMLInputElement | HTMLButtonElement>('input,button')].every(n => n.disabled)).toBe(true)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  expect(card.closest<HTMLElement>('[role=dialog]')!.hidden).toBe(false)
  fail(new Error('区域名称重复，请修改名称后重试。'))
  await vi.waitFor(() => expect(field('区域名称 1').disabled).toBe(false))
  expect(field('区域名称 1').value).toBe('Preserved')
  expect(error.textContent).toContain('名称重复')
  expect(document.activeElement).toBe(error)
  expect(reveal).toHaveBeenCalledWith({ block: 'nearest' })
  expect(card.closest('[role=dialog]')?.getAttribute('aria-busy')).toBe('false')
  dialog.dispose()
})

it('makes protected reasons readable and leaves cancel usable', () => {
  const { dialog, card, entry } = setup()
  dialog.open({ sheetName: 'Inputs', ranges: [{ name: 'Secret', sqref: 'A1', readonlyReason: '需要密码' }] })
  const error = card.querySelector<HTMLElement>('[role=alert]')!
  expect(document.activeElement).toBe(error)
  expect(error.getAttribute('aria-label')).toBeTruthy()
  expect(card.querySelector<HTMLButtonElement>('[type=submit]')!.disabled).toBe(true)
  card.querySelector<HTMLButtonElement>('[data-action=cancel]')!.click()
  // 重开仍在同一弹窗内时不以外部入口为回焦契约；首次打开取消在下一项覆盖。
  expect(card.closest<HTMLElement>('[role=dialog]')!.hidden).toBe(true)
  dialog.dispose(); entry.remove()
})

it('cancels edited definitions without applying them and restores the entry focus', () => {
  let applied = false
  const { dialog, card, entry, field } = setup(async () => { applied = true })
  field('区域名称 1').value = 'Cancelled'
  card.querySelector<HTMLButtonElement>('[data-action=cancel]')!.click()
  expect(applied).toBe(false); expect(document.activeElement).toBe(entry)
  dialog.dispose()
})
