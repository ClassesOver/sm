import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createSlidesEditorView } from './slides-main'
import { createEditorShell } from './shell'
import { NativeDraft } from './native-draft'
import type { NativeOperation } from './native-draft'
import { createSlidesNativeRibbon } from './slides-native-ribbon'
import type { SlidesNativeAIClient } from './slides-native-ai'

vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
const views: ReturnType<typeof createSlidesEditorView>[] = []
beforeEach(() => {
  document.documentElement.lang = 'zh-CN'
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
})
afterEach(() => { views.splice(0).forEach(view => view.dispose()); document.body.replaceChildren(); document.documentElement.lang = ''; vi.unstubAllGlobals() })

async function fixture(aiEnabled = true) {
  const source = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [0, 1].map(slideIndex => ({
    slideIndex, elements: [
      { id: 'title', name: '标题', type: 'text', text: '原文' + slideIndex, editable: true, geometry: { x: 20, y: 20, width: 300, height: 80 } },
      { id: 'body', name: '正文', type: 'text', text: '正文' + slideIndex, editable: true, geometry: { x: 20, y: 120, width: 300, height: 80 } },
      { id: 'readonly', name: '只读', type: 'text', text: '不可写内容', editable: false },
    ], animations: [],
  })) }
  const shell = createEditorShell(document.body.appendChild(document.createElement('main')), 'full', 'pptx')
  const draft = new NativeDraft({ documentId: 'preset', revision: 1, sourceSha256: source.sha256, scope: { database: 'fixture', companyId: 'c', userId: 'u', threadId: 't' } }, { getItem: () => null, setItem() {}, removeItem() {} })
  const operations: NativeOperation[] = [{ kind: 'editSlides', edits: [{ slideIndex: 0, elementId: 'title', text: '英文候选' }] }]
  const job = { editId: 'preset-candidate', status: 'succeeded', snapshotSha256: 'b'.repeat(64), proposal: { summary: '翻译候选', operations } }
  const api = { start: vi.fn<SlidesNativeAIClient['start']>(async () => job), status: vi.fn(async () => job), accept: vi.fn(async () => ({ operations })), cancel: vi.fn(async () => ({})), cancelRequest: vi.fn(async () => ({})) }
  const request = vi.fn(async (path: string, _init?: RequestInit) => path === 'deck' ? source : path === 'render-tree' ? { slides: source.slides.map(slide => ({ slideIndex: slide.slideIndex, widthPx: 960, heightPx: 540, nodes: [] })) } : {})
  const view = createSlidesEditorView(shell.editor, { native: true, draft, request: request as never, save: shell.save, download: shell.exportPptx, ...(aiEnabled ? { nativeAI: api } : {}) })
  views.push(view); await view.ready
  const control = <T extends HTMLElement>(selector: string) => shell.editor.querySelector<T>(selector)!
  const translate = (language = 'en') => { const select = control<HTMLSelectElement>('[data-command=translate]'); select.value = language; select.dispatchEvent(new Event('change')) }
  const submit = () => control<HTMLFormElement>('.native-ai-form').dispatchEvent(new Event('submit', { cancelable: true }))
  const write = (text: string) => { const input = control<HTMLTextAreaElement>('#object-text'); input.value = text; input.dispatchEvent(new Event('input', { bubbles: true })) }
  return { shell, draft, api, view, control, translate, submit, write, job, request }
}

