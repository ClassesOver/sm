import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { PreferenceApprovalSummary } from './preference-approval-summary'

let root: Root
const fetcher = vi.fn(), applied = vi.fn()
const hash = 'a'.repeat(64), contract = 'b'.repeat(64), executor = 'c'.repeat(64)
const approvalId = '5084d423-1511-463a-9f76-ef48f4613664'
const receipt = { id: 'bdff5c58-af4e-4634-9fd3-1607028e7054', contentHash: 'd'.repeat(64),
  contractHash: contract, executorManifestHash: executor, expiresAt: '2099-01-01T00:00:00Z' }
const summary = (overrides = {}) => ({ id: approvalId, contentHash: 'e'.repeat(64),
  draft: { version: 3, contentHash: hash }, contractVersion: 1, contractHash: contract,
  executorManifestHash: executor, expiresAt: '2099-01-01T00:00:00Z',
  status: 'incomplete', canApply: false, missingRequirements: [{ requirementId: 'native-table',
    reason: 'missing_evidence', format: 'pptx', scenario: 'native_table_style', missingDimensions: ['visual'] }], ...overrides })
const ready = () => summary({ status: 'ready', canApply: true, missingRequirements: [] })
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
const button = (label: string) => document.querySelector<HTMLButtonElement>(`[aria-label="${label}"]`)!
async function mount({ version = 3, contentHash = hash, disabled = false, receipts = [receipt] } = {}) {
  await act(async () => root.render(<PreferenceApprovalSummary receipts={receipts} version={version} contentHash={contentHash}
    csrf="csrf-test" disabled={disabled} effectiveRevision={4} onApplied={applied} />))
}
async function prepare(value = ready()) {
  fetcher.mockResolvedValueOnce(json(value)); await act(async () => button('汇总当前草稿验收').click())
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('fetch', fetcher)
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); fetcher.mockReset(); applied.mockReset() })

it('按需汇总只发精确服务器记录ID，具体缺项默认折叠且不把当前格式当全局批准', async () => {
  await mount(); expect(fetcher).not.toHaveBeenCalled()
  expect(document.body.textContent).toContain('已关联 1 条验收记录')
  await prepare(summary())
  expect(fetcher.mock.calls).toHaveLength(1)
  const [url, options] = fetcher.mock.calls[0]
  expect(url).toBe('/management/api/v1/configuration/preferences/report-verification/prepare')
  expect(JSON.parse(options.body)).toEqual({ expectedVersion: 3, expectedHash: hash, evidenceIds: [receipt.id] })
  expect(document.body.textContent).toContain('验收规则版本 1')
  const details = document.querySelector<HTMLDetailsElement>('details')!
  expect(details.open).toBe(false)
  expect(details.textContent).toContain('native-table')
  expect(button('应用已批准偏好')).toBeNull()
})

it.each([
  { status: 'incomplete', canApply: true, missingRequirements: [] },
  { status: 'ready', canApply: false, missingRequirements: [] },
  { status: 'ready', canApply: true },
  { status: 'ready', canApply: true, missingRequirements: [], expiresAt: '2000-01-01T00:00:00Z' },
])('不以不一致或过期摘要开放应用：%j', async state => {
  await mount(); await prepare(summary(state))
  expect(button('应用已批准偏好')).toBeNull()
})

it('服务器ready后仍需明确确认，应用精确CAS五字段并核实回执才刷新', async () => {
  await mount(); await prepare()
  await act(async () => button('应用已批准偏好').click())
  expect(fetcher.mock.calls).toHaveLength(1)
  expect(document.body.textContent).toContain('仅影响后续新任务')
  fetcher.mockResolvedValueOnce(json({ revision: 5, draftVersion: 3, document: {}, contentHash: hash,
    publishedAt: '2026-11-13', approvalId }))
  await act(async () => button('确认应用偏好').click())
  const [url, options] = fetcher.mock.calls[1]
  expect(url).toBe('/management/api/v1/configuration/preferences/apply')
  expect(JSON.parse(options.body)).toEqual({ expectedVersion: 3, expectedHash: hash, expectedEffectiveRevision: 4,
    approvalId, expectedApprovalHash: 'e'.repeat(64) })
  expect(applied).toHaveBeenCalledTimes(1)
  expect(document.body.textContent).toContain('已应用为偏好版本 5')
})

