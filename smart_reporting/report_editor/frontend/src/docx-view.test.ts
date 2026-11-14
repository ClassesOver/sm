import { afterEach, expect, it, vi } from 'vitest'
import { createDocxViewCommands, docxFitZoom } from './docx-view'

const views: ReturnType<typeof createDocxViewCommands>[] = []
afterEach(() => { views.splice(0).forEach(view => view.dispose()); document.body.replaceChildren() })
function setup(extra: Record<string, unknown> = {}) {
  const root = document.createElement('div'), scroller = document.createElement('div'), page = document.createElement('div')
  root.append(scroller); scroller.append(page); document.body.append(root)
  page.textContent = '原始段落'
  Object.defineProperty(scroller, 'clientWidth', { configurable: true, value: 848 })
  Object.defineProperty(scroller, 'clientHeight', { configurable: true, value: 648 })
  const preview = vi.fn()
  const view = createDocxViewCommands({ root, scroller, page, pageSize: () => ({ width: 800, height: 1000 }), onPaginationPreview: preview, ...extra })
  views.push(view)
  return { root, scroller, page, view, preview }
}
it('fits the full page in both axes and rejects unavailable viewport dimensions', () => {
  expect(docxFitZoom('width', { width: 848, height: 648 }, { width: 800, height: 1000 })).toBe(100)
  expect(docxFitZoom('page', { width: 848, height: 648 }, { width: 800, height: 1000 })).toBe(60)
  expect(docxFitZoom('width', { width: 0, height: 648 }, { width: 800, height: 1000 })).toBeUndefined()
  expect(docxFitZoom('width', { width: Infinity, height: 648 }, { width: 800, height: 1000 })).toBeUndefined()
})
it('uses source zoom limits and keeps original document content and physical dimensions unchanged', () => {
  const f = setup(); const content = f.page.innerHTML
  for (let i = 0; i < 60; i++) f.view.run('放大')
  expect(f.view.zoom).toBe(500)
  for (let i = 0; i < 60; i++) f.view.run('缩小')
  expect(f.view.zoom).toBe(10)
  f.view.run('100%'); expect(f.view.zoom).toBe(100)
  f.view.run('整页'); expect(f.view.zoom).toBe(60)
  f.view.run('页宽'); expect(f.view.zoom).toBe(100)
  expect(f.page.innerHTML).toBe(content)
  expect(f.page.style.width).toBe('')
  expect(f.view.reason('Web 版式')).toBeNull()
  f.view.run('分页预览'); expect(f.preview).toHaveBeenCalledOnce()
})
it('keeps fit responsive until the user chooses a manual zoom and restores the original display on disposal', () => {
  const f = setup(); f.view.run('页宽')
  Object.defineProperty(f.scroller, 'clientWidth', { value: 448 })
  f.view.refresh(); expect(f.view.zoom).toBe(50)
  f.view.run('放大'); expect(f.view.zoom).toBe(60)
  Object.defineProperty(f.scroller, 'clientWidth', { value: 848 })
  f.view.refresh(); expect(f.view.zoom).toBe(60)
  f.view.dispose(); expect(f.page.style.getPropertyValue('zoom')).toBe('')
  expect(f.root.hasAttribute('data-docx-zoom')).toBe(false)
})
it('validates the actual zoom dialog and cancels without altering the current view', () => {
  const f = setup(); f.view.run('缩放')
  const input = f.root.querySelector<HTMLInputElement>('input')!, form = f.root.querySelector('form')!
  input.value = '501'; form.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(f.view.zoom).toBe(100); expect(f.root.querySelector('[role=alert]')!.textContent).toContain('10–500')
  input.value = ''; form.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(f.view.zoom).toBe(100)
  input.value = '125'; form.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(f.view.zoom).toBe(125)
  f.view.run('缩放'); input.value = '250'; f.root.querySelector<HTMLButtonElement>('[data-action=cancel]')!.click()
  expect(f.view.zoom).toBe(125)
})

it('routes heading navigation and outline modes without changing zoom or paper content', () => {
  let visible = false, mode = 'page'
  const navigation = { toggle: vi.fn(() => { visible = !visible }), get visible() { return visible } }
  const outline = { run: vi.fn((label: string) => { mode = label === '大纲' ? 'outline' : 'page' }), reason: () => null, get mode() { return mode } }
  const f = setup({ navigation, outline }), original = f.page.innerHTML
  expect(f.view.reason('导航窗格')).toBeNull()
  expect(f.view.reason('大纲')).toBeNull()
  f.view.run('导航窗格'); expect(navigation.toggle).toHaveBeenCalledOnce()
  expect(f.view.active?.('导航窗格')).toBe(true)
  f.view.run('大纲'); expect(outline.run).toHaveBeenCalledWith('大纲')
  expect(f.view.active?.('大纲')).toBe(true)
  f.view.run('页面视图'); expect(f.view.active?.('页面视图')).toBe(true)
  expect(f.view.zoom).toBe(100); expect(f.page.innerHTML).toBe(original)
})

