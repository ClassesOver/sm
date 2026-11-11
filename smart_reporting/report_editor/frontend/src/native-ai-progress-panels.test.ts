import { afterEach, expect, it, vi } from 'vitest'
import { bindNativeAI } from './native-ai'
import { NativeDraft } from './native-draft'
import { mountSlidesNativeAI } from './slides-native-ai'
import { mountWorkbookNativeAI } from './workbook-native-ai'
import { createNativeApi } from './native-api'
import { createSlidesNativeAIClient } from './slides-native-ai'
import { createWorkbookNativeAIClient } from './workbook-native-ai'
import type { NativeAIProgressEvent } from './native-ai-progress'

afterEach(() => { vi.unstubAllGlobals(); document.body.replaceChildren(); localStorage.clear() })
it.each(['docx', 'pdf', 'pptx', 'xlsx'] as const)('%s streams tool progress without adopting unverified content and rejects stale events after cancel', async format => {
  const host = document.createElement('div'); document.body.append(host)
  let emit!: (event: NativeAIProgressEvent) => void, signal!: AbortSignal
  const events = vi.fn(async (_id, callback, activeSignal) => { emit = callback; signal = activeSignal })
  const running = { editId: 'job', status: 'running', snapshotSha256: 'snapshot' }
  const start = vi.fn(async () => running), status = vi.fn(() => new Promise<never>(() => {})), cancel = vi.fn(async () => ({})), apply = vi.fn()
  let binding: { dispose(): void }
  if (format === 'docx' || format === 'pdf') {
    const draft = new NativeDraft({ documentId: 'progress-' + format, revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'db', companyId: 'c', userId: 'u', threadId: 't' } }, localStorage)
    const api = { aiStart: start, aiStatus: status, aiCancel: cancel, aiEvents: events }
    const view = bindNativeAI(host, { api: api as never, draft, format, view: { refresh: vi.fn() }, onDraftChange: apply })
    view.setSelection(format === 'docx' ? [{ blockId: 'p' }] : [{ pageId: 'p', objectId: 'o' }]); binding = view
  } else {
    const api = { start, status, cancel, cancelRequest: cancel, events, accept: vi.fn() }
    binding = format === 'pptx'
      ? mountSlidesNativeAI(host, { api: api as never, locked: () => false, apply, context: () => ({ expectedSha256: 'a'.repeat(64), operations: [], selection: [{ slideIndex: 0, elementId: 'o' }], scope: 'selection', label: '当前对象', objects: [] }) })
      : mountWorkbookNativeAI(host, { api: api as never, locked: () => false, apply, context: async () => ({ expectedSha256: 'a'.repeat(64), operations: [], selection: { sheetName: 'Sheet', startRow: 0, endRow: 0, startColumn: 0, endColumn: 0 }, scope: 'range', label: 'A1', cells: {} }) })
  }
  host.querySelector('textarea')!.value = '调整内容'
  if (format === 'docx' || format === 'pdf') host.querySelector<HTMLButtonElement>('[data-ai=start]')!.click()
  else host.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  await vi.waitFor(() => expect(events).toHaveBeenCalledOnce())
  emit({ sequence: 1, kind: 'toolStarted', toolName: 'read_document' })
  emit({ sequence: 2, kind: 'content', delta: '未核验模型草稿' })
  emit({ sequence: 3, kind: 'terminal', status: 'succeeded' })
  expect(host.textContent).toContain('正在执行工具'); expect(host.textContent).toContain('未核验')
  expect(apply).not.toHaveBeenCalled()
  const accept = host.querySelector<HTMLButtonElement>('[data-ai=accept], .native-ai-accept')!
  expect(accept.disabled || accept.closest<HTMLElement>('.native-ai-preview')?.hidden).toBeTruthy()
  host.querySelector<HTMLButtonElement>('[data-ai=cancel], .native-ai-cancel')!.click()
  expect(signal.aborted).toBe(true)
  emit({ sequence: 4, kind: 'phase', label: '旧任务污染' })
  expect(host.textContent).not.toContain('旧任务污染'); expect(cancel).toHaveBeenCalled()
  binding.dispose()
})
it.each(['docx', 'pptx', 'xlsx'])('%s progress client uses encoded task route and same-origin read-only SSE', async format => {
  const fetcher = vi.fn(async () => new Response('id: 1\nevent: progress\ndata: {"sequence":1,"kind":"terminal","status":"succeeded"}\n\n', { headers: { 'Content-Type': 'text/event-stream' } }))
  vi.stubGlobal('fetch', fetcher)
  const callback = vi.fn(), signal = new AbortController().signal
  if (format === 'docx') await createNativeApi('doc', 1).aiEvents!('a/b', callback, signal)
  else if (format === 'pptx') await createSlidesNativeAIClient('doc', 1, '').events!('a/b', callback, signal)
  else await createWorkbookNativeAIClient('doc', 1, '').events!('a/b', callback, signal)
  const route = format === 'docx' ? 'ai' : format === 'pptx' ? 'slides-ai' : 'workbook-ai'
  expect(fetcher).toHaveBeenCalledWith('/reports/v1/native/doc/1/api/' + route + '/a%2Fb/events?after=0', expect.objectContaining({ method: 'GET', credentials: 'same-origin', signal }))
  expect(callback).toHaveBeenCalledWith(expect.objectContaining({ kind: 'terminal' }))
})
