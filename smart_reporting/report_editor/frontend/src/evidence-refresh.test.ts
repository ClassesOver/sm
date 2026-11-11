import { afterEach, expect, it, vi } from 'vitest'
import { ReportEditorClient } from './api'
import { mountDataRefresh } from './evidence-refresh'

afterEach(() => { document.body.innerHTML = ''; sessionStorage.clear() })

it('刷新响应丢失后重新打开只读取原请求，不重复POST，并提供四格式下载', async () => {
  let posted: Record<string, unknown> = {}
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (init?.method === 'POST') {
      posted = JSON.parse(String(init.body))
      throw new Error('response lost')
    }
    if (url.endsWith('/delivery')) return Response.json({ task: {}, delivery: {
      revision: 13, validation: { ok: false, issues: [{ message: '业务核对未完成' }] },
      ...Object.fromEntries(['pdf', 'word', 'pptx', 'xlsx'].map(format => [format, { downloadUrl: `/download/${format}` }])),
    } })
    return Response.json({ taskId: 'recalc-task', status: 'completed', result: { issueCodes: [] },
      execution: { runId: 'native-run', status: 'completed', issueCodes: [] } })
  })
  const client = new ReportEditorClient('/reports/v1/editor/report/12', fetcher as typeof fetch)
  const create = () => {
    const root = document.createElement('div'); document.body.append(root)
    const panel = mountDataRefresh(root, { client, storageKey: 'refresh-test',
      getDraft: () => ({ markdown: '# 原报告' }) })
    panel.update({ available: true, parentRevision: 12 })
    return root
  }
  let root = create()
  root.querySelector<HTMLButtonElement>('button')!.click()
  expect(root.textContent).toContain('原报告保持不变')
  root.querySelector<HTMLButtonElement>('button')!.click()
  await vi.waitFor(() => expect(root.textContent).toContain('结果未知'))
  expect(posted).toMatchObject({ operation: 'refresh_data', parentRevision: 12 })
  expect(posted.expectedSha256).toMatch(/^[a-f0-9]{64}$/)
  root.remove(); root = create()
  expect(root.querySelector('button')?.textContent).toBe('读取刷新进度')
  root.querySelector<HTMLButtonElement>('button')!.click()
  await vi.waitFor(() => expect(root.querySelectorAll('button')[1]?.hidden).toBe(false))
  root.querySelectorAll('button')[1]!.click()
  await vi.waitFor(() => expect(root.querySelectorAll('a')).toHaveLength(4))
  expect(root.textContent).toContain('业务核对未完成')
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  expect(fetcher.mock.calls.some(([input]) => String(input).endsWith('/api/recalculation-requests/' + posted.requestId))).toBe(true)
})

it('后台完成但交付记录待确认时仍可显式读取文件，不自动重新提交', async () => {
  const fetcher = vi.fn(async () => Response.json({ taskId: 'task', status: 'pending', result: null,
    execution: { status: 'completed', runId: 'run', issueCodes: ['refresh_completion_record_unavailable'] } }))
  const root = document.createElement('div')
  const panel = mountDataRefresh(root, { client: new ReportEditorClient('/editor', fetcher as typeof fetch),
    storageKey: 'pending', getDraft: () => ({ markdown: '报告' }) })
  panel.update({ available: true, parentRevision: 1 })
  root.querySelector<HTMLButtonElement>('button')!.click()
  root.querySelector<HTMLButtonElement>('button')!.click()
  await vi.waitFor(() => expect(root.textContent).toContain('完成状态未确认'))
  expect(root.querySelectorAll('button')[1]?.textContent).toBe('读取已生成文件')
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('服务端确认没有原请求后，只有管理员再次确认才重提同一请求', async () => {
  const bodies: string[] = []
  const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST') {
      bodies.push(String(init.body))
      if (bodies.length === 1) throw new Error('unknown registration')
      return Response.json({ taskId: 'task', status: 'pending', result: null,
        execution: { status: 'running', runId: 'run', issueCodes: [] } })
    }
    return Response.json({ detail: { code: 'source_missing', message: '任务不存在' } }, { status: 404 })
  })
  const root = document.createElement('div')
  const panel = mountDataRefresh(root, { client: new ReportEditorClient('/editor', fetcher as typeof fetch),
    storageKey: 'retry-original', getDraft: () => ({ markdown: '报告' }) })
  panel.update({ available: true, parentRevision: 1 })
  const button = root.querySelector<HTMLButtonElement>('button')!
  button.click(); button.click()
  await vi.waitFor(() => expect(button.disabled).toBe(false))
  button.click()
  await vi.waitFor(() => expect(button.textContent).toBe('确认提交原刷新请求'))
  expect(bodies).toHaveLength(1)
  button.click()
  await vi.waitFor(() => expect(bodies).toHaveLength(2))
  expect(bodies[0]).toBe(bodies[1])
})