it.each(['identity', 'network'])('应用%s故障保留批准，使用相同请求重试且不先刷新', async fault => {
  await mount(); await prepare(); await act(async () => button('应用已批准偏好').click())
  if (fault === 'network') fetcher.mockRejectedValueOnce(new TypeError('connection lost'))
  else fetcher.mockResolvedValueOnce(json({ revision: 5, draftVersion: 3, document: {}, contentHash: hash,
    publishedAt: '2026-11-13', approvalId: '00000000-0000-4000-8000-000000000000' }))
  await act(async () => button('确认应用偏好').click())
  expect(applied).not.toHaveBeenCalled()
  expect(document.body.textContent).toContain(fault === 'network' ? '提交结果待确认' : '应用回执')
  fetcher.mockResolvedValueOnce(json({ revision: 5, draftVersion: 3, document: {}, contentHash: hash,
    publishedAt: '2026-11-13', approvalId }))
  await act(async () => button('确认应用偏好').click())
  expect(fetcher.mock.calls[1][1].body).toBe(fetcher.mock.calls[2][1].body)
  expect(applied).toHaveBeenCalledTimes(1)
})

it('草稿变化后迟到汇总不能归给新草稿，未保存修改不允许汇总', async () => {
  let finish!: (response: Response) => void
  fetcher.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  await mount(); await act(async () => button('汇总当前草稿验收').click())
  await mount({ version: 4 })
  await act(async () => finish(json(ready())))
  expect(button('应用已批准偏好')).toBeNull()
  expect(document.body.textContent).not.toContain('验收规则版本 1')
  await mount({ disabled: true })
  expect(button('汇总当前草稿验收').disabled).toBe(true)
})

it('已展示批准到期后自动关闭应用入口', async () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date('2026-11-13T00:00:00Z'))
  try {
    await mount(); await prepare(summary({ status: 'ready', canApply: true, missingRequirements: [], expiresAt: '2026-11-13T00:00:01Z' }))
    expect(button('应用已批准偏好')).not.toBeNull()
    await act(async () => vi.advanceTimersByTime(1100))
    expect(button('应用已批准偏好')).toBeNull()
    expect(document.body.textContent).toContain('已过期')
  } finally { vi.useRealTimers() }
})

it('草稿改变后迟到应用回执不能刷新新草稿', async () => {
  await mount(); await prepare(); await act(async () => button('应用已批准偏好').click())
  let finish!: (response: Response) => void
  fetcher.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  await act(async () => button('确认应用偏好').click())
  await mount({ version: 4 })
  await act(async () => finish(json({ revision: 5, draftVersion: 3, document: {}, contentHash: hash,
    publishedAt: '2026-11-13', approvalId })))
  expect(applied).not.toHaveBeenCalled()
  expect(document.body.textContent).not.toContain('已应用为偏好版本')
})

it.each(['draft', 'contract', 'executor'])('服务器%s绑定不符时不展示应用批准', async mismatch => {
  await mount()
  const value = ready()
  if (mismatch === 'draft') value.draft.contentHash = 'f'.repeat(64)
  if (mismatch === 'contract') value.contractHash = 'f'.repeat(64)
  if (mismatch === 'executor') value.executorManifestHash = 'f'.repeat(64)
  await prepare(value)
  expect(button('应用已批准偏好')).toBeNull()
  expect(document.body.textContent).toContain('汇总响应与当前草稿')
})

it('按要求类别与待验证项分别计数，同类多个场景不冒充多个功能', async () => {
  const gaps = [
    { requirementId: 'slides-native-content-and-style', reason: 'coverage_missing', format: 'pptx', scenario: 'native_table_style', message: '表格视觉仍需验证。', missingDimensions: ['visual'] },
    { requirementId: 'slides-native-content-and-style', reason: 'coverage_missing', format: 'pptx', path: 'pptx.tables.borders', message: '边框字段仍需验证。', missingDimensions: ['native'] },
    { requirementId: 'template-binding-and-precedence', reason: 'implementation_missing', message: '模板落点尚未完成。', missingDimensions: [] },
  ]
  await mount(); await prepare(summary({ missingRequirements: gaps }))
  expect(document.querySelector('details > summary')?.textContent).toBe('查看 2 类要求的 3 项待验证项')
  expect(document.body.textContent).toContain('验收规则版本 1')
  expect(document.body.textContent).not.toContain('3 项未完成要求')
  expect([...document.querySelectorAll('details li')].map(item => item.textContent)).toEqual([
    expect.stringContaining('表格视觉仍需验证'), expect.stringContaining('边框字段仍需验证'), expect.stringContaining('模板落点尚未完成'),
  ])
  expect(document.querySelector<HTMLDetailsElement>('details')?.open).toBe(false)
})
