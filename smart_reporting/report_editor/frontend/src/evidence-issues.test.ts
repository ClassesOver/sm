import { afterEach, expect, it, vi } from 'vitest'
import { ReportEditorClient } from './api'
import { mountReportIssues } from './evidence-issues'

afterEach(() => { document.body.replaceChildren(); sessionStorage.clear(); vi.restoreAllMocks() })
const make = (fetcher: typeof fetch) => {
  const root = document.createElement('div'); document.body.append(root)
  mountReportIssues(root, { client: new ReportEditorClient('/editor', fetcher), storageKey: 'issues',
    loadObjects: async () => [{ id: 'fact-rate', label: '预算执行率' }] })
  return root
}
const click = (root: HTMLElement, action: string) => root.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!.click()

it('提交前保存原问题；丢响应后重开只读，并展示采纳理由及反例而不标为已解决', async () => {
  let submitted: any
  const calls: string[] = []
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(init?.method ?? 'GET')
    if (init?.method === 'POST') {
      submitted = JSON.parse(String(init.body))
      expect(JSON.parse(sessionStorage.getItem('issues:report-issue')!)).toEqual(submitted)
      throw Error('response lost')
    }
    expect(String(input)).toContain('issueId=' + submitted.issueId)
    return Response.json({ items: [{ version: 2, review: { ...submitted, status: 'accepted',
      decisionReason: '汇总应为190/300', correctedVersions: [], regressionCaseIds: [] },
      proposal: { changeSummary: '改为合计比率', counterexample: '均值70%错误，应为63.33%' } }], nextCursor: null })
  })
  let root = make(fetcher as typeof fetch)
  click(root, 'issue-new')
  await vi.waitFor(() => expect(root.querySelector('select')).not.toBeNull())
  const target = root.querySelector<HTMLSelectElement>('[name="object"]')!
  expect(target.value).toBe('')
  target.value = 'fact-rate'; target.dispatchEvent(new Event('change'))
  const description = root.querySelector<HTMLTextAreaElement>('textarea')!
  description.value = '比例不能平均'; description.dispatchEvent(new Event('input'))
  click(root, 'issue-submit')
  await vi.waitFor(() => expect(root.textContent).toContain('提交结果未知'))
  expect(submitted).toMatchObject({ objectRefs: ['fact-rate'], category: 'calculation', description: '比例不能平均' })
  root.remove(); root = make(fetcher as typeof fetch)
  expect(calls).toEqual(['POST'])
  click(root, 'issue-read-original')
  await vi.waitFor(() => expect(root.textContent).toContain('已采纳，待修复'))
  expect(root.textContent).toContain('汇总应为190/300')
  expect(root.textContent).toContain('均值70%错误，应为63.33%')
  expect(root.querySelector('h3')?.textContent).toBe('已采纳，待修复')
  expect(root.textContent).toContain('关联对象：预算执行率')
  expect(calls).toEqual(['POST', 'GET'])
})

it('原问题未找到后只有明确操作才重提同一内容', async () => {
  const cached = { issueId: 'issue-fixed', objectRefs: ['fact-rate'], category: 'data', description: '缺少十二月数据' }
  sessionStorage.setItem('issues:report-issue', JSON.stringify(cached))
  const posted: unknown[] = []
  const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST') { posted.push(JSON.parse(String(init.body))); return Response.json({ review: { ...cached, status: 'open' }, version: 1 }) }
    return Response.json({ items: [], nextCursor: null })
  })
  const root = make(fetcher as typeof fetch)
  expect(root.querySelector('[data-action="issue-resubmit"]')).toBeNull()
  click(root, 'issue-read-original')
  await vi.waitFor(() => expect(root.querySelector('[data-action="issue-resubmit"]')).not.toBeNull())
  expect(posted).toEqual([])
  click(root, 'issue-resubmit')
  await vi.waitFor(() => expect(root.textContent).toContain('待处理'))
  expect(posted).toEqual([cached])
})

it('会话存储不可用不提交；服务返回内容按纯文本展示', async () => {
  const fetcher = vi.fn(async () => Response.json({ items: [{ version: 1, review: { issueId: 'issue-1',
    status: 'open', description: '<img src=x onerror=alert(1)>', objectRefs: ['fact-rate'], category: 'data' } }], nextCursor: null }))
  const root = make(fetcher as typeof fetch); click(root, 'issue-new')
  await vi.waitFor(() => expect(root.querySelector('textarea')).not.toBeNull())
  const select = root.querySelector<HTMLSelectElement>('[name="object"]')!
  select.value = 'fact-rate'; select.dispatchEvent(new Event('change'))
  const input = root.querySelector<HTMLTextAreaElement>('textarea')!
  input.value = '缺少本月数据'; input.dispatchEvent(new Event('input'))
  const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('disabled') })
  click(root, 'issue-submit')
  await vi.waitFor(() => expect(root.textContent).toContain('无法保存问题身份'))
  expect(fetcher).not.toHaveBeenCalled()
  storage.mockRestore(); click(root, 'issue-list')
  await vi.waitFor(() => expect(root.textContent).toContain('<img src=x onerror=alert(1)>'))
  expect(root.querySelector('img')).toBeNull()
})

