import { transferableAbortController } from 'node:util'
import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ManagementApp } from './app'
let root: Root
const fetcher = vi.fn()
const scope = {
  id: 'org',
  name: '测试机构',
  database: 'warehouse',
  companyId: '100',
}
const draft = {
  source_id: 'operations',
  version: 2,
  name: '经营数仓',
  source_type: 'starrocks',
  database: 'warehouse',
  metadata_version_id: 'operations:1',
  content_hash: 'hash2',
}
const reply = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status })
let detail = {
  draft,
  published: null,
  enabled: true,
  hasUnpublishedChanges: true,
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  window.history.replaceState(
    {},
    '',
    '/management/sources?database=warehouse&companyId=100',
  )
  vi.stubGlobal('matchMedia', () => ({
    matches: false,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
  vi.stubGlobal(
    'AbortController',
    class {
      constructor() {
        return transferableAbortController()
      }
    },
  )
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  vi.stubGlobal('fetch', fetcher)
  fetcher.mockImplementation(async (path: string) => {
    if (path.endsWith('/me'))
      return reply({ username: 'admin', csrfToken: 'csrf-secret' })
    if (path.includes('/scopes'))
      return reply({ items: [scope], nextCursor: null })
    if (path.includes('/versions'))
      return reply({ items: [], nextCursor: null })
    if (path.includes('/sources/operations')) return reply(detail)
    return reply({
      items: [
        {
          ...draft,
          enabled: true,
          publishedRevision: null,
          hasUnpublishedChanges: false,
        },
      ],
      nextCursor: null,
    })
  })
  document.body.innerHTML = '<div id="management-root"></div>'
  root = createRoot(document.getElementById('management-root')!)
})
afterEach(async () => {
  await act(async () => root.unmount())
  vi.unstubAllGlobals()
  fetcher.mockReset()
})
async function waitFor(check: () => void) {
  for (let n = 0; n < 70; n++) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30))
    })
    try {
      check()
      return
    } catch {}
  }
  check()
}
async function mount() {
  await act(async () => {
    root.render(<ManagementApp />)
  })
  await waitFor(() =>
    expect(document.querySelector('.ant-skeleton')).toBeNull(),
  )
}
async function input(label: string, value: string) {
  await act(async () => {
    const field = document.querySelector<HTMLInputElement>(`#${label}`)!
    expect(field).toBeTruthy()
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!.call(field, value)
    field.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function submit() {
  await act(async () => {
    document
      .querySelector('form')!
      .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await new Promise((resolve) => setTimeout(resolve, 40))
  })
}
it('未登录时显示登录与初始化说明', async () => {
  fetcher.mockImplementation(async () =>
    reply({ message: '管理会话已失效' }, 401),
  )
  await mount()
  await waitFor(() =>
    expect(document.body.textContent).toContain('bootstrap-admin'),
  )
  expect(document.querySelector('#username')).toHaveProperty('value', 'admin')
  expect(document.querySelector('#password')?.getAttribute('type')).toBe(
    'password',
  )
})
it('登录错误清除密码，不自动重试', async () => {
  fetcher.mockImplementation(async (path: string) =>
    reply(
      {
        message: path.includes('login')
          ? '用户名或密码错误。'
          : '管理会话已失效',
      },
      401,
    ),
  )
  await mount()
  await waitFor(() =>
    expect(document.querySelector('#password')).not.toBeNull(),
  )
  await input('password', 'private-password')
  await submit()
  await waitFor(() =>
    expect(document.body.textContent).toContain('用户名或密码错误'),
  )
  expect(document.querySelector('#password')).toHaveProperty('value', '')
  expect(
    fetcher.mock.calls.filter(([p]) => p.includes('auth/login')),
  ).toHaveLength(1)
  expect(localStorage.length).toBe(0)
})
it('显式URL组织读取列表，显示真实状态', async () => {
  await mount()
  await waitFor(() => expect(document.body.textContent).toContain('经营数仓'))
  expect(
    fetcher.mock.calls.some(([p]) =>
      p.includes('scopeDatabase=warehouse&companyId=100'),
    ),
  ).toBe(true)
  expect(document.body.textContent).toContain('未发布')
  expect(document.body.textContent).not.toContain('连接正常')
})
it('详情深链独立读取，编辑默认保持凭据', async () => {
  window.history.replaceState(
    {},
    '',
    '/management/sources/operations/edit?database=warehouse&companyId=100',
  )
  await mount()
  await waitFor(() =>
    expect(document.querySelector('#name')).toHaveProperty('value', '经营数仓'),
  )
  expect(document.querySelector('#dsn')).toBeNull()
  expect(document.querySelector('#profile')).toBeNull()
  expect(fetcher.mock.calls.some(([path]) => path.includes('/profiles/'))).toBe(false)
  await input('name', '改名')
  await submit()
  const call = fetcher.mock.calls.find(([, o]) => o?.method === 'PUT')
  expect(call).toBeTruthy()
  const body = JSON.parse(call![1].body)
  expect(body.expectedVersion).toBe(2)
  expect(body.name).toBe('改名')
  expect(body).not.toHaveProperty('dsn')
  expect(body).not.toHaveProperty('reportingProfileVersionId')
  expect(call![1].headers['x-csrf-token']).toBe('csrf-secret')
})
it('后台不可用显示实际错误', async () => {
  fetcher.mockImplementation(async () =>
    reply({ message: '管理存储暂时不可用。' }, 503),
  )
  await mount()
  expect(document.body.textContent).toContain('管理存储暂时不可用')
  expect(document.body.textContent).not.toContain('暂无数据源')
})
it('业务401返回登录并清理表单', async () => {
  window.history.replaceState(
    {},
    '',
    '/management/sources/operations/edit?database=warehouse&companyId=100',
  )
  await mount()
  await waitFor(() => expect(document.querySelector('#name')).not.toBeNull())
  await input('name', '改名')
  fetcher.mockImplementation(async () =>
    reply({ message: '管理会话已失效，请重新登录。' }, 401),
  )
  await submit()
  await waitFor(() =>
    expect(document.querySelector('#password')).not.toBeNull(),
  )
  expect(document.querySelector('#name')).toBeNull()
})

it('慢保存期间不能继续修改而误丢未保存输入', async () => {
  window.history.replaceState(
    {},
    '',
    '/management/sources/operations/edit?database=warehouse&companyId=100',
  )
  const standard = fetcher.getMockImplementation()!
  let finish!: (response: Response) => void
  fetcher.mockImplementation((path: string, options?: { method?: string }) =>
    options?.method === 'PUT'
      ? new Promise((resolve) => {
          finish = resolve
        })
      : standard(path, options),
  )
  await mount()
  await waitFor(() => expect(document.querySelector('#name')).not.toBeNull())
  await act(async () => {
    document
      .querySelector<HTMLInputElement>('input[type=radio][value="true"]')!
      .click()
  })
  await input('dsn', 'starrocks://reader:private@localhost:9030/warehouse')
  await input('name', '提交快照')
  await submit()
  expect(document.querySelector('#name')).toHaveProperty('disabled', true)
  expect(document.querySelector('#database')).toHaveProperty('disabled', true)
  await act(async () => {
    finish(reply({ ...draft, name: '提交快照', version: 3 }))
    await new Promise((resolve) => setTimeout(resolve, 30))
  })
  expect(document.querySelector('#name')).toHaveProperty('disabled', false)
  expect(document.querySelector('#name')).toHaveProperty('value', '提交快照')
})

it('报告问题裁定先缓存；响应丢失重开只读原问题，不自动重发或标为修复', async () => {
  window.history.replaceState({}, '', '/management/report-issues?database=warehouse&companyId=100')
  sessionStorage.clear()
  const issue = { basisId: 'basis-1', reportId: 'report-1', revision: 2, runId: 'run-1',
    submittedBy: 'report-user', submittedAt: '2026-11-11T00:00:00Z', updatedAt: '2026-11-11T00:00:00Z', version: 1,
    review: { issueId: 'issue-C02', reportRevision: 'editor-revision-1', objectRefs: ['subject-rate'], category: 'calculation',
      description: '执行率不应平均，预算300、实际190应为63.33%', status: 'open', decisionReason: '',
      correctedVersions: [], regressionCaseIds: [], newReportRevision: null, notRecalculatedReason: '' }, proposal: null }
  let posted: any
  let version = 1
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.endsWith('/me')) return reply({ username: 'admin', csrfToken: 'csrf-secret' })
    if (path.includes('/scopes')) return reply({ items: [scope], nextCursor: null })
    if (init?.method === 'POST') {
      posted = JSON.parse(String(init.body))
      expect(init.headers).toMatchObject({ 'x-csrf-token': 'csrf-secret' })
      expect(Object.values(sessionStorage).some(value => value.includes('issue-C02') && value.includes('expectedVersion'))).toBe(true)
      version = 2; throw Error('response lost after commit')
    }
    return reply({ items: [{ ...issue, version, review: { ...issue.review,
      status: version === 1 ? 'open' : 'accepted', decisionReason: posted?.decisionReason ?? '' }, proposal: posted?.proposal ?? null }], nextCursor: null })
  })
  await mount()
  await waitFor(() => expect(document.body.textContent).toContain('报告问题'))
  const button = (text: string) => [...document.querySelectorAll('button')].find(node => node.textContent === text)!
  await waitFor(() => expect(button('查看并裁定')).toBeTruthy())
  await act(async () => button('查看并裁定').click())
  await act(async () => document.querySelector<HTMLInputElement>('input[value="accepted"]')!.click())
  const fill = async (id: string, value: string) => act(async () => {
    const field = document.querySelector<HTMLTextAreaElement>('#' + id)!
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, value)
    field.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await fill('issue-decision_decisionReason', '原始行合计证明平均比率有偏')
  await fill('issue-decision_changeSummary', '改为分子分母分别汇总后相除')
  await fill('issue-decision_counterexample', '预算100、200，实际90、100；70%错误，应63.33%')
  await submit()
  await waitFor(() => expect(document.body.textContent).toContain('裁定结果待确认'))
  expect(document.activeElement?.textContent).toBe('读取原裁定结果')
  expect(posted).toMatchObject({ scopeDatabase: 'warehouse', companyId: '100', expectedVersion: 1, status: 'accepted',
    proposal: { changeSummary: '改为分子分母分别汇总后相除' } })
  await act(async () => root.unmount())
  root = createRoot(document.getElementById('management-root')!)
  await mount()
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  await act(async () => button('读取原裁定结果').click())
  await waitFor(() => expect(document.body.textContent).toContain('已确认原裁定生效'))
  expect(document.body.textContent).toContain('已采纳，待修复')
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  sessionStorage.clear()
})

const reviewFixture = { basisId: 'basis-1', reportId: 'report-1', revision: 2, version: 1,
  review: { issueId: 'issue-conflict', objectRefs: ['subject-rate'], category: 'calculation',
    description: '请核对执行率汇总', status: 'open', decisionReason: '' }, proposal: null }
const reviewCacheKey = 'management-report-decision:' + JSON.stringify(['admin', 'warehouse', '100'])
const reviewButton = (text: string) => [...document.querySelectorAll('button')].find(node => node.textContent === text)!
async function fillReviewReason(value: string) {
  await act(async () => {
    const field = document.querySelector<HTMLTextAreaElement>('#issue-decision_decisionReason')!
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, value)
    field.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
function reviewFetch(record = reviewFixture) {
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.endsWith('/me')) return reply({ username: 'admin', csrfToken: 'csrf-secret' })
    if (path.includes('/scopes')) return reply({ items: [scope], nextCursor: null })
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body))
      return reply({ ...record, version: record.version + 1,
        review: { ...record.review, status: body.status, decisionReason: body.decisionReason } })
    }
    return reply({ items: [record], nextCursor: null })
  })
}
it('报告裁定冲突保留原内容；读取新版后显式重新核对才按新版本提交', async () => {
  window.history.replaceState({}, '', '/management/report-issues?database=warehouse&companyId=100')
  sessionStorage.clear()
  sessionStorage.setItem(reviewCacheKey, JSON.stringify({ issueId: 'issue-conflict', decision: {
    expectedVersion: 1, status: 'needs_evidence', decisionReason: '本地原裁定，不可静默覆盖',
  } }))
  reviewFetch({ ...reviewFixture, version: 2, review: { ...reviewFixture.review, status: 'needs_evidence', decisionReason: '其他管理员已要求核对原始行' } })
  await mount()
  await waitFor(() => expect(reviewButton('读取原裁定结果')).toBeTruthy())
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  await act(async () => reviewButton('读取原裁定结果').click())
  await waitFor(() => expect(document.body.textContent).toContain('问题已有其他裁定或更新'))
  expect(document.body.textContent).toContain('本地原裁定，不可静默覆盖')
  expect(document.body.textContent).toContain('其他管理员已要求核对原始行')
  expect(reviewButton('确认重新提交原裁定')).toBeUndefined()
  await act(async () => reviewButton('按当前版本重新核对').click())
  await fillReviewReason('核对当前版本后登记新理由')
  await submit()
  await waitFor(() => expect(document.body.textContent).toContain('裁定已登记'))
  const posts = fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(posts).toHaveLength(1)
  expect(JSON.parse(posts[0][1].body)).toMatchObject({ expectedVersion: 2, decisionReason: '核对当前版本后登记新理由' })
  expect(sessionStorage.getItem(reviewCacheKey)).toBeNull()
})
it('无法缓存裁定时保留表单且不发送管理写请求', async () => {
  window.history.replaceState({}, '', '/management/report-issues?database=warehouse&companyId=100')
  sessionStorage.clear()
  reviewFetch()
  await mount()
  await waitFor(() => expect(reviewButton('查看并裁定')).toBeTruthy())
  await act(async () => reviewButton('查看并裁定').click())
  await fillReviewReason('原始反例仍待补充')
  const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('storage unavailable') })
  try {
    await submit()
    await waitFor(() => expect(document.body.textContent).toContain('无法保存裁定身份'))
    expect(document.querySelector('#issue-decision_decisionReason')).toHaveProperty('value', '原始反例仍待补充')
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  } finally { storage.mockRestore() }
})

