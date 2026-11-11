import { webcrypto } from 'node:crypto'
import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { IssueResolution } from './resolutions'
import { approvalRequestHash } from './business-approvals'

let root: Root
const fetcher = vi.fn(), closed = vi.fn()
const scope = { database: 'warehouse', companyId: 'a' }
const fixes = [{ assetType: 'metric' as const, assetId: 'budget', revision: 2 }]
const prepared = { approvalRequestId: 'sign-1', regressionReceiptIds: ['reg-1'], regressionReady: true,
  originalReady: true, approvalReady: true, deliveryReady: false, factsReady: false }
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
let saved: Record<string, unknown> | null
beforeEach(() => {
  saved = null; sessionStorage.clear(); Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('crypto', webcrypto)
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('fetch', fetcher)
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.endsWith('/resolutions') && init?.method === 'POST') {
      const { scopeDatabase: _db, companyId: _co, ...body } = JSON.parse(String(init.body))
      saved = { issueId: 'issue-1', receiptId: 'closure-1', request: body, requestHash: await approvalRequestHash(body), correctedVersions: fixes,
        issueClosed: true, resolvedIssueVersion: 3, resolvedByUsername: 'admin', resolvedByAccountId: 1, historicalResult: true, createdAt: '2026-11-11T00:00:00Z',
        evidence: { businessApprovalReady: true, originalEvidenceReady: true, regressionEvidenceReady: true, deliveryReady: false, factPresentationReady: false,
          newReportRevision: null, deliveries: [] } }
      return response(saved)
    }
    if (path.includes('/resolutions/')) return saved ? response(saved) : response({ code: 'management_issue_resolution_not_found', message: '未登记' }, 404)
    if (path.includes('/report-issue-reviews?')) return response({ items: [{ version: 2, review: { issueId: 'issue-1', status: 'accepted', correctedVersions: fixes } }] })
    throw Error(path)
  })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); fetcher.mockReset(); closed.mockReset() })
async function until(check: () => void) {
  for (let i = 0; i < 80; i++) { await act(async () => { await new Promise(resolve => setTimeout(resolve, 15)) }); try { check(); return } catch {} }
  check()
}
const button = (name: string) => [...document.querySelectorAll('button')].find(item => item.textContent?.replaceAll(' ', '').includes(name))!
async function click(name: string) { await act(async () => button(name).click()) }
async function enter(name: string, value: string) {
  const element = document.querySelector<HTMLTextAreaElement>(`[aria-label="${name}"]`)!
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(element, value); element.dispatchEvent(new Event('input', { bubbles: true })) })
}
async function mount(selection: typeof prepared | null = prepared) {
  await act(async () => root.render(<IssueResolution scope={scope} issueId="issue-1" version={2} username="admin" csrf="csrf"
    correctedVersions={fixes} preparation={selection} disabled={false} onResolved={closed} />))
}
async function fill() {
  await act(async () => document.querySelector<HTMLInputElement>('input[value="not_recalculated"]')!.click())
  await enter('关闭裁定理由', '独立原始资料及正式修复已核对。')
  await enter('本次不重算的理由', '保留原报告作为历史记录，本次只修复后续规则。')
  await act(async () => document.querySelector<HTMLInputElement>('[aria-label="确认关闭并保留原报告"]')!.click())
}

it('requires explicit no-recalculation disposition and never equates it with delivery', async () => {
  await mount()
  expect(document.querySelector<HTMLInputElement>('input[value="recalculated"]')!.disabled).toBe(true)
  expect(button('确认关闭问题').disabled).toBe(true)
  await fill(); await click('确认关闭问题')
  await until(() => expect(document.body.textContent).toContain('关闭已登记'))
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  const body = JSON.parse(String(fetcher.mock.calls.find(([, init]) => init?.method === 'POST')![1].body))
  expect(body.mode).toBe('not_recalculated'); expect(body.originalReportUnchanged).toBe(true)
  expect(body.businessApprovalRequestId).toBe('sign-1'); expect(body.regressionReceiptIds).toEqual(['reg-1'])
  expect(document.body.textContent).toContain('本次不重算'); expect(document.body.textContent).toContain('不代表整份报告验收通过')
  expect(closed).toHaveBeenCalledOnce()
})

it('recovers a committed lost response after remount with GET and no second closing POST', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    const result = await handler(path, init)
    if (init?.method === 'POST') throw Error('response lost after commit')
    return result
  })
  await mount(); await fill(); await click('确认关闭问题')
  await until(() => expect(document.body.textContent).toContain('关闭结果待确认'))
  await act(async () => root.unmount()); root = createRoot(document.getElementById('root')!); await mount(null)
  await until(() => expect(document.activeElement).toBe(button('读取原关闭结果')))
  await click('读取原关闭结果')
  await until(() => expect(document.body.textContent).toContain('已确认原关闭登记'))
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  expect(closed).toHaveBeenCalledOnce()
})

it('does not submit when request persistence fails', async () => {
  await mount(); await fill()
  const setter = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('storage disabled') })
  await click('确认关闭问题')
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  expect(document.body.textContent).toContain('无法保存关闭请求')
  setter.mockRestore()
})

