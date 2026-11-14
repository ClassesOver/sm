import { capturePdfReading, pdfReadingRows } from './pdf-reading-state'
import { afterEach, expect, it, vi } from 'vitest'
import { bindPdfPageNavigation } from './pdf-page-navigation'
const controllers: AbortController[] = []
afterEach(() => { controllers.splice(0).forEach(controller => controller.abort()); document.body.replaceChildren() })
function fixture() {
  const viewport = document.createElement('div'); viewport.tabIndex = 0; document.body.append(viewport)
  const abort = new AbortController(); controllers.push(abort)
  let active = 'b', available = true, pages = [{ pageId: 'a' }, { pageId: 'b' }, { pageId: 'c' }]
  const navigate = vi.fn((id: string) => { active = id })
  bindPdfPageNavigation(viewport, { signal: abort.signal, available: () => available, pages: () => pages, readingPage: () => active, navigate })
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
  expect(f.navigate).toHaveBeenCalledTimes(4)
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
  bindPdfPageNavigation(f.viewport, { signal: replacement.signal, available: () => true, pages: () => [{ pageId: 'new' }], readingPage: () => 'new', navigate })
  f.key('Home'); expect(navigate).toHaveBeenCalledExactlyOnceWith('new'); expect(f.navigate).toHaveBeenCalledTimes(1)
})
it('leaves navigation untouched when the current page was removed', () => {
  const f = fixture(); f.setPages([{ pageId: 'a' }]); expect(f.key('PageDown').defaultPrevented).toBe(false); expect(f.navigate).not.toHaveBeenCalled()
})

it('uses the live reading anchor after wheel scrolling, not an old selected page', () => {
  const viewport = document.createElement('div'); viewport.tabIndex = 0; document.body.append(viewport)
  const ids = ['reordered', 'blank', 'fifth', 'last']
  viewport.getBoundingClientRect = () => new DOMRect(0, 0, 600, 500)
  ids.forEach((id, index) => {
    const page = document.createElement('section'); page.className = 'pdf-page'; page.dataset.pageId = id; viewport.append(page)
    page.getBoundingClientRect = () => new DOMRect(0, index * 1000 - viewport.scrollTop, 600, 1000)
  })
  const abort = new AbortController(); controllers.push(abort)
  const navigate = vi.fn()
  bindPdfPageNavigation(viewport, { signal: abort.signal, available: () => true,
    pages: () => ids.map(pageId => ({ pageId })),
    readingPage: () => { const reading = capturePdfReading(viewport, ids, 1, null); return reading ? ids[reading.page - 1]! : '' }, navigate })
  viewport.focus(); viewport.scrollTop = 2500
  viewport.dispatchEvent(new KeyboardEvent('keydown', { key: 'PageDown', cancelable: true }))
  expect(navigate).toHaveBeenLastCalledWith('last')
  viewport.scrollTop = 3500; navigate.mockClear()
  const boundary = new KeyboardEvent('keydown', { key: 'PageDown', cancelable: true }); viewport.dispatchEvent(boundary)
  expect(boundary.defaultPrevented).toBe(true); expect(navigate).not.toHaveBeenCalled(); expect(viewport.scrollTop).toBe(3500)
  viewport.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', cancelable: true })); expect(navigate).toHaveBeenLastCalledWith('reordered')
})