it('翻译语言菜单保留源21种语言顺序、中文标签、参数和未接AI的禁用原因', () => {
  const host = document.body.appendChild(document.createElement('div'))
  const actions: unknown[][] = [], ribbon = createSlidesNativeRibbon(host, { onAction: (...action) => actions.push(action) })
  try {
    const translate = host.querySelector<HTMLSelectElement>('select[data-command=translate]')!
    expect(translate).not.toBeNull()
    expect(translate.disabled).toBe(true)
    expect([...translate.options].map(option => [option.value, option.textContent])).toEqual([
      ['', '选择翻译语言…'], ['en', '英语'], ['zh-CN', '简体中文'], ['ja', '日语'], ['ko', '韩语'], ['fr', '法语'], ['de', '德语'], ['es', '西班牙语'], ['th', '泰文'], ['id', '印尼文'], ['ru', '俄文'], ['ar', '阿拉伯文'], ['pt', '葡萄牙文'], ['it', '意大利文'], ['pl', '波兰文'], ['cs', '捷克文'], ['nl', '荷兰文'], ['ms', '马来文'], ['he', '希伯来文'], ['hi', '印地文'], ['zh-TW', '繁体中文'], ['vi', '越南文'],
    ])
    ribbon.setAIEditEnabled(true)
    translate.value = 'ja'; translate.dispatchEvent(new Event('change'))
    expect(actions).toEqual([['translate', 'ja']]); expect(translate.value).toBe('')
    ribbon.setLocked(true); expect(translate.disabled).toBe(true)
    ribbon.setAIEditEnabled(false, '当前会话未启用 AI 编辑'); ribbon.setLocked(false)
    expect(translate.disabled).toBe(true); expect(translate.title).toContain('当前会话未启用 AI 编辑')
  } finally { ribbon.dispose() }
})

it('翻译入口引用本页未失焦草稿，生成真实候选后等待明确采纳并进入同一撤销重做链', async () => {
  const app = await fixture(); app.write('未失焦的人工草稿')
  const before = structuredClone(app.draft.operations)
  app.translate()
  expect(app.view.officeEditAssistant?.panel.hidden).toBe(false)
  expect(app.control<HTMLSelectElement>('[aria-label="AI 授权范围"]').value).toBe('slide')
  expect(app.control<HTMLTextAreaElement>('.slides-native-ai textarea').value).toContain('英语')
  expect(app.control('.native-ai-context').textContent).toContain('未失焦的人工草稿')
  expect(app.api.start).not.toHaveBeenCalled(); expect(app.draft.operations).toEqual(before)
  app.submit(); await vi.waitFor(() => expect(app.control<HTMLElement>('.native-ai-preview').hidden).toBe(false))
  const payload = app.api.start.mock.calls[0]![0] as unknown as Record<string, unknown>
  expect(payload).toMatchObject({ operations: before, scope: 'selection', selection: [{ slideIndex: 0, elementId: 'title' }, { slideIndex: 0, elementId: 'body' }] })
  expect(app.control('.native-ai-preview').textContent).toContain('未失焦的人工草稿 → 英文候选')
  expect(app.draft.operations).toEqual(before)
  app.control<HTMLButtonElement>('.native-ai-accept').click()
  await vi.waitFor(() => expect(app.draft.operations).toEqual(app.job.proposal.operations))
  app.control<HTMLButtonElement>('[data-source-action=onUndo]').click(); expect(app.draft.operations).toEqual(before)
  app.control<HTMLButtonElement>('[data-source-action=onRedo]').click(); expect(app.draft.operations).toEqual(app.job.proposal.operations)
  app.shell.save.click()
  await vi.waitFor(() => expect(app.request.mock.calls.some(([path]) => path === 'save')).toBe(true))
  const saved = app.request.mock.calls.find(([path]) => path === 'save')!
  expect(JSON.parse(saved[1]!.body as string)).toMatchObject({ expectedSha256: 'a'.repeat(64), operations: app.job.proposal.operations })
})

it('拼写检查保留源整稿范围，预填后等待生成并复用现有deck候选路由', async () => {
  const app = await fixture(); app.control<HTMLButtonElement>('[data-command=spelling]').click()
  expect(app.view.officeEditAssistant?.panel.hidden).toBe(false)
  expect(app.control<HTMLSelectElement>('[aria-label="AI 授权范围"]').value).toBe('deck')
  expect(app.control<HTMLTextAreaElement>('.slides-native-ai textarea').value).toContain('错别字、语法和标点')
  expect(app.api.start).not.toHaveBeenCalled()
  app.submit(); await vi.waitFor(() => expect(app.control<HTMLElement>('.native-ai-preview').hidden).toBe(false))
  expect(app.api.start.mock.calls[0]![0]).toMatchObject({ scope: 'deck', selection: [] })
  expect(app.draft.operations).toEqual([])
})

it('未启用AI时两预设入口保持禁用，不能调用候选或改变人工草稿', async () => {
  const app = await fixture(false)
  expect(app.control<HTMLButtonElement>('[data-command=spelling]').disabled).toBe(true)
  expect(app.control<HTMLSelectElement>('[data-command=translate]').disabled).toBe(true)
  app.control<HTMLButtonElement>('[data-command=spelling]').click(); app.translate()
  expect(app.api.start).not.toHaveBeenCalled(); expect(app.draft.operations).toEqual([])
})

