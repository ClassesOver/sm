import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MetricRetirement } from './retirement'

let root: Root, client: QueryClient, retired: unknown
const fetcher = vi.fn(), scope = { database: 'warehouse', companyId: 'a' }
const response = (body: unknown) => new Response(JSON.stringify(body))
beforeEach(() => {
  retired = null; sessionStorage.clear(); Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('fetch', fetcher)
  fetcher.mockImplementation(async (_path: string, init?: RequestInit) => {
    if (init?.method === 'POST') { retired = { assetType: 'metric', assetId: 'budget', revision: 1,
      reason: JSON.parse(String(init.body)).reason, replacement: JSON.parse(String(init.body)).replacement }; return response(retired) }
    if (_path.includes('/metrics?')) return response({ items: [{ metricId: 'budget', name: '预算额', publishedRevision: 2 }], nextCursor: null })
    if (_path.includes('revision=2')) return response({ published: { revision: 2, contentHash: 'hash-2' }, retirement: null })
    return response({ published: { revision: 1, contentHash: 'hash-1' }, retirement: retired })
  })
  client = new QueryClient(); document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); vi.unstubAllGlobals(); fetcher.mockReset() })
async function until(check: () => void) {
  for (let i = 0; i < 70; i++) { await act(async () => { await new Promise(resolve => setTimeout(resolve, 15)) }); try { check(); return } catch {} } check()
}
const button = (name: string) => [...document.querySelectorAll('button')].find(item => item.textContent?.replaceAll(' ', '').includes(name))!
async function click(name: string) { await act(async () => button(name).click()) }
async function mount(impactReady = true) {
  await act(async () => root.render(<QueryClientProvider client={client}><MetricRetirement scope={scope} metricId="budget" revision={1}
    contentHash="hash-1" username="admin" csrf="csrf" impactReady={impactReady} retired={false} /></QueryClientProvider>))
}
async function fill() {
  const field = document.querySelector<HTMLTextAreaElement>('[aria-label="指标退役原因"]')!
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, '原指标重复计入，停止新选用。'); field.dispatchEvent(new Event('input', { bubbles: true })) })
  await act(async () => document.querySelector<HTMLInputElement>('[aria-label="确认指标退役影响"]')!.click())
}
it('requires complete impact and explicit reason and acknowledgement', async () => {
  await mount(false); await fill(); expect(button('确认退役指标版本').disabled).toBe(true)
  await mount(); await click('确认退役指标版本')
  await until(() => expect(document.body.textContent).toContain('指标退役已登记'))
  expect(JSON.parse(String(fetcher.mock.calls.find(([, init]) => init?.method === 'POST')![1].body))).toEqual({
    scopeDatabase: 'warehouse', companyId: 'a', reason: '原指标重复计入，停止新选用。', replacement: null })
})
it('recovers committed response loss after remount with GET only', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => { const result = await handler(path, init); if (init?.method === 'POST') throw Error('lost'); return result })
  await mount(); await fill(); await click('确认退役指标版本')
  await until(() => expect(document.body.textContent).toContain('指标退役结果待确认'))
  await act(async () => root.unmount()); root = createRoot(document.getElementById('root')!); await mount()
  await click('读取原指标退役结果'); await until(() => expect(document.body.textContent).toContain('已确认原指标退役登记'))
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  expect(fetcher.mock.calls.some(([path]) => path.includes('revision=1'))).toBe(true)
})
it('blocks writes on malformed pending cache', async () => {
  sessionStorage.setItem('management-metric-retirement:' + JSON.stringify(['admin', 'warehouse', 'a', 'budget', 1]), '{broken')
  await mount(); expect(document.body.textContent).toContain('指标退役缓存无法读取'); expect(button('确认退役指标版本').disabled).toBe(true)
})
it('does not POST when storage fails', async () => {
  await mount(); await fill(); const setter = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('disabled') })
  await click('确认退役指标版本'); expect(fetcher.mock.calls).toHaveLength(0); setter.mockRestore()
})

it('keeps a conflicting retirement without claiming the original request succeeded', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === 'POST') { retired = { assetType: 'metric', assetId: 'budget', revision: 1, reason: '另一原因', replacement: null }; throw Error('lost') }
    return handler(path, init)
  })
  await mount(); await fill(); await click('确认退役指标版本'); await click('读取原指标退役结果')
  await until(() => expect(document.body.textContent).toContain('退役记录与原输入不同'))
  expect(sessionStorage.length).toBe(1); expect(button('确认退役指标版本').disabled).toBe(true)
})

