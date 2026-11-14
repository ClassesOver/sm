import { afterEach, expect, it, vi } from 'vitest'
import { ReportEditorApiError, ReportEditorClient } from './api'
import { mountPolicyAdoption } from './evidence-policy-adoption'
import { markdownSha256 } from './source-validation'

afterEach(() => { document.body.innerHTML = ''; sessionStorage.clear() })

it('逐题明确选择后提交；响应丢失重开只读原请求，并展示告警及五格式入口', async () => {
  let posted: any
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/policy-adoption-options')) return Response.json({ parentRevision: 2, items: [
      { policyVersion: { policyId: 'budget', revision: 2 }, name: '新预算口径' }], nextCursor: null })
    if (url.endsWith('/policy-adoption-preview')) return Response.json({ previewHash: 'a'.repeat(64), preview: {
      originalPolicyVersion: { policyId: 'budget', revision: 1 }, targetPolicyVersion: { policyId: 'budget', revision: 2 },
      changedFields: ['filters'], changes: [{ field: 'filters', before: '无附加过滤条件', after: '项目 等于 A' }], issues: [{ message: '期间适用性待核对' }],
      questions: [{ id: 'q-budget', text: '预算是多少？' }, { id: 'q-rate', text: '执行率是多少？' }],
      metricOptions: [{ metricVersion: { metricId: 'budget', revision: 2 }, name: '预算金额', unit: '元' }],
    } })
    if (init?.method === 'POST') { posted = JSON.parse(String(init.body)); throw new Error('lost') }
    if (url.endsWith('/delivery')) return Response.json({ task: {}, delivery: { revision: 3,
      validation: { ok: false, issues: [{ message: '业务核对未完成' }] }, editor: { openUrl: '/editor/new' },
      ...Object.fromEntries(['pdf', 'word', 'pptx', 'xlsx', 'md'].map(format => [format, { downloadUrl: `/download/${format}` }])),
    } })
    return Response.json({ taskId: 'task', status: 'completed', result: { issueCodes: [] },
      execution: { runId: 'native-run', status: 'completed', issueCodes: [] } })
  })
  const create = () => {
    const root = document.createElement('div'); document.body.append(root)
    mountPolicyAdoption(root, { client: new ReportEditorClient('/editor', fetcher as typeof fetch),
      storageKey: 'policy', saveMarkdown: async () => markdownSha256('原报告'), getDraft: () => ({ markdown: '原报告' }) })
    return root
  }
  let root = create()
  root.querySelector<HTMLButtonElement>('[data-action="load"]')!.click()
  await vi.waitFor(() => expect(root.querySelector('select')).not.toBeNull())
  const policy = root.querySelector<HTMLSelectElement>('select')!
  policy.value = '0'; policy.dispatchEvent(new Event('change'))
  root.querySelector<HTMLButtonElement>('[data-action="preview"]')!.click()
  await vi.waitFor(() => expect(root.textContent).toContain('预算是多少'))
  expect(root.textContent).toContain('期间适用性待核对')
  expect(root.textContent).toContain('原口径：无附加过滤条件')
  expect(root.textContent).toContain('新口径：项目 等于 A')
  const submit = root.querySelector<HTMLButtonElement>('[data-action="submit"]')!
  expect(submit.disabled).toBe(true)
  const selects = root.querySelectorAll<HTMLSelectElement>('fieldset select')
  expect([...selects].every(select => select.value === '')).toBe(true)
  selects[0]!.value = '0'; selects[0]!.dispatchEvent(new Event('change'))
  selects[1]!.value = 'unavailable'; selects[1]!.dispatchEvent(new Event('change'))
  root.querySelectorAll<HTMLTextAreaElement>('textarea').forEach(input => {
    input.value = '明确核对，执行率暂缺实际额'; input.dispatchEvent(new Event('input'))
  })
  expect(submit.disabled).toBe(false)
  submit.click()
  await vi.waitFor(() => expect(root.textContent).toContain('结果未知'))
  expect(posted).toMatchObject({ operation: 'adopt_policy', parentRevision: 2,
    confirmation: { targetPolicyVersion: { policyId: 'budget', revision: 2 }, previewHash: 'a'.repeat(64),
      questionChoices: [{ questionId: 'q-budget', metricVersion: { metricId: 'budget', revision: 2 } },
        { questionId: 'q-rate', metricVersion: null }] } })
  expect(posted.confirmation.requestId).toBe(posted.requestId)
  root.remove(); root = create()
  root.querySelector<HTMLButtonElement>('[data-action="status"]')!.click()
  await vi.waitFor(() => expect(root.textContent).toContain('新报告已生成'))
  root.querySelector<HTMLButtonElement>('[data-action="delivery"]')!.click()
  await vi.waitFor(() => expect(root.querySelectorAll('a')).toHaveLength(6))
  expect(root.textContent).toContain('业务核对未完成')
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(2)
})

