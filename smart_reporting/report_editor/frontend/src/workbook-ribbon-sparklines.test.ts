import { expect, it, vi } from 'vitest'
import { mountWorkbookRibbon } from './workbook-ribbon'

it('dispatches sparkline creation and deletion commands and respects readonly and protection', () => {
  document.body.replaceChildren()
  let editable = true, protectedSheet = false
  const command = vi.fn()
  const ribbon = mountWorkbookRibbon(document.body, command, {
    editable: () => editable, hasSelection: () => true, rotation: () => 0,
    protection: () => ({ sheet: { protected: protectedSheet }, workbook: { locked: false } }),
  })
  try {
    document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Insert"]')!.click()
    const menu = document.querySelector<HTMLSelectElement>('[data-ribbon-control="sparkline-insert"]')!
    expect(menu).not.toBeNull()
    expect(menu.disabled).toBe(false)
    expect(menu.title).toBe('单元格内迷你图，每个所选行一个（放在选区右侧）')
    expect(Array.from(menu.options, option => [option.value, option.text])).toEqual([
      ['', '迷你图'], ['sparkline:line', '折线'], ['sparkline:column', '柱形'], ['sparkline:stacked', '盈亏'],
    ])
    for (const option of Array.from(menu.options).slice(1)) {
      menu.value = option.value
      menu.dispatchEvent(new Event('change'))
      expect(command).toHaveBeenLastCalledWith(option.value)
      expect(menu.value).toBe('')
    }
    const buttons = ['edit', 'delete'].map(type =>
      document.querySelector<HTMLButtonElement>('[data-ribbon-command="sparkline:' + type + '"]')!)
    for (const button of buttons) {
      expect(button.disabled).toBe(false)
      button.click()
      expect(command).toHaveBeenLastCalledWith(button.dataset.ribbonCommand)
    }
    protectedSheet = true; ribbon.refreshState()
    expect([menu, ...buttons].every(control => control.disabled)).toBe(true)
    menu.value = 'sparkline:line'
    menu.dispatchEvent(new Event('change'))
    expect(command).toHaveBeenCalledTimes(5)
    protectedSheet = false; editable = false; ribbon.refreshState()
    expect([menu, ...buttons].every(control => control.disabled)).toBe(true)
  } finally { ribbon.dispose(); document.body.replaceChildren() }
})
