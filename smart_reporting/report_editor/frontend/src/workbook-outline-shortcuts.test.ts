import { afterEach, expect, it, vi } from 'vitest'
import { installOutlineShortcuts } from './workbook-outline-shortcuts'

const handles: { dispose(): void }[] = []
afterEach(() => { handles.splice(0).forEach(handle => handle.dispose()); document.body.replaceChildren() })
function setup() {
  document.body.innerHTML = '<main><div id="workbook-grid"><canvas tabindex="0"></canvas><div contenteditable="true"></div><div data-u-comp="formula-bar"><div contenteditable="true"></div></div><input /></div><textarea></textarea></main>'
  let editable = true, cellEditing = false
  const command = vi.fn()
  handles.push(installOutlineShortcuts(document.querySelector('main')!, () => editable, () => cellEditing, command))
  const key = (target: Element, code = 'ArrowRight', rest: KeyboardEventInit = {}) => {
    const event = new KeyboardEvent('keydown', { code, key: code, altKey: true, shiftKey: true, bubbles: true, cancelable: true, ...rest })
    target.dispatchEvent(event)
    return event
  }
  return { command, key, grid: document.querySelector('canvas')!, state: (enabled: boolean, editing = false) => { editable = enabled; cellEditing = editing } }
}
it('dispatches exact outline chords from canvas and the native hidden focus host', () => {
  const c = setup()
  expect(c.key(c.grid).defaultPrevented).toBe(true)
  c.key(document.querySelector('#workbook-grid > [contenteditable]')!, 'ArrowLeft')
  expect(c.command.mock.calls).toEqual([['outline-group:auto'], ['outline-ungroup:auto']])
})
it('preserves text editing, chrome, modal and unavailable states', () => {
  const c = setup()
  for (const target of document.querySelectorAll('input, textarea, [data-u-comp="formula-bar"] [contenteditable]')) expect(c.key(target).defaultPrevented).toBe(false)
  c.state(false); c.key(c.grid)
  c.state(true, true); c.key(c.grid)
  c.state(true); const modal = document.createElement('div'); modal.setAttribute('role', 'dialog'); document.body.append(modal); c.key(c.grid)
  expect(c.command).not.toHaveBeenCalled()
})
it('skips modified, already consumed and composing keys and removes the listener', () => {
  const c = setup()
  for (const rest of [{ ctrlKey: true }, { metaKey: true }, { altKey: false }, { shiftKey: false }, { isComposing: true }]) c.key(c.grid, 'ArrowRight', rest)
  const consumed = new KeyboardEvent('keydown', { code: 'ArrowRight', altKey: true, shiftKey: true, bubbles: true, cancelable: true }); consumed.preventDefault(); c.grid.dispatchEvent(consumed)
  handles[0]!.dispose(); c.key(c.grid)
  expect(c.command).not.toHaveBeenCalled()
})
