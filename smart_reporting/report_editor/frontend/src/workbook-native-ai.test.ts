import { afterEach, expect, it, vi } from 'vitest'
import type { NativeOperation } from './native-draft'
import { createWorkbookNativeAIClient, mountWorkbookNativeAI } from './workbook-native-ai'
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
function setup() {
  const host = document.createElement('div'); document.body.append(host)
  let operations: NativeOperation[] = []
  const selection = { sheetName: 'Sheet', startRow: 0, endRow: 0, startColumn: 0, endColumn: 0 }
  const candidate = { editId: 'id', status: 'succeeded', snapshotSha256: 'b'.repeat(64), proposal: { summary: '修改选区', operations: [{ kind: 'applyCellEdits', edits: [{ sheetName: 'Sheet', row: 0, column: 0, writeValue: true, cell: { value: '候选值' } }] }] } }
  const api = { start: vi.fn(async () => candidate), status: vi.fn(async () => candidate), accept: vi.fn(async () => ({ operations: candidate.proposal.operations })), cancel: vi.fn(async () => ({})), cancelRequest: vi.fn(async () => ({})) }
  const apply = vi.fn(async (next: NativeOperation[]) => { operations = next })
  const context = vi.fn(async (scope: 'range' | 'workbook') => ({ expectedSha256: 'a'.repeat(64), operations, scope, selection, label: 'Sheet!A1', cells: { A1: { value: '人工值' } } }))
  const view = mountWorkbookNativeAI(host, { api, locked: () => false, context, apply })
  const submit = () => { host.querySelector('textarea')!.value = '改成候选值'; host.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true })) }
  return { host, api, apply, view, submit, context, change: () => { operations = [{ kind: 'applyColumnWidths', sheetName: 'Sheet', entries: [] }] } }
}
it('freezes range, previews Chinese differences with real icons and adopts explicitly', async () => {
  const { host, api, apply, view, submit } = setup(); submit()
  await vi.waitFor(() => expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false))
  expect(api.start).toHaveBeenCalledWith(expect.objectContaining({ scope: 'range', selection: expect.objectContaining({ sheetName: 'Sheet' }) }), expect.any(AbortSignal))
  expect(host.textContent).toContain('人工值'); expect(host.textContent).toContain('候选值'); expect(apply).not.toHaveBeenCalled()
  expect([...host.querySelectorAll('button')].every(button => button.querySelector('svg[aria-hidden=true]'))).toBe(true)
  host.querySelector<HTMLButtonElement>('.native-ai-accept')!.click()
  await vi.waitFor(() => expect(apply).toHaveBeenCalledOnce()); view.dispose()
})
it('rejects a changed complete draft before acceptance', async () => {
  const { host, api, apply, view, submit, change } = setup(); submit()
  await vi.waitFor(() => expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false))
  change(); host.querySelector<HTMLButtonElement>('.native-ai-accept')!.click()
  await vi.waitFor(() => expect(host.textContent).toContain('草稿已变化'))
  expect(api.accept).not.toHaveBeenCalled(); expect(apply).not.toHaveBeenCalled(); view.dispose()
})
it('cancels before start receipt and cleans up the late server job', async () => {
  const { api, view, submit } = setup(); let finish!: (value: never) => void
  api.start.mockImplementationOnce(() => new Promise(done => { finish = done }))
  submit(); await vi.waitFor(() => expect(api.start).toHaveBeenCalledOnce()); view.dispose()
  expect(api.cancelRequest).toHaveBeenCalledWith(expect.any(String))
  finish({ editId: 'late', status: 'running' } as never)
  await vi.waitFor(() => expect(api.cancel).toHaveBeenCalledWith('late'))
})
it('uses dedicated native CSRF and keepalive cancellation', async () => {
  const fetcher = vi.fn<typeof fetch>(async () => new Response('{}')); vi.stubGlobal('fetch', fetcher)
  const api = createWorkbookNativeAIClient('book', 1, 'token'); await api.cancelRequest('early')
  expect(fetcher).toHaveBeenCalledWith('/reports/v1/native/book/1/api/workbook-ai/cancel-request', expect.objectContaining({ keepalive: true, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'token' } }))
})

it.each(['before_accept', 'after_accept'])('does not resume adoption after disposal during %s snapshot', async phase => {
  const { host, api, apply, view, submit, context } = setup(); submit()
  await vi.waitFor(() => expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false))
  const snapshot = await context('range'); let finish!: (value: typeof snapshot) => void
  const pause = () => context.mockImplementationOnce(() => new Promise(done => { finish = done }))
  if (phase === 'before_accept') pause()
  else api.accept.mockImplementationOnce(async () => { pause(); return { operations: [] } })
  host.querySelector<HTMLButtonElement>('.native-ai-accept')!.click()
  await vi.waitFor(() => expect(finish).toBeTypeOf('function')); view.dispose(); finish(snapshot)
  await new Promise(done => setTimeout(done, 20))
  expect(apply).not.toHaveBeenCalled()
  if (phase === 'before_accept') expect(api.accept).not.toHaveBeenCalled()
})

it('打开助手只聚焦现有输入，不提交 AI 任务', () => {
  const { host, api, view } = setup()
  view.open()
  expect(document.activeElement).toBe(host.querySelector('textarea'))
  expect(api.start).not.toHaveBeenCalled()
  view.dispose()
})
