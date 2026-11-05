import { createAITaskTransport, type AITaskKind, type AITaskStatus, type TaskRequest } from './ai-task'

/** Resource identity remains the native editId. Task IDs are transport-only. */
export class AssetTaskAdapter {
  private tasks = new Map<string, { taskId: string; snapshot: Record<string, unknown>; kind: AITaskKind; resource: string }>()
  constructor(private request: TaskRequest) {}
  async start(kind: 'chart-edit' | 'table-edit', resource: string, payload: Record<string, unknown>, mode?: string) {
    const { instruction, templateId, ...snapshot } = payload
    const adapter = createAITaskTransport(this.request)
    const status = await adapter.start({ kind, instruction: String(instruction || (mode === 'template' ? '应用模板' : '调整图表')),
      target: { [kind === 'chart-edit' ? 'chartId' : 'tableId']: resource, mode, templateId, instructionProvided: Boolean(instruction) }, snapshot })
    if (!status.nativeId) throw new Error('AI 任务缺少原生候选身份，请重新生成。')
    this.tasks.set(status.nativeId, { taskId: status.taskId, snapshot, kind, resource })
    return { editId: status.nativeId, status: 'running' }
  }
  private get(editId: string, resource?: string) {
    const entry = this.tasks.get(editId)
    if (!entry || resource && entry.resource !== resource) throw new Error('AI 会话已失效，请重新生成。')
    return entry
  }
  async status<T>(editId: string, resource: string, waitMs = 0): Promise<T> {
    const entry = this.get(editId, resource)
    const task = await this.request<AITaskStatus>(`ai/tasks/${encodeURIComponent(entry.taskId)}${waitMs ? `?waitMs=${waitMs}` : ''}`)
    return { ...(task.native ?? {}), editId,
      status: task.state === 'ready' || task.state === 'accepted' ? 'succeeded' : task.state,
      ...(task.issues?.length ? { error: task.issues[0] } : {}),
    } as T
  }
  async transition(editId: string, action: 'accept' | 'cancel' | 'reject', resource?: string) {
    const entry = this.get(editId, resource)
    await this.request(`ai/tasks/${encodeURIComponent(entry.taskId)}/${action}`, {
      method: 'POST', body: JSON.stringify(action === 'accept' ? { snapshot: entry.snapshot } : {}),
    })
  }
}

/** Shared polling with stale-result suppression and bounded transient retries. */
export async function pollAIResult<T extends { status: string }>(options: {
  read: (waitMs: number) => Promise<T>; serverWaitMs?: number; retryMs?: number; active: () => boolean; progress?: (status: T) => void; interval: number
}): Promise<T | null> {
  let failures = 0
  let first = true
  while (options.active()) {
    let status: T
    try { status = await options.read(first || failures ? 0 : options.serverWaitMs ?? 0); failures = 0; first = false }
    catch (error) { if (!(error instanceof TypeError) || ++failures >= 5) throw error; await new Promise(resolve => setTimeout(resolve, options.retryMs ?? options.interval)); continue }
    if (!options.active()) return null
    options.progress?.(status)
    if (!['running', 'pending', 'queued'].includes(status.status)) return status
    await new Promise(resolve => setTimeout(resolve, options.interval))
  }
  return null
}
