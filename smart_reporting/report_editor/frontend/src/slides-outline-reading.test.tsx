import React from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createSlidesEditorView } from './slides-main'
import { createEditorShell } from './shell'
import { NativeDraft } from './native-draft'
import { outlineOf } from './vendor/genoffice-slides/outline-of'

vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
vi.mock('./vendor/genoffice/renderer/SlideThumb', () => ({ SlideThumb: ({ width }: { width: number }) => <figure data-source-thumbnail data-width={width} /> }))
const text = (value: string, font = 18, y = 0, id = 'title') => ({ id, sourceId: id, type: 'text', box: { x: 10, y, w: 300, h: 50 }, text: { lines: [{ runs: [{ text: value, fontSizePx: font }] }] } })
const views: ReturnType<typeof createSlidesEditorView>[] = []
beforeEach(() => { vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }) })
afterEach(() => { views.splice(0).forEach(view => view.dispose()); document.body.replaceChildren(); vi.unstubAllGlobals() })

it('源大纲提取递归组合，按首run字号与y选标题，其余按y排列并折叠空白', () => {
  const nodes = [text('  正文\n A ', 20, 100), { type: 'group', children: [text('组合大标题', 40, 90)] }, text('同字号更上方', 40, 10), text('前置正文', 12, 5)]
  expect(outlineOf({ nodes } as never)).toEqual({ title: '同字号更上方', lines: ['前置正文', '组合大标题', '正文 A'] })
  expect(outlineOf({ nodes: [] } as never)).toEqual({ title: '', lines: [] })
})

async function fixture() {
  const source = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [0, 1, 2].map(slideIndex => ({ slideIndex, notesText: '', notesEditable: true, elements: [{ id: 'title', name: '标题', type: 'text', text: `来源${slideIndex}`, editable: true, geometry: { x: 10, y: 10, width: 300, height: 50 } }], animations: [] })) }
  const tree = { slides: source.slides.map(slide => ({ slideIndex: slide.slideIndex, widthPx: 960, heightPx: 540, nodes: slide.slideIndex === 1 ? [] : [text(`来源标题${slide.slideIndex}`, 36), ...Array.from({ length: 7 }, (_, index) => text(`正文${index}`, 18, index * 50 + 100, `body${index}`))] })) }
  const shell = createEditorShell(document.body.appendChild(document.createElement('main')), 'full', 'pptx')
  const draft = new NativeDraft({ documentId: 'outline-reading', revision: 1, sourceSha256: source.sha256, scope: { database: 'fixture', companyId: 'c', userId: 'u', threadId: 't' } }, { getItem: () => null, setItem() {}, removeItem() {} })
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === 'deck') return source
    if (path === 'render-tree') {
      if (init?.body) for (const edit of JSON.parse(String(init.body)).operations?.[0]?.edits ?? []) if (edit.text !== undefined) tree.slides[edit.slideIndex]!.nodes[0] = text(edit.text, 36)
      return tree
    }
    return { revision: 2, revisionRegistered: true, validation: { issues: [] } }
  })
  const view = createSlidesEditorView(shell.editor, { native: true, draft, request: request as never, save: shell.save, download: shell.exportPptx })
  views.push(view); await view.ready
  const control = <T extends HTMLElement>(selector: string) => shell.editor.querySelector<T>(selector)!
  const open = async (mode: 'outline' | 'reading') => {
    control<HTMLButtonElement>(`[data-command=${mode}View]`)!.click()
    await vi.waitFor(() => expect(control(`.slides-${mode === 'outline' ? 'outline-pane' : 'reading-view'}`)?.hidden).toBe(false))
  }
  const current = () => Number(control('.slide-row[data-selected=true] .slide-open').getAttribute('data-slide-index'))
  return { shell, draft, request, view, control, open, current }
}

it('大纲列出来源标题/前五正文/省略号及无文字页，选页保留画布且视图不写草稿', async () => {
  const app = await fixture(); await app.open('outline')
  const pane = app.control('.slides-outline-pane')
  expect(pane.querySelectorAll('[role=option]')).toHaveLength(3)
  expect(pane.querySelector('.slides-outline-title')!.textContent).toBe('来源标题0')
  expect(pane.querySelectorAll('.slides-outline-item:first-child .slides-outline-line:not(.slides-outline-more)')).toHaveLength(5)
  expect(pane.querySelector('.slides-outline-more')!.textContent).toBe('…')
  expect(pane.querySelector('[data-slide-index="1"] .slides-outline-title')!.textContent).toBe('（无文字）')
  pane.querySelector<HTMLElement>('[data-slide-index="2"]')!.click()
  expect(app.current()).toBe(2); expect(document.activeElement).toBe(pane)
  expect(app.control('.slides-workspace').dataset.viewMode).toBe('outline')
  expect(app.control('.slides-stage').hidden).toBe(false)
  expect(app.draft.operations).toEqual([])
})

