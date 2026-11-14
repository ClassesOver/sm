import { afterEach, expect, it, vi } from 'vitest'
import { consumeNativeAIProgress, listenNativeAIProgress, mountNativeAIProgress, type NativeAIProgressEvent } from './native-ai-progress'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
const frame = (sequence: number, kind: string, extra = {}) => `id: ${sequence}\r\nevent: progress\r\ndata: ${JSON.stringify({ sequence, kind, ...extra })}\r\n\r\n`
function stream(chunks: string[]) {
  const encoder = new TextEncoder()
  return new Response(new ReadableStream({ start(controller) { for (const chunk of chunks) controller.enqueue(encoder.encode(chunk)); controller.close() } }), { headers: { 'Content-Type': 'text/event-stream' } })
}
it('parses split SSE frames, rejects reasoning and duplicate events, and stops at terminal', async () => {
  const text = frame(1, 'toolStarted', { toolName: 'read_document' }) + frame(1, 'content', { delta: '重复' }) + frame(2, 'reasoning', { delta: '秘密' }) + frame(3, 'content', { delta: '<b>草稿</b>', reasoning: '秘密' }) + frame(4, 'terminal', { status: 'succeeded' }) + frame(5, 'content', { delta: '终态之后' })
  const events: NativeAIProgressEvent[] = []
  const result = await consumeNativeAIProgress(stream([text.slice(0, 37), text.slice(37)]), event => events.push(event), new AbortController().signal)
  expect(result).toEqual({ after: 4, terminal: true })
  expect(events.map(event => event.kind)).toEqual(['toolStarted', 'content', 'terminal'])
  expect(JSON.stringify(events)).not.toContain('秘密'); expect(events[1].delta).toBe('<b>草稿</b>')
})
it('reconnects from the last cursor with same-origin GET and stops after a bounded retry budget', async () => {
  const fetcher = vi.fn(async () => stream([frame(1, 'phase', { label: '读取文档' })]))
  vi.stubGlobal('fetch', fetcher)
  const events: NativeAIProgressEvent[] = []
  await listenNativeAIProgress('/api/ai/job/events', event => events.push(event), new AbortController().signal)
  expect(fetcher).toHaveBeenCalledTimes(3)
  expect(fetcher.mock.calls.map(call => (call as unknown[])[0])).toEqual(['/api/ai/job/events?after=0', '/api/ai/job/events?after=1', '/api/ai/job/events?after=1'])
  expect(fetcher).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ method: 'GET', credentials: 'same-origin', signal: expect.any(AbortSignal) }))
  expect(events).toHaveLength(1)
})
it('accepts an explicit cursor reset before replay while rejecting ordinary backwards events', async () => {
  const events: NativeAIProgressEvent[] = []
  const response = stream([frame(-1, 'reset') + frame(2, 'content', { delta: '旧事件' })
    + frame(0, 'reset') + frame(1, 'phase') + frame(2, 'terminal', { status: 'completed' })])
  const result = await consumeNativeAIProgress(response, event => events.push(event), new AbortController().signal, 100)
  expect(result).toEqual({ after: 2, terminal: true })
  expect(events.map(event => event.kind)).toEqual(['reset', 'phase', 'terminal'])
  expect(events[0].sequence).toBe(0)
})
it('aborts consumption, releases the reader and ignores buffered events after cancellation', async () => {
  const controller = new AbortController(), cancel = vi.fn(), events: NativeAIProgressEvent[] = []
  const response = new Response(new ReadableStream({ start(source) { source.enqueue(new TextEncoder().encode(frame(1, 'phase') + frame(2, 'content', { delta: '旧内容' }))) }, cancel }), { headers: { 'Content-Type': 'text/event-stream' } })
  await consumeNativeAIProgress(response, event => { events.push(event); controller.abort() }, controller.signal)
  expect(events).toHaveLength(1); expect(cancel).toHaveBeenCalledOnce()
})
it('shows bounded unverified draft only on demand and permanently rejects events after save lock', () => {
  const host = document.createElement('div'), progress = mountNativeAIProgress(host)
  let emit!: (event: NativeAIProgressEvent) => void, locked = false
  const listener = vi.fn(async (_id, callback, _signal) => { emit = callback })
  progress.start(listener, 'id', new AbortController().signal, () => !locked)
  emit({ sequence: 1, kind: 'toolStarted', toolName: 'read_document' })
  emit({ sequence: 2, kind: 'toolCompleted', toolName: 'read_document' })
  emit({ sequence: 3, kind: 'content', delta: '<script>草稿</script>' })
  expect(host.textContent).toContain('正在执行工具'); expect(host.textContent).toContain('工具已完成')
  const draft = host.querySelector('pre')!
  expect(draft.hidden).toBe(true)
  const checkbox = host.querySelector<HTMLInputElement>('input[type=checkbox]')!
  checkbox.checked = true; checkbox.dispatchEvent(new Event('change'))
  expect(draft.hidden).toBe(false); expect(draft.textContent).toContain('<script>草稿</script>'); expect(host.querySelector('script')).toBeNull()
  locked = true; emit({ sequence: 4, kind: 'phase', label: '不得出现' })
  locked = false; emit({ sequence: 5, kind: 'phase', label: '解锁后仍不得出现' })
  expect(host.textContent).not.toContain('不得出现')
  progress.stop()
})

