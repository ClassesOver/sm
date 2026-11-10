import { afterEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'
import { createNativeOfficeView } from './native-office-view'
import { NativeDraft, type NativeDraftIdentity, type NativeSaveRequest } from './native-draft'
import type { NativeContextResponse } from './native-api'
vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })
const deck = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [{ slideIndex: 0, transitionApplyAllSafe: true, animations: [], elements: [{ id: 'title', type: 'text', name: 'title', text: '原文', editable: true, geometry: { x: 10, y: 20, width: 300, height: 80 } }] }] }
it('native PPTX skips unsupported AI requests and retains draft until registration, then offers explicit reopen', async () => {
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'pptx')
  let saves = 0
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === 'deck') return deck
    if (path === 'render-tree') return { slides: [] }
    if (path === 'save') return { revision: 2, revisionRegistered: ++saves > 1, editor: { openUrl: '/next-revision' }, pptx: { downloadUrl: '/download' }, validation: { issues: [{ message: '待复核' }] } }
    throw Error(`unexpected ${path}`)
  })
  const view = createSlidesEditorView(shell.editor, { save: shell.save, download: shell.exportPptx, request: request as any, native: true })
  await view.ready
  expect(shell.editor.querySelector<HTMLElement>('.slides-ai')!.hidden).toBe(true)
  expect(shell.editor.querySelector<HTMLElement>('.slides-image-tools')!.hidden).toBe(true)
  expect(request.mock.calls.some(([path]) => path.startsWith('charts') || path.startsWith('ai'))).toBe(false)
  const effect = shell.editor.querySelector<HTMLSelectElement>('[data-command="animationEffect"]')!
  effect.value = 'fade'
  effect.dispatchEvent(new Event('change', { bubbles: true }))
  shell.editor.querySelector<HTMLButtonElement>('[data-command="addAnimation"]')!.click()
  const slideSize = shell.editor.querySelector<HTMLSelectElement>('[data-command="slideSize"][data-source-action="onSlideSize"]')!
  slideSize.value = '16:9'
  slideSize.dispatchEvent(new Event('change', { bubbles: true }))
  const text = shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!
  text.value = '修改值'; text.dispatchEvent(new Event('input'))
  shell.save.click(); await vi.waitFor(() => expect(saves).toBe(1)); await vi.waitFor(() => expect(shell.save.disabled).toBe(false))
  const saveRequest = request.mock.calls.find(([path]) => path === 'save')
  const payload = JSON.parse(saveRequest?.[1]?.body as string) as { animations: { effect: string; append?: boolean }[]; slideSize: { cx: number; cy: number } }
  expect(payload.animations).toEqual([expect.objectContaining({ effect: 'fade', append: true })])
  expect(payload.slideSize).toEqual({ cx: 12192000, cy: 6858000 })
  expect(text.value).toBe('修改值')
  shell.save.click(); await vi.waitFor(() => expect(shell.save.disabled).toBe(true))
  expect(shell.editor.querySelector<HTMLAnchorElement>('.revision-link')?.getAttribute('href')).toBe('/next-revision')
  expect(shell.editor.textContent).toContain('待复核'); view.dispose()
})
it('native PPTX exposes initialization failure to the host', async () => {
  document.body.innerHTML = '<span class="save-state-label"></span><span class="revision-label"></span>'
  const host = document.createElement('div'); document.body.append(host)
  const view = createSlidesEditorView(host, { save: document.createElement('button'), download: document.createElement('a'), native: true, request: async () => { throw Error('源文件不可读') } })
  await expect(view.ready).rejects.toThrow('源文件不可读'); view.dispose()
})

const draftIdentity: NativeDraftIdentity = { documentId: 'slides-draft', revision: 1, sourceSha256: deck.sha256,
  scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
const draftContext = { context: { ...draftIdentity, format: 'pptx', sourceFile: { sha256: deck.sha256 } }, editingEnabled: true } as unknown as NativeContextResponse
function draftStore() {
  const values = new Map<string, string>()
  return { getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
}
async function openDraft(draft: NativeDraft, api: Record<string, unknown>) {
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'pptx')
  const view = await createNativeOfficeView(shell, { api: api as never, context: draftContext, draft })
  if (!view) throw new Error('PPTX 编辑器未创建')
  return { shell, view }
}
function setRibbonValue(host: HTMLElement, command: string, value: string) {
  const control = host.querySelector<HTMLInputElement | HTMLSelectElement>(`[data-command="${command}"]`)!
  control.value = value
  control.dispatchEvent(new Event('change', { bubbles: true }))
}

it('swaps writable custom source dimensions without replacing them with a preset', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  const orientation = shell.editor.querySelector<HTMLSelectElement>('[data-command="slideOrientation"]')
  expect(orientation).not.toBeNull()
  expect(orientation!.disabled).toBe(false)
  setRibbonValue(shell.editor, 'slideOrientation', 'portrait')
  expect(draft.operations[0]).toMatchObject({ slideSize: { cx: 5143500, cy: 9144000 } })
  expect(deck.size).toEqual({ cx: 9144000, cy: 5143500 })
  setRibbonValue(shell.editor, 'slideSize', 'A4')
  expect(orientation!.disabled).toBe(false)
  expect(draft.operations[0]).toMatchObject({ slideSize: { cx: 7560000, cy: 10692000 } })
  view.dispose()
})

it('keeps preset orientation changes in the single PPTX draft and restores them with undo and redo', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  setRibbonValue(shell.editor, 'slideSize', 'A4')
  expect(draft.operations[0]).toMatchObject({ slideSize: { cx: 10692000, cy: 7560000 } })
  setRibbonValue(shell.editor, 'slideOrientation', 'portrait')
  expect(draft.operations[0]).toMatchObject({ slideSize: { cx: 7560000, cy: 10692000 } })
  setRibbonValue(shell.editor, 'slideSize', 'A3')
  expect(draft.operations[0]).toMatchObject({ slideSize: { cx: 10692000, cy: 15120000 } })
  setRibbonValue(shell.editor, 'slideOrientation', 'landscape')
  expect(draft.operations[0]).toMatchObject({ slideSize: { cx: 15120000, cy: 10692000 } })
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(shell.editor.querySelector<HTMLSelectElement>('[data-command="slideOrientation"]')!.value).toBe('portrait')
  expect(draft.operations[0]).toMatchObject({ slideSize: { cx: 10692000, cy: 15120000 } })
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  expect(shell.editor.querySelector<HTMLSelectElement>('[data-command="slideOrientation"]')!.value).toBe('landscape')
  view.dispose()
})

