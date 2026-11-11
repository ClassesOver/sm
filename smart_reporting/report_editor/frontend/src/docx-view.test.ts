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
  expect(f.view.reason('Web 版式')).not.toBeNull()
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
