import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'
import { NativeDraft } from './native-draft'

vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
const views: ReturnType<typeof createSlidesEditorView>[] = []
beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} }))
afterEach(() => { views.splice(0).forEach(view => view.dispose()); document.body.replaceChildren(); vi.unstubAllGlobals() })
const longName = '季度经营分析与收入构成的完整来源对象名称'.repeat(8)
async function open(count = 3) {
  const source = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [{ slideIndex: 0,
    animations: Array.from({ length: count }, () => ({ spid: 2, elementId: 'body', effect: 'fade', trigger: 'onClick', durationMs: 500, delayMs: 0 })),
    elements: [{ id: 'body', name: longName, text: '来源正文', type: 'text', editable: true, geometry: { x: 10, y: 10, width: 100, height: 50 } }] }] }
  const draft = new NativeDraft({ documentId: 'animations', revision: 1, sourceSha256: source.sha256, scope: { database: 'fixture', companyId: 'c', userId: 'u', threadId: 't' } }, { getItem: () => null, setItem() {}, removeItem() {} })
  const shell = createEditorShell(document.body.appendChild(document.createElement('main')), 'full', 'pptx')
  const view = createSlidesEditorView(shell.editor, { native: true, draft, save: shell.save, download: shell.exportPptx,
    request: async <T>(path: string) => (path === 'deck' ? source : { slides: [] }) as T })
  views.push(view); await view.ready
  shell.editor.querySelector<HTMLButtonElement>('[data-ribbon-tab="animations"]')!.click()
  const opener = shell.editor.querySelector<HTMLButtonElement>('[data-command="toggleAnimationPane"]')!
  opener.focus(); opener.click()
  const pane = shell.editor.querySelector<HTMLElement>('.slides-animation-pane')!
  return { shell, draft, pane, opener }
}
const control = (pane: HTMLElement, index: number, selector = '.animation-pane-select') => pane.querySelector<HTMLButtonElement>(`[data-animation-row="${index}"] ${selector}`)!

it('closes the pane, returns focus to its entry and preserves the draft', async () => {
  const app = await open()
  const close = app.pane.querySelector<HTMLButtonElement>('[aria-label="关闭动画窗格"]')
  expect(close).not.toBeNull(); close!.click()
  expect(app.pane.hidden).toBe(true)
  expect(app.opener.getAttribute('aria-pressed')).toBe('false')
  expect(document.activeElement).toBe(app.opener)
  expect(app.draft.operations).toEqual([])
  app.opener.click(); expect(app.pane.hidden).toBe(false)
})

it('keeps focus on the selected animation through selection and deselection', async () => {
  const app = await open()
  for (const pressed of ['true', 'false']) {
    control(app.pane, 1).focus(); control(app.pane, 1).click()
    expect(document.activeElement).toBe(control(app.pane, 1))
    expect(control(app.pane, 1).getAttribute('aria-pressed')).toBe(pressed)
    expect(app.draft.operations).toEqual([])
  }
})

it('returns to the active ribbon tab when the animation entry is hidden', async () => {
  const app = await open(), home = app.shell.editor.querySelector<HTMLButtonElement>('[data-ribbon-tab="home"]')!
  home.click()
  app.pane.querySelector<HTMLButtonElement>('[aria-label="关闭动画窗格"]')?.click()
  expect(app.pane.hidden).toBe(true)
  expect(document.activeElement).toBe(home)
  expect(app.draft.operations).toEqual([])
})

it.each([[-1, 0], [1, 2]])('follows the moved item and uses its selector at boundary %s', async (direction, target) => {
  const app = await open()
  const selector = `button[title="${direction === -1 ? '上移' : '下移'}"]`
  control(app.pane, 1, selector).focus(); control(app.pane, 1, selector).click()
  expect(document.activeElement).toBe(control(app.pane, target))
  expect(app.draft.operations[0]).toMatchObject({ animationSequences: [{ slideIndex: 0, items: direction === -1
    ? [{ source: 1 }, { source: 0 }, { source: 2 }] : [{ source: 0 }, { source: 2 }, { source: 1 }] }] })
})

it('keeps the move control focused while it can continue moving', async () => {
  const app = await open(4)
  control(app.pane, 2, 'button[title="上移"]').focus(); control(app.pane, 2, 'button[title="上移"]').click()
  expect(document.activeElement).toBe(control(app.pane, 1, 'button[title="上移"]'))
})

it.each([0, 2])('focuses the surviving row after deleting row %s', async index => {
  const app = await open()
  control(app.pane, index, 'button[title="删除"]').focus(); control(app.pane, index, 'button[title="删除"]').click()
  expect(document.activeElement).toBe(control(app.pane, Math.min(index, 1)))
  expect(app.pane.querySelectorAll('.animation-pane-row')).toHaveLength(2)
})

it('focuses the close control after deleting the final animation', async () => {
  const app = await open(1)
  control(app.pane, 0, 'button[title="删除"]').click()
  expect(document.activeElement).toBe(app.pane.querySelector('[aria-label="关闭动画窗格"]'))
  expect(app.pane.querySelectorAll('.animation-pane-row')).toHaveLength(0)
})

it('preserves list scroll when selection or ribbon timing rerenders it', async () => {
  const app = await open(30)
  app.pane.querySelector<HTMLOListElement>('ol')!.scrollTop = 250
  control(app.pane, 20).click()
  expect(app.pane.querySelector('ol')!.scrollTop).toBe(250)
  const timing = app.shell.editor.querySelector<HTMLInputElement>('[data-command="animationDuration"]')!
  timing.focus(); timing.value = '1200'; timing.dispatchEvent(new Event('change', { bubbles: true }))
  expect(document.activeElement).toBe(timing)
  expect(app.pane.querySelector('ol')!.scrollTop).toBe(250)
})

it('exposes the full object name and timing in the row tooltip', async () => {
  const app = await open()
  expect(control(app.pane, 0).title).toContain(longName)
  expect(control(app.pane, 0).title).toContain('单击时 · 0.50 秒')
})

it('allows Home and End to scroll a long row without changing selection or draft', async () => {
  const app = await open(), row = control(app.pane, 0)
  Object.defineProperty(row, 'scrollHeight', { value: 500 })
  row.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true, cancelable: true }))
  expect(row.scrollTop).toBe(500)
  row.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', ctrlKey: true, bubbles: true, cancelable: true }))
  expect(row.scrollTop).toBe(500)
  row.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true, cancelable: true }))
  expect(row.scrollTop).toBe(0)
  expect(row.getAttribute('aria-pressed')).toBe('false')
  expect(app.draft.operations).toEqual([])
})

it('rejects stale animation selection and delete events while saving', async () => {
  const app = await open(3)
  const row = control(app.pane, 1), remove = control(app.pane, 1, 'button[title="删除"]')
  app.draft.beginSave()
  row.dispatchEvent(new Event('click', { bubbles: true }))
  remove.dispatchEvent(new Event('click', { bubbles: true }))
  expect(row.getAttribute('aria-pressed')).toBe('false')
  expect(app.pane.querySelectorAll('.animation-pane-row')).toHaveLength(3)
  expect(app.draft.operations).toEqual([])
})
