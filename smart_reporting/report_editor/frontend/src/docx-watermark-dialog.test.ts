import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { openDocxWatermarkDialog } from './docx-watermark-dialog'

const descriptors = Object.fromEntries(['showModal', 'close'].map(name => [name, Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, name)]))
beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) { this.open = true } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function (this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event('close')) } })
})
afterEach(() => {
  document.body.replaceChildren()
  for (const name of ['showModal', 'close']) {
    const descriptor = descriptors[name]
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor)
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name)
  }
})
function open(current = false, apply = vi.fn()) {
  const opener = document.body.appendChild(document.createElement('button')); opener.textContent = '水印'; opener.focus()
  const dialog = openDocxWatermarkDialog(document.body, current ? { text: '已有水印' } : null, apply)
  return { dialog, opener, apply }
}
it.each([false, true])('opens at the selected watermark mode and separates fixed chrome (%s)', current => {
  const { dialog } = open(current)
  expect(document.activeElement).toBe(dialog.querySelector('input[name=mode]:checked'))
  expect(dialog.querySelector('header h2')?.textContent).toBe('插入水印')
  expect(dialog.querySelector('.docx-watermark-body fieldset')).not.toBeNull()
  expect(dialog.querySelector('footer button[value=ok]')).not.toBeNull()
})
it.each(['title', 'cancel', 'escape'])('discards unsubmitted input and restores focus on %s', action => {
  const { dialog, opener, apply } = open(true)
  dialog.querySelector<HTMLInputElement>('input[name=text]')!.value = '未提交输入'
  if (action === 'escape') {
    const event = new Event('cancel', { cancelable: true }); dialog.dispatchEvent(event); expect(event.defaultPrevented).toBe(true)
  } else {
    const control = dialog.querySelector<HTMLButtonElement>(action === 'title' ? '[aria-label="关闭水印设置"]' : '[value=cancel]')
    expect(control).not.toBeNull(); control!.focus(); control!.click()
  }
  expect(dialog.isConnected).toBe(false); expect(document.activeElement).toBe(opener); expect(apply).not.toHaveBeenCalled()
})
it('keeps failed application visible with a named keyboard-readable error and permits retry', () => {
  const apply = vi.fn().mockImplementationOnce(() => { throw Error('来源已变化，请重新选择') })
  const { dialog, opener } = open(true, apply)
  dialog.querySelector<HTMLButtonElement>('[value=ok]')!.click()
  expect(dialog.open).toBe(true); expect(dialog.isConnected).toBe(true)
  const error = dialog.querySelector<HTMLElement>('[role=alert]')!
  expect(error.getAttribute('aria-label')).toBe('水印设置错误'); expect(error.tabIndex).toBe(0)
  expect(document.activeElement).toBe(error); expect(error.textContent).toContain('来源已变化')
  expect(dialog.querySelector<HTMLInputElement>('[name=text]')!.value).toBe('已有水印')
  dialog.querySelector<HTMLButtonElement>('[value=ok]')!.click()
  expect(apply).toHaveBeenCalledTimes(2); expect(dialog.isConnected).toBe(false); expect(document.activeElement).toBe(opener)
})
it('rejects empty transparency without applying and keeps the entered text', () => {
  const { dialog, apply } = open(true)
  dialog.querySelector<HTMLInputElement>('[name=transparency]')!.value = ''
  dialog.querySelector<HTMLButtonElement>('[value=ok]')!.click()
  expect(apply).not.toHaveBeenCalled(); expect(dialog.open).toBe(true)
  expect(dialog.querySelector('[role=alert]')!.textContent).toContain('透明度')
  expect(dialog.querySelector<HTMLInputElement>('[name=text]')!.value).toBe('已有水印')
})
