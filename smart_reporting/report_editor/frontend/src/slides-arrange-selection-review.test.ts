import { afterEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'
import { NativeDraft } from './native-draft'
import type { SlidesCanvasState } from './slides-canvas'

const canvas = vi.hoisted(() => ({ state: undefined as SlidesCanvasState | undefined }))
vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update(state: SlidesCanvasState) { canvas.state = state }, destroy() {} }) }))
afterEach(() => { document.body.innerHTML = ''; document.documentElement.lang = ''; canvas.state = undefined })

async function open() {
  document.documentElement.lang = 'zh-CN'
  const source = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [{ slideIndex: 0, elements: [
    { id: 'one', type: 'text', name: '一', text: '一', editable: true, deletable: true, arrangeEditable: true, geometry: { x: 10, y: 20, width: 80, height: 40 } },
    { id: 'two', type: 'shape', name: '二', text: '二', editable: true, deletable: true, arrangeEditable: true, geometry: { x: 200, y: 90, width: 80, height: 40 } },
    { id: 'table', type: 'table', name: '表格', text: '', tableCells: [['原值']], geometry: { x: 300, y: 150, width: 80, height: 40 } },
  ] }] }
  const storage = new Map<string, string>()
  const draft = new NativeDraft({ documentId: 'selection-review', revision: 1, sourceSha256: source.sha256,
    scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } },
  { getItem: key => storage.get(key) ?? null, setItem: (key, value) => { storage.set(key, value) }, removeItem: key => { storage.delete(key) } })
  const root = document.createElement('main'); document.body.append(root)
  const shell = createEditorShell(root, 'full', 'pptx')
  const request = vi.fn(async (path: string) => path === 'deck' ? source : path === 'render-tree' ? { slides: [{ slideIndex: 0, widthPx: 960, heightPx: 540, nodes: [] }] } : {})
  const view = createSlidesEditorView(shell.editor, { native: true, draft, request: request as any, save: shell.save, download: shell.exportPptx })
  await view.ready
  await vi.waitFor(() => expect(canvas.state).toBeDefined())
  return { view, shell, draft }
}

it('多选时停用单对象动画入口且不产生草稿', async () => {
  const app = await open()
  canvas.state!.onSelect('two', true)
  expect(canvas.state!.selectedIds).toEqual(['one', 'two'])
  const add = app.shell.editor.querySelector<HTMLButtonElement>('.animation-add')!
  expect(add.disabled).toBe(true)
  add.click()
  expect(app.draft.operations).toEqual([])
  app.view.dispose()
})

it('画布空白清空选择后不隐式重选对象或产生历史', async () => {
  const app = await open()
  canvas.state!.onSelect('')
  expect(canvas.state!.selectedIds).toEqual([])
  expect(app.shell.editor.querySelectorAll('[data-arrange-object]:checked')).toHaveLength(0)
  expect(app.shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!.disabled).toBe(true)
  expect(app.shell.editor.querySelector<HTMLButtonElement>('[data-command="alignTop"]')!.disabled).toBe(true)
  expect(app.draft.operations).toEqual([])
  expect(app.draft.canUndo).toBe(false)
  app.view.dispose()
})

it('多选包含表格时停用单元格编辑且不产生草稿', async () => {
  const app = await open()
  canvas.state!.onSelect('table')
  const cell = app.shell.editor.querySelector<HTMLTextAreaElement>('[data-table-cell="0:0"]')!
  expect(cell.disabled).toBe(false)
  canvas.state!.onSelect('one', true)
  expect(canvas.state!.selectedIds).toEqual(['table', 'one'])
  expect(app.shell.editor.querySelector<HTMLElement>('.table-cell-editor')!.hidden).toBe(true)
  expect(app.shell.editor.querySelector('[data-table-cell]')).toBeNull()
  expect(cell.isConnected).toBe(false)
  // 多选前持有的旧单元格回调也不得写入草稿。
  cell.value = '不应应用'; cell.dispatchEvent(new Event('change'))
  expect(app.draft.operations).toEqual([])
  expect(cell.value).toBe('原值')
  app.view.dispose()
})

it('无位移对齐不产生草稿或撤销历史', async () => {
  const app = await open()
  // 单对象对齐到页顶会先产生一次变化；重复同一操作不应再写入历史。
  const align = app.shell.editor.querySelector<HTMLButtonElement>('[data-command="alignTop"]')!
  align.click()
  const operations = JSON.stringify(app.draft.operations)
  align.click()
  expect(JSON.stringify(app.draft.operations)).toBe(operations)
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(app.draft.operations).toEqual([])
  expect(app.draft.canUndo).toBe(false)
  app.view.dispose()
})
