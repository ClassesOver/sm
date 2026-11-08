import { NativeApiError } from './native-api'

type NativeFormat = 'docx' | 'pdf'
interface NativeLaunchOptions {
  basePath: string
  csrfToken: string
  formats: NativeFormat[]
  onError?: (error: NativeApiError) => void
  navigate?: (url: string) => void
  requestId?: () => string
}

/** 从已发布文件派生独立分支；当前 Markdown 的未保存修改不参与此操作。 */
export function attachNativeLaunchActions(container: HTMLElement, options: NativeLaunchOptions): () => void {
  if (!/^\/reports\/v1\/editor\/[^/]+\/[1-9]\d*\/?$/.test(options.basePath)) throw new Error('报告编辑路径无效')
  const basePath = options.basePath.replace(/\/$/, '')
  const group = document.createElement('section')
  group.className = 'native-launch-actions'
  group.setAttribute('aria-label', '编辑已发布文件')
  const status = document.createElement('span')
  status.setAttribute('role', 'status')
  const navigate = options.navigate ?? ((url: string) => window.location.assign(url))
  const newId = options.requestId ?? (() => crypto.randomUUID())
  const ids = new Map<NativeFormat, string>()
  let disposed = false
  const pending = new Set<NativeFormat>()
  for (const format of [...new Set(options.formats)]) {
    if (format !== 'docx' && format !== 'pdf') continue
    const button = document.createElement('button')
    button.type = 'button'
    button.textContent = `编辑已发布 ${format === 'docx' ? 'Word' : 'PDF'}`
    button.title = '编辑已发布文件；正文中尚未导出的修改不会带入'
    button.addEventListener('click', async () => {
      if (disposed || pending.has(format)) return
      pending.add(format)
      button.disabled = true
      status.textContent = '正在打开已发布文件'
      try {
        if (!options.csrfToken) throw new NativeApiError(403, 'native_csrf_missing', '编辑授权已失效，请重新打开报告')
        if (!ids.has(format)) ids.set(format, newId())
        const response = await fetch(`${basePath}/api/native/open`, {
          method: 'POST', credentials: 'same-origin', cache: 'no-store',
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': options.csrfToken },
          body: JSON.stringify({ format, requestId: ids.get(format) }),
        })
        const result = await response.json().catch(() => ({}))
        if (!response.ok) throw new NativeApiError(response.status, result.detail?.code ?? 'native_open_failed',
          result.detail?.message ?? `打开失败 (${response.status})`)
        const raw = result.editor?.url
        if (typeof raw !== 'string') throw new NativeApiError(502, 'native_editor_url_invalid', '原生编辑入口无效，请重试')
        const url = new URL(raw, window.location.origin)
        if (url.origin !== window.location.origin || !url.pathname.startsWith('/reports/v1/native/open/')) {
          throw new NativeApiError(502, 'native_editor_url_invalid', '原生编辑入口无效，请重试')
        }
        if (!disposed) { status.textContent = '已创建独立文件分支'; navigate(raw) }
      } catch (error) {
        const detail = error instanceof NativeApiError ? error : new NativeApiError(0, 'native_open_failed',
          error instanceof Error ? error.message : '原生编辑入口暂不可用，请重试')
        if (!disposed) { status.textContent = detail.message; options.onError?.(detail) }
      } finally {
        pending.delete(format)
        button.disabled = false
      }
    })
    group.append(button)
  }
  if (group.childElementCount) {
    group.append(status)
    container.append(group)
  }
  return () => { disposed = true; group.remove() }
}
