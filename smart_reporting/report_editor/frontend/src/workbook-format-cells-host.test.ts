import { afterEach, expect, it, vi } from 'vitest'
import { createFormatCellsDialog } from './workbook-format-cells-host'
import { draftFromSelection } from './vendor/genoffice-sheets-format/format-cells'
import { act } from 'react'
;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let dialog: ReturnType<typeof createFormatCellsDialog> | undefined
const draft = () => ({ ...draftFromSelection(null), pattern: '0.00', bold: 'on' as const, family: 'Calibri', size: '11', fill: '#ffff00' })
afterEach(() => { act(() => dialog?.dispose()); document.body.replaceChildren() })
function fixture(apply = vi.fn()) {
  const host = document.body.appendChild(document.createElement('main'))
  const opener = document.body.appendChild(document.createElement('button')); opener.focus()
  dialog = createFormatCellsDialog(host, { current: () => ({ draft: draft(), anchor: -1234.5 }), apply })
  act(() => dialog!.open())
  return { host, opener, apply }
}
const click = (text: string) => act(() => { [...document.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === text)!.click() })
async function pick(label: string, text: string) {
  act(() => document.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!.click())
  click(text)
}
it('provides all six fixed-source tabs, keyboard navigation and cancel with no mutation', () => {
  const { host, apply, opener } = fixture()
  expect([...host.querySelectorAll('[role="tab"]')].map(tab => tab.textContent)).toEqual(['数字', '对齐', '字体', '边框', '填充', '保护'])
  const first = host.querySelector<HTMLButtonElement>('[role="tab"]')!
  act(() => first.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true })))
  expect(document.activeElement?.textContent).toBe('保护')
  click('取消')
  expect(apply).not.toHaveBeenCalled(); expect(document.activeElement).toBe(opener)
})
it('treats an untouched dialog as a no-op, and keeps mixed values unchanged', async () => {
  const { apply } = fixture()
  await act(async () => click('确定'))
  expect(apply).not.toHaveBeenCalled()
  expect(document.querySelector('[role="dialog"]')?.getAttribute('hidden')).not.toBeNull()
})
it('collects edits across tabs into one batch and retains the dialog on validation failure', async () => {
  const apply = vi.fn().mockRejectedValueOnce(new Error('预算超限'))
  fixture(apply)
  click('字体'); await pick('加粗', '关')
  click('填充'); act(() => document.querySelector<HTMLInputElement>('.dialog-check input')!.click())
  click('保护'); await pick('锁定', '关'); await pick('隐藏（公式）', '开')
  await act(async () => click('确定'))
  expect(apply).toHaveBeenCalledExactlyOnceWith(['bold:off', 'fill:none', 'cellprot:locked-off:hidden-on'])
  expect(document.querySelector('[role="alert"]')?.textContent).toBe('预算超限')
  expect(document.querySelector('[role="dialog"]')?.hasAttribute('hidden')).toBe(false)
  await act(async () => click('确定'))
  expect(apply).toHaveBeenCalledTimes(2)
  expect(apply.mock.calls[1]).toEqual(apply.mock.calls[0])
})
it('prevents duplicate submissions and cancellation during an asynchronous apply', async () => {
  let finish!: () => void
  const apply = vi.fn(() => new Promise<void>(resolve => { finish = resolve }))
  fixture(apply); click('保护'); await pick('锁定', '关')
  await act(async () => click('确定'))
  click('确定'); click('取消')
  expect(apply).toHaveBeenCalledTimes(1)
  expect(document.querySelector('[role="dialog"]')?.hasAttribute('hidden')).toBe(false)
  await act(async () => finish())
  expect(document.querySelector('[role="dialog"]')?.hasAttribute('hidden')).toBe(true)
})

it('closes only the open color palette on Escape and keeps the current six-tab draft', async () => {
  const { apply } = fixture()
  click('字体'); await pick('加粗', '关')
  act(() => document.querySelector<HTMLButtonElement>('button[aria-label="颜色"]')!.click())
  expect(document.querySelector('.gcp-palette')).not.toBeNull()
  act(() => document.querySelector<HTMLButtonElement>('button[aria-label="颜色"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })))
  expect(document.querySelector('.gcp-palette')).toBeNull()
  expect(document.querySelector('[role="dialog"]')?.hasAttribute('hidden')).toBe(false)
  await act(async () => click('确定'))
  expect(apply).toHaveBeenCalledExactlyOnceWith(['bold:off'])
})

it('echoes a medium line when selecting the thick outline preset and persists that line', async () => {
  const { apply } = fixture()
  click('边框'); await pick('预置', '粗外侧框线')
  expect(document.querySelector<HTMLButtonElement>('button[aria-label="线型"]')?.dataset.value).toBe('medium')
  await act(async () => click('确定'))
  expect(apply).toHaveBeenCalledExactlyOnceWith(['border:thick-outer:#000000:medium'])
})
