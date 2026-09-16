import { describe, expect, it, vi } from 'vitest'

import { runInBackground } from './background'

describe('runInBackground', () => {
  it('consumes a rejected task through the error handler', async () => {
    let rejectTask: ((error: Error) => void) | undefined
    const task = new Promise<void>((_resolve, reject) => { rejectTask = reject })
    const onError = vi.fn()

    runInBackground(task, onError)
    const error = new Error('save failed')
    rejectTask?.(error)
    await task.catch(() => undefined)
    await Promise.resolve()

    expect(onError).toHaveBeenCalledWith(error)
  })
})
