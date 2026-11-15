import { afterEach, expect, it, vi } from 'vitest'
import type { NativeOperation } from './native-draft'
import { NativeApiError, type NativeWorkbookNavigation } from './native-api'
import { createWorkbookNativeAIClient, mountWorkbookNativeAI } from './workbook-native-ai'
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
function setup(navigate?: (target: NativeWorkbookNavigation, current: () => boolean) => Promise<void>) {
  const host = document.createElement('div'); document.body.append(host)
  let operations: NativeOperation[] = []
  const selection = { sheetName: 'Sheet', startRow: 0, endRow: 0, startColumn: 0, endColumn: 0 }
  const candidate = { editId: 'id', status: 'succeeded', snapshotSha256: 'b'.repeat(64), proposal: { summary: '修改选区', operations: [{ kind: 'applyCellEdits', edits: [{ sheetName: 'Sheet', row: 0, column: 0, writeValue: true, cell: { value: '候选值' } }] }] as NativeOperation[] } }
  const navigationCandidate = (operations: NativeOperation[] = []) => ({ ...candidate, proposal: { summary: '已请求定位', operations, navigation: { sheetName: 'Sheet', range: 'B2', startRow: 1, endRow: 1, startColumn: 1, endColumn: 1 } } })
  const api = { start: vi.fn(async (_payload: Parameters<ReturnType<typeof createWorkbookNativeAIClient>['start']>[0]) => candidate), status: vi.fn(async () => candidate), accept: vi.fn(async () => ({ operations: candidate.proposal.operations })), cancel: vi.fn(async () => ({})), cancelRequest: vi.fn(async () => ({})) }
  const apply = vi.fn(async (next: NativeOperation[]) => { operations = next })
  const context = vi.fn(async (scope: 'range' | 'workbook') => ({ expectedSha256: 'a'.repeat(64), operations, scope, selection, label: 'Sheet!A1', cells: { A1: { value: '人工值' } } }))
  const view = mountWorkbookNativeAI(host, { api, locked: () => false, context, apply, navigate })
  const submit = () => { host.querySelector('textarea')!.value = '改成候选值'; host.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true })) }
  return { host, api, apply, view, submit, context, candidate, selection, navigationCandidate, change: () => { operations = [{ kind: 'applyColumnWidths', sheetName: 'Sheet', entries: [] }] } }
}
it('resumes the same XLSX task after connection loss and a missing in-memory job', async () => {
  const { host, api, apply, view, submit, candidate } = setup()
  const editId = 'b'.repeat(64)
  api.start.mockResolvedValueOnce({ ...candidate, editId, status: 'running' })
    .mockResolvedValueOnce({ ...candidate, editId })
  api.status.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    .mockRejectedValueOnce(new NativeApiError(404, 'native_ai_job_missing', '任务不存在'))
  try {
    submit()
    await vi.waitFor(() => expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false), { timeout: 5000 })
    expect(api.status).toHaveBeenCalledTimes(2)
    expect(api.status).toHaveBeenNthCalledWith(1, editId, expect.any(AbortSignal))
    expect(api.status).toHaveBeenNthCalledWith(2, editId, expect.any(AbortSignal))
    expect(api.start).toHaveBeenCalledTimes(2)
    const [originalPayload] = api.start.mock.calls[0]!
    expect(api.start).toHaveBeenNthCalledWith(2, { ...originalPayload, resumeEditId: editId }, expect.any(AbortSignal))
    expect(api.accept).not.toHaveBeenCalled()
    expect(apply).not.toHaveBeenCalled()
    expect(host.textContent).toContain('候选值')
  } finally { view.dispose() }
})
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

