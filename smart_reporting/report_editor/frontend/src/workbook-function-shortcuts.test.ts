import { afterEach, expect, it, vi } from 'vitest'
import { installFunctionShortcuts } from './workbook-function-shortcuts'

let dispose: (() => void) | undefined
afterEach(() => { dispose?.(); document.body.replaceChildren() })
const press = (target: Element, init: KeyboardEventInit = {}) => {
  const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, code: 'F3', shiftKey: true, ...init })
  target.dispatchEvent(event); return event
}
it('dispatches source Shift+F3 from grid focus and releases its handler', () => {
  document.body.innerHTML = '<main><div id="workbook-grid"><div contenteditable="true"></div></div></main>'
  const command = vi.fn(), host = document.querySelector('main')!
  const handle = installFunctionShortcuts(host, () => true, command); dispose = handle.dispose
  expect(press(host.querySelector('[contenteditable]')!).defaultPrevented).toBe(true)
  expect(command).toHaveBeenCalledOnce()
  for (const init of [{ ctrlKey: true }, { metaKey: true }, { altKey: true }, { shiftKey: false }, { isComposing: true }]) expect(press(host, init).defaultPrevented).toBe(false)
  expect(command).toHaveBeenCalledOnce()
  handle.dispose(); press(host); expect(command).toHaveBeenCalledOnce()
})
it('legacy输入法按键不启动函数窗口，普通快捷键仍有效', () => {
  document.body.innerHTML = '<main><div id="workbook-grid"><canvas tabindex="0"></canvas></div></main>'
  const command = vi.fn(), host = document.querySelector('main')!, grid = host.querySelector('canvas')!
  dispose = installFunctionShortcuts(host, () => true, command).dispose
  expect(press(grid, { keyCode: 229 }).defaultPrevented).toBe(false); expect(command).not.toHaveBeenCalled()
  press(grid); expect(command).toHaveBeenCalledOnce()
})
it('preserves native fields, chrome, modals, handled events and read-only state', () => {
  document.body.innerHTML = '<main><input><textarea></textarea><select></select><div contenteditable="true"></div><div data-u-comp="formula-bar"><span></span></div></main>'
  const host = document.querySelector('main')!, command = vi.fn()
  let editable = true
  dispose = installFunctionShortcuts(host, () => editable, command).dispose
  for (const node of host.children) expect(press(node).defaultPrevented).toBe(false)
  const dialog = document.createElement('div'); dialog.setAttribute('role', 'dialog'); host.append(dialog)
  expect(press(host).defaultPrevented).toBe(false)
  dialog.hidden = true
  const handled = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, code: 'F3', shiftKey: true }); handled.preventDefault(); host.dispatchEvent(handled)
  editable = false; expect(press(host).defaultPrevented).toBe(false)
  expect(command).not.toHaveBeenCalled()
})
