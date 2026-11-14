import './binary-refresh.css'
import type { ExportResult, DataRefreshTask, RefreshDeliveryRecovery } from './api'

export interface BinaryRefreshCapability { available: boolean; reason?: string; message?: string }
export interface BinaryRefreshSource {
  route: string; reportId: string; revision: number; format: 'pdf' | 'docx' | 'xlsx' | 'pptx'
  contextSha256: string; sha256: string
}
type Task = (Omit<DataRefreshTask, 'result'> & { result?: { issueCodes?: string[] }; errorCode?: string; sourceIssue?: string }) | RefreshDeliveryRecovery
type Delivery = { task: Task; delivery: ExportResult }
export interface BinaryRefreshApi {
  submit(payload: { requestId: string; expectedBinarySha256: string }, signal?: AbortSignal): Promise<Task>
  status(requestId: string, signal?: AbortSignal): Promise<Task>
  delivery(taskId: string, signal?: AbortSignal): Promise<Delivery>
}
export interface BinaryRefreshEditor {
  saving(): boolean
  blocked(): boolean
  flush(): void | Promise<void>
  dirty(): boolean
  save(): Promise<unknown>
  setRefreshing(value: boolean): void
}

// 精确服务端 context digest 是缓存身份的一部分；相同二进制不等于相同授权上下文。
export function mountBinaryRefresh(host: HTMLElement, source: BinaryRefreshSource, capability: BinaryRefreshCapability | undefined,
  api: BinaryRefreshApi, editor: BinaryRefreshEditor) {
  const key = 'report-binary-refresh-v1:' + JSON.stringify(source)
  let requestId: string | undefined
  try {
    const cached: unknown = JSON.parse(localStorage.getItem(key) ?? 'null')
    if (cached && typeof cached === 'object' && 'requestId' in cached && typeof cached.requestId === 'string'
      && /^[a-zA-Z0-9_-]{1,128}$/.test(cached.requestId)) requestId = cached.requestId
  } catch { /* 禁用或损坏的本地存储不影响当前页面读取。 */ }
  const section = document.createElement('section')
  section.className = 'binary-refresh'
  section.setAttribute('aria-label', '数据库刷新报告')
  const message = document.createElement('p'); message.setAttribute('role', 'status')
  const result = document.createElement('div'); result.className = 'binary-refresh-result'; result.setAttribute('aria-live', 'polite')
  const action = document.createElement('button'); action.type = 'button'; action.dataset.action = 'binary-refresh'; action.textContent = '按数据库刷新报告'
  const read = document.createElement('button'); read.type = 'button'; read.textContent = '读取原刷新任务'
  const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = '重试原刷新任务'; retry.hidden = true
  section.append(message, result)
  if (capability?.available) section.prepend(action)
  section.append(read, retry)
  if (capability?.available || requestId) {
    const meta = host.querySelector('.report-meta')
    if (meta) meta.insertAdjacentElement('afterend', section)
    else host.prepend(section)
  }
  const abort = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  let disposed = false, busy = false, handling = false
  let task: Task | undefined
  let retryable = Boolean(requestId)
  const persist = () => {
    try { localStorage.setItem(key, JSON.stringify({ requestId, taskId: task?.taskId })) }
    catch { message.textContent = '浏览器无法保存任务身份；请保留当前页面以读取原任务。' }
  }
  const update = () => {
    action.disabled = handling || busy || editor.blocked() || !capability?.available || Boolean(requestId)
    read.hidden = !requestId; read.disabled = handling || busy || editor.saving()
    retry.hidden = !requestId || !retryable || !capability?.available
    retry.disabled = handling || busy || editor.blocked()
  }
  const setBusy = (value: boolean) => { busy = value; editor.setRefreshing(value); update() }
  const addText = (text: string | undefined) => { if (text) { const p = document.createElement('p'); p.textContent = text; result.append(p) } }
  const showTask = (value: Task) => {
    task = value; persist(); result.replaceChildren()
    addText(`刷新任务：${value.status}`)
    addText('businessApproval=not_performed（未进行人工业务批准）')
    addText(value.errorCode)
    if (value.status === 'unavailable') addText('刷新输入未核验（inputVerified=false）；只恢复可信交付，不表示验收通过。')
    else {
      addText(value.sourceIssue)
      addText(`执行状态：${value.execution?.status ?? 'unknown'}`)
      for (const code of [...(value.result?.issueCodes ?? []), ...(value.execution?.issueCodes ?? [])]) addText(code)
    }
    retryable = value.status === 'pending' && value.execution?.status === 'not_dispatched'
  }
  const showDelivery = (delivery: ExportResult) => {
    addText(delivery.validation?.ok === true && task?.status !== 'unavailable' ? '文件验收通过；未进行人工业务批准' : '文件验收未通过或尚未核验')
    for (const issue of delivery.validation?.issues ?? []) addText([issue.code, issue.message].filter(Boolean).join('：'))
    const artifact = source.format === 'docx' ? delivery.word : delivery[source.format]
    if (artifact?.downloadUrl) {
      try {
        const url = new URL(artifact.downloadUrl, location.origin)
        if (!['https:', 'http:'].includes(url.protocol)) return
        const link = document.createElement('a'); link.href = artifact.downloadUrl; link.referrerPolicy = 'no-referrer'
        link.textContent = '下载 ' + (source.format === 'docx' ? 'Word' : source.format.toUpperCase())
        result.append(link)
      } catch { /* 不把无效链接作为可信下载。 */ }
    }
  }
  const readTask = async () => {
    if (!requestId || disposed) return
    const value = await api.status(requestId, abort.signal)
    if (disposed) return
    showTask(value)
    if (value.status !== 'pending' || value.execution?.status === 'completed') {
      const response = await api.delivery(value.taskId, abort.signal)
      if (disposed) return
      showTask(response.task); showDelivery(response.delivery)
    } else if (['pending', 'running'].includes(value.execution?.status)) {
      timer = setTimeout(() => { void recover() }, 2000)
    }
  }
  const recover = async () => {
    if (disposed || handling || busy || !requestId) return
    if (editor.saving()) { timer = setTimeout(() => { void recover() }, 2000); return }
    clearTimeout(timer); setBusy(true)
    try { await readTask() }
    catch (error) { if (!disposed) message.textContent = '原任务读取未完成：' + errorMessage(error) }
    finally { if (!disposed) setBusy(false) }
  }
  const submit = async () => {
    if (!requestId) return
    clearTimeout(timer); setBusy(true)
    try {
      const value = await api.submit({requestId, expectedBinarySha256: source.sha256}, abort.signal)
      if (!disposed) { showTask(value); await readTask() }
    } catch (error) {
      if (!disposed) {
        message.textContent = '提交结果未知，先读取同一 requestId：' + errorMessage(error)
        retryable = true
        try { await readTask() } catch (readError) { if (!disposed) addText('原任务读取未完成：' + errorMessage(readError)) }
      }
    } finally { if (!disposed) setBusy(false) }
  }
  action.onclick = async () => {
    if (handling || busy || editor.blocked() || requestId || !capability?.available) return
    handling = true; update()
    try {
      await editor.flush()
      if (disposed || editor.blocked()) return
      if (editor.dirty()) {
        message.textContent = '当前稿有修改，先保存；请打开已登记的新修订后再显式刷新。'
        await editor.save()
        return // save 可能捕获失败；任何结果都不能在旧会话继续派发。
      }
      requestId = crypto.randomUUID(); persist()
      await submit()
    } catch (error) { if (!disposed) message.textContent = errorMessage(error) }
    finally { handling = false; if (!disposed) update() }
  }
  read.onclick = () => { void recover() }
  retry.onclick = async () => {
    if (disposed || handling || busy || !requestId || !capability?.available || editor.blocked()) return
    // 重试原意图不读取草稿、不保存、不换 source/ID；先查询原任务。
    handling = true; setBusy(true)
    try {
      try { await readTask() } catch (error) { message.textContent = '原任务状态未知：' + errorMessage(error) }
      if (retryable && !disposed) await submit()
    } finally { handling = false; if (!disposed) setBusy(false) }
  }
  const dispose = () => { disposed = true; clearTimeout(timer); abort.abort(); window.removeEventListener('pagehide', dispose) }
  window.addEventListener('pagehide', dispose, {once: true})
  update()
  if (requestId) void recover()
  return { update, get busy() { return busy }, dispose }
}