it('unlocks preset and orientation controls after a failed PPTX save', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })),
    save: vi.fn(async () => { throw Error('网络故障') }) }
  const { shell, view } = await openDraft(draft, api)
  setRibbonValue(shell.editor, 'slideSize', 'A4')
  shell.save.click()
  await vi.waitFor(() => expect(shell.statusLabel.textContent).toBe('保存失败'))
  expect(shell.editor.querySelector<HTMLSelectElement>('[data-command="slideSize"]')!.disabled).toBe(false)
  expect(shell.editor.querySelector<HTMLSelectElement>('[data-command="slideOrientation"]')!.disabled).toBe(false)
  setRibbonValue(shell.editor, 'slideOrientation', 'portrait')
  expect(draft.operations[0]).toMatchObject({ slideSize: { cx: 7560000, cy: 10692000 } })
  view.dispose()
})

it.each([
  ['16:9', 6858000, 12192000], ['4:3', 6858000, 9144000],
  ['A4', 7560000, 10692000], ['A3', 10692000, 15120000],
] as const)('retains restored portrait orientation when selecting the %s preset', async (preset, cx, cy) => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  draft.setOperations([{ kind: 'editSlides', slideSize: { cx: 7560000, cy: 10692000 } }])
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  expect(shell.editor.querySelector<HTMLSelectElement>('[data-command="slideSize"]')!.value).toBe('A4')
  setRibbonValue(shell.editor, 'slideSize', preset)
  expect(draft.operations[0]).toMatchObject({ slideSize: { cx, cy } })
  expect(shell.editor.querySelector<HTMLSelectElement>('[data-command="slideOrientation"]')!.value).toBe('portrait')
  view.dispose()
})

it('restores a failed PPTX size draft before later text edits and retries without losing size', async () => {
  const store = draftStore()
  let sequence = 0
  const newDraft = () => new NativeDraft(draftIdentity, store, () => `request-${++sequence}`)
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })),
    save: vi.fn().mockRejectedValueOnce(new Error('network unavailable')).mockRejectedValueOnce(new Error('network unavailable')).mockResolvedValue({ revision: 2, revisionRegistered: true,
      artifacts: { pptx: { downloadUrl: '/saved.pptx' } }, validation: { issues: [] } }) }
  const firstDraft = newDraft()
  const first = await openDraft(firstDraft, api)
  setRibbonValue(first.shell.editor, 'slideSize', '4:3')
  expect(firstDraft.operations[0]).toMatchObject({ kind: 'editSlides', slideSize: { cx: 9144000, cy: 6858000 } })
  first.shell.save.click()
  await vi.waitFor(() => expect(first.shell.statusLabel.textContent).toBe('保存失败'))
  first.view.dispose()

  const recovered = newDraft()
  const reopened = await openDraft(recovered, api)
  expect(reopened.shell.editor.querySelector<HTMLSelectElement>('[data-command="slideSize"]')!.value).toBe('4:3')
  reopened.shell.save.click()
  await vi.waitFor(() => expect(api.save).toHaveBeenCalledTimes(2))
  expect(api.save.mock.calls[1][0]).toEqual(api.save.mock.calls[0][0])
  await vi.waitFor(() => expect(reopened.shell.save.disabled).toBe(false))
  const text = reopened.shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!
  text.value = '刷新后继续编辑'; text.dispatchEvent(new Event('input'))
  reopened.shell.save.click()
  await vi.waitFor(() => expect(api.save).toHaveBeenCalledTimes(3))
  expect(api.save.mock.calls[2][0].operations[0]).toMatchObject({ slideSize: { cx: 9144000, cy: 6858000 }, edits: [{ slideIndex: 0, elementId: 'title', text: '刷新后继续编辑' }] })
  expect(api.save.mock.calls[2][0].requestId).not.toBe(api.save.mock.calls[0][0].requestId)
  reopened.view.dispose()
})

it('retains restored PPTX size when another edit replaces the saved draft snapshot', async () => {
  const store = draftStore()
  const original = new NativeDraft(draftIdentity, store)
  original.setOperations([{ kind: 'editSlides', slideSize: { cx: 9144000, cy: 6858000 } }])
  const recovered = new NativeDraft(draftIdentity, store)
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })),
    save: vi.fn(async (_request: NativeSaveRequest) => ({ revision: 2, revisionRegistered: true, artifacts: {}, validation: { issues: [] } })) }
  const { shell, view } = await openDraft(recovered, api)
  const text = shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!
  text.value = '刷新后修改'
  text.dispatchEvent(new Event('input'))
  expect(recovered.operations[0]).toMatchObject({ slideSize: { cx: 9144000, cy: 6858000 }, edits: [{ slideIndex: 0, elementId: 'title', text: '刷新后修改' }] })
  shell.save.click()
  await vi.waitFor(() => expect(api.save).toHaveBeenCalledOnce())
  expect(api.save.mock.calls[0][0].operations[0]).toMatchObject({ slideSize: { cx: 9144000, cy: 6858000 }, edits: [{ text: '刷新后修改', slideIndex: 0, elementId: 'title' }] })
  view.dispose()
})

it('restores all supported PPTX editSlides fields without rewriting an unchanged recovery request', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const operation = { kind: 'editSlides', edits: [{ slideIndex: 0, elementId: 'title', text: '恢复正文', geometry: { x: 30, y: 40, width: 310, height: 90 } }],
    order: [0], theme: 'modern', slideSize: { cx: 9144000, cy: 6858000 },
    textFormatting: [{ slideIndex: 0, elementId: 'title', bold: true, fontSizePt: 24 }],
    paragraphFormatting: [{ slideIndex: 0, elementId: 'title', align: 'center' }],
    transitions: [{ slideIndex: 0, kind: 'wipe' }],
    animations: [{ slideIndex: 0, elementId: 'title', effect: 'flyIn', trigger: 'afterPrev', durationMs: 900, delayMs: 150, direction: 'right', append: true }],
    slideLayouts: [{ slideIndex: 0, layoutPath: 'ppt/slideLayouts/layout2.xml' }],
    backgrounds: [{ slideIndex: 0, color: '#123456' }],
    textBoxes: [{ slideIndex: 0, text: '恢复文本框', geometry: { x: 30, y: 40, width: 180, height: 30 }, fontSize: 28, fontFamily: 'Arial', color: '#123456' }],
    deletions: [{ slideIndex: 0, elementId: 'old-shape' }] }
  draft.setOperations([operation])
  const source = { ...deck, layouts: [{ path: 'ppt/slideLayouts/layout2.xml', name: '标题', layoutType: 'title', placeholders: [] }],
    slides: [{ ...deck.slides[0], elements: [...deck.slides[0].elements, { id: 'old-shape', type: 'shape', name: '旧对象', editable: true, deletable: true, text: '' }] }] }
  let saves = 0
  const api = { preview: vi.fn(async () => ({ model: source })), renderTree: vi.fn(async () => ({ slides: [] })),
    save: vi.fn(async (_request: NativeSaveRequest) => ({ revision: 2, revisionRegistered: ++saves > 1, artifacts: {}, validation: { issues: [] } })) }
  const { shell, view } = await openDraft(draft, api)
  expect(shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!.value).toBe('恢复正文')
  expect(shell.editor.querySelector<HTMLInputElement>('.geometry-grid [name="x"]')!.value).toBe('30')
  expect(shell.editor.querySelector<HTMLButtonElement>('[data-command="bold"]')!.getAttribute('aria-pressed')).toBe('true')
  expect(shell.editor.querySelector<HTMLSelectElement>('[data-command="transition"]')!.value).toBe('wipe')
  expect(shell.editor.querySelector<HTMLSelectElement>('[data-command="animationDirection"]')!.value).toBe('right')
  expect(shell.editor.querySelector<HTMLInputElement>('[aria-label="新增文本内容"]')!.value).toBe('恢复文本框')
  expect(shell.editor.querySelector<HTMLOptionElement>('#object-select option[value="old-shape"]')).toBeNull()
  shell.save.click()
  await vi.waitFor(() => expect(api.save).toHaveBeenCalledOnce())
  expect(api.save.mock.calls[0][0].operations).toEqual([operation])
  await vi.waitFor(() => expect(shell.save.disabled).toBe(false))
  const text = shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!
  text.value = '恢复后再次修改'; text.dispatchEvent(new Event('input'))
  expect(draft.operations[0]).toEqual({ ...operation, edits: [{ ...operation.edits[0], text: '恢复后再次修改' }] })
  shell.save.click()
  await vi.waitFor(() => expect(api.save).toHaveBeenCalledTimes(2))
  expect(api.save.mock.calls[1][0].operations).toEqual(draft.operations)
  view.dispose()
})

