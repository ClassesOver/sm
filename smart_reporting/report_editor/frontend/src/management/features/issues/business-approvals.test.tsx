import { webcrypto } from 'node:crypto'
import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { BusinessApprovals, approvalRequestHash } from './business-approvals'
import { CurrentRegressions } from './current-regressions'

let root: Root
const fetcher = vi.fn()
const chosen = vi.fn()
const scope = { database: 'warehouse', companyId: 'a' }
const fixes = [{ assetType: 'metric' as const, assetId: 'budget', revision: 2 }]
const candidate = { receiptId: 'reg-1', status: 'passed' as const,
  request: { caseId: 'budget-total', expectedIssueVersion: 2, expectationReason: '原始100+200=300',
    assertions: [{ factId: 'fact-1', expectedStatus: 'computed', expectedValue: '300', unit: 'CNY' }] } }
const locator = { kind: 'text_lines', lineStart: 1, lineEnd: 1, page: null, paragraph: null, table: null, row: null, column: null }
const quote = '独立原始预算A100、B200，合计300。'
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
let saved: Record<string, unknown> | null
beforeEach(() => {
  saved = null; sessionStorage.clear()
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('crypto', webcrypto)
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('fetch', fetcher)
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.includes('/approval-source-options')) return response({ items: [{ documentId: 'original', revision: 1, name: '独立预算对账', available: true, reason: '' }], nextCursor: null })
    if (path.includes('/business-documents/original')) return response({ documentId: 'original', revisions: [{ revision: 1, reviewStatus: 'approved', ingestionStatus: 'ready',
      parseReceipt: { fragments: [{ locator, text: quote }] } }] })
    if (path.endsWith('/business-approvals') && init?.method === 'POST') {
      const { scopeDatabase: _database, companyId: _company, ...payload } = JSON.parse(String(init.body))
      saved = { receiptId: 'approval-1', issueId: 'issue-1', request: { ...payload, sources: payload.sources.map(({ quote: _quote, ...source }: Record<string, unknown>) => source) },
        requestHash: await approvalRequestHash(payload), correctedVersions: fixes, approvedByUsername: 'admin', approvedByAccountId: 1,
        approvalScope: 'regression_expected_values', businessApproval: 'explicitly_approved', currentEvidenceStatus: 'not_checked', createdAt: '2026-11-11T00:00:00Z' }
      return response(saved)
    }
    if (path.includes('/business-approvals/')) return saved ? response(saved) : response({ code: 'management_issue_approval_not_found', message: '未登记' }, 404)
    if (path.includes('/report-issue-reviews?')) return response({ items: [{ version: 2, review: { issueId: 'issue-1', status: 'accepted', correctedVersions: fixes } }] })
    throw Error(path)
  })
  document.body.innerHTML = '<div id="root"></div>'
  root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); fetcher.mockReset(); chosen.mockReset() })