it('routes gridlines as an independent display toggle without changing document or zoom', () => {
  let visible = false
  const gridlines = { toggle: vi.fn(() => { visible = !visible }), get visible() { return visible } }
  const f = setup({ gridlines }), original = f.page.innerHTML
  expect(f.view.reason('网格线')).toBeNull()
  expect(f.view.active?.('网格线')).toBe(false)
  f.view.run('网格线'); expect(gridlines.toggle).toHaveBeenCalledOnce()
  expect(f.view.active?.('网格线')).toBe(true)
  f.view.run('网格线'); expect(f.view.active?.('网格线')).toBe(false)
  expect(f.view.zoom).toBe(100); expect(f.page.innerHTML).toBe(original)
  f.view.dispose(); expect(f.view.reason('网格线')).not.toBeNull()
})

it('routes ruler independently from zoom, gridlines and document content', () => {
  let visible = false
  const ruler = { toggle: vi.fn(() => { visible = !visible }), get visible() { return visible } }
  const f = setup({ ruler }), original = f.page.innerHTML
  expect(f.view.reason('标尺')).toBeNull(); expect(f.view.active?.('标尺')).toBe(false)
  f.view.run('标尺'); expect(ruler.toggle).toHaveBeenCalledOnce(); expect(f.view.active?.('标尺')).toBe(true)
  f.view.run('放大'); expect(f.view.zoom).toBe(110); expect(f.view.active?.('标尺')).toBe(true)
  f.view.run('标尺'); expect(f.view.active?.('标尺')).toBe(false)
  expect(f.page.innerHTML).toBe(original)
  f.view.dispose(); expect(f.view.reason('标尺')).not.toBeNull()
})

it('notifies geometry consumers only when the zoom actually changes', () => {
  const onZoomChange = vi.fn(), f = setup({ onZoomChange })
  expect(onZoomChange).toHaveBeenCalledTimes(1)
  f.view.run('100%'); f.view.refresh()
  expect(onZoomChange).toHaveBeenCalledTimes(1)
  f.view.run('放大')
  expect(onZoomChange).toHaveBeenCalledTimes(2)
  expect(f.root.dataset.docxZoom).toBe('110')
})

it('zooms modifier wheel gestures only inside the canvas, keeps the cursor anchor and cleans up the listener', () => {
  const f = setup(); f.scroller.scrollTop = 200; f.scroller.scrollLeft = 100
  vi.spyOn(f.page, 'getBoundingClientRect').mockImplementation(() => ({
    x: -f.scroller.scrollLeft, y: -f.scroller.scrollTop,
    left: -f.scroller.scrollLeft, top: -f.scroller.scrollTop,
    width: 800 * f.view.zoom / 100, height: 1000 * f.view.zoom / 100,
    right: 800 * f.view.zoom / 100 - f.scroller.scrollLeft,
    bottom: 1000 * f.view.zoom / 100 - f.scroller.scrollTop, toJSON() {},
  }))
  const outside = new WheelEvent('wheel', { bubbles: true, cancelable: true, ctrlKey: true, deltaY: -120 })
  document.body.dispatchEvent(outside); expect(outside.defaultPrevented).toBe(false)
  const ordinary = new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: 120 })
  f.page.dispatchEvent(ordinary); expect(ordinary.defaultPrevented).toBe(false)
  const notch = new WheelEvent('wheel', { bubbles: true, cancelable: true, metaKey: true, deltaY: -3, deltaMode: 1, clientX: 50, clientY: 60 })
  f.page.dispatchEvent(notch)
  expect(notch.defaultPrevented).toBe(true); expect(f.view.zoom).toBe(110)
  expect(f.scroller.scrollTop).toBeCloseTo(226); expect(f.scroller.scrollLeft).toBeCloseTo(115)
  const pinch = new WheelEvent('wheel', { bubbles: true, cancelable: true, ctrlKey: true, deltaY: -0.5 })
  f.page.dispatchEvent(pinch); expect(f.view.zoom).toBeCloseTo(110.3)
  f.view.dispose()
  const removed = new WheelEvent('wheel', { bubbles: true, cancelable: true, ctrlKey: true, deltaY: 120 })
  f.page.dispatchEvent(removed); expect(removed.defaultPrevented).toBe(false)
})

it('provides web layout and returns to page or outline without modifying document content', () => {
  let mode = 'page'
  const outline = { run: (label: string) => { mode = label === '大纲' ? 'outline' : 'page' }, reason: () => null, get mode() { return mode } }
  const f = setup({ outline }), original = f.page.innerHTML
  expect(f.view.reason('Web 版式')).toBeNull()
  f.view.run('Web 版式'); expect(f.view.active?.('Web 版式')).toBe(true)
  expect(f.root.classList.contains('docx-view-web')).toBe(true)
  expect(f.view.active?.('页面视图')).toBe(false)
  f.view.run('大纲'); expect(f.view.active?.('大纲')).toBe(true)
  expect(f.root.classList.contains('docx-view-web')).toBe(false)
  f.view.run('Web 版式'); f.view.run('页面视图')
  expect(f.view.active?.('页面视图')).toBe(true); expect(f.page.innerHTML).toBe(original)
})