it('retains successive supported formatting records when editing a recovered PPTX object', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  draft.setOperations([{ kind: 'editSlides',
    edits: [{ slideIndex: 0, elementId: 'title', text: '恢复正文' }, { slideIndex: 0, elementId: 'title', geometry: { x: 40, y: 50, width: 300, height: 80 } }],
    textFormatting: [{ slideIndex: 0, elementId: 'title', bold: true }, { slideIndex: 0, elementId: 'title', fontSizePt: 24 }],
    paragraphFormatting: [{ slideIndex: 0, elementId: 'title', align: 'right' }, { slideIndex: 0, elementId: 'title', lineSpacingPct: 150 }] }])
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  expect(shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!.value).toBe('恢复正文')
  expect(shell.editor.querySelector<HTMLButtonElement>('[data-command="bold"]')!.getAttribute('aria-pressed')).toBe('true')
  setRibbonValue(shell.editor, 'slideSize', '4:3')
  expect(draft.operations[0]).toMatchObject({ edits: [{ slideIndex: 0, elementId: 'title', text: '恢复正文', geometry: { x: 40, y: 50, width: 300, height: 80 } }],
    textFormatting: [{ slideIndex: 0, elementId: 'title', bold: true, fontSizePt: 24 }],
    paragraphFormatting: [{ slideIndex: 0, elementId: 'title', align: 'right' }, { slideIndex: 0, elementId: 'title', lineSpacingPct: 150 }] })
  view.dispose()
})

it('preserves unknown recovery fields even if a newer preview service accepts them', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const operations = [{ kind: 'editSlides', futureOperation: true }]
  draft.setOperations(operations)
  const api = { preview: vi.fn(async () => ({ model: deck })) }
  await expect(openDraft(draft, api)).rejects.toThrow('草稿已保留')
  expect(draft.operations).toEqual(operations)
})

it('preserves a rejected restored PPTX draft instead of replacing it with a fresh empty view', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const operations = [{ kind: 'editSlides', futureOperation: true }]
  draft.setOperations(operations)
  const api = { preview: vi.fn().mockRejectedValue(new Error('草稿操作不受支持')) }
  await expect(openDraft(draft, api)).rejects.toThrow('草稿操作不受支持')
  expect(api.preview).toHaveBeenCalledWith({ expectedSha256: deck.sha256, operations })
  expect(draft.operations).toEqual(operations)
})

it('uses the existing NativeDraft history for PPTX size and later text undo/redo', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  setRibbonValue(shell.editor, 'slideSize', '4:3')
  const text = shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!
  text.value = '稍后修改'; text.dispatchEvent(new Event('input'))
  const undo = shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!
  const redo = shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!
  undo.click()
  expect(text.value).toBe('原文')
  expect(draft.operations[0]).toMatchObject({ slideSize: { cx: 9144000, cy: 6858000 } })
  undo.click()
  expect(draft.operations).toEqual([])
  expect(shell.editor.querySelector<HTMLSelectElement>('[data-command="slideSize"]')!.value).toBe('')
  expect(undo.disabled).toBe(true)
  redo.click(); redo.click()
  expect(text.value).toBe('稍后修改')
  expect(shell.editor.querySelector<HTMLSelectElement>('[data-command="slideSize"]')!.value).toBe('4:3')
  expect(redo.disabled).toBe(true)
  view.dispose()
})

it('locks PPTX draft history during save and restores it after a failed request', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  let failSave!: (error: Error) => void
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })),
    save: vi.fn(() => new Promise((_resolve, reject) => { failSave = reject })) }
  const { shell, view } = await openDraft(draft, api)
  setRibbonValue(shell.editor, 'slideSize', '4:3')
  const undo = shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!
  const redo = shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!
  expect(undo.disabled).toBe(false)
  shell.save.click()
  expect(undo.disabled).toBe(true)
  expect(redo.disabled).toBe(true)
  failSave(new Error('故障注入'))
  await vi.waitFor(() => expect(shell.statusLabel.textContent).toBe('保存失败'))
  expect(undo.disabled).toBe(false)
  undo.click()
  expect(draft.operations).toEqual([])
  view.dispose()
})

it('PPTX format deletion clears every target patch and preserves other object formats when saving', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const source = { ...deck, slides: [{ ...deck.slides[0], elements: [
    { ...deck.slides[0].elements[0], deletable: true },
    { ...deck.slides[0].elements[0], id: 'keep', name: '保留对象' },
  ] }] }
  const api = { preview: vi.fn(async () => ({ model: source })), renderTree: vi.fn(async () => ({ slides: [] })),
    save: vi.fn(async (_request: NativeSaveRequest) => ({ revision: 2, revisionRegistered: true, artifacts: {}, validation: { issues: [] } })) }
  const { shell, view } = await openDraft(draft, api)
  const object = shell.editor.querySelector<HTMLSelectElement>('#object-select')!
  object.value = 'keep'; object.dispatchEvent(new Event('change'))
  shell.editor.querySelector<HTMLButtonElement>('[data-command="bold"]')!.click()
  shell.editor.querySelector<HTMLButtonElement>('[data-command="paragraphAlignRight"]')!.click()
  object.value = 'title'; object.dispatchEvent(new Event('change'))
  setRibbonValue(shell.editor, 'fontSize', '32')
  shell.editor.querySelector<HTMLButtonElement>('[data-command="paragraphAlignCenter"]')!.click()
  const text = shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!
  text.value = '待删除文字'; text.dispatchEvent(new Event('input'))
  shell.editor.querySelector<HTMLButtonElement>('[data-command="addAnimation"]')!.click()
  shell.editor.querySelector<HTMLButtonElement>('.object-delete')!.click()
  const expected = { textFormatting: [{ slideIndex: 0, elementId: 'keep', bold: true }],
    paragraphFormatting: [{ slideIndex: 0, elementId: 'keep', align: 'right' }],
    deletions: [{ slideIndex: 0, elementId: 'title' }], edits: [], animations: [] }
  expect(draft.operations[0]).toMatchObject(expected)
  shell.save.click()
  await vi.waitFor(() => expect(api.save).toHaveBeenCalledOnce())
  expect(api.save.mock.calls[0][0].operations[0]).toMatchObject(expected)
  await vi.waitFor(() => expect(shell.statusLabel.textContent).toBe('已保存'))
  view.dispose()
})