it('只有读回确认请求不存在后，显式操作才重提相同确认', async () => {
  const cached = { requestId: 'confirmed-1', parentRevision: 2, expectedSha256: 'a'.repeat(64),
    operation: 'adopt_policy', confirmation: { requestId: 'confirmed-1', previewHash: 'b'.repeat(64),
      targetPolicyVersion: { policyId: 'budget', revision: 2 }, questionChoices: [
        { questionId: 'q-budget', metricVersion: null, reason: '没有适用指标' }] } }
  sessionStorage.setItem('resume:policy-adoption', JSON.stringify(cached))
  const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === 'POST'
    ? Response.json({ taskId: 'task', status: 'pending', execution: { status: 'running' } })
    : Response.json({ detail: { code: 'source_missing', message: '没有原请求' } }, { status: 404 }))
  const root = document.createElement('div')
  const save = vi.fn(async () => { throw new Error('恢复不得保存新输入') })
  mountPolicyAdoption(root, { client: new ReportEditorClient('/editor', fetcher as typeof fetch),
    storageKey: 'resume', saveMarkdown: save, getDraft: () => ({ markdown: '报告' }) })
  expect(fetcher).not.toHaveBeenCalled()
  const status = root.querySelector<HTMLButtonElement>('[data-action="status"]')!
  status.click()
  await vi.waitFor(() => expect(status.textContent).toBe('确认提交原口径请求'))
  expect(fetcher).toHaveBeenCalledTimes(1)
  status.click()
  await vi.waitFor(() => expect(root.textContent).toContain('正在按新口径生成报告'))
  expect(JSON.parse(String(fetcher.mock.calls[1]![1]?.body))).toEqual(cached)
  expect(save).not.toHaveBeenCalled()
})

it('切换口径后忽略前一个延迟预检，避免把旧问题确认绑定到新选择', async () => {
  let resolvePreview!: (response: Response) => void
  const fetcher = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/policy-adoption-preview')
    ? await new Promise<Response>(resolve => { resolvePreview = resolve })
    : Response.json({ parentRevision: 2, items: ['甲', '乙'].map((name, index) => ({ name,
      policyVersion: { policyId: name, revision: index + 2 } })), nextCursor: null }))
  const root = document.createElement('div')
  mountPolicyAdoption(root, { client: new ReportEditorClient('/editor', fetcher as typeof fetch),
    storageKey: 'races', saveMarkdown: async () => markdownSha256('报告'), getDraft: () => ({ markdown: '报告' }) })
  root.querySelector<HTMLButtonElement>('[data-action="load"]')!.click()
  await vi.waitFor(() => expect(root.querySelector('select')).not.toBeNull())
  const policy = root.querySelector<HTMLSelectElement>('select')!
  policy.value = '0'; policy.dispatchEvent(new Event('change'))
  root.querySelector<HTMLButtonElement>('[data-action="preview"]')!.click()
  await vi.waitFor(() => expect(resolvePreview).toBeTypeOf('function'))
  policy.value = '1'; policy.dispatchEvent(new Event('change'))
  policy.value = '0'; policy.dispatchEvent(new Event('change'))
  resolvePreview(Response.json({ previewHash: 'a'.repeat(64), preview: {
    originalPolicyVersion: { policyId: 'old', revision: 1 }, targetPolicyVersion: { policyId: '甲', revision: 2 },
    questions: [{ id: 'q-old', text: '过期问题' }], metricOptions: [], changedFields: [], changes: [], issues: [],
  } }))
  await vi.waitFor(() => expect(root.querySelector('[data-action="preview"]')?.getAttribute('aria-busy')).toBeNull())
  expect(root.textContent).not.toContain('过期问题')
})

