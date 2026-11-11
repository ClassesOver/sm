import { afterEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'
import { NativeDraft } from './native-draft'
vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
afterEach(() => { document.body.innerHTML = ''; document.documentElement.lang = '' })
const source = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [
  { slideIndex: 0, hidden: false, elements: [] }, { slideIndex: 1, hidden: true, elements: [] },
] }
function newDraft() {
  const data = new Map<string, string>()
  return new NativeDraft({ documentId: 'hidden-slides', revision: 1, sourceSha256: source.sha256,
    scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } },
  { getItem: k => data.get(k) ?? null, setItem: (k, v) => { data.set(k, v) }, removeItem: k => { data.delete(k) } })
}
async function open(draft: NativeDraft) {
  document.documentElement.lang = 'zh-CN'
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'pptx')
  const request = vi.fn(async (path: string) => path === 'deck' ? source : path === 'render-tree' ? { slides: [] }
    : { revision: 2, revisionRegistered: true, validation: { issues: [] } })
  const view = createSlidesEditorView(shell.editor, { native: true, draft, request: request as any, save: shell.save, download: shell.exportPptx })
  await view.ready
  return { shell, request, view }
}
it('隐藏页中文图标按钮连接草稿、撤销重做、恢复与保存', async () => {
  const draft = newDraft()
  let opened = await open(draft)
  const button = () => opened.shell.editor.querySelector<HTMLButtonElement>('[data-command="hideSlide"]')!
  expect(button().disabled).toBe(false)
  expect(button().textContent).toContain('隐藏幻灯片')
  expect(button().querySelector('svg')).not.toBeNull()
  expect(button().getAttribute('aria-pressed')).toBe('false')
  button().click()
  expect(draft.operations[0]).toMatchObject({ hiddenSlides: [{ slideIndex: 0, hidden: true }] })
  expect(button().getAttribute('aria-pressed')).toBe('true')
  expect(opened.shell.editor.querySelector('.slide-row')!.getAttribute('data-hidden')).toBe('true')
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(draft.operations).toEqual([])
  expect(button().getAttribute('aria-pressed')).toBe('false')
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  expect(button().getAttribute('aria-pressed')).toBe('true')
  opened.view.dispose()
  opened = await open(draft)
  expect(button().getAttribute('aria-pressed')).toBe('true')
  opened.shell.save.click()
  await vi.waitFor(() => expect(opened.request.mock.calls.some(([path]) => path === 'save')).toBe(true))
  const saveCall = (opened.request.mock.calls as unknown as [string, RequestInit][]).find(([path]) => path === 'save')!
  expect(JSON.parse(saveCall[1].body as string).operations[0].hiddenSlides).toEqual([{ slideIndex: 0, hidden: true }])
  opened.view.dispose()
})
it('来源隐藏页可取消隐藏，再次切换不保留无效覆盖', async () => {
  const draft = newDraft(), { shell, view } = await open(draft)
  shell.editor.querySelectorAll<HTMLButtonElement>('.slide-open')[1]!.click()
  const button = shell.editor.querySelector<HTMLButtonElement>('[data-command="hideSlide"]')!
  expect(button.getAttribute('aria-pressed')).toBe('true')
  button.click()
  expect(draft.operations[0]).toMatchObject({ hiddenSlides: [{ slideIndex: 1, hidden: false }] })
  expect(button.getAttribute('aria-pressed')).toBe('false')
  button.click()
  expect(draft.operations[0]?.hiddenSlides).toBeUndefined()
  view.dispose()
})

it.each([
  [{ slideIndex: 0, hidden: 'false' }],
  [{ slideIndex: 2, hidden: true }],
  [{ slideIndex: 0, hidden: true }, { slideIndex: 0, hidden: false }],
].map(hiddenSlides => ({ hiddenSlides })))('非法隐藏页草稿拒绝恢复且保留原操作 %j', async ({ hiddenSlides }) => {
  const draft = newDraft()
  draft.setOperations([{ kind: 'editSlides', hiddenSlides }])
  const before = structuredClone(draft.operations)
  await expect(open(draft)).rejects.toThrow('隐藏幻灯片无效')
  expect(draft.operations).toEqual(before)
})
it('隐藏页修改未保存时删除来源页会明确拒绝', async () => {
  const draft = newDraft(), { shell, view } = await open(draft)
  shell.editor.querySelector<HTMLButtonElement>('[data-command="hideSlide"]')!.click()
  const before = structuredClone(draft.operations)
  shell.editor.querySelector<HTMLButtonElement>('.slide-row button[aria-label="删除幻灯片"]')!.click()
  expect(draft.operations).toEqual(before)
  expect(shell.editor.textContent).toContain('该页有待保存修改')
  view.dispose()
})
it('复制预隐藏来源页后当前状态保留隐藏，但未保存副本仍不可修改', async () => {
  const draft = newDraft(), { shell, view } = await open(draft)
  shell.editor.querySelectorAll<HTMLButtonElement>('.slide-open')[1]!.click()
  shell.editor.querySelectorAll<HTMLButtonElement>('.slide-row button[aria-label="复制幻灯片"]')[1]!.click()
  const button = shell.editor.querySelector<HTMLButtonElement>('[data-command="hideSlide"]')!
  expect(button.getAttribute('aria-pressed')).toBe('true')
  expect(shell.editor.querySelector('.slide-row[data-selected="true"]')?.getAttribute('data-hidden')).toBe('true')
  const before = structuredClone(draft.operations)
  button.click()
  expect(draft.operations).toEqual(before)
  expect(shell.editor.textContent).toContain('保存并重新打开后')
  view.dispose()
})
