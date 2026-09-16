import { beforeEach, describe, expect, it, vi } from 'vitest'
import { showEditorOnboarding } from './onboarding'

describe('showEditorOnboarding', () => {
  beforeEach(() => { document.body.innerHTML = '<main id="app"></main>'; localStorage.clear() })
  it('shows first-use guidance and can dismiss permanently', () => {
    const root = document.querySelector<HTMLElement>('#app')!
    showEditorOnboarding(root, 'report-1')
    expect(root.querySelector('.editor-onboarding')).not.toBeNull()
    root.querySelector<HTMLButtonElement>('[data-onboarding="hide"]')!.click()
    expect(root.querySelector('.editor-onboarding')).toBeNull()
    expect(showEditorOnboarding(root, 'report-1')).toBeNull()
  })

  it('dismisses the current onboarding with Escape without hiding future guidance', () => {
    const root = document.querySelector<HTMLElement>('#app')!
    showEditorOnboarding(root, 'report-1')

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

    expect(root.querySelector('.editor-onboarding')).toBeNull()
    expect(localStorage.getItem('smart-reporting-editor:onboarding:report-1')).toBeNull()
  })

  it('still opens when localStorage reads are blocked', () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    try {
      const root = document.querySelector<HTMLElement>('#app')!

      expect(() => showEditorOnboarding(root, 'report-1')).not.toThrow()
      expect(root.querySelector('.editor-onboarding')).not.toBeNull()
    } finally {
      getItem.mockRestore()
    }
  })

  it('closes permanently-hide action even when localStorage writes fail', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    try {
      const root = document.querySelector<HTMLElement>('#app')!
      showEditorOnboarding(root, 'report-1')

      expect(() =>
        root.querySelector<HTMLButtonElement>('[data-onboarding="hide"]')!.click(),
      ).not.toThrow()
      expect(root.querySelector('.editor-onboarding')).toBeNull()
    } finally {
      setItem.mockRestore()
    }
  })

  it('moves focus into the dialog and restores the opener after dismissing', () => {
    const root = document.querySelector<HTMLElement>('#app')!
    const opener = document.createElement('button')
    root.append(opener)
    opener.focus()

    const panel = showEditorOnboarding(root, 'report-1')!

    expect(panel.getAttribute('aria-modal')).toBe('true')
    expect(document.activeElement).toBe(panel.querySelector('[data-onboarding="dismiss"]'))
    panel.querySelector<HTMLButtonElement>('[data-onboarding="dismiss"]')!.click()
    expect(document.activeElement).toBe(opener)
  })
})