it('PPTX alignment clears all pressed buttons when undo restores an unspecified source alignment', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  const center = shell.editor.querySelector<HTMLButtonElement>('[data-command="paragraphAlignCenter"]')!
  center.click()
  expect(center.getAttribute('aria-pressed')).toBe('true')
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(draft.operations).toEqual([])
  for (const command of ['paragraphAlignLeft', 'paragraphAlignCenter', 'paragraphAlignRight', 'paragraphAlignJustify']) {
    expect(shell.editor.querySelector<HTMLButtonElement>(`[data-command="${command}"]`)!.getAttribute('aria-pressed')).toBe('false')
  }
  view.dispose()
})

it('PPTX alignment clears the previous selection when switching to an object without explicit alignment', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const source = { ...deck, slides: [{ ...deck.slides[0], elements: [
    { ...deck.slides[0].elements[0], paragraphAlignments: ['center'] },
    { ...deck.slides[0].elements[0], id: 'unspecified', paragraphAlignments: [null] },
  ] }] }
  const api = { preview: vi.fn(async () => ({ model: source })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  expect(shell.editor.querySelector<HTMLButtonElement>('[data-command="paragraphAlignCenter"]')!.getAttribute('aria-pressed')).toBe('true')
  const object = shell.editor.querySelector<HTMLSelectElement>('#object-select')!
  object.value = 'unspecified'; object.dispatchEvent(new Event('change'))
  for (const command of ['paragraphAlignLeft', 'paragraphAlignCenter', 'paragraphAlignRight', 'paragraphAlignJustify']) {
    expect(shell.editor.querySelector<HTMLButtonElement>(`[data-command="${command}"]`)!.getAttribute('aria-pressed')).toBe('false')
  }
  expect(draft.operations).toEqual([])
  view.dispose()
})

it('commits custom dimensions atomically and restores them through history and refresh', async () => {
  const store = draftStore()
  const draft = new NativeDraft(draftIdentity, store)
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  shell.editor.querySelector<HTMLButtonElement>('[data-command="customSlideSize"]')!.click()
  const dialog = shell.editor.querySelector<HTMLDialogElement>('dialog')!
  const width = dialog.querySelector<HTMLInputElement>('[aria-label="Slide Width"]')!
  const height = dialog.querySelector<HTMLInputElement>('[aria-label="Slide Height"]')!
  width.value = '0'; height.value = '20'
  dialog.querySelector<HTMLButtonElement>('[data-command="applyCustomSlideSize"]')!.click()
  expect(dialog.querySelector('[role="alert"]')!.textContent).toContain('1–56')
  expect(draft.operations).toEqual([])
  width.value = '30,5'
  dialog.querySelector<HTMLButtonElement>('[data-command="applyCustomSlideSize"]')!.click()
  expect(dialog.isConnected).toBe(false)
  expect(draft.operations[0]).toMatchObject({ slideSize: { cx: 10980000, cy: 7200000 } })
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(draft.operations).toEqual([])
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  expect(draft.operations[0]).toMatchObject({ slideSize: { cx: 10980000, cy: 7200000 } })
  view.dispose()
  const recovered = new NativeDraft(draftIdentity, store)
  const reopened = await openDraft(recovered, api)
  reopened.shell.editor.querySelector<HTMLButtonElement>('[data-command="customSlideSize"]')!.click()
  expect(reopened.shell.editor.querySelector<HTMLInputElement>('[aria-label="Slide Width"]')!.value).toBe('30.5')
  expect(reopened.shell.editor.querySelector<HTMLInputElement>('[aria-label="Slide Height"]')!.value).toBe('20')
  reopened.view.dispose()
  expect(reopened.shell.editor.querySelector('dialog')).toBeNull()
})

it('cancels custom dimensions without edits and explains unavailable new-document defaults', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  shell.editor.querySelector<HTMLButtonElement>('[data-command="customSlideSize"]')!.click()
  shell.editor.querySelector<HTMLInputElement>('[aria-label="Slide Width"]')!.value = '42'
  shell.editor.querySelector<HTMLButtonElement>('[data-command="cancelCustomSlideSize"]')!.click()
  expect(draft.operations).toEqual([])
  const defaults = shell.editor.querySelector<HTMLButtonElement>('[data-command="defaultSlideSize"]')!
  expect(defaults.dataset.sourceAction).toBe('saveDefaultNewSlideSize')
  expect(shell.editor.querySelector<HTMLButtonElement>('[data-command="customSlideSize"]')!.dataset.sourceAction).toBe('onCustomSlideSize')
  expect(defaults.disabled).toBe(true)
  expect(defaults.title).toContain('新建空白')
  view.dispose()
})

it('refreshes preset and orientation state immediately after applying portrait custom dimensions', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  setRibbonValue(shell.editor, 'slideSize', 'A4')
  const preset = shell.editor.querySelector<HTMLSelectElement>('[data-command="slideSize"]')!
  const orientation = shell.editor.querySelector<HTMLSelectElement>('[data-command="slideOrientation"]')!
  expect(preset.value).toBe('A4')
  expect(orientation.value).toBe('landscape')
  shell.editor.querySelector<HTMLButtonElement>('[data-command="customSlideSize"]')!.click()
  shell.editor.querySelector<HTMLInputElement>('[aria-label="Slide Width"]')!.value = '20'
  shell.editor.querySelector<HTMLInputElement>('[aria-label="Slide Height"]')!.value = '30.5'
  shell.editor.querySelector<HTMLButtonElement>('[data-command="applyCustomSlideSize"]')!.click()
  expect(draft.operations[0]).toMatchObject({ slideSize: { cx: 7200000, cy: 10980000 } })
  expect(preset.value).toBe('')
  expect(orientation.value).toBe('portrait')
  expect(orientation.disabled).toBe(false)
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(preset.value).toBe('A4')
  expect(orientation.value).toBe('landscape')
  expect(orientation.disabled).toBe(false)
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  expect(preset.value).toBe('')
  expect(orientation.value).toBe('portrait')
  expect(orientation.disabled).toBe(false)
  view.dispose()
})


