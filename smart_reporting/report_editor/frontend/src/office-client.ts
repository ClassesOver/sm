export type OfficeUser = { user: string; name: string; role: 'admin' | 'user'; enabled: boolean }
export type OfficeSpace = {
  id: string; name: string; personal_user: string | null
  role: 'owner' | 'editor' | 'viewer'; archived: boolean
}
export type OfficeFile = {
  space: string
  id: string; name: string; format: 'docx' | 'xlsx' | 'pptx' | 'pdf'
  folder: string | null; document: string; revision: number; version: number
  starred: boolean; seen: number; recentHidden?: boolean
}
export type OfficeLibrary = {
  folders: { id: string; parent: string | null; name: string }[]
  files: OfficeFile[]
}

let csrf = ''

export class OfficeRequestError extends Error {
  constructor(message: string, readonly status: number) { super(message) }
}

export function expireOfficeSession() {
  if (!csrf) return
  csrf = ''
  window.dispatchEvent(new Event('genoffice-session-expired'))
}

export async function officeRequest<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const session = csrf
  const multipart = body instanceof FormData
  const response = await fetch(`/office/api${path}`, {
    method, credentials: 'same-origin', cache: 'no-store', signal,
    headers: {
      ...(method === 'GET' ? {} : { 'x-csrf-token': csrf }),
      ...(body && !multipart ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? multipart ? body : JSON.stringify(body) : undefined,
  })
  if (response.status === 401 && session === csrf && !(path === '/session' && method === 'POST')) {
    expireOfficeSession()
  }
  const result = await response.json()
  if (!response.ok) throw new OfficeRequestError(result.message ?? result.detail?.message ??
    (Array.isArray(result.detail) ? result.detail.map((item: { msg: string }) => item.msg).join('；') : 'Office 请求失败。'), response.status)
  return result as T
}

export async function officeSession() {
  const result = await officeRequest<{ user: OfficeUser; csrfToken: string }>('/session')
  csrf = result.csrfToken
  return result.user
}

export async function loginOffice(credentials: Record<string, string>) {
  const result = await officeRequest<{ user: OfficeUser; csrfToken: string }>('/session', 'POST', credentials)
  csrf = result.csrfToken
  return result.user
}

export function officeCsrf() { return csrf }
