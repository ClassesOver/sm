import React from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createSlidesEditorView } from './slides-main'
import { createEditorShell } from './shell'
import { NativeDraft } from './native-draft'

vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
vi.mock('./vendor/genoffice/renderer/SlideThumb', () => ({ SlideThumb: ({ slide }: { slide: { nodes: { text?: string }[] } }) => <figure data-source-thumbnail>{slide.nodes.map(node => node.text).join('')}</figure> }))
const views: ReturnType<typeof createSlidesEditorView>[] = []
beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
})
afterEach(() => { views.splice(0).forEach(view => view.dispose()); document.body.replaceChildren(); vi.unstubAllGlobals() })
async function fixture() {
  const source = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [0, 1, 2, 3].map(slideIndex => ({ slideIndex, notesText: '', notesEditable: true, elements: [{ id: 'title', name: '标题', type: 'text', text: `来源${slideIndex}`, editable: true, geometry: { x: 10, y: 10, width: 300, height: 50 } }], animations: [] })) }
  const tree = { slides: source.slides.map(slide => ({ slideIndex: slide.slideIndex, widthPx: 960, heightPx: 540, nodes: [{ id: 'title', sourceId: 'title', text: `真实内容${slide.slideIndex}`, type: 'text', box: { x: 10, y: 10, w: 300, h: 50 } }] })) }
  const shell = createEditorShell(document.body.appendChild(document.createElement('main')), 'full', 'pptx')
  const store = { getItem: () => null, setItem() {}, removeItem() {} }
  const draft = new NativeDraft({ documentId: 'view-modes', revision: 1, sourceSha256: source.sha256, scope: { database: 'fixture', companyId: 'c', userId: 'u', threadId: 't' } }, store)
  const request = vi.fn(async (path: string) => path === 'deck' ? source : path === 'render-tree' ? tree : { revision: 2, revisionRegistered: true, validation: { issues: [] } })
  const view = createSlidesEditorView(shell.editor, { native: true, draft, request: request as never, save: shell.save, download: shell.exportPptx })
  views.push(view); await view.ready
  const control = <T extends HTMLElement>(selector: string) => shell.editor.querySelector<T>(selector)!
  control<HTMLButtonElement>('[data-command=slideSorter]').click()
  await vi.waitFor(() => expect(control('.slides-sorter-view')?.querySelectorAll('[role=option]')).toHaveLength(4))
  const sorter = control('.slides-sorter-view')
  const card = (id: number) => sorter.querySelector<HTMLElement>(`[data-slide-index="${id}"]`)!
  const key = (key: string, extra = {}) => sorter.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...extra }))
  const selected = () => [...sorter.querySelectorAll<HTMLElement>('[aria-selected=true]')].map(el => Number(el.dataset.slideIndex))
  return { shell, view, control, draft, request, sorter, card, key, selected }
}

it('普通/浏览互切提供现有渲染树缩略图，保留当前页与草稿，不执行保存', async () => {
  const app = await fixture()
  expect(app.card(2).querySelector('[data-source-thumbnail]')!.textContent).toBe('真实内容2')
  expect(document.activeElement).toBe(app.sorter)
  app.card(2).click()
  await vi.waitFor(() => expect(app.selected()).toEqual([2]))
  app.card(2).dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))
  expect(app.sorter.hidden).toBe(true)
  expect(app.control('.slides-workspace').dataset.viewMode).toBe('normal')
  expect(app.control('[data-command=normalView]').getAttribute('aria-pressed')).toBe('true')
  expect(app.control('.slide-row[data-selected=true] .slide-open').getAttribute('data-slide-index')).toBe('2')
  app.control<HTMLButtonElement>('[data-command=slideSorter]').click()
  await vi.waitFor(() => expect(app.sorter.hidden).toBe(false))
  expect(app.draft.operations).toEqual([])
  expect(app.request.mock.calls.every(([path]) => path !== 'save')).toBe(true)
})