it('retains the pending request when 404 recovery finds an updated issue and prevents direct retry', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === 'POST') throw Error('not committed')
    if (path.includes('/report-issue-reviews?')) return response({ items: [{ version: 3, review: { issueId: 'issue-1', status: 'accepted', correctedVersions: fixes } }] })
    return handler(path, init)
  })
  await mount(); await fill(); await click('确认关闭问题')
  await until(() => expect(document.body.textContent).toContain('关闭结果待确认'))
  const original = sessionStorage.getItem('management-issue-resolution:' + JSON.stringify(['admin', 'warehouse', 'a', 'issue-1']))
  await click('读取原关闭结果')
  await until(() => expect(document.body.textContent).toContain('问题或修复版本已变化'))
  expect(button('确认重提原关闭')).toBeUndefined()
  expect(sessionStorage.getItem('management-issue-resolution:' + JSON.stringify(['admin', 'warehouse', 'a', 'issue-1']))).toBe(original)
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  await click('保留原输入，重新核对关闭条件')
  expect(document.querySelector<HTMLTextAreaElement>('[aria-label="关闭裁定理由"]')!.value).toBe('独立原始资料及正式修复已核对。')
  expect(document.body.textContent).toContain('上次关闭输入（仅供核对）')
  expect(sessionStorage.getItem('management-issue-resolution:' + JSON.stringify(['admin', 'warehouse', 'a', 'issue-1']) + ':prior')).toBe(original)
})

it('allows an explicit same-request retry only after 404 and current-version verification', async () => {
  const handler = fetcher.getMockImplementation()!
  let calls = 0
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === 'POST' && ++calls === 1) throw Error('not committed')
    return handler(path, init)
  })
  await mount(); await fill(); await click('确认关闭问题')
  await until(() => expect(document.body.textContent).toContain('关闭结果待确认'))
  await click('读取原关闭结果')
  await until(() => expect(button('确认重提原关闭')).toBeTruthy())
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  await click('确认重提原关闭')
  await until(() => expect(document.body.textContent).toContain('关闭已登记'))
  const posts = fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(posts).toHaveLength(2); expect(posts[0][1].body).toBe(posts[1][1].body)
})

it('rejects a returned receipt for different request content even with the same request id', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    const result = await handler(path, init)
    if (init?.method === 'POST') { saved!.requestHash = '0'.repeat(64); return response(saved) }
    return result
  })
  await mount(); await fill(); await click('确认关闭问题')
  await until(() => expect(document.body.textContent).toContain('关闭响应与原请求不一致'))
  expect(closed).not.toHaveBeenCalled()
  expect(button('读取原关闭结果')).toBeTruthy()
  expect(button('重新核对关闭条件')).toBeUndefined()
})

it('requires re-acknowledgement when the selected evidence changes', async () => {
  await mount(); await fill()
  expect(button('确认关闭问题').disabled).toBe(false)
  await mount({ ...prepared, approvalRequestId: 'another-signoff' })
  expect(document.querySelector<HTMLInputElement>('[aria-label="确认关闭并保留原报告"]')!.checked).toBe(false)
  expect(button('确认关闭问题').disabled).toBe(true)
})

it('records a verified new report while retaining its failed original validation', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    const result = await handler(path, init)
    if (init?.method === 'POST') {
      saved!.evidence = { businessApprovalReady: true, originalEvidenceReady: true, regressionEvidenceReady: true,
        deliveryReady: true, factPresentationReady: true, newReportRevision: 'editor-revision-1',
        deliveries: [{ targetRunId: 'new-run', outputRevision: 2, validationPassed: false,
          artifacts: [{ format: 'docx', path: 'report.docx', sha256: 'a'.repeat(64), size: 100 }] }] }
      return response(saved)
    }
    return result
  })
  await mount({ ...prepared, deliveryReady: true, factsReady: true })
  await act(async () => document.querySelector<HTMLInputElement>('input[value="recalculated"]')!.click())
  await enter('关闭裁定理由', '已核对新报告正文的精确纠错事实。')
  await act(async () => document.querySelector<HTMLInputElement>('[aria-label="确认关闭并保留原报告"]')!.click())
  await click('确认关闭问题')
  await until(() => expect(document.body.textContent).toContain('关闭已登记'))
  expect(document.body.textContent).toContain('原交付验收未通过')
  expect(document.body.textContent).toContain('DOCX')
  expect(closed).toHaveBeenCalledOnce()
})


it('blocks a new close when the pending request cache is unreadable', async () => {
  sessionStorage.setItem('management-issue-resolution:' + JSON.stringify(['admin', 'warehouse', 'a', 'issue-1']), '{invalid-json')
  await mount()
  expect(document.body.textContent).toContain('原关闭缓存无法读取')
  expect(button('确认关闭问题').disabled).toBe(true)
  expect(sessionStorage.getItem('management-issue-resolution:' + JSON.stringify(['admin', 'warehouse', 'a', 'issue-1']))).toBe('{invalid-json')
})

it('reads a closed issue through its server-bound request id without another submission', async () => {
  await mount(); await fill(); await click('确认关闭问题')
  await until(() => expect(document.body.textContent).toContain('关闭已登记'))
  const requestId = (saved!.request as { requestId: string }).requestId
  await act(async () => root.unmount()); root = createRoot(document.getElementById('root')!)
  await act(async () => root.render(<IssueResolution scope={scope} issueId="issue-1" version={3} username="admin" csrf="csrf"
    correctedVersions={fixes} preparation={null} disabled={true} resolutionRequestId={requestId} onResolved={closed} />))
  await click('读取本问题关闭记录')
  await until(() => expect(document.body.textContent).toContain('已确认原关闭登记'))
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
})
