import type { NativeOperation } from './native-draft'
import { nativeAIProgressListener, mountNativeAIProgress, type NativeAIProgressListener } from './native-ai-progress'
import { Sparkles, X, Check, Trash2, Undo2, Redo2, createElement } from 'lucide'
import { bindOfficeAssistantPanel } from './office-assistant-panel'

type Scope = 'range' | 'workbook'
export type WorkbookAISelection = { sheetName: string; startRow: number; endRow: number; startColumn: number; endColumn: number }
type Context = { expectedSha256: string; operations: NativeOperation[]; selection: WorkbookAISelection; scope: Scope; label: string; cells: Record<string, { value?: unknown; formula?: string }> }
type Job = { editId: string; status: string; snapshotSha256: string; proposal?: { summary: string; operations: NativeOperation[] }; error?: { message: string } }
type Start = Pick<Context, 'expectedSha256' | 'operations' | 'selection' | 'scope'> & { instruction: string; clientRequestId: string }
export interface WorkbookNativeAIClient {
  start(payload: Start, signal: AbortSignal): Promise<Job>
  status(id: string, signal: AbortSignal): Promise<Job>
  events?: NativeAIProgressListener
  accept(id: string, payload: { expectedSha256: string; operations: NativeOperation[]; snapshotSha256: string }, signal: AbortSignal): Promise<{ operations: NativeOperation[] }>
  cancel(id: string): Promise<unknown>
  cancelRequest(clientRequestId: string): Promise<unknown>
}

/** XLSX 专属入口保留原生 session cookie 和同源 CSRF；文件身份来自可信宿主。 */
export function createWorkbookNativeAIClient(documentId: string, revision: number, csrfToken: string): WorkbookNativeAIClient {
  const base = '/reports/v1/native/' + encodeURIComponent(documentId) + '/' + revision + '/api/workbook-ai'
  const events = nativeAIProgressListener(base)
  async function request<T>(path: string, payload?: object, signal?: AbortSignal): Promise<T> {
    if (payload !== undefined && !csrfToken) throw new Error('缺少原生 AI 编辑授权，请重新打开')
    const response = await fetch(base + '/' + path, { method: payload === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store', signal, ...(path === 'cancel-request' ? { keepalive: true } : {}),
      ...(payload === undefined ? {} : { headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken }, body: JSON.stringify(payload) }) })
    const body = await response.json()
    if (!response.ok) throw new Error(body.detail?.message ?? ('AI 请求失败 (' + response.status + ')'))
    return body as T
  }
  return { start: (payload, signal) => request('start', payload, signal), status: (id, signal) => request(encodeURIComponent(id) + '?waitMs=20000', undefined, signal), events,
    accept: (id, payload, signal) => request(encodeURIComponent(id) + '/accept', payload, signal), cancel: id => request(encodeURIComponent(id) + '/cancel', {}),
    cancelRequest: clientRequestId => request('cancel-request', { clientRequestId }) }
}

