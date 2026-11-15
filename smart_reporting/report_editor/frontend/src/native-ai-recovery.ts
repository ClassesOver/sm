import { NativeApiError } from './native-api'

export function missingNativeAITask(error: unknown) {
  return error instanceof NativeApiError && error.status === 404 && error.code === 'native_ai_job_missing'
}

export function temporaryConnectionFailure(error: unknown) {
  return error instanceof TypeError || error instanceof NativeApiError && [502, 503, 504].includes(error.status)
}

function waitForNativeAIService(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(signal.reason) }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort)
      resolve()
    }, 750)
    signal.addEventListener('abort', abort, {once:true})
    if (signal.aborted) abort()
  })
}

export async function reconnectNativeAITask<Job>(
  read: (signal: AbortSignal) => Promise<Job>,
  resume: (signal: AbortSignal) => Promise<Job>,
  error: unknown,
  parent: AbortSignal,
): Promise<Job> {
  const reconnect = new AbortController()
  const abort = () => reconnect.abort(parent.reason)
  parent.addEventListener('abort', abort, {once:true})
  if (parent.aborted) abort()
  const timeout = setTimeout(() => reconnect.abort(new Error('连接尚未恢复，请重新打开文档。')), 45000)
  const signal = reconnect.signal
  try {
    while (!signal.aborted) {
      try {
        if (missingNativeAITask(error)) return await resume(signal)
        if (!temporaryConnectionFailure(error)) throw error
        await waitForNativeAIService(signal)
        return await read(signal)
      } catch (next) {
        if (!missingNativeAITask(next) && !temporaryConnectionFailure(next)) throw next
        // If the resume endpoint rejects the original identity, the task is gone.
        if (missingNativeAITask(error) && missingNativeAITask(next)) throw next
        error = next
      }
    }
    throw signal.reason
  } finally {
    clearTimeout(timeout)
    parent.removeEventListener('abort', abort)
  }
}
