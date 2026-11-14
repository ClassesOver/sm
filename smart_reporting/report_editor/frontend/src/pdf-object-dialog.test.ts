import { afterEach, describe, expect, it, vi } from 'vitest'

import { showPdfObjectDialog } from './pdf-object-dialog'

afterEach(() => { document.body.replaceChildren() })

function fixture() {
  const opener = document.body.appendChild(document.createElement('button'))
  opener.focus()
  const dialog = document.body.appendChild(document.createElement('dialog'))
  dialog.setAttribute('aria-label', '编辑便签正文')
  const input = dialog.appendChild(document.createElement('textarea'))
  dialog.showModal = vi.fn(() => { dialog.open = true })
  dialog.close = vi.fn(() => {
    dialog.open = false
    dialog.dispatchEvent(new Event('close'))
  })
  showPdfObjectDialog(dialog, input)
  return { opener, dialog, input }
}

function escape(input: HTMLElement, isComposing = true) {
  const event = new KeyboardEvent('keydown', { key: 'Escape', isComposing, bubbles: true, cancelable: true })
  input.dispatchEvent(event)
  return event
}

describe('PDF 对象属性窗口的组合输入', () => {
  it('阻止组合输入 Escape 触发浏览器的原生取消', () => {
    const { dialog, input } = fixture()
    expect(escape(input).defaultPrevented).toBe(true)
    expect(dialog.open).toBe(true)
    expect(dialog.close).not.toHaveBeenCalled()
    expect(document.activeElement).toBe(input)
  })

  it.each([
    { key: 'Escape', keyCode: 27 },
    { key: 'Enter', keyCode: 13 },
    { key: 'Escape', keyCode: 229 },
    { key: 'Enter', keyCode: 229 },
  ])('不拦截非组合输入 $key（keyCode=$keyCode）', ({ key, keyCode }) => {
    const { input } = fixture()
    const event = new KeyboardEvent('keydown', { key, keyCode, bubbles: true, cancelable: true })
    input.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(false)
  })

  it.each(['close', 'title', 'cancel'])('通过 %s 关闭后移除组合输入监听并恢复焦点', method => {
    const { opener, dialog, input } = fixture()
    expect(escape(input).defaultPrevented).toBe(true)
    if (method === 'close') dialog.close()
    else if (method === 'title') dialog.querySelector<HTMLButtonElement>('[data-pdf-object-close]')!.click()
    else {
      const cancel = new Event('cancel', { cancelable: true })
      dialog.dispatchEvent(cancel)
      expect(cancel.defaultPrevented).toBe(true)
    }
    expect(dialog.close).toHaveBeenCalledTimes(1)
    expect(dialog.open).toBe(false)
    expect(document.activeElement).toBe(opener)
    expect(escape(input).defaultPrevented).toBe(false)
  })
})
