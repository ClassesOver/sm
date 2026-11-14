import { describe, expect, it } from 'vitest'

import { installFocusTrap } from './focus-trap'

it('原生证书链折叠标题占用Tab边界，无定位按钮时仍能由键盘进入', () => {
  const dialog = document.body.appendChild(document.createElement('section'))
  const details = dialog.appendChild(document.createElement('details'))
  const summary = details.appendChild(document.createElement('summary')); summary.textContent = '证书链'
  const last = dialog.appendChild(document.createElement('button')); last.textContent = '关闭'
  for (const control of [summary, last]) Object.defineProperty(control, 'offsetParent', { value: document.body })
  const release = installFocusTrap(dialog)
  try {
    last.focus()
    last.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(summary)
    summary.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(last)
  } finally { release(); dialog.remove() }
})

describe('installFocusTrap', () => {
  it.each([
    { mode: 'composition', shiftKey: false },
    { mode: 'composition', shiftKey: true },
    { mode: 'legacy229', shiftKey: false },
    { mode: 'legacy229', shiftKey: true },
  ])('does not redirect $mode Tab input at a dialog boundary (reverse=$shiftKey)', ({ mode, shiftKey }) => {
    const dialog = document.body.appendChild(document.createElement('section'))
    const first = dialog.appendChild(document.createElement('button'))
    const last = dialog.appendChild(document.createElement('button'))
    for (const button of [first, last]) Object.defineProperty(button, 'offsetParent', { value: document.body })
    const release = installFocusTrap(dialog)
    const active = shiftKey ? first : last
    active.focus()
    const event = new KeyboardEvent('keydown', {
      key: 'Tab', shiftKey, bubbles: true, cancelable: true,
      isComposing: mode === 'composition', keyCode: mode === 'legacy229' ? 229 : 0,
    })
    active.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(false)
    expect(document.activeElement).toBe(active)
    release(); dialog.remove()
  })

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

it('嵌套弹窗的Tab已循环时，祖先焦点约束不再处理同一按键', () => {
  const parent = document.body.appendChild(document.createElement('section'))
  const outside = parent.appendChild(document.createElement('button'))
  const child = parent.appendChild(document.createElement('section'))
  const first = child.appendChild(document.createElement('button'))
  const last = child.appendChild(document.createElement('button'))
  for (const button of [outside, first, last]) Object.defineProperty(button, 'offsetParent', { value: document.body })
  const releaseParent = installFocusTrap(parent), releaseChild = installFocusTrap(child)
  first.focus()
  first.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }))
  expect(document.activeElement).toBe(last)
  last.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
  expect(document.activeElement).toBe(first)
  first.remove(); last.focus()
  last.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
  expect(document.activeElement).toBe(last)
  releaseChild(); releaseParent(); parent.remove()
})

it('单选组只有已选项进入Tab顺序，Shift+Tab从该项回到窗口末尾', () => {
  const dialog = document.body.appendChild(document.createElement('section'))
  const radios = ['200', '100', 'custom'].map(value => {
    const input = dialog.appendChild(document.createElement('input'))
    input.type = 'radio'; input.name = 'zoom'; input.value = value; input.checked = value === 'custom'
    Object.defineProperty(input, 'offsetParent', { value: document.body }); return input
  })
  const last = dialog.appendChild(document.createElement('button'))
  Object.defineProperty(last, 'offsetParent', { value: document.body })
  const release = installFocusTrap(dialog)
  radios[2].focus()
  radios[2].dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }))
  expect(document.activeElement).toBe(last)
  last.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
  expect(document.activeElement).toBe(radios[2])
  release(); dialog.remove()
})

it('负tabindex与禁用fieldset内字段不占用窗口首尾Tab边界', () => {
  const dialog = document.body.appendChild(document.createElement('section'))
  const skipped = dialog.appendChild(document.createElement('input')); skipped.tabIndex = -1
  const disabled = dialog.appendChild(document.createElement('fieldset')); disabled.disabled = true
  const blocked = disabled.appendChild(document.createElement('input'))
  const only = dialog.appendChild(document.createElement('button'))
  for (const control of [skipped, blocked, only]) Object.defineProperty(control, 'offsetParent', { value: document.body })
  const release = installFocusTrap(dialog)
  only.focus()
  const forward = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
  only.dispatchEvent(forward)
  expect(forward.defaultPrevented).toBe(true)
  expect(document.activeElement).toBe(only)
  const reverse = new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true })
  only.dispatchEvent(reverse)
  expect(reverse.defaultPrevented).toBe(true)
  expect(document.activeElement).toBe(only)
  release(); dialog.remove()
})
