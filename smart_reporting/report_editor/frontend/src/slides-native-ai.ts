import {createElement,Sparkles,CircleStop,Check,X} from 'lucide'
import {bindOfficeAssistantPanel} from './office-assistant-panel'
import {NATIVE_CHART_TYPES} from './slides-native-chart-edit'
import type {SlidesAIObject} from './slides-native-ai-context'
import type { NativeOperation } from './native-draft'
import { nativeAIProgressListener, type NativeAIProgressListener } from './native-ai-progress'
import { mountNativeAIProgress } from './native-ai-progress'

type Scope = 'object' | 'slide' | 'deck' | 'notes' | 'deckNotes'
type Selection = { slideIndex: number; elementId?: string }
type Context = { expectedSha256: string; operations: NativeOperation[]; selection: Selection[]; scope: 'selection' | 'deck' | 'notes'; label: string; objects: SlidesAIObject[]; notes?: {slideIndex:number;text:string}[] }
type Job = { editId: string; status: string; snapshotSha256: string; proposal?: { summary: string; operations: NativeOperation[] }; error?: { message: string } }
type Start = Pick<Context, 'expectedSha256' | 'operations' | 'selection' | 'scope'> & { instruction: string; clientRequestId: string }
export interface SlidesNativeAIClient {
  start(payload: Start, signal: AbortSignal): Promise<Job>
  status(id: string, signal: AbortSignal): Promise<Job>
  events?: NativeAIProgressListener
  accept(id: string, payload: { expectedSha256: string; operations: NativeOperation[]; snapshotSha256: string }, signal: AbortSignal): Promise<{ operations: NativeOperation[] }>
  cancel(id: string): Promise<unknown>
  cancelRequest(clientRequestId: string): Promise<unknown>
}

