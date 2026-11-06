import { describe, expect, it, vi } from 'vitest'
import { createToolbar } from './toolbar'
describe('toolbar registry', () => {
  it('keeps three slots and refreshes visibility, disabled state and contextual label', () => {
    const host = document.createElement('div'); const toolbar = createToolbar(host); let enabled = false
    const remove = toolbar.registerToolbarAction({ id: 'chart-ai', bar: 'context', label: '改图', run: vi.fn(),
      visible: () => toolbar.getContextTarget()?.kind === 'chart', disabled: () => !enabled })
    const button = host.querySelector('button')!
    expect(host.querySelectorAll('[role="toolbar"]')).toHaveLength(3); expect(button.hidden).toBe(true)
    toolbar.setContextTarget({ kind: 'chart', label: '收入' }); expect(button.hidden).toBe(false); expect(button.disabled).toBe(true)
    enabled = true; toolbar.refreshToolbar(); expect(button.disabled).toBe(false)
    expect(toolbar.bars.context.getAttribute('aria-label')).toContain('收入'); remove(); expect(host.querySelector('button')).toBeNull()
  })
  it('guards double clicks and reports failures while restoring button state', async () => {
    const host = document.createElement('div'); const toolbar = createToolbar(host)
    const error = vi.fn(); host.addEventListener('toolbar-error', error)
    let reject!: (error: Error) => void
    const run = vi.fn(() => new Promise<void>((_resolve, fail) => { reject = fail }))
    toolbar.registerToolbarAction({ id: 'save', label: '保存', bar: 'public', run })
    const button = host.querySelector('button')!; button.click(); button.click()
    expect(run).toHaveBeenCalledTimes(1); expect(button.disabled).toBe(true)
    reject(new Error('failed')); await vi.waitFor(() => expect(button.disabled).toBe(false)); expect(error).toHaveBeenCalledTimes(1)
  })
})
it('registers existing shell buttons without duplicating nodes or icons', async () => {
  const host = document.createElement('div'); const button = document.createElement('button')
  button.dataset.action = 'save'; button.innerHTML = '<i data-lucide="save"></i>保存'
  host.append(button); const toolbar = createToolbar(host); const run = vi.fn()
  toolbar.registerToolbarAction({ id: 'save', label: '保存', bar: 'public', run })
  expect(toolbar.bars.public.querySelectorAll('button')).toHaveLength(1)
  expect(toolbar.bars.public.firstElementChild).toBe(button)
  button.click(); await vi.waitFor(() => expect(button.disabled).toBe(false)); expect(run).toHaveBeenCalledTimes(1)
})