async function until(check: () => void) {
  for (let i = 0; i < 80; i++) { await act(async () => { await new Promise(resolve => setTimeout(resolve, 15)) }); try { check(); return } catch {} }
  check()
}
function button(label: string) { return [...document.querySelectorAll('button')].find(item => item.textContent?.replaceAll(' ', '').includes(label))! }
async function click(label: string) { await act(async () => { expect(button(label)).toBeTruthy(); button(label).click() }) }
async function enter(label: string, text: string) {
  await act(async () => {
    const field = document.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[aria-label="${label}"]`)!
    expect(field).toBeTruthy()
    Object.getOwnPropertyDescriptor(field.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(field, text)
    field.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function mount() {
  await act(async () => { root.render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <BusinessApprovals scope={scope} issueId="issue-1" version={2} username="admin" csrf="csrf" correctedVersions={fixes} candidates={[candidate]} disabled={false} onUse={chosen} />
  </QueryClientProvider>) })
}
async function fill() {
  await click('签认回归预期')
  await until(() => expect(document.querySelector('[aria-label="签认budget-total的预期"]')).toBeTruthy())
  await act(async () => document.querySelector<HTMLInputElement>('[aria-label="签认budget-total的预期"]')!.click())
  await click('选择独立原件')
  await until(() => expect(button('读取独立预算对账')).toBeTruthy())
  await click('读取独立预算对账')
  await until(() => expect(button('采用此原文位置')).toBeTruthy())
  await click('采用此原文位置')
  await enter('签认理由与独立推导', '已核对A100+B200=300，与所选全部预期一致。')
  await act(async () => document.querySelector<HTMLInputElement>('[aria-label="明确签认所选回归预期"]')!.click())
}

it('matches the server sorted ASCII JSON hash for Chinese and surrogate pairs', async () => {
  expect(await approvalRequestHash({ sources: [{ quote: '中文😀', locator: { kind: 'text_lines', lineStart: 1, lineEnd: 2 } }],
    requestId: 'sign-1', expectedIssueVersion: 2 })).toBe('d225d594b4a36ba8667e2f4499455056ff9c80a53bf01d1a6639ad66f5169e74')
})

it('requires explicit source and acknowledgement, signs once and explicitly selects it for checking', async () => {
  await mount(); await fill()
  await click('确认签认并登记')
  await until(() => expect(document.body.textContent).toContain('预期签认已登记'))
  const posts = fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(posts).toHaveLength(1)
  const body = JSON.parse(String(posts[0][1].body))
  expect(body.decision).toBe('approve_expected_values')
  expect(body.sources[0]).toEqual({ regressionReceiptId: 'reg-1', documentId: 'original', revision: 1, locator, quote })
  expect(chosen).not.toHaveBeenCalled()
  await click('用于本次关闭准备检查')
  expect(chosen).toHaveBeenCalledWith({ requestId: body.requestId, regressionReceiptIds: ['reg-1'] })
  expect(document.body.textContent).toContain('问题未关闭')
})

it('recovers a lost signing response by exact GET without another POST', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    const result = await handler(path, init)
    if (init?.method === 'POST') throw Error('lost response')
    return result
  })
  await mount(); await fill(); await click('确认签认并登记')
  await until(() => expect(document.body.textContent).toContain('签认结果待确认'))
  await act(async () => root.unmount())
  root = createRoot(document.getElementById('root')!)
  await mount()
  expect(document.body.textContent).toContain('待确认的原签认请求')
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  await click('读取原签认结果')
  await until(() => expect(document.body.textContent).toContain('已确认原签认登记'))
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  expect(chosen).not.toHaveBeenCalled()
})

it('does not POST when session cache cannot preserve the exact signing request', async () => {
  await mount(); await fill()
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('full') })
  await click('确认签认并登记')
  expect(document.body.textContent).toContain('无法保存签认请求')
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  vi.restoreAllMocks()
})

it('keeps the local request when readback finds a changed issue instead of offering a retry', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === 'POST') throw Error('unknown before commit')
    if (path.includes('/report-issue-reviews?')) return response({ items: [{ version: 3, review: { issueId: 'issue-1', status: 'accepted', correctedVersions: fixes } }] })
    return handler(path, init)
  })
  await mount(); await fill(); await click('确认签认并登记')
  await until(() => expect(document.body.textContent).toContain('签认结果待确认'))
  await click('读取原签认结果')
  await until(() => expect(document.body.textContent).toContain('问题或修复版本已变化'))
  expect(document.body.textContent).toContain('原完整签认请求')
  expect(button('确认重提原签认')).toBeUndefined()
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
})

it('does not trust a same-ID signing response whose full request hash differs', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    const result = await handler(path, init)
    return init?.method === 'POST' ? response({ ...saved, requestHash: '0'.repeat(64) }) : result
  })
  await mount(); await fill(); await click('确认签认并登记')
  await until(() => expect(document.body.textContent).toContain('签认响应与原完整请求不一致'))
  expect(button('用于本次关闭准备检查')).toBeUndefined()
  expect(chosen).not.toHaveBeenCalled()
})

it('sends the explicitly chosen signoff and exact regressions only in the full current check', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.endsWith('/resolution-evidence-check')) {
      const body = JSON.parse(String(init?.body))
      return response({ issueId: 'issue-1', issueVersion: 2, checkedAt: '2026-11-11T00:00:00Z', regressionEvidenceReady: true,
        businessApproval: 'explicitly_approved', businessApprovalReady: true, issueClosed: false, issues: [],
        checks: [{ receiptId: 'reg-1', status: 'passed', issues: [] }], originalEvidenceReady: true, originalChecks: [], reportRelationships: [],
        businessApprovalCheck: { requestId: body.businessApprovalRequestId, status: 'verified', issues: [] } })
    }
    return handler(path, init)
  })
  await act(async () => root.render(<QueryClientProvider client={new QueryClient()}>
    <CurrentRegressions scope={scope} issueId="issue-1" version={2} csrf="csrf" username="admin" correctedVersions={fixes} candidates={[candidate]} disabled={false} />
  </QueryClientProvider>))
  await fill(); await click('确认签认并登记')
  await until(() => expect(document.body.textContent).toContain('预期签认已登记'))
  await click('用于本次关闭准备检查')
  await click('检查原件与新报告关系')
  await until(() => expect(document.body.textContent).toContain('所选回归预期的显式签认本次有效'))
  const sent = fetcher.mock.calls.find(([path]) => String(path).endsWith('/resolution-evidence-check'))!
  expect(JSON.parse(String(sent[1].body))).toMatchObject({ businessApprovalRequestId: (saved!.request as { requestId: string }).requestId, regressionReceiptIds: ['reg-1'] })
  await act(async () => document.querySelector<HTMLInputElement>('[aria-label="检查budget-total的当前证据"]')!.click())
  expect(document.body.textContent).not.toContain('已选择业务预期签认；')
})
