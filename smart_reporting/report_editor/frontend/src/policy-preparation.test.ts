import { afterEach, expect, it, vi } from 'vitest'
import { ReportEditorClient } from './api'
import { mountPolicyAdoption } from './evidence-policy-adoption'

const original = { requestId: 'confirmed', parentRevision: 2, expectedSha256: 'a'.repeat(64),
  operation: 'adopt_policy', confirmation: { requestId: 'confirmed', previewHash: 'b'.repeat(64),
    targetPolicyVersion: { policyId: 'budget', revision: 2 }, questionChoices: [
      { questionId: 'budget', metricVersion: null, reason: '缺少指标' }] } }
const file = { path: '报表/智能分析/new/policy-adoption/analysis-preparation.json', size: 128, sha256: 'c'.repeat(64) }
const preparation = { taskId: 'task', runId: 'new', outputRevision: 3, stateVersion: 7,
  analysis: { status: 'awaiting_confirmation', identity: file, recoveryId: 'recovery-fixed', issueCodes: [] },
  document: { status: 'not_applicable', issueCodes: [] } }
const task = { taskId: 'task', status: 'pending', result: null,
  execution: { runId: 'original-run', status: 'error', issueCodes: [] } }
const recovery = { taskId: 'task', recoveryId: 'recovery-fixed', status: 'pending', deliveryStatus: 'pending', issueCodes: [] }
const mount = (fetcher: typeof fetch) => {
  sessionStorage.setItem('recovery-ui:policy-adoption', JSON.stringify(original))
  const root = document.createElement('div'); document.body.append(root)
  mountPolicyAdoption(root, { client: new ReportEditorClient('/editor', fetcher),
    storageKey: 'recovery-ui', getDraft: () => ({ markdown: '原报告' }) })
  return root
}
const click = (root: HTMLElement, action: string) => root.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!.click()
afterEach(() => { document.body.innerHTML = ''; sessionStorage.clear(); vi.restoreAllMocks() })

it('恢复响应丢失前缓存固定身份；重开只读同一票据，后台结束不冒充交付完成', async () => {
  const calls: { url: string; method: string }[] = []
  let delivered = false
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input); calls.push({ url, method: init?.method ?? 'GET' })
    if (url.endsWith('/preparation/resume')) {
      expect(JSON.parse(String(init?.body))).toEqual({ kind: 'analysis', identity: file, expectedStateVersion: 7 })
      const cache = sessionStorage.getItem('recovery-ui:policy-adoption:preparation-recovery')!
      expect(JSON.parse(cache)).toMatchObject({ taskId: 'task', recoveryId: 'recovery-fixed',
        confirmation: { kind: 'analysis', identity: file, expectedStateVersion: 7 } })
      throw new Error('response lost')
    }
    if (url.endsWith('/recoveries/recovery-fixed')) return Response.json({ ...recovery, status: 'completed',
      issueCodes: ['policy_recovery_completion_unconfirmed'] })
    if (url.endsWith('/preparation')) return Response.json(preparation)
    return Response.json({ ...task, status: delivered ? 'completed' : 'pending' })
  })
  let root = mount(fetcher as typeof fetch)
  click(root, 'status')
  await vi.waitFor(() => expect(root.querySelector('[data-action="preparation-read"]')).not.toBeNull())
  click(root, 'preparation-read')
  await vi.waitFor(() => expect(root.textContent).toContain('确认分析准备并继续'))
  expect(calls.every(call => call.method === 'GET')).toBe(true)
  expect(root.textContent).toContain('128')
  click(root, 'preparation-resume')
  await vi.waitFor(() => expect(root.textContent).toContain('续跑结果未知'))
  expect(root.querySelector('[data-action="preparation-resume"]')).toBeNull()
  root.remove(); root = mount(fetcher as typeof fetch)
  click(root, 'status')
  await vi.waitFor(() => expect(root.querySelector('[data-action="recovery-read"]')).not.toBeNull())
  click(root, 'recovery-read')
  await vi.waitFor(() => expect(root.textContent).toContain('报告交付尚未确认'))
  expect(calls.filter(call => call.method === 'POST')).toHaveLength(1)
  expect(calls.at(-1)?.url).toBe('/editor/api/recalculations/task/preparation/recoveries/recovery-fixed')
  delivered = true; click(root, 'status')
  await vi.waitFor(() => expect(root.textContent).not.toContain('报告交付尚未确认'))
  expect(root.textContent).toContain('新报告已生成')
})

it.each(['running', 'paused', 'unknown'])('原任务状态%s时只核对准备文件，不提供继续执行', async status => {
  const fetcher = vi.fn(async (input: RequestInfo | URL) => Response.json(String(input).endsWith('/preparation')
    ? preparation : { ...task, execution: { ...task.execution, status } }))
  const root = mount(fetcher as typeof fetch); click(root, 'status')
  await vi.waitFor(() => expect(root.querySelector('[data-action="preparation-read"]')).not.toBeNull())
  click(root, 'preparation-read')
  await vi.waitFor(() => expect(root.textContent).toContain('尚未确认结束'))
  expect(root.querySelector('[data-action="preparation-resume"]')).toBeNull()
})

