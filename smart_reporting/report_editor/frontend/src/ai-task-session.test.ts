import { afterEach, expect, it, vi } from 'vitest'
import { createAskAIPanel } from './ask-ai-panel'
import { createAITaskAdapter, type AITaskKind } from './ai-task'
afterEach(() => document.body.replaceChildren())
it('maintains five independent sessions and notifies when a collapsed task finishes', async () => {
  const panel = createAskAIPanel()
  const kinds = { document: 'document-selection', slides: 'slides-edit', workbook: 'workbook-edit', chart: 'chart-edit', table: 'table-edit' } as const
  const sessions = Object.entries(kinds).map(([kind, taskKind]) => {
    const request = vi.fn().mockResolvedValueOnce({ taskId: kind }).mockResolvedValue({ taskId: kind, kind: taskKind, state: 'ready', proposal: { text: kind } })
    return panel.createTaskSession({ kind: kind as keyof typeof kinds, label: kind, captureInput: async () => ({ snapshot: {} }),
      adapter: createAITaskAdapter({ kind: taskKind as AITaskKind, request, renderProposal: (proposal: { text: string }, target) => { target.textContent = proposal.text }, applyProposal: vi.fn(async () => {}) }) })
  })
  sessions[0]!.open(); sessions[0]!.close()
  await Promise.all(sessions.map(session => { session.instruction.value = 'edit'; return session.generate() }))
  expect(panel.panel.querySelectorAll('.ask-ai-session-tab')).toHaveLength(5)
  expect(document.querySelectorAll('.ask-ai-notification')).toHaveLength(5)
  for (const [index, session] of sessions.entries()) {
    expect(session.state).toBe('ready'); expect(session.card.querySelector('.ai-task-preview')!.textContent).toBe(Object.keys(kinds)[index])
    session.remove()
  }
})

function sessionSetup() {
  const panel = createAskAIPanel()
  const request = vi.fn().mockImplementation(async (path: string) => path === 'ai/tasks' ? { taskId: 'test' }
    : path === 'ai/tasks/test' ? { taskId: 'test', state: 'ready', kind: 'document-selection', proposal: { text: 'new' }, issues: [{ message: '请核对引用' }] } : {})
  const apply = vi.fn(async () => {})
  const session = panel.createTaskSession({ kind: 'document', label: '正文选区', captureInput: async () => ({ snapshot: {} }),
    suggestions: [{ label: '润色表达', instruction: '润色并保留事实' }], refinements: ['再精简一些'],
    adapter: createAITaskAdapter({ kind: 'document-selection', request, renderProposal: (proposal: { text: string }, target) => { target.textContent = proposal.text }, applyProposal: apply, undo: async () => {} }),
  })
  session.open()
  return { panel, session, request, apply }
}
it('restores recommendations, refinements, issue details and keyboard review without intercepting typing', async () => {
  const { session, request, apply } = sessionSetup()
  session.card.querySelector<HTMLButtonElement>('.ask-ai-start-item')!.click()
  expect(session.instruction.value).toBe('润色并保留事实')
  expect(request).not.toHaveBeenCalled()
  session.instruction.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true }))
  await vi.waitFor(() => expect(session.state).toBe('ready'))
  expect(session.card.querySelector('.ai-task-issues')?.textContent).toContain('请核对引用')
  session.composer.querySelector<HTMLButtonElement>('.ask-ai-refine-chip')!.click()
  expect(session.instruction.value).toBe('润色并保留事实；再精简一些')
  session.instruction.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }))
  expect(apply).not.toHaveBeenCalled()
  document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'c', bubbles: true }))
  expect(document.activeElement).toBe(session.instruction)
  document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }))
  await vi.waitFor(() => expect(apply).toHaveBeenCalledTimes(1))
  expect(session.undoButton.hidden).toBe(false)
  session.remove()
})
it('does not run review shortcuts in a hidden or inactive session', async () => {
  const { session, apply } = sessionSetup()
  session.instruction.value = 'edit'; await session.generate(); session.close()
  document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }))
  expect(apply).not.toHaveBeenCalled()
  session.remove()
})
it('shows a retry action after failure and preserves the instruction', async () => {
  const { session, request } = sessionSetup()
  request.mockRejectedValueOnce(new Error('暂时不可用'))
  session.instruction.value = '原来的要求'; await session.generate()
  const retry = session.reviewDock.querySelector<HTMLButtonElement>('[data-task-action="retry"]')!
  expect(retry.hidden).toBe(false); expect(session.state).toBe('error')
  retry.click(); await vi.waitFor(() => expect(session.state).toBe('ready'))
  expect(session.instruction.value).toBe('原来的要求')
  session.remove()
})