it('管理裁定显示已关联的正式修复版本并保留待核验状态', async () => {
  window.history.replaceState({}, '', '/management/report-issues?database=warehouse&companyId=100')
  sessionStorage.clear()
  fetcher.mockImplementation(async (path: string) => {
    if (path.endsWith('/me')) return reply({ username: 'admin', csrfToken: 'csrf-secret' })
    if (path.includes('/scopes')) return reply({ items: [scope], nextCursor: null })
    return reply({ items: [{ ...reviewFixture, review: { ...reviewFixture.review, status: 'accepted',
      correctedVersions: [{ assetType: 'metric', assetId: 'budget', revision: 2 }] } }], nextCursor: null })
  })
  await mount()
  await waitFor(() => expect(reviewButton('查看并裁定')).toBeTruthy())
  await act(async () => reviewButton('查看并裁定').click())
  expect(document.body.textContent).toContain('已关联正式修复版本，仍待回归与重算核验')
  expect(document.body.textContent).toContain('指标 · budget · 修订 2')
})

it('裁定读回不能将他人新增修复关联误认为原提交成功', async () => {
  window.history.replaceState({}, '', '/management/report-issues?database=warehouse&companyId=100')
  sessionStorage.clear()
  const proposal = { changeSummary: '合计后计算比率', counterexample: '190/300应为63.33%' }
  sessionStorage.setItem(reviewCacheKey, JSON.stringify({ issueId: 'issue-conflict', decision: {
    expectedVersion: 1, status: 'accepted', decisionReason: '核对合计比率', proposal,
  } }))
  fetcher.mockImplementation(async (path: string) => {
    if (path.endsWith('/me')) return reply({ username: 'admin', csrfToken: 'csrf-secret' })
    if (path.includes('/scopes')) return reply({ items: [scope], nextCursor: null })
    return reply({ items: [{ ...reviewFixture, version: 2, proposal, review: { ...reviewFixture.review,
      status: 'accepted', decisionReason: '核对合计比率', correctedVersions: [{ assetType: 'metric', assetId: 'budget', revision: 2 }] } }], nextCursor: null })
  })
  await mount()
  await waitFor(() => expect(reviewButton('读取原裁定结果')).toBeTruthy())
  await act(async () => reviewButton('读取原裁定结果').click())
  await waitFor(() => expect(document.body.textContent).toContain('问题已有其他裁定或更新'))
  expect(sessionStorage.getItem(reviewCacheKey)).not.toBeNull()
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  sessionStorage.clear()
})

