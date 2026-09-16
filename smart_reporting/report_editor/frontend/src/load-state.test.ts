import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createLoadStatePanel } from './load-state'

describe('createLoadStatePanel', () => {
  beforeEach(() => {
    document.body.innerHTML = '<main id="app"><section class="editor-surface"></section></main>'
  })

  it('shows an accessible loading state instead of a blank editor', () => {
    const panel = createLoadStatePanel(document.querySelector<HTMLElement>('#app')!)

    panel.showLoading()

    expect(panel.element.hidden).toBe(false)
    expect(panel.element.getAttribute('role')).toBe('status')
    expect(panel.element.textContent).toContain('正在打开报告')
    expect(panel.element.querySelector<HTMLButtonElement>('button')?.hidden).toBe(true)
  })

  it('explains an expired session and retries through the provided action', () => {
    const retry = vi.fn()
    const panel = createLoadStatePanel(document.querySelector<HTMLElement>('#app')!)

    panel.showError({ status: 410 }, retry)

    expect(panel.element.getAttribute('role')).toBe('alert')
    expect(panel.element.textContent).toContain('编辑会话已过期')
    panel.element.querySelector<HTMLButtonElement>('button')!.click()
    expect(retry).toHaveBeenCalledOnce()
  })

  it('uses a network-specific message for fetch failures', () => {
    const panel = createLoadStatePanel(document.querySelector<HTMLElement>('#app')!)

    panel.showError(new TypeError('Failed to fetch'), vi.fn())

    expect(panel.element.textContent).toContain('无法连接报告服务')
    expect(panel.element.textContent).toContain('检查网络')
  })
})
