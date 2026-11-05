import { afterEach, expect, it, vi } from 'vitest'
import { createRoot, type Root } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { DocxHomeSource } from './docx-home-source'

const roots: Root[] = []
afterEach(() => {
  for (const root of roots.splice(0)) flushSync(() => root.unmount())
  document.body.replaceChildren()
})

function renderHome() {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  const noop = () => {}
  const onSpacing = vi.fn()
  flushSync(() => root.render(<DocxHomeSource editable onMark={noop} onFontSize={noop}
    onFontFamily={noop} onFontSizeValue={noop} onColor={noop} onAlignment={noop}
    onIndent={noop} onList={noop} onSpacing={onSpacing} />))
  return {
    host,
    onSpacing,
    trigger: host.querySelector<HTMLButtonElement>('[data-source-action="line-spacing-menu"]')!,
    panel: host.querySelector<HTMLDivElement>('[data-source-action="line-spacing-options-menu"]')!,
  }
}

it.each(['outside pointerdown', 'Escape', 'window blur'])('dismisses the spacing popup on %s without invoking a spacing command', reason => {
  const { host, trigger, panel, onSpacing } = renderHome()
  flushSync(() => trigger.click())
  expect(trigger.getAttribute('aria-expanded')).toBe('true')
  expect(panel.hidden).toBe(false)
  const outside = document.createElement('button')
  host.append(outside)
  // 别的控件即使阻止冒泡，上游 capture-phase listener 也应关闭菜单。
  outside.addEventListener('pointerdown', event => event.stopPropagation())
  flushSync(() => {
    if (reason === 'outside pointerdown') outside.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    else if (reason === 'Escape') window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    else window.dispatchEvent(new Event('blur'))
  })
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  expect(panel.hidden).toBe(true)
  expect(onSpacing).not.toHaveBeenCalled()
})

it('keeps the spacing popup open for internal presses and other keys, and lets its trigger toggle it closed', () => {
  const { host, trigger, panel } = renderHome()
  flushSync(() => trigger.click())
  const preset = host.querySelector<HTMLButtonElement>('[data-source-action="line-spacing-2"]')!
  flushSync(() => {
    preset.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
  })
  expect(panel.hidden).toBe(false)
  flushSync(() => {
    trigger.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    trigger.click()
  })
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  expect(panel.hidden).toBe(true)
})