it('采纳可选择精确正式修复版本，跨页保留且丢响应后读回原完整关联', async () => {
  window.history.replaceState({}, '', '/management/report-issues?database=warehouse&companyId=100')
  sessionStorage.clear()
  let posted: any
  const reference = { assetType: 'metric', assetId: 'budget', revision: 2 }
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.endsWith('/me')) return reply({ username: 'admin', csrfToken: 'csrf-secret' })
    if (path.includes('/scopes')) return reply({ items: [scope], nextCursor: null })
    if (path.includes('/fix-options')) return reply(path.includes('after=')
      ? { items: [{ reference: { ...reference, assetId: 'actual' }, name: '实际额', available: true, reason: '' }], nextCursor: null }
      : { items: [{ reference: { ...reference, revision: 1 }, name: '原预算额', available: false, reason: '原报告已采用' },
        { reference, name: '修复预算额', available: true, reason: '' }], nextCursor: 'next' })
    if (init?.method === 'POST') {
      posted = JSON.parse(String(init.body))
      expect(JSON.parse(sessionStorage.getItem(reviewCacheKey)!).decision.correctedVersions).toEqual([reference])
      throw Error('commit response lost')
    }
    return reply({ items: [{ ...reviewFixture, version: posted ? 2 : 1, proposal: posted?.proposal ?? null,
      review: { ...reviewFixture.review, status: posted ? 'accepted' : 'open', decisionReason: posted?.decisionReason ?? '',
        correctedVersions: posted?.correctedVersions ?? [] } }], nextCursor: null })
  })
  await mount()
  await waitFor(() => expect(reviewButton('查看并裁定')).toBeTruthy())
  await act(async () => reviewButton('查看并裁定').click())
  await act(async () => document.querySelector<HTMLInputElement>('input[type=radio][value=accepted]')!.click())
  await waitFor(() => expect(document.querySelector('input[aria-label="选择修复预算额，修订2"]')).toBeTruthy())
  expect(document.querySelector('input[aria-label="选择原预算额，修订1"]')).toHaveProperty('disabled', true)
  await act(async () => document.querySelector<HTMLInputElement>('input[aria-label="选择修复预算额，修订2"]')!.click())
  await act(async () => reviewButton('加载更多正式版本').click())
  await waitFor(() => expect(document.body.textContent).toContain('实际额'))
  expect(document.querySelector('input[aria-label="选择修复预算额，修订2"]')).toHaveProperty('checked', true)
  await fillReviewReason('核对原始字段和反例')
  for (const [name, value] of [['changeSummary', '分别汇总'], ['counterexample', '190/300应为63.33%']]) {
    await act(async () => {
      const field = document.querySelector<HTMLTextAreaElement>('#issue-decision_' + name)!
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, value)
      field.dispatchEvent(new Event('input', { bubbles: true }))
    })
  }
  await submit()
  await waitFor(() => expect(document.body.textContent).toContain('裁定结果待确认'))
  expect(posted.correctedVersions).toEqual([reference])
  await act(async () => root.unmount())
  root = createRoot(document.getElementById('management-root')!)
  await mount()
  await waitFor(() => expect(reviewButton('读取原裁定结果')).toBeTruthy())
  await act(async () => reviewButton('读取原裁定结果').click())
  await waitFor(() => expect(document.body.textContent).toContain('已确认原裁定生效'))
  expect(sessionStorage.getItem(reviewCacheKey)).toBeNull()
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
})