it('navigation-only result awaits viewport confirmation and never offers adoption', async () => {
  let finish!: () => void
  const navigate = vi.fn((_target: NativeWorkbookNavigation, _current: () => boolean) => new Promise<void>(done => { finish = done }))
  const {host, api, apply, submit, view, navigationCandidate} = setup(navigate)
  api.start.mockResolvedValueOnce(navigationCandidate())
  try {
    submit()
    await vi.waitFor(() => expect(navigate).toHaveBeenCalledOnce())
    expect(api.start).toHaveBeenCalledWith(expect.objectContaining({navigationEnabled:true}), expect.any(AbortSignal))
    expect(host.querySelector('.native-ai-status')!.textContent).not.toContain('已定位到')
    finish()
    await vi.waitFor(() => expect(host.querySelector('.native-ai-status')!.textContent).toContain('已定位到 Sheet!B2'))
    expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(true)
    expect(api.accept).not.toHaveBeenCalled(); expect(apply).not.toHaveBeenCalled()
  } finally { view.dispose() }
})
it('failed navigation retains a separately adoptable edit candidate', async () => {
  const navigate = vi.fn(async () => { throw new Error('目标未能显示') })
  const {host, api, submit, view, navigationCandidate, candidate} = setup(navigate)
  api.start.mockResolvedValueOnce(navigationCandidate(candidate.proposal.operations))
  try {
    submit()
    await vi.waitFor(() => expect(host.querySelector('.native-ai-status')!.textContent).toContain('目标未能显示'))
    expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false)
    expect(api.accept).not.toHaveBeenCalled()
  } finally { view.dispose() }
})
it('changed view blocks delayed navigation while retaining edit candidate', async () => {
  const navigate = vi.fn(async () => {})
  const {host, api, submit, view, navigationCandidate, candidate, selection} = setup(navigate)
  api.start.mockImplementationOnce(async () => { selection.startRow=1; selection.endRow=1; return navigationCandidate(candidate.proposal.operations) })
  try {
    submit()
    await vi.waitFor(() => expect(host.querySelector('.native-ai-status')!.textContent).toContain('视图已变化'))
    expect(navigate).not.toHaveBeenCalled()
    expect(host.querySelector<HTMLElement>('.native-ai-preview')!.hidden).toBe(false)
  } finally { view.dispose() }
})
it('closing during navigation invalidates the host completion guard', async () => {
  let current!: () => boolean, finish!: () => void
  const navigate = vi.fn(async (_target: NativeWorkbookNavigation, guard: () => boolean) => { current=guard; await new Promise<void>(done=>{finish=done}) })
  const {host, api, submit, view, navigationCandidate} = setup(navigate)
  api.start.mockResolvedValueOnce(navigationCandidate())
  submit(); await vi.waitFor(() => expect(navigate).toHaveBeenCalledOnce())
  view.close(); expect(current()).toBe(false); finish()
  await new Promise(done=>setTimeout(done,20))
  expect(host.querySelector('.native-ai-status')!.textContent).not.toContain('已定位到')
  view.dispose()
})

it('successful navigation leaves mixed edits pending explicit adoption even after view changes', async () => {
  const navigate = vi.fn(async () => { selection.startRow=1; selection.endRow=1 })
  const {host, api, apply, submit, view, navigationCandidate, candidate, selection} = setup(navigate)
  api.start.mockResolvedValueOnce(navigationCandidate(candidate.proposal.operations))
  try {
    submit()
    await vi.waitFor(() => expect(host.querySelector('.native-ai-status')!.textContent).toContain('已定位到 Sheet!B2'))
    expect(apply).not.toHaveBeenCalled(); expect(api.accept).not.toHaveBeenCalled()
    host.querySelector<HTMLButtonElement>('.native-ai-accept')!.click()
    await vi.waitFor(() => expect(apply).toHaveBeenCalledOnce())
  } finally { view.dispose() }
})
it('changed draft blocks navigation and subsequent adoption', async () => {
  const navigate = vi.fn(async () => {})
  const {host, api, submit, view, navigationCandidate, candidate, change} = setup(navigate)
  api.start.mockImplementationOnce(async () => { change(); return navigationCandidate(candidate.proposal.operations) })
  try {
    submit()
    await vi.waitFor(() => expect(host.querySelector('.native-ai-status')!.textContent).toContain('草稿已变化'))
    expect(navigate).not.toHaveBeenCalled()
    host.querySelector<HTMLButtonElement>('.native-ai-accept')!.click()
    await vi.waitFor(() => expect(host.querySelector('.native-ai-status')!.textContent).toContain('草稿已变化'))
    expect(api.accept).not.toHaveBeenCalled()
  } finally { view.dispose() }
})
