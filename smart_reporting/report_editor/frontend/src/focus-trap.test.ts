import { describe, expect, it } from 'vitest'

import { installFocusTrap } from './focus-trap'

describe('installFocusTrap', () => {
  it('cycles tab focus within an open dialog', () => {
    const dialog = document.createElement('section')
    const first = document.createElement('button')
    const last = document.createElement('button')
    dialog.append(first, last)
    document.body.append(dialog)
    Object.defineProperty(first, 'offsetParent', { value: document.body })
    Object.defineProperty(last, 'offsetParent', { value: document.body })
    installFocusTrap(dialog)

    last.focus()
    const forward = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true })
    dialog.dispatchEvent(forward)
    expect(document.activeElement).toBe(first)

    first.focus()
    const backward = new KeyboardEvent('keydown', {
      key: 'Tab',
      shiftKey: true,
      bubbles: true,
    })
    dialog.dispatchEvent(backward)
    expect(document.activeElement).toBe(last)
  })
})
