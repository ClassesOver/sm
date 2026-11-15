import { afterEach, expect, it, vi } from 'vitest'
import { createRoot, type Root } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { DocxHomeSource } from './docx-home-source'

const roots: Root[] = []
afterEach(() => {
  for (const root of roots.splice(0)) flushSync(() => root.unmount())
  document.body.replaceChildren()
})

function renderHome(editable = true, onExport?: (format:'pdf'|'html'|'markdown')=>void) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  const noop = () => {}
  const onSpacing = vi.fn()
  const onToggleFormattingMarks = vi.fn()
  flushSync(() => root.render(<DocxHomeSource editable={editable} onExport={onExport} onToggleFormattingMarks={onToggleFormattingMarks} onMark={noop} onFontSize={noop}
    onFontFamily={noop} onFontSizeValue={noop} onColor={noop} onAlignment={noop}
    onIndent={noop} onList={noop} onSpacing={onSpacing} />))
  return {
    host,
    onSpacing,
    onToggleFormattingMarks,
    trigger: host.querySelector<HTMLButtonElement>('[data-source-action="line-spacing-menu"]')!,
    panel: host.querySelector<HTMLDivElement>('[data-source-action="line-spacing-options-menu"]')!,
  }
}

it('opens the GenOffice Home Convert menu and invokes the existing export callback', () => {
  const onExport=vi.fn(),{host}=renderHome(true,onExport)
  const trigger=host.querySelector<HTMLButtonElement>('[data-action="convert-menu"]')!
  flushSync(()=>trigger.click())
  const menu=host.querySelector('[role="menu"][aria-label="转换"]')!
  const options=Array.from(menu.querySelectorAll<HTMLButtonElement>('button'))
  expect(options.map(button=>button.dataset.action)).toEqual(['convert-pdf','convert-html','convert-markdown','export-images'])
  expect(options[3].disabled).toBe(true)
  flushSync(()=>options[0].click())
  expect(onExport).toHaveBeenCalledExactlyOnceWith('pdf')
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  flushSync(()=>trigger.click())
  flushSync(()=>host.querySelector<HTMLButtonElement>('[data-action="convert-markdown"]')!.click())
  expect(onExport).toHaveBeenLastCalledWith('markdown')
  flushSync(()=>trigger.click())
  const option=host.querySelector<HTMLButtonElement>('[data-action="convert-html"]')!
  option.focus()
  flushSync(()=>option.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true})))
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  expect(document.activeElement).toBe(trigger)
  const readonly=renderHome(false,onExport)
  flushSync(()=>readonly.host.querySelector<HTMLButtonElement>('[data-action="convert-menu"]')!.click())
  expect(readonly.host.querySelector<HTMLButtonElement>('[data-action="convert-pdf"]')!.disabled).toBe(true)
  expect(readonly.host.querySelector<HTMLButtonElement>('[data-action="convert-html"]')!.disabled).toBe(false)
})

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

it('keeps the formatting marks view toggle available when the document is read-only', () => {
  const { host, onToggleFormattingMarks } = renderHome(false)
  const toggle = host.querySelector<HTMLButtonElement>('[data-action="formatting-marks"]')!
  expect(toggle.disabled).toBe(false)
  flushSync(() => toggle.click())
  expect(onToggleFormattingMarks).toHaveBeenCalledOnce()
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
