import { afterEach, expect, it, vi } from 'vitest'
import { mountWorkbookRibbon } from './workbook-ribbon'

afterEach(() => document.body.replaceChildren())

const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'] as const
const protections = ['composing', 'legacy229', 'consumed'] as const

for (const protection of protections) for (const key of keys) {
  it(`preserves the workbook ribbon tab for ${protection} ${key}`, () => {
    const command = vi.fn()
    const ribbon = mountWorkbookRibbon(document.body, command, { editable: () => true, rotation: () => 0 })
    const selected = document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Home"]')!
    selected.focus()
    const panel = document.querySelector('[role="tabpanel"]')!
    const firstControl = panel.firstElementChild
    const event = new KeyboardEvent('keydown', {
      key, bubbles: true, cancelable: true,
      isComposing: protection === 'composing',
      keyCode: protection === 'legacy229' ? 229 : 0,
    })
    if (protection === 'consumed') event.preventDefault()
    selected.dispatchEvent(event)
    expect(document.querySelector('[role="tab"][aria-selected="true"]')).toBe(selected)
    expect(document.activeElement).toBe(selected)
    expect(panel.firstElementChild).toBe(firstControl)
    expect(event.defaultPrevented).toBe(protection === 'consumed')
    expect(command).not.toHaveBeenCalled()
    ribbon.dispose()
  })
}

for (const [key, expected] of [['ArrowLeft', 'File'], ['ArrowRight', 'Insert'], ['Home', 'File'], ['End', 'Chart Design']] as const) {
  it(`keeps ordinary workbook tab navigation for ${key}`, () => {
    const command = vi.fn()
    const ribbon = mountWorkbookRibbon(document.body, command, { editable: () => true, rotation: () => 0 })
    document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Home"]')!.focus()
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })
    document.activeElement!.dispatchEvent(event)
    const selected = document.querySelector<HTMLButtonElement>('[role="tab"][aria-selected="true"]')!
    expect(selected.dataset.ribbonTab).toBe(expected)
    expect(document.activeElement).toBe(selected)
    expect(event.defaultPrevented).toBe(true)
    expect(command).not.toHaveBeenCalled()
    ribbon.dispose()
  })
}