it('无法保存恢复身份时不派发；文件无法核验时不给出确认按钮', async () => {
  let unavailable = false
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST') throw new Error('unexpected mutation')
    return Response.json(String(input).endsWith('/preparation') ? unavailable
      ? { ...preparation, analysis: { status: 'unverifiable', issueCodes: ['mismatch'], message: '文件身份变化' } }
      : preparation : task)
  })
  const root = mount(fetcher as typeof fetch); click(root, 'status')
  await vi.waitFor(() => expect(root.querySelector('[data-action="preparation-read"]')).not.toBeNull())
  click(root, 'preparation-read')
  await vi.waitFor(() => expect(root.querySelector('[data-action="preparation-resume"]')).not.toBeNull())
  const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('disabled') })
  click(root, 'preparation-resume')
  await vi.waitFor(() => expect(root.textContent).toContain('无法保存恢复身份'))
  expect(fetcher.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  storage.mockRestore(); unavailable = true; click(root, 'preparation-read')
  await vi.waitFor(() => expect(root.textContent).toContain('文件身份变化'))
  expect(root.querySelector('[data-action="preparation-resume"]')).toBeNull()
})

it('读回票据不存在后才允许明确提交原确认，重复读取不自动派发', async () => {
  sessionStorage.setItem('recovery-ui:policy-adoption:preparation-recovery', JSON.stringify({ taskId: 'task',
    recoveryId: 'recovery-fixed', confirmation: { kind: 'analysis', identity: file, expectedStateVersion: 7 } }))
  const posted: unknown[] = []
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith('/recoveries/recovery-fixed')) return Response.json(
      { detail: { code: 'source_missing', message: '票据不存在' } }, { status: 404 })
    if (init?.method === 'POST') { posted.push(JSON.parse(String(init.body))); return Response.json(recovery) }
    return Response.json(task)
  })
  const root = mount(fetcher as typeof fetch); click(root, 'status')
  await vi.waitFor(() => expect(root.querySelector('[data-action="recovery-read"]')).not.toBeNull())
  expect(root.querySelector('[data-action="recovery-resubmit"]')).toBeNull()
  click(root, 'recovery-read')
  await vi.waitFor(() => expect(root.querySelector('[data-action="recovery-resubmit"]')).not.toBeNull())
  expect(posted).toEqual([])
  click(root, 'recovery-resubmit')
  await vi.waitFor(() => expect(root.textContent).toContain('续跑已排队'))
  expect(posted).toEqual([{ kind: 'analysis', identity: file, expectedStateVersion: 7 }])
  expect(root.querySelector('[data-action="recovery-resubmit"]')).toBeNull()
})

it('旧版本确认冲突后保留身份；读回无票据并重新核对后才允许采用新状态版本', async () => {
  const versions: number[] = []
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/preparation/resume')) {
      const payload = JSON.parse(String(init?.body)); versions.push(payload.expectedStateVersion)
      expect(payload.identity).toEqual(file)
      return versions.length === 1 ? Response.json({ detail: { code: 'report_editor_conflict' } }, { status: 409 }) : Response.json(recovery)
    }
    if (url.endsWith('/recoveries/recovery-fixed')) return Response.json({ detail: { code: 'source_missing' } }, { status: 404 })
    if (url.endsWith('/preparation')) return Response.json({ ...preparation, stateVersion: versions.length ? 8 : 7 })
    return Response.json(task)
  })
  const root = mount(fetcher as typeof fetch); click(root, 'status')
  await vi.waitFor(() => expect(root.querySelector('[data-action="preparation-read"]')).not.toBeNull())
  click(root, 'preparation-read')
  await vi.waitFor(() => expect(root.querySelector('[data-action="preparation-resume"]')).not.toBeNull())
  click(root, 'preparation-resume')
  await vi.waitFor(() => expect(root.textContent).toContain('原确认身份已保留'))
  click(root, 'recovery-read')
  await vi.waitFor(() => expect(root.querySelector('[data-action="recovery-resubmit"]')).not.toBeNull())
  click(root, 'preparation-read')
  await vi.waitFor(() => expect(root.querySelector('[data-action="recovery-recheck"]')).not.toBeNull())
  expect(versions).toEqual([7])
  click(root, 'recovery-recheck')
  await vi.waitFor(() => expect(root.querySelector('[data-action="preparation-resume"]')).not.toBeNull())
  expect(versions).toEqual([7])
  click(root, 'preparation-resume')
  await vi.waitFor(() => expect(root.textContent).toContain('续跑已排队'))
  expect(versions).toEqual([7, 8])
})
