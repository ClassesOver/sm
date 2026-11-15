import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'
import { NativeDraft } from './native-draft'

vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} }))
afterEach(() => {
  document.body.innerHTML = ''
  document.documentElement.lang = ''
  vi.unstubAllGlobals()
})
const geometry = (x: number, y: number, width = 80, height = 40) => ({ x, y, width, height })
const source = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [
  { slideIndex: 0, elements: [
    { id: 'one', type: 'text', name: '一', text: '保留文字', editable: true, deletable: true, arrangeEditable: true, geometry: geometry(10, 20) },
    { id: 'two', type: 'shape', name: '二', text: '二', editable: true, deletable: true, arrangeEditable: true, geometry: geometry(200, 90) },
    { id: 'three', type: 'shape', name: '三', text: '', editable: true, deletable: true, arrangeEditable: true, geometry: geometry(400, 150) },
    { id: 'picture', type: 'picture', name: '图片', text: '', editable: false, deletable: true, arrangeEditable: true, pictureCropEditable: true,
      pictureOpacityEditable: true, pictureTransform: { rot: 0, flipH: false, flipV: false }, pictureReplaceable: true, pictureSha256: 'b'.repeat(64), pictureSize: 68, srcRect: null, geometry: geometry(40, 200, 200, 100) },
  ] },
  { slideIndex: 1, elements: [{ id: 'other', type: 'text', name: '其他页', text: '其他页', editable: true, arrangeEditable: true, geometry: geometry(40, 40) }] },
] }
async function open(operations: Record<string, unknown>[] = []) {
  document.documentElement.lang = 'zh-CN'
  const storage = new Map<string, string>()
  const draft = new NativeDraft({ documentId: 'crop-arrange', revision: 1, sourceSha256: source.sha256,
    scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } },
  { getItem: key => storage.get(key) ?? null, setItem: (key, value) => { storage.set(key, value) }, removeItem: key => { storage.delete(key) } })
  if (operations.length) draft.setOperations(operations as any)
  const root = document.createElement('main'); document.body.append(root)
  const shell = createEditorShell(root, 'full', 'pptx')
  const request = vi.fn(async (path: string, _init?: RequestInit) => path === 'deck' ? source : path === 'render-tree' ? { slides: [] }
    : { revision: 2, revisionRegistered: true, validation: { issues: [] } })
  const view = createSlidesEditorView(shell.editor, { native: true, draft, request: request as any, save: shell.save, download: shell.exportPptx })
  await view.ready
  const command = (name: string) => shell.editor.querySelector<HTMLButtonElement>(`[data-command="${name}"]`)!
  const choose = (id: string) => {
    const checkbox = shell.editor.querySelector<HTMLInputElement>(`[data-arrange-object="${id}"]`)!
    expect(checkbox).not.toBeNull(); checkbox.click()
  }
  return { view, shell, draft, request, command, choose }
}

it('多选排列保留文字与非目标编辑，一次撤销恢复整批并可保存', async () => {
  const app = await open([{ kind: 'editSlides', edits: [{ slideIndex: 0, elementId: 'one', text: '已改文字' }], order: [0, 1] }])
  // 默认焦点已选第一项；复选第二项扩展同页选择。
  app.choose('two')
  expect(app.command('alignTop').disabled).toBe(false)
  app.command('alignTop').click()
  expect(app.draft.operations[0]?.edits).toEqual([
    { slideIndex: 0, elementId: 'one', text: '已改文字' },
    { slideIndex: 0, elementId: 'two', geometry: geometry(200, 20) },
  ])
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(app.draft.operations[0]?.edits).toEqual([{ slideIndex: 0, elementId: 'one', text: '已改文字' }])
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  app.shell.save.click()
  await vi.waitFor(() => expect(app.request.mock.calls.some(([path]) => path === 'save')).toBe(true))
  const call = app.request.mock.calls.find(([path]) => path === 'save')!
  expect(JSON.parse(call[1]!.body as string).operations[0].edits).toHaveLength(2)
  app.view.dispose()
})

it('分布需至少三项，切换页面后不沿用上页选择', async () => {
  const app = await open()
  app.choose('two')
  expect(app.command('distributeHorizontal').disabled).toBe(true)
  app.choose('three')
  expect(app.command('distributeHorizontal').disabled).toBe(false)
  const slide = app.shell.editor.querySelector<HTMLButtonElement>('[data-slide-index="1"]')
  expect(slide).not.toBeNull(); slide!.click()
  expect(app.command('distributeHorizontal').disabled).toBe(true)
  expect(app.shell.editor.querySelectorAll('[data-arrange-object]:checked')).toHaveLength(1)
  expect(app.draft.operations).toEqual([])
  app.view.dispose()
})

it('stages picture rotation and flips from the ribbon with one undo step per command', async () => {
  const app = await open()
  try {
    const rotate = app.command('rotatePictureRight')
    expect(rotate.disabled).toBe(true)
    const select = app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!
    select.value = 'picture'
    select.dispatchEvent(new Event('change', { bubbles: true }))
    expect(rotate.disabled).toBe(false)
    rotate.click()
    app.command('flipPictureH').click()
    app.command('flipPictureV').click()
    expect(app.draft.operations[0]?.edits).toEqual([
      { slideIndex: 0, elementId: 'picture', pictureTransform: { rot: 5400000, flipH: true, flipV: true } },
    ])
    app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
    expect(app.draft.operations[0]?.edits).toEqual([
      { slideIndex: 0, elementId: 'picture', pictureTransform: { rot: 5400000, flipH: true, flipV: false } },
    ])
  } finally {
    app.view.dispose()
  }
})
it('selects a GenOffice picture transparency preset and saves against the original picture identity', async () => {
  const app = await open()
  try {
    const picker = app.shell.editor.querySelector<HTMLSelectElement>('select[data-command="pictureOpacity"]')!
    expect(picker.disabled).toBe(true)
    const object = app.shell.editor.querySelector<HTMLSelectElement>('#object-select')!
    object.value = 'picture'
    object.dispatchEvent(new Event('change', { bubbles: true }))
    expect(picker.disabled).toBe(false)
    expect(Array.from(picker.options, option => option.textContent)).toEqual(['0%', '15%', '30%', '50%', '65%', '80%', '95%'])
    picker.value = '65'
    picker.dispatchEvent(new Event('change', { bubbles: true }))
    app.shell.save.click()
    await vi.waitFor(() => expect(app.request.mock.calls.some(([path]) => path === 'save')).toBe(true))
    const call = app.request.mock.calls.find(([path]) => path === 'save')!
    expect(JSON.parse(call[1]!.body as string).operations[0].pictureOpacities).toEqual([
      { slideIndex: 0, elementId: 'picture', expectedSha256: 'b'.repeat(64), expectedSize: 68, opacity: 0.35 },
    ])
  } finally {
    app.view.dispose()
  }
})
