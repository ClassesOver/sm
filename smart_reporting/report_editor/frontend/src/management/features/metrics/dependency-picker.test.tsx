import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MetricDependencyPicker } from './dependency-picker'

let root: Root, client: QueryClient
const fetcher = vi.fn(), changed = vi.fn(), ready = vi.fn()
const scope = { database: 'warehouse', companyId: 'a' }
const response = (value: unknown) => new Response(JSON.stringify(value))
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('fetch', fetcher)
  fetcher.mockImplementation(async (path: string) => path.includes('/metrics?')
    ? response({ items: [{ metricId: path.includes('after=') ? 'budget' : 'actual', name: '预算额', publishedRevision: 2 }], nextCursor: path.includes('after=') ? null : 'actual' })
    : response({ published: { revision: 1, document: { id: 'actual', name: '预算额', unit: 'CNY', grain: ['project'] } }, retirement: null }))
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); vi.unstubAllGlobals(); fetcher.mockReset(); changed.mockReset(); ready.mockReset() })
async function until(check: () => void) {
  for (let i = 0; i < 60; i++) { await act(async () => { await new Promise(resolve => setTimeout(resolve, 15)) }); try { check(); return } catch {} } check()
}
const button = (name: string) => [...document.querySelectorAll('button')].find(item => item.textContent?.replaceAll(' ', '').includes(name))!
async function click(name: string) { await act(async () => button(name).click()) }
async function mount(value: { metricId: string; revision: number } | null = null) {
  await act(async () => root.render(<QueryClientProvider client={client}><MetricDependencyPicker scope={scope} label="分子" value={value} disabled={false} onChange={changed} onAvailabilityChange={ready} /></QueryClientProvider>))
}
it('lists scoped published candidates with identity, pages without choosing a latest version', async () => {
  await mount(); expect(fetcher).not.toHaveBeenCalled()
  await click('选择分子指标'); await until(() => expect(document.body.textContent).toContain('预算额 · actual'))
  await click('加载更多候选'); await until(() => expect(document.body.textContent).toContain('预算额 · budget'))
  await click('选择预算额·budget')
  expect(changed).toHaveBeenLastCalledWith({ metricId: 'budget', revision: 0 })
  expect(fetcher.mock.calls.every(([path]) => path.includes('companyId=a'))).toBe(true)
  expect(document.body.textContent).toContain('请明确选择发布版本')
})
it('reads the selected exact revision and reports its unit and grain without changing selection', async () => {
  await mount({ metricId: 'actual', revision: 1 })
  await until(() => expect(ready).toHaveBeenLastCalledWith(true))
  expect(fetcher.mock.calls[0][0]).toContain('revision=1')
  expect(document.body.textContent).toContain('CNY')
  expect(document.body.textContent).toContain('project')
  expect(changed).not.toHaveBeenCalled()
})
it('keeps a retired selection visible but unavailable without auto replacement', async () => {
  fetcher.mockImplementation(async () => response({ published: { revision: 1, document: { id: 'actual', name: '预算额', unit: 'CNY', grain: ['project'] } }, retirement: { reason: '原版本重复', replacement: { metricId: 'actual', revision: 2 } } }))
  await mount({ metricId: 'actual', revision: 1 })
  await until(() => expect(document.body.textContent).toContain('原版本重复'))
  expect(ready).toHaveBeenLastCalledWith(false); expect(changed).not.toHaveBeenCalled()
})
it('rejects another metric identity returned for the selected exact reference', async () => {
  fetcher.mockImplementation(async () => response({ published: { revision: 1, document: { id: 'budget', name: '预算额', unit: 'CNY', grain: ['project'] } }, retirement: null }))
  await mount({ metricId: 'actual', revision: 1 })
  await until(() => expect(document.body.textContent).toContain('依赖指标身份不一致'))
  expect(ready).toHaveBeenLastCalledWith(false); expect(changed).not.toHaveBeenCalled()
})
