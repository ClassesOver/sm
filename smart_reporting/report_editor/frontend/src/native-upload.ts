export interface NativeUploadAuthorization { thread: string; capability: string }

/** 宿主按当前登录会话取得短期凭据；组件不存储凭据，也不从文件或表单推导身份。 */
export function createNativeUploader(container: HTMLElement, options: {
  getAuthorization(): Promise<NativeUploadAuthorization>
  requestId?: () => string
}) {
  const form = document.createElement('form')
  form.className = 'native-uploader'
  form.setAttribute('aria-label', '上传文件编辑')
  const input = document.createElement('input')
  input.type = 'file'; input.accept = '.pdf,.docx,.xlsx,.pptx'
  input.setAttribute('aria-label', '选择 PDF、Word、Excel 或 PowerPoint 文件')
  const submit = document.createElement('button')
  submit.type = 'submit'; submit.textContent = '上传并打开编辑器'
  const status = document.createElement('p')
  status.setAttribute('role', 'status')
  form.append(input, submit, status); container.append(form)
  const abort = new AbortController()
  let selected: File | undefined, requestId = '', disposed = false, busy = false
  input.onchange = () => {
    selected = input.files?.[0]
    requestId = (options.requestId ?? (() => crypto.randomUUID?.() ?? Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')))()
    status.replaceChildren()
  }
  form.onsubmit = async event => {
    event.preventDefault()
    if (disposed || busy) return
    if (!selected) { status.textContent = '请选择一个文件'; return }
    if (!selected.size || selected.size > 24 * 1024 * 1024) { status.textContent = '文件必须为 1 字节至 24 MiB'; return }
    busy = true; input.disabled = true; submit.disabled = true; status.textContent = '正在上传并核验文件'
    try {
      const authorization = await options.getAuthorization()
      if (disposed) return
      if (!authorization.thread || !authorization.capability) throw new Error('上传授权暂不可用，请从工作区重新打开')
      const body = new FormData()
      body.append('requestId', requestId); body.append('file', selected)
      const response = await fetch('/reports/v1/native/import', { method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'X-Workspace-Thread': authorization.thread, 'X-Workspace-Capability': authorization.capability }, body, signal: abort.signal })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail?.message ?? '上传失败，请检查文件后重试')
      const url = new URL(result.editor?.url, window.location.origin)
      if (url.origin !== window.location.origin || !/^\/reports\/v1\/native\/open\/[^/]+$/.test(url.pathname)) throw new Error('上传返回的编辑入口无效')
      status.replaceChildren('文件已登记，上传内容尚未进行业务核验。 ')
      const open = document.createElement('a')
      open.href = url.pathname; open.referrerPolicy = 'no-referrer'; open.textContent = '打开文件编辑器'
      status.append(open)
    } catch (error) { if (!disposed) status.textContent = error instanceof Error ? error.message : '上传失败，可重试' }
    finally { busy = false; if (!disposed) { input.disabled = false; submit.disabled = false } }
  }
  return { dispose() { disposed = true; abort.abort(); form.remove() } }
}