it('回归填写独立预期，完整缓存后提交；丢响应重开先精确读回且不关闭问题', async () => {
  window.history.replaceState({}, '', '/management/report-issues?database=warehouse&companyId=100')
  sessionStorage.clear()
  const references = [{ assetType: 'metric', assetId: 'budget', revision: 2 }]
  let saved: any
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.endsWith('/me')) return reply({ username: 'admin', csrfToken: 'csrf-secret' })
    if (path.includes('/scopes')) return reply({ items: [scope], nextCursor: null })
    if (path.includes('/regression-targets')) return reply({ issueVersion: 2, items: [{ targetRunId: 'fixed-run',
      targetReportRevision: 'initial', calculationReceiptId: 'fixed-calculation', basisId: 'fixed-basis',
      available: true, reason: '', goal: '本月预算核对', metricName: '预算额', metricVersion: { metricId: 'budget', revision: 2 },
      period: { start: '2026-11-01', end: '2026-12-01' }, facts: [{ factId: 'fact-budget', unit: 'CNY', dimensions: [] }] }], nextCursor: null })
    if (init?.method === 'POST' && path.endsWith('/regressions')) {
      const { scopeDatabase: _, companyId: __, ...request } = JSON.parse(String(init.body))
      expect(Object.values(sessionStorage).some(value => value.includes(request.requestId) && value.includes('100+200'))).toBe(true)
      saved = { receiptId: 'issue-regression-saved', issueId: 'issue-conflict', request, correctedVersions: references,
        status: 'passed', verificationLevel: 'snapshot_recomputed', businessApproval: 'not_performed', createdAt: '2026-11-11T00:00:00Z',
        comparisons: [{ assertion: request.assertions[0], actual: { factId: 'fact-budget', value: '300', status: 'computed', unit: 'CNY', issueCodes: [] }, matches: true }] }
      throw Error('actual commit response lost')
    }
    if (path.includes('/regressions')) return reply({ items: saved ? [saved] : [], nextCursor: null })
    return reply({ items: [{ ...reviewFixture, version: 2, review: { ...reviewFixture.review, status: 'accepted', correctedVersions: references } }], nextCursor: null })
  })
  await mount()
  await waitFor(() => expect(reviewButton('查看并裁定')).toBeTruthy())
  await act(async () => reviewButton('查看并裁定').click())
  await act(async () => reviewButton('新建回归核验').click())
  await waitFor(() => expect(reviewButton('选择此计算')).toBeTruthy())
  await act(async () => reviewButton('选择此计算').click())
  expect(document.querySelector('#issue-regression_assertions_0_expectedValue')).toBeNull()
  await act(async () => document.querySelector<HTMLInputElement>('input[type=radio][value=computed]')!.click())
  const fill = async (id: string, value: string) => act(async () => {
    const element = document.getElementById(id) as HTMLInputElement
    Object.getOwnPropertyDescriptor(element.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(element, value)
    element.dispatchEvent(new Event('input', { bubbles: true }))
  })
  expect(document.querySelector('#issue-regression_assertions_0_expectedValue')).toHaveProperty('value', '')
  await fill('issue-regression_caseId', 'budget-total')
  await fill('issue-regression_expectationReason', '独立核对原始两行100+200')
  await act(async () => document.querySelector('form#issue-regression')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  await waitFor(() => expect(document.querySelector('#issue-regression .ant-form-item-explain-error')).toBeTruthy())
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  await fill('issue-regression_assertions_0_expectedValue', '300')
  const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('storage unavailable') })
  try {
    await act(async () => document.querySelector('form#issue-regression')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
    await waitFor(() => expect(document.body.textContent).toContain('无法保存核验请求'))
    expect(document.querySelector('#issue-regression_assertions_0_expectedValue')).toHaveProperty('value', '300')
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  } finally { storage.mockRestore() }
  await act(async () => document.querySelector('form#issue-regression')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  await waitFor(() => expect(document.body.textContent).toContain('核验登记结果待确认'))
  await act(async () => root.unmount())
  root = createRoot(document.getElementById('management-root')!)
  await mount()
  await waitFor(() => expect(reviewButton('查看并裁定')).toBeTruthy())
  await act(async () => reviewButton('查看并裁定').click())
  await waitFor(() => expect(reviewButton('读取原回归结果')).toBeTruthy())
  await act(async () => reviewButton('读取原回归结果').click())
  await waitFor(() => expect(document.body.textContent).toContain('已确认原回归核验登记'))
  expect(document.body.textContent).toContain('业务预期尚未签认')
  expect(document.body.textContent).toContain('已采纳，待修复')
  expect(fetcher.mock.calls.some(([path]) => path.includes('/regressions?') && path.includes('requestId='))).toBe(true)
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
}, 15000)

