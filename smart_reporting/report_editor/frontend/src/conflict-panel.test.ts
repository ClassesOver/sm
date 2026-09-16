import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createConflictPanel } from './conflict-panel'

describe('createConflictPanel', () => {
  beforeEach(() => { document.body.innerHTML = '<main id="app"></main>' })
  it('shows local and remote choices with a safe diff', () => {
    const keepLocal = vi.fn()
    const mergeAndRetry = vi.fn()
    const panel = createConflictPanel(document.body, { keepLocal, useRemote: vi.fn(), mergeAndRetry })
    panel.show('原文', '本地', '远端')
    expect(panel.panel.textContent).toContain('本地：本地')
    panel.panel.querySelector<HTMLButtonElement>('[data-conflict="local"]')!.click()
    expect(keepLocal).toHaveBeenCalledOnce()
    panel.show('# base', '# local', '# remote')
    const merge = panel.panel.querySelector<HTMLTextAreaElement>('[data-conflict="merge"]')!
    merge.value = '# merged'
    panel.panel.querySelector<HTMLButtonElement>('[data-conflict="merge-retry"]')!.click()
    expect(mergeAndRetry).toHaveBeenCalledWith('# merged')
    expect(panel.panel.hidden).toBe(true)
  })
})