export interface OfficeRefreshContext {
  reportId: string; revision: number; contextSha256: string; sha256: string; dataRefresh?: BinaryRefreshCapability
}
export async function mountOfficeReportRefresh(host: HTMLElement, format: 'xlsx' | 'pptx',
  request: <T>(path: string, init?: RequestInit) => Promise<T>, editor: BinaryRefreshEditor) {
  const route = location.pathname.replace(/\/$/, '')
  const match = /^\/reports\/v1\/(workbooks|slides)\/([^/]+)\/(\d+)$/.exec(route)
  if (!match || match[1] !== (format === 'xlsx' ? 'workbooks' : 'slides')) return
  try {
    const context = await request<OfficeRefreshContext>('context')
    if (context.reportId !== decodeURIComponent(match[2]) || context.revision !== Number(match[3])
      || !/^[a-f0-9]{64}$/.test(context.contextSha256) || !/^[a-f0-9]{64}$/.test(context.sha256)) return
    return mountBinaryRefresh(host, {route, reportId: context.reportId, revision: context.revision, format,
      contextSha256: context.contextSha256, sha256: context.sha256}, context.dataRefresh, {
      submit: (payload, signal) => request('recalculations', {method:'POST',body:JSON.stringify(payload),signal}),
      status: (id, signal) => request(`recalculations/by-request/${encodeURIComponent(id)}`, {signal}),
      delivery: (id, signal) => request(`recalculations/${encodeURIComponent(id)}/delivery`, {signal}),
    }, editor)
  } catch { /* Context 读取失败不阻断原有文件编辑与下载。 */ }
}
function errorMessage(error: unknown) { return error instanceof Error ? error.message : '请求失败' }

// 恢复读取可能早于预览完成；释放临时锁时恢复原状态，不能粘住 loading 的禁用值。
export function binaryRefreshLock(surface: HTMLElement, save: HTMLButtonElement, closed: () => boolean) {
  let active = false, previousInert = false, previousSave = false
  return (value: boolean) => {
    if (value && !active) { previousInert = surface.inert; previousSave = save.disabled }
    if (value) { surface.inert = true; save.disabled = true }
    else if (active) { surface.inert = previousInert; save.disabled = previousSave || closed() }
    active = value
  }
}
