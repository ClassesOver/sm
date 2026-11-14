/** Shared, view-free task control. Task status is authoritative on the server;
 * a terminal task is neither an accepted candidate nor a saved document.
 * Format adapters capture trusted context and map typed HTTP methods only.
 */
export interface OfficeTaskTransport<Input, Job> {
  start(input: Input, signal: AbortSignal): Promise<Job>
  status(id: string, signal: AbortSignal): Promise<Job>
  cancel?(id: string): Promise<unknown>
  cancelRequest?(requestId: string): Promise<unknown>
  id(job: Job): string
  running(job: Job): boolean
}
type Cleanup = { kind: 'request' | 'task'; id: string; pending?: Promise<void> }
export class OfficeAssistantController<Input, Job> {
  private generation = 0
  private abort = new AbortController()
  private requestId = ''
  private taskId = ''
  private busy = false
  private accepting = false
  private terminalObserved = false
  private readonly cleanups = new Map<string, Cleanup>()
  private pendingCancel: { generation: number; promise: Promise<void> } | undefined
  constructor(private readonly transport: OfficeTaskTransport<Input, Job>) {}
  get signal() { return this.abort.signal }
  async run(input: Input, requestId: string, onStart?: (job: Job, signal: AbortSignal) => void): Promise<Job | undefined> {
    if (this.busy || this.accepting) throw new Error('office_task_busy')
    const previousRequest = this.requestId, previousTask = this.taskId
    if (previousRequest || previousTask) void this.cleanup(previousRequest, previousTask).catch(() => {})
    const turn = ++this.generation
    this.terminalObserved = false
    this.abort.abort(); this.abort = new AbortController()
    const signal = this.abort.signal
    this.requestId = requestId; this.taskId = ''; this.busy = true
    try {
      let job = await this.transport.start(input, signal)
      if (turn !== this.generation) {
        // An aborted HTTP request may still have created a server-side task.
        // A late task is independent of the active run. Keep its cleanup handle
        // until cancellation succeeds, without restoring it over a replacement.
        await this.cleanup(this.transport.cancel ? '' : requestId, this.transport.cancel ? this.transport.id(job) : '')
        return undefined
      }
      this.taskId = this.transport.id(job)
      onStart?.(job, signal)
      if (turn !== this.generation) return undefined
      while (this.transport.running(job)) {
        job = await this.transport.status(this.taskId, signal)
        if (turn !== this.generation) return undefined
      }
      this.terminalObserved = true
      return job
    } catch (error) {
      if (turn !== this.generation) return undefined
      this.abort.abort()
      const failedRequest = this.requestId, failedTask = this.taskId
      // Error delivery is not held hostage by a hung cancellation endpoint.
      // Transfer handles to independent cleanup records before a replacement
      // starts. A successful endpoint must not be re-enqueued from active state.
      this.requestId = ''; this.taskId = ''
      void this.cleanup(failedRequest, failedTask).catch(() => {})
      throw error
    } finally { if (turn === this.generation) this.busy = false }
  }
  /** Invalidates local responses immediately, but always sends server cancellation. */
  async cancel(): Promise<void> {
    // Close/dispose/cancel may arrive together. Share this task's in-flight
    // cancellation instead of advancing the fence with an empty second cancel.
    if (this.pendingCancel?.generation === this.generation) return this.pendingCancel.promise
    ++this.generation; this.abort.abort(); this.busy = false; this.accepting = false
    const requestId = this.requestId, taskId = this.taskId
    this.requestId = ''; this.taskId = ''
    this.terminalObserved = false
    const turn = this.generation
    const current = this.queueCleanup(requestId, taskId)
    const completion = this.cleanupAll([...new Set([...current, ...this.cleanups.values()])]).finally(() => {
      if (this.pendingCancel?.promise === completion) this.pendingCancel = undefined
    })
    this.pendingCancel = { generation: turn, promise: completion }
    return completion
  }
  private queueCleanup(requestId: string, taskId: string): Cleanup[] {
    const records: Cleanup[] = []
    const add = (kind: Cleanup['kind'], id: string) => {
      if (!id || !(kind === 'request' ? this.transport.cancelRequest : this.transport.cancel)) return
      const key = `${kind}:${id}`
      let record = this.cleanups.get(key)
      if (!record) { record = { kind, id }; this.cleanups.set(key, record) }
      records.push(record)
    }
    add('request', requestId); add('task', taskId)
    return records
  }
  private cleanupRecord(record: Cleanup): Promise<void> {
    if (record.pending) return record.pending
    const invoke = async () => record.kind === 'request' ? this.transport.cancelRequest!(record.id) : this.transport.cancel!(record.id)
    const completion = invoke().then(() => {
      this.cleanups.delete(`${record.kind}:${record.id}`)
    }).finally(() => { if (record.pending === completion) record.pending = undefined })
    record.pending = completion
    return completion
  }
  private cleanup(requestId: string, taskId: string): Promise<void> {
    return this.cleanupAll(this.queueCleanup(requestId, taskId))
  }
  private async cleanupAll(records: Cleanup[]): Promise<void> {
    const results = await Promise.allSettled(records.map(record => this.cleanupRecord(record)))
    const failure = results.find(result => result.status === 'rejected')
    if (failure?.status === 'rejected') throw failure.reason
  }
  /** Acceptance still requires the format's snapshot checks before and after HTTP. */
  async accept<Result>(operation: (signal: AbortSignal) => Promise<Result>): Promise<Result | undefined> {
    if (this.busy || this.accepting) throw new Error('office_task_busy')
    if (!this.taskId || !this.terminalObserved) return undefined
    const turn = this.generation
    this.accepting = true
    try {
      const result = await operation(this.signal)
      return turn === this.generation ? result : undefined
    } finally { if (turn === this.generation) this.accepting = false }
  }
  release() { if (this.terminalObserved) { this.requestId = ''; this.taskId = '' } }
}
