import { afterEach, expect, it, vi } from 'vitest'
import { createDocxViewCommands, docxFitZoom } from './docx-view'

const views: ReturnType<typeof createDocxViewCommands>[] = []
afterEach(() => { views.splice(0).forEach(view => view.dispose()); document.body.replaceChildren() })
function setup() {
  const root = document.createElement('div'), scroller = document.createElement('div'), page = document.createElement('div')
  root.append(scroller); scroller.append(page); document.body.append(root)
  page.textContent = '原始段落'
  Object.defineProperty(scroller, 'clientWidth', { configurable: true, value: 848 })
  Object.defineProperty(scroller, 'clientHeight', { configurable: true, value: 648 })
  const preview = vi.fn()
  const view = createDocxViewCommands({ root, scroller, page, pageSize: () => ({ width: 800, height: 1000 }), onPaginationPreview: preview })
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
