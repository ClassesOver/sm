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
    for (const type of ['line', 'column', 'stacked', 'edit', 'delete']) {
      const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="sparkline:${type}"]`)!
      expect(button).not.toBeNull()
      expect(button.disabled).toBe(false)
      button.click()
      expect(command).toHaveBeenLastCalledWith(`sparkline:${type}`)
      protectedSheet = true; ribbon.refreshState()
      expect(button.disabled).toBe(true)
      protectedSheet = false; editable = false; ribbon.refreshState()
      expect(button.disabled).toBe(true)
      editable = true; ribbon.refreshState()
    }
  } finally { ribbon.dispose(); document.body.replaceChildren() }
})
