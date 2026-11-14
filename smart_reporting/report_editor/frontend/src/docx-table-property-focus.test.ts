// @vitest-environment jsdom
import { afterEach, expect, it } from 'vitest'
import { openDocxCellMarginOverridesDialog } from './docx-table-cell-margin-overrides-controls'
import { openDocxRowBreaksDialog } from './docx-table-row-breaks-controls'
import { openDocxTableAlignmentDialog } from './docx-table-alignment-controls'

afterEach(() => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); document.body.replaceChildren() })

for (const action of ['row-breaks', 'table-alignment']) {
  it(`${action} 关闭后恢复外部入口焦点`, () => {
    const opener = document.createElement('button'), root = document.createElement('div')
    document.body.append(opener, root); opener.focus()
    openDocxCellMarginOverridesDialog(root, { top: 0, right: 109, bottom: 7, left: 108 }, '', () => {},
      { reason: null, open: () => openDocxRowBreaksDialog(root, null, 0, 3, () => {}) },
      { reason: null, open: () => openDocxTableAlignmentDialog(root, 'left', false, () => {}) })
    root.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!.click()
    expect(root.querySelectorAll('[role=dialog]')).toHaveLength(1)
    expect(root.querySelector('[role=dialog]')!.contains(document.activeElement)).toBe(true)
    root.querySelector<HTMLButtonElement>('[data-action=cancel]')!.click()
    expect(root.querySelector('[role=dialog]')).toBeNull()
    expect(document.activeElement).toBe(opener)
  })
}

it('二级设置打开失败后保留边距草稿并允许关闭回到入口', () => {
  const opener = document.createElement('button'), root = document.createElement('div')
  document.body.append(opener, root); opener.focus()
  openDocxCellMarginOverridesDialog(root, { top: 0, right: 109, bottom: 7, left: 108 }, '', () => {},
    { reason: null, open: () => { throw new Error('选区已变化') } })
  root.querySelector<HTMLInputElement>('[data-margin=left]')!.value = '12'
  root.querySelector<HTMLButtonElement>('[data-action=row-breaks]')!.click()
  expect(root.querySelector<HTMLElement>('[role=dialog]')!.hidden).toBe(false)
  expect(root.querySelector<HTMLInputElement>('[data-margin=left]')!.value).toBe('12')
  expect(root.querySelector('[role=alert]')!.textContent).toBe('选区已变化')
  expect(root.querySelector('[role=dialog]')!.contains(document.activeElement)).toBe(true)
  root.querySelector<HTMLButtonElement>('[data-action=cancel]')!.click()
  expect(document.activeElement).toBe(opener)
})