export function mountWorkbookNativeAI(host: HTMLElement, options: { api: WorkbookNativeAIClient; context(scope: Scope): Promise<Context>; locked(): boolean; apply(operations: NativeOperation[]): Promise<void>; history?(direction: 'undo' | 'redo'): Promise<void>; accepting?(value: boolean): void }) {
  const panel = document.createElement('section'); panel.className = 'workbook-ai workbook-native-ai native-ai native-ai-panel'; panel.setAttribute('aria-label', 'XLSX AI 助手')
  panel.hidden = true
  panel.innerHTML = '<form class="native-ai-form"><label>AI 助手<textarea rows="2" maxlength="2000" placeholder="描述要如何修改所选单元格"></textarea></label><label>授权范围<select aria-label="AI 授权范围"><option value="range">当前选区</option><option value="workbook">整份工作簿</option></select></label><p class="native-ai-context"></p><button type="submit">生成候选</button><button class="native-ai-cancel" type="button" hidden>取消任务</button></form><p class="native-ai-status" role="status" aria-live="polite"></p><div class="native-ai-preview" hidden><strong></strong><ul></ul><button class="native-ai-accept" type="button">采纳到草稿</button><button class="native-ai-discard" type="button">放弃候选</button></div><p>选区支持值、公式和格式。整簿还支持工作表、行列、规则、批注、透视表及表格新增等现有结构化操作；不支持 AI 图表、图片、保护与主题。</p><button type="button" class="native-ai-undo">撤销草稿</button><button type="button" class="native-ai-redo">重做草稿</button>'
  for (const [selector, icon] of [['[type=submit]', Sparkles], ['.native-ai-cancel', X], ['.native-ai-accept', Check], ['.native-ai-discard', Trash2], ['.native-ai-undo', Undo2], ['.native-ai-redo', Redo2]] as const) {
    const svg = createElement(icon, { width: 16, height: 16, 'aria-hidden': 'true' }); panel.querySelector(selector)!.prepend(svg)
  }
  host.append(panel)
  const title = document.createElement('h3'); title.textContent = 'AI 助手'
  const closeButton = document.createElement('button'); closeButton.type = 'button'
  const progress = mountNativeAIProgress(panel)
  const form = panel.querySelector<HTMLFormElement>('form')!, instruction = panel.querySelector<HTMLTextAreaElement>('textarea')!, scope = panel.querySelector<HTMLSelectElement>('select')!
  const submit = panel.querySelector<HTMLButtonElement>('[type=submit]')!, cancel = panel.querySelector<HTMLButtonElement>('.native-ai-cancel')!
  const status = panel.querySelector<HTMLElement>('.native-ai-status')!, preview = panel.querySelector<HTMLElement>('.native-ai-preview')!, accept = panel.querySelector<HTMLButtonElement>('.native-ai-accept')!
  const help = [...panel.children].findLast(element => element.tagName === 'P') as HTMLElement
  const panelView = bindOfficeAssistantPanel(panel,{title,help,input:instruction,start:submit,cancel,close:closeButton,scope,onClose:()=>{void discard()}})
  let disposed = false, busy = false, accepting = false, generation = 0, activeId = '', activeRequestId = '', pending: Job | undefined, snapshot = '', quoted: Context | undefined
  let controller = new AbortController()
  let requestInput = ''
  const inputIdentity = () => JSON.stringify({instruction:instruction.value.trim(),scope:scope.value})
  const current = () => options.context(scope.value as Scope)
  const identity = (context: Context) => JSON.stringify({ expectedSha256: context.expectedSha256, operations: context.operations })
  const message = (error: unknown) => error instanceof Error ? error.message : 'AI 请求失败，人工草稿已保留'
  let refreshGeneration = 0
  async function refresh() {
    const turn = ++refreshGeneration
    if (disposed || busy) return
    try { const context = await current(); if (!disposed && turn === refreshGeneration && !busy) panel.querySelector<HTMLElement>('.native-ai-context')!.textContent = context.label }
    catch (error) { if (!disposed && turn === refreshGeneration) panel.querySelector<HTMLElement>('.native-ai-context')!.textContent = message(error) }
  }
  function show(job: Job) {
    pending = job
    preview.querySelector('strong')!.textContent = job.proposal!.summary
    const list = preview.querySelector('ul')!; list.replaceChildren()
    for (const operation of job.proposal!.operations) {
      const edits = operation.edits as { sheetName: string; row: number; column: number; writeValue?: boolean; cell?: { value?: unknown; formula?: string }; style?: unknown }[] | undefined
      if (operation.kind === 'applyCellEdits' && edits) for (const edit of edits) {
        let column = edit.column + 1, letters = ''
        while (column) { column--; letters = String.fromCharCode(65 + column % 26) + letters; column = Math.floor(column / 26) }
        const address = letters + (edit.row + 1), before = edit.sheetName === quoted?.selection.sheetName ? quoted.cells[address] : undefined
        const item = document.createElement('li')
        item.textContent = edit.sheetName + '!' + address + (edit.writeValue === false ? ' · 值与公式保持不变' : '：' + (edit.sheetName === quoted?.selection.sheetName ? String(before?.formula ?? before?.value ?? '空白') : '其他工作表原值') + ' → ' + String(edit.cell?.formula ?? edit.cell?.value ?? '空白')) + (edit.style ? ' · 格式 ' + JSON.stringify(edit.style) : '')
        list.append(item)
      } else {
        const item = document.createElement('li'); item.textContent = '结构化候选：' + operation.kind + ' · ' + JSON.stringify(operation); list.append(item)
      }
    }
    preview.hidden = false; accept.disabled = false
  }
  form.addEventListener('submit', async event => {
    event.preventDefault()
    if (disposed || busy || accepting || options.locked() || !instruction.value.trim()) return
    if (activeRequestId) void options.api.cancelRequest?.(activeRequestId).catch(() => {})
    const turn = ++generation; controller.abort(); controller = new AbortController()
    requestInput = inputIdentity()
    activeRequestId = crypto.randomUUID()
    busy = true; scope.disabled = true; submit.disabled = true; cancel.hidden = false; preview.hidden = true; pending = undefined; status.textContent = '正在规划并核验 XLSX 候选…'
    try {
      quoted = structuredClone(await current())
      if (disposed || turn !== generation) return
      snapshot = identity(quoted)
      panel.querySelector<HTMLElement>('.native-ai-context')!.textContent = '本次冻结范围：' + quoted.label
      const started = await options.api.start({ expectedSha256: quoted.expectedSha256, operations: quoted.operations, selection: quoted.selection, scope: quoted.scope, instruction: instruction.value.trim(), clientRequestId: activeRequestId }, controller.signal)
      if (disposed || turn !== generation) { if (started.editId) void options.api.cancel(started.editId).catch(() => {}); return }
      activeId = started.editId; cancel.hidden = false
      progress.start(options.api.events, started.editId, controller.signal, () => !disposed && turn === generation && !options.locked())
      let job = started
      while (job.status === 'running') {
        job = await options.api.status(started.editId, controller.signal)
        if (disposed || turn !== generation) return
      }
      if (job.status === 'succeeded' && job.proposal) { show(job); status.textContent = '候选已经引擎核验，请检查差异后明确采纳。' }
      else status.textContent = job.error?.message ?? 'AI 任务已取消，人工草稿已保留。'
    } catch (error) { if (!disposed && turn === generation) status.textContent = message(error) }
    finally { if (!disposed && turn === generation) { busy = false; scope.disabled = false; submit.disabled = false; cancel.hidden = true; activeId = '' } }
  })
  async function discard() {
    progress.stop()
    const id = activeId || pending?.editId, requestId = activeRequestId, turn = ++generation; controller.abort(); busy = false; pending = undefined; activeId = ''; activeRequestId = ''; preview.hidden = true; cancel.hidden = true; scope.disabled = false; submit.disabled = false
    status.textContent = 'AI 候选已放弃，人工草稿已保留。'
    const cancellations = [requestId ? options.api.cancelRequest?.(requestId) : undefined, id ? options.api.cancel(id) : undefined].filter(Boolean)
    const results = await Promise.allSettled(cancellations)
    const failure = results.find(result => result.status === 'rejected')
    if (failure?.status === 'rejected' && !disposed && turn === generation) status.textContent = message(failure.reason)
  }
  cancel.addEventListener('click', () => { void discard() })
  panel.querySelector('.native-ai-discard')!.addEventListener('click', () => { if (!accepting) void discard() })
  accept.addEventListener('click', async () => {
    if (!pending || accepting || disposed || options.locked()) return
    if (inputIdentity() !== requestInput) { void discard(); return }
    const turn = generation
    accepting = true; accept.disabled = true; options.accepting?.(true)
    try {
      const context = await current()
      if (disposed || turn !== generation || options.locked()) return
      if (identity(context) !== snapshot) throw new Error('完整草稿已变化，请重新生成候选。')
      if (inputIdentity() !== requestInput) throw new Error('填写要求已变化，请重新生成候选。')
      const accepted = await options.api.accept(pending.editId, { expectedSha256: context.expectedSha256, operations: context.operations, snapshotSha256: pending.snapshotSha256 }, controller.signal)
      if (disposed || turn !== generation || options.locked()) return
      const latest = await current()
      if (disposed || turn !== generation || options.locked()) return
      if (identity(latest) !== snapshot) throw new Error('完整草稿已变化，请重新生成候选。')
      if (inputIdentity() !== requestInput) throw new Error('填写要求已变化，请重新生成候选。')
      await options.apply(accepted.operations); pending = undefined; activeRequestId = ''; preview.hidden = true; status.textContent = '候选已加入草稿，可撤销或保存为新修订；业务事实仍需人工复核。'; refresh()
    } catch (error) { if (!disposed && turn === generation) { status.textContent = message(error); accept.disabled = false } }
    finally { accepting = false; options.accepting?.(false) }
  })
  for (const direction of ['undo', 'redo'] as const) panel.querySelector('.native-ai-' + direction)!.addEventListener('click', () => {
    if (!busy && !accepting && !options.locked()) void options.history?.(direction).then(() => refresh()).catch(error => { status.textContent = message(error) })
  })
  const invalidate = () => { if (busy || pending || accepting) void discard() }
  instruction.addEventListener('input', invalidate)
  scope.addEventListener('change', () => { invalidate(); void refresh() })
  function close() { if (!disposed) closeButton.click() }
  refresh()
  return { panel, close, open() { if (disposed) return; panelView.beforeOpen(); panel.hidden = false; instruction.focus({preventScroll:true}) }, refresh, dispose() { disposed = true; ++generation; panelView.dispose(); progress.stop(); controller.abort(); const id = activeId || pending?.editId; if (activeRequestId) void options.api.cancelRequest?.(activeRequestId).catch(() => {}); if (id) void options.api.cancel(id).catch(() => {}); panel.remove() } }
}
