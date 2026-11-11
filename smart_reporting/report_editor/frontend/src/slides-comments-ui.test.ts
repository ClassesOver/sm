import { afterEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'
import { NativeDraft } from './native-draft'
vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
afterEach(() => { document.body.innerHTML = ''; document.documentElement.lang = '' })
const source = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [
  { slideIndex: 0, elements: [], comments: { items: [{ authorId: 0, idx: 1, author: 'Alice', initials: 'A', dt: '', text: '<来源A>' }, { authorId: 1, idx: 1, author: 'Bob', initials: 'B', dt: '', text: '来源B' }], readOnlyReason: null } },
  { slideIndex: 1, elements: [], comments: { items: [], readOnlyReason: null } },
] }
function draft() {
  const data = new Map<string, string>()
  return new NativeDraft({ documentId: 'comments', revision: 1, sourceSha256: source.sha256, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' } }, { getItem: k => data.get(k) ?? null, setItem: (k, v) => { data.set(k, v) }, removeItem: k => { data.delete(k) } })
}
async function open(nativeDraft = draft(), model: any = source, nativeAI?: any) {
  document.documentElement.lang = 'zh-CN'; document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'pptx')
  const request = vi.fn(async (path: string) => path === 'deck' ? structuredClone(model) : path === 'render-tree' ? { slides: [] } : { revision: 2, revisionRegistered: true, validation: { issues: [] } })
  const view = createSlidesEditorView(shell.editor, { native: true, draft: nativeDraft, request: request as any, save: shell.save, download: shell.exportPptx, nativeAI })
  await view.ready
  const command = (id: string) => shell.editor.querySelector<HTMLButtonElement>('[data-command="' + id + '"]')!
  const action = (id: string) => shell.editor.querySelector<HTMLButtonElement>('[data-comment-action="' + id + '"]')!
  const input = () => shell.editor.querySelector<HTMLTextAreaElement>('[data-comment-text]')!
  return { shell, nativeDraft, request, view, command, action, input }
}
it('中文批注入口可查看来源、保持纯文本，打开关闭不写草稿', async () => {
  const o = await open()
  expect(o.command('commentsPane').disabled).toBe(false)
  expect(o.command('commentsPane').querySelector('svg')).not.toBeNull()
  o.command('commentsPane').click()
  expect(o.shell.editor.querySelector('.slides-comments-pane')!.textContent).toContain('<来源A>')
  expect(o.shell.editor.querySelector('.slides-comments-pane 来源A')).toBeNull()
  o.action('close').click(); expect(o.nativeDraft.operations).toEqual([])
  o.command('newComment').click(); expect(document.activeElement).toBe(o.input())
  o.action('cancel').click(); expect(o.nativeDraft.operations).toEqual([])
  o.view.dispose()
})
it('发布、撤回新增、源删除与UndoRedo/刷新恢复共用完整草稿', async () => {
  const o = await open()
  o.command('newComment').click(); o.input().value = ' 新增😀 '; o.input().dispatchEvent(new Event('input', { bubbles: true })); o.action('add').click()
  const added = (o.nativeDraft.operations[0] as any).commentEdits[0]
  expect(added).toMatchObject({ kind: 'add', slideIndex: 0, text: ' 新增😀 ' }); expect(added.author).toBeUndefined()
  o.shell.editor.querySelector<HTMLButtonElement>('[data-comment-author-id="0"][data-comment-idx="1"] [data-comment-action="delete"]')!.click()
  expect((o.nativeDraft.operations[0] as any).commentEdits[1]).toEqual({ slideIndex: 0, kind: 'delete', authorId: 0, idx: 1 })
  expect(o.shell.editor.querySelector('[data-comment-author-id="1"][data-comment-idx="1"]')).not.toBeNull()
  o.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect((o.nativeDraft.operations[0] as any).commentEdits).toHaveLength(1)
  o.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  const saved = o.nativeDraft; o.view.dispose(); const restored = await open(saved)
  restored.command('commentsPane').click(); expect(restored.shell.editor.textContent).toContain('新增😀')
  restored.action('withdraw').click(); expect((saved.operations[0] as any).commentEdits).toEqual([{ slideIndex: 0, kind: 'delete', authorId: 0, idx: 1 }])
  restored.view.dispose()
})
it('保存前flush仍聚焦的输入，取消composer不产生操作', async () => {
  const o = await open(); o.command('newComment').click(); o.input().value = '未失焦新增'; o.input().dispatchEvent(new Event('input', { bubbles: true }))
  o.shell.save.click(); await vi.waitFor(() => expect(o.request.mock.calls.some(([path]) => path === 'save')).toBe(true))
  const call = (o.request.mock.calls as unknown as [string, RequestInit][]).find(([path]) => path === 'save')!
  expect(JSON.parse(call[1].body as string).operations[0].commentEdits[0]).toMatchObject({ slideIndex: 0, kind: 'add', text: '未失焦新增' })
  o.view.dispose()
})
it('只读原因可见，新增和源删除禁止；超限输入不写操作', async () => {
  const ro = structuredClone(source); ro.slides[0]!.comments.readOnlyReason = '现代批注来源无法唯一核对' as any
  let o = await open(draft(), ro); o.command('commentsPane').click(); expect(o.shell.editor.textContent).toContain('现代批注来源无法唯一核对')
  o.command('newComment').click(); expect(o.shell.editor.querySelector('[data-comment-text]')).toBeNull(); expect(o.action('delete').disabled).toBe(true); o.view.dispose()
  o = await open(); o.command('newComment').click(); expect(o.action('add').disabled).toBe(true)
  o.input().value = 'x'.repeat(10001); o.input().dispatchEvent(new Event('input', { bubbles: true })); o.action('add').click()
  expect(o.shell.editor.textContent).toContain('10000'); expect(o.nativeDraft.operations).toEqual([]); o.view.dispose()
})
it('非法评论草稿拒绝恢复且保持原草稿', async () => {
  const d = draft(); d.setOperations([{ kind: 'editSlides', commentEdits: [{ slideIndex: 0, kind: 'delete', authorId: 9, idx: 1 }] }]); const before = structuredClone(d.operations)
  await expect(open(d)).rejects.toThrow('批注'); expect(d.operations).toEqual(before)
})
it('来源重排仍绑定原页，评论草稿阻止同页删除，撤回最后新增恢复空草稿', async () => {
  let o = await open()
  o.shell.editor.querySelector<HTMLButtonElement>('.slide-row button[aria-label="下移页面"]')!.click()
  o.command('newComment').click(); o.input().value = '原页零'; o.input().dispatchEvent(new Event('input', { bubbles: true })); o.action('add').click()
  expect((o.nativeDraft.operations[0] as any).order).toEqual([1, 0])
  expect((o.nativeDraft.operations[0] as any).commentEdits[0].slideIndex).toBe(0)
  const before = structuredClone(o.nativeDraft.operations)
  o.shell.editor.querySelectorAll<HTMLButtonElement>('.slide-row button[aria-label="删除幻灯片"]')[1]!.click()
  expect(o.nativeDraft.operations).toEqual(before); expect(o.shell.editor.textContent).toContain('该页有待保存修改'); o.view.dispose()
  o = await open(); o.command('newComment').click(); o.input().value = '仅新增'; o.input().dispatchEvent(new Event('input', { bubbles: true })); o.action('add').click(); o.action('withdraw').click()
  expect(o.nativeDraft.operations).toEqual([]); o.view.dispose()
})
it('新建或复制页保存重开前禁用新增，未知批注来源保持只读', async () => {
  let o = await open(); o.command('addSlide').click(); expect(o.command('newComment').disabled).toBe(true)
  o.command('commentsPane').click(); expect(o.shell.editor.querySelector('.slides-comments-pane')!.textContent).toContain('保存并重新打开'); o.view.dispose()
  o = await open(); o.shell.editor.querySelector<HTMLButtonElement>('.slide-row button[aria-label="复制幻灯片"]')!.click(); expect(o.command('newComment').disabled).toBe(true); o.view.dispose()
  const unknown = structuredClone(source) as any; delete unknown.slides[0].comments
  o = await open(draft(), unknown); expect(o.command('newComment').disabled).toBe(true); o.command('commentsPane').click(); expect(o.shell.editor.querySelector('.slides-comments-pane')!.textContent).toContain('批注来源'); o.view.dispose()
})
it('AI上下文携带完整评论base，采纳与Undo不丢人工评论', async () => {
  const d = draft(), model = structuredClone(source) as any
  model.slides[0].elements = [{ id: 'title', type: 'text', name: '标题', text: '原文', editable: true, geometry: { x: 0, y: 0, width: 100, height: 30 } }]
  const commentEdits = [{ slideIndex: 0, kind: 'add', clientId: 'manual', text: '人工评论' }]
  d.setOperations([{ kind: 'editSlides', commentEdits }])
  const operations = [{ kind: 'editSlides', commentEdits, edits: [{ slideIndex: 0, elementId: 'title', text: 'AI文字' }] }]
  const candidate = { editId: 'id', status: 'succeeded', snapshotSha256: 's'.repeat(64), proposal: { summary: '候选', operations } }
  const api = { start: vi.fn(async () => candidate), status: vi.fn(async () => candidate), accept: vi.fn(async () => ({ operations })), cancel: vi.fn(async () => ({})), cancelRequest: vi.fn(async () => ({})) }
  const o = await open(d, model, api)
  const panel = o.shell.editor.querySelector('.slides-native-ai')!
  panel.querySelector<HTMLTextAreaElement>('textarea')!.value = '润色'; panel.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  await vi.waitFor(() => expect(panel.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false))
  expect(api.start).toHaveBeenCalledWith(expect.objectContaining({ expectedSha256: source.sha256, operations: [{ kind: 'editSlides', commentEdits }] }), expect.any(AbortSignal))
  panel.querySelector<HTMLButtonElement>('.native-ai-accept')!.click(); await vi.waitFor(() => expect((d.operations[0] as any).edits?.[0]?.text).toBe('AI文字'))
  expect((d.operations[0] as any).commentEdits).toEqual(commentEdits)
  o.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click(); expect((d.operations[0] as any).commentEdits).toEqual(commentEdits); expect((d.operations[0] as any).edits).toBeUndefined(); o.view.dispose()
})
it('未发布输入阻止删除来源页，非法未失焦输入不保存或部分写入', async () => {
  const o = await open(); o.command('newComment').click(); o.input().value = '未发布'; o.input().dispatchEvent(new Event('input', { bubbles: true }))
  o.shell.editor.querySelector<HTMLButtonElement>('.slide-row button[aria-label="删除幻灯片"]')!.click()
  expect(o.shell.editor.querySelectorAll('.slide-row')).toHaveLength(2); expect(o.shell.editor.textContent).toContain('该页有待保存修改')
  o.shell.editor.querySelectorAll<HTMLButtonElement>('.slide-open')[1]!.click(); o.command('newComment').click(); o.input().value = 'x'.repeat(10001); o.input().dispatchEvent(new Event('input', { bubbles: true }))
  o.shell.save.click(); expect(o.request.mock.calls.some(([path]) => path === 'save')).toBe(false); expect(o.nativeDraft.operations).toEqual([]); expect(o.shell.editor.textContent).toContain('10000'); o.view.dispose()
})