it('切换语言废弃旧候选与请求身份，不采纳旧语言并保留新预设', async () => {
  const app = await fixture(); app.translate(); app.submit()
  await vi.waitFor(() => expect(app.control<HTMLElement>('.native-ai-preview').hidden).toBe(false))
  app.translate('ja')
  expect(app.control<HTMLElement>('.native-ai-preview').hidden).toBe(true)
  expect(app.control<HTMLTextAreaElement>('.slides-native-ai textarea').value).toContain('日语')
  expect(app.api.cancel).toHaveBeenCalledWith('preset-candidate')
  expect(app.api.cancelRequest).toHaveBeenCalledOnce()
  app.control<HTMLButtonElement>('.native-ai-accept').click()
  expect(app.api.accept).not.toHaveBeenCalled(); expect(app.draft.operations).toEqual([])
})

it.each(['page', 'draft'])('翻译候选之后改变%s拒绝旧候选，不覆盖新上下文', async change => {
  const app = await fixture(); app.translate(); app.submit()
  await vi.waitFor(() => expect(app.control<HTMLElement>('.native-ai-preview').hidden).toBe(false))
  if (change === 'page') app.control<HTMLButtonElement>('.slide-open[data-slide-index="1"]').click()
  else app.write('新草稿')
  const before = structuredClone(app.draft.operations)
  app.control<HTMLButtonElement>('.native-ai-accept').click()
  await vi.waitFor(() => expect(app.control('.native-ai-status').textContent).toContain('草稿已变化'))
  expect(app.api.accept).not.toHaveBeenCalled(); expect(app.draft.operations).toEqual(before)
})

it('切换语言取消尚未返回的start，迟到候选不得覆盖新语言或进入草稿', async () => {
  const app = await fixture()
  let finish!: (job: typeof app.job) => void
  app.api.start.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  app.translate(); app.submit()
  const requestId = app.api.start.mock.calls[0]![0].clientRequestId
  app.translate('ja')
  expect(app.api.cancelRequest).toHaveBeenCalledWith(requestId)
  finish(app.job)
  await vi.waitFor(() => expect(app.api.cancel).toHaveBeenCalledWith(app.job.editId))
  expect(app.control<HTMLElement>('.native-ai-preview').hidden).toBe(true)
  expect(app.control<HTMLTextAreaElement>('.slides-native-ai textarea').value).toContain('日语')
  expect(app.draft.operations).toEqual([])
})

it('旧任务取消失败回执不覆盖新预设的准备状态', async () => {
  const app = await fixture()
  app.translate(); app.submit(); await vi.waitFor(() => expect(app.control<HTMLElement>('.native-ai-preview').hidden).toBe(false))
  let reject!: (error: Error) => void
  app.api.cancel.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
  app.translate('ja'); reject(new Error('旧取消失败'))
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
  expect(app.control('.native-ai-status').textContent).toContain('请核对授权范围')
  expect(app.control<HTMLTextAreaElement>('.slides-native-ai textarea').value).toContain('日语')
})

it('正在采纳或保存时不切换预设，不覆盖已冻结的候选身份', async () => {
  const app = await fixture(); app.translate(); app.submit()
  await vi.waitFor(() => expect(app.control<HTMLElement>('.native-ai-preview').hidden).toBe(false))
  let finish!: (value: { operations: NativeOperation[] }) => void
  app.api.accept.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  app.control<HTMLButtonElement>('.native-ai-accept').click()
  expect(app.view.officeEditAssistant!.openPreset({ kind: 'translate', language: 'ja' })).toBe(false)
  expect(app.control<HTMLTextAreaElement>('.slides-native-ai textarea').value).toContain('英语')
  finish({ operations: app.job.proposal.operations })
  await vi.waitFor(() => expect(app.draft.operations).toEqual(app.job.proposal.operations))
  app.draft.beginSave()
  expect(app.view.officeEditAssistant!.openPreset({ kind: 'spelling' })).toBe(false)
  app.draft.saveFailed()
})