it('correlates repeated tool progress by call id and displays failure state without error details', () => {
  const host = document.createElement('div'), progress = mountNativeAIProgress(host)
  let emit!: (event: NativeAIProgressEvent) => void
  progress.start(vi.fn(async (_id, callback) => { emit = callback }), 'id', new AbortController().signal, () => true)
  emit({ sequence: 1, kind: 'toolStarted', toolName: 'read_pages', toolCallId: 'read-1' })
  emit({ sequence: 2, kind: 'toolStarted', toolName: 'read_pages', toolCallId: 'read-2' })
  emit({ sequence: 3, kind: 'toolCompleted', toolName: 'read_pages', toolCallId: 'read-1', outcome: 'success' })
  emit({ sequence: 4, kind: 'toolCompleted', toolName: 'read_pages', toolCallId: 'read-2', outcome: 'error' })
  const items = [...host.querySelectorAll('li')]
  expect(items).toHaveLength(2)
  expect(items.map(item => item.textContent)).toEqual(['工具已完成：读取页面', '工具执行失败：读取页面'])
  expect(items.map(item => item.dataset.toolCallId)).toEqual(['read-1', 'read-2'])
  progress.stop()
})

it.each([
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
])('shows Chinese progress for registered tool %s', (toolName, label) => {
  const host = document.createElement('div'), progress = mountNativeAIProgress(host)
  let emit!: (event: NativeAIProgressEvent) => void
  progress.start(vi.fn(async (_id, callback) => { emit = callback }), 'id', new AbortController().signal, () => true)
  emit({ sequence: 1, kind: 'toolStarted', toolName, toolCallId: 'call' })
  expect(host.querySelector('li')?.textContent).toBe('正在执行工具：' + label)
  emit({ sequence: 2, kind: 'toolCompleted', toolName, toolCallId: 'call', outcome: 'success' })
  emit({ sequence: 3, kind: 'toolCompleted', toolName, outcome: 'error' })
  expect([...host.querySelectorAll('li')].map(item => item.textContent)).toEqual(['工具已完成：' + label, '工具执行失败：' + label])
  progress.stop()
})

it('prefers event labels and retains unknown tool names and the unnamed tool fallback', () => {
  const host = document.createElement('div'), progress = mountNativeAIProgress(host)
  let emit!: (event: NativeAIProgressEvent) => void
  progress.start(vi.fn(async (_id, callback) => { emit = callback }), 'id', new AbortController().signal, () => true)
  emit({ sequence: 1, kind: 'toolStarted', toolName: 'read_pages', label: '读取选定页面', toolCallId: 'call' })
  expect(host.querySelector('li')?.textContent).toBe('正在执行工具：读取选定页面')
  emit({ sequence: 2, kind: 'toolCompleted', toolName: 'read_pages', label: '页面读取完毕', toolCallId: 'call' })
  emit({ sequence: 3, kind: 'toolStarted', toolName: 'future_tool' })
  emit({ sequence: 4, kind: 'toolCompleted', toolName: 'future_tool' })
  emit({ sequence: 5, kind: 'toolStarted' })
  expect([...host.querySelectorAll('li')].map(item => item.textContent)).toEqual([
    '工具已完成：页面读取完毕', '正在执行工具：future_tool', '工具已完成：future_tool', '正在执行工具：文档工具',
  ])
  progress.stop()
})
