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
export class OfficeAssistantController<Input, Job> {
  private generation = 0
  private abort = new AbortController()
  private requestId = ''
  private taskId = ''
  private busy = false
  private accepting = false
  private terminalObserved = false
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
        await (this.transport.cancel?.(this.transport.id(job)) ?? this.transport.cancelRequest?.(requestId))
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
      // Keep the handles until cleanup succeeds; read adapters may call release()
      // in finally, but an unobserved terminal state must remain cancellable.
      void this.cleanup(failedRequest, failedTask).then(() => {
        if (turn === this.generation) { this.requestId = ''; this.taskId = '' }
      }).catch(() => {})
      throw error
    } finally { if (turn === this.generation) this.busy = false }
  }
  /** Invalidates local responses immediately, but always sends server cancellation. */
  async cancel(): Promise<void> {
    ++this.generation; this.abort.abort(); this.busy = false; this.accepting = false
    const requestId = this.requestId, taskId = this.taskId
    this.requestId = ''; this.taskId = ''
    this.terminalObserved = false
    const turn = this.generation
    try { await this.cleanup(requestId, taskId) }
    catch (error) {
      // Retrying cancellation must remain possible, but never restore an old
      // task's handles over a newer run.
      if (turn === this.generation) { this.requestId = requestId; this.taskId = taskId }
      throw error
    }
  }
  private async cleanup(requestId: string, taskId: string): Promise<void> {
    const invoke = async (operation: () => Promise<unknown>) => operation()
    const results = await Promise.allSettled([
      ...(requestId && this.transport.cancelRequest ? [invoke(() => this.transport.cancelRequest!(requestId))] : []),
      ...(taskId && this.transport.cancel ? [invoke(() => this.transport.cancel!(taskId))] : []),
    ])
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