it('源范围/切换选择与键盘选页遵守焦点及IME边界', async () => {
  const app = await fixture()
  app.card(2).dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }))
  await vi.waitFor(() => expect(app.selected()).toEqual([0, 1, 2]))
  app.card(1).dispatchEvent(new MouseEvent('click', { bubbles: true, ctrlKey: true }))
  await vi.waitFor(() => expect(app.selected()).toEqual([0, 2]))
  app.key('End'); await vi.waitFor(() => expect(app.selected()).toEqual([3]))
  app.key('Home', { shiftKey: true }); await vi.waitFor(() => expect(app.selected()).toEqual([0, 1, 2, 3]))
  app.key('PageUp', { isComposing: true }); expect(app.selected()).toEqual([0, 1, 2, 3])
  app.key('PageUp'); await vi.waitFor(() => expect(app.selected()).toEqual([2]))
  const nested = document.createElement('input'); app.sorter.append(nested)
  nested.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }))
  expect(app.selected()).toEqual([2]); expect(app.draft.operations).toEqual([])
})

it('按最终落点移动所选整块，沿用页面身份并作为一次草稿历史撤销重做', async () => {
  const app = await fixture()
  app.card(1).dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }))
  await vi.waitFor(() => expect(app.selected()).toEqual([0, 1]))
  const transfer = { setData: vi.fn(), effectAllowed: '', dropEffect: '' }
  const drag = (kind: string, target: HTMLElement, clientX: number) => {
    const event = new MouseEvent(kind, { bubbles: true, cancelable: true, clientX })
    Object.defineProperty(event, 'dataTransfer', { value: transfer }); target.dispatchEvent(event)
  }
  drag('dragstart', app.card(0), 0)
  drag('dragover', app.card(3), -1)
  drag('drop', app.card(3), 1)
  await vi.waitFor(() => expect(app.draft.operations).toMatchObject([{ order: [2, 3, 0, 1] }]))
  expect([...app.sorter.querySelectorAll<HTMLElement>('[role=option]')].map(el => Number(el.dataset.slideIndex))).toEqual([2, 3, 0, 1])
  app.control<HTMLButtonElement>('[data-source-action=onUndo]').click()
  await vi.waitFor(() => expect(app.draft.operations).toEqual([]))
  expect([...app.sorter.querySelectorAll<HTMLElement>('[role=option]')].map(el => Number(el.dataset.slideIndex))).toEqual([0, 1, 2, 3])
  app.control<HTMLButtonElement>('[data-source-action=onRedo]').click()
  await vi.waitFor(() => expect(app.draft.operations).toMatchObject([{ order: [2, 3, 0, 1] }]))
})

it('Delete批量删除使用同一历史且至少保留一页，关闭后旧节点不能写入', async () => {
  const app = await fixture()
  app.key('a', { ctrlKey: true }); await vi.waitFor(() => expect(app.selected()).toEqual([0, 1, 2, 3]))
  app.key('Delete'); expect(app.draft.operations).toEqual([])
  app.card(1).click(); await vi.waitFor(() => expect(app.selected()).toEqual([1]))
  app.key('Delete'); await vi.waitFor(() => expect(app.draft.operations).toMatchObject([{ order: [0, 2, 3], deletedSlides: [1] }]))
  app.control<HTMLButtonElement>('[data-source-action=onUndo]').click(); await vi.waitFor(() => expect(app.draft.operations).toEqual([]))
  app.view.dispose(); views.splice(views.indexOf(app.view), 1)
  app.key('Delete'); expect(app.draft.operations).toEqual([])
})

it('备注输入法未结束时拒绝切换，结束后切换保留同一来源草稿', async () => {
  const app = await fixture()
  app.control<HTMLButtonElement>('[data-command=normalView]').click()
  const notes = app.control<HTMLTextAreaElement>('[data-notes-text]')
  notes.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }))
  notes.value = '输入法中的备注'
  notes.dispatchEvent(new InputEvent('input', { bubbles: true, isComposing: true }))
  app.control<HTMLButtonElement>('[data-command=slideSorter]').click()
  expect(app.control('.slides-workspace').dataset.viewMode).toBe('normal')
  expect(app.draft.operations).toEqual([])
  notes.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true }))
  app.control<HTMLButtonElement>('[data-command=slideSorter]').click()
  await vi.waitFor(() => expect(app.control('.slides-workspace').dataset.viewMode).toBe('sorter'))
  expect(app.draft.operations).toMatchObject([{ notesEdits: [{ slideIndex: 0, text: '输入法中的备注' }] }])
})
