import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MetricVersionDetails } from './detail'

let root: Root, client: QueryClient
const fetcher = vi.fn()
const scope = { database: 'warehouse', companyId: 'a' }
const response = (body: unknown) => new Response(JSON.stringify(body))
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('fetch', fetcher)
  fetcher.mockImplementation(async (path: string) => path.includes('/impact?') ? response({ metricVersion: { metricId: 'rate', revision: 1 },
    items: [{ kind: 'policy', referenceId: 'monthly', name: '月度分析口径', revision: 1, basisId: null, policyVersion: { policyId: 'monthly', revision: 1 } }], nextCursor: 'policy:monthly:1' })
    : response({ published: { revision: 1, contentHash: 'hash-1', document: { name: '执行率', kind: 'ratio', unit: '%', grain: ['project'],
      numeratorVersion: { metricId: 'actual', revision: 2 }, denominatorVersion: { metricId: 'budget', revision: 1 },
      aggregationPolicy: { observationKind: 'flow', timeAggregation: 'sum' } } }, retirement: { reason: '旧版本错误', replacement: { metricId: 'rate', revision: 2 } } }))
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); vi.unstubAllGlobals(); fetcher.mockReset() })
async function until(check: () => void) {
  for (let i = 0; i < 70; i++) { await act(async () => { await new Promise(resolve => setTimeout(resolve, 15)) }); try { check(); return } catch {} }
  check()
}
async function mount() {
  await act(async () => root.render(<QueryClientProvider client={client}><MetricVersionDetails scope={scope} metricId="rate" revision={1} /></QueryClientProvider>))
}
it('shows exact formula references and retirement without replacing the historical metric', async () => {
  await mount(); await until(() => expect(document.body.textContent).toContain('月度分析口径'))
  expect(document.body.textContent).toContain('actual · 版本 2')
  expect(document.body.textContent).toContain('budget · 版本 1')
  expect(document.body.textContent).toContain('旧版本错误')
  expect(document.body.textContent).toContain('替代建议：rate · 版本 2')
  expect(document.querySelector('[aria-label="指标影响明细，可滚动"]')?.getAttribute('tabindex')).toBe('0')
  expect(fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true)
})
it('loads impact pages for the selected exact version only', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init: RequestInit) => path.includes('after=') ? response({ metricVersion: { metricId: 'rate', revision: 1 },
    items: [{ kind: 'report', referenceId: 'old-run', name: 'old-run', revision: null, basisId: 'basis-old', policyVersion: { policyId: 'monthly', revision: 1 } }], nextCursor: null }) : handler(path, init))
  await mount(); await until(() => expect(document.body.textContent).toContain('月度分析口径'))
  await act(async () => [...document.querySelectorAll('button')].find(item => item.textContent?.includes('加载更多影响'))!.click())
  await until(() => expect(document.body.textContent).toContain('old-run'))
  expect(fetcher.mock.calls.filter(([path]) => path.includes('/impact?')).every(([path]) => path.includes('revision=1'))).toBe(true)
})
it('rejects an impact response for a different metric version', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init: RequestInit) => path.includes('/impact?')
    ? response({ metricVersion: { metricId: 'rate', revision: 2 }, items: [], nextCursor: null }) : handler(path, init))
  await mount(); await until(() => expect(document.body.textContent).toContain('影响响应与当前指标版本不一致'))
})
