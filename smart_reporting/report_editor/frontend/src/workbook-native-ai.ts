import { mountOfficeReadQueue } from './office-read-queue'
import { OfficeAssistantController } from './office-assistant-controller'
import type { NativeOperation } from './native-draft'
import { nativeAIProgressListener, mountNativeAIProgress, type NativeAIProgressListener } from './native-ai-progress'
import { Sparkles, X, Check, Trash2, Undo2, Redo2, createElement } from 'lucide'
import { bindOfficeAssistantPanel } from './office-assistant-panel'
import { NativeApiError, type NativeWorkbookNavigation } from './native-api'
import { missingNativeAITask, reconnectNativeAITask, temporaryConnectionFailure } from './native-ai-recovery'
import { requireWorkbookTranslation, workbookTranslationPrompt, type WorkbookTranslationLanguage } from './workbook-ai-translation'
import { formatAddress } from '../../../reporting/workbook_engine/packages/xlsx-engine/src/cell-address'

type Scope = 'range' | 'workbook'

function visibilityDescription(operation: NativeOperation): string | undefined {
  if (operation.kind !== 'applySheetOutline' || operation.summaryBelow !== undefined || operation.summaryRight !== undefined) return
  const rows = Array.isArray(operation.rows) && operation.columns === undefined
  const entries = rows ? operation.rows : operation.rows === undefined ? operation.columns : undefined
  if (!Array.isArray(entries) || !entries.length) return
  const { index, hidden } = entries[0]
  if (typeof hidden !== 'boolean' || !Number.isInteger(index) ||
      entries.some((entry, offset) => entry.level !== undefined || entry.hidden !== hidden || entry.index !== index + offset)) return
  const label = (value: number) => rows ? String(value + 1) : formatAddress(0, value).slice(0, -1)
  const range = entries.length === 1 ? label(index) : `${label(index)}–${label(index + entries.length - 1)}`
  return `${operation.sheetName} · ${hidden ? '隐藏' : '显示'}${rows ? '行' : '列'} ${range}`
}
export type WorkbookAISelection = { sheetName: string; startRow: number; endRow: number; startColumn: number; endColumn: number }
type Context = { expectedSha256: string; operations: NativeOperation[]; selection: WorkbookAISelection; scope: Scope; label: string; cells: Record<string, { value?: unknown; formula?: string }> }
type Job = { editId: string; status: string; snapshotSha256: string; proposal?: { summary: string; operations: NativeOperation[]; navigation?: NativeWorkbookNavigation }; error?: { message: string } }
type Start = Pick<Context, 'expectedSha256' | 'operations' | 'selection' | 'scope'> & { instruction: string; clientRequestId: string; resumeEditId?: string; navigationEnabled?: boolean }
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
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new NativeApiError(response.status, body?.detail?.code ?? '', body?.detail?.message ?? ('AI 请求失败 (' + response.status + ')'))
    }
    return await response.json() as T
  }
  return { start: (payload, signal) => request('start', payload, signal), status: (id, signal) => request(encodeURIComponent(id) + '?waitMs=20000', undefined, signal), events,
    accept: (id, payload, signal) => request(encodeURIComponent(id) + '/accept', payload, signal), cancel: id => request(encodeURIComponent(id) + '/cancel', {}),
    cancelRequest: clientRequestId => request('cancel-request', { clientRequestId }) }
}

