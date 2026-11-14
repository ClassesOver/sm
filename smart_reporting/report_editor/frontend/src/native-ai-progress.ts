export interface NativeAIProgressEvent {
  sequence: number
  kind: 'phase' | 'content' | 'toolStarted' | 'toolCompleted' | 'terminal' | 'reset'
  label?: string
  delta?: string
  toolName?: string
  toolCallId?: string
  outcome?: 'success' | 'error'
  status?: string
}
export type NativeAIProgressListener = (id: string, onEvent: (event: NativeAIProgressEvent) => void, signal: AbortSignal) => Promise<void>

// 仅用于展示，名称对应四种文档 AI 已注册的真实工具。
const nativeAIToolLabels = new Map([
  ['list_form_fields','读取表单字段'], ['apply_ops','核验表单填值候选'],
  ['get_document_context', '读取文档上下文'], ['read_blocks', '读取文档内容块'],
  ['read_review_targets', '读取审阅目标'],
  ['read_comments', '读取批注'], ['read_revisions', '读取修订'],
  ['search_text', '搜索文本'], ['propose_operations', '提交候选修改'],
  ['get_workbook_context', '读取工作簿上下文'], ['read_range', '读取单元格区域'],
  ['read_cells', '读取单元格'], ['read_formats', '读取单元格格式'],
  ['read_sheet_features', '读取工作表功能'], ['find_cells', '查找单元格'],
  ['aggregate_range', '汇总单元格区域'], ['trace_precedents', '追踪引用单元格'],
  ['trace_dependents', '追踪从属单元格'], ['load_guide', '读取操作指南'],
  ['get_presentation_context', '读取演示文稿上下文'], ['read_slide', '读取幻灯片'],
  ['read_pages', '读取页面'], ['read_annotations', '读取批注'], ['get_outline', '读取文档大纲'],
  ['propose_replace_text', '提交文本替换建议'], ['propose_markup', '提交标记建议'],
  ['propose_reply', '提交批注回复建议'], ['skip_note', '跳过批注'],
  ['delete_markup', '提交删除标注建议'],
])

export const nativeAIToolLabel = (name: string) => nativeAIToolLabels.get(name) ?? name

export function nativeAIProgressListener(base: string): NativeAIProgressListener {
  return (id, onEvent, signal) => listenNativeAIProgress(base + '/' + encodeURIComponent(id) + '/events', onEvent, signal)
}

/** 只读取公开进度字段；推理事件、工具参数及未核验操作不进入界面。 */
export async function consumeNativeAIProgress(response: Response, onEvent: (event: NativeAIProgressEvent) => void, signal: AbortSignal, after = 0): Promise<{ after: number; terminal: boolean }> {
  if (!response.ok || !response.body || !response.headers.get('Content-Type')?.includes('text/event-stream')) throw new Error('AI 进度暂不可用')
  const reader = response.body.getReader(), decoder = new TextDecoder()
  let buffer = '', terminal = false
  const abort = () => { void reader.cancel().catch(() => {}) }
  signal.addEventListener('abort', abort, { once: true })
  try {
    while (!signal.aborted && !terminal) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      if (buffer.length > 131072) throw new Error('AI 进度数据过长')
      let boundary: RegExpExecArray | null
      while (!signal.aborted && !terminal && (boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index); buffer = buffer.slice(boundary.index + boundary[0].length)
        let id = '', type = '', data = ''
        for (const line of frame.split(/\r?\n/)) {
          const colon = line.indexOf(':')
          if (colon < 0) continue
          const field = line.slice(0, colon), text = line.slice(colon + 1).replace(/^ /, '')
          if (field === 'id') id = text
          if (field === 'event') type = text
          if (field === 'data') data += (data ? '\n' : '') + text
        }
        if (type !== 'progress') continue
        let raw: unknown
        try { raw = JSON.parse(data) } catch { continue }
        if (!raw || typeof raw !== 'object') continue
        const item = raw as Record<string, unknown>
        if (!Number.isSafeInteger(item.sequence) || Number(item.sequence) < 0
          || (item.kind !== 'reset' && Number(item.sequence) <= after) || String(item.sequence) !== id
          || !['phase', 'content', 'toolStarted', 'toolCompleted', 'terminal', 'reset'].includes(String(item.kind))) continue
        const event: NativeAIProgressEvent = { sequence: Number(item.sequence), kind: item.kind as NativeAIProgressEvent['kind'] }
        for (const field of ['label', 'toolName', 'toolCallId', 'status', 'delta'] as const) if (typeof item[field] === 'string') event[field] = item[field].slice(0, field === 'delta' ? 16384 : 256)
        if (item.outcome === 'success' || item.outcome === 'error') event.outcome = item.outcome
        after = event.sequence; terminal = event.kind === 'terminal'
        onEvent(event)
      }
    }
    return { after, terminal }
  } finally {
    signal.removeEventListener('abort', abort)
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

/** 断流最多重新连接两次，游标仅由已校验事件推进；不触发服务端取消。 */
export async function listenNativeAIProgress(url: string, onEvent: (event: NativeAIProgressEvent) => void, signal: AbortSignal): Promise<void> {
  let after = 0
  for (let attempt = 0; attempt < 3 && !signal.aborted; attempt++) {
    try {
      const response = await fetch(url + '?after=' + after, { method: 'GET', credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'text/event-stream' }, signal })
      const result = await consumeNativeAIProgress(response, event => { after = event.sequence; onEvent(event) }, signal, after)
      if (result.terminal) return
    } catch { if (signal.aborted) return }
  }
}

