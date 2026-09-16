import { beforeEach, describe, expect, it } from 'vitest'
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
})