it('does not label custom dimensions as a preset just because the aspect ratio matches', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  draft.setOperations([{ kind: 'editSlides', slideSize: { cx: 10000000, cy: 5625000 } }])
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  expect(shell.editor.querySelector<HTMLSelectElement>('[data-command="slideSize"]')!.value).toBe('')
  setRibbonValue(shell.editor, 'slideOrientation', 'portrait')
  expect(draft.operations[0]).toMatchObject({ slideSize: { cx: 5625000, cy: 10000000 } })
  view.dispose()
})

function enterSpacing(host: HTMLElement, command: string, value: string) {
  const input = host.querySelector<HTMLInputElement>(`[data-command="${command}"]`)!
  input.value = value
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
}

it('PPTX paragraph spacing retains explicit ordered fields and shares alignment history and refresh', async () => {
  const store = draftStore()
  const draft = new NativeDraft(draftIdentity, store)
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  enterSpacing(shell.editor, 'spaceBeforePt', '12,5')
  setRibbonValue(shell.editor, 'lineSpacingPct', '150')
  shell.editor.querySelector<HTMLButtonElement>('[data-command="paragraphAlignCenter"]')!.click()
  enterSpacing(shell.editor, 'spaceAfterPt', '0')
  const target = { slideIndex: 0, elementId: 'title' }
  const expected = [{ ...target, spaceBeforePt: 12.5 }, { ...target, lineSpacingPct: 150 }, { ...target, align: 'center' }, { ...target, spaceAfterPt: 0 }]
  expect(draft.operations[0]).toMatchObject({ paragraphFormatting: expected })
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  const beforeAfterEdit = expected.slice(0, -1)
  expect(draft.operations[0]).toMatchObject({ paragraphFormatting: beforeAfterEdit })
  expect((draft.operations[0] as any).paragraphFormatting[0]).not.toHaveProperty('spaceAfterPt')
  expect(shell.editor.querySelector<HTMLInputElement>('[data-command="spaceAfterPt"]')!.value).toBe('')
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  expect(draft.operations[0]).toMatchObject({ paragraphFormatting: expected })
  view.dispose()
  const reopened = await openDraft(new NativeDraft(draftIdentity, store), api)
  expect(reopened.shell.editor.querySelector<HTMLInputElement>('[data-command="spaceBeforePt"]')!.value).toBe('12.5')
  expect(reopened.shell.editor.querySelector<HTMLSelectElement>('[data-command="lineSpacingPct"]')!.value).toBe('150')
  reopened.view.dispose()
})

