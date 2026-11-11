import { z } from 'zod'
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly fieldErrors: {
      field: string
      code: string
      message: string
    }[] = [],
    readonly retryAfter?: number,
  ) {
    super(message)
  }
}
let epoch = 0
let unauthorized: (() => void) | undefined
export function setUnauthorized(handler: (() => void) | undefined) {
  unauthorized = handler
}
export function advanceSession() {
  epoch++
}
export function sessionEpoch() {
  return epoch
}
export async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  options: {
    method?: string
    body?: unknown
    csrf?: string
    signal?: AbortSignal
  } = {},
): Promise<T> {
  const started = epoch
  const headers: Record<string, string> = {}
  if (options.body !== undefined) headers['content-type'] = 'application/json'
  if (options.csrf) headers['x-csrf-token'] = options.csrf
  let response: Response
  try {
    response = await fetch('/management/api/v1' + path, {
      method: options.method ?? 'GET',
      headers,
      credentials: 'same-origin',
      cache: 'no-store',
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    })
  } catch (error) {
    if (options.signal?.aborted) throw error
    throw new ApiError(
      options.method && options.method !== 'GET'
        ? '网络连接中断，提交结果待确认。请读取最新状态后再决定是否重试。'
        : '网络连接中断，请重试。',
      0,
      'network_error',
    )
  }
  if (started !== epoch) throw new DOMException('会话已变化', 'AbortError')
  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new ApiError(
      '服务器响应格式异常，请稍后重试。',
      response.status,
      'protocol_error',
    )
  }
  if (started !== epoch) throw new DOMException('会话已变化', 'AbortError')
  if (!response.ok) {
    const error = z
      .object({
        message: z.string().optional(),
        code: z.string().optional(),
        fieldErrors: z
          .array(
            z.object({
              field: z.string(),
              code: z.string(),
              message: z.string(),
            }),
          )
          .optional(),
      })
      .safeParse(payload)
    if (
      response.status === 401 &&
      !path.startsWith('/auth/login') &&
      !(
        path === '/auth/password' &&
        error.success &&
        error.data.code === 'management_credentials_invalid'
      )
    )
      unauthorized?.()
    const retry = Number(response.headers.get('Retry-After'))
    throw new ApiError(
      error.success
        ? error.data.message || '请求失败，请重试。'
        : '请求失败，请重试。',
      response.status,
      error.success ? error.data.code || 'http_error' : 'http_error',
      error.success ? error.data.fieldErrors : [],
      retry > 0 ? retry : undefined,
    )
  }
  const result = schema.safeParse(payload)
  if (!result.success)
    throw new ApiError(
      '服务器响应格式异常，请稍后重试。',
      response.status,
      'protocol_error',
    )
  return result.data
}
export const emptySchema = z.object({}).passthrough()
export const identity = (scope: { database: string; companyId: string }) => ({
  scopeDatabase: scope.database,
  companyId: scope.companyId,
})
export const scopeQuery = (scope: { database: string; companyId: string }) =>
  new URLSearchParams(identity(scope)).toString()
