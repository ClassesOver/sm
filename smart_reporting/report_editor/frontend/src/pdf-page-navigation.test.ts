import { afterEach, expect, it, vi } from 'vitest'
import { bindPdfPageNavigation } from './pdf-page-navigation'
const controllers: AbortController[] = []
afterEach(() => { controllers.splice(0).forEach(controller => controller.abort()); document.body.replaceChildren() })
function fixture() {
  const viewport = document.createElement('div'); viewport.tabIndex = 0; document.body.append(viewport)
  const abort = new AbortController(); controllers.push(abort)
  let active = 'b', available = true, pages = [{ pageId: 'a' }, { pageId: 'b' }, { pageId: 'c' }]
  const navigate = vi.fn((id: string) => { active = id })
  bindPdfPageNavigation(viewport, { signal: abort.signal, available: () => available, pages: () => pages, activePage: () => active, navigate })
  const key = (key: string, init: KeyboardEventInit = {}, target: HTMLElement = viewport) => {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }); target.dispatchEvent(event); return event
  }
  return { viewport, abort, navigate, key, setAvailable(value: boolean) { available = value }, setPages(value: typeof pages) { pages = value }, active: () => active }
}
it('navigates current visible page order without wrapping, preserving focus', () => {
  const f = fixture(); f.viewport.focus()
  for (const [key, expected] of [['PageDown', 'c'], ['PageDown', 'c'], ['Home', 'a'], ['PageUp', 'a'], ['End', 'c'], ['PageUp', 'b']]) {
    expect(f.key(key!).defaultPrevented).toBe(true); expect(f.active()).toBe(expected); expect(document.activeElement).toBe(f.viewport)
  }
  f.setPages([{ pageId: 'c' }, { pageId: 'b' }, { pageId: 'a' }]); f.key('PageDown'); expect(f.active()).toBe('a')
  f.setPages([]); expect(f.key('Home').defaultPrevented).toBe(false)
})
it.each(['input', 'textarea', 'select', 'button', 'a', 'div'])('does not intercept descendants including %s', tag => {
  const f = fixture(), child = document.createElement(tag); child.setAttribute('contenteditable', 'true'); f.viewport.append(child)
  expect(f.key('End', {}, child).defaultPrevented).toBe(false); expect(f.navigate).not.toHaveBeenCalled()
})
it.each([{ isComposing: true }, { keyCode: 229 }, { ctrlKey: true }, { metaKey: true }, { altKey: true }, { shiftKey: true }])('ignores composition and modifiers %j', init => {
  const f = fixture(); expect(f.key('PageDown', init).defaultPrevented).toBe(false); expect(f.navigate).not.toHaveBeenCalled()
})
it('respects already consumed keys, unavailable state and open modals', () => {
  const f = fixture(); f.viewport.addEventListener('keydown', event => event.preventDefault(), { capture: true, once: true }); f.key('End')
  f.setAvailable(false); f.key('End'); f.setAvailable(true)
  const modal = document.createElement('dialog'); modal.open = true; document.body.append(modal); f.key('End'); modal.remove()
  expect(f.navigate).not.toHaveBeenCalled(); f.key('End'); expect(f.active()).toBe('c')
})
it('does not navigate during a pointer gesture; releases on cancel and stops after disposal', () => {
  const f = fixture(); f.viewport.dispatchEvent(new Event('pointerdown')); f.key('End'); expect(f.navigate).not.toHaveBeenCalled()
  window.dispatchEvent(new Event('pointercancel')); f.key('End'); expect(f.active()).toBe('c')
  f.abort.abort(); f.key('Home'); expect(f.active()).toBe('c')
})
it('never intercepts keys on the surrounding document or unrelated controls', () => {
  const f = fixture(); f.key('Home', {}, document.body); f.key('ArrowDown'); expect(f.navigate).not.toHaveBeenCalled()
})
it('allows hidden custom modals and a clean replacement binding after abort', () => {
  const f = fixture(), modal = document.createElement('div'); modal.setAttribute('aria-modal', 'true'); modal.hidden = true; document.body.append(modal)
  f.key('End'); expect(f.active()).toBe('c'); f.abort.abort()
  const replacement = new AbortController(); controllers.push(replacement); const navigate = vi.fn()
  bindPdfPageNavigation(f.viewport, { signal: replacement.signal, available: () => true, pages: () => [{ pageId: 'new' }], activePage: () => 'new', navigate })
  f.key('Home'); expect(navigate).toHaveBeenCalledExactlyOnceWith('new'); expect(f.navigate).toHaveBeenCalledTimes(1)
})
it('leaves navigation untouched when the current page was removed', () => {
  const f = fixture(); f.setPages([{ pageId: 'a' }]); expect(f.key('PageDown').defaultPrevented).toBe(false); expect(f.navigate).not.toHaveBeenCalled()
})
