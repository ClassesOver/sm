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
  constructor(private readonly transport: OfficeTaskTransport<Input, Job>) {}
  get signal() { return this.abort.signal }
  async run(input: Input, requestId: string, onStart?: (job: Job, signal: AbortSignal) => void): Promise<Job | undefined> {
    if (this.busy || this.accepting) throw new Error('office_task_busy')
    const turn = ++this.generation
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
      return job
    } catch (error) {
      if (turn !== this.generation) return undefined
      if (!this.taskId && this.requestId) {
        this.requestId = ''
        // A failed start response does not prove the server did not start it.
        try { await this.transport.cancelRequest?.(requestId) } catch { /* preserve the original transport error */ }
      }
      throw error
    } finally { if (turn === this.generation) this.busy = false }
  }
  /** Invalidates local responses immediately, but always sends server cancellation. */
  async cancel(): Promise<void> {
    ++this.generation; this.abort.abort(); this.busy = false; this.accepting = false
    const requestId = this.requestId, taskId = this.taskId
    this.requestId = ''; this.taskId = ''
    const results = await Promise.allSettled([
      ...(requestId && this.transport.cancelRequest ? [this.transport.cancelRequest(requestId)] : []),
      ...(taskId && this.transport.cancel ? [this.transport.cancel(taskId)] : []),
    ])
    const failure = results.find(result => result.status === 'rejected')
    if (failure?.status === 'rejected') throw failure.reason
  }
  /** Acceptance still requires the format's snapshot checks before and after HTTP. */
  async accept<Result>(operation: (signal: AbortSignal) => Promise<Result>): Promise<Result | undefined> {
    if (this.busy || this.accepting) throw new Error('office_task_busy')
    if (!this.taskId) return undefined
    const turn = this.generation
    this.accepting = true
    try {
      const result = await operation(this.signal)
      return turn === this.generation ? result : undefined
    } finally { if (turn === this.generation) this.accepting = false }
  }
  release() { this.requestId = ''; this.taskId = '' }
}