it('回归结果未登记但问题已变时保留原预期；失败记录精确读回仍展示具体差异', async () => {
  window.history.replaceState({}, '', '/management/report-issues?database=warehouse&companyId=100')
  sessionStorage.clear()
  const correctedVersions = [{ assetType: 'metric', assetId: 'budget', revision: 2 }]
  const request = { requestId: 'regression-original', expectedIssueVersion: 2, caseId: 'budget-total', targetRunId: 'fixed-run',
    targetReportRevision: 'initial', calculationReceiptId: 'calculation-1', expectationReason: '独立反例合计应310',
    assertions: [{ factId: 'fact-budget', expectedStatus: 'computed', expectedValue: '310', unit: 'CNY', decimalPlaces: null, expectedIssueCodes: [] }] }
  const key = 'management-issue-regression:' + JSON.stringify(['admin', 'warehouse', '100', 'issue-conflict'])
  sessionStorage.setItem(key, JSON.stringify({ issueId: 'issue-conflict', request, correctedVersions }))
  let registered = false
  fetcher.mockImplementation(async (path: string) => {
    if (path.endsWith('/me')) return reply({ username: 'admin', csrfToken: 'csrf-secret' })
    if (path.includes('/scopes')) return reply({ items: [scope], nextCursor: null })
    if (path.includes('/regressions')) return reply({ items: registered ? [{ receiptId: 'failed-receipt', issueId: 'issue-conflict',
      request, correctedVersions, status: 'failed', verificationLevel: 'snapshot_recomputed', businessApproval: 'not_performed',
      createdAt: '2026-11-11T00:00:00Z', comparisons: [{ assertion: request.assertions[0],
        actual: { factId: 'fact-budget', value: '300', status: 'computed', unit: 'CNY', issueCodes: [] }, matches: false }] }] : [], nextCursor: null })
    return reply({ items: [{ ...reviewFixture, version: 3, review: { ...reviewFixture.review, status: 'accepted', correctedVersions } }], nextCursor: null })
  })
  await mount()
  await waitFor(() => expect(reviewButton('查看并裁定')).toBeTruthy())
  await act(async () => reviewButton('查看并裁定').click())
  await act(async () => reviewButton('读取原回归结果').click())
  await waitFor(() => expect(document.body.textContent).toContain('问题或修复版本已变化'))
  expect(reviewButton('确认重新提交原核验')).toBeUndefined()
  expect(sessionStorage.getItem(key)).not.toBeNull()
  registered = true
  await act(async () => reviewButton('读取原回归结果').click())
  await waitFor(() => expect(document.body.textContent).toContain('快照核验不符合预期'))
  expect(document.body.textContent).toContain('预期：310')
  expect(document.body.textContent).toContain('实际：300')
  expect(document.body.textContent).toContain('业务预期尚未签认')
  expect(sessionStorage.getItem(key)).toBeNull()
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
})

