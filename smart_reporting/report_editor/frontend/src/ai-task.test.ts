import { describe, expect, it, vi } from 'vitest'
import { createAITaskAdapter, type AITaskAdapter } from './ai-task'
import { createAITaskController } from './ai-task-controller'
import { AssetTaskAdapter } from './asset-task-adapter'
function setup() {
  const adapter: AITaskAdapter<{ text: string }> = {
    kind: 'document-selection', start: vi.fn(async () => ({ taskId: 'task' })),
    status: vi.fn(async () => ({ taskId: 'task', kind: 'document-selection' as const, state: 'ready' as const, proposal: { text: 'new' } })),
    accept: vi.fn(async () => {}), cancel: vi.fn(async () => {}), reject: vi.fn(async () => {}),
    renderProposal: vi.fn(), applyProposal: vi.fn(async () => {}), undo: vi.fn(async () => {}),
  }
  let selection = 'old'
  const controller = createAITaskController({ adapter, pollMs: 0, captureInput: async () => ({ snapshot: { selection } }) })
  return { adapter, controller, change: () => { selection = 'changed' } }
}
describe('shared AI task controller', () => {
  it('previews, applies once, and undoes without cancelling accepted task', async () => {
    const { adapter, controller } = setup()
    await controller.generate('polish'); expect(adapter.applyProposal).not.toHaveBeenCalled()
    await Promise.all([controller.accept(), controller.accept()])
    expect(adapter.applyProposal).toHaveBeenCalledTimes(1); expect(controller.draft).toBe('applied')
    await controller.undo(); expect(controller.draft).toBe('undone'); expect(adapter.cancel).not.toHaveBeenCalled()
  })
  it('preserves accepted candidate after application failure for safe retry', async () => {
    const { adapter, controller } = setup()
    vi.mocked(adapter.applyProposal).mockRejectedValueOnce(new Error('temporarily unavailable'))
    await controller.generate('polish'); await controller.accept()
    expect(controller.task?.state).toBe('accepted'); expect(controller.error).toContain('temporarily')
    await controller.accept(); expect(controller.draft).toBe('applied'); expect(adapter.start).toHaveBeenCalledTimes(1)
  })
  it('revalidates snapshots before and after server confirmation', async () => {
    const { adapter, controller, change } = setup()
    await controller.generate('polish'); vi.mocked(adapter.accept).mockImplementationOnce(async () => { change() })
    await controller.accept(); expect(adapter.applyProposal).not.toHaveBeenCalled(); expect(controller.error).toContain('内容已变化')
    await controller.accept(); expect(adapter.accept).toHaveBeenCalledTimes(1)
  })
  it('cancels a job whose start response arrives after cancellation', async () => {
    const { adapter, controller } = setup()
    let finish!: (value: { taskId: string }) => void
    vi.mocked(adapter.start).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const running = controller.generate('polish'); await vi.waitFor(() => expect(adapter.start).toHaveBeenCalled())
    await controller.cancel(); finish({ taskId: 'late' }); await running
    expect(adapter.cancel).toHaveBeenCalledWith('late'); expect(adapter.status).not.toHaveBeenCalled(); expect(controller.task).toBeUndefined()
  })
  it('suppresses a late status after disposal', async () => {
    const { adapter, controller } = setup()
    let finish!: (value: Awaited<ReturnType<typeof adapter.status>>) => void
    vi.mocked(adapter.status).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const running = controller.generate('polish'); await vi.waitFor(() => expect(adapter.status).toHaveBeenCalled())
    controller.dispose(); finish({ taskId: 'task', kind: adapter.kind, state: 'ready', proposal: { text: 'late' } }); await running
    expect(controller.task?.state).toBe('running'); expect(adapter.cancel).toHaveBeenCalledWith('task')
  })
  it('retries failed generation with a new idempotency key', async () => {
    const { adapter, controller } = setup()
    vi.mocked(adapter.status).mockResolvedValueOnce({ taskId: 'task', kind: adapter.kind, state: 'failed', issues: [{ message: 'bad result' }] })
    await controller.generate('polish'); expect(controller.error).toBe('bad result')
    await controller.generate('retry'); expect(controller.task?.state).toBe('ready')
    const calls = vi.mocked(adapter.start).mock.calls
    expect(calls[0]![0].idempotencyKey).not.toBe(calls[1]![0].idempotencyKey); expect(adapter.reject).toHaveBeenCalledWith('task')
  })
})
it('encodes task IDs and sends snapshot on accept', async () => {
  const request = vi.fn(async () => ({}))
  const adapter = createAITaskAdapter({ kind: 'chart-edit', request: request as never, renderProposal: () => {}, applyProposal: async () => {} })
  await adapter.accept('a/b', { previousEditId: 'native' })
  expect(request).toHaveBeenCalledWith('ai/tasks/a%2Fb/accept', expect.objectContaining({ body: '{"snapshot":{"previousEditId":"native"}}' }))
})
it('preserves native resource identities through unified asset task transport', async () => {
  const request = vi.fn().mockResolvedValueOnce({ taskId: 'transport', nativeId: 'cedit-original', state: 'running' })
    .mockResolvedValueOnce({ state: 'ready', native: { editId: 'cedit-original', imagePath: 'chart.png', status: 'succeeded' } }).mockResolvedValue({})
  const adapter = new AssetTaskAdapter(request)
  expect(await adapter.start('chart-edit', 'chart-1', { instruction: 'blue', previousEditId: 'cedit-previous' })).toEqual({ editId: 'cedit-original', status: 'running' })
  expect(await adapter.status('cedit-original', 'chart-1')).toMatchObject({ editId: 'cedit-original', imagePath: 'chart.png' })
  await adapter.transition('cedit-original', 'accept')
  expect(request).toHaveBeenLastCalledWith('ai/tasks/transport/accept', expect.objectContaining({ body: '{"snapshot":{"previousEditId":"cedit-previous"}}' }))
})
it('retries an ambiguous start using the same idempotency key', async () => {
  const request = vi.fn().mockRejectedValueOnce(new TypeError('network')).mockResolvedValueOnce({ taskId: 'same-task' })
  const adapter = createAITaskAdapter({ kind: 'document-selection', request, renderProposal: () => {}, applyProposal: async () => {} })
  expect(await adapter.start({ kind: 'document-selection', instruction: 'polish' })).toEqual({ taskId: 'same-task' })
  expect(request.mock.calls[0]![1].body).toBe(request.mock.calls[1]![1].body)
})
it('does not apply a candidate after disposal during server acceptance', async () => {
  const { adapter, controller } = setup()
  let confirm!: () => void
  vi.mocked(adapter.accept).mockImplementationOnce(() => new Promise(resolve => { confirm = resolve }))
  await controller.generate('polish')
  const accepting = controller.accept()
  await vi.waitFor(() => expect(adapter.accept).toHaveBeenCalled())
  controller.dispose(); confirm(); await accepting
  expect(adapter.applyProposal).not.toHaveBeenCalled()
})

it('retains undo after generating and rejecting a later candidate', async () => {
  const { adapter, controller } = setup()
  await controller.generate('first'); await controller.accept()
  await controller.generate('second'); await controller.reject()
  expect(controller.canUndo).toBe(true)
  await controller.undo()
  expect(adapter.undo).toHaveBeenCalledTimes(1)
  expect(controller.canUndo).toBe(false)
})