/** 草稿流始终与通过引擎核验的候选分开，且仅在用户勾选后展示。 */
export function mountNativeAIProgress(host: HTMLElement) {
  const section = document.createElement('details'), summary = document.createElement('summary'), list = document.createElement('ul')
  section.className = 'native-ai-progress'; section.hidden = true
  summary.textContent = '生成过程（未核验）'
  list.setAttribute('aria-label', 'AI 执行进度'); list.setAttribute('aria-live', 'polite')
  const label = document.createElement('label'), checkbox = document.createElement('input'), draft = document.createElement('pre')
  checkbox.type = 'checkbox'; label.append(checkbox, '显示生成中的草稿（未核验，不会自动采纳）')
  draft.hidden = true; draft.style.whiteSpace = 'pre-wrap'; draft.style.maxHeight = '12em'; draft.style.overflow = 'auto'
  checkbox.addEventListener('change', () => { draft.hidden = !checkbox.checked })
  section.append(summary, list, label, draft); host.append(section)
  let controller: AbortController | undefined, disconnect: (() => void) | undefined
  const toolItems = new Map<string, HTMLLIElement>()
  function stop() { controller?.abort(); disconnect?.(); controller = undefined; disconnect = undefined }
  function reset() { stop(); section.hidden = true; list.replaceChildren(); toolItems.clear(); draft.textContent = ''; checkbox.checked = false; draft.hidden = true }
  function start(listener: NativeAIProgressListener | undefined, id: string, signal: AbortSignal, current: () => boolean) {
    stop()
    if (!listener || signal.aborted || !current()) return
    const active = new AbortController(); controller = active
    const abort = () => active.abort()
    signal.addEventListener('abort', abort, { once: true }); disconnect = () => signal.removeEventListener('abort', abort)
    void listener(id, event => {
      if (active.signal.aborted) return
      if (!current()) { active.abort(); return }
      section.hidden = false; section.open = true
      if (event.kind === 'content') { draft.textContent = ((draft.textContent ?? '') + (event.delta ?? '')).slice(-12000); return }
      if (event.kind === 'reset') { list.replaceChildren(); toolItems.clear(); draft.textContent = '' }
      const toolLabel = event.label || nativeAIToolLabel(event.toolName ?? '') || '文档工具'
      if (event.kind === 'toolCompleted' && event.toolCallId) {
        const item = toolItems.get(event.toolCallId)
        if (item) {
          item.textContent = event.outcome === 'error'
            ? '工具执行失败：' + toolLabel
            : '工具已完成：' + toolLabel
          toolItems.delete(event.toolCallId)
          return
        }
      }
      const item = document.createElement('li')
      item.textContent = event.kind === 'toolStarted' ? '正在执行工具：' + toolLabel
        : event.kind === 'toolCompleted' ? (event.outcome === 'error' ? '工具执行失败：' : '工具已完成：') + toolLabel
        : event.kind === 'terminal' ? '生成结束，正在读取核验结果'
        : event.kind === 'reset' ? '已恢复最新进度，较早过程已省略' : (event.label || '正在处理文档')
      if (event.kind === 'toolStarted' && event.toolCallId) {
        item.dataset.toolCallId = event.toolCallId
        toolItems.set(event.toolCallId, item)
      }
      list.append(item)
      while (list.childElementCount > 30) {
        const first = list.firstElementChild as HTMLLIElement | null
        if (!first) break
        if (first.dataset.toolCallId) toolItems.delete(first.dataset.toolCallId)
        first.remove()
      }
    }, active.signal).catch(() => {})
  }
  return { start, stop, reset }
}