it.each(['draft_changed', 'storage_unavailable'])('确认前%s时不发送采用请求', async fault => {
  let markdown = '原报告'
  const fetcher = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/policy-adoption-preview')
    ? Response.json({ previewHash: 'a'.repeat(64), preview: {
      originalPolicyVersion: { policyId: 'old', revision: 1 }, targetPolicyVersion: { policyId: 'budget', revision: 2 },
      changedFields: [], changes: [], issues: [], questions: [{ id: 'q', text: '预算？' }], metricOptions: [],
    } }) : Response.json({ parentRevision: 2, items: [
      { policyVersion: { policyId: 'budget', revision: 2 }, name: '预算口径' }], nextCursor: null }))
  const root = document.createElement('div')
  mountPolicyAdoption(root, { client: new ReportEditorClient('/editor', fetcher as typeof fetch),
    storageKey: 'prevent', saveMarkdown: async () => markdownSha256(markdown), getDraft: () => ({ markdown }) })
  root.querySelector<HTMLButtonElement>('[data-action="load"]')!.click()
  await vi.waitFor(() => expect(root.querySelector('select')).not.toBeNull())
  const policy = root.querySelector<HTMLSelectElement>('select')!
  policy.value = '0'; policy.dispatchEvent(new Event('change'))
  root.querySelector<HTMLButtonElement>('[data-action="preview"]')!.click()
  await vi.waitFor(() => expect(root.querySelector('textarea')).not.toBeNull())
  const select = root.querySelector<HTMLSelectElement>('fieldset select')!
  select.value = 'unavailable'; select.dispatchEvent(new Event('change'))
  const reason = root.querySelector<HTMLTextAreaElement>('textarea')!
  reason.value = '明确缺少适用指标'; reason.dispatchEvent(new Event('input'))
  if (fault === 'draft_changed') markdown = '已修改正文'
  const storage = fault === 'storage_unavailable'
    ? vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('disabled') }) : undefined
  try {
    root.querySelector<HTMLButtonElement>('[data-action="submit"]')!.click()
    await vi.waitFor(() => expect(root.textContent).toContain(fault === 'draft_changed' ? '正文已变化' : '无法保存请求身份'))
    expect(fetcher).toHaveBeenCalledTimes(2)
  } finally { storage?.mockRestore() }
})

it.each([true, false, 'code-only'] as const)('新口径MD单格式验收=%s，空回执不能显示文件已生成', async state => {
  const valid = state === true
  const reason = state === 'code-only' ? 'md_identity_unverified' : 'MD 业务核对未完成'
  sessionStorage.setItem('md:policy-adoption', JSON.stringify({ requestId: 'md-request', parentRevision: 1,
    expectedSha256: 'a'.repeat(64), operation: 'adopt_policy', confirmation: {
      requestId: 'md-request', previewHash: 'b'.repeat(64),
      targetPolicyVersion: { policyId: 'budget', revision: 2 },
      questionChoices: [{ questionId: 'q', metricVersion: null, reason: '缺少适用指标' }],
    } }))
  let empty = false
  const fetcher = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/delivery')
    ? Response.json({ task: {}, delivery: { revision: 2, ...(empty ? {} : { md: { downloadUrl: '/download/md' } }),
      editor: { openUrl: '/editor/new' },
      validation: { ok: valid, issues: valid ? [] : [state === 'code-only' ? { code: reason } : { message: reason }] } } })
    : Response.json({ taskId: 'md-task', status: 'completed', execution: { status: 'completed', issueCodes: [] } }))
  const root = document.createElement('div')
  mountPolicyAdoption(root, { client: new ReportEditorClient('/editor', fetcher as typeof fetch),
    storageKey: 'md', saveMarkdown: async () => markdownSha256('# 报告'), getDraft: () => ({ markdown: '# 报告' }) })
  root.querySelector<HTMLButtonElement>('[data-action="status"]')!.click()
  await vi.waitFor(() => expect(root.querySelector<HTMLButtonElement>('[data-action="delivery"]')?.hidden).toBe(false))
  root.querySelector<HTMLButtonElement>('[data-action="delivery"]')!.click()
  await vi.waitFor(() => expect(root.querySelector('a')?.getAttribute('href')).toContain('/download/md'))
  expect(root.querySelector('a')?.textContent).toContain('下载 文本报告')
  expect(root.textContent).toContain(valid ? '尚未进行业务批准' : reason)
  if (!valid) expect(root.textContent).toContain('验收尚未通过')
  empty = true
  root.querySelector<HTMLButtonElement>('[data-action="delivery"]')!.click()
  await vi.waitFor(() => expect(root.querySelectorAll('a')).toHaveLength(1))
  expect(root.textContent).toContain('未生成可下载文件')
  expect(root.textContent).not.toContain('文件已生成')
  if (!valid) expect(root.textContent).toContain(reason)
})