it('关闭前可检查选中的回归当前证据，快照缺失显示原因且不关闭问题', async () => {
  window.history.replaceState({}, '', '/management/report-issues?database=warehouse&companyId=100')
  sessionStorage.clear()
  const request = { requestId: 'original-request', expectedIssueVersion: 2, caseId: 'budget-total', targetRunId: 'fixed-run',
    targetReportRevision: 'initial', calculationReceiptId: 'calculation-1', expectationReason: '独立原始两行合计300',
    assertions: [{ factId: 'fact-budget', expectedStatus: 'computed', expectedValue: '300', unit: 'CNY', decimalPlaces: null, expectedIssueCodes: [] }] }
  let delivered = false
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.endsWith('/me')) return reply({ username: 'admin', csrfToken: 'csrf-secret' })
    if (path.includes('/scopes')) return reply({ items: [scope], nextCursor: null })
    if (path.endsWith('/regression-evidence-check')) {
      expect(JSON.parse(String(init?.body))).toMatchObject({ expectedIssueVersion: 2, regressionReceiptIds: ['regression-passed'] })
      return reply({ issueId: 'issue-conflict', issueVersion: 2, checkedAt: '2026-11-11T00:00:00Z', regressionEvidenceReady: false,
        businessApproval: 'not_performed', issueClosed: false, issues: [], checks: [{ receiptId: 'regression-passed', status: 'failed',
          issues: [{ code: 'metric_snapshot_invalid', message: '回归快照缺失或不可读取。' }] }] })
    }
    if (path.endsWith('/resolution-evidence-check')) return reply({ issueId: 'issue-conflict', issueVersion: 2,
      checkedAt: '2026-11-11T00:00:00Z', regressionEvidenceReady: true, businessApproval: 'not_performed', issueClosed: false,
      issues: [], checks: [{ receiptId: 'regression-passed', status: 'passed', issues: [] }], originalEvidenceReady: false,
      originalChecks: [{ documentId: 'budget-rules', revision: 2, status: 'unavailable',
        issues: [{ code: 'management_document_original_unavailable', message: '原件缺失或身份已变化，暂时无法读取。' }] }],
      reportRelationships: [{ receiptId: 'regression-passed', targetRunId: 'fixed-run', targetBasisId: 'fixed-basis',
        parentBasisId: 'basis-1', status: 'verified', deliveryVerified: delivered, issues: [], outputRevision: 3, validationPassed: false,
        factPresentationVerified: delivered, coveredFactIds: delivered ? ['fact-budget'] : [], missingFactIds: delivered ? [] : ['fact-budget'],
        contentIssues: delivered ? [] : [{ code: 'management_issue_report_fact_uncovered', message: '尚未呈现回归事实。' }],
        deliveryArtifacts: delivered ? [{ format: 'xlsx', path: 'report.xlsx', size: 123, sha256: 'a'.repeat(64) }] : [] }] })
    if (path.includes('/regressions')) return reply({ items: [{ receiptId: 'regression-passed', issueId: 'issue-conflict',
      request, correctedVersions: [{ assetType: 'metric', assetId: 'budget', revision: 2 }], status: 'passed',
      verificationLevel: 'snapshot_recomputed', businessApproval: 'not_performed', createdAt: '2026-11-11T00:00:00Z',
      comparisons: [{ assertion: request.assertions[0], actual: { factId: 'fact-budget', value: '300', status: 'computed', unit: 'CNY', issueCodes: [] }, matches: true }] }], nextCursor: null })
    return reply({ items: [{ ...reviewFixture, version: 2, review: { ...reviewFixture.review, status: 'accepted',
      correctedVersions: [{ assetType: 'metric', assetId: 'budget', revision: 2 }] } }], nextCursor: null })
  })
  await mount()
  await waitFor(() => expect(reviewButton('查看并裁定')).toBeTruthy())
  await act(async () => reviewButton('查看并裁定').click())
  await waitFor(() => expect(document.querySelector('input[aria-label="检查budget-total的当前证据"]')).toBeTruthy())
  await act(async () => document.querySelector<HTMLInputElement>('input[aria-label="检查budget-total的当前证据"]')!.click())
  await act(async () => reviewButton('检查所选回归的当前证据').click())
  await waitFor(() => expect(document.body.textContent).toContain('回归快照缺失或不可读取。'))
  expect(document.body.textContent).toContain('当前回归证据尚不齐全')
  expect(document.body.textContent).toContain('已采纳，待修复')
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  await act(async () => reviewButton('检查原件与新报告关系').click())
  await waitFor(() => expect(document.body.textContent).toContain('原件缺失或身份已变化，暂时无法读取。'))
  expect(document.body.textContent).toContain('新依据父链已核对')
  expect(document.body.textContent).toContain('报告最终交付尚未核验')
  expect(document.body.textContent).toContain('尚未呈现回归事实。')
  expect(document.body.textContent).toContain('已采纳，待修复')
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(2)
  delivered = true
  await act(async () => reviewButton('检查原件与新报告关系').click())
  await waitFor(() => expect(document.body.textContent).toContain('新报告修订 3 的请求格式文件本次可读且身份匹配。'))
  expect(document.body.textContent).toContain('XLSX · 文件身份已核对')
  expect(document.body.textContent).toContain('回归计算的全部根指标事实已在本次正文或冻结附表中核对。')
  expect(document.body.textContent).toContain('此项不证明业务解释、图表或全部导出内容一致，仍需业务签认。')
  expect(document.body.textContent).toContain('原交付验收未通过；文件可读不代表验收或业务签认通过。')
  expect(document.body.textContent).toContain('已采纳，待修复')
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(3)
})