it('enters readonly immersive reading at 100 percent and restores zoom and fit on Escape or disposal', () => {
  let readOnly = false
  const reading = { setActive: (value: boolean) => { readOnly = value } }
  const f = setup({ reading }); f.view.run('整页'); expect(f.view.zoom).toBe(60)
  expect(f.view.reason('阅读视图')).toBeNull(); f.view.run('阅读视图')
  expect(readOnly).toBe(true); expect(f.view.zoom).toBe(100)
  expect(f.root.querySelector<HTMLButtonElement>('.docx-read-exit')?.hidden).toBe(false)
  f.view.run('放大'); expect(f.view.zoom).toBe(110)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  expect(readOnly).toBe(false); expect(f.view.zoom).toBe(60)
  Object.defineProperty(f.scroller, 'clientHeight', { value: 1048 }); f.view.refresh(); expect(f.view.zoom).toBe(100)
  f.view.run('阅读视图'); f.view.dispose(); expect(readOnly).toBe(false)
})

it('persists the explicit dark page choice using the source preference and respects authored page colors', () => {
  localStorage.removeItem('aidocs.darkPage')
  let pageColor: string | null = null
  const f = setup({ themeDark: () => true, pageColor: () => pageColor })
  expect(f.root.classList.contains('page-dark')).toBe(true)
  expect(f.view.active?.('深色模式')).toBe(true)
  f.view.run('深色模式'); expect(localStorage.getItem('aidocs.darkPage')).toBe('0')
  expect(f.root.classList.contains('page-dark')).toBe(false)
  f.view.run('深色模式'); expect(localStorage.getItem('aidocs.darkPage')).toBe('1')
  pageColor = '#ffeeaa'; f.view.refresh(); expect(f.root.classList.contains('page-dark')).toBe(false)
  expect(f.view.active?.('深色模式')).toBe(true)
  f.view.dispose(); expect(f.root.classList.contains('page-dark')).toBe(false)
  localStorage.removeItem('aidocs.darkPage')
})


it('requires a readonly integration for reading and restores inherited display classes on disposal', () => {
  const f = setup()
  expect(f.view.reason('阅读视图')).not.toBeNull()
  f.view.run('阅读视图'); expect(f.root.querySelector<HTMLButtonElement>('.docx-read-exit')!.hidden).toBe(true)
  f.view.run('Web 版式'); f.view.run('深色模式')
  expect(f.root.classList.contains('docx-view-web')).toBe(true)
  f.view.dispose(); expect(f.root.classList.contains('docx-view-web')).toBe(false)
  expect(f.scroller.classList.contains('page-dark')).toBe(false)
  localStorage.removeItem('aidocs.darkPage')
})

it('classifies a dense Cmd wheel stream as a single notch and rounds buttons after continuous pinch', () => {
  const f = setup()
  for (let i = 0; i < 8; i++) {
    const event = new WheelEvent('wheel', { bubbles: true, cancelable: true, metaKey: true, deltaY: -20 })
    Object.defineProperty(event, 'timeStamp', { value: i * 10 })
    f.page.dispatchEvent(event)
  }
  expect(f.view.zoom).toBe(110)
  f.page.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, ctrlKey: true, deltaY: -0.5 }))
  expect(f.view.zoom).toBeCloseTo(110.3)
  f.view.run('放大'); expect(f.view.zoom).toBe(120)
})

it('keeps reading active when a context menu consumes Escape before it reaches the window', () => {
  const f = setup({ reading: { setActive: () => {} } })
  f.view.run('放大'); f.view.run('阅读视图')
  const menu = document.createElement('div'); menu.setAttribute('role', 'menu'); f.root.append(menu)
  menu.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); menu.remove() } })
  const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
  menu.dispatchEvent(escape)
  expect(escape.defaultPrevented).toBe(true)
  expect(menu.isConnected).toBe(false)
  expect(f.view.reading).toBe(true); expect(f.view.zoom).toBe(100)
  f.page.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  expect(f.view.reading).toBe(false); expect(f.view.zoom).toBe(110)
})

it.each([{ isComposing: true }, { keyCode: 229 }])('keeps reading active during IME Escape %j', flags => {
  const f = setup({ reading: { setActive: () => {} } }); f.view.run('阅读视图')
  f.page.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, ...flags }))
  expect(f.view.reading).toBe(true)
  f.page.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  expect(f.view.reading).toBe(false)
})

it('lets a modal own Escape without exiting the underlying reading view', () => {
  const f = setup({ reading: { setActive: () => {} } }); f.view.run('阅读视图')
  const dialog = document.createElement('div'), input = document.createElement('input')
  dialog.setAttribute('role', 'dialog'); dialog.append(input); document.body.append(dialog)
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
  expect(f.view.reading).toBe(true)
  dialog.remove()
  f.page.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  expect(f.view.reading).toBe(false)
})