it('requires fresh acknowledgement before explicitly retrying an uncommitted identical request', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => { if (init?.method === 'POST') throw Error('not committed'); return handler(path, init) })
  await mount(); await fill(); await click('确认退役指标版本'); await click('读取原指标退役结果')
  await until(() => expect(document.body.textContent).toContain('此精确版本尚未退役'))
  expect(button('确认重提原指标退役').disabled).toBe(true)
  await act(async () => document.querySelector<HTMLInputElement>('[aria-label="确认指标退役影响"]')!.click())
  fetcher.mockImplementation(handler); await click('确认重提原指标退役')
  await until(() => expect(document.body.textContent).toContain('指标退役已登记'))
  const posts = fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(posts).toHaveLength(2); expect(posts[0][1].body).toBe(posts[1][1].body)
})

async function choose(version: string) {
  await act(async () => document.querySelector<HTMLInputElement>('[aria-label="登记替代指标版本"]')!.click())
  await until(() => expect(button('选择预算额')).toBeTruthy()); await click('选择预算额')
  await act(async () => document.querySelector('[aria-label="替代指标发布版本"]')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })))
  await until(() => expect(document.querySelector('.ant-select-item-option-content')).toBeTruthy())
  await act(async () => [...document.querySelectorAll<HTMLElement>('.ant-select-item-option-content')].find(item => item.textContent === version)!.click())
}
it('preserves an explicitly selected replacement through unknown response recovery', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => { const result = await handler(path, init); if (init?.method === 'POST') throw Error('lost'); return result })
  await mount(); await choose('版本 2'); await fill()
  await until(() => expect(button('确认退役指标版本').disabled).toBe(false)); await click('确认退役指标版本')
  await until(() => expect(document.body.textContent).toContain('指标退役结果待确认'))
  await act(async () => root.unmount()); root = createRoot(document.getElementById('root')!); await mount()
  await click('读取原指标退役结果'); await until(() => expect(document.body.textContent).toContain('已确认原指标退役登记'))
  const posts = fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(posts).toHaveLength(1); expect(JSON.parse(String(posts[0][1].body)).replacement).toEqual({ metricId: 'budget', revision: 2 })
})
it('does not allow the same metric version as its own replacement', async () => {
  await mount(); await choose('版本 1'); await fill()
  await until(() => expect(document.body.textContent).toContain('替代指标不能指向自身版本'))
  expect(button('确认退役指标版本').disabled).toBe(true)
})

it('blocks an already retired replacement', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => path.includes('revision=2') ? response({ published: { revision: 2, contentHash: 'hash-2' },
    retirement: { assetType: 'metric', assetId: 'budget', revision: 2, reason: '已退役', replacement: null } }) : handler(path, init))
  await mount(); await choose('版本 2'); await fill()
  await until(() => expect(document.body.textContent).toContain('替代指标版本已退役'))
  expect(button('确认退役指标版本').disabled).toBe(true)
})

it('does not claim a readback with a different replacement', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === 'POST') { await handler(path, init); (retired as { replacement: unknown }).replacement = null; throw Error('lost') }
    return handler(path, init)
  })
  await mount(); await choose('版本 2'); await fill(); await until(() => expect(button('确认退役指标版本').disabled).toBe(false))
  await click('确认退役指标版本'); await click('读取原指标退役结果')
  await until(() => expect(document.body.textContent).toContain('退役记录与原输入不同'))
  expect(sessionStorage.length).toBe(1)
})

it('retains the original input before reselecting a replacement retired after an uncommitted attempt', async () => {
  const handler = fetcher.getMockImplementation()!
  let later = false
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === 'POST') { later = true; throw Error('not committed') }
    if (later && path.includes('revision=2')) return response({ published: { revision: 2, contentHash: 'hash-2' },
      retirement: { assetType: 'metric', assetId: 'budget', revision: 2, reason: '后来退役', replacement: null } })
    return handler(path, init)
  })
  await mount(); await choose('版本 2'); await fill(); await until(() => expect(button('确认退役指标版本').disabled).toBe(false))
  await click('确认退役指标版本'); await click('读取原指标退役结果')
  await until(() => expect(document.body.textContent).toContain('原替代指标版本已不可用'))
  await click('保留原请求并重选替代指标')
  const key = 'management-metric-retirement:' + JSON.stringify(['admin', 'warehouse', 'a', 'budget', 1])
  expect(sessionStorage.getItem(key)).toBeNull()
  expect(JSON.parse(sessionStorage.getItem(key + ':prior')!)[0].replacement).toEqual({ metricId: 'budget', revision: 2 })
  expect(button('确认退役指标版本').disabled).toBe(true)
})
