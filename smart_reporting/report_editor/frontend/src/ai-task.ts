export type AITaskKind = 'document-selection' | 'slides-edit' | 'workbook-edit' | 'chart-edit' | 'table-edit'
export type AITaskState = 'queued' | 'running' | 'ready' | 'accepted' | 'cancelled' | 'failed'
export interface AITaskStartRequest {
  kind: AITaskKind
  instruction: string
  idempotencyKey?: string
  target?: Record<string, unknown>
  snapshot?: Record<string, unknown>
}
export interface AITaskStatus<T = unknown> {
  taskId: string
  kind: AITaskKind
  state: AITaskState
  summary?: string
  proposal?: T
  issues?: { code?: string; message: string }[]
  native?: Record<string, unknown>
}
export interface AITaskAdapter<T = unknown> {
  kind: AITaskKind
  start(input: AITaskStartRequest): Promise<{ taskId: string; nativeId?: string }>
  status(taskId: string): Promise<AITaskStatus<T>>
  cancel(taskId: string): Promise<void>
  accept(taskId: string, snapshot?: unknown): Promise<void>
  reject(taskId: string): Promise<void>
  renderProposal(proposal: T, target: HTMLElement): void
  applyProposal(proposal: T): Promise<void>
  validateTarget?(): void | Promise<void>
  locateTarget?(): boolean | Promise<boolean>
  dispose?(): void
  undo?(): Promise<void>
  withDraftLock?<R>(action: () => Promise<R>): Promise<R>
}
export type TaskRequest = <T>(path: string, init?: RequestInit) => Promise<T>

export function createAITaskAdapter<T>(options: {
  kind: AITaskKind
  request: TaskRequest
  renderProposal: AITaskAdapter<T>['renderProposal']
  applyProposal: AITaskAdapter<T>['applyProposal']
  validateTarget?: AITaskAdapter<T>['validateTarget']
  locateTarget?: AITaskAdapter<T>['locateTarget']
  dispose?: AITaskAdapter<T>['dispose']
  undo?: AITaskAdapter<T>['undo']
  withDraftLock?: AITaskAdapter<T>['withDraftLock']
}): AITaskAdapter<T> {
  return { ...createAITaskTransport<T>(options.request), ...options }
}

export function createAITaskTransport<T = unknown>(request: TaskRequest): Pick<AITaskAdapter<T>, 'start' | 'status' | 'accept' | 'cancel' | 'reject'> {
  const update = async (taskId: string, action: string, snapshot?: unknown) => {
    await request(`ai/tasks/${encodeURIComponent(taskId)}/${action}`, {
      method: 'POST', body: JSON.stringify({ ...(snapshot === undefined ? {} : { snapshot }) }),
    })
  }
  return {
    start: async input => {
      const body = JSON.stringify({ ...input, idempotencyKey: input.idempotencyKey ?? crypto.randomUUID() })
      const start = () => request<{ taskId: string; nativeId?: string }>('ai/tasks', { method: 'POST', body })
      try { return await start() }
      catch (error) { if (!(error instanceof TypeError)) throw error; return start() }
    },
    status: taskId => request(`ai/tasks/${encodeURIComponent(taskId)}`),
    cancel: taskId => update(taskId, 'cancel'),
    accept: (taskId, snapshot) => update(taskId, 'accept', snapshot),
    reject: taskId => update(taskId, 'reject'),
  }
}
