import type { AITaskAdapter, AITaskStartRequest, AITaskStatus } from './ai-task'

export type DraftState = 'unapplied' | 'applying' | 'applied' | 'undone'
export function snapshotKey(value: unknown): string {
  return JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item)
}

/** Owns one candidate; UI collapse never disposes this controller. */
export function createAITaskController<T>(options: {
  adapter: AITaskAdapter<T>
  captureInput: () => Promise<Pick<AITaskStartRequest, 'target' | 'snapshot'>>
  changed?: () => void
  pollMs?: number
}) {
  const { adapter } = options
  let task: AITaskStatus<T> | undefined
  let draft: DraftState = 'unapplied'
  let canUndo = false
  let snapshot: Record<string, unknown> = {}
  let generation = 0
  let busy = false
  let disposed = false
  let error = ''
  let wake: (() => void) | undefined
  const changed = () => { if (!disposed) options.changed?.() }
  const fail = (value: unknown) => { error = value instanceof Error ? value.message : 'AI 编辑失败，请重试。'; changed() }
  const pause = () => new Promise<void>(resolve => {
    const timer = setTimeout(() => { wake = undefined; resolve() }, options.pollMs ?? 400)
    wake = () => { clearTimeout(timer); wake = undefined; resolve() }
  })
  const abandon = async (action: 'cancel' | 'reject') => {
    if (busy) return
    ++generation; wake?.()
    if (task?.taskId && task.state !== 'accepted' && task.state !== 'cancelled') await adapter[action](task.taskId)
    task = undefined; error = ''; changed()
  }
  return {
    get task() { return task }, get draft() { return draft }, get error() { return error }, get busy() { return busy }, get canUndo() { return canUndo },
    async generate(instruction: string) {
      if (busy || disposed || !instruction.trim()) return
      let owner = generation
      try {
        await abandon('reject')
        owner = ++generation
        draft = 'unapplied'; error = ''
        task = { taskId: '', kind: adapter.kind, state: 'queued' }; changed()
        const input = await options.captureInput()
        if (disposed || owner !== generation) return
        snapshot = structuredClone(input.snapshot ?? {})
        const request = { ...input, snapshot, instruction, kind: adapter.kind, idempotencyKey: crypto.randomUUID() }
        // Retrying an ambiguous start uses the same key; never creates a second native job.
        const started = await adapter.start(request)
        if (disposed || owner !== generation) { await adapter.cancel(started.taskId); return }
        task = { ...task!, taskId: started.taskId, state: 'running' }; changed()
        let failures = 0
        while (!disposed && owner === generation) {
          let status: AITaskStatus<T>
          try { status = await adapter.status(started.taskId); failures = 0 }
          catch (failure) { if (++failures >= 3) throw failure; await pause(); continue }
          if (disposed || owner !== generation) return
          task = status; changed()
          if (status.state === 'ready' || status.state === 'accepted') break
          if (status.state === 'cancelled') break
          if (status.state === 'failed') throw new Error(status.issues?.map(issue => issue.message).join('；') || '候选生成失败，请重试。')
          await pause()
        }
      } catch (failure) { if (!disposed && owner === generation) { if (task) task = { ...task, state: 'failed' }; fail(failure) } }
    },
    async cancel() { try { await abandon('cancel') } catch (failure) { if (task) task = { ...task, state: 'failed' }; fail(failure) } },
    async reject() { try { await abandon('reject') } catch (failure) { fail(failure) } },
    async accept() {
      if (busy || disposed || !task?.proposal || draft === 'applied' || !['ready', 'accepted'].includes(task.state)) return
      const owner = generation
      busy = true; draft = 'applying'; error = ''; changed()
      const apply = async () => {
        const validate = async () => {
          if (disposed || owner !== generation) throw new Error('会话已关闭，候选未写入草稿。')
          await adapter.validateTarget?.()
          const current = (await options.captureInput()).snapshot ?? {}
          if (snapshotKey(current) !== snapshotKey(snapshot)) throw new Error('内容已变化，请重新生成候选。')
          return current
        }
        const current = await validate()
        await adapter.accept(task!.taskId, current)
        task!.state = 'accepted'
        // Network confirmation may yield while an editor without a lock keeps accepting input.
        await validate()
        if (disposed || owner !== generation) throw new Error('会话已关闭，候选未写入草稿。')
        await adapter.applyProposal(task!.proposal!)
      }
      try {
        if (adapter.withDraftLock) await adapter.withDraftLock(apply)
        else await apply()
        draft = 'applied'
        canUndo = Boolean(adapter.undo)
      } catch (failure) { draft = 'unapplied'; fail(failure) }
      finally { busy = false; changed() }
    },
    async undo() {
      if (busy || disposed || !canUndo || !adapter.undo || task?.state === 'running' || task?.state === 'queued') return
      busy = true; error = ''; changed()
      try {
        // A later preview must not erase the undo receipt for the last adoption.
        if (task?.taskId && task.state !== 'accepted' && task.state !== 'cancelled') {
          await adapter.reject(task.taskId); task = undefined
        }
        await adapter.undo(); draft = 'undone'; canUndo = false
      }
      catch (failure) { fail(failure) }
      finally { busy = false; changed() }
    },
    dispose() {
      if (disposed) return
      disposed = true; ++generation; wake?.()
      if (task?.taskId && task.state !== 'accepted') void adapter.cancel(task.taskId).catch(() => {})
      adapter.dispose?.()
    },
  }
}
