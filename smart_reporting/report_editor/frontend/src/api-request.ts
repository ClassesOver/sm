export async function requestJson<T>(url: string, init: RequestInit = {}, csrfCookieName?: string): Promise<T> {
  const headers = new Headers({ 'Content-Type': 'application/json' })
  if ((init.method ?? 'GET').toUpperCase() === 'POST' && csrfCookieName) {
    const token = document.cookie.split('; ').find(value => value.startsWith(`${csrfCookieName}=`))?.split('=', 2)[1] ?? ''
    headers.set('X-CSRF-Token', decodeURIComponent(token))
  }
  new Headers(init.headers).forEach((value, name) => headers.set(name, value))
  const response = await fetch(url, { credentials: 'same-origin', ...init, headers })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail?.message ?? `请求失败 (${response.status})`)
  }
  return response.json() as Promise<T>
}