it.each(['preview_failure', 'preview_conflict', 'preview_unknown', 'preview_invalid', 'confirm_failure', 'confirm_conflict', 'confirm_unknown', 'confirm_invalid', 'changed', 'success'])(
  '保存回执%s：预检绑定实际SHA，失败或变化不采用', async fault => {
    let previewCalls = 0; let adopted: any
    const save = vi.fn(async (): Promise<string> => {
      if (fault.startsWith('preview') || (fault.startsWith('confirm') && save.mock.calls.length > 1)) {
        if (fault.endsWith('invalid')) return 'invalid-receipt'
        throw fault.endsWith('conflict') ? new ReportEditorApiError(409, 'conflict', '保存冲突') : new Error('保存结果未知')
      }
      return fault === 'changed' && save.mock.calls.length > 1 ? 'd'.repeat(64) : 'c'.repeat(64)
    })
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/policy-adoption-preview')) {
        previewCalls++
        expect(JSON.parse(String(init?.body)).expectedSha256).toBe('c'.repeat(64))
        return Response.json({ previewHash: 'a'.repeat(64), preview: {
          originalPolicyVersion: { policyId: 'old', revision: 1 }, targetPolicyVersion: { policyId: 'budget', revision: 2 },
          changedFields: [], changes: [], issues: [], questions: [{ id: 'q', text: '预算？' }], metricOptions: [],
        } })
      }
      if (String(input).endsWith('/recalculations')) {
        adopted = JSON.parse(String(init?.body))
        return Response.json({ taskId: 'task', status: 'pending', execution: { status: 'running' } })
      }
      return Response.json({ parentRevision: 2, items: [
        { policyVersion: { policyId: 'budget', revision: 2 }, name: '预算口径' }], nextCursor: null })
    })
    const root = document.createElement('div')
    mountPolicyAdoption(root, { client: new ReportEditorClient('/editor', fetcher as typeof fetch),
      storageKey: 'saved-' + fault, saveMarkdown: save, getDraft: () => ({ markdown: 'local draft' }) })
    root.querySelector<HTMLButtonElement>('[data-action="load"]')!.click()
    await vi.waitFor(() => expect(root.querySelector('select')).not.toBeNull())
    const policy = root.querySelector<HTMLSelectElement>('select')!
    policy.value = '0'; policy.dispatchEvent(new Event('change'))
    const inspect = root.querySelector<HTMLButtonElement>('[data-action="preview"]')!
    inspect.click()
    if (fault.startsWith('preview')) {
      await vi.waitFor(() => expect(inspect.getAttribute('aria-busy')).toBeNull())
      expect(save).toHaveBeenCalledTimes(1); expect(previewCalls).toBe(0); expect(adopted).toBeUndefined()
      return
    }
    await vi.waitFor(() => expect(root.querySelector('textarea')).not.toBeNull())
    const select = root.querySelector<HTMLSelectElement>('fieldset select')!
    select.value = 'unavailable'; select.dispatchEvent(new Event('change'))
    const reason = root.querySelector<HTMLTextAreaElement>('textarea')!
    reason.value = '明确保留缺项'; reason.dispatchEvent(new Event('input'))
    const submit = root.querySelector<HTMLButtonElement>('[data-action="submit"]')!
    submit.click()
    await vi.waitFor(() => expect(submit.getAttribute('aria-busy')).toBeNull())
    expect(save).toHaveBeenCalledTimes(2)
    if (fault === 'success') expect(adopted.expectedSha256).toBe('c'.repeat(64))
    else expect(adopted).toBeUndefined()
    if (fault === 'changed') expect(root.textContent).toContain('重新预检')
  })
