import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'
import { NativeDraft } from './native-draft'

vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
vi.mock('react-konva', async () => {
  const React = await import('react')
  const container = ({ children }: any) => React.createElement('div', null, children)
  return { Stage: container, Layer: container, Group: container, Rect: () => null }
})
vi.mock('./vendor/genoffice/renderer/NodeBody', () => ({ StaticNode: () => null }))
const views: ReturnType<typeof createSlidesEditorView>[] = []
beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} }))
afterEach(() => { views.splice(0).forEach(view => view.dispose()); document.body.replaceChildren(); vi.unstubAllGlobals() })

async function fixture() {
  const source = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [{ slideIndex: 0, animations: [{ spid: 2, elementId: 'title', effect: 'fade', trigger: 'onClick', durationMs: 500, delayMs: 0 }], elements: [{ id: 'title', type: 'text', name: '标题', text: '来源标题', editable: true }] }] }
  const tree = { slides: [{ slideIndex: 0, widthPx: 960, heightPx: 540, background: { kind: 'solid', color: '#ffffff' }, nodes: [{ id: 'title', sourceId: 'title', type: 'shape', box: { x: 10, y: 10, w: 200, h: 50 } }] }] }
  const shell = createEditorShell(document.body.appendChild(document.createElement('main')), 'full', 'pptx')
  const draft = new NativeDraft({ documentId: 'animation-preview', revision: 1, sourceSha256: source.sha256, scope: { database: 'fixture', companyId: 'c', userId: 'u', threadId: 't' } }, { getItem: () => null, setItem() {}, removeItem() {} })
  const request = vi.fn(async (path: string, _init?: RequestInit) => path === 'deck' ? source : tree)
  const view = createSlidesEditorView(shell.editor, { native: true, draft, request: request as never, save: shell.save, download: shell.exportPptx }); views.push(view); await view.ready
  const opener = shell.editor.querySelector<HTMLButtonElement>('[data-command="animationPreview"]')!
  return { source, tree, shell, draft, request, view, opener }
}

it('动画预览入口读取来源与新增动画的当前原生草稿快照，取消后保留来源与草稿且恢复入口焦点', async () => {
  const { source, shell, draft, request, opener } = await fixture()
  expect(opener.disabled).toBe(false)
  const select = shell.editor.querySelector<HTMLSelectElement>('#object-select')!; select.value = 'title'; select.dispatchEvent(new Event('change'))
  const effect = shell.editor.querySelector<HTMLSelectElement>('[data-command="animationEffect"]')!; effect.value = 'pulse'; effect.dispatchEvent(new Event('change'))
  shell.editor.querySelector<HTMLButtonElement>('[data-command="addAnimation"]')!.click()
  expect(draft.operations).toMatchObject([{ animations: [{ elementId: 'title', effect: 'pulse', append: true }] }])
  const before = JSON.stringify(draft.operations), sourceBefore = JSON.stringify(source)
  opener.focus(); opener.click()
  await vi.waitFor(() => expect(shell.editor.querySelector('.slides-animation-preview')).not.toBeNull())
  expect(request.mock.calls.filter(call => call[0] === 'render-tree').length).toBe(2)
  const sent = JSON.parse(String(request.mock.calls.filter(call => call[0] === 'render-tree').at(-1)![1]!.body))
  expect(sent.operations).toEqual(JSON.parse(before)); expect(sent.expectedSha256).toBe(source.sha256)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
  expect(shell.editor.querySelector('.slides-animation-preview')).toBeNull()
  expect(document.activeElement).toBe(opener)
  expect(JSON.stringify(draft.operations)).toBe(before); expect(JSON.stringify(source)).toBe(sourceBefore)
})


it.each(['draft', 'dispose'])('预览快照请求未返回时%s变化，迟到结果不得打开旧播放器', async change => {
  const { shell, draft, request, view, opener, tree } = await fixture()
  let resolve!: (value: typeof tree) => void
  request.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  opener.focus(); opener.click()
  if (change === 'dispose') { view.dispose(); views.splice(views.indexOf(view), 1) }
  else { shell.editor.querySelector<HTMLButtonElement>('[data-command="hideSlide"]')!.click(); expect(draft.operations).not.toEqual([]) }
  resolve(tree); await new Promise(done => setTimeout(done, 30))
  expect(shell.editor.querySelector('.slides-animation-preview')).toBeNull()
})

it('重复启动只接纳最后一次快照，销毁活动播放器不留下叠层', async () => {
  const { shell, request, view, opener, tree } = await fixture()
  let first!: (value: typeof tree) => void
  request.mockImplementationOnce(() => new Promise(done => { first = done }))
  opener.focus(); opener.click(); opener.click()
  await vi.waitFor(() => expect(shell.editor.querySelectorAll('.slides-animation-preview')).toHaveLength(1))
  first(tree); await new Promise(done => setTimeout(done, 30))
  expect(shell.editor.querySelectorAll('.slides-animation-preview')).toHaveLength(1)
  view.dispose(); views.splice(views.indexOf(view), 1)
  expect(shell.editor.querySelector('.slides-animation-preview')).toBeNull()
})