it('PPTX paragraph spacing shows mixed, unset and alternate units honestly and rejects invalid input without mutation', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const source = { ...deck, slides: [{ ...deck.slides[0], elements: [
    { ...deck.slides[0].elements[0], paragraphFormatting: [{ lineSpacingPct: 150, spaceBeforePt: 10 }, { lineSpacingPct: 200, spaceBeforePt: 20 }] },
    { ...deck.slides[0].elements[0], id: 'other', paragraphFormatting: [{ lineSpacingPt: 24, spaceBeforePct: 100 }] },
    { ...deck.slides[0].elements[0], id: 'readonly', editable: false, deletable: true },
  ] }] }
  const api = { preview: vi.fn(async () => ({ model: source })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  const before = shell.editor.querySelector<HTMLInputElement>('[data-command="spaceBeforePt"]')!
  const line = shell.editor.querySelector<HTMLSelectElement>('[data-command="lineSpacingPct"]')!
  expect(before.value).toBe(''); expect(line.value).toBe('')
  expect(before.placeholder).toContain('混合值')
  for (const value of ['', '-1', '501', 'NaN', 'Infinity', '1,2,3', '1e2']) enterSpacing(shell.editor, 'spaceBeforePt', value)
  expect(draft.operations).toEqual([])
  setRibbonValue(shell.editor, 'lineSpacingPct', '115')
  enterSpacing(shell.editor, 'spaceBeforePt', '500')
  const object = shell.editor.querySelector<HTMLSelectElement>('#object-select')!
  object.value = 'other'; object.dispatchEvent(new Event('change'))
  expect(before.value).toBe(''); expect(line.value).toBe('')
  enterSpacing(shell.editor, 'spaceAfterPt', '3.25')
  expect(draft.operations[0]).toMatchObject({ paragraphFormatting: [
    { slideIndex: 0, elementId: 'title', lineSpacingPct: 115 },
    { slideIndex: 0, elementId: 'title', spaceBeforePt: 500 },
    { slideIndex: 0, elementId: 'other', spaceAfterPt: 3.25 },
  ] })
  object.value = 'readonly'; object.dispatchEvent(new Event('change'))
  const snapshot = JSON.stringify(draft.operations)
  expect(before.disabled).toBe(true); expect(line.disabled).toBe(true)
  enterSpacing(shell.editor, 'spaceBeforePt', '7')
  expect(JSON.stringify(draft.operations)).toBe(snapshot)
  view.dispose()
})

it('retains every ordered list command across undo, redo, selection changes and draft refresh', async () => {
  const store = draftStore()
  const draft = new NativeDraft(draftIdentity, store)
  const source = { ...deck, slides: [{ ...deck.slides[0], elements: [
    { ...deck.slides[0].elements[0], paragraphLists: [{ level: 0, rtl: null }, { level: 8, rtl: null }] },
    { ...deck.slides[0].elements[0], id: 'other', paragraphLists: [{ bulletKind: 'none', rtl: null }] },
  ] }] }
  const api = { preview: vi.fn(async () => ({ model: source })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  const button = (command: string) => shell.editor.querySelector<HTMLButtonElement>(`[data-command="${command}"]`)!
  expect(button('directionLtr').getAttribute('aria-pressed')).toBe('false')
  expect(shell.editor.querySelector<HTMLInputElement>('[data-command="startAt"]')!.disabled).toBe(true)
  button('indentIncrease').click(); button('indentDecrease').click()
  setRibbonValue(shell.editor, 'bulletCharPreset', '2')
  setRibbonValue(shell.editor, 'bulletSizePct', '125')
  button('directionRtl').click()
  const target = { slideIndex: 0, elementId: 'title' }
  const expected = [{ ...target, indentDelta: 1 }, { ...target, indentDelta: -1 }, { ...target, bullet: 'char', bulletChar: '§', bulletFont: 'Wingdings' }, { ...target, bulletSizePct: 125 }, { ...target, rtl: true }]
  expect((draft.operations[0] as any).paragraphFormatting).toEqual(expected)
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(button('directionRtl').getAttribute('aria-pressed')).toBe('false')
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  expect(button('directionRtl').getAttribute('aria-pressed')).toBe('true')
  const select = shell.editor.querySelector<HTMLSelectElement>('#object-select')!
  select.value = 'other'; select.dispatchEvent(new Event('change'))
  expect(shell.editor.querySelector<HTMLSelectElement>('[data-command="bulletCharPreset"]')!.value).toBe('')
  expect(shell.editor.querySelector<HTMLSelectElement>('[data-command="bulletSizePct"]')!.disabled).toBe(true)
  view.dispose()
  const recoveredDraft = new NativeDraft(draftIdentity, store)
  const reopened = await openDraft(recoveredDraft, api)
  expect((recoveredDraft.operations[0] as any).paragraphFormatting).toEqual(expected)
  expect(reopened.shell.editor.querySelector<HTMLSelectElement>('[data-command="bulletCharPreset"]')!.value).toBe('2')
  expect(reopened.shell.editor.querySelector<HTMLSelectElement>('[data-command="bulletSizePct"]')!.value).toBe('125')
  expect(reopened.shell.editor.querySelector<HTMLButtonElement>('[data-command="directionRtl"]')!.getAttribute('aria-pressed')).toBe('true')
  reopened.view.dispose()
})

it('rejects overflowing list proposals before history persistence and keeps the valid draft reopenable', async () => {
  const store = draftStore(); const draft = new NativeDraft(draftIdentity, store)
  const source = { ...deck, slides: [{ ...deck.slides[0], elements: [{ ...deck.slides[0].elements[0], paragraphLists: [{ bulletKind: 'char', bulletChar: '•', level: 0, indentEmu: -285750, marLEmu: 285750, hasExplicitHangingIndent: true }] }] }] }
  const api = { preview: vi.fn(async () => ({ model: source })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  enterSpacing(shell.editor, 'bulletHangPx', '5376')
  const before = JSON.stringify(draft.operations)
  const history = vi.spyOn(draft, 'setOperations')
  shell.editor.querySelector<HTMLButtonElement>('[data-command="indentIncrease"]')!.click()
  expect(history).not.toHaveBeenCalled()
  expect(JSON.stringify(draft.operations)).toBe(before)
  expect(shell.editor.textContent).toContain('超出 OOXML 范围')
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(draft.operations).toEqual([])
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  expect(JSON.stringify(draft.operations)).toBe(before)
  view.dispose()
  const recovered = new NativeDraft(draftIdentity, store)
  const reopened = await openDraft(recovered, api)
  expect(JSON.stringify(recovered.operations)).toBe(before)
  reopened.view.dispose()
})

it('rejects a previously stored overflowing list sequence without rewriting its draft', async () => {
  const store = draftStore(); const draft = new NativeDraft(draftIdentity, store)
  const target = { slideIndex: 0, elementId: 'title' }
  const operations = [{ kind: 'editSlides', paragraphFormatting: [{ ...target, bullet: 'char', bulletHangEmu: 51206400 }, { ...target, indentDelta: 1 }, { ...target, indentDelta: -1 }] }]
  draft.setOperations(operations)
  const source = { ...deck, slides: [{ ...deck.slides[0], elements: [{ ...deck.slides[0].elements[0], paragraphLists: [{ level: 0, hasExplicitHangingIndent: false }] }] }] }
  const api = { preview: vi.fn(async () => ({ model: source })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const writes = vi.spyOn(draft, 'setOperations')
  await expect(openDraft(draft, api)).rejects.toThrow('原草稿已保留')
  expect(writes).not.toHaveBeenCalled()
  expect(draft.operations).toEqual(operations)
  expect(new NativeDraft(draftIdentity, store).operations).toEqual(operations)
})

it('does not create an undo step when Enter repeats an absolute paragraph value', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  shell.editor.querySelector<HTMLButtonElement>('[data-command="indentDecrease"]')!.click()
  expect(draft.operations).toEqual([])
  enterSpacing(shell.editor, 'spaceBeforePt', '12.5')
  const before = JSON.stringify(draft.operations)
  const writes = vi.spyOn(draft, 'setOperations')
  for (let index = 0; index < 501; index++) enterSpacing(shell.editor, 'spaceBeforePt', '12,5')
  expect(writes).not.toHaveBeenCalled()
  expect(JSON.stringify(draft.operations)).toBe(before)
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(draft.operations).toEqual([])
  view.dispose()
})

it('undoes the preceding real paragraph edit after repeating an earlier field value', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  enterSpacing(shell.editor, 'spaceBeforePt', '12.5')
  enterSpacing(shell.editor, 'spaceAfterPt', '0')
  const writes = vi.spyOn(draft, 'setOperations')
  enterSpacing(shell.editor, 'spaceBeforePt', '12.5')
  expect(writes).not.toHaveBeenCalled()
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(shell.editor.querySelector<HTMLInputElement>('[data-command="spaceAfterPt"]')!.value).toBe('')
  expect(shell.editor.querySelector<HTMLInputElement>('[data-command="spaceBeforePt"]')!.value).toBe('12.5')
  view.dispose()
})

it('refuses the 501st real paragraph edit without changing persistence or history', async () => {
  const store = draftStore(); const draft = new NativeDraft(draftIdentity, store)
  const target = { slideIndex: 0, elementId: 'title' }
  draft.setOperations([{ kind: 'editSlides', paragraphFormatting: Array.from({ length: 499 }, (_, i) => ({ ...target, spaceBeforePt: i % 2 })) }])
  const api = { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const { shell, view } = await openDraft(draft, api)
  enterSpacing(shell.editor, 'spaceBeforePt', '2')
  expect((draft.operations[0] as any).paragraphFormatting).toHaveLength(500)
  const snapshot = JSON.stringify(draft.operations)
  const writes = vi.spyOn(draft, 'setOperations')
  enterSpacing(shell.editor, 'spaceBeforePt', '3')
  expect(writes).not.toHaveBeenCalled()
  expect(JSON.stringify(draft.operations)).toBe(snapshot)
  expect(shell.editor.textContent).toContain('请先保存并打开新修订')
  expect(shell.editor.querySelector<HTMLInputElement>('[data-command="spaceBeforePt"]')!.value).toBe('2')
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect((draft.operations[0] as any).paragraphFormatting).toHaveLength(499)
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  expect(JSON.stringify(draft.operations)).toBe(snapshot)
  view.dispose()
  const recovered = new NativeDraft(draftIdentity, store)
  const reopened = await openDraft(recovered, api)
  expect(JSON.stringify(recovered.operations)).toBe(snapshot)
  reopened.view.dispose()
})


it('applies the current source/pending transition once to source identities across reorder and recovery', async () => {
  const store = draftStore(), draft = new NativeDraft(draftIdentity, store)
  draft.setOperations([{ kind: 'editSlides', order: [2, 0, 1], transitions: [{ slideIndex: 0, kind: 'wipe' }] }])
  const source = { ...deck, slides: [
    { ...deck.slides[0], transition: 'fade' },
    { ...deck.slides[0], slideIndex: 1, transition: 'push' },
    { ...deck.slides[0], slideIndex: 2, transition: 'none' },
  ] }
  const api = { preview: vi.fn(async () => ({ model: source })), renderTree: vi.fn(async () => ({ slides: [] })),
    save: vi.fn(async (_request: NativeSaveRequest) => ({ revision: 2, revisionRegistered: true, artifacts: {}, validation: { issues: [] } })) }
  let opened = await openDraft(draft, api)
  const command = opened.shell.editor.querySelector<HTMLButtonElement>('[data-command="applyTransitionAll"]')!
  expect(command.disabled).toBe(false)
  command.click(); command.click()
  expect(draft.operations[0]).toMatchObject({ order: [2, 0, 1], transitions: [{ slideIndex: 2, kind: 'wipe' }, { slideIndex: 0, kind: 'wipe' }, { slideIndex: 1, kind: 'wipe' }] })
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(draft.operations[0].transitions).toEqual([{ slideIndex: 0, kind: 'wipe' }])
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  opened.view.dispose!()
  const recovered = new NativeDraft(draftIdentity, store)
  opened = await openDraft(recovered, api)
  expect(opened.shell.editor.querySelector<HTMLSelectElement>('[data-command="transition"]')!.value).toBe('wipe')
  opened.shell.save.click(); await vi.waitFor(() => expect(api.save).toHaveBeenCalledOnce())
  expect(api.save.mock.calls[0][0].operations[0].transitions).toEqual([{ slideIndex: 2, kind: 'wipe' }, { slideIndex: 0, kind: 'wipe' }, { slideIndex: 1, kind: 'wipe' }])
  expect(opened.shell.editor.querySelector<HTMLButtonElement>('[data-command="applyTransitionAll"]')!.disabled).toBe(true)
  opened.view.dispose!()
})
it('copies the actual source transition without a pending effect or an editable text target', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const source = { ...deck, slides: [{ slideIndex: 0, transitionApplyAllSafe: true, transition: 'push', elements: [], animations: [] }, { slideIndex: 1, transitionApplyAllSafe: true, transition: 'fade', elements: [], animations: [] }] }
  const { shell, view } = await openDraft(draft, { preview: vi.fn(async () => ({ model: source })), renderTree: vi.fn(async () => ({ slides: [] })) })
  shell.editor.querySelector<HTMLButtonElement>('[data-command="applyTransitionAll"]')!.click()
  expect(draft.operations[0].transitions).toEqual([{ slideIndex: 0, kind: 'push' }, { slideIndex: 1, kind: 'push' }])
  view.dispose!()
})
it.each([
  { transitions: [{ slideIndex: 0, kind: 'bad' }] }, { transitions: [{ slideIndex: 8, kind: 'wipe' }] }, { transitions: [{ slideIndex: 0, kind: 'fade', duration: 100 }] },
])('refuses invalid restored transition records while preserving storage %#', async ({ transitions }) => {
  const store = draftStore(), draft = new NativeDraft(draftIdentity, store)
  draft.setOperations([{ kind: 'editSlides', transitions }])
  const recovered = new NativeDraft(draftIdentity, store)
  await expect(openDraft(recovered, { preview: vi.fn(async () => ({ model: deck })), renderTree: vi.fn(async () => ({ slides: [] })) })).rejects.toThrow(/转场草稿/)
  expect(new NativeDraft(draftIdentity, store).operations).toEqual(draft.operations)
})

it.each([{ order: [0] }, { order: [0, 0, 1] }, { order: [0, -1, 2] }, { order: [] }])('refuses an invalid restored source permutation without clearing storage %#', async ({ order }) => {
  const store = draftStore(), draft = new NativeDraft(draftIdentity, store)
  draft.setOperations([{ kind: 'editSlides', order }])
  const source = { ...deck, slides: [deck.slides[0], { ...deck.slides[0], slideIndex: 1 }, { ...deck.slides[0], slideIndex: 2 }] }
  await expect(openDraft(new NativeDraft(draftIdentity, store), { preview: vi.fn(async () => ({ model: source })), renderTree: vi.fn(async () => ({ slides: [] })) })).rejects.toThrow(/草稿页面顺序/)
  expect(new NativeDraft(draftIdentity, store).operations).toEqual(draft.operations)
})

it('bounds Apply to All at 500 pages without clearing earlier changes on an invalid request', async () => {
  const { applyTransitionToAll, restoredTransitions } = await import('./slides-transitions')
  const changes = new Map<number, import('./slides-transitions').SlideTransition>([[9, 'wipe']])
  expect(() => applyTransitionToAll(Array.from({ length: 501 }, (_, i) => i), 'fade', changes)).toThrow()
  expect([...changes]).toEqual([[9, 'wipe']])
  expect(applyTransitionToAll(Array.from({ length: 500 }, (_, i) => i), 'fade', changes)).toBe(true)
  expect(changes.size).toBe(500)
  expect(applyTransitionToAll(Array.from({ length: 500 }, (_, i) => i), 'fade', changes)).toBe(false)
  const records = [...changes].map(([slideIndex, kind]) => ({ slideIndex, kind }))
  expect(restoredTransitions(records, 500)).toHaveLength(500)
  expect(() => restoredTransitions([...records, { slideIndex: 500, kind: 'fade' }], 501)).toThrow()
})

it('restores ordered absolute transition records with last-write semantics without rewriting storage', async () => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const transitions = [{ slideIndex: 0, kind: 'fade' }, { slideIndex: 0, kind: 'wipe' }]
  draft.setOperations([{ kind: 'editSlides', transitions }])
  const source = { ...deck, slides: [deck.slides[0], { ...deck.slides[0], slideIndex: 1, transition: 'push' }] }
  const { shell, view } = await openDraft(draft, { preview: vi.fn(async () => ({ model: source })), renderTree: vi.fn(async () => ({ slides: [] })) })
  expect(shell.editor.querySelector<HTMLSelectElement>('[data-command="transition"]')!.value).toBe('wipe')
  expect(draft.operations[0].transitions).toEqual(transitions)
  shell.editor.querySelector<HTMLButtonElement>('[data-command="applyTransitionAll"]')!.click()
  expect(draft.operations[0].transitions).toEqual([{ slideIndex: 0, kind: 'wipe' }, { slideIndex: 1, kind: 'wipe' }])
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(draft.operations[0].transitions).toEqual(transitions)
  view.dispose!()
})

it.each([false, undefined])('disables and refuses Apply to All when any source page has unsafe or unverified metadata %s', async transitionApplyAllSafe => {
  const draft = new NativeDraft(draftIdentity, draftStore())
  const original = { kind: 'editSlides', transitions: [{ slideIndex: 0, kind: 'wipe' }] }
  draft.setOperations([original])
  const source = { ...deck, slides: [deck.slides[0], { ...deck.slides[0], slideIndex: 1, transitionApplyAllSafe }] }
  const { shell, view } = await openDraft(draft, { preview: vi.fn(async () => ({ model: source })), renderTree: vi.fn(async () => ({ slides: [] })) })
  const button = shell.editor.querySelector<HTMLButtonElement>('[data-command="applyTransitionAll"]')!
  expect(button.disabled).toBe(true)
  expect(button.title).toMatch(/声音或效果变体/)
  button.dispatchEvent(new Event('click', { bubbles: true }))
  expect(draft.operations).toEqual([original])
  expect(shell.editor.textContent).toMatch(/未支持的转场/)
  view.dispose!()
})

it.each([true, false])('gates single transition editing separately from bulk metadata eligibility %s', async transitionEditSafe => {
  const store = draftStore(), draft = new NativeDraft(draftIdentity, store)
  const source = { ...deck, slides: [{ ...deck.slides[0], transitionApplyAllSafe: false, transitionEditSafe, transition: 'fade' }] }
  const { shell, view } = await openDraft(draft, { preview: vi.fn(async () => ({ model: source })), renderTree: vi.fn(async () => ({ slides: [] })) })
  const select = shell.editor.querySelector<HTMLSelectElement>('[data-command="transition"]')!
  expect(select.disabled).toBe(!transitionEditSafe)
  expect(shell.editor.querySelector<HTMLButtonElement>('[data-command="applyTransitionAll"]')!.disabled).toBe(true)
  select.value = 'wipe'; select.dispatchEvent(new Event('change', { bubbles: true }))
  if (transitionEditSafe) expect(draft.operations[0].transitions).toEqual([{ slideIndex: 0, kind: 'wipe' }])
  else { expect(draft.operations).toEqual([]); expect(shell.editor.querySelector('.slides-status')?.textContent ?? shell.editor.textContent).toMatch(/不能安全修改/) }
  view.dispose!()
})
it('refuses an unsafe restored source transition without replacing persisted draft', async () => {
  const store = draftStore(), draft = new NativeDraft(draftIdentity, store)
  const operations = [{ kind: 'editSlides', transitions: [{ slideIndex: 0, kind: 'wipe' }] }]
  draft.setOperations(operations)
  const source = { ...deck, slides: [{ ...deck.slides[0], transitionEditSafe: false }] }
  await expect(openDraft(new NativeDraft(draftIdentity, store), { preview: vi.fn(async () => ({ model: source })), renderTree: vi.fn(async () => ({ slides: [] })) })).rejects.toThrow(/原草稿已保留/)
  expect(new NativeDraft(draftIdentity, store).operations).toEqual(operations)
})

it('keeps text and paragraph animation targets coherent in one undo snapshot', async () => {
  const model=structuredClone(deck) as any
  model.slides[0].elements[0].text='one\ntwo\nthree'
  model.slides[0].elements[0].paragraphFormatting=[{}, {}, {}]
  model.slides[0].animations=[0,1,2].map(paragraph=>({spid:2,elementId:'title',effect:'fade',trigger:'onClick',durationMs:500,delayMs:0,paragraph}))
  const draft=new NativeDraft(draftIdentity,draftStore())
  const {shell,view}=await openDraft(draft,{preview:vi.fn(async()=>({model})),renderTree:vi.fn(async()=>({slides:[]}))})
  const text=shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!
  text.value='single';text.dispatchEvent(new Event('input'))
  expect(draft.operations[0]).toMatchObject({edits:[{text:'single'}],animationSequences:[{slideIndex:0,items:[{source:0,spid:2,effect:'fade'}]}]})
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(text.value).toBe('one\ntwo\nthree');expect(draft.operations).toEqual([])
  view.dispose()
})

it('builds By Paragraph animations from pending expanded text rather than source paragraph count', async()=>{
  const draft=new NativeDraft(draftIdentity,draftStore())
  const {shell,view}=await openDraft(draft,{preview:vi.fn(async()=>({model:deck})),renderTree:vi.fn(async()=>({slides:[]}))})
  const text=shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!
  text.value='one\ntwo\nthree';text.dispatchEvent(new Event('input'))
  shell.editor.querySelector<HTMLButtonElement>('[data-command="animationByParagraph"]')!.click()
  shell.editor.querySelector<HTMLButtonElement>('[data-command="addAnimation"]')!.click()
  const operation=draft.operations[0] as any
  expect(operation.animationSequences[0].items.map((item:any)=>item.paragraph)).toEqual([0,1,2])
  view.dispose()
})

it('stages table shading and borders with text edits, history and exact source recovery',async()=>{
  const model=structuredClone(deck) as any
  model.slides[0].elements=[{id:'tbl_1',type:'table',name:'Source table',editable:false,text:'',tableCells:[['a','b'],['c','d']]}]
  const store=draftStore(),draft=new NativeDraft(draftIdentity,store)
  const api={preview:vi.fn(async()=>({model})),renderTree:vi.fn(async()=>({slides:[]}))}
  let {shell,view}=await openDraft(draft,api)
  const shading=shell.editor.querySelector<HTMLSelectElement>('[data-command="tableShading"]')!
  shading.value='#FFF2CC';shading.dispatchEvent(new Event('change',{bubbles:true}))
  shell.editor.querySelector<HTMLButtonElement>('[data-command="tableAllBorders"]')!.click()
  expect(draft.operations[0]).toMatchObject({tableStyles:[{slideIndex:0,elementId:'tbl_1',shadingColor:'#FFF2CC',borderPreset:'all'}]})
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect((draft.operations[0] as any).tableStyles[0]).toEqual({slideIndex:0,elementId:'tbl_1',shadingColor:'#FFF2CC'})
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  view.dispose()
  const recovered=new NativeDraft(draftIdentity,store)
  ;({shell,view}=await openDraft(recovered,api))
  expect(shell.editor.querySelector<HTMLSelectElement>('[data-command="tableShading"]')!.value).toBe('#FFF2CC')
  expect((recovered.operations[0] as any).tableStyles[0].borderPreset).toBe('all')
  view.dispose()
})

it('recovers new paragraph targets against the recovered text snapshot',async()=>{
  const draft=new NativeDraft(draftIdentity,draftStore())
  const operations=[{kind:'editSlides',edits:[{slideIndex:0,elementId:'title',text:'one\ntwo\nthree'}],animationSequences:[{slideIndex:0,items:[{elementId:'title',effect:'fade',trigger:'onClick',durationMs:500,delayMs:0,paragraph:2}]}]}]
  draft.setOperations(operations)
  const {shell,view}=await openDraft(draft,{preview:vi.fn(async()=>({model:deck})),renderTree:vi.fn(async()=>({slides:[]}))})
  expect(shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!.value).toBe('one\ntwo\nthree')
  expect(draft.operations).toEqual(operations);view.dispose()
})