it('大纲键盘遵守焦点和IME，正文仍经现有编辑/预览/撤销链刷新大纲', async () => {
  const app = await fixture(); await app.open('outline')
  const pane = app.control('.slides-outline-pane')
  pane.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true })); expect(app.current()).toBe(2)
  pane.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true, isComposing: true })); expect(app.current()).toBe(2)
  const select = app.control<HTMLSelectElement>('#object-select'); select.value = 'title'; select.dispatchEvent(new Event('change'))
  const input = app.control<HTMLTextAreaElement>('#object-text'); input.value = '大纲保持编辑结果'; input.dispatchEvent(new Event('input'))
  expect(app.draft.operations).toMatchObject([{ edits: [{ slideIndex: 2, elementId: 'title', text: '大纲保持编辑结果' }] }])
  await vi.waitFor(() => expect(pane.querySelector('[data-slide-index="2"] .slides-outline-title')!.textContent).toBe('大纲保持编辑结果'), { timeout: 3000 })
  app.control<HTMLButtonElement>('[data-source-action=onUndo]').click(); expect(app.draft.operations).toEqual([])
})

it('阅读用源SlideThumb静态逐页浏览，点击/键盘/上下页边界和Escape回普通不写草稿', async () => {
  const app = await fixture(); await app.open('reading')
  const pane = app.control('.slides-reading-view')
  await vi.waitFor(() => expect(pane.querySelector('[data-source-thumbnail]')).not.toBeNull())
  expect(document.activeElement).toBe(pane)
  expect(pane.textContent).toContain('不播放动画、转场和音视频')
  const key = (key: string, extra = {}) => pane.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...extra }))
  key('ArrowRight'); expect(app.current()).toBe(1)
  key('PageDown'); expect(app.current()).toBe(2)
  await vi.waitFor(() => expect(pane.querySelector<HTMLButtonElement>('.slides-reading-bar button:nth-of-type(2)')!.disabled).toBe(true))
  key('Enter'); expect(app.current()).toBe(2)
  key('ArrowLeft'); expect(app.current()).toBe(1)
  key(' ', { isComposing: true }); expect(app.current()).toBe(1)
  key('Escape'); expect(app.control('.slides-workspace').dataset.viewMode).toBe('normal')
  expect(app.current()).toBe(1); expect(app.draft.operations).toEqual([])
})

it('阅读快捷键不接管Ribbon/输入，按钮空格不双翻，退出/销毁后捕获监听失效', async () => {
  const app = await fixture(); await app.open('reading'); const pane = app.control('.slides-reading-view')
  app.control<HTMLButtonElement>('[data-ribbon-tab=view]').focus()
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })); expect(app.current()).toBe(0)
  pane.focus(); await vi.waitFor(() => expect(pane.querySelector('.slides-reading-bar')).not.toBeNull())
  const next = pane.querySelector<HTMLButtonElement>('.slides-reading-bar button:nth-of-type(2)')!; next.focus()
  const space = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true }); next.dispatchEvent(space)
  expect(space.defaultPrevented).toBe(false); next.click(); expect(app.current()).toBe(1)
  const nested = document.createElement('input'); pane.append(nested); nested.focus(); nested.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })); expect(app.current()).toBe(1)
  app.view.dispose(); views.splice(views.indexOf(app.view), 1)
  const after = structuredClone(app.draft.operations); window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })); expect(app.draft.operations).toEqual(after)
})

it('备注IME阻止两种视图切换时四个入口状态保持一致', async () => {
  const app = await fixture(), notes = app.control<HTMLTextAreaElement>('[data-notes-text]')
  notes.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true })); notes.value = '未结束输入'
  for (const command of ['outlineView', 'readingView']) {
    app.control<HTMLButtonElement>(`[data-command=${command}]`).click()
    expect(app.control(`[data-command=${command}]`).getAttribute('aria-pressed')).toBe('false')
    expect(app.control('[data-command=normalView]').getAttribute('aria-pressed')).toBe('true')
  }
  expect(app.draft.operations).toEqual([])
})