/** PPTX 专属入口保留原生 session cookie 和同源 CSRF；文件身份来自可信宿主。 */
export function createSlidesNativeAIClient(documentId: string, revision: number, csrfToken: string): SlidesNativeAIClient {
  const base = '/reports/v1/native/' + encodeURIComponent(documentId) + '/' + revision + '/api/slides-ai'
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

export function mountSlidesNativeAI(host: HTMLElement, options: { api: SlidesNativeAIClient; context(scope: Scope): Context; locked(): boolean; apply(operations: NativeOperation[]): void; accepting?(value: boolean): void }) {
  const panel = document.createElement('section'); panel.className = 'slides-ai slides-native-ai native-ai native-ai-panel'; panel.hidden = true; panel.setAttribute('aria-label', 'PPTX AI 助手')
  panel.innerHTML = '<form class="native-ai-form"><label>AI 助手<textarea rows="2" maxlength="2000" placeholder="描述要如何修改文字、表格单元格、图表数据、演讲者备注或布局"></textarea></label><label>授权范围<select aria-label="AI 授权范围"><option value="object">当前对象</option><option value="slide">当前页可编辑对象</option><option value="deck">整份演示文稿画布</option><option value="notes">当前页演讲者备注</option><option value="deckNotes">整稿演讲者备注</option></select></label><p class="native-ai-context"></p><button type="submit">生成候选</button><button class="native-ai-cancel" type="button" hidden>取消任务</button></form><p class="native-ai-status" role="status" aria-live="polite"></p><div class="native-ai-preview" hidden><strong></strong><ul></ul><button class="native-ai-accept" type="button">采纳到草稿</button><button class="native-ai-discard" type="button">放弃候选</button></div><p>支持已有可编辑文字、字号、字体、颜色、粗斜体、下划线、删除线及对象位置大小；整稿范围可调整页序和商务主题。支持已有表格可写单元格文字、可安全编辑图表的数据与类型；演讲者备注需单独选择授权范围，画布授权不包含备注；图片、母版与动画不在 AI 修改范围内。</p>'
  for(const [selector,icon] of [['[type=submit]',Sparkles],['.native-ai-cancel',CircleStop],['.native-ai-accept',Check],['.native-ai-discard',X]] as const)panel.querySelector(selector)!.prepend(createElement(icon,{'aria-hidden':'true',width:18,height:18}))
  host.append(panel)
  const progress = mountNativeAIProgress(panel)
  const form = panel.querySelector<HTMLFormElement>('form')!, instruction = panel.querySelector<HTMLTextAreaElement>('textarea')!, scope = panel.querySelector<HTMLSelectElement>('select')!
  const submit = panel.querySelector<HTMLButtonElement>('[type=submit]')!, cancel = panel.querySelector<HTMLButtonElement>('.native-ai-cancel')!
  const status = panel.querySelector<HTMLElement>('.native-ai-status')!, preview = panel.querySelector<HTMLElement>('.native-ai-preview')!, accept = panel.querySelector<HTMLButtonElement>('.native-ai-accept')!
  const title = document.createElement('h3'); title.textContent = 'AI 助手 · 编辑选区'
  const closeButton = document.createElement('button'); closeButton.type = 'button'; closeButton.className = 'native-ai-close'
  const help = [...panel.children].findLast(element => element.tagName === 'P') as HTMLElement
  const panelView = bindOfficeAssistantPanel(panel, {title,help,input:instruction,start:submit,cancel,close:closeButton,onClose:()=>{void discard()}})
  let disposed = false, busy = false, accepting = false, generation = 0, activeId = '', activeRequestId = '', pending: Job | undefined, snapshot = '', quoted: Context | undefined
  let controller = new AbortController()
  const current = () => options.context(scope.value as Scope)
  const identity = (context: Context) => JSON.stringify({ expectedSha256: context.expectedSha256, operations: context.operations, selection: context.selection, scope: context.scope, instruction: instruction.value.trim() })
  const message = (error: unknown) => error instanceof Error ? error.message : 'AI 请求失败，人工草稿已保留'
  function refresh() {
    if (disposed) return
    try { const context = current(); panel.querySelector<HTMLElement>('.native-ai-context')!.textContent = context.label + '：' + (context.scope === 'notes' ? context.notes?.map(note => note.text || '（空白备注）').join(' / ') : context.objects.map(object => object.text).join(' / '))?.slice(0, 600) }
    catch (error) { panel.querySelector<HTMLElement>('.native-ai-context')!.textContent = message(error) }
  }
  function show(job: Job) {
    pending = job
    preview.querySelector('strong')!.textContent = job.proposal!.summary
    const list = preview.querySelector('ul')!; list.replaceChildren()
    for (const operation of job.proposal!.operations) {
      const edits = [...(operation.edits as object[] ?? []), ...(operation.textFormatting as object[] ?? [])] as (Selection & { text?: string; geometry?: unknown; fontSizePt?: number; fontFamily?: string; color?: string; bold?: boolean; italic?: boolean; underline?: boolean; strike?: boolean })[]
      for (const edit of edits ?? []) {
        const before = quoted?.objects.find(object => object.slideIndex === edit.slideIndex && object.elementId === edit.elementId)
        const item = document.createElement('li')
        const styles = [edit.fontSizePt !== undefined ? `字号 ${edit.fontSizePt}` : '', edit.fontFamily ? `字体 ${edit.fontFamily}` : '', edit.color ? `颜色 ${edit.color}` : '', ...(['bold', 'italic', 'underline', 'strike'] as const).map((key, index) => edit[key] === undefined ? '' : (edit[key] ? '启用' : '取消') + ['粗体', '斜体', '下划线', '删除线'][index])].filter(Boolean).join('，')
        item.textContent = '第 ' + (edit.slideIndex + 1) + ' 页 · ' + (before?.name || edit.elementId) + (edit.text !== undefined ? '：' + (before?.text ?? '') + ' → ' + edit.text : '') + (edit.geometry ? ' · 位置大小 ' + JSON.stringify(edit.geometry) : '') + (styles ? ' · ' + styles : '')
        list.append(item)
      }
      for(const edit of (operation.tableCells as (Selection & {row:number;col:number;text:string})[]|undefined)??[]){
        const before=quoted?.objects.find(object=>object.slideIndex===edit.slideIndex&&object.elementId===edit.elementId),item=document.createElement('li')
        item.textContent='第'+(edit.slideIndex+1)+'页 表格 '+(before?.name??edit.elementId)+' 第'+(edit.row+1)+'行'+(edit.col+1)+'列：'+(before?.tableCells?.[edit.row]?.[edit.col]??'')+' → '+edit.text;list.append(item)
      }
      for(const edit of (operation.chartEdits as (Selection & {kind?:string;categories?:string[];series?:{name:string;values:number[]}[]})[]|undefined)??[]){
        const before=quoted?.objects.find(object=>object.slideIndex===edit.slideIndex&&object.elementId===edit.elementId),item=document.createElement('li')
        const kind=(value?:string|null)=>NATIVE_CHART_TYPES.find(([key])=>key===value)?.[1]??value??'未提供'
        const series=(value?:{name:string;values:number[]}[]|null)=>value?.map(row=>row.name+'：'+row.values.join('、')).join('；')??''
        item.textContent='第'+(edit.slideIndex+1)+'页 图表 '+(before?.name??edit.elementId)+(edit.kind?'；类型：'+kind(before?.chartKind)+' → '+kind(edit.kind):'')+(edit.categories?'；类别：'+(before?.chartCategories?.join('、')??'')+' → '+edit.categories.join('、'):'')+(edit.series?'；序列：'+series(before?.chartSeries)+' → '+series(edit.series):'');list.append(item)
      }
      for(const edit of (operation.notesEdits as {slideIndex:number;text:string}[]|undefined)??[]){
        const item=document.createElement('li'),before=quoted?.notes?.find(note=>note.slideIndex===edit.slideIndex)
        item.textContent='第'+(edit.slideIndex+1)+'页 · 演讲者备注：'+(before?.text||'（空白）')+' → '+(edit.text||'（清空）');list.append(item)
      }
      if (operation.order) { const item = document.createElement('li'); item.textContent = '候选页序：' + (operation.order as number[]).map(index => index + 1).join(' → '); list.append(item) }
      if (operation.theme) { const item = document.createElement('li'); item.textContent = '候选主题：' + ({ executive: '执行汇报', clinical: '临床医疗', modern: '现代商务' } as Record<string, string>)[String(operation.theme)]; list.append(item) }
    }
    preview.hidden = false; accept.disabled = false
  }
  form.addEventListener('submit', async event => {
    event.preventDefault()
    if (disposed || busy || accepting || options.locked() || !instruction.value.trim()) return
    if (activeRequestId) void options.api.cancelRequest?.(activeRequestId).catch(() => {})
    const turn = ++generation; controller.abort(); controller = new AbortController()
    activeRequestId = crypto.randomUUID()
    busy = true; submit.disabled = true; cancel.hidden = false; preview.hidden = true; pending = undefined; status.textContent = '正在规划并核验 PPTX 候选…'
    try {
      quoted = structuredClone(current()); snapshot = identity(quoted)
      if (quoted.scope !== 'deck' && !quoted.selection.length) throw new Error('请选择可编辑文字、表格或图表对象')
      const started = await options.api.start({ expectedSha256: quoted.expectedSha256, operations: quoted.operations, selection: quoted.selection, scope: quoted.scope, instruction: instruction.value.trim(), clientRequestId: activeRequestId }, controller.signal)
      if (disposed || turn !== generation) { if (started.editId) void options.api.cancel(started.editId).catch(() => {}); return }
      activeId = started.editId; cancel.hidden = false
      progress.start(options.api.events, started.editId, controller.signal, () => !disposed && turn === generation && !options.locked())
      let job = started
      while (job.status === 'running') {
        job = await options.api.status(started.editId, controller.signal)
        if (disposed || turn !== generation) return
      }
      if (options.locked() || identity(current()) !== snapshot) throw new Error('完整草稿或授权范围已变化，请重新生成候选。')
      if (job.status === 'succeeded' && job.proposal) { show(job); status.textContent = '候选已经引擎核验，请检查差异后明确采纳。' }
      else status.textContent = job.error?.message ?? 'AI 任务已取消，人工草稿已保留。'
    } catch (error) { if (!disposed && turn === generation) status.textContent = message(error) }
    finally { if (!disposed && turn === generation) { busy = false; submit.disabled = false; cancel.hidden = true; activeId = '' } }
  })
  async function discard() {
    progress.stop()
    const id = activeId || pending?.editId, requestId = activeRequestId, turn = ++generation; controller.abort(); busy = false; pending = undefined; activeId = ''; activeRequestId = ''; preview.hidden = true; cancel.hidden = true; submit.disabled = false
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
    const turn = generation
    accepting = true; accept.disabled = true; options.accepting?.(true)
    try {
      const context = current()
      if (identity(context) !== snapshot) throw new Error('完整草稿已变化，请重新生成候选。')
      const accepted = await options.api.accept(pending.editId, { expectedSha256: context.expectedSha256, operations: context.operations, snapshotSha256: pending.snapshotSha256 }, controller.signal)
      if (disposed || turn !== generation || options.locked()) return
      if (identity(current()) !== snapshot) throw new Error('完整草稿已变化，请重新生成候选。')
      options.apply(accepted.operations); pending = undefined; activeRequestId = ''; preview.hidden = true; status.textContent = '候选已加入草稿，可撤销或保存为新修订；业务事实仍需人工复核。'; refresh()
    } catch (error) { if (!disposed && turn === generation) { status.textContent = message(error); accept.disabled = false } }
    finally { accepting = false; options.accepting?.(false) }
  })
  const invalidate = () => { if (activeRequestId || pending || busy) void discard(); refresh() }
  instruction.addEventListener('input', invalidate)
  scope.addEventListener('change', invalidate)
  refresh()
  return { panel, open() { if (disposed) return; panelView.beforeOpen(); panel.hidden = false; refresh(); panel.scrollIntoView?.({block:'nearest'}); instruction.focus({preventScroll:true}) }, close() { if (!disposed) closeButton.click() }, refresh, dispose() { panelView.dispose(); disposed = true; ++generation; progress.stop(); controller.abort(); const id = activeId || pending?.editId; if (activeRequestId) void options.api.cancelRequest?.(activeRequestId).catch(() => {}); if (id) void options.api.cancel(id).catch(() => {}); panel.remove() } }
}