it('列表翻页保留已有问题；未知读取故障不能开启重提', async () => {
  sessionStorage.setItem('issues:report-issue', JSON.stringify({ issueId: 'issue-fixed', objectRefs: ['fact-rate'], category: 'data', description: '原问题核对材料' }))
  let listPage = 0
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('issueId=')) throw Error('network unavailable')
    listPage += 1
    return Response.json({ items: [{ version: 1, review: { issueId: listPage === 1 ? 'issue-a' : 'issue-b',
      description: listPage === 1 ? '第一条问题' : '第二条问题', category: 'data', objectRefs: ['fact-rate'], status: 'open' } }],
      nextCursor: listPage === 1 ? 'issue-a' : null })
  })
  const root = make(fetcher as typeof fetch)
  expect(root.textContent).toContain('原问题核对材料')
  click(root, 'issue-read-original')
  await vi.waitFor(() => expect(root.textContent).toContain('读取失败'))
  expect(root.querySelector('[data-action="issue-resubmit"]')).toBeNull()
  click(root, 'issue-list')
  await vi.waitFor(() => expect(root.textContent).toContain('第一条问题'))
  click(root, 'issue-more')
  await vi.waitFor(() => expect(root.textContent).toContain('第二条问题'))
  expect(root.textContent).toContain('第一条问题')
  expect(root.querySelector('[data-action="issue-more"]')).toBeNull()
})

it('依据浏览器反馈候选来自本修订来源目录，不要求可编辑正文', async () => {
  const { createEvidenceBrowser } = await import('./evidence-browser')
  const client = new ReportEditorClient('/editor', async (input: RequestInfo | URL) => {
    if (String(input).endsWith('/sources')) return Response.json({ available: true, subjects: [
      { subjectId: 'sub-rate', subjectKind: 'text_claim', locator: { sectionId: 'section_001' }, factRefs: [], computationId: null },
    ], datasets: [] })
    return Response.json({ available: false })
  })
  const root = document.createElement('div'); document.body.append(root)
  createEvidenceBrowser(root, { client, revisionLabel: '修订2', storageKey: 'integrated-issues',
    onReturnToReport: () => {}, locateSubject: () => {} })
  const panel = root.querySelector<HTMLElement>('.evidence-report-issues')!
  expect(panel).not.toBeNull()
  click(panel, 'issue-new')
  await vi.waitFor(() => expect(panel.querySelectorAll('[name="object"] option')).toHaveLength(2))
  expect([...panel.querySelectorAll<HTMLOptionElement>('[name="object"] option')].map(item => item.value)).toEqual(['', 'sub-rate'])
})

it('正式修复关联可读，但不把尚无回归和新报告证据的问题标为解决', async () => {
  const root = make(async () => Response.json({ items: [{ version: 3, review: { issueId: 'issue-fix',
    status: 'accepted', description: '预算执行率应按合计比例', objectRefs: ['fact-rate'], category: 'calculation',
    correctedVersions: [{ assetType: 'metric', assetId: 'rate', revision: 2 },
      { assetType: 'evidence_release', assetId: 'release-correction', revision: null }] } }], nextCursor: null }))
  click(root, 'issue-list')
  await vi.waitFor(() => expect(root.textContent).toContain('已关联正式修复版本，仍待回归与重算核验'))
  expect(root.textContent).toContain('指标 · rate · 修订 2')
  expect(root.textContent).toContain('证据集合 · release-correction')
  expect(root.querySelector('h3')?.textContent).toBe('已采纳，待修复')
})

it('报告反馈展示已关闭的处理方式，不把历史报告标为已重算', async () => {
  const root = make(vi.fn(async () => Response.json({ items: [{ version: 4, review: {
    issueId: 'issue-closed', status: 'resolved', description: '比例核对', objectRefs: ['fact-rate'],
    decisionReason: '已签认纠错预期', correctedVersions: [{ assetType: 'metric', assetId: 'rate', revision: 2 }],
    regressionCaseIds: ['C02'], newReportRevision: null, notRecalculatedReason: '只修复后续规则',
  } }], nextCursor: null })) as typeof fetch)
  click(root, 'issue-list')
  await vi.waitFor(() => expect(root.textContent).toContain('本次不重算：只修复后续规则'))
  expect(root.textContent).toContain('原报告保持不变')
  expect(root.textContent).toContain('C02')
  expect(root.textContent).not.toContain('仍待回归与重算核验')
})