it('disables empty input, prevents duplicate starts and preserves focus on completion', async () => {
  const { session, request } = sessionSetup()
  const submit = session.composer.querySelector<HTMLButtonElement>('[type="submit"]')!
  expect(submit.disabled).toBe(true)
  session.instruction.value = '修改'; session.instruction.dispatchEvent(new Event('input'))
  expect(submit.disabled).toBe(false)
  session.instruction.focus()
  await Promise.all([session.generate(), session.generate()])
  expect(request.mock.calls.filter(([path]) => path === 'ai/tasks')).toHaveLength(1)
  expect(document.activeElement).toBe(session.instruction)
  expect(session.card.querySelector<HTMLDetailsElement>('.ai-task-history')!.open).toBe(false)
  expect(session.reviewDock.querySelector<HTMLButtonElement>('[data-task-action="view"]')!.hidden).toBe(false)
  session.remove()
})
it('only exposes target location when supported and reports missing targets', async () => {
  const panel = createAskAIPanel()
  const locate = vi.fn().mockReturnValueOnce(false).mockResolvedValueOnce(true)
  const session = panel.createTaskSession({ kind: 'slides', label: '幻灯片', captureInput: async () => ({}), adapter: createAITaskAdapter({
    kind: 'slides-edit', request: vi.fn().mockImplementation(async path => path === 'ai/tasks' ? { taskId: 'id' } : path === 'ai/tasks/id' ? { state: 'ready', proposal: {} } : {}),
    renderProposal: () => {}, applyProposal: async () => {}, locateTarget: locate,
  }) })
  session.open(); session.instruction.value = '修改'; await session.generate(); await session.controller.accept()
  const button = session.reviewDock.querySelector<HTMLButtonElement>('[data-task-action="locate"]')!
  expect(button.hidden).toBe(false); button.click()
  await vi.waitFor(() => expect(session.card.textContent).toContain('目标已变化或无法定位'))
  expect(session.visible).toBe(true); button.click()
  await vi.waitFor(() => expect(session.visible).toBe(false)); session.remove()
})

it('shows instruction limits and does not silently truncate or submit oversized refinements', async () => {
  const { session, request } = sessionSetup()
  session.instruction.value = '长'.repeat(2001); session.instruction.dispatchEvent(new Event('input'))
  expect(session.composer.querySelector('.ai-instruction-count')?.textContent).toBe('2001 / 2000')
  expect(session.composer.querySelector<HTMLButtonElement>('[type="submit"]')!.disabled).toBe(true)
  await session.generate(); expect(request).not.toHaveBeenCalled()
  session.instruction.value = '短'; session.instruction.dispatchEvent(new Event('input')); await session.generate()
  session.instruction.value = '长'.repeat(2000); session.instruction.dispatchEvent(new Event('input'))
  session.composer.querySelector<HTMLButtonElement>('.ask-ai-refine-chip')!.click()
  expect(session.instruction.value).toHaveLength(2000)
  expect(session.card.textContent).toContain('请精简后再添加微调')
  session.remove()
})

it('allows immediate regeneration after cancellation without waiting for a late start response', async () => {
  const { session, request } = sessionSetup()
  let finish!: (value: { taskId: string }) => void
  request.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  session.instruction.value = '第一轮'
  const pending = session.generate()
  await vi.waitFor(() => expect(request).toHaveBeenCalledWith('ai/tasks', expect.anything()))
  session.reviewDock.querySelector<HTMLButtonElement>('[data-task-action="cancel"]')!.click()
  await vi.waitFor(() => expect(session.controller.task).toBeUndefined())
  session.instruction.value = '第二轮'; await session.generate()
  expect(session.state).toBe('ready')
  finish({ taskId: 'late-task' }); await pending
  expect(session.controller.task?.taskId).toBe('test')
  expect(request.mock.calls.some(([path]) => path === 'ai/tasks/late-task/cancel')).toBe(true)
  session.remove()
})
