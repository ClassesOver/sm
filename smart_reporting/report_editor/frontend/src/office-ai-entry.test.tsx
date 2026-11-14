import { afterEach, expect, it, vi } from 'vitest'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { createOfficeAIEntry, OfficeAIEntry } from './office-ai-entry'
import { mountWorkbookRibbon } from './workbook-ribbon'
import { createSlidesNativeRibbon } from './slides-native-ribbon'

afterEach(() => document.body.replaceChildren())

it('React 和 DOM 入口采用相同 GenOffice 图标、中文名称和可用状态', () => {
  const host = document.body.appendChild(document.createElement('div'))
  const root = createRoot(host), open = vi.fn()
  flushSync(() => root.render(<OfficeAIEntry onOpen={open} />))
  const dom = createOfficeAIEntry(open)
  const react = host.querySelector('button')!
  expect(dom.innerHTML).toBe(react.innerHTML)
  for (const button of [dom, react]) {
    expect(button.textContent).toBe('AI 助手')
    expect(button.getAttribute('aria-label')).toBe('AI 助手')
    expect(button.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true')
    button.click()
  }
  expect(open).toHaveBeenCalledTimes(2)
  expect(createOfficeAIEntry().disabled).toBe(true)
  flushSync(() => root.unmount())
})

it('XLSX 助手位于开始首组，切换标签、无选区和只读刷新后仍能打开', () => {
  const host = document.body.appendChild(document.createElement('div')), open = vi.fn()
  const ribbon = mountWorkbookRibbon(host, vi.fn(), { rotation: () => undefined, editable: () => false, onAssistant: open })
  const check = () => {
    const group = host.querySelector('.workbook-ribbon-body > section')!
    expect(group.querySelector('h2')?.textContent).toBe('AI 助手')
    group.querySelector<HTMLButtonElement>('button')!.click()
  }
  check()
  host.querySelector<HTMLButtonElement>('[data-ribbon-tab=Insert]')!.click()
  host.querySelector<HTMLButtonElement>('[data-ribbon-tab=Home]')!.click()
  ribbon.refreshState(); check()
  expect(open).toHaveBeenCalledTimes(2)
  ribbon.dispose()
})

it('PPTX 助手位于开始首组，编辑锁不阻断阅读入口', () => {
  const host = document.body.appendChild(document.createElement('div')), open = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction: vi.fn(), onAssistant: open })
  const first = host.querySelector('[data-ribbon-panel=home] > section')!
  expect(first.querySelector('h2')?.textContent).toBe('AI 助手')
  ribbon.setLocked(true)
  first.querySelector<HTMLButtonElement>('button')!.click()
  expect(open).toHaveBeenCalledOnce()
  ribbon.dispose()
})
