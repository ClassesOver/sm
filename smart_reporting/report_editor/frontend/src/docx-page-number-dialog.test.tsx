import { afterEach, expect, it, vi } from 'vitest'
import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { DocxPageNumberDialog } from './docx-page-number-dialog'

const cleanup: (() => void)[] = []
afterEach(() => { cleanup.splice(0).forEach(dispose => dispose()); document.body.replaceChildren() })
function setup(commit = vi.fn()) {
  const opener = document.body.appendChild(document.createElement('button')); opener.focus()
  const host = document.body.appendChild(document.createElement('div')), root = createRoot(host)
  let lock!: (reason?: string) => void
  function Fixture() {
    const [open, setOpen] = useState(true)
    const [disabledReason, setDisabledReason] = useState<string>()
    lock = reason => flushSync(() => setDisabledReason(reason))
    return open ? <DocxPageNumberDialog format="upperRoman" start={3} disabledReason={disabledReason} onChange={commit} onClose={() => setOpen(false)} /> : null
  }
  flushSync(() => root.render(<Fixture />))
  cleanup.push(() => flushSync(() => root.unmount()))
  const fill = (value: string) => {
    const input = host.querySelector('input')!
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    flushSync(() => input.dispatchEvent(new Event('input', { bubbles:true })))
  }
  const submit = () => flushSync(() => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles:true, cancelable:true })))
  return { host, opener, commit, fill, submit, lock }
}

it('focuses the format field and restores the opener after Escape without committing', () => {
  const f = setup()
  expect(document.activeElement).toBe(f.host.querySelector('select'))
  flushSync(() => document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key:'Escape', bubbles:true })))
  expect(f.host.querySelector('[role=dialog]')).toBeNull()
  expect(document.activeElement).toBe(f.opener)
  expect(f.commit).not.toHaveBeenCalled()
})

it.each(['composition', 'legacy', 'consumed'] as const)('keeps the page number draft and focus when %s Escape belongs to the field', protection => {
  const f = setup(); f.fill('12')
  const input = f.host.querySelector('input')!
  input.focus()
  const event = new KeyboardEvent('keydown', {
    key: 'Escape', bubbles: true, cancelable: true,
    isComposing: protection === 'composition', keyCode: protection === 'legacy' ? 229 : 0,
  })
  if (protection === 'consumed') event.preventDefault()
  flushSync(() => input.dispatchEvent(event))
  expect(f.host.querySelector('[role=dialog]')).not.toBeNull()
  expect(input.value).toBe('12')
  expect(document.activeElement).toBe(input)
  expect(f.commit).not.toHaveBeenCalled()
  if (protection !== 'consumed') expect(event.defaultPrevented).toBe(false)
  flushSync(() => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })))
  expect(f.host.querySelector('[role=dialog]')).toBeNull()
  expect(document.activeElement).toBe(f.opener)
  expect(f.commit).not.toHaveBeenCalled()
})

it('explains invalid starts inline and commits a corrected value using the same section protocol', () => {
  const f = setup(); f.fill('9007199254740992'); f.submit()
  expect(f.host.querySelector('[role=alert]')?.textContent).toContain('起始页码')
  expect(f.host.querySelector('input')?.getAttribute('aria-invalid')).toBe('true')
  expect(f.commit).not.toHaveBeenCalled()
  f.fill('0'); f.submit()
  expect(f.commit).toHaveBeenCalledExactlyOnceWith({ pageNumberFmt:'upperRoman', pageNumberStart:0 })
  expect(document.activeElement).toBe(f.opener)
})

it('retains continuation semantics and exposes a close button that does not write', () => {
  const f = setup(); f.fill(''); f.submit()
  expect(f.commit).toHaveBeenCalledExactlyOnceWith({ pageNumberFmt:'upperRoman', pageNumberStart:null })
  const g = setup()
  flushSync(() => g.host.querySelector<HTMLButtonElement>('[aria-label="关闭页码格式"]')!.click())
  expect(g.commit).not.toHaveBeenCalled()
  expect(g.host.querySelector('[role=dialog]')).toBeNull()
})

it('keeps the entered draft and explains a rejected commit inside the dialog', () => {
  const commit = vi.fn(() => { throw new Error('当前节发生变化，请重新打开页码格式') })
  const f = setup(commit); f.fill('12'); f.submit()
  expect(f.host.querySelector('[role=dialog]')).not.toBeNull()
  expect(f.host.querySelector('input')?.value).toBe('12')
  expect(f.host.querySelector('[role=alert]')?.textContent).toContain('当前节发生变化')
})

it('keeps the draft and displays a controlled failure receipt without marking the number invalid', () => {
  const f = setup(vi.fn(() => ({ error: '此节已插入分节符，请先保存，再调整页面设置' })))
  f.fill('12'); f.submit()
  expect(f.host.querySelector('[role=dialog]')).not.toBeNull()
  expect(f.host.querySelector('input')?.value).toBe('12')
  expect(f.host.querySelector('input')?.getAttribute('aria-invalid')).toBeNull()
  expect(f.host.querySelector('[role=alert]')?.textContent).toContain('此节已插入分节符')
})

it.each(['input', 'cancel', 'outside'] as const)('does not steal %s focus when confirmation becomes unavailable', target => {
  const f = setup()
  const focused = target === 'outside' ? f.opener : f.host.querySelector<HTMLElement>(target === 'input' ? 'input' : '[data-source-action="page-number-cancel"]')!
  focused.focus(); f.lock('当前文档不可编辑或正在保存')
  expect(document.activeElement).toBe(focused)
  expect(f.host.querySelector<HTMLButtonElement>('[type=submit]')?.disabled).toBe(true)
  f.submit(); expect(f.commit).not.toHaveBeenCalled()
  expect(f.host.querySelector('[role=dialog]')).not.toBeNull()
})
