import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { editorViewCtx, parserCtx, serializerCtx } from '@milkdown/kit/core'
import { TextSelection } from '@milkdown/kit/prose/state'
import { createReportEditor } from './editor-features'
import { createDocumentAI } from './document-ai'

beforeEach(() => {
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList
  Range.prototype.getBoundingClientRect = () => new DOMRect()
})
afterEach(() => document.body.replaceChildren())
async function setup() {
  const root = document.createElement('div'); document.body.append(root)
  const crepe = createReportEditor(root, 'first\n\noriginal\n\nlast', {})
  const request = vi.fn().mockResolvedValueOnce({ taskId: 'document-task' }).mockResolvedValueOnce({
    taskId: 'document-task', kind: 'document-selection', state: 'ready', proposal: { markdown: 'revised' },
  }).mockResolvedValue({})
  const ai = createDocumentAI({
    view: () => crepe.editor.ctx.get(editorViewCtx),
    serialize: node => crepe.editor.ctx.get(serializerCtx)(node), parse: text => crepe.editor.ctx.get(parserCtx)(text), request,
  })
  crepe.editor.use(ai.plugin); await crepe.create()
  const view = crepe.editor.ctx.get(editorViewCtx)
  let from = 0; view.state.doc.descendants((node, pos) => { if (node.isTextblock && node.textContent === 'original') from = pos + 1 })
  view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, from, from + 8)))
  const session = ai.open(); session.instruction.value = 'polish'; await session.generate()
  return { crepe, view, session, request, from }
}
it('opens a shared document session, maps the selection around other edits, and supports native undo', async () => {
  const { crepe, view, session, request } = await setup()
  try {
    view.dispatch(view.state.tr.insertText('outside ', 1))
    await session.controller.accept()
    expect(view.state.doc.textContent).toBe('outside firstrevisedlast')
    session.reviewDock.querySelector<HTMLButtonElement>('[data-task-action="locate"]')!.click()
    await vi.waitFor(() => expect(view.state.doc.textBetween(view.state.selection.from, view.state.selection.to)).toBe('revised'))
    expect(request.mock.calls[0]![0]).toBe('ai/tasks')
    expect(request.mock.calls.some(([path]) => String(path).includes('rewrite'))).toBe(false)
    await session.controller.undo()
    expect(view.state.doc.textContent).toBe('outside firstoriginallast')
  } finally { session.remove(); await crepe.destroy() }
})
it('refuses to overwrite a selection modified during generation', async () => {
  const { crepe, view, session, request, from } = await setup()
  try {
    view.dispatch(view.state.tr.insertText('manual ', from + 2)); await session.controller.accept()
    expect(session.controller.error).toContain('原选区已修改')
    expect(request.mock.calls.some(([path]) => String(path).endsWith('/accept'))).toBe(false)
    expect(view.state.doc.textContent).toContain('manual')
  } finally { session.remove(); await crepe.destroy() }
})

it('restores the four preset actions and diff review, then continues from the adopted selection', async () => {
  const { crepe, view, session, request } = await setup()
  try {
    expect([...session.card.querySelectorAll('.ask-ai-start-item strong')].map(item => item.textContent)).toEqual(['润色表达', '精简内容', '扩写说明', '专业报告语气'])
    expect(session.card.querySelector('.ai-text-preview del')).not.toBeNull()
    expect(session.card.querySelector('.ai-text-preview ins')).not.toBeNull()
    session.card.querySelector<HTMLButtonElement>('[data-preview-mode="compare"]')!.click()
    expect([...session.card.querySelectorAll('.ai-preview-text')].map(item => item.textContent?.trim())).toEqual(['original', 'revised'])
    await session.controller.accept()
    request.mockResolvedValueOnce({ taskId: 'round2' }).mockResolvedValueOnce({ taskId: 'round2', kind: 'document-selection', state: 'ready', proposal: { markdown: 'refined again' } })
    session.instruction.value = '再精简'; await session.generate()
    const start = request.mock.calls.find(([path, init]) => path === 'ai/tasks' && JSON.parse(init.body).instruction === '再精简')!
    expect(JSON.parse(start[1].body).snapshot.selection.trim()).toBe('revised')
    expect(session.controller.error).toBe('')
    await session.controller.accept()
    expect(view.state.doc.textContent).toBe('firstrefined againlast')
    await session.controller.undo()
    expect(view.state.doc.textContent).toBe('firstrevisedlast')
  } finally { session.remove(); await crepe.destroy() }
})
