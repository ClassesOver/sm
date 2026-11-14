import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'
import { NativeDraft } from './native-draft'
const show = vi.hoisted(() => ({ open: vi.fn(() => ({ dispose() {} })) }))
vi.mock('./slides-show', () => ({ openSlidesShow: show.open }))
vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
const views: ReturnType<typeof createSlidesEditorView>[] = []
beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} }))
afterEach(() => { views.splice(0).forEach(v => v.dispose()); document.body.replaceChildren(); vi.unstubAllGlobals(); show.open.mockClear() })

it.each(['startShow', 'startShowCurrent'])('%s读取完整草稿动画/转场和隐藏页，起点按来源语义处理，不保存或改草稿', async command => {
  const source = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [0, 1, 2].map(index => ({ slideIndex: index, hidden: index === 0,
    transition: 'none', transitionEditSafe: true, animations: index === 0 ? [{ spid: 2, elementId: 'a', effect: 'fade', trigger: 'onClick', durationMs: 400, delayMs: 0 }] : [],
    elements: [{ id: 'a', name: '矩形', type: 'shape', text: '', editable: true }] })) }
  const tree = { slides: source.slides.map(s => ({ slideIndex: s.slideIndex, hidden: s.hidden, widthPx: 960, heightPx: 540, background: { kind: 'solid', color: '#fff' }, nodes: [{ id: 'a', sourceId: 'a', type: 'shape', box: { x: 0, y: 0, w: 200, h: 50 } }] })) }
  const draft = new NativeDraft({ documentId: 'show-core', revision: 1, sourceSha256: source.sha256, scope: { database: 'fixture', companyId: 'c', userId: 'u', threadId: 't' } }, { getItem: () => null, setItem() {}, removeItem() {} })
  draft.setOperations([{ kind: 'editSlides', transitions: [{ slideIndex: 2, kind: 'push' }], animations: [{ slideIndex: 0, elementId: 'a', effect: 'pulse', trigger: 'onClick', durationMs: 600, delayMs: 0, append: true }] }])
  const shell = createEditorShell(document.body.appendChild(document.createElement('main')), 'full', 'pptx')
  const preview = { sourceSha256: source.sha256, model: { slides: source.slides.map((s, index) => ({ ...s, transition: index === 2 ? 'push' : 'none', animations: index === 0 ? [...s.animations, { spid: 2, elementId: 'a', effect: 'pulse', trigger: 'onClick', durationMs: 600, delayMs: 0 }] : [] })) } }
  const request = vi.fn(async (path: string, _init?: RequestInit) => path === 'deck' ? source : path === 'preview' ? preview : tree)
  const view = createSlidesEditorView(shell.editor, { native: true, draft, request: request as never, save: shell.save, download: shell.exportPptx }); views.push(view); await view.ready
  const before = JSON.stringify(draft.operations), original = JSON.stringify(source)
  shell.editor.querySelector<HTMLButtonElement>('[data-command="' + command + '"]')!.click()
  await vi.waitFor(() => expect(show.open).toHaveBeenCalledOnce())
  const options = (show.open.mock.calls[0] as any[])[1]
  expect(options.slides).toHaveLength(3); expect(options.slides[0].hidden).toBe(true)
  expect(options.startIndex).toBe(command === 'startShow' ? 1 : 0)
  expect(options.animations[0].map((item: any) => item.effect)).toEqual(['fade', 'pulse'])
  expect(options.transitions).toEqual(['none', 'none', 'push'])
  const sent = JSON.parse(String(request.mock.calls.filter(([path, init]) => path === 'render-tree' && init).at(-1)![1]!.body))
  expect(sent.operations).toEqual(JSON.parse(before)); expect(sent.expectedSha256).toBe(source.sha256)
  expect(request.mock.calls.some(([path]) => path === 'save')).toBe(false)
  expect(JSON.stringify(draft.operations)).toBe(before); expect(JSON.stringify(source)).toBe(original)
})