it('moves by a reading row in two-page spread mode, without repeatedly targeting its right page', () => {
  const f = fixture(), abort = new AbortController(); controllers.push(abort); f.abort.abort()
  let reading = 'a'; const navigate = vi.fn((id: string) => { reading = id })
  bindPdfPageNavigation(f.viewport, { signal: abort.signal, available: () => true,
    pages: () => ['a', 'b', 'c', 'd'].map(pageId => ({ pageId })), readingPage: () => reading, readingRows: () => [{ pageId: 'a' }, { pageId: 'c' }], navigate })
  f.key('PageDown'); expect(reading).toBe('c'); expect(navigate).toHaveBeenCalledTimes(1)
  f.key('PageDown'); expect(navigate).toHaveBeenCalledTimes(1)
  f.key('PageUp'); expect(reading).toBe('a'); expect(navigate).toHaveBeenCalledTimes(2)
})
it.each([{ ids: ['a', 'b', 'c', 'd'], columns: 2 }, { ids: ['a', 'b', 'c'], columns: 2 }, { ids: ['a', 'b', 'c'], columns: 1 }])('advances between actual DOM reading rows %j', ({ ids, columns }) => {
  const viewport = document.createElement('div'); document.body.append(viewport)
  viewport.getBoundingClientRect = () => new DOMRect(0, 0, 600, 500)
  ids.forEach((id, index) => {
    const page = document.createElement('section'); page.className = 'pdf-page'; page.dataset.pageId = id; viewport.append(page)
    page.getBoundingClientRect = () => new DOMRect(index % columns * 300, Math.floor(index / columns) * 1000 - viewport.scrollTop, 300, 1000)
  })
  const abort = new AbortController(); controllers.push(abort)
  const navigate = vi.fn((id: string) => { viewport.scrollTop = Math.floor(ids.indexOf(id) / columns) * 1000 })
  bindPdfPageNavigation(viewport, { signal: abort.signal, available: () => true, readingRows: () => pdfReadingRows(viewport, ids),
    pages: () => ids.map(pageId => ({ pageId })),
    readingPage: () => { const reading = capturePdfReading(viewport, ids, 1, null); return reading ? ids[reading.page - 1]! : '' }, navigate })
  const key = (key: string) => viewport.dispatchEvent(new KeyboardEvent('keydown', { key, cancelable: true }))
  key('PageDown'); expect(navigate).toHaveBeenLastCalledWith(ids[columns]); expect(viewport.scrollTop).toBe(1000)
  const lastRow = Math.floor((ids.length - 1) / columns) * 1000
  viewport.scrollTop = lastRow + 500; window.dispatchEvent(new Event('wheel')); navigate.mockClear(); key('PageDown'); expect(navigate).not.toHaveBeenCalled(); expect(viewport.scrollTop).toBe(lastRow + 500)
  key('Home'); expect(navigate).toHaveBeenLastCalledWith('a'); expect(viewport.scrollTop).toBe(0)
  key('PageDown'); key('PageUp'); expect(navigate).toHaveBeenLastCalledWith('a'); expect(viewport.scrollTop).toBe(0)
})
it('advances rapid repeated keys by interruptible intent while DOM scroll is still behind', () => {
  const viewport = document.createElement('div'); document.body.append(viewport)
  const abort = new AbortController(); controllers.push(abort)
  let reading = '1', layout = 'original'
  const navigate = vi.fn(), binding = bindPdfPageNavigation(viewport, { signal: abort.signal, available: () => true,
    pages: () => ['1','2','3','4','5'].map(pageId => ({ pageId })), readingPage: () => reading, navigationKey: () => layout, navigate })
  const key = (key: string) => viewport.dispatchEvent(new KeyboardEvent('keydown', { key, cancelable: true }))
  key('PageDown'); key('PageDown'); key('PageDown'); expect(navigate.mock.calls.map(call => call[0])).toEqual(['2','3','4'])
  reading = '2'; window.dispatchEvent(new Event('wheel')); key('PageDown'); expect(navigate).toHaveBeenLastCalledWith('3')
  reading = '1'; layout = 'zoom'; key('PageDown'); expect(navigate).toHaveBeenLastCalledWith('2')
  binding.recordNavigation('5'); key('PageUp'); expect(navigate).toHaveBeenLastCalledWith('4')
  key('PageUp'); expect(navigate).toHaveBeenLastCalledWith('3')
  binding.invalidate(); key('PageDown'); expect(navigate).toHaveBeenLastCalledWith('2')
})
it('maps an explicit right-page End target back to its reading row before paging up', () => {
  const viewport = document.createElement('div'); document.body.append(viewport)
  const abort = new AbortController(); controllers.push(abort); const navigate = vi.fn()
  bindPdfPageNavigation(viewport, { signal: abort.signal, available: () => true,
    pages: () => ['a','b','c','d'].map(pageId => ({ pageId })),
    readingRows: () => [{pageId:'a',pageIds:['a','b']},{pageId:'c',pageIds:['c','d']}], readingPage: () => 'a', navigate })
  for (const key of ['End','PageUp']) viewport.dispatchEvent(new KeyboardEvent('keydown', { key, cancelable: true }))
  expect(navigate.mock.calls.map(call => call[0])).toEqual(['d','a'])
})
it.each(['wheel','pointerdown','touchstart','blur','focusout'])('invalidates navigation intent on %s before reading the DOM again', type => {
  const viewport = document.createElement('div'); document.body.append(viewport)
  const abort = new AbortController(); controllers.push(abort); const navigate = vi.fn()
  const binding = bindPdfPageNavigation(viewport, { signal: abort.signal, available: () => true,
    pages: () => ['1','2','3'].map(pageId => ({ pageId })), readingPage: () => '1', navigate })
  binding.recordNavigation('3')
  ;(type === 'focusout' ? viewport : window).dispatchEvent(new Event(type))
  viewport.dispatchEvent(new KeyboardEvent('keydown', { key: 'PageDown', cancelable: true }))
  expect(navigate).toHaveBeenLastCalledWith('2')
})
it.each([{key:'ArrowDown'}, {key:' '}, {key:' ',shiftKey:true}, {key:'End',ctrlKey:true}, {key:'Home',metaKey:true}])('lets native keyboard scrolling %j invalidate intent without consuming it', init => {
  const viewport = document.createElement('div'); document.body.append(viewport)
  const abort = new AbortController(); controllers.push(abort); let reading = '1'; const navigate = vi.fn()
  bindPdfPageNavigation(viewport, { signal: abort.signal, available: () => true,
    pages: () => ['1','2','3','4'].map(pageId => ({ pageId })), readingPage: () => reading, navigate })
  viewport.dispatchEvent(new KeyboardEvent('keydown', {key:'PageDown',cancelable:true}))
  const native = new KeyboardEvent('keydown', {...init,cancelable:true}); viewport.dispatchEvent(native); expect(native.defaultPrevented).toBe(false)
  reading = '3'; viewport.dispatchEvent(new KeyboardEvent('keydown', {key:'PageDown',cancelable:true}))
  expect(navigate.mock.calls.map(call => call[0])).toEqual(['2','4'])
})