export function mountWorkbookNativeAI(host: HTMLElement, options: { api: WorkbookNativeAIClient; context(scope: Scope): Promise<Context>; locked(): boolean; navigate?(target: NativeWorkbookNavigation, current: () => boolean): Promise<void>; apply(operations: NativeOperation[]): Promise<void>; history?(direction: 'undo' | 'redo'): Promise<void>; accepting?(value: boolean): void }) {
  const panel = document.createElement('section'); panel.className = 'workbook-ai workbook-native-ai native-ai native-ai-panel'; panel.setAttribute('aria-label', 'XLSX AI 助手')
  panel.hidden = true
  panel.innerHTML = '<form class="native-ai-form"><label>AI 助手<textarea rows="2" maxlength="2000" placeholder="描述要修改的内容；图表请明确指定目标"></textarea></label><label>授权范围<select aria-label="AI 授权范围"><option value="range">当前选区</option><option value="workbook">整份工作簿</option></select></label><p class="native-ai-context"></p><button type="submit">生成候选</button><button class="native-ai-cancel" type="button" hidden>取消任务</button></form><p class="native-ai-status" role="status" aria-live="polite"></p><div class="native-ai-preview" hidden><strong></strong><ul></ul><button class="native-ai-accept" type="button">采纳到草稿</button><button class="native-ai-discard" type="button">放弃候选</button></div><p>选区支持值、公式和格式。整簿还支持工作表、行列、规则、批注、透视表、表格以及已有图表的格式编辑和删除；请明确指定图表，检查候选后采纳并保存。暂不支持 AI 新建图表、替换图表数据、图片、保护与主题。</p><button type="button" class="native-ai-undo">撤销草稿</button><button type="button" class="native-ai-redo">重做草稿</button>'
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
  const queue = mountOfficeReadQueue(instruction, submitQueued)
  const panelView = bindOfficeAssistantPanel(panel,{title,help,input:instruction,start:submit,cancel,close:closeButton,scope,
    queue:queue.host,onQueue:enqueue,onClose:()=>{ queue.hold(); void discard() }})
  let disposed = false, busy = false, accepting = false, generation = 0, activeRequestId = '', pending: Job | undefined, snapshot = '', quoted: Context | undefined
  const tasks = new OfficeAssistantController({ ...options.api, id:(job: Job)=>job.editId, running:(job: Job)=>job.status==='running' })
  let requestScope: Scope
  type QueueTarget = { scope: Scope; identity: Promise<string | undefined> }
  const targetIdentity = (context: Context) => JSON.stringify([context.expectedSha256, context.scope, context.selection])
  const current = () => options.context(scope.value as Scope)
  const identity = (context: Context) => JSON.stringify({ expectedSha256: context.expectedSha256, operations: context.operations })
  const message = (error: unknown) => error instanceof Error ? error.message : 'AI 请求失败，人工草稿已保留'
  function refreshQueue() {
    const active = busy || accepting || !!pending
    submit.disabled = active
    scope.disabled = active
    queue.setBusy(active)
  }
  function enqueue() {
    const selectedScope = scope.value as Scope
    const identity = options.context(selectedScope).then(targetIdentity, () => undefined)
    queue.enqueue({ scope: selectedScope, identity })
  }
  function submitQueued(text: string, target: QueueTarget) {
    if (disposed || busy || accepting || pending || options.locked()) return false
    void start(text, false, target)
    return true
  }
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
      const visibility = visibilityDescription(operation)
      const edits = operation.edits as { sheetName: string; row: number; column: number; writeValue?: boolean; cell?: { value?: unknown; formula?: string }; style?: unknown }[] | undefined
      if (operation.kind === 'applyCellEdits' && edits) for (const edit of edits) {
        let column = edit.column + 1, letters = ''
        while (column) { column--; letters = String.fromCharCode(65 + column % 26) + letters; column = Math.floor(column / 26) }
        const address = letters + (edit.row + 1), before = edit.sheetName === quoted?.selection.sheetName ? quoted.cells[address] : undefined
        const item = document.createElement('li')
        item.textContent = edit.sheetName + '!' + address + (edit.writeValue === false ? ' · 值与公式保持不变' : '：' + (edit.sheetName === quoted?.selection.sheetName ? String(before?.formula ?? before?.value ?? '空白') : '其他工作表原值') + ' → ' + String(edit.cell?.formula ?? edit.cell?.value ?? '空白')) + (edit.style ? ' · 格式 ' + JSON.stringify(edit.style) : '')
        list.append(item)
      } else if (operation.kind === 'clearCellRange') {
        const item = document.createElement('li')
        item.textContent = `${operation.sheetName}!${operation.range} · 清空值和公式，保留格式`
        list.append(item)
      } else if (operation.kind === 'replaceRangeText') {
        const item = document.createElement('li')
        const mode = operation.wholeCell ? '整格匹配' : '部分匹配'
        const casing = operation.matchCase ? '区分大小写' : '忽略大小写'
        item.textContent = `${operation.sheetName}!${operation.range} · ${JSON.stringify(operation.find)} → ${JSON.stringify(operation.replace)}（${mode}，${casing}）`
        list.append(item)
      } else if (visibility) {
        const item = document.createElement('li')
        item.textContent = visibility
        list.append(item)
      } else {
        const item = document.createElement('li'); item.textContent = '结构化候选：' + operation.kind + ' · ' + JSON.stringify(operation); list.append(item)
      }
    }
    preview.hidden = false; accept.disabled = false
  }
  async function start(text: string, translation = false, target?: QueueTarget) {
    if (disposed || busy || accepting || pending || options.locked() || !text) return
    panelView.beforeTask()
    if (activeRequestId) void tasks.cancel().catch(() => {})
    const turn = ++generation
    requestScope = scope.value as Scope
    activeRequestId = crypto.randomUUID()
    busy = true; cancel.hidden = false; preview.hidden = true; pending = undefined; status.textContent = '正在规划并核验 XLSX 候选…'
    refreshQueue()
    try {
      const queuedIdentity = target ? await target.identity : undefined
      if (disposed || turn !== generation) return
      quoted = structuredClone(await options.context(requestScope))
      if (disposed || turn !== generation || options.locked()) return
      if (target && (target.scope !== requestScope || queuedIdentity !== targetIdentity(quoted))) {
        status.textContent = '排队指令的授权范围或目标已变化，请选中目标后重新发送。'
        return
      }
      snapshot = identity(quoted)
      panel.querySelector<HTMLElement>('.native-ai-context')!.textContent = '本次冻结范围：' + quoted.label
      const payload = { expectedSha256: quoted.expectedSha256, operations: structuredClone(quoted.operations),
        selection: structuredClone(quoted.selection), scope: quoted.scope, ...(options.navigate ? {navigationEnabled:true} : {}), instruction: text, clientRequestId: activeRequestId }
      const job = await tasks.run(payload, activeRequestId, (started, signal) => {
        cancel.hidden = false
        progress.start(options.api.events, started.editId, signal, () => !disposed && turn === generation && !options.locked())
      }, (started, error, signal) => {
        if (/^[0-9a-f]{64}$/.test(started.editId) && (missingNativeAITask(error) || temporaryConnectionFailure(error))) {
          return reconnectNativeAITask(
            signal => options.api.status(started.editId, signal),
            signal => options.api.start({...payload,resumeEditId:started.editId}, signal),
            error, signal,
          )
        }
      })
      if (!job || disposed || turn !== generation) return
      if (job.status === 'succeeded' && job.proposal) {
        if (translation) requireWorkbookTranslation(job.proposal.operations, quoted.selection, quoted.cells)
        const hasEdits = job.proposal.operations.length > 0
        let navigationStatus = ''
        if (job.proposal.navigation) {
          try {
            if (!options.navigate) throw new Error('当前视图不支持定位')
            const latest = await current()
            if (disposed || turn !== generation || options.locked()) return
            if (identity(latest) !== snapshot) throw new Error('完整草稿已变化，定位未执行')
            if (JSON.stringify(latest.selection) !== JSON.stringify(quoted.selection)) throw new Error('当前视图已变化，定位未执行')
            const target = job.proposal.navigation
            await options.navigate(target, () => !disposed && turn === generation && !options.locked() && scope.value === requestScope)
            if (disposed || turn !== generation || options.locked()) return
            navigationStatus = `已定位到 ${target.sheetName}!${target.range}。`
          } catch (error) {
            if (disposed || turn !== generation) return
            navigationStatus = '定位未完成：' + message(error) + '。'
          }
        }
        if (hasEdits) show(job)
        else { tasks.release(); pending = undefined; activeRequestId = ''; preview.hidden = true }
        status.textContent = navigationStatus + (hasEdits ? '候选已经引擎核验，请检查差异后明确采纳。' : '文档与草稿未修改。')
      }
      else status.textContent = job.error?.message ?? 'AI 任务已取消，人工草稿已保留。'
    } catch (error) { if (!disposed && turn === generation) status.textContent = message(error) }
    finally { if (!disposed && turn === generation) { busy = false; cancel.hidden = true; refreshQueue() } }
  }
  form.addEventListener('submit', event => { event.preventDefault(); void start(instruction.value.trim()) })
  async function discard() {
    progress.stop()
    const turn = ++generation; busy = false; pending = undefined; activeRequestId = ''; preview.hidden = true; cancel.hidden = true
    refreshQueue()
    status.textContent = 'AI 候选已放弃，人工草稿已保留。'
    const results = await Promise.allSettled([tasks.cancel()])
    const failure = results.find(result => result.status === 'rejected')
    if (failure?.status === 'rejected' && !disposed && turn === generation) status.textContent = message(failure.reason)
  }
  cancel.addEventListener('click', () => { queue.hold(); void discard() })
  panel.querySelector('.native-ai-discard')!.addEventListener('click', () => { if (!accepting) void discard() })
  accept.addEventListener('click', async () => {
    if (!pending || accepting || disposed || options.locked()) return
    if (scope.value !== requestScope) { void discard(); return }
    const turn = generation
    accepting = true; accept.disabled = true; options.accepting?.(true)
    try {
      const context = await current()
      if (disposed || turn !== generation || options.locked()) return
      if (identity(context) !== snapshot) throw new Error('完整草稿已变化，请重新生成候选。')
      if (scope.value !== requestScope) throw new Error('授权范围已变化，请重新生成候选。')
      const candidate = pending
      const accepted = await tasks.accept(signal => options.api.accept(candidate.editId, { expectedSha256: context.expectedSha256, operations: context.operations, snapshotSha256: candidate.snapshotSha256 }, signal))
      if (!accepted) return
      if (disposed || turn !== generation || options.locked()) return
      const latest = await current()
      if (disposed || turn !== generation || options.locked()) return
      if (identity(latest) !== snapshot) throw new Error('完整草稿已变化，请重新生成候选。')
      if (scope.value !== requestScope) throw new Error('授权范围已变化，请重新生成候选。')
      await options.apply(accepted.operations); tasks.release(); pending = undefined; activeRequestId = ''; preview.hidden = true; status.textContent = '候选已加入草稿，可撤销或保存为新修订；业务事实仍需人工复核。'; refresh()
    } catch (error) { if (!disposed && turn === generation) { status.textContent = message(error); accept.disabled = false } }
    finally { accepting = false; options.accepting?.(false); if (!disposed) refreshQueue() }
  })
  for (const direction of ['undo', 'redo'] as const) panel.querySelector('.native-ai-' + direction)!.addEventListener('click', () => {
    if (!busy && !accepting && !options.locked()) void options.history?.(direction).then(() => refresh()).catch(error => { status.textContent = message(error) })
  })
  const invalidate = () => { if (busy || pending || accepting) { queue.hold(); void discard() } }
  scope.addEventListener('change', () => { invalidate(); void refresh() })
  function close() { if (!disposed) closeButton.click() }
  function open() { if (disposed) return; panelView.beforeOpen(); panel.hidden = false; instruction.focus({preventScroll:true}) }
  function translate(language: WorkbookTranslationLanguage) {
    if (disposed || busy || accepting || pending || options.locked()) return false
    open()
    scope.value = 'range'
    instruction.value = workbookTranslationPrompt(language)
    void start(instruction.value.trim(), true)
    return true
  }
  refresh()
  return { panel, close, open, translate, refresh, dispose() { disposed = true; ++generation; panelView.dispose(); progress.stop(); void tasks.cancel().catch(() => {}); queue.dispose(); panel.remove() } }
}
